"""Punto de entrada. La ruta del estate se recibe en tiempo de ejecucion.

    python3 -m src.run --estate data/estates/estate_0042.db --out submission.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from src.forensic.client import LLMClient
from src.pipeline import ejecutar
from src.tools import EstateDB


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--estate", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-leads", type=int, default=12,
                    help="cuantos leads investigar (presupuesto de LLM)")
    ap.add_argument("--sin-modelo", action="store_true",
                    help="solo etapas deterministas, sin llamar al LLM")
    ap.add_argument("--offline", action="store_true",
                    help="replay desde el cache, sin red")
    ap.add_argument("--silencioso", action="store_true",
                    help="no imprimir progreso a stderr mientras corre (por defecto SI se "
                        "imprime: un modelo local de 12B puede tardar 10-40s por turno, y sin "
                        "esto la terminal se queda muda por minutos — indistinguible de un "
                        "cuelgue)")
    args = ap.parse_args()

    if not args.estate.exists():
        raise SystemExit(f"No existe el estate: {args.estate}")

    started = time.time()

    def progreso(texto: str) -> None:
        print(f"[{time.time() - started:6.1f}s] {texto}", file=sys.stderr, flush=True)

    # detectores -> leads -> investigator -> validator -> challenger.
    # Todo el orden vive en src/pipeline.py; aqui solo se parsean argumentos.
    # --sin-modelo corre unicamente las etapas deterministas, util cuando
    # Ollama no esta levantado.
    client = None if args.sin_modelo else LLMClient(offline=args.offline)
    with EstateDB(args.estate) as estate:
        submission = ejecutar(estate, client, max_leads=args.max_leads,
                              on_progress=None if args.silencioso else progreso)

    submission["seed"] = args.seed
    submission["run_metadata"].setdefault("cost_by_role", {})
    findings = submission["findings"]
    leads_not_pursued = submission["leads_not_pursued"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(submission, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"{args.out}  findings={len(findings)}  leads={len(leads_not_pursued)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
