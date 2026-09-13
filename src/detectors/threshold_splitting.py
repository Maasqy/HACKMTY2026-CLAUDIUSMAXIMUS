"""threshold_splitting: fraccionamiento de POs para eludir el limite de autorizacion.

Senal: mismo vendor_rfc, ventana de SPLIT_WINDOW_DAYS, cada PO < APPROVAL_LIMIT_MXN,
al menos SPLIT_MIN_POS POs, suma rebasa el limite. Refuerzo si comparten approver.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from src.config import APPROVAL_LIMIT_MXN, SPLIT_MIN_POS, SPLIT_WINDOW_DAYS
from src.detectors.base import Lead
from src.forensic.company import CompanyIdentity
from src.tools.estate_access import EstateDB
from src.tools.models import PurchaseOrder


DETECTOR_ID = "threshold_splitting"


def find_leads(db: EstateDB, company: CompanyIdentity) -> list[Lead]:
    all_pos = db.obtener_ordenes_compra()
    under = [p for p in all_pos if p.amount < APPROVAL_LIMIT_MXN and p.vendor_rfc]

    by_vendor: dict[str, list[PurchaseOrder]] = defaultdict(list)
    for p in under:
        by_vendor[p.vendor_rfc].append(p)

    leads: list[Lead] = []
    seen_vendors: set[str] = set()
    for vendor_rfc in sorted(by_vendor.keys()):
        pos = sorted(by_vendor[vendor_rfc], key=lambda x: (x.date, x.po_id))
        cluster = _first_valid_cluster(pos)
        if cluster is None:
            continue
        if vendor_rfc in seen_vendors:
            continue
        seen_vendors.add(vendor_rfc)

        total = round(sum(p.amount for p in cluster), 2)
        approvers = {p.approver for p in cluster if p.approver}
        same_approver = len(approvers) == 1
        approver = next(iter(approvers)) if same_approver else None

        records: list[tuple[str, str]] = [("purchase_orders", p.po_id) for p in cluster]
        first_day = cluster[0].date
        last_day = cluster[-1].date
        for inv in db.obtener_facturas(
            rfc_emisor=vendor_rfc, fecha_inicio=first_day, fecha_fin=last_day,
        ):
            if inv.receiver_rfc == company.rfc:
                records.append(("invoices", inv.uuid))
        records.append(("vendors", vendor_rfc))

        reinforce = (
            f", todas aprobadas por {approver}" if same_approver and approver else ""
        )
        reason = (
            f"Del {first_day} al {last_day} se emitieron {len(cluster)} POs al "
            f"proveedor {vendor_rfc}, cada una debajo de ${APPROVAL_LIMIT_MXN:,.2f} "
            f"pero sumando ${total:,.2f} MXN{reinforce}. El limite de autorizacion "
            f"se elude por fraccionamiento."
        )
        leads.append(Lead(
            detector_id=DETECTOR_ID,
            entity=f"RFC:{vendor_rfc}",
            signal="threshold_splitting",
            reason=reason,
            suggested_records=tuple(records),
            monto_estimado=total,
            detector_context=(
                ("num_pos", str(len(cluster))),
                ("total", f"{total:.2f}"),
                ("approval_limit", f"{APPROVAL_LIMIT_MXN:.2f}"),
                ("same_approver", "true" if same_approver else "false"),
                ("approver", approver or ""),
                ("first_day", first_day),
                ("last_day", last_day),
            ),
        ))
    return leads


def _first_valid_cluster(pos: list[PurchaseOrder]) -> list[PurchaseOrder] | None:
    """Primera ventana temporal con >=SPLIT_MIN_POS POs cuya suma rebase el
    limite. Determinista, orden lexicografico por (fecha, po_id)."""
    n = len(pos)
    for i in range(n):
        start = _parse(pos[i].date)
        if start is None:
            continue
        window = [pos[i]]
        for j in range(i + 1, n):
            end = _parse(pos[j].date)
            if end is None:
                continue
            if (end - start).days > SPLIT_WINDOW_DAYS:
                break
            window.append(pos[j])
        if len(window) >= SPLIT_MIN_POS:
            total = sum(p.amount for p in window)
            if total > APPROVAL_LIMIT_MXN:
                return window
    return None


def _parse(s: str):
    if not s or len(s) < 10:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None
