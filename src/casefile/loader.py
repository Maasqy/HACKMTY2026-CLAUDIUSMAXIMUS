"""Load submission.json into a CaseFile.

Strict validation lives in the official validate_format.py; this loader is
tolerant with optional fields and defensive about missing ones. Its job is
to build a renderable CaseFile whenever the submission has the shape required
by the schema.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from . import trail
from .estate_context import EstateContext
from .model import (
    DEFAULT_METHOD,
    AdversarialReview,
    CaseFile,
    Exhibit,
    Finding,
    Header,
    Lead,
    MethodLimits,
    PeriodSource,
    Reconciliation,
    Summary,
    TrailStep,
)


def load_case_file(
    submission_path: Path,
    ctx: Optional[EstateContext],
    company_flag: Optional[str],
    period_flag: Optional[str],
    method: Optional[MethodLimits] = None,
) -> CaseFile:
    raw = json.loads(submission_path.read_text(encoding="utf-8"))
    header = _build_header(raw, ctx, company_flag, period_flag)
    findings = _build_findings(raw.get("findings", []), ctx)
    leads = _build_leads(raw.get("leads_not_pursued", []))
    summary = _build_summary(findings, len(leads))
    return CaseFile(
        header=header,
        summary=summary,
        findings=findings,
        leads_not_pursued=leads,
        method=method or DEFAULT_METHOD,
    )


def _build_header(
    raw: dict[str, Any],
    ctx: Optional[EstateContext],
    company_flag: Optional[str],
    period_flag: Optional[str],
) -> Header:
    metadata = raw.get("run_metadata", {}) or {}
    seed = int(raw.get("seed", 0))

    company_rfc: Optional[str] = None
    if ctx is not None:
        company_rfc = ctx.derive_company_rfc()

    if company_flag:
        company_name = company_flag
    elif company_rfc is not None:
        company_name = f"Empresa auditada · RFC:{company_rfc}"
    else:
        company_name = "Empresa auditada"

    period, period_source = _resolve_period(period_flag, ctx)

    return Header(
        company_name=company_name,
        company_rfc=company_rfc,
        audit_period=period,
        period_source=period_source,
        seed=seed,
        deterministic=bool(metadata.get("deterministic", False)),
        llm_calls=int(metadata.get("llm_calls", 0)),
        mxn_cost=float(metadata.get("mxn_cost", 0.0)),
        wall_clock_seconds=float(metadata.get("wall_clock_seconds", 0.0)),
    )


def _resolve_period(
    period_flag: Optional[str],
    ctx: Optional[EstateContext],
) -> tuple[str, PeriodSource]:
    if period_flag:
        return period_flag, "flag"
    if ctx is not None:
        derived = ctx.derive_audit_period()
        if derived is not None:
            return derived, "derived"
    return "periodo no especificado", "default"


def _build_findings(
    raw_findings: list[dict[str, Any]],
    ctx: Optional[EstateContext],
) -> tuple[Finding, ...]:
    out: list[Finding] = []
    for idx, raw in enumerate(raw_findings, start=1):
        exhibits = _build_exhibits(raw.get("exhibits", []))
        trail_steps = _build_trail_steps(raw.get("money_trail", []) or [])
        scheme_type = str(raw.get("scheme_type", ""))
        graph = trail.build(scheme_type, exhibits, trail_steps, ctx)
        recon = _build_reconciliation(float(raw.get("peso_amount", 0.0)), exhibits, ctx)
        adversarial = _build_adversarial(raw.get("adversarial_review"))
        out.append(
            Finding(
                index=idx,
                scheme_type=scheme_type,
                entities=tuple(str(e) for e in raw.get("entities", [])),
                narrative=str(raw.get("narrative", "")),
                rule_broken=str(raw.get("rule_broken", "")),
                peso_amount=float(raw.get("peso_amount", 0.0)),
                confidence=str(raw.get("confidence", "")),
                exhibits=exhibits,
                trail_steps=trail_steps,
                trail_graph=graph,
                reconciliation=recon,
                adversarial_review=adversarial,
            )
        )
    return tuple(out)


def _build_exhibits(raw: list[dict[str, Any]]) -> tuple[Exhibit, ...]:
    return tuple(
        Exhibit(
            exhibit_id=str(e.get("exhibit_id", "")),
            source_table=str(e.get("source_table", "")),
            record_id=str(e.get("record_id", "")),
            note=str(e.get("note", "")),
        )
        for e in raw
    )


def _build_trail_steps(raw: list[dict[str, Any]]) -> tuple[TrailStep, ...]:
    return tuple(
        TrailStep(
            from_entity=str(s.get("from", "")),
            to_entity=str(s.get("to", "")),
            amount=float(s.get("amount", 0.0)),
            date=str(s.get("date", "")),
            exhibit_id=str(s.get("exhibit_id", "")),
        )
        for s in raw
    )


def _build_adversarial(raw: Optional[dict[str, Any]]) -> Optional[AdversarialReview]:
    if not isinstance(raw, dict):
        return None
    challenged = str(raw.get("challenged", "")).strip()
    survived = str(raw.get("survived_because", "")).strip()
    if not challenged or not survived:
        return None
    return AdversarialReview(
        challenged=challenged,
        survived_because=survived,
        reviewer=str(raw.get("reviewer", "challenger")),
    )


def _build_reconciliation(
    peso_amount: float,
    exhibits: tuple[Exhibit, ...],
    ctx: Optional[EstateContext],
) -> Reconciliation:
    """Per-table sum, then pick the closest table (schema rule).

    peso_amount reconciles against the best-matching table, so citing an
    invoice AND the bank_txn that settled it does NOT double the money.
    """
    per_table_counts: Counter[str] = Counter()
    per_table_totals: dict[str, float] = {}
    for exhibit in exhibits:
        per_table_counts[exhibit.source_table] += 1
        amount = _exhibit_amount(exhibit, ctx)
        if amount is not None:
            per_table_totals[exhibit.source_table] = (
                per_table_totals.get(exhibit.source_table, 0.0) + amount
            )

    per_table_sorted = tuple(
        (table, per_table_totals.get(table, 0.0), per_table_counts[table])
        for table in sorted(per_table_counts.keys())
    )

    best_match_table: Optional[str] = None
    delta_pct: Optional[float] = None
    if per_table_totals and peso_amount > 0:
        best_match_table = min(
            per_table_totals,
            key=lambda t: (abs(per_table_totals[t] - peso_amount), t),
        )
        best_sum = per_table_totals[best_match_table]
        delta_pct = (peso_amount - best_sum) / peso_amount

    return Reconciliation(
        peso_amount=peso_amount,
        per_table=per_table_sorted,
        best_match_table=best_match_table,
        delta_pct=delta_pct,
    )


def _exhibit_amount(exhibit: Exhibit, ctx: Optional[EstateContext]) -> Optional[float]:
    if ctx is None:
        return None
    if exhibit.source_table == "invoices":
        row = ctx.lookup_invoice(exhibit.record_id)
        return row.total if row is not None else None
    if exhibit.source_table == "bank_txns":
        row = ctx.lookup_bank_txn(exhibit.record_id)
        return row.amount if row is not None else None
    return None


def _build_leads(raw_leads: list[dict[str, Any]]) -> tuple[Lead, ...]:
    return tuple(
        Lead(
            entity=str(lead.get("entity", "")),
            signal=str(lead.get("signal", "")),
            reason=str(lead.get("reason", "")),
            tool_calls_made=tuple(str(t) for t in lead.get("tool_calls_made", []) or []),
            closed_by=(str(lead["closed_by"]) if lead.get("closed_by") else None),
        )
        for lead in raw_leads
    )


def _build_summary(findings: tuple[Finding, ...], leads_count: int) -> Summary:
    by_confidence: Counter[str] = Counter()
    total_exposure = 0.0
    for f in findings:
        by_confidence[f.confidence or "sin_confianza"] += 1
        total_exposure += f.peso_amount
    ordered = tuple(sorted(by_confidence.items()))
    return Summary(
        findings_total=len(findings),
        findings_by_confidence=ordered,
        total_exposure=total_exposure,
        leads_investigated=leads_count,
    )
