"""
src/pipeline.py

El pipeline completo, de punta a punta:

    SQLite -> CART -> Gemma -> validator -> challenger -> reporting

Una sola funcion, `ejecutar()`, para que el orden de las etapas sea legible
de corrido y para que src/run.py no tenga logica propia mas alla de parsear
argumentos.

Dos propiedades que el track exige y que se sostienen aqui:

  Nada se acusa sin validar. Un FindingDraft solo se convierte en finding
  despues de que el validador confirme cada record_id contra SQLite y
  reconcilie el monto. Lo que no pasa, no se imprime: se va a
  leads_not_pursued con el motivo exacto.

  Todo lead termina en algun lado. Los que no se investigaron (por el limite
  de presupuesto), los que el validador rechazo y los que el challenger
  tumbo, todos aparecen en leads_not_pursued con su razon. La spec pide que
  los leads declinados vivan en el cuerpo del expediente, no en un apendice.
"""

from __future__ import annotations

from src.forensic.challenger import desafiar
from src.forensic.client import LLMClient, LLMUnavailableError
from src.forensic.investigator import investigar_lead
from src.forensic.money_trail import construir as construir_money_trail
from src.forensic.validator import validar
from src.metrics.run_metrics import RunMetrics
from src.scoring import generar_leads


def ejecutar(estate, client: LLMClient | None = None, max_leads: int = 12,
             usar_challenger: bool = True) -> dict:
    """Corre el pipeline sobre una estate abierta y devuelve el dict de
    submission (findings, leads_not_pursued, run_metadata).

    `client=None` corre solo las etapas deterministas (1-2): util para medir
    el CART, para depurar sin modelo, y para que el pipeline siga siendo
    ejecutable cuando no hay Ollama levantado. En ese modo no se emite
    ningun finding — sin investigador no hay evidencia que validar.
    """
    m = RunMetrics()
    findings: list[dict] = []
    no_perseguidos: list[dict] = []

    # --- etapas 1-2: SQLite -> CART ------------------------------------
    with m.cronometrar("deterministico_cart"):
        company = estate.identificar_empresa()
        leads = generar_leads(estate)
    m.leads_generados = len(leads)

    if client is None:
        for lead in leads:
            no_perseguidos.append({
                "entity": lead.entity,
                "signal": ", ".join(lead.scheme_hints) or "senales genericas",
                "reason": "Corrida sin modelo (solo etapas deterministas): "
                          "no se investigo ningun lead.",
                "tool_calls_made": [],
                "closed_by": "validator",
            })
        m.findings_finales = 0
        return _submission(findings, no_perseguidos, m, None)

    # --- etapas 3-5: Gemma -> validator -> challenger -------------------
    for lead in leads[:max_leads]:
        try:
            with m.cronometrar("investigador_llm"):
                draft = investigar_lead(estate, lead, client, company=company)
        except LLMUnavailableError as exc:
            no_perseguidos.append({
                "entity": lead.entity,
                "signal": ", ".join(lead.scheme_hints) or "senales genericas",
                "reason": f"El modelo no estuvo disponible: {exc}",
                "tool_calls_made": [],
                "closed_by": "validator",
            })
            continue

        m.leads_investigados += 1

        if not draft.es_fraude:
            no_perseguidos.append({
                "entity": lead.entity,
                "signal": ", ".join(lead.scheme_hints) or "senales genericas",
                "reason": draft.reason_if_not or "El investigador no encontro fraude.",
                "tool_calls_made": list(draft.tool_calls_made),
                "closed_by": "investigator",
            })
            continue

        with m.cronometrar("validator"):
            v = validar(estate, draft)

        if not v.ok:
            m.drafts_rechazados_validator += 1
            no_perseguidos.append({
                "entity": lead.entity,
                "signal": ", ".join(lead.scheme_hints) or "senales genericas",
                "reason": f"El validador rechazo la acusacion: {v.resumen}",
                "tool_calls_made": list(draft.tool_calls_made),
                "closed_by": "validator",
            })
            continue

        confidence = draft.confidence
        if usar_challenger:
            with m.cronometrar("challenger_llm"):
                ch = desafiar(draft, v, client)
            if not ch.sobrevive:
                m.findings_descartados_challenger += 1
                no_perseguidos.append({
                    "entity": lead.entity,
                    "signal": ", ".join(lead.scheme_hints) or "senales genericas",
                    "reason": ch.motivo_descarte,
                    "tool_calls_made": list(draft.tool_calls_made),
                    "closed_by": "challenger",
                })
                continue
            confidence = ch.confidence_final

        exhibits = [{"exhibit_id": f"EX-{i + 1:02d}", **ex} for i, ex in enumerate(draft.exhibits)]
        # El money_trail se arma desde bank_txns, no se le pide al modelo: el
        # schema exige que la cadena conecte, y un LLM narraria un flujo que
        # lee bien y no cuadra con el mayor. Vacio es valido (un
        # phantom_vendor documental no tiene dinero que dibujar); lo que el
        # validador rechaza es que la llave no exista.
        with m.cronometrar("money_trail"):
            trail = construir_money_trail(estate, exhibits, company=company)

        findings.append({
            "scheme_type": draft.scheme_type,
            "entities": list(draft.entities),
            "narrative": draft.narrative,
            "rule_broken": draft.rule_broken,
            "peso_amount": draft.peso_amount,
            "exhibits": exhibits,
            "money_trail": trail,
            "confidence": confidence,
        })

    # Leads que ni siquiera se miraron, por presupuesto.
    for lead in leads[max_leads:]:
        no_perseguidos.append({
            "entity": lead.entity,
            "signal": ", ".join(lead.scheme_hints) or "senales genericas",
            "reason": f"Fuera del presupuesto de investigacion (score {lead.score:.4f}, "
                      f"por debajo de los {max_leads} leads priorizados).",
            "tool_calls_made": [],
            "closed_by": "validator",
        })

    m.findings_finales = len(findings)
    return _submission(findings, no_perseguidos, m, client.usage)


def _submission(findings, no_perseguidos, metrics: RunMetrics, usage) -> dict:
    return {
        "findings": findings,
        "leads_not_pursued": no_perseguidos,
        "run_metadata": metrics.as_run_metadata(usage),
    }
