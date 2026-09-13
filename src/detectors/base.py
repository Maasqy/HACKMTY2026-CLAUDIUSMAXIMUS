"""Lead: la unidad de trabajo que un detector produce.

Un lead no es una acusacion. Es una senal reproducible en el estate, con los
record_ids que la disparan y un texto legible en espanol. El validador y el
promoter deciden si sube a finding o cae en leads_not_pursued.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Lead:
    detector_id: str
    entity: str                  # p. ej. "RFC:AAAA010101AA1" o "EMP:0007"
    signal: str                  # p. ej. "efos_definitivo"
    reason: str                  # espanol legible, especifico a esta entidad
    suggested_records: tuple[tuple[str, str], ...]  # ((source_table, record_id), ...)
    monto_estimado: float        # 0.0 si el detector no puede estimarlo
    detector_context: tuple[tuple[str, str], ...] = field(default_factory=tuple)
