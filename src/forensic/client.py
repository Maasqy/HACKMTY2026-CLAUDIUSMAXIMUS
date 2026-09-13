"""
src/forensic/client.py

The one place this project talks to an LLM. Everything downstream — the
investigator (etapa 3), the challenger (etapa 5) — goes through this client,
so the three numbers the spec demands (llm_calls, mxn_cost,
wall_clock_seconds) are counted in exactly one place and cannot drift.

Design constraints this file exists to satisfy, all of them from the
track's own rules rather than from taste:

  Determinism. "Same seed -> same case file." A sampling LLM breaks that
  outright, so every request pins temperature 0 and a fixed seed, and every
  response is cached on disk keyed by a hash of the exact request. Re-running
  the same estate replays from cache instead of re-asking.

  Replay without network. The cache is the mechanism: once a run has been
  recorded, `LLMClient(offline=True)` serves it back with the network never
  touched. A cache miss while offline raises instead of silently degrading —
  a demo that quietly produces different findings because the model was
  unreachable is worse than one that stops and says so.

  Cost accounting. The spec asks for llm_calls and mxn_cost. Both are
  tracked here per call, cache hits included (counted separately, since a
  replayed call costs nothing but still happened).

No dependency on the `ollama` python package: this speaks the HTTP API with
`requests`, which is already available everywhere this runs. Swapping the
backend means changing `_post`, not the investigator.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import requests

from src.config import (
    LLM_BASE_URL,
    LLM_MODEL,
    LLM_NUM_CTX,
    LLM_SEED,
    LLM_TIMEOUT_S,
    MXN_PER_1K_TOKENS,
)

DEFAULT_CACHE_DIR = Path(os.environ.get("FORENSIC_LLM_CACHE", ".llm_cache"))


class LLMUnavailableError(RuntimeError):
    """Raised when the model cannot be reached and the cache cannot answer."""


@dataclass
class LLMUsage:
    """Running totals for this process. Feeds submission.run_metadata."""
    llm_calls: int = 0
    cache_hits: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    wall_clock_seconds: float = 0.0

    @property
    def mxn_cost(self) -> float:
        """Cost of the tokens actually generated (cache hits are free).

        A locally-hosted model has no per-token invoice, so this is an
        imputed cost at MXN_PER_1K_TOKENS — the spec asks for a number and
        "0.00 because it runs on our laptop" answers nothing about whether
        the approach scales. See src/config.py for the rate and its basis.
        """
        total = self.prompt_tokens + self.completion_tokens
        return round(total / 1000.0 * MXN_PER_1K_TOKENS, 4)

    def as_run_metadata(self) -> dict:
        return {
            "llm_calls": self.llm_calls,
            "mxn_cost": self.mxn_cost,
            "wall_clock_seconds": round(self.wall_clock_seconds, 2),
            "cache_hits": self.cache_hits,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
        }


@dataclass
class LLMClient:
    model: str = LLM_MODEL
    base_url: str = LLM_BASE_URL
    seed: int = LLM_SEED
    timeout_s: float = LLM_TIMEOUT_S
    num_ctx: int = LLM_NUM_CTX
    cache_dir: Path = DEFAULT_CACHE_DIR
    offline: bool = False
    usage: LLMUsage = field(default_factory=LLMUsage)

    def __post_init__(self):
        self.cache_dir = Path(self.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # -- cache ---------------------------------------------------------

    def _cache_key(self, payload: dict) -> str:
        """Hash of the EXACT request. Any change to the prompt, the tool
        list, the model or the seed is a different key — a stale cache can
        never silently answer for a prompt it never saw."""
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    # -- transport -----------------------------------------------------

    def _post(self, payload: dict) -> dict:
        url = f"{self.base_url.rstrip('/')}/api/chat"
        try:
            r = requests.post(url, json=payload, timeout=self.timeout_s)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.HTTPError as exc:
            # `raise_for_status()` deja el cuerpo de la respuesta en `r`, no en
            # `exc`. Sin capturarlo aqui, un 400 de Ollama (p. ej. "el modelo
            # no soporta tools") se veia como "400 Client Error: Bad Request"
            # sin decir POR QUE — imposible de diagnosticar desde el mensaje.
            try:
                detalle = r.json().get("error", r.text)
            except ValueError:
                detalle = r.text
            raise LLMUnavailableError(
                f"Ollama respondio {r.status_code} en {url}: {detalle}"
            ) from exc
        except requests.RequestException as exc:
            raise LLMUnavailableError(
                f"No se pudo contactar el modelo en {url}: {exc}. "
                f"Levanta el servidor (ollama serve) o corre con offline=True "
                f"sobre un cache ya poblado."
            ) from exc

    # -- public --------------------------------------------------------

    def chat(self, messages: list[dict], tools: Optional[list[dict]] = None,
            format: Optional[str] = None) -> dict:
        """One turn. Returns the raw message dict from the model, which may
        carry `content`, `tool_calls`, or both.

        Deterministic by construction: temperature 0 and a fixed seed, so
        the same messages produce the same reply and therefore the same
        cache key on the next run.

        `tools` uses Ollama's native tool-calling API — which only a small,
        hardcoded subset of models actually support. Passing it to a model
        outside that list (gemma3, notably) does not degrade gracefully: it
        400s on every call with "does not support tools", which is the
        actual failure mode this project hit. The investigator (etapa 3)
        does not use this parameter for that reason — see
        src/forensic/prompts.py for the model-agnostic alternative (tools
        described in the prompt, calls requested as plain JSON).

        `format="json"` asks Ollama to constrain sampling to syntactically
        valid JSON. Unlike `tools`, this works on every model — it is a
        decoding constraint, not a per-model feature — so it is the
        mechanism actually used here to make replies parseable.

        `num_ctx` is sent explicitly on every call rather than left to
        Ollama's default (4096). A multi-turn tool-calling loop accumulates
        the system prompt, the tool catalog, and every prior tool result
        (up to 6000 characters each, see MAX_TOOL_PAYLOAD) into the same
        context — by turn 5-6 that can fill a 4096 window, leaving the model
        no budget to finish writing its conclusion. The observed failure
        mode was a reply that is valid JSON up to the point it runs out of
        room and just stops (e.g. `...,"record_` with no closing brace),
        which investigator.py's `_parse_json` correctly treats as unparseable
        and retries — burning an extra turn instead of fixing the cause.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0, "seed": self.seed, "num_ctx": self.num_ctx},
        }
        if tools:
            payload["tools"] = tools
        if format:
            payload["format"] = format

        key = self._cache_key(payload)
        cached = self._cache_path(key)

        if cached.exists():
            data = json.loads(cached.read_text(encoding="utf-8"))
            self.usage.llm_calls += 1
            self.usage.cache_hits += 1
            return data["message"]

        if self.offline:
            raise LLMUnavailableError(
                f"offline=True y no hay cache para esta petición (key={key}). "
                f"Corre una vez con red para poblar {self.cache_dir}/ antes de "
                f"replayar sin conexión."
            )

        started = time.perf_counter()
        data = self._post(payload)
        elapsed = time.perf_counter() - started

        self.usage.llm_calls += 1
        self.usage.wall_clock_seconds += elapsed
        self.usage.prompt_tokens += int(data.get("prompt_eval_count", 0) or 0)
        self.usage.completion_tokens += int(data.get("eval_count", 0) or 0)

        cached.write_text(
            json.dumps({"request": payload, "message": data.get("message", {})},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return data.get("message", {})

    def chat_json(self, messages: list[dict], tools: Optional[list[dict]] = None) -> dict:
        """Same as chat(), but parses the reply as JSON.

        Returns {} when the model emits something unparseable rather than
        raising: an investigator that cannot read one reply should drop that
        lead and keep working, not abort the whole run. The caller decides
        what an empty answer means.
        """
        msg = self.chat(messages, tools=tools)
        content = (msg.get("content") or "").strip()
        if not content:
            return {}
        if content.startswith("```"):
            content = content.strip("`")
            content = content.split("\n", 1)[1] if "\n" in content else content
            content = content.rsplit("```", 1)[0] if "```" in content else content
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            start, end = content.find("{"), content.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(content[start:end + 1])
                except json.JSONDecodeError:
                    return {}
            return {}
