"""kickback: el proveedor devuelve un porcentaje al empleado que autorizo.

Senal:
  - bank_txn cuyo to_clabe pertenece a un empleado registrado
  - from_clabe es la CLABE de un vendor
  - el mismo vendor recibio pago de la empresa dentro de KICKBACK_WINDOW_DAYS
  - el monto vendor->empleado esta entre KICKBACK_MIN_PCT y KICKBACK_MAX_PCT
    del pago empresa->vendor

Refuerzo: el empleado aparece como approver o requester en POs de ese vendor.
peso_amount = monto desviado al empleado (no el pago total al vendor).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from src.config import KICKBACK_MAX_PCT, KICKBACK_MIN_PCT, KICKBACK_WINDOW_DAYS
from src.detectors.base import Lead
from src.forensic.company import CompanyIdentity
from src.tools.estate_access import EstateDB


DETECTOR_ID = "kickback"


def find_leads(db: EstateDB, company: CompanyIdentity) -> list[Lead]:
    employees = db.buscar_empleados()
    emp_by_clabe = {e.bank_clabe: e for e in employees if e.bank_clabe}
    if not emp_by_clabe:
        return []
    vendors_all = db.buscar_proveedores()
    vendor_by_clabe = {v.bank_clabe: v for v in vendors_all if v.bank_clabe}

    all_txns = db.obtener_transferencias()
    company_to_vendor: dict[str, list] = defaultdict(list)
    for t in all_txns:
        if t.from_clabe == company.clabe and t.to_clabe in vendor_by_clabe:
            company_to_vendor[t.to_clabe].append(t)

    vendor_to_emp: list = [
        t for t in all_txns
        if t.from_clabe in vendor_by_clabe and t.to_clabe in emp_by_clabe
    ]
    if not company_to_vendor or not vendor_to_emp:
        return []

    leads: list[Lead] = []
    seen: set[tuple[str, str]] = set()
    for kick in sorted(vendor_to_emp, key=lambda x: (x.date, x.txn_id)):
        vendor = vendor_by_clabe.get(kick.from_clabe)
        emp = emp_by_clabe.get(kick.to_clabe)
        if vendor is None or emp is None:
            continue

        original = _find_original(company_to_vendor.get(kick.from_clabe, []), kick.date)
        if original is None:
            continue

        pct = kick.amount / original.amount if original.amount else 0
        if not (KICKBACK_MIN_PCT <= pct <= KICKBACK_MAX_PCT):
            continue

        key = (vendor.rfc, emp.emp_id)
        if key in seen:
            continue
        seen.add(key)

        pos = db.obtener_ordenes_compra(rfc_proveedor=vendor.rfc)
        reinforce_pos = [
            p for p in pos
            if p.approver in {emp.name, emp.emp_id}
            or p.requester in {emp.name, emp.emp_id}
        ]

        records: list[tuple[str, str]] = [
            ("bank_txns", original.txn_id),
            ("bank_txns", kick.txn_id),
            ("employees", emp.emp_id),
            ("vendors", vendor.rfc),
        ]
        for p in sorted(reinforce_pos, key=lambda x: x.po_id):
            records.append(("purchase_orders", p.po_id))

        reinforce_frag = (
            f", firmadas por el mismo empleado en {len(reinforce_pos)} PO(s)"
            if reinforce_pos else ""
        )
        reason = (
            f"El proveedor {vendor.rfc} recibio ${original.amount:,.2f} MXN de la "
            f"empresa el {original.date} y transfirio ${kick.amount:,.2f} MXN "
            f"({pct * 100:.1f}%) al empleado {emp.emp_id} ({emp.name}) el "
            f"{kick.date}{reinforce_frag}."
        )
        leads.append(Lead(
            detector_id=DETECTOR_ID,
            entity=f"RFC:{vendor.rfc}",
            signal="kickback_vendor_to_employee",
            reason=reason,
            suggested_records=tuple(records),
            monto_estimado=round(kick.amount, 2),
            detector_context=(
                ("vendor_rfc", vendor.rfc),
                ("employee_id", emp.emp_id),
                ("employee_name", emp.name),
                ("original_txn", original.txn_id),
                ("kickback_txn", kick.txn_id),
                ("original_amount", f"{original.amount:.2f}"),
                ("kickback_amount", f"{kick.amount:.2f}"),
                ("pct", f"{pct:.4f}"),
                ("reinforced_by_pos", str(len(reinforce_pos))),
            ),
        ))
    return leads


def _find_original(company_payments: list, kick_date: str):
    kd = _parse(kick_date)
    if kd is None or not company_payments:
        return None
    window_lo = kd - timedelta(days=KICKBACK_WINDOW_DAYS)
    best = None
    for t in company_payments:
        td = _parse(t.date)
        if td is None:
            continue
        if window_lo <= td <= kd:
            if best is None or td > _parse(best.date):
                best = t
    return best


def _parse(s: str):
    if not s or len(s) < 10:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None
