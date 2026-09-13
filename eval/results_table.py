#!/usr/bin/env python3
"""
eval/results_table.py — la tabla del criterio Results, en el formato exacto
que pide docs/spec/results_table_template.csv.

VIVE SOLO EN eval/. Lee gt_NNNN.json para puntuar, y por eso NO puede estar
bajo src/: el agente nunca importa este archivo. Es, junto con el generador
y eval/harness.py, uno de los tres lugares del proyecto donde la frase
"ground truth" tiene permiso de aparecer.

Corre el pipeline completo sobre varias seeds del holdout sellado y emite
una fila por seed con lo que los jueces miden:

  recall            cuantos esquemas plantados encontramos
  false_accusation  cuantas entidades honestas (decoys) acusamos de mas
  peso_reconciles   si el monto reclamado cuadra con el real
  llm_calls / mxn_cost / wall_clock_s

Las reglas del template, que este script respeta:
  - >=5 seeds no vistas para las bandas altas.
  - Recall SOLO no es puntuable: un sistema que acusa a todos llega a 100%.
  - Hay que nombrar en que seeds se ajusto y en cuales se reporta, y deben
    ser disjuntas. Este script imprime ambos conjuntos al final.

Uso:
    python3 eval/results_table.py --out eval/runs/results_table.csv
    python3 eval/results_table.py --sin-modelo      # solo etapas deterministas
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.forensic.client import LLMClient  # noqa: E402
from src.pipeline import ejecutar  # noqa: E402
from src.tools import EstateDB  # noqa: E402

COLUMNAS = ["seed", "schemes_planted", "schemes_found", "recall_pct",
            "decoys_planted", "decoys_accused", "false_accusation_rate_pct",
            "peso_claimed", "peso_actual", "peso_reconciles",
            "llm_calls", "mxn_cost", "wall_clock_s"]

TUNING_SEEDS = "1-200"
REPORT_SEEDS = [921, 922, 923, 924, 925]


def _entidades_acusadas(submission: dict) -> set[str]:
    ents: set[str] = set()
    for f in submission.get("findings", []):
        ents.update(f.get("entities", []))
    return ents


def evaluar_seed(db_path: Path, gt_path: Path, client, max_leads: int) -> dict:
    gt = json.loads(gt_path.read_text(encoding="utf-8"))
    plantadas = {e for s in gt["schemes"] for e in s["entities"]}
    decoys = {d["entity"] for d in gt.get("decoys", []) if "entity" in d}
    peso_real = round(sum(float(s.get("peso_amount", 0) or 0) for s in gt["schemes"]), 2)

    with EstateDB(db_path) as estate:
        sub = ejecutar(estate, client, max_leads=max_leads)

    acusadas = _entidades_acusadas(sub)
    encontradas = plantadas & acusadas
    falsas = decoys & acusadas
    peso_reclamado = round(sum(float(f.get("peso_amount", 0) or 0)
                               for f in sub.get("findings", [])), 2)

    # "Reconcilia" aqui es contra el ground truth: el monto que reclamamos
    # frente al que realmente movieron los esquemas plantados. Es distinto de
    # la reconciliacion interna del validador (monto vs exhibits citados),
    # que ya se verifico antes de imprimir cada finding.
    reconcilia = (abs(peso_reclamado - peso_real) <= 0.02 * max(peso_real, 1.0)
                  if peso_reclamado else False)

    md = sub["run_metadata"]
    return {
        "seed": db_path.stem.split("_")[1],
        "schemes_planted": len(plantadas),
        "schemes_found": len(encontradas),
        "recall_pct": round(100 * len(encontradas) / max(len(plantadas), 1), 1),
        "decoys_planted": len(decoys),
        "decoys_accused": len(falsas),
        "false_accusation_rate_pct": round(100 * len(falsas) / max(len(decoys), 1), 1),
        "peso_claimed": peso_reclamado,
        "peso_actual": peso_real,
        "peso_reconciles": "si" if reconcilia else "no",
        "llm_calls": md.get("llm_calls", 0),
        "mxn_cost": md.get("mxn_cost", 0.0),
        "wall_clock_s": md.get("wall_clock_seconds", 0.0),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--estates-dir", type=Path, default=REPO / "data" / "holdout_sealed" / "estates")
    ap.add_argument("--gt-dir", type=Path, default=REPO / "eval" / "holdout_sealed" / "answers")
    ap.add_argument("--seeds", type=int, nargs="*", default=REPORT_SEEDS)
    ap.add_argument("--out", type=Path, default=REPO / "eval" / "runs" / "results_table.csv")
    ap.add_argument("--max-leads", type=int, default=12)
    ap.add_argument("--sin-modelo", action="store_true")
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()

    client = None if args.sin_modelo else LLMClient(offline=args.offline)

    filas = []
    for seed in args.seeds:
        tag = f"{seed:04d}"
        db, gt = args.estates_dir / f"estate_{tag}.db", args.gt_dir / f"gt_{tag}.json"
        if not db.exists() or not gt.exists():
            print(f"  saltando seed {tag}: falta {db.name} o {gt.name}")
            continue
        fila = evaluar_seed(db, gt, client, args.max_leads)
        filas.append(fila)
        print(f"  seed {tag}: recall {fila['recall_pct']}% | "
              f"falsas acusaciones {fila['false_accusation_rate_pct']}% | "
              f"{fila['llm_calls']} llamadas | {fila['wall_clock_s']}s")

    if not filas:
        raise SystemExit("Ninguna seed evaluada. Corre scripts/rebuild_estates.sh primero.")

    total = {
        "seed": "TOTAL",
        "schemes_planted": sum(f["schemes_planted"] for f in filas),
        "schemes_found": sum(f["schemes_found"] for f in filas),
        "decoys_planted": sum(f["decoys_planted"] for f in filas),
        "decoys_accused": sum(f["decoys_accused"] for f in filas),
        "peso_claimed": round(sum(f["peso_claimed"] for f in filas), 2),
        "peso_actual": round(sum(f["peso_actual"] for f in filas), 2),
        "llm_calls": sum(f["llm_calls"] for f in filas),
        "mxn_cost": round(sum(f["mxn_cost"] for f in filas), 4),
        "wall_clock_s": round(sum(f["wall_clock_s"] for f in filas), 2),
    }
    total["recall_pct"] = round(100 * total["schemes_found"] / max(total["schemes_planted"], 1), 1)
    total["false_accusation_rate_pct"] = round(
        100 * total["decoys_accused"] / max(total["decoys_planted"], 1), 1)
    total["peso_reconciles"] = f"{sum(1 for f in filas if f['peso_reconciles'] == 'si')}/{len(filas)}"
    filas.append(total)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNAS)
        w.writeheader()
        w.writerows(filas)

    print()
    print(f"TOTAL: recall {total['recall_pct']}% | "
          f"falsas acusaciones {total['false_accusation_rate_pct']}% | "
          f"{total['llm_calls']} llamadas | ${total['mxn_cost']} MXN | "
          f"{total['wall_clock_s']}s")
    print(f"Tuning seeds : {TUNING_SEEDS}")
    print(f"Report seeds : {', '.join(str(s) for s in args.seeds)}  (disjuntas del tuning)")
    print(f"escrito: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
