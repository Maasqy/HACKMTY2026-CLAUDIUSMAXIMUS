"""Registry de detectores.

Corre en orden alfabetico por detector_id para que la salida sea determinista.
Agregar un detector nuevo: importarlo abajo y anadirlo a _REGISTRY.
"""

from __future__ import annotations

from src.detectors.base import Lead
from src.detectors import (
    efos_match,
    kickback,
    payment_wo_inv,
    round_tripping,
    threshold_splitting,
)
from src.forensic.company import CompanyIdentity
from src.tools.estate_access import EstateDB

_REGISTRY = [efos_match, kickback, payment_wo_inv, round_tripping, threshold_splitting]


def run_all(db: EstateDB, company: CompanyIdentity) -> list[Lead]:
    leads: list[Lead] = []
    for module in sorted(_REGISTRY, key=lambda m: m.DETECTOR_ID):
        leads.extend(module.find_leads(db, company))
    return sorted(leads, key=lambda l: (l.detector_id, l.entity, l.signal))


__all__ = ["Lead", "run_all"]
