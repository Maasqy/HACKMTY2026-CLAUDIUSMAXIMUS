"""
src/tools/models.py

Typed, read-only row models for the 8 estate_schema.sql tables. These are the
only shapes the rest of src/ (detectors, scoring, investigator) should ever
see coming out of the database — never a raw sqlite3.Row, never a hand-rolled
dict with unchecked keys.

Nothing in this file, or anywhere under src/, imports eval/answers/ or
references the evaluation answer key by name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True, slots=True)
class Vendor:
    rfc: str
    legal_name: str
    registered_date: str
    address: str
    bank_clabe: str
    category: str
    contact_email: str


@dataclass(frozen=True, slots=True)
class Employee:
    emp_id: str          # "EMP:0001" — cite verbatim in Finding.entities
    name: str
    role: str
    bank_clabe: str
    hire_date: str


@dataclass(frozen=True, slots=True)
class Contract:
    contract_id: str
    vendor_rfc: str
    start_date: str
    value: float
    scope_text: str


@dataclass(frozen=True, slots=True)
class PurchaseOrder:
    po_id: str
    vendor_rfc: str
    date: str
    amount: float
    requester: str
    approver: str
    description: str


@dataclass(frozen=True, slots=True)
class Invoice:
    uuid: str             # CFDI UUID — cite verbatim in exhibits.record_id
    issuer_rfc: str
    receiver_rfc: str
    issue_date: str
    subtotal: float
    iva: float
    total: float
    concepto_text: str
    uso_cfdi: str
    forma_pago: str
    metodo_pago: str      # "PUE" | "PPD"
    status: str           # "vigente" | "cancelado"


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    entry_id: int
    date: str
    account_code: str
    account_name: str
    debit: float
    credit: float
    description: str
    invoice_uuid: Optional[str]
    cost_center: str
    approver: str


@dataclass(frozen=True, slots=True)
class BankTxn:
    txn_id: str
    date: str
    from_clabe: str
    to_clabe: str
    amount: float
    reference: str
    channel: str           # "SPEI" | "cheque" | "efectivo"


@dataclass(frozen=True, slots=True)
class EfosRecord:
    rfc: str
    legal_name: str
    status: str            # "definitivo" | "presunto"
    publication_date: str


@dataclass(frozen=True, slots=True)
class VendorProfile:
    """Composite, pre-aggregated view of a vendor — the kind of thing an
    investigator asks for first, instead of pulling five raw tables and
    joining them itself."""
    vendor: Optional[Vendor]
    en_lista_69b: Optional[EfosRecord]
    tiene_contrato: bool
    tiene_ordenes_compra: bool
    num_facturas: int
    monto_total_facturado: float
    facturas_sin_po_ni_contrato: int


@dataclass(frozen=True, slots=True)
class ClabeOwner:
    """Resolves whose account a CLABE is, inside this estate. Used to name
    the endpoints of a money trail in plain language instead of raw digits."""
    clabe: str
    owner_type: str        # "vendor" | "employee" | "company" | "unknown"
    owner_id: str          # rfc, emp_id, "COMPANY", or "" if unknown
    owner_name: str


@dataclass(frozen=True, slots=True)
class CompanyProfile:
    """The audited company itself, INFERRED from this estate's own data —
    the schema has no dedicated 'company' table, and this must never come
    from the ground truth file (which isn't reachable from src/ anyway).
    See EstateDB.identificar_empresa() for the inference rule. `confianza_*`
    is the fraction of the evidence base that supports each value, so a
    caller can sanity-check before trusting it on a very sparse estate."""
    rfc: str
    clabe: str
    confianza_rfc: float
    confianza_clabe: float
