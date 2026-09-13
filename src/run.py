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

from src.detectors import run_all as run_detectors
from src.forensic.company import CompanyDerivationConflict, derive_company
from src.forensic.promoter import promote
from src.forensic.validator import validate
from src.metrics.events import EventEmitter, NullEmitter
from src.metrics.run_metrics import RunMetrics
from src.tools.estate_access import EstateDB, EstateNotFoundError


def _seed_from_path(path: Path, fallback: int) -> int:
    m = re.search(r"(\d+)", path.stem)
    return int(m.group(1)) if m else fallback


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.run")
    ap.add_argument("--estate", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--company-rfc", type=str, default=None,
                    help="RFC de la empresa auditada; si se omite, se deriva del estate.")
    ap.add_argument("--events", type=Path, default=None,
                    help="ruta del jsonl de eventos; default out/events_<seed>.jsonl")
    ap.add_argument("--no-events", action="store_true",
                    help="no emitir events.jsonl (util para tests o benchmarks)")
    args = ap.parse_args(argv)

    if not args.estate.exists():
        print(f"No existe el estate: {args.estate}", file=sys.stderr)
        return 2

    seed = args.seed if args.seed is not None else _seed_from_path(args.estate, 0)

    metrics = RunMetrics()
    metrics.start()

    findings: list[dict] = []
    leads_not_pursued: list[dict] = []

    if args.no_events:
        emitter = NullEmitter()
    else:
        events_path = args.events or (args.out.parent / f"events_{seed:04d}.jsonl")
        emitter = EventEmitter(events_path)

    try:
        with EstateDB(args.estate) as db, emitter:
            emitter.emit("run_started", "", {"seed": seed, "estate": str(args.estate)})
            try:
                company = derive_company(db, rfc_override=args.company_rfc)
            except CompanyDerivationConflict as e:
                print(f"[company-derivation] FAIL: {e}", file=sys.stderr)
                emitter.emit("run_finished", "", {"status": "company_conflict", "error": str(e)})
                return 3
            print(f"[company-derivation] {company.evidence}", file=sys.stderr)
            emitter.emit("metrics", "", {"company_rfc": company.rfc, "company_clabe": company.clabe})

            leads = run_detectors(db, company)
            for lead in leads:
                emitter.emit("lead_opened", lead.entity, {
                    "signal": lead.signal,
                    "detector": lead.detector_id,
                    "monto_estimado": lead.monto_estimado,
                    "reason": lead.reason,
                })
                result = promote(lead, db, company)
                if result.candidate is None:
                    leads_not_pursued.append(_lead_to_dict(lead, result.reason))
                    emitter.emit("lead_closed", lead.entity, {
                        "closed_by": "validator",
                        "reason": result.reason,
                    })
                    continue
                verdict = validate(result.candidate, db)
                if verdict.aprobado:
                    findings.append(result.candidate)
                    emitter.emit("finding", lead.entity, result.candidate)
                else:
                    leads_not_pursued.append(_lead_to_dict(lead, verdict.motivo))
                    emitter.emit("lead_closed", lead.entity, {
                        "closed_by": "validator",
                        "reason": verdict.motivo,
                    })
    except EstateNotFoundError as e:
        print(f"[estate] {e}", file=sys.stderr)
        return 2

    metrics.stop()

    findings.sort(key=_finding_sort_key)
    leads_not_pursued.sort(key=_lead_sort_key)

    metadata = metrics.as_dict()
    submission = {
        "seed": seed,
        "findings": findings,
        "leads_not_pursued": leads_not_pursued,
        "run_metadata": metadata,
    }
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
