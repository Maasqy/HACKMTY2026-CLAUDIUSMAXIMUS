"""Render a MoneyGraph as an SVG string.

Pure standard library. No random. Marker ids are numbered.

Layout: layered left-to-right. Layers assigned via Kahn's topological sort with
ties broken by node_id string comparison. Cycle-remnant nodes go in an extra
trailing layer. Parallel edges between the same pair are stacked with a
perpendicular offset.
"""

from __future__ import annotations

from html import escape

from .model import Edge, MoneyGraph, Node

NODE_W = 220
NODE_H = 64
COL_GAP = 90
ROW_GAP = 30
MARGIN = 24
STROKE_W = 2.2
DASH_PATTERN = "8 5"
FONT_PRIMARY = 14
FONT_SECONDARY = 12
FONT_EDGE = 12


def render_svg(graph: MoneyGraph) -> str:
    if not graph.nodes and not graph.edges:
        return _render_empty(graph.empty_reason or "")

    positions, canvas_w, canvas_h = _layout(graph.nodes, graph.edges)
    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {canvas_w} {canvas_h}" '
        f'role="img" aria-label="Money trail" class="money-trail">'
    )
    parts.append(_defs())
    parts.append(_render_edges(graph.edges, positions))
    parts.append(_render_nodes(graph.nodes, positions))
    parts.append("</svg>")
    return "".join(parts)


def _render_empty(msg: str) -> str:
    text = escape(msg)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 80" '
        f'role="img" aria-label="Sin flujo monetario" class="money-trail money-trail--empty">'
        f'<rect x="0" y="0" width="640" height="80" fill="#fafafa" stroke="#c0c0c0" '
        f'stroke-dasharray="{DASH_PATTERN}"/>'
        f'<text x="320" y="46" text-anchor="middle" font-size="14" fill="#333333" '
        f'font-family="system-ui, sans-serif">{text}</text>'
        f'</svg>'
    )


def _defs() -> str:
    return (
        '<defs>'
        '<marker id="arrow-1" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        'markerHeight="7" orient="auto-start-reverse">'
        '<path d="M0,0 L10,5 L0,10 z" fill="#111111"/>'
        '</marker>'
        '<marker id="arrow-2" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        'markerHeight="7" orient="auto-start-reverse">'
        '<path d="M0,0 L10,5 L0,10 z" fill="#8b0000"/>'
        '</marker>'
        '</defs>'
    )


def _layout(
    nodes: tuple[Node, ...],
    edges: tuple[Edge, ...],
) -> tuple[dict[str, tuple[float, float]], int, int]:
    layer_of = _assign_layers(nodes, edges)
    by_layer: dict[int, list[str]] = {}
    for nid, layer in layer_of.items():
        by_layer.setdefault(layer, []).append(nid)
    for layer in by_layer:
        by_layer[layer].sort()

    max_layer = max(by_layer.keys()) if by_layer else 0
    max_rows = max((len(v) for v in by_layer.values()), default=1)

    canvas_w = MARGIN * 2 + (max_layer + 1) * NODE_W + max_layer * COL_GAP
    canvas_h = MARGIN * 2 + max_rows * NODE_H + max(0, max_rows - 1) * ROW_GAP
    canvas_h = max(canvas_h, 120)

    positions: dict[str, tuple[float, float]] = {}
    for layer, ids in by_layer.items():
        col_x = MARGIN + layer * (NODE_W + COL_GAP) + NODE_W / 2
        total_h = len(ids) * NODE_H + max(0, len(ids) - 1) * ROW_GAP
        start_y = (canvas_h - total_h) / 2 + NODE_H / 2
        for i, nid in enumerate(ids):
            cy = start_y + i * (NODE_H + ROW_GAP)
            positions[nid] = (col_x, cy)
    return positions, canvas_w, canvas_h


def _assign_layers(
    nodes: tuple[Node, ...],
    edges: tuple[Edge, ...],
) -> dict[str, int]:
    """Kahn's topological ordering with lexicographic tie-break.

    Cycle-only nodes are placed in a trailing residual layer.
    """
    node_ids = sorted(n.node_id for n in nodes)
    in_deg: dict[str, int] = {nid: 0 for nid in node_ids}
    adj: dict[str, list[str]] = {nid: [] for nid in node_ids}
    for e in edges:
        if e.from_id == e.to_id:
            continue
        if e.to_id not in in_deg or e.from_id not in in_deg:
            continue
        adj[e.from_id].append(e.to_id)
        in_deg[e.to_id] += 1

    layer: dict[str, int] = {}
    queue = sorted([nid for nid, d in in_deg.items() if d == 0])
    while queue:
        nid = queue.pop(0)
        layer.setdefault(nid, 0)
        for nxt in sorted(adj[nid]):
            new_layer = layer[nid] + 1
            if new_layer > layer.get(nxt, -1):
                layer[nxt] = new_layer
            in_deg[nxt] -= 1
            if in_deg[nxt] == 0:
                _insert_sorted(queue, nxt)

    if any(nid not in layer for nid in node_ids):
        residual = (max(layer.values()) + 1) if layer else 0
        for nid in node_ids:
            layer.setdefault(nid, residual)
    return layer


