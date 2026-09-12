# 04 — Prompts maestros

Cinco prompts. El primero es el que pega en Claude Code en la sesión 0 y define todo
el resto del hackathon. Los otros cuatro son de apoyo.

---

## PROMPT A — Bootstrap del repositorio (sesión 0 de Claude Code)

> Requisitos previos: ECC instalado, `CLAUDE.md` (archivo 02) ya en la raíz del repo,
> `data/raw/Listado_completo_69-B.csv` presente.

```
Eres el arquitecto técnico de un equipo de 4 personas en HackMTY 2026. Reto: "The
Forensic Auditor" de Infosys. Lee CLAUDE.md antes de responder cualquier cosa.

## Objetivo de esta sesión
Dejar el repositorio listo para que 4 personas trabajen en paralelo durante 36 horas.
NO vas a implementar el agente todavía. Vas a construir el esqueleto, los contratos de
datos y el andamio de evaluación, en ese orden.

## Contexto del reto que no puedes perder de vista
El agente recibirá libros contables que nunca ha visto, con la sola pista de que "algo
está mal". Debe encontrar el esquema de fraude, seguir el dinero, probarlo con evidencia,
y negarse explícitamente a acusar a quien no puede respaldar. En la demo, los jueces
esconden un esquema fresco en los datos y hacen una pregunta sorpresa sobre el
razonamiento del agente. Los criterios son Results, Judgment, Feasibility y Clarity, con
el mismo peso. Judgment y Clarity se ganan con disciplina de evidencia y narrativa, no
con modelado.

## Restricciones duras
- 36 horas, 4 personas, un solo repositorio.
- Muchas llamadas LLM por investigación: diseña desde el inicio con modelo local (Ollama)
  + caché en disco por hash de prompt, y reserva el modelo grande para síntesis.
- Cero alucinación de identificadores: todo UUID/RFC/folio en un output debe existir en
  el dataset cargado.
- El Evidence Gate es código determinista, nunca un prompt.

## Metodología
Seguimos CRISP-DM y el jurado valora explícitamente el proceso de pensamiento. Cada
decisión de diseño produce un archivo en docs/decisions/ con: decisión, alternativas
consideradas, por qué se descartaron, y qué la haría reversible.

## Usa estos recursos de ECC (están instalados)
- Subagente `planner` para descomponer, `architect` para el diseño del loop.
- Skill `agent-harness-construction` para diseñar el action space y el formato de
  observaciones del agente forense.
- Skill `recursive-decision-ledger` para el patrón de investigación con rastro de
  evidencia y cambio de teoría ante callejones sin salida.
- Skill `eval-harness` para el andamio de evaluación.
- Skill `cost-aware-llm-pipeline` para el router de modelos y el presupuesto.
Cita explícitamente qué skill estás aplicando en cada decisión.

## Plan de esta sesión — ejecuta en este orden, deteniéndote en cada puerta

### Puerta 1 — Interrogatorio (NO escribas código todavía)
Hazme exactamente las preguntas cuya respuesta cambiaría el diseño. Máximo 7, en una
sola tanda, numeradas. Si puedes deducir la respuesta de CLAUDE.md, no la preguntes.
Espera mi respuesta.

### Puerta 2 — Contratos de datos
Propón el esquema del patrimonio de datos: ledger (pólizas), CFDIs, movimientos
bancarios, padrón de proveedores, y el archivo de ground truth de los esquemas
inyectados. Para cada tabla: columnas, tipos, llaves, y cómo se unen entre sí.
Explica qué campo hace posible cada uno de los detectores listados en CLAUDE.md.
Marca cuáles campos vienen del estándar CFDI 4.0 real y cuáles son invención nuestra.
Espera mi aprobación.

### Puerta 3 — Action space del agente
Aplicando `agent-harness-construction`, define las herramientas tipadas que el agente
puede llamar sobre el patrimonio. Para cada una: firma, qué devuelve, y por qué existe.
Regla: ninguna herramienta devuelve "todo"; toda herramienta devuelve evidencia citable
con IDs. Justifica el número de herramientas — demasiadas degradan la tasa de acierto.
Espera mi aprobación.

### Puerta 4 — Esqueleto
Crea la estructura de carpetas de CLAUDE.md con archivos stub que compilan y tests que
fallan a propósito con un mensaje claro de qué falta. Incluye:
- src/forensic/evidence_gate.py con el contrato de la acusación y sus tests completos
  (esta pieza sí se implementa hoy, entera).
- eval/scorer.py con las tres métricas definidas: recall de esquemas, precisión de
  acusaciones, tasa de falsa acusación contra proveedores limpios.
- scripts/fetch_data.sh, .gitignore, pyproject.toml, Makefile con los comandos de uso.
- docs/crisp-dm/ con los 6 archivos de fase, cada uno con su plantilla y la fase 1
  (Business Understanding) ya redactada a partir de este contexto.

### Puerta 5 — Reparto
Propón la división en 4 carriles paralelos con las interfaces exactas entre ellos, qué
puede hacer cada carril sin esperar a los otros, y el orden en que deben integrarse.
Incluye el primer commit que debe hacer cada persona.

## Formato de tus respuestas
- Directo, sin preámbulo. Tablas cuando comparas opciones.
- Cuando hay una decisión no obvia: recomendación + alternativa + razón, en 3 líneas.
- Si algo no cabe en 36 horas, dilo con el recorte propuesto, no lo silencies.
- Nunca inventes métricas, montos ni resultados. Escribe "PENDIENTE — medir con {script}".

Empieza por la Puerta 1.
```

