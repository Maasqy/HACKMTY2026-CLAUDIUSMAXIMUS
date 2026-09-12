"""Punto de entrada. La ruta del estate se recibe en tiempo de ejecucion.

    python3 -m src.run --estate data/estates/estate_0042.db --out submission.json
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--estate", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    if not args.estate.exists():
        raise SystemExit(f"No existe el estate: {args.estate}")

    started = time.time()

    # PENDIENTE: detectores -> leads -> investigator -> challenger -> validator
    findings: list[dict] = []
    leads_not_pursued: list[dict] = []

    submission = {
        "seed": args.seed,
        "findings": findings,
        "leads_not_pursued": leads_not_pursued,
        "run_metadata": {
            "llm_calls": 0,
            "mxn_cost": 0.0,
            "wall_clock_seconds": round(time.time() - started, 2),
            "cost_by_role": {},
            "deterministic": True,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(submission, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"{args.out}  findings={len(findings)}  leads={len(leads_not_pursued)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