def _insert_sorted(seq: list[str], value: str) -> None:
    lo, hi = 0, len(seq)
    while lo < hi:
        mid = (lo + hi) // 2
        if seq[mid] < value:
            lo = mid + 1
        else:
            hi = mid
    seq.insert(lo, value)


def _render_nodes(
    nodes: tuple[Node, ...],
    positions: dict[str, tuple[float, float]],
) -> str:
    out: list[str] = []
    for node in nodes:
        cx, cy = positions[node.node_id]
        x = cx - NODE_W / 2
        y = cy - NODE_H / 2
        fill = _node_fill(node.kind)
        out.append(
            f'<g class="node node--{node.kind}">'
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{NODE_W}" height="{NODE_H}" '
            f'rx="6" ry="6" fill="{fill}" stroke="#111111" stroke-width="1.2"/>'
        )
        if node.label_secondary:
            out.append(
                f'<text x="{cx:.1f}" y="{cy - 4:.1f}" text-anchor="middle" '
                f'font-size="{FONT_PRIMARY}" font-family="system-ui, sans-serif" '
                f'fill="#111111" font-weight="600">{escape(node.label_primary)}</text>'
                f'<text x="{cx:.1f}" y="{cy + 16:.1f}" text-anchor="middle" '
                f'font-size="{FONT_SECONDARY}" font-family="system-ui, sans-serif" '
                f'fill="#333333">{escape(node.label_secondary)}</text>'
            )
        else:
            out.append(
                f'<text x="{cx:.1f}" y="{cy + 5:.1f}" text-anchor="middle" '
                f'font-size="{FONT_PRIMARY}" font-family="system-ui, sans-serif" '
                f'fill="#111111" font-weight="600">{escape(node.label_primary)}</text>'
            )
        out.append("</g>")
    return "".join(out)


def _node_fill(kind: str) -> str:
    return {
        "vendor": "#f7f2e8",
        "company": "#e8f0f7",
        "employee": "#f5e8f2",
        "clabe": "#eeeeee",
    }.get(kind, "#fafafa")


def _render_edges(
    edges: tuple[Edge, ...],
    positions: dict[str, tuple[float, float]],
) -> str:
    grouped: dict[tuple[str, str], list[Edge]] = {}
    order: list[tuple[str, str]] = []
    for e in edges:
        key = (e.from_id, e.to_id)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(e)

    out: list[str] = []
    for key in order:
        group = grouped[key]
        n = len(group)
        for local_index, edge in enumerate(group):
            offset = _perpendicular_offset(local_index, n)
            out.append(_render_edge(edge, positions, offset))
    return "".join(out)


def _perpendicular_offset(local_index: int, count: int) -> float:
    if count == 1:
        return 0.0
    step = 14.0
    center = (count - 1) / 2
    return (local_index - center) * step * 2


def _render_edge(
    edge: Edge,
    positions: dict[str, tuple[float, float]],
    offset: float,
) -> str:
    if edge.from_id not in positions or edge.to_id not in positions:
        return ""
    x1, y1 = positions[edge.from_id]
    x2, y2 = positions[edge.to_id]

    if x2 >= x1:
        sx = x1 + NODE_W / 2
        ex = x2 - NODE_W / 2
    else:
        sx = x1 - NODE_W / 2
        ex = x2 + NODE_W / 2
    sy = y1
    ey = y2

    dx = ex - sx
    dy = ey - sy
    length = (dx * dx + dy * dy) ** 0.5 or 1.0
    nx = -dy / length
    ny = dx / length
    ox = nx * offset
    oy = ny * offset

    stroke = "#111111" if edge.style == "solid" else "#8b0000"
    marker = "arrow-1" if edge.style == "solid" else "arrow-2"
    dash = "" if edge.style == "solid" else f' stroke-dasharray="{DASH_PATTERN}"'

    if offset == 0:
        line = (
            f'<line x1="{sx:.1f}" y1="{sy:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" '
            f'stroke="{stroke}" stroke-width="{STROKE_W}"{dash} marker-end="url(#{marker})"/>'
        )
        mx = (sx + ex) / 2
        my = (sy + ey) / 2 - 8
    else:
        cx = (sx + ex) / 2 + ox
        cy = (sy + ey) / 2 + oy
        line = (
            f'<path d="M {sx:.1f} {sy:.1f} Q {cx:.1f} {cy:.1f} {ex:.1f} {ey:.1f}" '
            f'fill="none" stroke="{stroke}" stroke-width="{STROKE_W}"{dash} '
            f'marker-end="url(#{marker})"/>'
        )
        mx = cx
        my = cy - 6

    label_bg_w = max(80, len(edge.label) * 6.6)
    label = (
        f'<g class="edge-label edge-label--{edge.style}">'
        f'<rect x="{mx - label_bg_w / 2:.1f}" y="{my - 12:.1f}" width="{label_bg_w:.1f}" '
        f'height="18" rx="3" ry="3" fill="#fafafa" stroke="#e0e0e0"/>'
        f'<text x="{mx:.1f}" y="{my + 2:.1f}" text-anchor="middle" '
        f'font-size="{FONT_EDGE}" font-family="system-ui, sans-serif" '
        f'fill="{stroke}">{escape(edge.label)}</text>'
        f'</g>'
    )
    return line + label
