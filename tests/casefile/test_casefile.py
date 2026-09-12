"""Case file renderer tests.

Covers: loader, trail fallback branches, revenue_inflation post-rule,
byte-identical determinism, empty-findings dignity.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from src.casefile import load_case_file, render_html, render_md
from src.casefile import trail as trail_mod
from src.casefile.estate_context import EstateContext
from src.casefile.model import Exhibit, TrailStep

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLE = FIXTURES / "submission_example.json"
EMPTY = FIXTURES / "submission_empty.json"


# In-memory estate so trail fallback and reconciliation have real data.

_SCHEMA = """
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
CREATE TABLE bank_txns (
    txn_id TEXT PRIMARY KEY, date TEXT, from_clabe TEXT,
    to_clabe TEXT, amount REAL, reference TEXT, channel TEXT
);
"""


@contextmanager
def _in_memory_estate() -> Iterator[EstateContext]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.executemany(
        "INSERT INTO vendors (rfc, legal_name, bank_clabe) VALUES (?, ?, ?)",
        [
            ("GRUP870101ABC", "Grupo Meridiana S.A. de C.V.", "000000000000000099"),
            ("AAAA010101AA1", "Proveedor Alpha S.A. de C.V.", "000000000000000001"),
            ("CLIE990909XYZ", "Cliente Beta S.A.", "000000000000000200"),
        ],
    )
    conn.executemany(
        """INSERT INTO invoices
        (uuid, issuer_rfc, receiver_rfc, issue_date, subtotal, iva, total,
         concepto_text, uso_cfdi, forma_pago, metodo_pago, status)
        VALUES (?, ?, ?, ?, 0, 0, ?, '', '', '', '', 'vigente')""",
        [
            ("INV-00042", "AAAA010101AA1", "GRUP870101ABC", "2026-02-15", 1200000.00),
            ("INV-00301", "GRUP870101ABC", "CLIE990909XYZ", "2026-05-10", 350000.00),
            ("INV-00302", "GRUP870101ABC", "CLIE990909XYZ", "2026-06-01", 500000.00),
        ],
    )
    conn.executemany(
        """INSERT INTO bank_txns
        (txn_id, date, from_clabe, to_clabe, amount, reference, channel)
        VALUES (?, ?, ?, ?, ?, '', 'SPEI')""",
        [
            ("BNK-00099", "2026-02-15", "000000000000000099", "000000000000000001", 1200000.00),
            ("BNK-00100", "2026-02-15", "000000000000000001", "000000000000000501", 288000.00),
        ],
    )
    conn.commit()
    try:
        yield EstateContext(conn)
    finally:
        conn.close()


# --- Loader / summary -------------------------------------------------------


def test_loader_builds_summary_and_confidence_breakdown() -> None:
    with _in_memory_estate() as ctx:
        case = load_case_file(
            EXAMPLE, ctx,
            company_flag="Grupo Meridiana, S.A. de C.V.",
            period_flag=None,
        )
    assert case.header.company_name == "Grupo Meridiana, S.A. de C.V."
    assert case.header.deterministic is True
    assert case.header.llm_calls == 24
    assert case.header.period_source == "derived"
    assert case.summary.findings_total == 2
    assert dict(case.summary.findings_by_confidence) == {"probable": 1, "proven": 1}
    assert case.summary.leads_investigated == 2


def test_loader_period_source_default_when_no_estate() -> None:
    case = load_case_file(EXAMPLE, ctx=None, company_flag=None, period_flag=None)
    assert case.header.period_source == "default"
    assert case.header.audit_period == "periodo no especificado"


def test_loader_reads_tool_calls_and_closed_by() -> None:
    case = load_case_file(EXAMPLE, ctx=None, company_flag=None, period_flag=None)
    lead0 = case.leads_not_pursued[0]
    assert lead0.tool_calls_made == (
        "get_invoices_by_vendor", "get_efos_status", "get_ledger_by_invoice",
    )
    assert lead0.closed_by == "investigator"


def test_loader_adversarial_present_and_absent() -> None:
    case = load_case_file(EXAMPLE, ctx=None, company_flag=None, period_flag=None)
    assert case.findings[0].adversarial_review is not None
    assert case.findings[1].adversarial_review is None


# --- Trail fallback --------------------------------------------------------


def test_trail_from_explicit_steps_preserves_order() -> None:
    with _in_memory_estate() as ctx:
        case = load_case_file(EXAMPLE, ctx, company_flag=None, period_flag=None)
    kickback = case.findings[0]
    graph = kickback.trail_graph
    assert len(graph.edges) == 2
    assert graph.edges[0].from_id == "RFC_GRUP870101ABC"
    assert graph.edges[0].to_id == "RFC_AAAA010101AA1"
    assert graph.edges[1].from_id == "RFC_AAAA010101AA1"
    assert graph.edges[1].to_id == "EMP_0007"


def test_trail_empty_when_no_monetary_exhibits() -> None:
    exhibits = (
        Exhibit(exhibit_id="X1", source_table="employees", record_id="EMP:0001", note="n"),
        Exhibit(exhibit_id="X2", source_table="contracts", record_id="CTR-01", note="n"),
        Exhibit(exhibit_id="X3", source_table="purchase_orders", record_id="PO-01", note="n"),
    )
    graph = trail_mod.build("kickback", exhibits, trail_steps=(), ctx=None)
    assert graph.nodes == () and graph.edges == ()
    assert graph.empty_reason and "documental" in graph.empty_reason


def test_trail_fallback_from_invoices_and_bank_txns() -> None:
    exhibits = (
        Exhibit(exhibit_id="E1", source_table="invoices", record_id="INV-00042", note="."),
        Exhibit(exhibit_id="E2", source_table="bank_txns", record_id="BNK-00099", note="."),
    )
    with _in_memory_estate() as ctx:
        graph = trail_mod.build("kickback", exhibits, trail_steps=(), ctx=ctx)
    styles = sorted(e.style for e in graph.edges)
    assert styles == ["solid", "solid"]
    assert any("facturas" in e.label for e in graph.edges)
    assert any("liquidaciones" in e.label for e in graph.edges)


def test_trail_fallback_only_invoices_produces_one_solid_edge() -> None:
    exhibits = (
        Exhibit(exhibit_id="F1", source_table="invoices", record_id="INV-00301", note="."),
        Exhibit(exhibit_id="F2", source_table="invoices", record_id="INV-00302", note="."),
    )
    with _in_memory_estate() as ctx:
        graph = trail_mod.build("phantom_vendor", exhibits, trail_steps=(), ctx=ctx)
    assert any(e.style == "solid" and "facturas" in e.label for e in graph.edges)


# --- revenue_inflation post-rule -------------------------------------------


def test_revenue_inflation_dashes_explicit_trail_edge_when_no_bank_backing() -> None:
    exhibits = (
        Exhibit(exhibit_id="F1", source_table="invoices", record_id="INV-00301", note="."),
        Exhibit(exhibit_id="F2", source_table="invoices", record_id="INV-00302", note="."),
        Exhibit(exhibit_id="F3", source_table="ledger", record_id="LDG-04412", note="."),
    )
    trail_steps = (
        TrailStep(
            from_entity="RFC:GRUP870101ABC",
            to_entity="RFC:CLIE990909XYZ",
            amount=850000.00,
            date="2026-06-01",
            exhibit_id="F1",
        ),
    )
    with _in_memory_estate() as ctx:
        graph = trail_mod.build("revenue_inflation", exhibits, trail_steps, ctx=ctx)
    assert len(graph.edges) == 1
    assert graph.edges[0].style == "dashed"
    assert "facturado no cobrado" in graph.edges[0].label


def test_revenue_inflation_keeps_solid_when_bank_leg_present() -> None:
    exhibits = (
        Exhibit(exhibit_id="E1", source_table="invoices", record_id="INV-00042", note="."),
        Exhibit(exhibit_id="E2", source_table="bank_txns", record_id="BNK-00099", note="."),
    )
    trail_steps = (
        TrailStep(
            from_entity="RFC:GRUP870101ABC",
            to_entity="RFC:AAAA010101AA1",
            amount=1200000.00,
            date="2026-02-15",
            exhibit_id="E1",
        ),
        TrailStep(
            from_entity="RFC:GRUP870101ABC",
            to_entity="RFC:AAAA010101AA1",
            amount=1200000.00,
            date="2026-02-15",
            exhibit_id="E2",
        ),
    )
    with _in_memory_estate() as ctx:
        graph = trail_mod.build("revenue_inflation", exhibits, trail_steps, ctx=ctx)
    assert all(e.style == "solid" for e in graph.edges)


# --- Determinism -----------------------------------------------------------


def test_render_md_bytes_identical_between_runs() -> None:
    with _in_memory_estate() as ctx:
        case_a = load_case_file(
            EXAMPLE, ctx, company_flag="Grupo Meridiana", period_flag="2025-07/2026-06",
        )
    with _in_memory_estate() as ctx:
        case_b = load_case_file(
            EXAMPLE, ctx, company_flag="Grupo Meridiana", period_flag="2025-07/2026-06",
        )
    assert render_md(case_a).encode("utf-8") == render_md(case_b).encode("utf-8")


def test_render_html_bytes_identical_between_runs() -> None:
    with _in_memory_estate() as ctx:
        case_a = load_case_file(
            EXAMPLE, ctx, company_flag="Grupo Meridiana", period_flag="2025-07/2026-06",
        )
    with _in_memory_estate() as ctx:
        case_b = load_case_file(
            EXAMPLE, ctx, company_flag="Grupo Meridiana", period_flag="2025-07/2026-06",
        )
    assert render_html(case_a).encode("utf-8") == render_html(case_b).encode("utf-8")


def test_html_has_no_network_references() -> None:
    case = load_case_file(EXAMPLE, ctx=None, company_flag=None, period_flag=None)
    html = render_html(case)
    # SVG xmlns is a URI identifier, not a fetch — strip it before checking.
    stripped = html.replace("http://www.w3.org/2000/svg", "")
    assert "http://" not in stripped
    assert "https://" not in stripped
    assert "<script" not in html


# --- Empty findings: obligatory dignity ------------------------------------


def test_empty_findings_summary_has_dignity_markdown() -> None:
    case = load_case_file(EMPTY, ctx=None, company_flag=None, period_flag=None)
    md = render_md(case)
    assert "no encontró ningún esquema de fraude" in md
    assert "leads no perseguidos" in md.lower()
    assert "get_pos_by_vendor" in md
    assert "check_settlement_window" in md
    assert "## Hallazgos" not in md


def test_empty_findings_html_has_dignity_and_lead_tools() -> None:
    case = load_case_file(EMPTY, ctx=None, company_flag=None, period_flag=None)
    html = render_html(case)
    assert "empty-summary" in html
    assert "no encontró ningún esquema" in html
    assert "get_pos_by_vendor" in html
    # Both leads in the empty fixture have closed_by set, so the fallback
    # label must NOT appear.
    assert "sin registro" not in html
