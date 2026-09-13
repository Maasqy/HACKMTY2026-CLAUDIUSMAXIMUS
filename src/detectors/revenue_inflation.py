"""revenue_inflation: reconocimiento de ingreso sin cobro ni sustancia.

Senal:
  - Facturas emitidas por la empresa (issuer_rfc == company.rfc) a un cliente
    externo (receiver_rfc != company.rfc, no es empleado ni vendor).
  - Emitidas al cierre del periodo: dia del mes >= last_day_of_month
    - PERIOD_END_DAYS + 1.
  - Status 'vigente'.
  - Al menos REVENUE_INFL_MIN_INVOICES facturas al cliente.
  - Ninguna de esas facturas tiene bank_txn entrante correlacionado: en el
    estate los cobros llevan reference 'Cobro factura {UUID8}', donde UUID8
    son los primeros 8 caracteres del UUID. Un cliente al que la empresa le
    factura pero nunca le cobra es la marca del esquema.

Reforzadores (materialidad):
  - Ledger tiene asientos de reconocimiento (debit 1100 CxC, credit 4000
    Ingresos) por esas facturas, sin cash inflow.

Rule broken: NIF A-2 devengacion + CFF art. 69-B (operaciones inexistentes)
cuando se documenta un ingreso al cierre sin sustancia economica.

peso_amount = suma de invoice.total del cluster. Reconcilia contra tabla
invoices porque se citan como exhibits todas las invoices. Ledger se cita
adicionalmente para probar el reconocimiento contable.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from src.config import (
    PERIOD_END_DAYS,
    REVENUE_INFL_MIN_INVOICES,
)
from src.detectors.base import Lead
from src.forensic.company import CompanyIdentity
from src.tools.estate_access import EstateDB


DETECTOR_ID = "revenue_inflation"


def find_leads(db: EstateDB, company: CompanyIdentity) -> list[Lead]:
    all_invoices = db.obtener_facturas()
    all_txns = db.obtener_transferencias()

    # Prefijos de UUIDs con cobro entrante a la empresa.
    prefijos_cobrados: set[str] = set()
    for t in all_txns:
        if t.to_clabe != company.clabe:
            continue
        ref = (t.reference or "").strip()
        if not ref or "cobro" not in ref.lower():
            continue
        token = ref.split()[-1].upper()
        if len(token) >= 8:
            prefijos_cobrados.add(token[:8])

    # Facturas emitidas por la empresa a un cliente externo.
    vendors_rfc = {v.rfc for v in db.buscar_proveedores()}

    emitidas = [
        f for f in all_invoices
        if f.issuer_rfc == company.rfc
        and f.receiver_rfc
        and f.receiver_rfc != company.rfc
        and f.receiver_rfc not in vendors_rfc
        and (f.status or "").lower() == "vigente"
    ]

    by_client: dict[str, list] = defaultdict(list)
    for f in emitidas:
        by_client[f.receiver_rfc].append(f)

    leads: list[Lead] = []
    for client_rfc in sorted(by_client.keys()):
        facturas = sorted(by_client[client_rfc], key=lambda x: (x.issue_date, x.uuid))
        cierre = [f for f in facturas if _en_cierre_mes(f.issue_date)]
        if len(cierre) < REVENUE_INFL_MIN_INVOICES:
            continue

        con_cobro = [f for f in cierre if f.uuid[:8].upper() in prefijos_cobrados]
        if con_cobro:
            continue

        otras = [f for f in facturas if f not in cierre]
        otras_cobradas = [f for f in otras if f.uuid[:8].upper() in prefijos_cobrados]
        cliente_nuevo = len(otras_cobradas) == 0

        total = round(sum(f.total for f in cierre), 2)
        first_date = cierre[0].issue_date
        last_date = cierre[-1].issue_date

        records: list[tuple[str, str]] = [("invoices", f.uuid) for f in cierre]
        ledger_entries: list = []
        for f in cierre:
            entries = db.obtener_asientos_contables(invoice_uuid=f.uuid)
            for e in entries:
                if e.account_code in {"1100", "4000"}:
                    ledger_entries.append(e)
                    records.append(("ledger", str(e.entry_id)))

        histo_frag = (
            " y sin historial previo de cobros por otras facturas"
            if cliente_nuevo else ""
        )
        reason = (
            f"La empresa emitio {len(cierre)} facturas al cliente {client_rfc} "
            f"entre {first_date} y {last_date} por un total de ${total:,.2f} MXN, "
            f"todas dentro de los ultimos {PERIOD_END_DAYS} dias del mes, "
            f"sin bank_txn de cobro correlacionado{histo_frag}. "
            f"Los asientos de reconocimiento existen en ledger."
        )
        leads.append(Lead(
            detector_id=DETECTOR_ID,
            entity=f"RFC:{client_rfc}",
            signal="revenue_at_period_end_uncollected",
            reason=reason,
            suggested_records=tuple(records),
            monto_estimado=total,
            detector_context=(
                ("client_rfc", client_rfc),
                ("num_invoices", str(len(cierre))),
                ("total", f"{total:.2f}"),
                ("first_invoice_date", first_date),
                ("last_invoice_date", last_date),
                ("num_ledger_entries", str(len(ledger_entries))),
                ("cliente_nuevo", "true" if cliente_nuevo else "false"),
            ),
        ))
    return leads


def _en_cierre_mes(d: str) -> bool:
    """Ultimo tramo del mes calendario: dia >= last_of_month - PERIOD_END_DAYS + 1."""
    dt = _parse(d)
    if dt is None:
        return False
    last = _last_day_of_month(dt.year, dt.month)
    return dt.day >= last - PERIOD_END_DAYS + 1


def _last_day_of_month(year: int, month: int) -> int:
    if month == 12:
        first_next = date(year + 1, 1, 1)
    else:
        first_next = date(year, month + 1, 1)
    return (first_next - date(year, month, 1)).days


def _parse(s: str):
    if not s or len(s) < 10:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None