---

## PROMPT B — Diseño del loop forense (sesión 1, después del bootstrap)

```
Implementa el loop de investigación siguiendo el patrón de `recursive-decision-ledger`.

El loop recibe: un patrimonio de datos cargado y la pista "algo está mal en estos libros".
No recibe ninguna otra señal.

Requisitos de comportamiento, en orden de importancia:

1. HIPÓTESIS EXPLÍCITA. Antes de cualquier consulta, el agente declara qué cree que está
   pasando y qué evidencia confirmaría o refutaría esa creencia. Ambas cosas: qué la
   confirmaría y qué la MATARÍA.
2. CAMBIO DE TEORÍA. Si dos consultas seguidas no mueven la hipótesis, la abandona,
   escribe por qué, y pasa al siguiente lead. Un investigador terco es un mal
   investigador y el jurado lo va a notar.
3. SEPARACIÓN DE PODERES. El agente que construye la acusación nunca la aprueba. Invoca
   al subagente `evidence-gatekeeper` cuyo único trabajo es intentar destruirla. Solo si
   sobrevive, y solo si pasa el Evidence Gate determinista, entra al expediente.
4. LEADS NO PERSEGUIDOS. Todo lead descartado se registra con su razón. Esta lista es
   entregable explícito del reto, no un subproducto.
5. PRESUPUESTO. El loop tiene un límite de pasos y de llamadas. Al agotarse, entrega lo
   que tiene con una nota honesta de qué quedó sin investigar. Nunca rellena.

Implementa InvestigationLog como estructura de datos, no como texto: cada entrada es
{paso, hipótesis, herramienta, argumentos, hallazgo, decisión, razón}. La demo proyecta
esta estructura en vivo, así que debe ser legible por un humano sin traducción.

Escribe los tests primero. Un test debe verificar que, sobre un dataset SIN fraude
inyectado, el agente termina con cero acusaciones y una explicación de por qué no acusó.
Ese test es el más importante del repositorio.
```

---

## PROMPT C — Deep research de datasets (para Perplexity, Gemini o el skill `deep-research`)

```
Necesito un inventario exhaustivo de fuentes de datos gratuitas y legalmente utilizables
para construir un simulador de "patrimonio de datos contables" de una empresa mexicana,
con fines de un hackathon de detección de fraude de facturación (EFOS/EDOS, art. 69-B CFF).

Busca y evalúa, con URL directa de descarga y fecha de última actualización:

1. Listado 69-B del SAT: todas las variantes publicadas (presuntos, definitivos,
   desvirtuados, sentencia favorable), formato, frecuencia de actualización, y si existe
   un endpoint o solo descarga manual.
2. Catálogos oficiales del Anexo 20 / CFDI 4.0: c_ClaveProdServ, c_FormaPago,
   c_MetodoPago, c_UsoCFDI, c_RegimenFiscal. XSD y catálogos en formato tabular.
3. Datasets públicos de contratación pública mexicana con nombres reales de proveedores,
   montos y fechas (CompraNet histórico, datos.gob.mx, estándar EDCA/OCDS).
4. Directorio de proveedores y contratistas sancionados de la SFP: formato y descarga.
5. Generadores sintéticos de transacciones financieras con tipologías de lavado
   etiquetadas: IBM AMLSim, IBM AML-Data, PaySim, y cualquier alternativa más reciente.
   Para cada uno: qué requiere para correr (Java, Python, tamaño), si trae etiquetas de
   ground truth, y cuánto tarda en producir un dataset de ~100k transacciones.
6. Cualquier dataset público de asientos contables (general ledger / journal entries) con
   anomalías etiquetadas, académico o de competencia.
7. Papers o guías con tipologías documentadas de facturación simulada en México y sus
   señales observables en datos.

Para cada fuente entrega: nombre, URL, licencia, tamaño, esquema de columnas, qué señal
de fraude habilita, y una calificación de 1 a 5 de "utilidad para un hackathon de 36
horas" considerando el costo de ponerla a funcionar.

Termina con una recomendación de 3 fuentes máximo y el plan de ensamblado entre ellas.
No incluyas fuentes de pago ni scrapers de sitios que lo prohíban.
```

---

## PROMPT D — Simulador de juez (usar cada 8 horas)

```
Actúa como el juez más escéptico del panel de Infosys. Eres director de auditoría con 20
años de experiencia y has visto cientos de herramientas que prometen detectar fraude.

Te voy a mostrar un hallazgo de nuestro agente forense [pegar expediente].

Tu trabajo:
1. Encuentra la debilidad más grave de la cadena de evidencia. No la más obvia: la más
   grave.
2. Formula la pregunta que dejaría al equipo sin respuesta en el escenario.
3. Pregúntate si acusarías a ese proveedor con esta evidencia y explica tu respuesta como
   se la explicarías a un abogado.
4. Dime qué pieza de evidencia adicional convertiría esto de "sospechoso" a "accionable".

Sé breve y brutal. No nos felicites.
```

---

## PROMPT E — Auditoría de claridad del expediente (día del pitch)

```
Lee este expediente como si fueras el director de finanzas de la empresa auditada, con 90
segundos de atención y sin formación técnica.

1. Marca cada frase que no entenderías de inmediato.
2. Dime en qué punto exacto perdiste el hilo del dinero.
3. Reescribe el resumen ejecutivo en máximo 5 líneas, en las que el monto, el esquema y la
   prueba queden claros.
4. Dime qué gráfico hace falta y por qué.

No sugieras mejoras de diseño visual. Solo comprensión.
```
