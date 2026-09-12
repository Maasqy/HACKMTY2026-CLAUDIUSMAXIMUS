---
name: crisp-dm-logging
description: Donde y como documentar cada decision del proyecto segun la fase de CRISP-DM. Consultar al cerrar una sesion de trabajo o al tomar una decision de diseno.
---

# Donde va cada cosa

| Fase | Archivo |
|---|---|
| Business Understanding | docs/crisp-dm/01-business-understanding.md |
| Data Understanding | docs/crisp-dm/02-data-understanding.md |
| Data Preparation | docs/crisp-dm/03-data-preparation.md |
| Modeling | docs/crisp-dm/04-modeling.md |
| Evaluation | docs/crisp-dm/05-evaluation.md |
| Deployment | docs/crisp-dm/06-deployment.md |

Decisiones de arquitectura: un archivo corto en docs/decisions/, nombrado
`NNN-titulo-corto.md`, con cuatro secciones y nada mas:

```
## Decision
## Alternativas consideradas
## Por que se descarto cada una
## Que la haria reversible
```

# Reglas

- Se documenta cuando la decision se toma, no al final. Al final nadie se acuerda.
- Lo que se descarta se documenta igual que lo que se elige. La bitacora de callejones sin
  salida es entregable: el reto pide explicitamente la lista de leads no perseguidos y su
  razon, y el jurado dijo que valora el proceso de pensamiento.
- Nunca escribir metricas sin haberlas medido. Se escribe `PENDIENTE - medir con {script}`.
- Cada entrada lleva fecha y autor.
