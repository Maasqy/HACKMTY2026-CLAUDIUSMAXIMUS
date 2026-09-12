# 03 — Setup de Claude Code + ECC (affaan-m/ECC)

## Qué es realmente ECC (lo analicé completo)

`affaan-m/ECC` v2.2.1 no es un template de proyecto: es un **plugin de Claude Code**
distribuido por marketplace. Contiene:

- **68 subagentes** (`agents/*.md`) — markdown con frontmatter `name / description / tools /
  model`. Incluyen `planner`, `code-reviewer`, `security-reviewer`, `python-reviewer`,
  `mle-reviewer`, `architect`, `silent-failure-hunter`, `agent-evaluator`, `gan-planner`.
- **292 skills** (`skills/<nombre>/SKILL.md`) — conocimiento invocable bajo demanda.
- **94 slash commands** (`commands/*.md`).
- **Hooks** (`hooks/hooks.json`) — automatizaciones PreToolUse/PostToolUse, incluido
  `gateguard` (bloquea Edit/Write/Bash hasta que el agente investigó los hechos) y
  `delivery-gate` (bloquea el "ya terminé" hasta que pasan checks).
- **rules/** — reglas siempre activas por lenguaje.

**Error que hay que evitar:** clonar o copiar el repo dentro del suyo. El propio README
advierte que no se deben apilar métodos de instalación. Se instala **una vez** como plugin
y ustedes escriben **su propia capa delgada** encima.

## Paso 1 — Instalar ECC (cada miembro del equipo, en su máquina)

Dentro de Claude Code:

```text
/plugin marketplace add https://github.com/affaan-m/ECC
/plugin install ecc@ecc
```

Eso instala skills, agentes, comandos y hooks gestionados por el plugin. **Detente ahí**,
no corras además `./install.sh --profile full`.

Verificación rápida: `/ecc-guide` debe responder y `/plugin` debe listar `ecc@ecc`.

Si el instalador nativo se queja de un scope existente, usa la ruta guiada:
`npx ecc-universal@2.2.1 setup`.

## Paso 2 — Las skills de ECC que SÍ vamos a usar

De las 292, estas son las que aplican al reto. Ignora el resto (no las cargues a mano,
Claude Code las invoca por descripción cuando aplican — solo necesitas saber que existen
para pedirlas por nombre):

| Skill | Para qué en este reto |
|---|---|
| `deep-research` | Investigación multi-fuente con citas — para tipologías de fraude y datasets |
| `recursive-decision-ledger` | **La joya para este reto.** Rollouts repetidos con rastro de evidencia visible, exploración de óptimos locales. Es literalmente el patrón del investigador que cambia de teoría cuando se topa con pared |
| `agent-harness-construction` | Diseñar el action space y el formato de observaciones del agente forense |
| `eval-harness` + `agent-eval` | Evaluación formal antes de confiar en el agente (el criterio "Results") |
| `gateguard` | Fuerza al agente a investigar hechos antes de escribir. Inspiración directa para nuestro Evidence Gate |
| `verification-loop` | Verificar el trabajo antes de declararlo completo |
| `cost-aware-llm-pipeline` | Router de modelos + caché + presupuesto (crítico: el reto avisa de límites) |
| `mle-workflow` | Contratos de datos, reproducibilidad, evaluación |
| `python-patterns`, `python-testing` | Estándares de código |
| `orch-build-mvp` | Convertir el spec en un MVP por rebanadas verticales |
| `plan-canvas` | Revisar el plan visualmente con el equipo |
| `frontend-slides` | Presentación HTML animada para el pitch (al final, no antes) |
| `dashboard-builder` | Visualización del flujo de dinero en la demo |
| `context-budget`, `strategic-compact` | Sobrevivir 36h sin reventar la ventana de contexto |

Agentes de ECC a invocar explícitamente: `planner` (arranque de cada fase),
`architect` (diseño del loop), `silent-failure-hunter` (antes de la demo — busca los
fallos que no truenan pero mienten), `agent-evaluator`, `python-reviewer`,
`security-reviewer` (manejo de datos fiscales).

## Paso 3 — Su capa propia (esto es lo que los diferencia)

ECC les da el andamio genérico. El jurado premia el **dominio**. Creen esto en su repo:

```
.claude/
  agents/
    ledger-investigator.md     # forma hipótesis y navega los libros
    evidence-gatekeeper.md     # adversario interno: rompe acusaciones débiles
    money-tracer.md            # sigue el flujo entre cuentas y arma el grafo
    case-writer.md             # redacta el expediente para un auditor humano
    judge-simulator.md         # simula la pregunta sorpresa del jurado
  skills/
    sat-69b-rules/SKILL.md     # 69-B, estatus, EFOS/EDOS, plazos, qué prueba qué
    cfdi-40-schema/SKILL.md    # campos, catálogos, qué combinación es señal de humo
    fraud-typologies/SKILL.md  # facturación simulada, kickback vía fachada, round-tripping
    evidence-standard/SKILL.md # qué cuenta como prueba y qué no (el estándar interno)
    crisp-dm-logging/SKILL.md  # cómo y dónde documentar cada fase
  commands/
    investigar.md
    caso.md
    bitacora.md
    reto-juez.md
    eval.md
  settings.json                # hooks propios + permisos
```

Formato de un subagente propio (igual que ECC):

```markdown
---
name: evidence-gatekeeper
description: Adversario interno que intenta destruir cada acusación antes de que salga del sistema. Úsalo PROACTIVAMENTE antes de agregar cualquier hallazgo al expediente.
tools: Read, Grep, Glob, Bash
model: opus
---

Tu única función es intentar que la acusación falle...
```

**Por qué agentes separados y no un prompt gigante:** el criterio "Judgment" se gana con
separación de poderes. El que acusa no puede ser el que valida. Eso es demostrable en la
demo y es un argumento de diseño que ningún otro equipo va a tener.

## Paso 4 — Hooks propios

En `.claude/settings.json`, dos hooks que valen oro:

1. **PostToolUse sobre Write/Edit en `src/casefile/`** → corre
   `python scripts/validate_ids.py` y falla si aparece un UUID/RFC que no existe en el
   dataset. Alucinación de identificadores = descalificación ante un auditor.
2. **Stop hook** → bloquea el cierre de sesión si `docs/crisp-dm/` no se tocó en las
   últimas 2 horas de trabajo. Copia el patrón de `delivery-gate` de ECC.

## Paso 5 — Cómo trabajan 4 personas sin pisarse

- `main` protegida, PRs con `/code-review` de ECC antes de merge.
- Cuatro carriles paralelos con interfaces acordadas **en la hora 1**:
  - **A — Data estate**: generador de patrimonio + inyector de esquemas + hold-out.
  - **B — Detectores + herramientas**: el action space que consume el agente.
  - **C — Loop forense + evidence gate**: el corazón.
  - **D — Expediente, demo y CRISP-DM docs**: y es quien entrevista al papá.
- El contrato entre A y B/C es un **schema JSON congelado en la hora 2**. Si cambia
  después, cambia por PR y se avisa en el canal.
- Cada quien corre su propia sesión de Claude Code. Contexto compartido = el repo, no el chat.

## Paso 6 — Rituales de sesión (esto es lo que salva hackathons)

- Cada 4 horas: `/bitacora` → consolidar decisiones en `docs/crisp-dm/`.
- Antes de cada merge a `main`: `/eval` y pegar métricas en el PR.
- Hora -6 antes del pitch: congelar features. Solo bugs y demo.
- Hora -3: `silent-failure-hunter` sobre todo el repo + ensayo cronometrado del demo
  con `judge-simulator` haciendo la pregunta sorpresa.

## Sobre las tareas programadas en el Proyecto de Claude.ai

Sirven, pero pocas. Durante 36 horas la mayoría del valor está en rituales manuales.
Las tres que sí valen:

1. **Cada 6 h — "Checkpoint de riesgo"**: que revise el estado declarado del proyecto y
   liste los 3 riesgos que más probablemente hunden la demo, con la mitigación más barata.
2. **Cada 8 h — "Simulacro de juez"**: que genere 5 preguntas adversarias nuevas sobre el
   diseño actual y las respuestas que deberíamos tener listas.
3. **Una vez, mañana del pitch — "Auditoría de claridad"**: que lea el expediente de
   ejemplo y marque todo lo que un director de finanzas no entendería en 30 segundos.

No programes tareas de código: Claude Code las hace mejor en contexto.
