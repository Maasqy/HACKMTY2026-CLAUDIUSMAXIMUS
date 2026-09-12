"""CaseFile -> HTML string.

Self-contained: inline CSS, inline SVG, no <script>, no external URLs. Meant
to open with a double click and read well when projected or printed.
"""

from __future__ import annotations

from html import escape

from .model import (
    AdversarialReview,
    CaseFile,
    Finding,
    Header,
    Lead,
    MethodLimits,
    Reconciliation,
    Summary,
)
from .svg import render_svg

_STYLE = """
:root {
  --ink: #111111;
  --ink-soft: #333333;
  --paper: #fafafa;
  --paper-alt: #f2ede3;
  --accent: #8b0000;
  --accent-cool: #0b4f6c;
  --rule: #d8d2c4;
  --measure: 780px;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: var(--paper); color: var(--ink); }
body {
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  font-size: 17px;
  line-height: 1.55;
  padding: 48px 24px 96px;
}
main { max-width: var(--measure); margin: 0 auto; }
h1, h2, h3, h4 {
  font-family: Georgia, "Iowan Old Style", "Palatino Linotype", serif;
  color: var(--ink);
  line-height: 1.25;
}
h1 { font-size: 2.2rem; margin: 0 0 0.25rem; letter-spacing: -0.01em; }
h2 {
  font-size: 1.6rem;
  margin: 2.6rem 0 0.8rem;
  padding-bottom: 0.3rem;
  border-bottom: 2px solid var(--ink);
}
h3 { font-size: 1.25rem; margin: 1.8rem 0 0.6rem; color: var(--accent); }
h4 { font-size: 1.05rem; margin: 1.2rem 0 0.4rem; }
p { margin: 0.6rem 0; }
ul { padding-left: 1.2rem; }
li { margin: 0.15rem 0; }
strong { color: var(--ink); }
em { color: var(--ink-soft); font-style: italic; }
code {
  font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  font-size: 0.92em;
  background: var(--paper-alt);
  padding: 0.05rem 0.35rem;
  border-radius: 3px;
}
.header-meta {
  display: grid;
  grid-template-columns: max-content 1fr;
  column-gap: 1.2rem;
  row-gap: 0.25rem;
  margin: 0.8rem 0 1.6rem;
  padding: 0.8rem 1rem;
  background: var(--paper-alt);
  border-left: 4px solid var(--accent-cool);
}
.header-meta dt { font-weight: 600; }
.header-meta dd { margin: 0; }
.summary-table, .exhibits, .recon {
  width: 100%;
  border-collapse: collapse;
  margin: 0.6rem 0 1rem;
}
.summary-table td, .summary-table th,
.exhibits td, .exhibits th,
.recon td, .recon th {
  border-bottom: 1px solid var(--rule);
  padding: 0.4rem 0.6rem;
  text-align: left;
  vertical-align: top;
}
.exhibits th, .recon th { background: var(--paper-alt); }
.finding {
  page-break-inside: avoid;
  margin-bottom: 2rem;
  padding: 1rem 1.2rem;
  border: 1px solid var(--rule);
  border-left: 4px solid var(--accent);
  background: #ffffff;
}
.finding__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem 1.2rem;
  margin-bottom: 0.6rem;
}
.finding__meta strong { color: var(--accent-cool); }
.trail {
  margin: 0.8rem 0 1rem;
  padding: 0.8rem;
  background: #ffffff;
  border: 1px solid var(--rule);
  overflow-x: auto;
}
.trail svg { max-width: 100%; height: auto; display: block; }
.adversarial {
  margin: 0.8rem 0;
  padding: 0.6rem 0.9rem;
  background: var(--paper-alt);
  border-left: 3px solid var(--accent-cool);
}
.adversarial h4 { margin-top: 0; color: var(--accent-cool); }
.lead {
  padding: 0.8rem 1rem;
  margin-bottom: 0.8rem;
  border: 1px solid var(--rule);
  background: #ffffff;
}
.lead h3 {
  margin: 0 0 0.4rem;
  color: var(--ink);
  font-family: system-ui, sans-serif;
  font-size: 1.05rem;
}
.tools code { margin-right: 0.3rem; }
.empty-summary {
  padding: 1rem 1.2rem;
  background: var(--paper-alt);
  border-left: 4px solid var(--accent-cool);
}
.period-source {
  font-style: italic;
  color: var(--ink-soft);
  font-weight: 400;
  font-size: 0.92em;
}
@media print {
  body { font-size: 12pt; padding: 24px; background: #ffffff; }
  main { max-width: none; }
  h2 { border-bottom-color: #000; }
  .finding, .lead, .trail, .adversarial, .empty-summary, .header-meta {
    background: #ffffff;
    border-color: #000;
  }
  .finding { border-left-color: #000; }
  .adversarial, .header-meta { border-left-color: #000; }
  code { background: #f0f0f0; }
}
"""


