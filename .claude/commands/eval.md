---
description: "Corre la evaluacion sobre escenarios hold-out y reporta las tres metricas."
argument-hint: "[ruta a los escenarios, por defecto eval/holdout]"
---

Corre `python eval/run_eval.py --scenarios ${ARGUMENTS:-eval/holdout}`.

Reporta:

- Recall de esquemas: de los esquemas inyectados, cuantos encontro y probo.
- Precision de acusaciones: de las acusaciones emitidas, cuantas eran correctas.
- Tasa de falsa acusacion: acusaciones contra proveedores limpios. Objetivo: cero.
- Pasos, llamadas LLM y segundos por caso.

Pega la tabla en docs/crisp-dm/05-evaluation.md con fecha. Si alguna metrica empeoro
respecto a la corrida anterior, dilo primero.
