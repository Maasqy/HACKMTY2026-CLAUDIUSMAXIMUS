"""Los tres numeros que el reto exige en run_metadata.

Determinismo:
  El baseline zero-LLM garantiza que findings, leads y exhibits son bit-a-bit
  identicos entre corridas de la misma seed. wall_clock_seconds se mide honesto
  y por naturaleza varia entre corridas.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class RunMetrics:
    llm_calls: int = 0
    mxn_cost: float = 0.0
    _started: float = 0.0
    _wall_clock: float = 0.0

    def start(self) -> None:
        self._started = time.monotonic()

    def stop(self) -> None:
        self._wall_clock = time.monotonic() - self._started

    def as_dict(self) -> dict:
        return {
            "llm_calls": self.llm_calls,
            "mxn_cost": round(self.mxn_cost, 2),
            "wall_clock_seconds": round(self._wall_clock, 2),
            "cost_by_role": {},
            "deterministic": True,
        }
