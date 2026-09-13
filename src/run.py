"""Punto de entrada. La ruta del estate se recibe en tiempo de ejecucion.

    python3 -m src.run --estate data/estates/estate_0042.db --out out/submission.json

Baseline zero-LLM:
  1. Deriva la empresa auditada (RFC + CLABE) con contraste cruzado.
  2. Corre los detectores registrados.
  3. Para cada lead intenta promoter -> validator; si el gate aprueba va a
     findings, si no, va a leads_not_pursued con closed_by='validator' y la
     razon concreta.
  4. Serializa determinista.

Ningun umbral aqui. Todo vive en src/config.py.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from src.forensic.client import LLMClient
from src.pipeline import ejecutar
from src.tools import EstateDB



def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.run")
    ap.add_argument("--estate", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-leads", type=int, default=12,
                    help="cuantos leads investigar (presupuesto de LLM)")
    ap.add_argument("--sin-modelo", action="store_true",
                    help="solo etapas deterministas, sin llamar al LLM")
    ap.add_argument("--offline", action="store_true",
                    help="replay desde el cache, sin red")
    args = ap.parse_args()

    if not args.estate.exists():
        print(f"No existe el estate: {args.estate}", file=sys.stderr)
        return 2

    seed = args.seed if args.seed is not None else _seed_from_path(args.estate, 0)

    metrics = RunMetrics()
    metrics.start()

    # detectores -> leads -> investigator -> validator -> challenger.
    # Todo el orden vive en src/pipeline.py; aqui solo se parsean argumentos.
    # --sin-modelo corre unicamente las etapas deterministas, util cuando
    # Ollama no esta levantado.
    client = None if args.sin_modelo else LLMClient(offline=args.offline)
    with EstateDB(args.estate) as estate:
        submission = ejecutar(estate, client, max_leads=args.max_leads)

    submission["seed"] = args.seed
    submission["run_metadata"].setdefault("cost_by_role", {})
    findings = submission["findings"]
    leads_not_pursued = submission["leads_not_pursued"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(submission, indent=2, ensure_ascii=True, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    # Nota: `emitter` ya cerro con el `with`; los eventos finales se re-abren
    # aparte para escribir las tres metricas finales sin depender del context.
    if not args.no_events:
        events_path = args.events or (args.out.parent / f"events_{seed:04d}.jsonl")
        with events_path.open("a", encoding="utf-8", buffering=1, newline="\n") as fh:
            for line in (
                {"seq": 10**6, "t": metadata["wall_clock_seconds"], "type": "metrics",
                 "entity": "", "payload": metadata},
                {"seq": 10**6 + 1, "t": metadata["wall_clock_seconds"], "type": "run_finished",
                 "entity": "", "payload": {
                     "findings": len(findings),
                     "leads_not_pursued": len(leads_not_pursued),
                 }},
            ):
                fh.write(json.dumps(line, ensure_ascii=True))
                fh.write("\n")
    print(
        f"{args.out}  findings={len(findings)}  leads={len(leads_not_pursued)}  "
        f"seed={seed}"
    )
    return 0


def _lead_to_dict(lead, motivo: str) -> dict:
    return {
        "entity": lead.entity,
        "signal": lead.signal,
        "reason": f"{lead.reason} | Cerrado por validator: {motivo}",
        "tool_calls_made": [lead.detector_id],
        "closed_by": "validator",
    }


def _finding_sort_key(f: dict) -> tuple:
    first_entity = (f.get("entities") or [""])[0]
    return (f.get("scheme_type", ""), first_entity, -float(f.get("peso_amount", 0)))


def _lead_sort_key(l: dict) -> tuple:
    return (l.get("signal", ""), l.get("entity", ""))


if __name__ == "__main__":
    raise SystemExit(main())
