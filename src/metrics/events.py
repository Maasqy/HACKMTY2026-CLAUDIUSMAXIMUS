"""Emisor de events.jsonl. Es el guion de la demo.

Cada linea es un JSON con {seq, t, type, entity, payload}. Line-buffered:
si la corrida se cae, el archivo queda con todo hasta el ultimo evento.

Tipos cerrados (PLAN-10H seccion 6):
  run_started, lead_opened, hypothesis, tool_call, evidence,
  challenge, lead_closed, finding, metrics, run_finished
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, IO


_ALLOWED_TYPES = frozenset({
    "run_started", "lead_opened", "hypothesis", "tool_call", "evidence",
    "challenge", "lead_closed", "finding", "metrics", "run_finished",
})


class EventEmitter:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh: IO[str] = self.path.open(
            "w", encoding="utf-8", buffering=1, newline="\n"
        )
        self._seq = 0
        self._t0 = time.monotonic()

    def emit(self, type_: str, entity: str, payload: dict[str, Any]) -> None:
        if type_ not in _ALLOWED_TYPES:
            raise ValueError(f"tipo de evento invalido: {type_!r}")
        self._seq += 1
        event = {
            "seq": self._seq,
            "t": round(time.monotonic() - self._t0, 3),
            "type": type_,
            "entity": entity,
            "payload": payload,
        }
        self._fh.write(json.dumps(event, ensure_ascii=True, sort_keys=False))
        self._fh.write("\n")
        self._fh.flush()

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()

    def __enter__(self) -> "EventEmitter":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


class NullEmitter:
    """No-op para pruebas o runs sin trazabilidad."""

    def emit(self, type_: str, entity: str, payload: dict[str, Any]) -> None:
        return

    def close(self) -> None:
        return

    def __enter__(self) -> "NullEmitter":
        return self

    def __exit__(self, *exc: Any) -> None:
        return
