"""Evidence Gate: rechaza acusaciones que no puedan probarse.

Los siete gates de CLAUDE.md invariant #2, codificados. Ninguna acusacion sale
del sistema sin evidencia auditable.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.config import (
    AMOUNT_TABLES,
    MAX_NARRATIVE_WORDS,
    MIN_EXHIBITS,
    PESO_TOLERANCE,
    STATISTICAL_RULE_BLOCKLIST,
)
from src.tools.estate_access import EstateDB


@dataclass(frozen=True, slots=True)
class Verdict:
    aprobado: bool
    motivo: str


_PK_BY_TABLE = {
    "invoices": "uuid",
    "bank_txns": "txn_id",
    "purchase_orders": "po_id",
    "contracts": "contract_id",
}


def validate(candidate: dict, db: EstateDB) -> Verdict:
    exhibits = candidate.get("exhibits") or []
    if len(exhibits) < MIN_EXHIBITS:
        return Verdict(False, f"solo {len(exhibits)} exhibits; el minimo son {MIN_EXHIBITS}.")

    if not any(ex.get("source_table") in AMOUNT_TABLES for ex in exhibits):
        return Verdict(
            False,
            f"ningun exhibit cita una tabla con monto ({sorted(AMOUNT_TABLES)}); "
            f"la reconciliacion en pesos no es posible.",
        )

    for ex in exhibits:
        tbl, rid = ex.get("source_table", ""), str(ex.get("record_id", ""))
        if not tbl or not rid:
            return Verdict(False, f"exhibit con source_table o record_id vacio: {ex!r}.")
        try:
            existe = db.existe_registro(tbl, rid)
        except ValueError as e:
            return Verdict(False, f"exhibit invalido: {e}")
        if not existe:
            return Verdict(
                False,
                f"exhibit {ex.get('exhibit_id', '?')} cita {tbl}.{rid} pero ese "
                f"registro no existe en el estate.",
            )

    claimed = float(candidate.get("peso_amount") or 0.0)
    if claimed <= 0:
        return Verdict(False, f"peso_amount no positivo: {claimed}.")
    per_table = _sum_per_table(exhibits, db)
    if not per_table:
        return Verdict(False, "no se pudo sumar monto de ninguna tabla citada.")
    best = min(per_table.values(), key=lambda v: abs(claimed - v))
    if abs(claimed - best) > PESO_TOLERANCE * max(best, 1.0):
        detail = ", ".join(f"{t}={v:,.2f}" for t, v in sorted(per_table.items()))
        return Verdict(
            False,
            f"peso_amount {claimed:,.2f} no reconcilia con ninguna tabla citada "
            f"[{detail}] dentro del {PESO_TOLERANCE * 100:.0f}%.",
        )

    rule = str(candidate.get("rule_broken") or "").strip()
    if not rule:
        return Verdict(False, "rule_broken vacio.")
    rule_lc = rule.lower()
    hit = next((k for k in STATISTICAL_RULE_BLOCKLIST if k in rule_lc), None)
    if hit is not None:
        return Verdict(
            False,
            f"rule_broken describe un patron estadistico ({hit!r}); debe nombrar "
            f"una regla o articulo concreto.",
        )

    narrative = str(candidate.get("narrative") or "").strip()
    if not narrative:
        return Verdict(False, "narrative vacia.")
    words = len(narrative.split())
    if words > MAX_NARRATIVE_WORDS:
        return Verdict(
            False, f"narrative de {words} palabras; el maximo son {MAX_NARRATIVE_WORDS}."
        )

    entities = candidate.get("entities") or []
    if not entities:
        return Verdict(False, "sin entities acusadas.")
    unsupported = [e for e in entities if not _entity_supported(e, exhibits, db)]
    if unsupported:
        return Verdict(
            False,
            f"entities {unsupported} no tienen exhibit que las involucre directamente.",
        )

    return Verdict(True, "ok")


def _sum_per_table(exhibits: list[dict], db: EstateDB) -> dict[str, float]:
    conn = db._conn
    out: dict[str, float] = {}
    for ex in exhibits:
        tbl = ex.get("source_table")
        col = AMOUNT_TABLES.get(tbl or "")
        if not col or tbl not in _PK_BY_TABLE:
            continue
        pk = _PK_BY_TABLE[tbl]
        row = conn.execute(
            f"SELECT {col} FROM {tbl} WHERE {pk} = ?",
            (str(ex.get("record_id", "")),),
        ).fetchone()
        if row is None:
            continue
        out[tbl] = out.get(tbl, 0.0) + float(row[col] or 0)
    return out


def _entity_supported(entity: str, exhibits: list[dict], db: EstateDB) -> bool:
    if ":" not in entity:
        return False
    kind, ident = entity.split(":", 1)
    for ex in exhibits:
        tbl, rid = ex.get("source_table"), str(ex.get("record_id", ""))
        if kind == "RFC":
            if tbl in ("vendors", "efos_list") and rid == ident:
                return True
            if tbl == "invoices":
                inv = db.obtener_factura(rid)
                if inv and (inv.issuer_rfc == ident or inv.receiver_rfc == ident):
                    return True
            if tbl == "bank_txns":
                txn = db.obtener_transferencia(rid)
                if txn is None:
                    continue
                vendor = db.obtener_proveedor(ident)
                if vendor and vendor.bank_clabe in (txn.from_clabe, txn.to_clabe):
                    return True
        elif kind == "EMP":
            emp_id = ident if ident.startswith("EMP:") else f"EMP:{ident}"
            if tbl == "employees" and rid in (ident, emp_id):
                return True
            if tbl == "bank_txns":
                txn = db.obtener_transferencia(rid)
                if txn is None:
                    continue
                emp = db.obtener_empleado(emp_id) or db.obtener_empleado(ident)
                if emp and emp.bank_clabe in (txn.from_clabe, txn.to_clabe):
                    return True
    return False
