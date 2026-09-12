"""CaseFile -> Markdown string.

Inline SVG is embedded directly with an <svg> tag. GitHub-flavored Markdown
renders inline SVG in many contexts; VS Code preview does too. The file
contains no network references.
"""

from __future__ import annotations

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


def render(case: CaseFile) -> str:
    parts: list[str] = [
        _header(case.header),
        _executive_summary(case.summary, len(case.findings) == 0),
        _findings(case.findings),
        _leads(case.leads_not_pursued),
        _method(case.method),
    ]
    return "\n\n".join(p for p in parts if p) + "\n"


def _header(h: Header) -> str:
    period_note = ""
    if h.period_source != "default":
        period_note = f"  _(fuente: {_period_source_label(h.period_source)})_"
    lines = [
        f"# Expediente forense — {h.company_name}",
        "",
        f"- **Periodo auditado:** {h.audit_period}{period_note}",
        f"- **Semilla del estate:** {h.seed}",
        f"- **Determinista:** {'sí' if h.deterministic else 'no'}",
        f"- **Llamadas al modelo:** {h.llm_calls}",
        f"- **Costo:** ${h.mxn_cost:,.2f} MXN",
        f"- **Tiempo de reloj:** {h.wall_clock_seconds:,.2f} s",
    ]
    return "\n".join(lines)


def _period_source_label(source: str) -> str:
    return {
        "flag": "declarado",
        "derived": "derivado del estate",
        "default": "sin dato",
    }.get(source, source)


def _executive_summary(s: Summary, findings_empty: bool) -> str:
    lines = ["## Resumen ejecutivo", ""]
    if findings_empty:
        lines.append(
            "El sistema no encontró ningún esquema de fraude que pudiera **probar** "
            "con la evidencia disponible en el estate. La lista de acusaciones va "
            "vacía por decisión, no por omisión: cada señal detectada fue "
            "investigada y cerrada. La sección de leads no perseguidos deja el "
            "rastro de por qué."
        )
    else:
        lines.append(
            f"Se documentan {s.findings_total} hallazgos con exposición total de "
            f"${s.total_exposure:,.2f} MXN. Cada uno pasa el gate de evidencia: "
            f"regla concreta violada, mínimo tres exhibits reales, reconciliación "
            f"por pesos dentro del 2% y narrativa bajo 150 palabras."
        )
    lines.append("")
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append(f"| Findings | {_findings_by_confidence_str(s)} |")
    lines.append(f"| Exposición total | ${s.total_exposure:,.2f} MXN |")
    lines.append(f"| Leads investigados y cerrados | {s.leads_investigated} |")
    return "\n".join(lines)


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
    blocks = ["## Hallazgos"]
    for f in findings:
        blocks.append(_finding(f))
    return "\n\n".join(blocks)


def _finding(f: Finding) -> str:
    entities = ", ".join(f.entities) or "sin entidades"
    lines = [
        f"### {f.index}. {entities} — {f.scheme_type}",
        "",
        f"**Regla violada.** {f.rule_broken}",
        "",
        f"**Monto y confianza.** ${f.peso_amount:,.2f} MXN — _{f.confidence}_",
        "",
        "**Qué pasó.**",
        "",
        f.narrative,
        "",
        "**Cadena de dinero.**",
        "",
        render_svg(f.trail_graph),
        "",
        _exhibits_table(f),
        "",
    ]
    if f.adversarial_review is not None:
        lines.extend([_adversarial(f.adversarial_review), ""])
    lines.append(_reconciliation(f.reconciliation))
    return "\n".join(lines)


def _exhibits_table(f: Finding) -> str:
    header = ["**Pruebas.**", "", "| Exhibit | Tabla | Record id | Qué prueba |", "|---|---|---|---|"]
    rows = []
    for exhibit in f.exhibits:
        note = exhibit.note.replace("|", "\\|")
        rows.append(
            f"| {exhibit.exhibit_id} | `{exhibit.source_table}` | `{exhibit.record_id}` | {note} |"
        )
    return "\n".join(header + rows)


def _adversarial(a: AdversarialReview) -> str:
    return (
        "**Revisión adversaria.**\n\n"
        f"- _Argumentó el {a.reviewer}:_ {a.challenged}\n"
        f"- _La acusación sobrevivió porque:_ {a.survived_because}"
    )


def _reconciliation(r: Reconciliation) -> str:
    lines = ["**Reconciliación.**", ""]
    if not r.per_table:
        lines.append("_(sin exhibits para reconciliar)_")
        return "\n".join(lines)
    lines.append("| Tabla | Exhibits | Suma citada |")
    lines.append("|---|---|---|")
    for table, total, count in r.per_table:
        lines.append(f"| `{table}` | {count} | ${total:,.2f} |")
    lines.append("")
    if r.best_match_table and r.delta_pct is not None:
        lines.append(
            f"Monto reclamado: **${r.peso_amount:,.2f}**. Reconcilia contra "
            f"`{r.best_match_table}` con desviación {r.delta_pct * 100:+.2f}%."
        )
    else:
        lines.append(f"Monto reclamado: **${r.peso_amount:,.2f}**.")
    return "\n".join(lines)


def _leads(leads: tuple[Lead, ...]) -> str:
    if not leads:
        return "## Leads no perseguidos\n\nEl sistema no cerró leads sin acusación en esta corrida."
    lines = ["## Leads no perseguidos", ""]
    for lead in leads:
        lines.extend(_lead_block(lead))
        lines.append("")
    return "\n".join(lines).rstrip()


def _lead_block(lead: Lead) -> list[str]:
    tools = (
        ", ".join(f"`{t}`" for t in lead.tool_calls_made)
        or "_(sin herramientas registradas)_"
    )
    closed_by = lead.closed_by or "sin registro"
    return [
        f"### {lead.entity}",
        "",
        f"- **Señal:** {lead.signal}",
        f"- **Razón de cierre:** {lead.reason}",
        f"- **Herramientas llamadas:** {tools}",
        f"- **Cerrado por:** {closed_by}",
    ]


def _method(m: MethodLimits) -> str:
    lines = ["## Método y límites", "", m.architecture, "", "**Fuera de alcance.**", ""]
    lines.extend(f"- {item}" for item in m.out_of_scope)
    lines.append("")
    lines.append("**Lo que este sistema no detecta.**")
    lines.append("")
    lines.extend(f"- {item}" for item in m.cannot_detect)
    lines.append("")
    lines.append("**Reproducibilidad.**")
    lines.append("")
    lines.append(m.reproducibility)
    return "\n".join(lines)
