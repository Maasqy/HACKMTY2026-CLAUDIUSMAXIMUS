"""
src/forensic/investigator.py — etapa 3 del pipeline.

    SQLite -> CART -> [Gemma: AQUI] -> validator -> challenger -> reporting

Takes one Lead (the hypothesis produced by src/scoring) and runs the model
over it with the EstateDB tool surface attached, so it can do the actual
forensic work: pull the real invoices, read the exact transfer dates, check
whether a contract or purchase order backs each operation, and decide
whether the pattern is fraud or a legitimate corporate movement.

What this stage does NOT do:
  - It does not accuse. It returns a DRAFT. The validator (etapa 4) checks
    every cited record_id against SQLite and reconciles peso_amount before
    anything is allowed to become a Finding, precisely because a model can
    hallucinate a UUID that looks perfectly well-formed.
  - It never sees ground truth. Its only inputs are the estate and the lead.

The tool loop is bounded by MAX_STEPS_PER_RUN: a model that keeps calling
tools without concluding is a cost leak, and an unbounded loop cannot give
the wall-clock number the spec asks for.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from src.config import MAX_STEPS_PER_RUN
from src.forensic.client import LLMClient, LLMUnavailableError
from src.forensic.prompts import CONCLUSION_KEY, TOOL_CALL_KEY, system_with_tools, user_prompt
from src.tools.tool_specs import build_tool_specs, dispatch


@dataclass(frozen=True, slots=True)
class FindingDraft:
    """The investigator's conclusion about one lead — NOT a Finding yet.

    `es_fraude=False` is a first-class outcome, not a failure: it becomes a
    leads_not_pursued entry with `reason` in the final submission, which the
    spec requires to live in the case file body rather than an appendix.
    """
    entity: str
    es_fraude: bool
    scheme_type: Optional[str]
    entities: tuple[str, ...]
    narrative: str
    rule_broken: str
    peso_amount: float
    exhibits: tuple[dict, ...]
    confidence: str
    reason_if_not: str
    # Nombres de las herramientas llamadas, en orden. El schema pide un
    # array de strings ("que consultaste"), no un contador.
    tool_calls_made: tuple[str, ...]
    raw: dict = field(default_factory=dict, compare=False)


def _as_draft(entity: str, data: dict, tool_calls: tuple[str, ...]) -> FindingDraft:
    ents = data.get("entities") or [entity]
    if isinstance(ents, str):
        ents = [ents]
    exhibits = data.get("exhibits") or []
    if not isinstance(exhibits, list):
        exhibits = []
    try:
        peso = round(float(data.get("peso_amount") or 0.0), 2)
    except (TypeError, ValueError):
        peso = 0.0
    conf = data.get("confidence")
    if conf not in ("proven", "probable"):
        conf = "probable"
    return FindingDraft(
        entity=entity,
        es_fraude=bool(data.get("es_fraude")),
        scheme_type=data.get("scheme_type"),
        entities=tuple(str(e) for e in ents),
        narrative=str(data.get("narrative") or "").strip(),
        rule_broken=str(data.get("rule_broken") or "").strip(),
        peso_amount=peso,
        exhibits=tuple(e for e in exhibits if isinstance(e, dict)),
        confidence=conf,
        reason_if_not=str(data.get("reason_if_not") or "").strip(),
        tool_calls_made=tuple(tool_calls),
        raw=data,
    )


def investigar_lead(estate, lead, client: LLMClient, company=None,
                    max_steps: int = MAX_STEPS_PER_RUN) -> FindingDraft:
    """Runs the forensic loop over one lead and returns its draft.

    Tool calling is PROMPTED, not Ollama's native `tools` API — see
    src/forensic/prompts.py for why: gemma3 (what this project ships with)
    is not in the small list of models Ollama supports native tool-calling
    for, and passing `tools` to it 400s on every call. Instead the model is
    asked to reply with one of two small JSON shapes: a tool request
    ({TOOL_CALL_KEY: name, "arguments": {...}}) or a conclusion
    ({CONCLUSION_KEY: true/false, ...}). `format="json"` constrains
    decoding so the reply is reliably valid JSON on any model.

    On an unreachable model this raises LLMUnavailableError — the caller
    decides whether a run without the LLM is still worth producing. On a
    reply the client cannot parse, it returns a draft with es_fraude=False
    and a reason saying so, because one unreadable answer should cost one
    lead, not the whole run.
    """
    company = company or estate.identificar_empresa()
    tool_specs = build_tool_specs(type(estate))
    messages = [
        {"role": "system", "content": system_with_tools(tool_specs)},
        {"role": "user", "content": user_prompt(lead, company.rfc)},
    ]

    tool_calls_made: list[str] = []
    intentos_sin_json = 0
    for _ in range(max_steps):
        msg = client.chat(messages, format="json")
        content = (msg.get("content") or "").strip()
        data = _parse_json(content)

        if not data:
            # Sin JSON legible: se pide una vez mas, explicitamente. Si
            # insiste en no dar JSON dos veces seguidas, se corta — seguir
            # insistiendo indefinidamente es el mismo costo que un loop sin
            # limite, solo que mas lento de notar.
            intentos_sin_json += 1
            if intentos_sin_json > 2:
                break
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user",
                             "content": "Tu respuesta no fue JSON valido. Responde SOLO con "
                                       f"el objeto {{\"{TOOL_CALL_KEY}\": ...}} o "
                                       f"{{\"{CONCLUSION_KEY}\": ...}}, sin texto alrededor."})
            continue
        intentos_sin_json = 0

        if CONCLUSION_KEY in data:
            return _as_draft(lead.entity, data, tuple(tool_calls_made))

        if TOOL_CALL_KEY not in data:
            # JSON valido pero ninguna de las dos formas esperadas.
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user",
                             "content": f"Ese JSON no trae ni \"{TOOL_CALL_KEY}\" ni "
                                       f"\"{CONCLUSION_KEY}\". Responde con uno de los dos."})
            continue

        name = str(data.get(TOOL_CALL_KEY, ""))
        args = data.get("arguments") or {}
        if isinstance(args, str):
            args = _parse_json(args) or {}
        tool_calls_made.append(name)
        try:
            result = dispatch(estate, name, args)
            payload = _serializar_resultado(result)
        except Exception as exc:  # herramienta inexistente o argumento invalido
            payload = json.dumps({"error": f"{type(exc).__name__}: {exc}"},
                                 ensure_ascii=False)
        messages.append({"role": "assistant", "content": content})
        # Sin rol "tool" (eso tambien es parte de la API nativa que no
        # usamos): el resultado vuelve como un turno de usuario normal, que
        # cualquier modelo de chat entiende sin soporte especial.
        messages.append({"role": "user",
                         "content": f"RESULTADO de {name}:\n{payload}\n\n"
                                   f"Continua investigando (otro {{\"{TOOL_CALL_KEY}\": ...}}) "
                                   f"o concluye ({{\"{CONCLUSION_KEY}\": ...}})."})

    return FindingDraft(
        entity=lead.entity, es_fraude=False, scheme_type=None, entities=(lead.entity,),
        narrative="", rule_broken="", peso_amount=0.0, exhibits=(), confidence="probable",
        reason_if_not=f"El investigador agoto {max_steps} pasos sin concluir.",
        tool_calls_made=tuple(tool_calls_made),
    )


MAX_TOOL_PAYLOAD = 6000


def _serializar_resultado(result) -> str:
    """Serializa el resultado de una herramienta, recortando por ELEMENTOS
    cuando es muy grande — nunca cortando el string a la mitad.

    Recortar el JSON ya serializado (`json.dumps(...)[:6000]`) deja una
    cadena sintacticamente rota que el modelo no puede leer, y el modelo no
    tiene forma de saber que le llego basura: simplemente alucina sobre un
    payload corrupto. Aqui se recortan filas y se le dice explicitamente
    cuantas se omitieron, para que pueda pedir un filtro mas estrecho.
    """
    texto = json.dumps(result, ensure_ascii=False, default=str)
    if len(texto) <= MAX_TOOL_PAYLOAD:
        return texto

    if isinstance(result, list) and result:
        recorte = list(result)
        while recorte and len(json.dumps(recorte, ensure_ascii=False, default=str)) > MAX_TOOL_PAYLOAD - 200:
            recorte = recorte[:max(1, int(len(recorte) * 0.7))]
            if len(recorte) == 1:
                break
        return json.dumps({
            "resultados": recorte,
            "_truncado": f"Se muestran {len(recorte)} de {len(result)} filas. "
                         f"Filtra mas (por RFC, fecha o monto) para ver el resto.",
        }, ensure_ascii=False, default=str)

    return json.dumps({
        "_truncado": "El resultado excede el tamano maximo; pide un subconjunto mas especifico."
    }, ensure_ascii=False)


def _parse_json(content: str) -> dict:
    content = (content or "").strip()
    if not content:
        return {}
    if content.startswith("```"):
        content = content.strip("`")
        content = content.split("\n", 1)[1] if "\n" in content else content
        content = content.rsplit("```", 1)[0] if "```" in content else content
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        a, b = content.find("{"), content.rfind("}")
        if a >= 0 and b > a:
            try:
                return json.loads(content[a:b + 1])
            except json.JSONDecodeError:
                return {}
        return {}
