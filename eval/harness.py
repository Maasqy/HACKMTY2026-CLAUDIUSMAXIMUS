#!/usr/bin/env python3
"""Arnes de evaluacion: submission de referencia + scorer.

VIVE SOLO EN eval/. El agente y sus herramientas nunca importan este archivo.
Es el unico lugar del proyecto, junto con el generador, donde la palabra
ground truth puede aparecer.

Dos usos:

1. Submission de referencia (prueba de humo del estate)
   Construye la respuesta perfecta a partir de la clave y la valida con el
   validador oficial. Si esto no pasa, el estate esta mal construido y ningun
   agente podria producir una respuesta valida sobre el.

       python3 harness.py reference --estate data/estates/estate_0042.db \
           --answers eval/answers/gt_0042.json --out eval/runs/reference_0042.json
       python3 validate_format.py --submission eval/runs/reference_0042.json \
           --estate data/estates/estate_0042.db

2. Scorer
   Compara la submission del agente contra la clave y emite la fila de
   results_table_template.csv.

       python3 harness.py score --submission out/findings_0042.json \
           --answers eval/answers/gt_0042.json --estate data/estates/estate_0042.db
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

PESO_TOLERANCE = 0.02

RULE_BY_TYPE = {
    "phantom_vendor": "SAT Articulo 69-B CFF: deduccion de CFDI emitido por contribuyente en listado definitivo de operaciones inexistentes",
    "kickback": "Conflicto de interes: el mismo empleado solicita y autoriza la compra, y recibe transferencias del proveedor beneficiado",
    "round_tripping": "Simulacion de operacion: el pago regresa a la cuenta de la empresa tras pasar por intermediarios sin funcion economica",
    "threshold_splitting": "Elusion del limite de autorizacion: fraccionamiento sistematico de ordenes de compra por debajo del umbral",
    "revenue_inflation": "Registro de ingresos por operaciones no materializadas al cierre del periodo",
}


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. Submission de referencia
# ---------------------------------------------------------------------------

def build_reference(estate: Path, answers: Path) -> dict:
    gt = load(answers)
    conn = sqlite3.connect(estate)
    conn.row_factory = sqlite3.Row

    findings = []
    for s in gt["schemes"]:
        exhibits, trail, total = [], [], 0.0
        n = 0
        for u in s.get("supporting_invoices", []):
            row = conn.execute("SELECT * FROM invoices WHERE uuid = ?", (u,)).fetchone()
            if row is None:
                continue
            n += 1
            exhibits.append({
                "exhibit_id": f"EX-{n:02d}", "source_table": "invoices", "record_id": u,
                "note": f"Factura por {row['total']:,.2f} MXN con concepto '{row['concepto_text']}'.",
            })
            total += float(row["total"])
        for t in s.get("supporting_txns", [])[:6]:
            row = conn.execute("SELECT * FROM bank_txns WHERE txn_id = ?", (t,)).fetchone()
            if row is None:
                continue
            n += 1
            eid = f"EX-{n:02d}"
            exhibits.append({
                "exhibit_id": eid, "source_table": "bank_txns", "record_id": t,
                "note": f"Transferencia de {row['amount']:,.2f} MXN el {row['date']}.",
            })
            trail.append({"from": row["from_clabe"], "to": row["to_clabe"],
                          "amount": float(row["amount"]), "date": row["date"],
                          "exhibit_id": eid})
        for ent in s["entities"]:
            if ent.startswith("RFC:"):
                rfc = ent[4:]
                table = "vendors"
                row = conn.execute("SELECT rfc FROM vendors WHERE rfc = ?", (rfc,)).fetchone()
            else:
                rfc = ent.split(":", 1)[1]
                rfc = ent          # emp_id ya viene con prefijo EMP:
                table = "employees"
                row = conn.execute("SELECT emp_id FROM employees WHERE emp_id = ?",
                                   (ent,)).fetchone()
            if row is None:
                continue
            n += 1
            exhibits.append({
                "exhibit_id": f"EX-{n:02d}", "source_table": table,
                "record_id": rfc if table == "vendors" else ent,
                "note": "Registro de la entidad involucrada en el esquema.",
            })
        if s["type"] == "phantom_vendor":
            rfc = s["entities"][0][4:]
            row = conn.execute("SELECT * FROM efos_list WHERE rfc = ?", (rfc,)).fetchone()
            if row:
                n += 1
                exhibits.append({
                    "exhibit_id": f"EX-{n:02d}", "source_table": "efos_list", "record_id": rfc,
                    "note": f"Publicado como {row['status']} el {row['publication_date']}.",
                })

        findings.append({
            "scheme_type": s["type"],
            "entities": s["entities"],
            "rule_broken": RULE_BY_TYPE[s["type"]],
            "narrative": (f"Referencia automatica construida desde la clave de respuestas "
                          f"para el esquema {s['scheme_id']}. Sirve unicamente para probar "
                          f"que el estate reconcilia y que el formato valida."),
            "peso_amount": round(total, 2),
            "confidence": "proven",
            "money_trail": trail,
            "exhibits": exhibits,
        })

    leads = [{
        "entity": d["entity"], "signal": d["signal"], "reason": d["why_innocent"],
        "tool_calls_made": ["lookup_vendor", "list_contracts", "trace_payments"],
        "closed_by": "investigator",
    } for d in gt.get("decoys", [])]

    conn.close()
    return {"seed": gt["seed"], "findings": findings, "leads_not_pursued": leads,
            "run_metadata": {"llm_calls": 0, "mxn_cost": 0.0, "wall_clock_seconds": 0.0,
                             "cost_by_role": {}, "deterministic": True}}


# ---------------------------------------------------------------------------
# 2. Scorer
# ---------------------------------------------------------------------------

def entities_of(obj: dict) -> set[str]:
    return {e for e in obj.get("entities", [])}


def score(submission: Path, answers: Path, estate: Path | None) -> dict:
    sub = load(submission)
    gt = load(answers)

    planted = gt["schemes"]
    decoys = {d["entity"] for d in gt.get("decoys", [])}
    findings = sub.get("findings", [])

    matched, used = [], set()
    for i, s in enumerate(planted):
        want = entities_of(s)
        for j, f in enumerate(findings):
            if j in used:
                continue
            if f.get("scheme_type") == s["type"] and want & entities_of(f):
                matched.append((i, j))
                used.add(j)
                break

    accused = {e for f in findings for e in entities_of(f)}
    decoys_accused = accused & decoys

    peso_claimed = sum(float(f.get("peso_amount", 0)) for i, j in matched
                       for f in [findings[j]])
    peso_actual = sum(float(planted[i]["peso_amount"]) for i, j in matched)

    reconciles = True
    if estate:
        conn = sqlite3.connect(estate)
        conn.row_factory = sqlite3.Row
        amount_col = {"invoices": "total", "bank_txns": "amount",
                      "purchase_orders": "amount", "contracts": "value"}
        id_col = {"invoices": "uuid", "bank_txns": "txn_id",
                  "purchase_orders": "po_id", "contracts": "contract_id"}
        for f in findings:
            per: dict[str, float] = {}
            for ex in f.get("exhibits", []):
                t = ex.get("source_table")
                if t not in amount_col:
                    continue
                row = conn.execute(
                    f"SELECT {amount_col[t]} AS a FROM {t} WHERE {id_col[t]} = ?",
                    (str(ex.get("record_id")),)).fetchone()
                if row:
                    per[t] = per.get(t, 0.0) + float(row["a"] or 0)
            claimed = float(f.get("peso_amount", 0) or 0)
            if not per:
                reconciles = False
            else:
                best = min(per.values(), key=lambda v: abs(claimed - v))
                if abs(claimed - best) > PESO_TOLERANCE * max(best, 1):
                    reconciles = False
        conn.close()

    n_planted = len(planted)
    n_decoys = len(decoys)
    meta = sub.get("run_metadata", {})
    return {
        "seed": gt["seed"],
        "schemes_planted": n_planted,
        "schemes_found": len(matched),
        "recall_pct": round(100 * len(matched) / n_planted, 1) if n_planted else 0.0,
        "decoys_planted": n_decoys,
        "decoys_accused": len(decoys_accused),
        "false_accusation_rate_pct": round(100 * len(decoys_accused) / n_decoys, 1) if n_decoys else 0.0,
        "peso_claimed": round(peso_claimed, 2),
        "peso_actual": round(peso_actual, 2),
        "peso_reconciles": "yes" if reconciles else "no",
        "llm_calls": meta.get("llm_calls", ""),
        "mxn_cost": meta.get("mxn_cost", ""),
        "wall_clock_s": meta.get("wall_clock_seconds", ""),
        "_decoys_accused_list": sorted(decoys_accused),
        "_schemes_missed": [planted[i]["scheme_id"] for i in range(n_planted)
                            if i not in {m[0] for m in matched}],
    }


COLUMNS = ["seed", "schemes_planted", "schemes_found", "recall_pct", "decoys_planted",
           "decoys_accused", "false_accusation_rate_pct", "peso_claimed", "peso_actual",
           "peso_reconciles", "llm_calls", "mxn_cost", "wall_clock_s"]


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("reference")
    r.add_argument("--estate", type=Path, required=True)
    r.add_argument("--answers", type=Path, required=True)
    r.add_argument("--out", type=Path, required=True)

    s = sub.add_parser("score")
    s.add_argument("--submission", type=Path, required=True)
    s.add_argument("--answers", type=Path, required=True)
    s.add_argument("--estate", type=Path)
    s.add_argument("--csv", action="store_true", help="imprime la fila lista para el results table")

    args = ap.parse_args()

    if args.cmd == "reference":
        out = build_reference(args.estate, args.answers)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"submission de referencia escrita en {args.out} "
              f"({len(out['findings'])} findings, {len(out['leads_not_pursued'])} leads)")
        return 0

    res = score(args.submission, args.answers, args.estate)
    if args.csv:
        print(",".join(COLUMNS))
        print(",".join(str(res[c]) for c in COLUMNS))
        return 0
    print()
    print(f"  seed {res['seed']}")
    print(f"  recall                  {res['schemes_found']}/{res['schemes_planted']} "
          f"= {res['recall_pct']}%")
    print(f"  falsas acusaciones      {res['decoys_accused']}/{res['decoys_planted']} "
          f"= {res['false_accusation_rate_pct']}%")
    print(f"  pesos reclamados        {res['peso_claimed']:,.2f}")
    print(f"  pesos reales            {res['peso_actual']:,.2f}")
    print(f"  reconcilia              {res['peso_reconciles']}")
    if res["_schemes_missed"]:
        print(f"  esquemas no encontrados {', '.join(res['_schemes_missed'])}")
    if res["_decoys_accused_list"]:
        print(f"  decoys acusados         {', '.join(res['_decoys_accused_list'])}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
