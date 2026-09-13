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
    KICKBACK_WINDOW_DAYS,
    PERIOD_END_DAYS,
    PESO_TOLERANCE,
    REVENUE_INFL_MIN_INVOICES,
    ROUNDTRIP_WINDOW_DAYS,
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
        "kickback": _promote_kickback,
        "revenue_inflation": _promote_revenue_inflation,
        "round_tripping": _promote_round_tripping,
        # threshold_splitting existe como promoter (ver
        # _promote_threshold_splitting), pero sobre el sweep 1-50 subia falsas
        # acusaciones de 0 a 33. El plan es explicito: un detector no entra si
        # sube las falsas acusaciones. Queda como lead con la senal, no como
        # finding.
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


def _promote_kickback(
    lead: Lead, db: EstateDB, company: CompanyIdentity,
) -> PromotionResult:
    ctx = dict(lead.detector_context)
    vendor_rfc = ctx.get("vendor_rfc", "")
    emp_id = ctx.get("employee_id", "")
    original_txn = ctx.get("original_txn", "")
    kickback_txn = ctx.get("kickback_txn", "")
    reinforced = int(ctx.get("reinforced_by_pos", "0") or 0)

    if reinforced == 0:
        return PromotionResult(
            None,
            "kickback detectado pero el empleado no aparece como approver/requester "
            "en POs del vendor; sin ese refuerzo no se acredita conflicto de interes. "
            "Se mantiene como lead.",
        )

    original = db.obtener_transferencia(original_txn)
    kick = db.obtener_transferencia(kickback_txn)
    vendor = db.obtener_proveedor(vendor_rfc)
    emp = db.obtener_empleado(emp_id)
    if not all([original, kick, vendor, emp]):
        return PromotionResult(None, "no se pudieron cargar las transferencias, vendor o empleado.")

    po_ids = [rid for tbl, rid in lead.suggested_records if tbl == "purchase_orders"]
    pos_full = []
    for pid in po_ids:
        row = db._one("SELECT * FROM purchase_orders WHERE po_id = ?", (pid,))
        if row is not None:
            from src.tools.models import PurchaseOrder
            pos_full.append(PurchaseOrder(**dict(row)))

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

    # Solo se cita el bank_txn del kickback: asi la suma per-tabla en bank_txns
    # queda igual a peso_amount y reconcilia. El pago empresa->vendor se
    # documenta en la narrativa y en la PO firmada por el empleado (que ya se
    # cita entre los exhibits).
    _add(
        "bank_txns", kick.txn_id,
        f"Transferencia del proveedor {vendor_rfc} a la CLABE personal del "
        f"empleado {emp_id} por ${kick.amount:,.2f} MXN el {kick.date} "
        f"(el pago originante empresa->vendor {original.txn_id} por "
        f"${original.amount:,.2f} MXN esta narrado y ligado en la PO citada).",
    )
    _add(
        "employees", emp.emp_id,
        f"Registro del empleado {emp.emp_id} ({emp.name}, {emp.role}) "
        f"con CLABE {emp.bank_clabe}.",
    )
    _add(
        "vendors", vendor.rfc,
        f"Registro del proveedor {vendor.rfc} ({vendor.legal_name}) con "
        f"CLABE {vendor.bank_clabe or 'sin registro'}.",
    )
    first_po_id: str | None = None
    for p in sorted(pos_full, key=lambda x: x.po_id):
        pid = _add(
            "purchase_orders", p.po_id,
            f"PO {p.po_id} por ${p.amount:,.2f} MXN al proveedor {vendor_rfc}, "
            f"aprobada por {p.approver} y solicitada por {p.requester}.",
        )
        if first_po_id is None:
            first_po_id = p.po_id

    steps = [
        {
            "from": f"RFC:{company.rfc}",
            "to": f"RFC:{vendor.rfc}",
            "amount": round(original.amount, 2),
            "date": original.date,
            "exhibit_id": exhibit_id_by_record[("purchase_orders", first_po_id)]
                if first_po_id else exhibit_id_by_record[("vendors", vendor.rfc)],
        },
        {
            "from": f"RFC:{vendor.rfc}",
            "to": f"EMP:{emp.emp_id.replace('EMP:', '')}",
            "amount": round(kick.amount, 2),
            "date": kick.date,
            "exhibit_id": exhibit_id_by_record[("bank_txns", kick.txn_id)],
        },
    ]

    pct = kick.amount / original.amount if original.amount else 0
    narrative = (
        f"El proveedor {vendor.rfc} ({vendor.legal_name}) recibio "
        f"${original.amount:,.2f} MXN de la empresa el {original.date}. Dentro de "
        f"{KICKBACK_WINDOW_DAYS} dias, transfirio ${kick.amount:,.2f} MXN "
        f"({pct * 100:.1f}%) a la CLABE personal del empleado {emp.emp_id} "
        f"({emp.name}, {emp.role}), quien firmo {reinforced} orden(es) de compra "
        f"al mismo proveedor. La CLABE receptora esta registrada en la tabla "
        f"employees, no es una cuenta corporativa."
    )

    candidate = {
        "scheme_type": "kickback",
        "entities": [f"RFC:{vendor.rfc}", f"EMP:{emp.emp_id.replace('EMP:', '')}"],
        "narrative": narrative,
        "rule_broken": (
            "Conflicto de interes: el empleado que autorizo/solicito la compra "
            "recibio una transferencia del proveedor beneficiado."
        ),
        "peso_amount": round(kick.amount, 2),
        "exhibits": exhibits,
        "money_trail": steps,
        "confidence": "proven",
    }
    return PromotionResult(candidate, "ok")