def render(case: CaseFile) -> str:
    parts: list[str] = [
        "<!doctype html>",
        '<html lang="es"><head>',
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>Expediente forense — {escape(case.header.company_name)}</title>",
        f"<style>{_STYLE}</style>",
        "</head><body><main>",
        _header(case.header),
        _executive_summary(case.summary, len(case.findings) == 0),
        _findings(case.findings),
        _leads(case.leads_not_pursued),
        _method(case.method),
        "</main></body></html>",
    ]
    return "".join(parts)


def _header(h: Header) -> str:
    period_note = ""
    if h.period_source != "default":
        label = {"flag": "declarado", "derived": "derivado del estate"}.get(h.period_source, h.period_source)
        period_note = f' <span class="period-source">({escape(label)})</span>'
    rows = [
        ("Periodo auditado", f"{escape(h.audit_period)}{period_note}"),
        ("Semilla del estate", escape(str(h.seed))),
        ("Determinista", "sí" if h.deterministic else "no"),
        ("Llamadas al modelo", escape(str(h.llm_calls))),
        ("Costo", f"${h.mxn_cost:,.2f} MXN"),
        ("Tiempo de reloj", f"{h.wall_clock_seconds:,.2f} s"),
    ]
    dl = "".join(f"<dt>{escape(k)}</dt><dd>{v}</dd>" for k, v in rows)
    return (
        f"<h1>Expediente forense — {escape(h.company_name)}</h1>"
        f'<dl class="header-meta">{dl}</dl>'
    )


def _executive_summary(s: Summary, findings_empty: bool) -> str:
    if findings_empty:
        body = (
            '<div class="empty-summary"><p>El sistema no encontró ningún esquema de fraude '
            'que pudiera <strong>probar</strong> con la evidencia disponible en el estate. '
            'La lista de acusaciones va vacía por decisión, no por omisión: cada señal '
            'detectada fue investigada y cerrada. La sección de leads no perseguidos deja '
            'el rastro de por qué.</p></div>'
        )
    else:
        body = (
            f'<p>Se documentan {s.findings_total} hallazgos con exposición total de '
            f'<strong>${s.total_exposure:,.2f} MXN</strong>. Cada uno pasa el gate de '
            f'evidencia: regla concreta violada, mínimo tres exhibits reales, '
            f'reconciliación por pesos dentro del 2% y narrativa bajo 150 palabras.</p>'
        )
    table = (
        '<table class="summary-table">'
        f'<tr><td><strong>Findings</strong></td><td>{escape(_findings_by_confidence_str(s))}</td></tr>'
        f'<tr><td><strong>Exposición total</strong></td><td>${s.total_exposure:,.2f} MXN</td></tr>'
        f'<tr><td><strong>Leads investigados y cerrados</strong></td><td>{s.leads_investigated}</td></tr>'
        '</table>'
    )
    return f"<h2>Resumen ejecutivo</h2>{body}{table}"


def _findings_by_confidence_str(s: Summary) -> str:
    if s.findings_total == 0:
        return "0"
    parts = [f"{count} {_confidence_label(label, count)}" for label, count in s.findings_by_confidence]
    return f"{s.findings_total} — " + ", ".join(parts)


def _confidence_label(label: str, count: int) -> str:
    plural = count != 1
    if label == "proven":
        return "probados" if plural else "probado"
    if label == "probable":
        return "probables" if plural else "probable"
    return label


def _findings(findings: tuple[Finding, ...]) -> str:
    if not findings:
        return ""
    body = "".join(_finding(f) for f in findings)
    return f"<h2>Hallazgos</h2>{body}"


