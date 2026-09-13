"""
src/forensic/prompts.py

Prompt text for the investigator (etapa 3). Kept apart from the loop so the
wording can be reviewed without reading control flow.

What is deliberately NOT in here: thresholds, the approval limit, the peso
tolerance, the exhibit minimum, the scheme_type enum. Those live in
src/config.py and src/detectors/, because the track requires business
constraints to be in code rather than in a prompt — a number a model can
paraphrase is a number nobody can audit.

TOOL CALLING IS PROMPTED, NOT NATIVE. Ollama's native `tools` API only
works on a small, hardcoded subset of models (llama3.1, qwen2.5, a few
others) — gemma3, the model this project actually ships with, is not in
that list, and passing `tools` to it 400s on every single call with
"does not support tools". That is not a degraded mode, it is a hard
failure with zero findings, and it is exactly what this project hit.

So tools are described here in plain text, and the model is asked to
request one by replying with a small JSON object rather than through
Ollama's tool-calling field. This works on any model, because it is not a
model feature — it is text the model reads and JSON it writes, the same
trick every LLM tool-use library used before native function calling
existed. `LLMClient.chat(..., format="json")` (not `tools=`) constrains
the model's decoding to valid JSON so the reply is reliably parseable.
"""

from __future__ import annotations

from src.config import MAX_NARRATIVE_WORDS, MIN_EXHIBITS, SCHEME_TYPES, SOURCE_TABLES

CONCLUSION_KEY = "es_fraude"   # top-level key that marks a final answer
TOOL_CALL_KEY = "tool"         # top-level key that marks a tool request


def tools_catalog(tool_specs: list[dict]) -> str:
    """Renders build_tool_specs()'s output as plain text for the prompt.

    One line per tool: its name, its parameters with their JSON types, and
    the first line of its docstring. The full signature stays visible so
    the model doesn't have to guess an argument name — a wrong key means a
    dispatch() error, one wasted step, and (worse, silently) a model that
    might quietly give up on a tool it thinks doesn't exist.
    """
    lineas = []
    for spec in tool_specs:
        fn = spec["function"]
        props = fn["parameters"].get("properties", {})
        required = set(fn["parameters"].get("required", []))
        args = ", ".join(
            f"{name}: {info['type']}" + ("" if name in required else " (opcional)")
            for name, info in props.items()
        )
        primera_linea = (fn.get("description") or "").strip().split("\n", 1)[0]
        lineas.append(f"  - {fn['name']}({args})\n      {primera_linea}")
    return "\n".join(lineas)


