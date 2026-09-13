"""Tests del pipeline zero-LLM: company, detectores, promoter, validator, run."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest

from src.detectors import efos_match, kickback, payment_wo_inv, threshold_splitting, run_all
from src.forensic.company import (
    CompanyDerivationConflict,
    CompanyIdentity,
    derive_company,
)
from src.forensic.promoter import promote
from src.forensic.validator import validate
from src.tools.estate_access import EstateDB


SCHEMA = """
CREATE TABLE vendors (
    rfc TEXT PRIMARY KEY, legal_name TEXT, registered_date TEXT,
    address TEXT, bank_clabe TEXT, category TEXT, contact_email TEXT
);
CREATE TABLE invoices (
    uuid TEXT PRIMARY KEY, issuer_rfc TEXT, receiver_rfc TEXT,
    issue_date TEXT, subtotal REAL, iva REAL, total REAL,
    concepto_text TEXT, uso_cfdi TEXT, forma_pago TEXT,
    metodo_pago TEXT, status TEXT
);
CREATE TABLE ledger (
    entry_id INTEGER PRIMARY KEY, date TEXT, account_code TEXT,
    account_name TEXT, debit REAL, credit REAL, description TEXT,
    invoice_uuid TEXT, cost_center TEXT, approver TEXT
);
CREATE TABLE bank_txns (
    txn_id TEXT PRIMARY KEY, date TEXT, from_clabe TEXT,
    to_clabe TEXT, amount REAL, reference TEXT, channel TEXT
);
CREATE TABLE purchase_orders (
    po_id TEXT PRIMARY KEY, vendor_rfc TEXT, date TEXT, amount REAL,
    requester TEXT, approver TEXT, description TEXT
);
CREATE TABLE contracts (
    contract_id TEXT PRIMARY KEY, vendor_rfc TEXT, start_date TEXT,
    value REAL, scope_text TEXT
);
CREATE TABLE employees (
    emp_id TEXT PRIMARY KEY, name TEXT, role TEXT,
    bank_clabe TEXT, hire_date TEXT
);
CREATE TABLE efos_list (
    rfc TEXT PRIMARY KEY, legal_name TEXT, status TEXT, publication_date TEXT
);
"""

COMPANY_RFC = "UDA230508OIG"
COMPANY_CLABE = "999999999999999999"
EFOS_DEF_PRE = "PRE010101AA1"
EFOS_DEF_POST = "POS020202BB2"
EFOS_PRESUNTO = "PRE030303CC3"
EFOS_DESVIRTUADO = "DES040404DD4"
EFOS_SENT_FAV = "SEN050505EE5"
NORMAL_VENDOR = "NRM060606FF6"


def _seed_estate(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT INTO vendors (rfc, legal_name, bank_clabe, category, registered_date) VALUES (?,?,?,?,?)",
        [
            # Fresco (< 90d de primera factura): flag de materialidad se dispara.
            (EFOS_DEF_PRE, "Proveedor EFOS Pre S.A.", "000000000000000001", "Servicios", "2026-04-01"),
            (EFOS_DEF_POST, "Proveedor EFOS Post S.A.", "000000000000000002", "Servicios", "2020-01-01"),
            (EFOS_PRESUNTO, "Proveedor Presunto S.A.", "000000000000000003", "Servicios", "2020-01-01"),
            (EFOS_DESVIRTUADO, "Proveedor Desvirtuado S.A.", "000000000000000005", "Servicios", "2020-01-01"),
            (EFOS_SENT_FAV, "Proveedor Sentencia Favorable S.A.", "000000000000000006", "Servicios", "2020-01-01"),
            (NORMAL_VENDOR, "Proveedor Normal S.A.", "000000000000000004", "Consultoria", "2020-01-01"),
        ],
    )
    conn.executemany(
        "INSERT INTO efos_list (rfc, legal_name, status, publication_date) VALUES (?,?,?,?)",
        [
            (EFOS_DEF_PRE, "Proveedor EFOS Pre S.A.", "definitivo", "2025-01-15"),
            (EFOS_DEF_POST, "Proveedor EFOS Post S.A.", "definitivo", "2026-12-31"),
            (EFOS_PRESUNTO, "Proveedor Presunto S.A.", "presunto", "2025-06-01"),
            (EFOS_DESVIRTUADO, "Proveedor Desvirtuado S.A.", "desvirtuado", "2025-08-01"),
            (EFOS_SENT_FAV, "Proveedor Sentencia Favorable S.A.", "sentencia_favorable", "2025-09-01"),
        ],
    )
    invoices = [
        (f"INV-COMP-{i:04d}", NORMAL_VENDOR, COMPANY_RFC, f"2026-03-{(i % 27) + 1:02d}",
         0, 0, 10000.00, "", "G03", "03", "PUE", "vigente")
        for i in range(1, 61)
    ]
    invoices += [
        ("INV-PRE-001", EFOS_DEF_PRE, COMPANY_RFC, "2026-04-10", 0, 0, 500000.00, "", "G03", "03", "PUE", "vigente"),
        ("INV-POST-001", EFOS_DEF_POST, COMPANY_RFC, "2026-01-10", 0, 0, 100000.00, "", "G03", "03", "PUE", "vigente"),
        ("INV-PSU-001", EFOS_PRESUNTO, COMPANY_RFC, "2026-05-10", 0, 0, 80000.00, "", "G03", "03", "PUE", "vigente"),
        ("INV-DES-001", EFOS_DESVIRTUADO, COMPANY_RFC, "2026-05-10", 0, 0, 70000.00, "", "G03", "03", "PUE", "vigente"),
        ("INV-SEN-001", EFOS_SENT_FAV, COMPANY_RFC, "2026-05-10", 0, 0, 65000.00, "", "G03", "03", "PUE", "vigente"),
        ("INV-EMI-001", COMPANY_RFC, NORMAL_VENDOR, "2026-06-15", 0, 0, 5000.00, "", "G03", "03", "PUE", "vigente"),
        ("INV-NRM-JUN", NORMAL_VENDOR, COMPANY_RFC, "2026-06-05", 0, 0, 20000.00, "", "G03", "03", "PUE", "vigente"),
    ]
    conn.executemany(
        """INSERT INTO invoices
        (uuid, issuer_rfc, receiver_rfc, issue_date, subtotal, iva, total,
         concepto_text, uso_cfdi, forma_pago, metodo_pago, status)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        invoices,
    )
    bank_txns = [
        ("BNK-PRE-001", "2026-04-15", COMPANY_CLABE, "000000000000000001", 500000.00, "Pago", "SPEI"),
        ("BNK-POST-001", "2026-01-15", COMPANY_CLABE, "000000000000000002", 100000.00, "Pago", "SPEI"),
        ("BNK-DES-001", "2026-05-15", COMPANY_CLABE, "000000000000000005", 70000.00, "Pago", "SPEI"),
        ("BNK-SEN-001", "2026-05-15", COMPANY_CLABE, "000000000000000006", 65000.00, "Pago", "SPEI"),
        ("BNK-NRM-JUN", "2026-06-08", COMPANY_CLABE, "000000000000000004", 20000.00, "Pago", "SPEI"),
        ("BNK-NRM-JUL", "2026-07-15", COMPANY_CLABE, "000000000000000004", 45000.00, "Pago", "SPEI"),
    ]
    for i in range(30):
        bank_txns.append(
            (f"BNK-DOM-{i:03d}", f"2026-03-{(i % 27) + 1:02d}",
             COMPANY_CLABE, "000000000000000004", 5000.00, "", "SPEI")
        )
    conn.executemany(
        """INSERT INTO bank_txns
        (txn_id, date, from_clabe, to_clabe, amount, reference, channel)
        VALUES (?,?,?,?,?,?,?)""",
        bank_txns,
    )
    conn.commit()