def _promote_revenue_inflation(
    lead: Lead, db: EstateDB, company: CompanyIdentity,
) -> PromotionResult:
    ctx = dict(lead.detector_context)
    client_rfc = ctx.get("client_rfc", "")
    num_invoices = int(ctx.get("num_invoices", "0") or 0)
    cliente_nuevo = ctx.get("cliente_nuevo") == "true"

    if num_invoices < REVENUE_INFL_MIN_INVOICES:
        return PromotionResult(
            None,
            f"solo {num_invoices} facturas al cliente; el patron sistematico "
            f"requiere >={REVENUE_INFL_MIN_INVOICES}.",
        )

    invoice_uuids = [rid for tbl, rid in lead.suggested_records if tbl == "invoices"]
    ledger_ids = [rid for tbl, rid in lead.suggested_records if tbl == "ledger"]
    facturas = [f for f in (db.obtener_factura(u) for u in invoice_uuids) if f is not None]
    if len(facturas) < REVENUE_INFL_MIN_INVOICES:
        return PromotionResult(None, "no se pudieron cargar todas las invoices citadas.")

    # Ledger recargado por invoice_uuid para narrativa contable.
    ledger_debit = 0.0
    ledger_credit = 0.0
    ledger_by_id: dict[int, object] = {}
    for f in facturas:
        for e in db.obtener_asientos_contables(invoice_uuid=f.uuid):
            if e.account_code in {"1100", "4000"}:
                ledger_by_id[e.entry_id] = e
                ledger_debit += e.debit
                ledger_credit += e.credit

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

    for f in sorted(facturas, key=lambda x: (x.issue_date, x.uuid)):
        _add(
            "invoices", f.uuid,
            f"Factura {f.uuid[:8]} emitida por la empresa a {client_rfc} el "
            f"{f.issue_date} por ${f.total:,.2f} MXN (metodo {f.metodo_pago}, "
            f"status {f.status}).",
        )
    for eid_num in sorted(ledger_by_id.keys()):
        e = ledger_by_id[eid_num]
        _add(
            "ledger", str(e.entry_id),
            f"Asiento {e.entry_id} el {e.date}: cuenta {e.account_code} "
            f"({e.account_name}) debit ${e.debit:,.2f} / credit ${e.credit:,.2f} "
            f"contra factura {(e.invoice_uuid or '')[:8]}.",
        )

    total = round(sum(f.total for f in facturas), 2)
    first_date = min(f.issue_date for f in facturas)
    last_date = max(f.issue_date for f in facturas)

    # Money trail: un step virtual empresa -> cliente reconociendo el ingreso
    # sin cobro. Exhibit_id apunta a la primera factura.
    first_inv_uuid = sorted(facturas, key=lambda x: (x.issue_date, x.uuid))[0].uuid
    steps = [{
        "from": f"RFC:{company.rfc}",
        "to": f"RFC:{client_rfc}",
        "amount": total,
        "date": last_date,
        "exhibit_id": exhibit_id_by_record[("invoices", first_inv_uuid)],
    }]

    histo_frag = (
        "ese cliente no tiene ningun cobro previo en el estate"
        if cliente_nuevo
        else "el cliente tiene cobros previos por otras facturas pero ninguno correlacionado con este cluster"
    )
    narrative = (
        f"La empresa emitio {len(facturas)} facturas al cliente {client_rfc} "
        f"entre {first_date} y {last_date} por un total de ${total:,.2f} MXN, "
        f"todas dentro de los ultimos {PERIOD_END_DAYS} dias del mes. El "
        f"ledger registra los ingresos (debit CxC 1100 ${ledger_debit:,.2f}, "
        f"credit Ingresos 4000 ${ledger_credit:,.2f}) pero no existe bank_txn "
        f"entrante correlacionado; {histo_frag}. El patron es reconocimiento "
        f"de ingreso al cierre sin cobro ni sustancia economica."
    )

    confidence = "proven" if cliente_nuevo and ledger_by_id else "probable"

    candidate = {
        "scheme_type": "revenue_inflation",
        "entities": [f"RFC:{client_rfc}"],
        "narrative": narrative,
        "rule_broken": (
            "NIF A-2 devengacion + CFF art. 69-B: reconocimiento de ingreso al "
            "cierre del periodo sin sustancia economica ni cobro correlacionado."
        ),
        "peso_amount": total,
        "exhibits": exhibits,
        "money_trail": steps,
        "confidence": confidence,
    }
    return PromotionResult(candidate, "ok")


