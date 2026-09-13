"""Identifica el RFC y la CLABE de la empresa auditada.

Doble derivacion cruzada: la empresa es quien paga (from_clabe dominante en
bank_txns) y a quien le facturan (receiver_rfc dominante en invoices). Si las
dos derivaciones no convergen con margen amplio, o si el candidato aparece
como vendor/employee registrado (una empresa no se compra a si misma), se lanza
CompanyDerivationConflict y run.py pide --company-rfc.

La regla de "excluir revenue_inflation" del prompt sale gratis con estos dos
gates: aunque la empresa tambien emite facturas, no domina como emisora, y su
RFC no aparece en vendors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.tools.estate_access import EstateDB

_DOMINANCE_RATIO = 5.0


class CompanyDerivationConflict(RuntimeError):
    """Se lanza cuando la derivacion no es concluyente y se necesita --company-rfc."""


@dataclass(frozen=True, slots=True)
class CompanyIdentity:
    rfc: str
    clabe: str
    evidence: str


def derive_company(db: EstateDB, rfc_override: Optional[str] = None) -> CompanyIdentity:
    top_r = _top_receiver_rfc(db)
    top_c = _top_from_clabe(db)

    rfc = rfc_override or _pick_rfc(top_r, db)
    clabe = _pick_clabe(top_c, db)

    return CompanyIdentity(
        rfc=rfc,
        clabe=clabe,
        evidence=_format_evidence(top_r, top_c, rfc, clabe, rfc_override is not None),
    )


def _top_receiver_rfc(db: EstateDB) -> list[tuple[str, int]]:
    rows = db._query(
        "SELECT receiver_rfc AS r, COUNT(*) AS n FROM invoices "
        "WHERE receiver_rfc IS NOT NULL AND receiver_rfc != '' "
        "GROUP BY receiver_rfc ORDER BY n DESC, receiver_rfc ASC LIMIT 5"
    )
    return [(r["r"], int(r["n"])) for r in rows]


def _pick_rfc(top: list[tuple[str, int]], db: EstateDB) -> str:
    if not top:
        raise CompanyDerivationConflict("invoices vacia; no se puede derivar receiver_rfc")
    first_rfc, first_n = top[0]
    second_n = top[1][1] if len(top) > 1 else 0
    if second_n > 0 and first_n / second_n < _DOMINANCE_RATIO:
        raise CompanyDerivationConflict(
            f"receiver_rfc no dominante: top={first_rfc} ({first_n}) vs segundo ({second_n}); "
            f"ratio {first_n / second_n:.2f} < {_DOMINANCE_RATIO}. Pasa --company-rfc explicito."
        )
    if db.obtener_proveedor(first_rfc) is not None:
        raise CompanyDerivationConflict(
            f"top receiver_rfc {first_rfc} esta registrado en vendors; "
            f"una empresa no se compra a si misma. Pasa --company-rfc explicito."
        )
    return first_rfc


def _top_from_clabe(db: EstateDB) -> list[tuple[str, float, int]]:
    rows = db._query(
        "SELECT from_clabe AS c, SUM(amount) AS s, COUNT(*) AS n FROM bank_txns "
        "WHERE from_clabe IS NOT NULL AND from_clabe != '' "
        "GROUP BY from_clabe ORDER BY s DESC, from_clabe ASC LIMIT 5"
    )
    return [(r["c"], float(r["s"] or 0), int(r["n"])) for r in rows]


def _pick_clabe(top: list[tuple[str, float, int]], db: EstateDB) -> str:
    if not top:
        raise CompanyDerivationConflict("bank_txns vacia; no se puede derivar from_clabe")
    first_clabe, first_s, _ = top[0]
    second_s = top[1][1] if len(top) > 1 else 0.0
    if second_s > 0 and first_s / second_s < _DOMINANCE_RATIO:
        raise CompanyDerivationConflict(
            f"from_clabe no dominante: {first_clabe} suma {first_s:,.2f} vs "
            f"segundo {second_s:,.2f}; ratio {first_s / second_s:.2f} < {_DOMINANCE_RATIO}."
        )
    owner = db.resolver_clabe(first_clabe)
    if owner.owner_type in {"vendor", "employee"}:
        raise CompanyDerivationConflict(
            f"top from_clabe {first_clabe} pertenece a {owner.owner_type} "
            f"registrado ({owner.owner_id}); no puede ser la empresa auditada."
        )
    return first_clabe


def _format_evidence(
    top_r: list[tuple[str, int]],
    top_c: list[tuple[str, float, int]],
    rfc: str,
    clabe: str,
    override: bool,
) -> str:
    r_lines = ", ".join(f"{r}={n}" for r, n in top_r[:3])
    c_lines = ", ".join(f"{c[:8]}...={s:,.0f}" for c, s, _ in top_c[:3])
    tag = "override" if override else "derivada"
    return (
        f"empresa {tag}: RFC={rfc} CLABE={clabe} | "
        f"top receiver_rfc [{r_lines}] | top from_clabe (sum) [{c_lines}]"
    )
