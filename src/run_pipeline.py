"""
src/run_pipeline.py

Punto de entrada del pipeline completo.

    python3 -m src.run_pipeline --estate data/estates/estate_0001.db --out submission.json

NOTA: src/run.py es de otra persona del equipo y esta intacto. Cuando quieran
unificarlos, el cableado es una linea:

    from src.pipeline import ejecutar
    submission = ejecutar(estate, client)

Modos:
  (sin flags)        pipeline completo, requiere el modelo levantado
  --sin-modelo       solo etapas deterministas (SQLite -> CART). No emite
                     findings; sirve para medir el CART y para depurar.
  --offline          sirve las respuestas del cache, sin tocar la red. Es el
                     modo de "replay sin conexion" que pide la spec; falla si
                     el cache no cubre la corrida, en vez de degradar callado.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from src.config import LLM_BASE_URL, LLM_MODEL
from src.forensic.client import LLMClient
from src.pipeline import ejecutar
from src.tools import EstateDB


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--estate", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-leads", type=int, default=12,
                    help="cuantos leads investigar (presupuesto de LLM)")
    ap.add_argument("--sin-modelo", action="store_true",
                    help="solo etapas deterministas, sin llamar al LLM")
    ap.add_argument("--offline", action="store_true",
                    help="replay desde el cache, sin red")
    ap.add_argument("--sin-challenger", action="store_true")
    ap.add_argument("--modelo", default=LLM_MODEL, help=f"tag de ollama (default {LLM_MODEL})")
    ap.add_argument("--base-url", default=LLM_BASE_URL)
    ap.add_argument("--silencioso", action="store_true",
                    help="no imprimir progreso a stderr (un modelo local de 12B puede tardar "
                        "10-40s por turno; sin esto, varios minutos de silencio son "
                        "indistinguibles de un cuelgue)")
    args = ap.parse_args()

    if not args.estate.exists():
        raise SystemExit(f"No existe el estate: {args.estate}")

    started = time.time()

    def progreso(texto: str) -> None:
        print(f"[{time.time() - started:6.1f}s] {texto}", file=sys.stderr, flush=True)

    client = None
    if not args.sin_modelo:
        client = LLMClient(model=args.modelo, base_url=args.base_url, offline=args.offline)

    with EstateDB(args.estate) as estate:
        submission = ejecutar(estate, client, max_leads=args.max_leads,
                               usar_challenger=not args.sin_challenger,
                               on_progress=None if args.silencioso else progreso)

    submission["seed"] = args.seed
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(submission, indent=2, ensure_ascii=False), encoding="utf-8")

    md = submission["run_metadata"]
    emb = md["embudo"]
    print(f"escrito: {args.out}")
    print(f"  findings            : {len(submission['findings'])}")
    print(f"  leads_not_pursued   : {len(submission['leads_not_pursued'])}")
    print(f"  llm_calls           : {md['llm_calls']}   mxn_cost: {md['mxn_cost']}")
    print(f"  wall_clock_seconds  : {md['wall_clock_seconds']}")
    print(f"  embudo              : {emb['leads_generados']} leads -> "
          f"{emb['leads_investigados']} investigados -> "
          f"{emb['rechazados_por_validator']} frenados por validator -> "
          f"{emb['descartados_por_challenger']} tumbados por challenger -> "
          f"{emb['findings_finales']} findings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
