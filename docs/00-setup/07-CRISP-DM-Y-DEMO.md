# 07 — CRISP-DM aplicado al hackathon + guion de demo

## Por qué CRISP-DM les conviene aquí

Los presentadores dijeron que valoran el proceso de pensamiento. CRISP-DM les da tres
cosas que un equipo improvisado no tiene: un vocabulario que un consultor de Infosys
reconoce al instante, una razón defendible para cada decisión, y —la más importante— un
lugar legítimo donde documentar **lo que descartaron**. En un reto cuyo entregable
incluye explícitamente "la lista de pistas que decidió no perseguir y por qué", la
metodología y el producto riman. Díganlo así en el pitch: *el agente investiga como
nosotros investigamos*.

## Mapeo fase → horas → artefacto

| Fase CRISP-DM | Horas | Qué hacen | Artefacto en el repo |
|---|---|---|---|
| **1. Business Understanding** | 0–3 | Reto, criterios de juicio, entrevista al director de finanzas, definición interna de "evidencia", alcance y anti-alcance | `docs/crisp-dm/01-business-understanding.md` |
| **2. Data Understanding** | 2–6 | Inventario de fuentes, esquema del 69-B y CFDI 4.0, qué señal habilita cada campo, qué NO se puede saber con estos datos | `docs/crisp-dm/02-data-understanding.md` |
| **3. Data Preparation** | 4–12 | Generador de patrimonio, inyector de esquemas, ground truth, hold-out sellado | `docs/crisp-dm/03-data-preparation.md` + `src/estate/` |
| **4. Modeling** | 8–26 | Detectores deterministas, action space, loop de investigación, evidence gate, expediente | `docs/crisp-dm/04-modeling.md` + `src/` |
| **5. Evaluation** | 20–32 | Recall sobre hold-out, tasa de falsa acusación, ablaciones, casos donde falla | `docs/crisp-dm/05-evaluation.md` + `eval/` |
| **6. Deployment** | 30–36 | Demo, expediente ejemplar, guion, respuestas a preguntas sorpresa | `docs/crisp-dm/06-deployment.md` + `demo/` |

Las fases se traslapan a propósito: CRISP-DM es cíclico, no una cascada. Lo que **no**
se traslapa: no empiecen Modeling antes de tener ground truth, porque sin etiquetas no
saben si su agente funciona o si solo suena convincente.

## Las dos iteraciones que sí van a ocurrir

Anótenlas cuando pasen, con hora. Son evidencia de método, no de fracaso.

- **Vuelta de Evaluation a Data Preparation**: van a descubrir que sus esquemas
  inyectados son demasiado fáciles y el agente los encuentra siempre. Súbanle dificultad.
- **Vuelta de Evaluation a Business Understanding**: van a descubrir un caso donde el
  agente técnicamente tiene razón pero un auditor no acusaría. Ahí es donde ajustan la
  definición de evidencia con lo que dijo el papá.

## Ablaciones para la sección de Evaluation

Esto es lo que separa un proyecto de hackathon de un proyecto que parece de investigación.
Corran el eval quitando una pieza a la vez y reporten la tabla:

| Configuración | Recall de esquemas | Falsas acusaciones | Pasos por caso |
|---|---|---|---|
| Completo | PENDIENTE | PENDIENTE | PENDIENTE |
| Sin detectores (solo LLM libre) | PENDIENTE | PENDIENTE | PENDIENTE |
| Sin evidence gate | PENDIENTE | PENDIENTE | PENDIENTE |
| Sin gatekeeper adversario | PENDIENTE | PENDIENTE | PENDIENTE |
| Solo detectores (sin agente) | PENDIENTE | PENDIENTE | PENDIENTE |

La fila que más les conviene es "sin evidence gate": debería mostrar recall igual o mayor
con falsas acusaciones disparadas. Ese es el gráfico que prueba su tesis entera.

## Guion de demo — 3 minutos exactos

El reto especifica: los jueces esconden un esquema fresco, el agente rastrea el dinero en
pantalla, y responde una pregunta sorpresa. Ensáyenlo cronometrado al menos tres veces.

**0:00–0:20 — El problema, no el producto.**
Una frase con el dolor real: cuando un proveedor aparece en el 69-B definitivo, la
empresa ya dedujo y tiene 30 días. Nadie sigue el dinero completo.

**0:20–0:35 — Reciban el dataset del juez en vivo.**
Que uno de los jueces genere la semilla o elija el escenario. Que se vea que no está
preparado. Este momento vale más que cualquier slide.

**0:35–2:10 — El agente investiga, en pantalla.**
Muestren el `InvestigationLog` avanzando: hipótesis declarada → consulta → hallazgo →
decisión. Narren **un** cambio de teoría ("aquí el agente creyó que era X, se topó con
pared, y giró"). Después el grafo del flujo de dinero armándose. Después el expediente
con el monto.

**2:10–2:35 — El momento que ganan.**
Muestren la lista de leads no perseguidos y **el proveedor trampa que el agente decidió
no acusar**, con su razón textual. Digan: *encontró el fraude y también supo callarse*.

**2:35–3:00 — Métrica y cierre.**
Una cifra de recall sobre hold-out, una de falsas acusaciones (idealmente cero), y la
frase de cierre: la diferencia entre un reporte que se cae y un caso sobre el que una
empresa puede actuar.

## Preparen estas cinco respuestas antes de subir al escenario

1. *¿Cómo sé que no memorizó los datos?* → hold-out sellado, semilla del juez, métricas.
2. *¿Qué pasa si el proveedor es honesto y solo se ve raro?* → el caso trampa, en vivo.
3. *¿Por qué no un modelo de machine learning?* → no hay etiquetas reales de fraude de
   facturación mexicano; y un score sin cadena de evidencia no es accionable para el SAT.
4. *¿Cuánto cuesta correr esto?* → tokens y costo por investigación, medidos, del router.
5. *¿Qué NO detecta?* → tengan la respuesta lista y sean honestos. Un equipo que conoce
   sus límites se ve más creíble que uno que promete todo. Este es el criterio Feasibility.
