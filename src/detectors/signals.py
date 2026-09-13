"""
src/detectors/signals.py

Signal: the deterministic, rule-based unit of evidence a detector in
rules.py emits. A Signal is NOT an accusation — src/scoring turns Signals
(deterministic) plus the ML model's situacion_sat prediction into a Lead,
and only the investigator/challenger/validator (LLM) loop turns a Lead into
either a Finding or a leads_not_pursued entry in the final submission.

Every field maps directly onto something submission_schema.json needs later,
so nothing has to be re-derived downstream:
  - entity        the "entities" id format (RFC:xxx / EMP:xxx)
  - scheme_hint   one of the fixed submission_schema.json scheme_type enum
                  values, or None for a general documentary/process signal
                  not tied to one specific scheme
  - evidence      Exhibit tuples, ready to drop straight into a Finding's
                  `exhibits` array (source_table/record_id/note)
  - strength      0..1, this detector's OWN confidence in its own rule —
                  not a calibrated probability. Several strengths get
                  averaged in src/scoring, they are not meant to be read
                  in isolation as "% chance of fraud".

Nothing in this package imports eval/ or references the evaluation answer
key — detectors are pure functions of src.tools.EstateDB.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.config import SCHEME_TYPES  # single source of truth for the enum

SOURCE_TABLES = (
    "ledger",
    "invoices",
    "bank_txns",
    "vendors",
    "efos_list",
    "purchase_orders",
    "contracts",
    "employees",
)


@dataclass(frozen=True, slots=True)
class Exhibit:
    exhibit_id: str
    source_table: str
    record_id: str
    note: str

    def __post_init__(self):
        if self.source_table not in SOURCE_TABLES:
            raise ValueError(f"source_table invalido: {self.source_table!r}")


@dataclass(frozen=True, slots=True)
class Signal:
    entity: str
    detector: str
    scheme_hint: str | None
    strength: float
    description: str
    evidence: tuple[Exhibit, ...] = field(default_factory=tuple)

    def __post_init__(self):
        if self.scheme_hint is not None and self.scheme_hint not in SCHEME_TYPES:
            raise ValueError(f"scheme_hint invalido: {self.scheme_hint!r}")
        if not (0.0 <= self.strength <= 1.0):
            raise ValueError(f"strength fuera de rango [0,1]: {self.strength}")