@contextmanager
def _estate() -> Iterator[EstateDB]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _seed_estate(conn)
    db = EstateDB.__new__(EstateDB)
    db.path = Path(":memory:")
    db._conn = conn
    try:
        yield db
    finally:
        conn.close()


def _company() -> CompanyIdentity:
    return CompanyIdentity(rfc=COMPANY_RFC, clabe=COMPANY_CLABE, evidence="(fixture)")


def test_derive_company_picks_dominant_receiver_and_clabe() -> None:
    with _estate() as db:
        c = derive_company(db)
    assert c.rfc == COMPANY_RFC
    assert c.clabe == COMPANY_CLABE


def test_derive_company_conflict_when_top_from_clabe_is_a_vendor() -> None:
    with _estate() as db:
        db._conn.execute(
            "INSERT INTO bank_txns (txn_id, date, from_clabe, to_clabe, amount, channel)"
            " VALUES ('X', '2026-01-01', '000000000000000001', 'z', 999999999.00, 'SPEI')"
        )
        db._conn.commit()
        with pytest.raises(CompanyDerivationConflict):
            derive_company(db)


def test_efos_match_emits_one_lead_per_efos_with_invoices() -> None:
    with _estate() as db:
        leads = efos_match.find_leads(db, _company())
    entities = sorted(l.entity for l in leads)
    assert entities == sorted([
        f"RFC:{EFOS_DEF_POST}", f"RFC:{EFOS_DEF_PRE}", f"RFC:{EFOS_PRESUNTO}",
        f"RFC:{EFOS_DESVIRTUADO}", f"RFC:{EFOS_SENT_FAV}",
    ])