def _finding(f: Finding) -> str:
    entities = ", ".join(f.entities) or "sin entidades"
    parts = [
        '<section class="finding">',
        f'<h3>{f.index}. {escape(entities)} — <code>{escape(f.scheme_type)}</code></h3>',
        '<div class="finding__meta">'
        f'<span><strong>Regla violada:</strong> {escape(f.rule_broken)}</span>'
        f'<span><strong>Monto:</strong> ${f.peso_amount:,.2f} MXN</span>'
        f'<span><strong>Confianza:</strong> <em>{escape(f.confidence)}</em></span>'
        '</div>',
        f'<h4>Qué pasó</h4><p>{escape(f.narrative)}</p>',
        '<h4>Cadena de dinero</h4>',
        f'<div class="trail">{render_svg(f.trail_graph)}</div>',
        _exhibits_html(f),
    ]
    if f.adversarial_review is not None:
        parts.append(_adversarial(f.adversarial_review))
    parts.append(_reconciliation_html(f.reconciliation))
    parts.append("</section>")
    return "".join(parts)


def _exhibits_html(f: Finding) -> str:
    rows = "".join(
        f'<tr><td>{escape(e.exhibit_id)}</td>'
        f'<td><code>{escape(e.source_table)}</code></td>'
        f'<td><code>{escape(e.record_id)}</code></td>'
        f'<td>{escape(e.note)}</td></tr>'
        for e in f.exhibits
    )
    return (
        '<h4>Pruebas</h4>'
        '<table class="exhibits">'
        '<thead><tr><th>Exhibit</th><th>Tabla</th><th>Record id</th><th>Qué prueba</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
    )


def _adversarial(a: AdversarialReview) -> str:
    return (
        '<div class="adversarial">'
        '<h4>Revisión adversaria</h4>'
        f'<p><em>Argumentó el {escape(a.reviewer)}:</em> {escape(a.challenged)}</p>'
        f'<p><em>La acusación sobrevivió porque:</em> {escape(a.survived_because)}</p>'
        '</div>'
    )


def _reconciliation_html(r: Reconciliation) -> str:
    if not r.per_table:
        return '<h4>Reconciliación</h4><p><em>(sin exhibits para reconciliar)</em></p>'
    rows = "".join(
        f'<tr><td><code>{escape(table)}</code></td>'
        f'<td>{count}</td>'
        f'<td>${total:,.2f}</td></tr>'
        for table, total, count in r.per_table
    )
    if r.best_match_table and r.delta_pct is not None:
        footer = (
            f'<p>Monto reclamado: <strong>${r.peso_amount:,.2f}</strong>. '
            f'Reconcilia contra <code>{escape(r.best_match_table)}</code> '
            f'con desviación {r.delta_pct * 100:+.2f}%.</p>'
        )
    else:
        footer = f'<p>Monto reclamado: <strong>${r.peso_amount:,.2f}</strong>.</p>'
    return (
        '<h4>Reconciliación</h4>'
        '<table class="recon">'
        '<thead><tr><th>Tabla</th><th>Exhibits</th><th>Suma citada</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
        f'{footer}'
    )


def _leads(leads: tuple[Lead, ...]) -> str:
    if not leads:
        return (
            "<h2>Leads no perseguidos</h2>"
            "<p>El sistema no cerró leads sin acusación en esta corrida.</p>"
        )
    body = "".join(_lead_block(lead) for lead in leads)
    return f"<h2>Leads no perseguidos</h2>{body}"


def _lead_block(lead: Lead) -> str:
    if lead.tool_calls_made:
        tools_html = (
            '<span class="tools">'
            + "".join(f"<code>{escape(t)}</code>" for t in lead.tool_calls_made)
            + '</span>'
        )
    else:
        tools_html = "<em>(sin herramientas registradas)</em>"
    closed_by = escape(lead.closed_by) if lead.closed_by else "sin registro"
    return (
        '<div class="lead">'
        f'<h3>{escape(lead.entity)}</h3>'
        f'<p><strong>Señal:</strong> {escape(lead.signal)}</p>'
        f'<p><strong>Razón de cierre:</strong> {escape(lead.reason)}</p>'
        f'<p><strong>Herramientas llamadas:</strong> {tools_html}</p>'
        f'<p><strong>Cerrado por:</strong> {closed_by}</p>'
        '</div>'
    )


def _method(m: MethodLimits) -> str:
    out_of_scope = "".join(f"<li>{escape(item)}</li>" for item in m.out_of_scope)
    cannot = "".join(f"<li>{escape(item)}</li>" for item in m.cannot_detect)
    return (
        "<h2>Método y límites</h2>"
        f"<p>{escape(m.architecture)}</p>"
        f"<h4>Fuera de alcance</h4><ul>{out_of_scope}</ul>"
        f"<h4>Lo que este sistema no detecta</h4><ul>{cannot}</ul>"
        f"<h4>Reproducibilidad</h4><p>{escape(m.reproducibility)}</p>"
    )
