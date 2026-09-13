"""payment_without_invoice: pagos salientes de la empresa sin factura mensual.

Agrupa las transferencias salientes de la empresa por (vendor, mes calendario)
y las contrasta con la suma de facturas emitidas por ese vendor a la empresa
en el mismo mes. Si la diferencia rebasa PESO_TOLERANCE (2%), se emite un lead.

Este detector siempre produce leads, nunca findings. El promoter no lo asciende:
"pagos sin factura" es un patron sospechoso pero por si solo no es acusable —
puede ser un anticipo legitimo, un reembolso, un impuesto.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from src.config import PESO_TOLERANCE, RECONCILIATION_WINDOW_MONTHS
from src.detectors.base import Lead
from src.forensic.company import CompanyIdentity
from src.tools.estate_access import EstateDB
from src.tools.models import BankTxn, Invoice


DETECTOR_ID = "payment_without_invoice"


def find_leads(db: EstateDB, company: CompanyIdentity) -> list[Lead]:
    salientes = db.obtener_transferencias(clabe=company.clabe, direccion="saliente")
    if not salientes:
        return []

    grouped: dict[tuple[str, str], list[BankTxn]] = defaultdict(list)
    for txn in salientes:
        owner = db.resolver_clabe(txn.to_clabe)
        if owner.owner_type != "vendor":
            continue
        month = _month_key(txn.date)
        if not month:
            continue
        grouped[(owner.owner_id, month)].append(txn)

    leads: list[Lead] = []
    for (vendor_rfc, month) in sorted(grouped.keys()):
        txns = grouped[(vendor_rfc, month)]
        total_pagos = round(sum(t.amount for t in txns), 2)
        facturas = _invoices_in_month(db, vendor_rfc, company.rfc, month)
        total_facturas = round(sum(f.total for f in facturas), 2)

        delta_pct = None
        if total_facturas > 0:
            delta = abs(total_pagos - total_facturas) / max(total_facturas, 1.0)
            if delta <= PESO_TOLERANCE:
                continue
            delta_pct = delta * 100

        records: list[tuple[str, str]] = []
        for t in sorted(txns, key=lambda x: x.txn_id):
            records.append(("bank_txns", t.txn_id))
        for f in sorted(facturas, key=lambda x: x.uuid):
            records.append(("invoices", f.uuid))
        records.append(("vendors", vendor_rfc))

        vendor = db.obtener_proveedor(vendor_rfc)
        legal = vendor.legal_name if vendor is not None else "(sin registro)"
        if total_facturas == 0:
            reason = (
                f"En {month} la empresa transfirio ${total_pagos:,.2f} MXN al "
                f"proveedor {vendor_rfc} ({legal}) en {len(txns)} pago(s), y no hay "
                f"ninguna factura de ese proveedor a la empresa en el mismo mes."
            )
        else:
            reason = (
                f"En {month} la empresa pago ${total_pagos:,.2f} MXN al proveedor "
                f"{vendor_rfc} ({legal}) en {len(txns)} pago(s), pero la suma de "
                f"facturas del mismo mes es ${total_facturas:,.2f} MXN — "
                f"desviacion {delta_pct:.1f}%, arriba del "
                f"{PESO_TOLERANCE * 100:.0f}% permitido."
            )

        leads.append(Lead(
            detector_id=DETECTOR_ID,
            entity=f"RFC:{vendor_rfc}",
            signal="pago_sin_factura_mensual",
            reason=reason,
            suggested_records=tuple(records),
            monto_estimado=total_pagos,
            detector_context=(
                ("month", month),
                ("total_pagos", f"{total_pagos:.2f}"),
                ("total_facturas", f"{total_facturas:.2f}"),
                ("num_bank_txns", str(len(txns))),
                ("num_facturas", str(len(facturas))),
                ("legal_name", legal),
            ),
        ))
    return leads


def _month_key(d: str) -> str:
    if not d or len(d) < 7:
        return ""
    return d[:7]


def _invoices_in_month(
    db: EstateDB, vendor_rfc: str, company_rfc: str, month: str
) -> list[Invoice]:
    _ = RECONCILIATION_WINDOW_MONTHS  # declarado en config; hoy es 1
    lo = f"{month}-01"
    hi = _last_day_of_month(month)
    return [
        f for f in db.obtener_facturas(
            rfc_emisor=vendor_rfc, fecha_inicio=lo, fecha_fin=hi
        )
        if f.receiver_rfc == company_rfc
    ]


def _last_day_of_month(month: str) -> str:
    year, mo = int(month[:4]), int(month[5:7])
    if mo == 12:
        return f"{year}-12-31"
    first_next = date(year + (mo // 12), (mo % 12) + 1, 1)
    return (first_next - timedelta(days=1)).isoformat()