def test_payment_wo_invoice_flags_month_without_matching_invoice() -> None:
    with _estate() as db:
        leads = payment_wo_inv.find_leads(db, _company())
    months = {dict(l.detector_context)["month"] for l in leads}
    assert "2026-07" in months
    assert "2026-06" not in months


def test_promoter_rejects_efos_presunto() -> None:
    with _estate() as db:
        lead = next(l for l in efos_match.find_leads(db, _company()) if l.entity == f"RFC:{EFOS_PRESUNTO}")
        result = promote(lead, db, _company())
    assert result.candidate is None
    assert "presunto" in result.reason


def test_promoter_rejects_efos_desvirtuado_as_exonerado() -> None:
    with _estate() as db:
        lead = next(l for l in efos_match.find_leads(db, _company()) if l.entity == f"RFC:{EFOS_DESVIRTUADO}")
        result = promote(lead, db, _company())
    assert result.candidate is None
    assert "exonerado" in result.reason or "desvirtuado" in result.reason


def test_promoter_rejects_efos_sentencia_favorable_as_exonerado() -> None:
    with _estate() as db:
        lead = next(l for l in efos_match.find_leads(db, _company()) if l.entity == f"RFC:{EFOS_SENT_FAV}")
        result = promote(lead, db, _company())
    assert result.candidate is None
    assert "exonerado" in result.reason or "sentencia_favorable" in result.reason


def test_promoter_promotes_efos_definitivo_with_operations_after_publication() -> None:
    """El caso normal: publicacion posterior a las facturas. Efecto retroactivo."""
    with _estate() as db:
        lead = next(l for l in efos_match.find_leads(db, _company()) if l.entity == f"RFC:{EFOS_DEF_POST}")
        result = promote(lead, db, _company())
    # POST fixture: pub=2026-12-31, first_op=2026-01-10. All ops pre publication.
    # Vendor no tiene registered_date "fresco", pero sin contrato+sin PO ya son 2 flags.
    assert result.candidate is not None
    cand = result.candidate
    assert cand["scheme_type"] == "phantom_vendor"
    assert "retroactivo" in cand["narrative"].lower()
    assert "69-B" in cand["rule_broken"]
    with _estate() as db:
        assert validate(cand, db).aprobado


def test_promoter_promotes_efos_definitivo_with_materiality() -> None:
    with _estate() as db:
        lead = next(l for l in efos_match.find_leads(db, _company()) if l.entity == f"RFC:{EFOS_DEF_PRE}")
        result = promote(lead, db, _company())
        assert result.candidate is not None
        cand = result.candidate
        assert cand["entities"] == [f"RFC:{EFOS_DEF_PRE}"]
        assert len(cand["exhibits"]) >= 3
        assert len(cand["money_trail"]) >= 1
        assert validate(cand, db).aprobado


def test_promoter_rejects_efos_definitivo_with_insufficient_materiality() -> None:
    """Un EFOS definitivo con contrato + PO + no fresco + concepto claro no
    dispara flags suficientes: se queda como lead."""
    with _estate() as db:
        conn = db._conn
        conn.execute(
            "INSERT INTO contracts (contract_id, vendor_rfc, start_date, value, scope_text)"
            " VALUES ('CTR-PRE', ?, '2025-11-01', 500000, 'contrato marco especifico')",
            (EFOS_DEF_PRE,),
        )
        conn.execute(
            "INSERT INTO purchase_orders (po_id, vendor_rfc, date, amount, requester, approver, description)"
            " VALUES ('PO-PRE', ?, '2026-04-05', 500000, 'req', 'apv', 'servicio concreto')",
            (EFOS_DEF_PRE,),
        )
        # Reset registered_date lejos para quitar el flag de freshness.
        conn.execute("UPDATE vendors SET registered_date='2020-01-01' WHERE rfc=?", (EFOS_DEF_PRE,))
        conn.commit()
        lead = next(l for l in efos_match.find_leads(db, _company()) if l.entity == f"RFC:{EFOS_DEF_PRE}")
        result = promote(lead, db, _company())
    assert result.candidate is None
    assert "materialidad" in result.reason.lower()


