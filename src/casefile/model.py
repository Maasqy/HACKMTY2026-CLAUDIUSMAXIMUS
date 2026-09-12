"""Data model for the case file.

Owns the shapes shared by the loader, trail builder, and both renderers.
Also holds the default text for the Method-and-limits section — small enough
to live here instead of a separate module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

SchemeType = Literal[
    "phantom_vendor",
    "kickback",
    "round_tripping",
    "threshold_splitting",
    "revenue_inflation",
]
Confidence = Literal["proven", "probable"]
ClosedBy = Literal["investigator", "challenger", "validator"]
PeriodSource = Literal["flag", "derived", "default"]


@dataclass(frozen=True)
class Header:
    company_name: str
    company_rfc: Optional[str]
    audit_period: str
    period_source: PeriodSource
    seed: int
    deterministic: bool
    llm_calls: int
    mxn_cost: float
    wall_clock_seconds: float


@dataclass(frozen=True)
class Exhibit:
    exhibit_id: str
    source_table: str
    record_id: str
    note: str


@dataclass(frozen=True)
class TrailStep:
    from_entity: str
    to_entity: str
    amount: float
    date: str
    exhibit_id: str


@dataclass(frozen=True)
class AdversarialReview:
    """Optional per-finding block.

    Carril C populates this when the challenger attacks a finding and the
    accusation survives. The renderer omits the section entirely when absent
    (no placeholder, no empty heading).
    """

    challenged: str
    survived_because: str
    reviewer: str


@dataclass(frozen=True)
class Node:
    node_id: str
    label_primary: str
    label_secondary: Optional[str]
    kind: Literal["vendor", "company", "employee", "clabe", "unknown"]


@dataclass(frozen=True)
class Edge:
    from_id: str
    to_id: str
    amount: float
    label: str
    style: Literal["solid", "dashed"]


@dataclass(frozen=True)
class MoneyGraph:
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    empty_reason: Optional[str]


@dataclass(frozen=True)
class Reconciliation:
    peso_amount: float
    per_table: tuple[tuple[str, float, int], ...]  # (table, sum, count) sorted by table
    best_match_table: Optional[str]
    delta_pct: Optional[float]  # signed (claimed - best_sum) / claimed


@dataclass(frozen=True)
class Finding:
    index: int  # 1-based, submission order
    scheme_type: str
    entities: tuple[str, ...]
    narrative: str
    rule_broken: str
    peso_amount: float
    confidence: str
    exhibits: tuple[Exhibit, ...]
    trail_steps: tuple[TrailStep, ...]
    trail_graph: MoneyGraph
    reconciliation: Reconciliation
    adversarial_review: Optional[AdversarialReview]


@dataclass(frozen=True)
class Lead:
    entity: str
    signal: str
    reason: str
    tool_calls_made: tuple[str, ...]
    closed_by: Optional[str]


@dataclass(frozen=True)
class Summary:
    findings_total: int
    findings_by_confidence: tuple[tuple[str, int], ...]  # sorted by label
    total_exposure: float
    leads_investigated: int


@dataclass(frozen=True)
class MethodLimits:
    architecture: str
    out_of_scope: tuple[str, ...]
    cannot_detect: tuple[str, ...]
    reproducibility: str


@dataclass(frozen=True)
class CaseFile:
    header: Header
    summary: Summary
    findings: tuple[Finding, ...]
    leads_not_pursued: tuple[Lead, ...]
    method: MethodLimits


DEFAULT_METHOD = MethodLimits(
    architecture=(
        "Detectores deterministas producen leads, un investigador con herramientas "
        "tipadas sobre el estate arma la evidencia, y un validador de código bloquea "
        "toda acusación que no reconcilie por pesos, no cite al menos tres exhibits "
        "reales, o carezca de regla concreta violada."
    ),
    out_of_scope=(
        "Detección de fraude fuera de los libros entregados (correos, chats, hardware).",
        "Reclasificación contable o valoración de impacto fiscal.",
        "Cruces con fuentes externas en vivo distintas al listado 69-B provisto.",
    ),
    cannot_detect=(
        "Esquemas cuya evidencia vive únicamente fuera del estate.",
        "Colusión perfectamente balanceada sin rastro documental en ninguna de las "
        "ocho tablas.",
        "Fraude por omisión: transacciones que debieron existir y nunca se registraron.",
    ),
    reproducibility=(
        "Misma semilla y mismo estate producen bytes idénticos de submission.json y "
        "case_file. Toda llamada al modelo pasa por caché en disco; el sistema corre "
        "con conectividad apagada. Comando: "
        "`python3 -m src.run --estate <ruta> --out submission.json` "
        "seguido de `python3 -m src.casefile --submission submission.json`."
    ),
)
