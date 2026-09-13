"""Promueve un lead a un finding candidato. Solo para el patron blindado.

Regla del baseline:
  - Solo se asciende un lead cuyo detector es 'efos_match' y cuyo estatus 69-B
    es 'definitivo'.
  - La publicacion en efos_list debe ser estrictamente anterior a la fecha
    minima de la operacion. Si es posterior, la empresa no podia saberlo y
    el lead se queda como leads_not_pursued con esa razon exacta.

Money trail (spec del usuario):
  - Agrupar bank_txns por par (from_clabe, to_clabe).
  - Un step por par: amount = suma, fecha = la del movimiento con mayor
    monto (desempate txn_id), exhibit_id = ese movimiento.
  - Ordenar steps por fecha del primer movimiento del par.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.config import EFOS_DEFINITIVO, PESO_TOLERANCE
from src.detectors.base import Lead
from src.forensic.company import CompanyIdentity
from src.tools.estate_access import EstateDB


@dataclass(frozen=True, slots=True)
class PromotionResult:
    candidate: Optional[dict]
    reason: str


def promote(lead: Lead, db: EstateDB, company: CompanyIdentity) -> PromotionResult:
    if lead.detector_id != "efos_match":
        return PromotionResult(None, "el baseline solo asciende leads de efos_match.")

    ctx = dict(lead.detector_context)
    if ctx.get("efos_status") != EFOS_DEFINITIVO:
        return PromotionResult(
            None,
            f"estatus 69-B es {ctx.get('efos_status', '(vacio)')!r}, "
            "no 'definitivo'; sin acusacion.",
        )

    pub_date = ctx.get("publication_date") or ""
    if not pub_date:
        return PromotionResult(
            None,
            "efos_list no tiene publication_date; no se puede validar la temporalidad.",
        )

    invoice_uuids = [rid for tbl, rid in lead.suggested_records if tbl == "invoices"]
    bank_ids = [rid for tbl, rid in lead.suggested_records if tbl == "bank_txns"]

    facturas = [f for f in (db.obtener_factura(u) for u in invoice_uuids) if f is not None]
    txns = [t for t in (db.obtener_transferencia(b) for b in bank_ids) if t is not None]

    if not facturas and not txns:
        return PromotionResult(
            None, "el proveedor esta en efos_list pero sin operacion citable en el estate."
        )
    if not txns:
        return PromotionResult(
            None,
            "hay facturas del EFOS pero ningun bank_txn asociado; sin flujo bancario "
            "no se puede reconciliar la acusacion.",
        )

    op_dates = sorted(d for d in ([f.issue_date for f in facturas] + [t.date for t in txns]) if d)
    if not op_dates:
        return PromotionResult(None, "ninguna operacion tiene fecha citable.")
    earliest_op = op_dates[0]
    if pub_date >= earliest_op:
        return PromotionResult(
            None,
            f"publicacion 69-B ({pub_date}) es posterior o igual a la primera operacion "
            f"({earliest_op}); la empresa no podia saber que era EFOS en ese momento.",
        )

    rfc = lead.entity.split(":", 1)[1]
    vendor = db.obtener_proveedor(rfc)
    legal_name = vendor.legal_name if vendor is not None else ctx.get("legal_name", rfc)

    exhibits: list[dict] = []
    exhibit_id_by_record: dict[tuple[str, str], str] = {}

    def _add(source_table: str, record_id: str, note: str) -> str:
        eid = f"E{len(exhibits) + 1}"
        exhibits.append({
            "exhibit_id": eid,
            "source_table": source_table,
            "record_id": record_id,
            "note": note,
        })
        exhibit_id_by_record[(source_table, record_id)] = eid
        return eid

    _add(
        "efos_list", rfc,
        f"Publicado en la lista 69-B con estatus {EFOS_DEFINITIVO} el {pub_date}.",
    )
    for f in sorted(facturas, key=lambda x: x.uuid):
        _add(
            "invoices", f.uuid,
            f"Factura de {rfc} a la empresa por ${f.total:,.2f} MXN el {f.issue_date}.",
        )
    for t in sorted(txns, key=lambda x: x.txn_id):
        _add(
            "bank_txns", t.txn_id,
            f"Transferencia de la empresa al proveedor por ${t.amount:,.2f} MXN el {t.date}.",
        )
    if vendor is not None:
        _add(
            "vendors", vendor.rfc,
            f"Registro del proveedor {vendor.rfc} con CLABE "
            f"{vendor.bank_clabe or 'sin registro'}.",
        )

    pairs: dict[tuple[str, str], list] = {}
    for t in txns:
        pairs.setdefault((t.from_clabe, t.to_clabe), []).append(t)

    steps: list[dict] = []
    for (from_clabe, to_clabe), group in pairs.items():
        rep = sorted(group, key=lambda x: (-x.amount, x.txn_id))[0]
        first_date = min(t.date for t in group if t.date)
        total = round(sum(t.amount for t in group), 2)
        steps.append({
            "from": _clabe_to_entity(db, from_clabe, company),
            "to": _clabe_to_entity(db, to_clabe, company),
            "amount": total,
            "date": rep.date,
            "exhibit_id": exhibit_id_by_record[("bank_txns", rep.txn_id)],
            "_first_date": first_date,
        })
    steps.sort(key=lambda s: (s["_first_date"], s["from"], s["to"]))
    for s in steps:
        s.pop("_first_date")

    total_pagado = round(sum(t.amount for t in txns), 2)
    total_facturado = round(sum(f.total for f in facturas), 2) if facturas else 0.0
    delta = (
        abs(total_pagado - total_facturado) / max(total_facturado, 1.0)
        if total_facturado else 1.0
    )
    confidence = "proven" if (total_facturado > 0 and delta <= PESO_TOLERANCE) else "probable"

    candidate = {
        "scheme_type": "phantom_vendor",
        "entities": [f"RFC:{rfc}"],
        "narrative": _narrative(
            rfc=rfc, legal=legal_name, pub_date=pub_date,
            num_facturas=len(facturas), num_txns=len(txns),
            total_pagado=total_pagado, earliest_op=earliest_op,
        ),
        "rule_broken": (
            "SAT Articulo 69-B: operacion con contribuyente publicado en la lista "
            "definitiva de EFOS antes de la fecha de la operacion."
        ),
        "peso_amount": total_pagado,
        "exhibits": exhibits,
        "money_trail": steps,
        "confidence": confidence,
    }
    return PromotionResult(candidate, "ok")


def _clabe_to_entity(db: EstateDB, clabe: str, company: CompanyIdentity) -> str:
    if clabe == company.clabe:
        return f"RFC:{company.rfc}"
    owner = db.resolver_clabe(clabe)
    if owner.owner_type == "vendor":
        return f"RFC:{owner.owner_id}"
    if owner.owner_type == "employee":
        return f"EMP:{owner.owner_id.replace('EMP:', '')}"
    return f"CLABE:{clabe}"


def _narrative(
    *, rfc: str, legal: str, pub_date: str, num_facturas: int, num_txns: int,
    total_pagado: float, earliest_op: str,
) -> str:
    return (
        f"El proveedor {rfc} ({legal}) fue publicado por el SAT en la lista 69-B con "
        f"estatus definitivo el {pub_date}. Con esa publicacion previa, la empresa "
        f"realizo operaciones a partir del {earliest_op}: recibio {num_facturas} "
        f"factura(s) y pago ${total_pagado:,.2f} MXN en {num_txns} transferencia(s). "
        f"La ley obliga a la empresa a suspender toda operacion con un EFOS "
        f"definitivo desde la fecha de publicacion, y el efecto fiscal de las "
        f"facturas emitidas es nulo."
    )
