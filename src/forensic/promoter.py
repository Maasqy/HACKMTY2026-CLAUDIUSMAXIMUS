"""Promueve un lead a un finding candidato.

Reglas del baseline zero-LLM:

1. Cuatro estados reales del 69-B:
   - definitivo         -> potencialmente acusable
   - presunto           -> nunca finding; siempre lead
   - desvirtuado        -> jamas acusable; el SAT ya resolvio a favor
   - sentencia_favorable-> jamas acusable; tribunal ya resolvio a favor

2. El efecto de 69-B es RETROACTIVO. La fecha de publicacion no es compuerta;
   decide unicamente el matiz de la narrativa.

3. Compuerta de materialidad: un match EFOS definitivo asciende a finding solo
   si se cumplen al menos EFOS_MATERIALITY_MIN_FLAGS banderas.

4. Money trail: pares (from_clabe, to_clabe) agrupados; un step por par.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from src.config import (
    APPROVAL_LIMIT_MXN,
    EFOS_DEFINITIVO,
    EFOS_EXONERADO,
    EFOS_MATERIALITY_MIN_FLAGS,
    EFOS_PRESUNTO,
    GENERIC_CONCEPT_PATTERNS,
    PESO_TOLERANCE,
    VENDOR_FRESHNESS_DAYS,
)
from src.detectors.base import Lead
from src.forensic.company import CompanyIdentity
from src.tools.estate_access import EstateDB


@dataclass(frozen=True, slots=True)
class PromotionResult:
    candidate: Optional[dict]
    reason: str


def promote(lead: Lead, db: EstateDB, company: CompanyIdentity) -> PromotionResult:
    router = {
        "efos_match": _promote_efos_match,
        # threshold_splitting existe como promoter (ver
        # _promote_threshold_splitting), pero sobre el sweep 1-50 subia falsas
        # acusaciones de 0 a 33. El plan es explicito: un detector no entra si
        # sube las falsas acusaciones. Queda como lead con la senal, no como
        # finding. Se puede reactivar sumando materialidad al promoter.
    }
    fn = router.get(lead.detector_id)
    if fn is None:
        return PromotionResult(
            None,
            f"detector {lead.detector_id!r} produce lead con senal reproducible pero "
            f"sin compuerta de materialidad; se mantiene abierto para revision manual.",
        )
    return fn(lead, db, company)


def _promote_efos_match(lead: Lead, db: EstateDB, company: CompanyIdentity) -> PromotionResult:
    ctx = dict(lead.detector_context)
    status = (ctx.get("efos_status") or "").lower()

    if status in EFOS_EXONERADO:
        return PromotionResult(
            None,
            f"el SAT resolvio a favor del contribuyente ({status}); el listado 69-B "
            f"distingue sospechoso de exonerado y no se acusa a un exonerado.",
        )
    if status == EFOS_PRESUNTO:
        return PromotionResult(
            None,
            "presunto sin resolucion; la presuncion admite prueba en contrario. "
            "Se mantiene como lead pero sin acusacion.",
        )
    if status != EFOS_DEFINITIVO:
        return PromotionResult(None, f"estatus 69-B desconocido: {status!r}.")

    pub_date = ctx.get("publication_date") or ""
    if not pub_date:
        return PromotionResult(
            None, "efos_list no tiene publication_date; no se puede citar el articulo.",
        )

    invoice_uuids = [rid for tbl, rid in lead.suggested_records if tbl == "invoices"]
    bank_ids = [rid for tbl, rid in lead.suggested_records if tbl == "bank_txns"]
    facturas = [f for f in (db.obtener_factura(u) for u in invoice_uuids) if f is not None]
    txns = [t for t in (db.obtener_transferencia(b) for b in bank_ids) if t is not None]

    if not facturas:
        return PromotionResult(
            None, "el proveedor esta en 69-B definitivo pero sin factura citable."
        )
    if not txns:
        return PromotionResult(
            None,
            "hay facturas del EFOS definitivo pero ningun bank_txn asociado; sin flujo "
            "bancario no se puede reconciliar el peso_amount.",
        )

    rfc = lead.entity.split(":", 1)[1]
    vendor = db.obtener_proveedor(rfc)
    legal_name = vendor.legal_name if vendor is not None else ctx.get("legal_name", rfc)

    # Compuerta de materialidad
    contracts = db.obtener_contratos(rfc_proveedor=rfc)
    pos = db.obtener_ordenes_compra(rfc_proveedor=rfc)
    flags: list[str] = []
    if not contracts:
        flags.append("no existe contrato registrado para el proveedor")
    if not pos:
        flags.append("no existe orden de compra registrada para el proveedor")

    first_invoice = min(facturas, key=lambda f: f.issue_date)
    if vendor is not None and vendor.registered_date and first_invoice.issue_date:
        gap = _days_between(vendor.registered_date, first_invoice.issue_date)
        if gap <= VENDOR_FRESHNESS_DAYS:
            flags.append(
                f"proveedor registrado el {vendor.registered_date}, a {gap} dias de la "
                f"primera factura ({first_invoice.issue_date})"
            )

    generic_hit = next((f for f in facturas if _is_generic_concept(f.concepto_text)), None)
    if generic_hit is not None:
        flags.append(
            f"factura {generic_hit.uuid} con concepto generico "
            f"({generic_hit.concepto_text!r})"
        )

    if vendor is not None and vendor.bank_clabe:
        mismatch = next((t for t in txns if t.to_clabe != vendor.bank_clabe), None)
        if mismatch is not None:
            flags.append(
                f"pago {mismatch.txn_id} a CLABE distinta a la registrada en vendors"
            )

    if len(flags) < EFOS_MATERIALITY_MIN_FLAGS:
        return PromotionResult(
            None,
            f"EFOS definitivo pero materialidad insuficiente: {len(flags)}/"
            f"{EFOS_MATERIALITY_MIN_FLAGS} banderas "
            f"({'; '.join(flags) or 'ninguna'}). El SAT admite acreditar materialidad; "
            f"el lead se mantiene abierto.",
        )

    # Exhibits
    exhibits: list[dict] = []
    exhibit_id_by_record: dict[tuple[str, str], str] = {}

    def _add(source_table: str, record_id: str, note: str) -> str:
        eid = f"E{len(exhibits) + 1}"
        exhibits.append({
            "exhibit_id": eid, "source_table": source_table,
            "record_id": record_id, "note": note,
        })
        exhibit_id_by_record[(source_table, record_id)] = eid
        return eid

    _add(
        "efos_list", rfc,
        f"Publicado en la lista 69-B con estatus definitivo el {pub_date}.",
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
            f"Registro del proveedor {vendor.rfc} (CLABE {vendor.bank_clabe or 'sin registro'}, "
            f"alta {vendor.registered_date or 'sin fecha'}).",
        )

    # Money trail
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
            "amount": total, "date": rep.date,
            "exhibit_id": exhibit_id_by_record[("bank_txns", rep.txn_id)],
            "_first_date": first_date,
        })
    steps.sort(key=lambda s: (s["_first_date"], s["from"], s["to"]))
    for s in steps:
        s.pop("_first_date")

    # Peso y confidence
    total_pagado = round(sum(t.amount for t in txns), 2)
    total_facturado = round(sum(f.total for f in facturas), 2)
    delta = abs(total_pagado - total_facturado) / max(total_facturado, 1.0)
    confidence = "proven" if delta <= PESO_TOLERANCE else "probable"

    op_dates = sorted(d for d in ([f.issue_date for f in facturas] + [t.date for t in txns]) if d)
    earliest_op = op_dates[0] if op_dates else ""
    latest_op = op_dates[-1] if op_dates else ""
    all_pre = bool(latest_op) and latest_op < pub_date
    some_post = bool(latest_op) and latest_op >= pub_date

    narrative = _narrative(
        rfc=rfc, legal=legal_name, pub_date=pub_date,
        num_facturas=len(facturas), num_txns=len(txns),
        total_pagado=total_pagado, earliest_op=earliest_op,
        all_pre=all_pre, some_post=some_post, materiality=flags,
    )

    candidate = {
        "scheme_type": "phantom_vendor",
        "entities": [f"RFC:{rfc}"],
        "narrative": narrative,
        "rule_broken": (
            "SAT Articulo 69-B CFF: operaciones amparadas por CFDI de contribuyente en "
            "listado 69-B definitivo no producen ni produjeron efectos fiscales (efecto "
            "retroactivo); materialidad no acreditada."
        ),
        "peso_amount": total_pagado,
        "exhibits": exhibits,
        "money_trail": steps,
        "confidence": confidence,
    }
    return PromotionResult(candidate, "ok")


def _promote_threshold_splitting(
    lead: Lead, db: EstateDB, company: CompanyIdentity,
) -> PromotionResult:
    ctx = dict(lead.detector_context)
    po_ids = [rid for tbl, rid in lead.suggested_records if tbl == "purchase_orders"]
    if len(po_ids) < 3:
        return PromotionResult(
            None,
            f"solo {len(po_ids)} POs en el cluster; la senal requiere >=3 para "
            f"llamar fraccionamiento sistematico.",
        )

    rfc = lead.entity.split(":", 1)[1]
    vendor = db.obtener_proveedor(rfc)
    legal_name = vendor.legal_name if vendor is not None else rfc

    # POs completos.
    pos = [p for p in (db._one(
        "SELECT * FROM purchase_orders WHERE po_id = ?", (pid,)
    ) for pid in po_ids) if p is not None]
    if len(pos) < 3:
        return PromotionResult(None, "no se pudieron cargar todas las POs.")
    from src.tools.models import PurchaseOrder
    pos = [PurchaseOrder(**dict(p)) for p in pos]

    total = round(sum(p.amount for p in pos), 2)
    same_approver = ctx.get("same_approver") == "true"
    approver = ctx.get("approver", "")

    exhibits: list[dict] = []
    exhibit_id_by_record: dict[tuple[str, str], str] = {}

    def _add(source_table: str, record_id: str, note: str) -> str:
        eid = f"E{len(exhibits) + 1}"
        exhibits.append({
            "exhibit_id": eid, "source_table": source_table,
            "record_id": record_id, "note": note,
        })
        exhibit_id_by_record[(source_table, record_id)] = eid
        return eid

    for p in sorted(pos, key=lambda x: x.po_id):
        note = (
            f"PO {p.po_id} por ${p.amount:,.2f} MXN el {p.date}, "
            f"aprobada por {p.approver or 'sin firma'}."
        )
        _add("purchase_orders", p.po_id, note)

    # Facturas del vendor en la ventana de las POs.
    invoice_uuids = [rid for tbl, rid in lead.suggested_records if tbl == "invoices"]
    facturas = [f for f in (db.obtener_factura(u) for u in invoice_uuids) if f is not None]
    for f in sorted(facturas, key=lambda x: x.uuid):
        _add(
            "invoices", f.uuid,
            f"Factura de {rfc} a la empresa por ${f.total:,.2f} MXN el {f.issue_date}.",
        )
    if vendor is not None:
        _add(
            "vendors", vendor.rfc,
            f"Registro del proveedor {vendor.rfc} (CLABE {vendor.bank_clabe or 'sin registro'}).",
        )

    # Money trail: una arista empresa -> vendor, monto = suma POs, fecha = ultima PO.
    if vendor is not None and vendor.bank_clabe:
        last_po = max(pos, key=lambda x: x.date)
        steps = [{
            "from": f"RFC:{company.rfc}",
            "to": f"RFC:{rfc}",
            "amount": total,
            "date": last_po.date,
            "exhibit_id": exhibit_id_by_record[("purchase_orders", last_po.po_id)],
        }]
    else:
        steps = []

    approver_frag = (
        f", todas firmadas por {approver}" if same_approver and approver else ""
    )
    narrative = (
        f"El proveedor {rfc} ({legal_name}) recibio {len(pos)} ordenes de compra "
        f"entre {min(p.date for p in pos)} y {max(p.date for p in pos)}, cada una "
        f"debajo de ${APPROVAL_LIMIT_MXN:,.2f} MXN, sumando ${total:,.2f} MXN"
        f"{approver_frag}. El limite de autorizacion interno se elude al fraccionar "
        f"lo que economicamente es una sola compra en pedazos independientes."
    )

    candidate = {
        "scheme_type": "threshold_splitting",
        "entities": [f"RFC:{rfc}"],
        "narrative": narrative,
        "rule_broken": (
            f"Politica interna de autorizacion: toda compra superior a "
            f"${APPROVAL_LIMIT_MXN:,.0f} MXN requiere segunda firma "
            f"(umbral en src/config.py:APPROVAL_LIMIT_MXN)."
        ),
        "peso_amount": total,
        "exhibits": exhibits,
        "money_trail": steps,
        "confidence": "proven" if same_approver else "probable",
    }
    return PromotionResult(candidate, "ok")


def _is_generic_concept(text: str) -> bool:
    if not text:
        return False
    lc = text.lower()
    return any(pat in lc for pat in GENERIC_CONCEPT_PATTERNS)


def _days_between(a: str, b: str) -> int:
    try:
        da = date.fromisoformat(a[:10])
        db_ = date.fromisoformat(b[:10])
    except ValueError:
        return 10_000
    return abs((db_ - da).days)


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
    all_pre: bool, some_post: bool, materiality: list[str],
) -> str:
    materiality_frag = "; ".join(materiality[:2]) if materiality else "sin materialidad"
    if some_post:
        temporal = (
            f"algunas operaciones son posteriores al listado del {pub_date}; el efecto "
            f"del 69-B tambien alcanza retroactivamente a las anteriores"
        )
    elif all_pre:
        temporal = (
            f"todas las operaciones son anteriores al listado del {pub_date}; el "
            f"articulo 69-B CFF establece que estas 'no producen ni produjeron efectos "
            f"fiscales' (efecto retroactivo)"
        )
    else:
        temporal = f"listado publicado el {pub_date}"
    return (
        f"El proveedor {rfc} ({legal}) esta publicado por el SAT en la lista 69-B con "
        f"estatus definitivo. La empresa recibio {num_facturas} factura(s) desde "
        f"{earliest_op} y pago ${total_pagado:,.2f} MXN en {num_txns} transferencia(s); "
        f"{temporal}. Materialidad no acreditada: {materiality_frag}."
    )