def test_promoter_refuses_non_efos_leads() -> None:
    with _estate() as db:
        leads = payment_wo_inv.find_leads(db, _company())
        assert leads
        result = promote(leads[0], db, _company())
    assert result.candidate is None


def _valid_candidate() -> dict:
    return {
        "scheme_type": "phantom_vendor",
        "entities": [f"RFC:{EFOS_DEF_PRE}"],
        "narrative": "El proveedor esta en 69-B definitivo antes de operar.",
        "rule_broken": "SAT Articulo 69-B: operacion con EFOS definitivo publicado antes.",
        "peso_amount": 500000.00,
        "exhibits": [
            {"exhibit_id": "E1", "source_table": "efos_list", "record_id": EFOS_DEF_PRE, "note": "n"},
            {"exhibit_id": "E2", "source_table": "invoices", "record_id": "INV-PRE-001", "note": "n"},
            {"exhibit_id": "E3", "source_table": "bank_txns", "record_id": "BNK-PRE-001", "note": "n"},
        ],
        "money_trail": [
            {"from": f"RFC:{COMPANY_RFC}", "to": f"RFC:{EFOS_DEF_PRE}",
             "amount": 500000.00, "date": "2026-04-15", "exhibit_id": "E3"},
        ],
        "confidence": "proven",
    }


def test_validator_accepts_well_formed_candidate() -> None:
    with _estate() as db:
        assert validate(_valid_candidate(), db).aprobado


def test_validator_rejects_when_below_min_exhibits() -> None:
    c = _valid_candidate()
    c["exhibits"] = c["exhibits"][:2]
    with _estate() as db:
        v = validate(c, db)
    assert not v.aprobado and "minimo" in v.motivo


def test_validator_rejects_when_no_amount_table_cited() -> None:
    c = _valid_candidate()
    c["exhibits"] = [
        {"exhibit_id": "E1", "source_table": "efos_list", "record_id": EFOS_DEF_PRE, "note": "n"},
        {"exhibit_id": "E2", "source_table": "vendors", "record_id": EFOS_DEF_PRE, "note": "n"},
        {"exhibit_id": "E3", "source_table": "vendors", "record_id": NORMAL_VENDOR, "note": "n"},
    ]
    with _estate() as db:
        v = validate(c, db)
    assert not v.aprobado and "monto" in v.motivo


def test_validator_rejects_hallucinated_record_id() -> None:
    c = _valid_candidate()
    c["exhibits"][1] = {"exhibit_id": "E2", "source_table": "invoices",
                        "record_id": "INV-INEXISTENTE", "note": "n"}
    with _estate() as db:
        v = validate(c, db)
    assert not v.aprobado and "no existe" in v.motivo


def test_validator_rejects_peso_amount_out_of_tolerance() -> None:
    c = _valid_candidate()
    c["peso_amount"] = 100000.00
    with _estate() as db:
        v = validate(c, db)
    assert not v.aprobado and "reconcilia" in v.motivo


def test_validator_rejects_statistical_rule_broken() -> None:
    c = _valid_candidate()
    c["rule_broken"] = "outlier estadistico en el gasto mensual"
    with _estate() as db:
        v = validate(c, db)
    assert not v.aprobado and "estadistico" in v.motivo


def test_validator_rejects_over_word_narrative() -> None:
    c = _valid_candidate()
    c["narrative"] = " ".join(["palabra"] * 200)
    with _estate() as db:
        v = validate(c, db)
    assert not v.aprobado and "palabras" in v.motivo


def test_validator_rejects_unsupported_entity() -> None:
    c = _valid_candidate()
    c["entities"] = [f"RFC:{EFOS_DEF_PRE}", "EMP:9999"]
    with _estate() as db:
        v = validate(c, db)
    assert not v.aprobado and "EMP:9999" in v.motivo