def _promote_round_tripping(
    lead: Lead, db: EstateDB, company: CompanyIdentity,
) -> PromotionResult:
    ctx = dict(lead.detector_context)
    cycle_txn_ids = [x for x in ctx.get("cycle_txns", "").split(",") if x]
    txns = [t for t in (db.obtener_transferencia(x) for x in cycle_txn_ids) if t is not None]
    if len(txns) < 2 or len(txns) != len(cycle_txn_ids):
        return PromotionResult(None, "no se pudieron cargar todos los bank_txns del ciclo.")

    first = txns[0]
    last = txns[-1]
    if first.amount <= 0:
        return PromotionResult(None, "monto inicial no positivo; no se puede reconciliar.")

    # Intermediarios y sus duenos.
    intermediates_clabes = [t.to_clabe for t in txns[:-1]]
    owners = [db.resolver_clabe(c) for c in intermediates_clabes]

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

    for i, t in enumerate(txns):
        if i == 0:
            note = (
                f"Salida de la empresa por ${t.amount:,.2f} MXN el {t.date} "
                f"hacia CLABE {t.to_clabe}."
            )
        elif i == len(txns) - 1:
            note = (
                f"Retorno a la empresa por ${t.amount:,.2f} MXN el {t.date} "
                f"desde CLABE {t.from_clabe}, cerrando el ciclo."
            )
        else:
            note = (
                f"Salto intermedio ${t.amount:,.2f} MXN el {t.date} de CLABE "
                f"{t.from_clabe} a CLABE {t.to_clabe}."
            )
        _add("bank_txns", t.txn_id, note)

    entities: list[str] = []
    seen_entity: set[str] = set()
    for owner in owners:
        if owner.owner_type == "vendor":
            v = db.obtener_proveedor(owner.owner_id)
            if v is not None and (("vendors", v.rfc) not in exhibit_id_by_record):
                _add(
                    "vendors", v.rfc,
                    f"Registro del proveedor {v.rfc} ({v.legal_name}) con "
                    f"CLABE {v.bank_clabe or 'sin registro'}.",
                )
            key = f"RFC:{owner.owner_id}"
            if key not in seen_entity:
                seen_entity.add(key)
                entities.append(key)
        elif owner.owner_type == "employee":
            emp = db.obtener_empleado(owner.owner_id)
            if emp is not None and (("employees", emp.emp_id) not in exhibit_id_by_record):
                _add(
                    "employees", emp.emp_id,
                    f"Registro del empleado {emp.emp_id} ({emp.name}, {emp.role}) "
                    f"con CLABE {emp.bank_clabe}.",
                )
            key = f"EMP:{owner.owner_id.replace('EMP:', '')}"
            if key not in seen_entity:
                seen_entity.add(key)
                entities.append(key)

    if not entities:
        return PromotionResult(
            None,
            "el ciclo pasa exclusivamente por CLABEs desconocidos (no vendors ni "
            "employees registrados); sin contraparte identificable no se puede "
            "acusar a nadie.",
        )

    # Money trail: un step por salto, orden cronologico.
    steps: list[dict] = []
    for t in txns:
        from_entity = _clabe_to_entity(db, t.from_clabe, company)
        to_entity = _clabe_to_entity(db, t.to_clabe, company)
        steps.append({
            "from": from_entity,
            "to": to_entity,
            "amount": round(t.amount, 2),
            "date": t.date,
            "exhibit_id": exhibit_id_by_record[("bank_txns", t.txn_id)],
        })

    span_days = int(ctx.get("span_days", "0") or 0)
    delta_pct = abs(last.amount - first.amount) / first.amount
    total_cycle = round(sum(t.amount for t in txns), 2)

    primary_entity = entities[0]
    intermediary_frag = (
        f"y {len(entities) - 1} intermediario(s) adicional(es)"
        if len(entities) > 1 else "sin intermediarios adicionales identificados"
    )
    narrative = (
        f"En {span_days} dias la empresa envio ${first.amount:,.2f} MXN via "
        f"{primary_entity} el {first.date} y recibio ${last.amount:,.2f} MXN "
        f"de retorno el {last.date} tras {len(txns)} saltos "
        f"(desviacion {delta_pct * 100:.1f}%, {intermediary_frag}). El flujo "
        f"cierra un ciclo sobre el mismo CLABE de la empresa dentro de "
        f"{ROUNDTRIP_WINDOW_DAYS} dias, patron caracteristico de simulacion "
        f"de operaciones."
    )

    confidence = "proven" if delta_pct <= PESO_TOLERANCE else "probable"

    candidate = {
        "scheme_type": "round_tripping",
        "entities": entities,
        "narrative": narrative,
        "rule_broken": (
            "Simulacion de operaciones: los recursos regresan al originante sin "
            "sustancia economica (CFF art. 69-B, operaciones inexistentes)."
        ),
        "peso_amount": total_cycle,
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
