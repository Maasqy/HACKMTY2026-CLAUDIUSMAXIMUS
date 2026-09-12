"""Build a MoneyGraph for one finding.

Fallback chain, in order:
  1. Explicit money_trail: one edge per step (order preserved).
  2. No trail but invoice exhibits: aggregate by (issuer_rfc, receiver_rfc)
     into solid edges. Overlay bank_txn edges. Unpaid remainder becomes a
     dashed edge.
  3. No monetary exhibits at all: empty graph with an honest sentence.

Post-rule (independent of source): for revenue_inflation, every edge without
bank-txn backing is redrawn dashed with 'facturado no cobrado'.

Determinism: all aggregations sort by stable string keys. No set iteration.
No timestamps. No random ids.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal, Optional

from .estate_context import EstateContext
from .model import Edge, Exhibit, MoneyGraph, Node, TrailStep

_EMPTY_REASON = (
    "El hallazgo no tiene flujo monetario asociado; la evidencia es documental."
)

EdgeOrigin = Literal["invoice", "bank", "unpaid", "trail_step", "trail_bank_step"]


@dataclass(frozen=True)
class _EdgeDraft:
    from_id: str
    to_id: str
    amount: float
    label: str
    origin: EdgeOrigin


def build(
    scheme_type: str,
    exhibits: tuple[Exhibit, ...],
    trail_steps: tuple[TrailStep, ...],
    ctx: Optional[EstateContext],
) -> MoneyGraph:
    invoice_exhibits = tuple(e for e in exhibits if e.source_table == "invoices")
    bank_exhibits = tuple(e for e in exhibits if e.source_table == "bank_txns")

    has_monetary = bool(trail_steps) or bool(invoice_exhibits) or bool(bank_exhibits)
    if not has_monetary:
        return MoneyGraph(nodes=(), edges=(), empty_reason=_EMPTY_REASON)

    exhibits_by_id = {e.exhibit_id: e for e in exhibits}

    if trail_steps:
        drafts = _drafts_from_trail(trail_steps, exhibits_by_id)
    else:
        drafts = _drafts_from_exhibits(invoice_exhibits, bank_exhibits, ctx)

    if scheme_type == "revenue_inflation":
        drafts = _apply_revenue_inflation_rule(drafts)

    edges = tuple(_to_edge(d) for d in drafts)
    nodes = _collect_nodes(drafts, ctx)
    return MoneyGraph(nodes=nodes, edges=edges, empty_reason=None)


def _drafts_from_trail(
    steps: tuple[TrailStep, ...],
    exhibits_by_id: dict[str, Exhibit],
) -> list[_EdgeDraft]:
    out: list[_EdgeDraft] = []
    for step in steps:
        exhibit = exhibits_by_id.get(step.exhibit_id)
        is_bank = exhibit is not None and exhibit.source_table == "bank_txns"
        origin: EdgeOrigin = "trail_bank_step" if is_bank else "trail_step"
        date_frag = f" · {step.date}" if step.date else ""
        label = f"${_pesos(step.amount)}{date_frag}"
        out.append(
            _EdgeDraft(
                from_id=_slug(step.from_entity),
                to_id=_slug(step.to_entity),
                amount=step.amount,
                label=label,
                origin=origin,
            )
        )
    return out


def _drafts_from_exhibits(
    invoice_exhibits: tuple[Exhibit, ...],
    bank_exhibits: tuple[Exhibit, ...],
    ctx: Optional[EstateContext],
) -> list[_EdgeDraft]:
    """Aggregate then emit in stable order: invoices, then banks, then unpaid."""
    invoice_agg = _aggregate_invoices(invoice_exhibits, ctx)
    bank_agg = _aggregate_bank(bank_exhibits, ctx)

    drafts: list[_EdgeDraft] = []
    for pair in sorted(invoice_agg.keys()):
        total, count, date_lo, date_hi = invoice_agg[pair]
        drafts.append(
            _EdgeDraft(
                from_id=_slug(pair[0]),
                to_id=_slug(pair[1]),
                amount=total,
                label=_range_label(count, total, date_lo, date_hi, "facturas"),
                origin="invoice",
            )
        )
    for pair in sorted(bank_agg.keys()):
        total, count, date_lo, date_hi = bank_agg[pair]
        drafts.append(
            _EdgeDraft(
                from_id=_slug(pair[0]),
                to_id=_slug(pair[1]),
                amount=total,
                label=_range_label(count, total, date_lo, date_hi, "liquidaciones"),
                origin="bank",
            )
        )
    bank_total_by_nodeset: dict[frozenset[str], float] = {}
    for bp, (total, _c, _lo, _hi) in bank_agg.items():
        key = frozenset(bp)
        bank_total_by_nodeset[key] = bank_total_by_nodeset.get(key, 0.0) + total
    for pair in sorted(invoice_agg.keys()):
        inv_total = invoice_agg[pair][0]
        bank_total = bank_total_by_nodeset.get(frozenset(pair), 0.0)
        unpaid = inv_total - bank_total
        if unpaid > 0.01:
            drafts.append(
                _EdgeDraft(
                    from_id=_slug(pair[0]),
                    to_id=_slug(pair[1]),
                    amount=unpaid,
                    label=f"sin liquidación en bank_txns · ${_pesos(unpaid)}",
                    origin="unpaid",
                )
            )
    return drafts


def _aggregate_invoices(
    exhibits: tuple[Exhibit, ...],
    ctx: Optional[EstateContext],
) -> dict[tuple[str, str], tuple[float, int, str, str]]:
    agg: dict[tuple[str, str], tuple[float, int, str, str]] = {}
    if ctx is None:
        return agg
    for exhibit in sorted(exhibits, key=lambda e: e.exhibit_id):
        row = ctx.lookup_invoice(exhibit.record_id)
        if row is None or not row.issuer_rfc or not row.receiver_rfc:
            continue
        pair = (f"RFC:{row.issuer_rfc}", f"RFC:{row.receiver_rfc}")
        prev = agg.get(pair)
        if prev is None:
            agg[pair] = (row.total, 1, row.issue_date, row.issue_date)
        else:
            lo = min(prev[2], row.issue_date) if prev[2] and row.issue_date else (prev[2] or row.issue_date)
            hi = max(prev[3], row.issue_date) if prev[3] and row.issue_date else (prev[3] or row.issue_date)
            agg[pair] = (prev[0] + row.total, prev[1] + 1, lo, hi)
    return agg


def _aggregate_bank(
    exhibits: tuple[Exhibit, ...],
    ctx: Optional[EstateContext],
) -> dict[tuple[str, str], tuple[float, int, str, str]]:
    agg: dict[tuple[str, str], tuple[float, int, str, str]] = {}
    if ctx is None:
        return agg
    for exhibit in sorted(exhibits, key=lambda e: e.exhibit_id):
        row = ctx.lookup_bank_txn(exhibit.record_id)
        if row is None:
            continue
        from_id = _clabe_to_id(row.from_clabe, ctx)
        to_id = _clabe_to_id(row.to_clabe, ctx)
        pair = (from_id, to_id)
        prev = agg.get(pair)
        if prev is None:
            agg[pair] = (row.amount, 1, row.date, row.date)
        else:
            lo = min(prev[2], row.date) if prev[2] and row.date else (prev[2] or row.date)
            hi = max(prev[3], row.date) if prev[3] and row.date else (prev[3] or row.date)
            agg[pair] = (prev[0] + row.amount, prev[1] + 1, lo, hi)
    return agg


def _clabe_to_id(clabe: str, ctx: EstateContext) -> str:
    if not clabe:
        return "CLABE:desconocida"
    vendor = ctx.vendor_by_clabe(clabe)
    if vendor is not None:
        return f"RFC:{vendor.rfc}"
    return f"CLABE:{clabe}"


def _apply_revenue_inflation_rule(drafts: list[_EdgeDraft]) -> list[_EdgeDraft]:
    # Settlement is direction-agnostic: an invoice pair (issuer, receiver) is
    # settled by a bank flow (receiver, issuer). Match on the unordered node
    # pair so both directions register.
    settled_pairs: set[frozenset[str]] = {
        frozenset({d.from_id, d.to_id})
        for d in drafts
        if d.origin in ("bank", "trail_bank_step")
    }
    # Pairs where an invoice/trail edge will be re-labeled to
    # "facturado no cobrado". A pre-existing unpaid overlay on the same pair
    # would say the same thing — drop it to keep the diagram uncluttered.
    will_convert: set[frozenset[str]] = {
        frozenset({d.from_id, d.to_id})
        for d in drafts
        if d.origin in ("invoice", "trail_step")
        and frozenset({d.from_id, d.to_id}) not in settled_pairs
    }
    out: list[_EdgeDraft] = []
    for d in drafts:
        pair_set = frozenset({d.from_id, d.to_id})
        if d.origin == "unpaid" and pair_set in will_convert:
            continue
        if d.origin in ("bank", "trail_bank_step", "unpaid"):
            out.append(d)
            continue
        if pair_set in settled_pairs:
            out.append(d)
            continue
        out.append(
            _EdgeDraft(
                from_id=d.from_id,
                to_id=d.to_id,
                amount=d.amount,
                label=f"facturado no cobrado · ${_pesos(d.amount)}",
                origin="unpaid",
            )
        )
    return out


def _collect_nodes(
    drafts: Iterable[_EdgeDraft],
    ctx: Optional[EstateContext],
) -> tuple[Node, ...]:
    seen: dict[str, Node] = {}
    for d in drafts:
        for node_id in (d.from_id, d.to_id):
            if node_id in seen:
                continue
            seen[node_id] = _build_node(node_id, ctx)
    return tuple(seen.values())


def _build_node(node_id: str, ctx: Optional[EstateContext]) -> Node:
    primary = node_id.replace("_", ":", 1)
    if primary.startswith("EMP:"):
        return Node(node_id=node_id, label_primary=primary, label_secondary=None, kind="employee")
    if primary.startswith("CLABE:"):
        return Node(node_id=node_id, label_primary=primary, label_secondary=None, kind="clabe")
    if primary.startswith("RFC:"):
        rfc = primary.split(":", 1)[1]
        legal_name = None
        if ctx is not None:
            vendor = ctx.lookup_vendor(rfc)
            if vendor is not None:
                legal_name = vendor.legal_name
        return Node(
            node_id=node_id,
            label_primary=primary,
            label_secondary=legal_name,
            kind="vendor",
        )
    return Node(node_id=node_id, label_primary=node_id, label_secondary=None, kind="unknown")


def _to_edge(d: _EdgeDraft) -> Edge:
    style = "dashed" if d.origin == "unpaid" else "solid"
    return Edge(
        from_id=d.from_id,
        to_id=d.to_id,
        amount=d.amount,
        label=d.label,
        style=style,
    )


def _slug(entity: str) -> str:
    return entity.replace(":", "_")


def _pesos(amount: float) -> str:
    return f"{amount:,.2f}"


def _range_label(count: int, total: float, lo: str, hi: str, unit: str) -> str:
    date_frag = ""
    if lo and hi:
        date_frag = f" · {lo}" if lo == hi else f" · {lo}/{hi}"
    return f"{count} {unit} · ${_pesos(total)}{date_frag}"