def test_kickback_positive_promotes_to_finding() -> None:
    """Vendor->empleado 5%, empresa->vendor con la misma ventana, empleado en la PO."""
    with _estate() as db:
        conn = db._conn
        conn.execute(
            "INSERT INTO employees (emp_id, name, role, bank_clabe, hire_date)"
            " VALUES ('EMP:KICK', 'Empleado Kick', 'Comprador', '000000000000000777', '2022-01-01')"
        )
        conn.execute(
            "INSERT INTO purchase_orders (po_id, vendor_rfc, date, amount, requester, approver, description)"
            " VALUES ('PO-KICK-1', ?, '2026-09-01', 200000, 'Empleado Kick', 'Empleado Kick', 'servicios')",
            (NORMAL_VENDOR,),
        )
        conn.executemany(
            "INSERT INTO bank_txns (txn_id, date, from_clabe, to_clabe, amount, reference, channel) VALUES (?,?,?,?,?,?,?)",
            [
                ("BNK-KICK-1", "2026-09-05", COMPANY_CLABE, "000000000000000004", 200000.00, "Pago PO", "SPEI"),
                ("BNK-KICK-2", "2026-09-07", "000000000000000004", "000000000000000777", 10000.00, "gracias", "SPEI"),
            ],
        )
        conn.commit()
        leads = kickback.find_leads(db, _company())
        entities = [l.entity for l in leads]
        assert f"RFC:{NORMAL_VENDOR}" in entities
        lead = next(l for l in leads if l.entity == f"RFC:{NORMAL_VENDOR}")
        result = promote(lead, db, _company())
    assert result.candidate is not None
    cand = result.candidate
    assert cand["scheme_type"] == "kickback"
    assert f"EMP:KICK" in cand["entities"] or "EMP:KICK" in " ".join(cand["entities"])
    assert cand["peso_amount"] == 10000.00
    with _estate() as db2:
        conn = db2._conn
        conn.execute(
            "INSERT INTO employees (emp_id, name, role, bank_clabe, hire_date)"
            " VALUES ('EMP:KICK', 'Empleado Kick', 'Comprador', '000000000000000777', '2022-01-01')"
        )
        conn.execute(
            "INSERT INTO purchase_orders (po_id, vendor_rfc, date, amount, requester, approver, description)"
            " VALUES ('PO-KICK-1', ?, '2026-09-01', 200000, 'Empleado Kick', 'Empleado Kick', 'servicios')",
            (NORMAL_VENDOR,),
        )
        conn.executemany(
            "INSERT INTO bank_txns (txn_id, date, from_clabe, to_clabe, amount, reference, channel) VALUES (?,?,?,?,?,?,?)",
            [
                ("BNK-KICK-1", "2026-09-05", COMPANY_CLABE, "000000000000000004", 200000.00, "Pago PO", "SPEI"),
                ("BNK-KICK-2", "2026-09-07", "000000000000000004", "000000000000000777", 10000.00, "gracias", "SPEI"),
            ],
        )
        conn.commit()
        assert validate(cand, db2).aprobado


def test_kickback_negative_pct_out_of_range() -> None:
    """95% no es kickback plausible: la senal no dispara."""
    with _estate() as db:
        conn = db._conn
        conn.execute(
            "INSERT INTO employees (emp_id, name, role, bank_clabe, hire_date)"
            " VALUES ('EMP:BIG', 'X', 'Y', '000000000000000888', '2022-01-01')"
        )
        conn.executemany(
            "INSERT INTO bank_txns (txn_id, date, from_clabe, to_clabe, amount, reference, channel) VALUES (?,?,?,?,?,?,?)",
            [
                ("BNK-BIG-1", "2026-09-05", COMPANY_CLABE, "000000000000000004", 100000.00, "", "SPEI"),
                ("BNK-BIG-2", "2026-09-07", "000000000000000004", "000000000000000888", 95000.00, "", "SPEI"),
            ],
        )
        conn.commit()
        leads = kickback.find_leads(db, _company())
    assert not any(dict(l.detector_context).get("employee_id") == "EMP:BIG" for l in leads)


def test_kickback_negative_no_reinforcing_po_stays_lead() -> None:
    """Sin PO firmada por el empleado, el promoter no acusa."""
    with _estate() as db:
        conn = db._conn
        conn.execute(
            "INSERT INTO employees (emp_id, name, role, bank_clabe, hire_date)"
            " VALUES ('EMP:NR', 'Sin Refuerzo', 'X', '000000000000000999', '2022-01-01')"
        )
        conn.executemany(
            "INSERT INTO bank_txns (txn_id, date, from_clabe, to_clabe, amount, reference, channel) VALUES (?,?,?,?,?,?,?)",
            [
                ("BNK-NR-1", "2026-09-05", COMPANY_CLABE, "000000000000000004", 100000.00, "", "SPEI"),
                ("BNK-NR-2", "2026-09-07", "000000000000000004", "000000000000000999", 5000.00, "", "SPEI"),
            ],
        )
        conn.commit()
        leads = kickback.find_leads(db, _company())
        lead = next(l for l in leads if dict(l.detector_context).get("employee_id") == "EMP:NR")
        result = promote(lead, db, _company())
    assert result.candidate is None
    assert "refuerzo" in result.reason or "approver" in result.reason or "requester" in result.reason