def system_with_tools(tool_specs: list[dict]) -> str:
    """The system prompt, with the tool catalog and the prompted
    tool-calling protocol appended. See the module docstring for why this
    is prompted instead of Ollama's native `tools` parameter."""
    return f"""Eres un auditor forense trabajando sobre la contabilidad de UNA empresa mexicana.

Recibes una HIPOTESIS generada por reglas deterministas y un modelo estadistico: una entidad
(RFC o EMP) que parece participar en un esquema de fraude, con la evidencia preliminar que
disparo esa sospecha.

Tu trabajo NO es confiar en la hipotesis. Es verificarla contra los datos reales usando las
herramientas disponibles, y concluir si se sostiene o no. Una hipotesis estadistica no es una
acusacion: un score alto no prueba nada ante un auditor.

COMO TRABAJAS:
- Consulta los datos con las herramientas. Nunca inventes un UUID, un txn_id, un monto ni una
  fecha: si no lo leiste de una herramienta, no existe.
- Revisa las fechas exactas de las transferencias, los conceptos de las facturas, y si hay
  contrato u orden de compra que respalde cada operacion.
- Pregúntate siempre si existe una explicacion corporativa legitima para el patron. Un pago
  rapido, un proveedor nuevo o un monto redondo NO son fraude por si solos.

HERRAMIENTAS DISPONIBLES (consultan la base de datos real; no tienes otra forma de leerla):
{tools_catalog(tool_specs)}

COMO LLAMAS A UNA HERRAMIENTA:
Responde SOLO con este objeto JSON, sin texto alrededor:

{{"{TOOL_CALL_KEY}": "<nombre_exacto_de_la_herramienta>", "arguments": {{"param": "valor"}}}}

Te devuelvo el resultado en el siguiente turno y continuas. Puedes llamar herramientas varias
veces, una por turno, hasta tener evidencia suficiente para concluir.

CUANDO CONCLUYAS, responde SOLO con este otro objeto JSON, sin texto alrededor:

{{
  "{CONCLUSION_KEY}": true | false,
  "scheme_type": uno de {list(SCHEME_TYPES)},
  "entities": ["RFC:XXX", "EMP:0001"],
  "narrative": "que paso, en menos de {MAX_NARRATIVE_WORDS} palabras",
  "rule_broken": "la regla de control o la norma fiscal que se incumplio",
  "peso_amount": 0.00,
  "exhibits": [
    {{"source_table": "invoices", "record_id": "<uuid real>", "note": "que prueba"}}
  ],
  "confidence": "proven" | "probable",
  "reason_if_not": "si es_fraude=false, por que la hipotesis no se sostiene"
}}

REGLAS DE LA SALIDA:
- Nunca mezcles los dos objetos ni agregues texto fuera del JSON: cada respuesta tuya es
  UNA llamada a herramienta O UNA conclusion, nunca ambas ni ninguna.
- Minimo {MIN_EXHIBITS} exhibits, todos con record_id leido de una herramienta.
- "source_table" de cada exhibit DEBE ser exactamente uno de estos valores literales, en
  ingles, SIN TRADUCIR: {list(SOURCE_TABLES)}. Son los nombres reales de las tablas SQL, no
  una descripcion: "bank_txns" (no "transferencias"), "purchase_orders" (no "ordenes de
  compra"), etc. Cualquier otro valor es rechazado por el validador.
- peso_amount debe ser la suma de los montos de los exhibits que citas, no una estimacion.
- Si la evidencia no alcanza, responde es_fraude=false con reason_if_not. Es una respuesta
  valida y preferible a acusar de mas: acusar a una entidad honesta cuesta mas que dejar
  pasar un caso dudoso."""


def user_prompt(lead, company_rfc: str) -> str:
    """The hypothesis handed to the model: what fired, on whom, and the
    exhibits the deterministic rules already cited — so the model starts
    from real record ids instead of going fishing."""
    lineas = [
        f"EMPRESA AUDITADA: {company_rfc}",
        f"ENTIDAD BAJO SOSPECHA: {lead.entity}",
        f"SCORE DE LA HIPOTESIS: {lead.score:.4f} (ranking interno, NO es probabilidad de fraude)",
    ]
    if lead.scheme_hints:
        lineas.append(f"ESQUEMAS SUGERIDOS: {', '.join(lead.scheme_hints)}")
    if lead.ml_scheme_type and lead.ml_scheme_type != "no_esquema":
        lineas.append(f"CLASIFICADOR (CART) dice: {lead.ml_scheme_type}")
    if lead.ml_situacion_sat and lead.ml_situacion_sat != "no_listado":
        lineas.append(f"STATUS SAT 69-B estimado: {lead.ml_situacion_sat}")

    lineas.append("\nSENALES DETERMINISTAS QUE DISPARARON (cada una con su evidencia):")
    if not lead.signals:
        lineas.append("  (ninguna: esta hipotesis viene solo del clasificador, "
                      "verifica con mas cuidado)")
    for s in lead.signals:
        lineas.append(f"  - [{s.detector}] fuerza {s.strength}: {s.description}")
        for ex in s.evidence:
            lineas.append(f"      exhibit candidato: {ex.source_table}/{ex.record_id} — {ex.note}")

    lineas.append(
        "\nVerifica esto contra los datos reales. Los exhibits candidatos son un punto de "
        "partida: confirmalos con las herramientas y descarta los que no aguanten. "
        "Concluye con el JSON."
    )
    return "\n".join(lineas)
