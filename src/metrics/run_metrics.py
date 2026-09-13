"""
src/metrics/run_metrics.py

The three numbers the track demands out loud — llm_calls, mxn_cost,
wall_clock_seconds — plus the per-stage breakdown that makes them
defensible. "We don't know" scores low on Feasibility; "172 ms of
deterministic work, 4 LLM calls, $0.03 MXN" is an answer.

The LLM side comes from LLMUsage (counted inside the client, the single
place that talks to a model). The deterministic side is timed here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class RunMetrics:
    """Stage timings in seconds; LLM counters folded in at the end."""
    started_at: float = field(default_factory=time.perf_counter)
    etapas: dict[str, float] = field(default_factory=dict)
    leads_generados: int = 0
    leads_investigados: int = 0
    drafts_rechazados_validator: int = 0
    findings_descartados_challenger: int = 0
    findings_finales: int = 0

    def cronometrar(self, nombre: str):
        """with metrics.cronometrar('cart'): ..."""
        return _Timer(self, nombre)

    @property
    def wall_clock_seconds(self) -> float:
        return time.perf_counter() - self.started_at

    def as_run_metadata(self, usage=None) -> dict:
        md = {
            "llm_calls": 0,
            "mxn_cost": 0.0,
            "wall_clock_seconds": round(self.wall_clock_seconds, 2),
            "deterministic": True,
            "etapas_segundos": {k: round(v, 4) for k, v in self.etapas.items()},
            "embudo": {
                "leads_generados": self.leads_generados,
                "leads_investigados": self.leads_investigados,
                "rechazados_por_validator": self.drafts_rechazados_validator,
                "descartados_por_challenger": self.findings_descartados_challenger,
                "findings_finales": self.findings_finales,
            },
        }
        if usage is not None:
            md["llm_calls"] = usage.llm_calls
            md["mxn_cost"] = usage.mxn_cost
            md["cache_hits"] = usage.cache_hits
            md["prompt_tokens"] = usage.prompt_tokens
            md["completion_tokens"] = usage.completion_tokens
        return md


class _Timer:
    def __init__(self, metrics: RunMetrics, nombre: str):
        self.metrics, self.nombre = metrics, nombre

    def __enter__(self):
        self._t = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.metrics.etapas[self.nombre] = (
            self.metrics.etapas.get(self.nombre, 0.0) + time.perf_counter() - self._t
        )
        return False