def test_threshold_splitting_positive_case() -> None:
    """3+ POs bajo el limite, ventana <=15d, suma rebasa limite: lead."""
    with _estate() as db:
        conn = db._conn
        conn.executemany(
            """INSERT INTO purchase_orders
            (po_id, vendor_rfc, date, amount, requester, approver, description)
            VALUES (?,?,?,?,?,?,?)""",
            [
                ("PO-SPL-1", NORMAL_VENDOR, "2026-08-01", 40000, "req", "aprovador-x", "servicios"),
                ("PO-SPL-2", NORMAL_VENDOR, "2026-08-05", 45000, "req", "aprovador-x", "servicios"),
                ("PO-SPL-3", NORMAL_VENDOR, "2026-08-10", 48000, "req", "aprovador-x", "servicios"),
            ],
        )
        conn.commit()
        leads = threshold_splitting.find_leads(db, _company())
    entities = [l.entity for l in leads]
    assert f"RFC:{NORMAL_VENDOR}" in entities
    lead = next(l for l in leads if l.entity == f"RFC:{NORMAL_VENDOR}")
    assert dict(lead.detector_context)["same_approver"] == "true"
    assert dict(lead.detector_context)["num_pos"] == "3"


def test_threshold_splitting_negative_case_below_min_pos() -> None:
    """Solo 2 POs no dispara aunque suma rebase el limite."""
    with _estate() as db:
        conn = db._conn
        conn.executemany(
            """INSERT INTO purchase_orders
            (po_id, vendor_rfc, date, amount, requester, approver, description)
            VALUES (?,?,?,?,?,?,?)""",
            [
                ("PO-DOS-1", NORMAL_VENDOR, "2026-08-01", 40000, "r", "a", ""),
                ("PO-DOS-2", NORMAL_VENDOR, "2026-08-02", 40000, "r", "a", ""),
            ],
        )
        conn.commit()
        leads = threshold_splitting.find_leads(db, _company())
    assert not any(l.entity == f"RFC:{NORMAL_VENDOR}" for l in leads)


def test_threshold_splitting_stays_as_lead_not_finding() -> None:
    """Por politica del plan: threshold_splitting sube falsas -> lead only."""
    with _estate() as db:
        conn = db._conn
        conn.executemany(
            """INSERT INTO purchase_orders
            (po_id, vendor_rfc, date, amount, requester, approver, description)
            VALUES (?,?,?,?,?,?,?)""",
            [
                ("PO-LDN-1", NORMAL_VENDOR, "2026-08-01", 40000, "r", "a", ""),
                ("PO-LDN-2", NORMAL_VENDOR, "2026-08-05", 45000, "r", "a", ""),
                ("PO-LDN-3", NORMAL_VENDOR, "2026-08-10", 48000, "r", "a", ""),
            ],
        )
        conn.commit()
        leads = threshold_splitting.find_leads(db, _company())
        lead = next(l for l in leads if l.entity == f"RFC:{NORMAL_VENDOR}")
        result = promote(lead, db, _company())
    assert result.candidate is None
    assert "revision manual" in result.reason or "no tiene promoter" in result.reason


def test_run_all_orders_leads_stably() -> None:
    with _estate() as db:
        leads_a = run_all(db, _company())
        leads_b = run_all(db, _company())
    key_a = [(l.detector_id, l.entity, l.signal) for l in leads_a]
    key_b = [(l.detector_id, l.entity, l.signal) for l in leads_b]
    assert key_a == key_b == sorted(key_a)


def test_two_runs_produce_identical_submission_content(tmp_path: Path) -> None:
    from src.run import main as run_main
    estate = Path("data/estates/estate_0200.db")
    if not estate.exists():
        pytest.skip("estate_0200 no disponible")
    out_a = tmp_path / "a.json"
    out_b = tmp_path / "b.json"
    assert run_main(["--estate", str(estate), "--out", str(out_a)]) == 0
    assert run_main(["--estate", str(estate), "--out", str(out_b)]) == 0
    sub_a = json.loads(out_a.read_text(encoding="utf-8"))
    sub_b = json.loads(out_b.read_text(encoding="utf-8"))
    for k in ("seed", "findings", "leads_not_pursued"):
        assert sub_a[k] == sub_b[k]
