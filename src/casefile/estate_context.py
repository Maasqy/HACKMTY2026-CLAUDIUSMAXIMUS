"""Read-only SQLite context over the estate.

Purpose: derive the company RFC and audit period from real data, look up
invoice/bank_txn/vendor rows referenced by exhibit record_ids, and expose those
to the trail builder. All queries are strictly read-only.

Absent estate: every method returns None / empty containers; callers fall back
to defaults with no exception.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional


@dataclass(frozen=True)
class InvoiceRow:
    uuid: str
    issuer_rfc: str
    receiver_rfc: str
    issue_date: str
    total: float


@dataclass(frozen=True)
class BankTxnRow:
    txn_id: str
    date: str
    from_clabe: str
    to_clabe: str
    amount: float


@dataclass(frozen=True)
class VendorRow:
    rfc: str
    legal_name: Optional[str]
    bank_clabe: Optional[str]


class EstateContext:
    """Wraps a sqlite3 connection to the estate .db opened read-only."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @classmethod
    @contextmanager
    def open(cls, path: Optional[Path]) -> Iterator[Optional["EstateContext"]]:
        if path is None:
            yield None
            return
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            conn.row_factory = sqlite3.Row
            yield cls(conn)
        finally:
            conn.close()

    def derive_company_rfc(self) -> Optional[str]:
        row = self._conn.execute(
            """
            SELECT receiver_rfc, COUNT(*) AS n
            FROM invoices
            WHERE receiver_rfc IS NOT NULL AND receiver_rfc <> ''
            GROUP BY receiver_rfc
            ORDER BY n DESC, receiver_rfc ASC
            LIMIT 1
            """
        ).fetchone()
        return row["receiver_rfc"] if row else None

    def derive_audit_period(self) -> Optional[str]:
        row = self._conn.execute(
            "SELECT MIN(issue_date) AS lo, MAX(issue_date) AS hi FROM invoices"
        ).fetchone()
        if row is None or row["lo"] is None or row["hi"] is None:
            return None
        return f"{row['lo']}/{row['hi']}"

    def lookup_invoice(self, record_id: str) -> Optional[InvoiceRow]:
        row = self._conn.execute(
            """
            SELECT uuid, issuer_rfc, receiver_rfc, issue_date, total
            FROM invoices WHERE uuid = ?
            """,
            (record_id,),
        ).fetchone()
        if row is None:
            return None
        return InvoiceRow(
            uuid=row["uuid"],
            issuer_rfc=row["issuer_rfc"] or "",
            receiver_rfc=row["receiver_rfc"] or "",
            issue_date=row["issue_date"] or "",
            total=float(row["total"] or 0.0),
        )

    def lookup_bank_txn(self, record_id: str) -> Optional[BankTxnRow]:
        row = self._conn.execute(
            """
            SELECT txn_id, date, from_clabe, to_clabe, amount
            FROM bank_txns WHERE txn_id = ?
            """,
            (record_id,),
        ).fetchone()
        if row is None:
            return None
        return BankTxnRow(
            txn_id=row["txn_id"],
            date=row["date"] or "",
            from_clabe=row["from_clabe"] or "",
            to_clabe=row["to_clabe"] or "",
            amount=float(row["amount"] or 0.0),
        )

    def lookup_vendor(self, rfc: str) -> Optional[VendorRow]:
        row = self._conn.execute(
            "SELECT rfc, legal_name, bank_clabe FROM vendors WHERE rfc = ?",
            (rfc,),
        ).fetchone()
        if row is None:
            return None
        return VendorRow(
            rfc=row["rfc"],
            legal_name=row["legal_name"],
            bank_clabe=row["bank_clabe"],
        )

    def vendor_by_clabe(self, clabe: str) -> Optional[VendorRow]:
        row = self._conn.execute(
            "SELECT rfc, legal_name, bank_clabe FROM vendors WHERE bank_clabe = ?",
            (clabe,),
        ).fetchone()
        if row is None:
            return None
        return VendorRow(
            rfc=row["rfc"],
            legal_name=row["legal_name"],
            bank_clabe=row["bank_clabe"],
        )
