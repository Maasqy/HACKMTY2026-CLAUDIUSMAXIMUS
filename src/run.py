"""Punto de entrada. La ruta del estate se recibe en tiempo de ejecucion.

    python3 -m src.run --estate data/estates/estate_0042.db --out out/submission.json

`main(argv=None)` acepta un argv explicito (en vez de leer solo sys.argv)
porque eval/sweep.py y tests/test_pipeline.py lo importan y lo llaman como
funcion (`run_main(["--estate", ..., "--out", ...])`), no solo como script.

`--events` es opcional (ver frontend/README.md: "opcional, con --events").
El frontend cae a datos mock si `out/events.jsonl` no existe, asi que esto
NUNCA se activa por default. Cuando se pide, escribe run_started/metrics/
run_finished con el emisor real de src/metrics/events.py — instrumentar
cada paso interno del investigador (lead_opened, tool_call, evidence,
challenge, lead_closed) es trabajo aparte, de quien construya esa parte
del frontend; esto solo deja el archivo bien formado con lo que ya se
sabe al terminar la corrida.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from src.forensic.client import LLMClient
from src.metrics.events import EventEmitter, NullEmitter
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
    ap.add_argument("--silencioso", action="store_true",
                    help="no imprimir progreso a stderr mientras corre (por defecto SI se "
                        "imprime: un modelo local de 12B puede tardar 10-40s por turno, y sin "
                        "esto la terminal se queda muda por minutos — indistinguible de un "
                        "cuelgue)")
    ap.add_argument("--events", type=Path, default=None, nargs="?",
                    const=Path("out/events.jsonl"),
                    help="ruta opcional de events.jsonl para el frontend (ver "
                        "frontend/README.md). Sin esta bandera no se escribe nada: "
                        "es opcional, la UI cae a datos mock si no existe. Pasarla "
                        "sin valor usa out/events.jsonl.")
    args = ap.parse_args(argv)

    if not args.estate.exists():
        print(f"No existe el estate: {args.estate}", file=sys.stderr)
        return 2

    started = time.time()

    def progreso(texto: str) -> None:
        print(f"[{time.time() - started:6.1f}s] {texto}", file=sys.stderr, flush=True)

    emitter = EventEmitter(args.events) if args.events else NullEmitter()

    # detectores -> leads -> investigator -> validator -> challenger.
    # Todo el orden vive en src/pipeline.py; aqui solo se parsean argumentos.
    # --sin-modelo corre unicamente las etapas deterministas, util cuando
    # Ollama no esta levantado.
    client = None if args.sin_modelo else LLMClient(offline=args.offline)
    with emitter:
        emitter.emit("run_started", "", {"estate": str(args.estate), "seed": args.seed})
        with EstateDB(args.estate) as estate:
            submission = ejecutar(estate, client, max_leads=args.max_leads,
                                  on_progress=None if args.silencioso else progreso)

        submission["seed"] = args.seed
        submission["run_metadata"].setdefault("cost_by_role", {})
        findings = submission["findings"]
        leads_not_pursued = submission["leads_not_pursued"]
        emitter.emit("metrics", "", submission["run_metadata"])
        emitter.emit("run_finished", "", {
            "findings": len(findings),
            "leads_not_pursued": len(leads_not_pursued),
        })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(submission, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"{args.out}  findings={len(findings)}  leads={len(leads_not_pursued)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
