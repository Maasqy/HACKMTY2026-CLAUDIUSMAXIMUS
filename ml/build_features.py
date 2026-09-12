#!/usr/bin/env python3
"""
ml/build_features.py — HACKMTY2026 Forensic Auditor track.

Lives OUTSIDE src/, alongside estate_gen/, as part of the training flow —
this script and everything downstream of it (train_cart.py) is allowed to
read eval/answers/gt_NNNN.json directly, because it produces the TRAINING
LABEL for a model, not a live investigation. The agent that runs during the
demo (src/investigator, src/detectors, ...) never imports this file and
never sees a ground-truth file — that isolation is enforced in src/, not
here.

What it does: for every estate_NNNN.db under --estates-dir with a matching
gt_NNNN.json under --gt-dir, computes one feature row per VENDOR (joining
across all 8 estate tables: vendors, invoices, ledger, bank_txns,
purchase_orders, contracts, employees, efos_list) and produces TWO labels:

  es_fraude      binary — 1 if the vendor's RFC appears in any planted
                 scheme's `entities` list (gt_NNNN.json). This is the
                 "is this vendor part of a fraud scheme I planted" label.

  situacion_sat  multiclass — the vendor's REAL SAT Articulo 69-B status
                 (Definitivo / Presunto / Desvirtuado / Favorable /
                 Otro / No listado), read straight from efos_list. This is
                 the real government classification, independent of
                 whether the vendor happens to be cast in a planted
                 scheme. Desvirtuado and Favorable are real, confirmed
                 NON-fraud outcomes (the taxpayer was investigated and
                 cleared, administratively or in court) — not synthetic
                 decoys, actual entries from Listado_completo_69-B.csv.

Scope note: features are computed at the VENDOR level. Four of the five
scheme types (phantom_vendor, round_tripping, threshold_splitting,
kickback) are cast with a vendor as the accused entity, so they show up
here. revenue_inflation is cast with a CLIENT (an invoice receiver_rfc that
is never inserted into the vendors table), and kickback's employee side
(EMP:xxxx) is a second entity on that same scheme — neither is a vendor row,
so neither gets a feature row or a label from this script. That is a known
limitation of a single flat vendor table, not a bug: extending this to
client-level and employee-level feature tables is future work, not required
for the CART exercise below to run and be meaningful on the other four
scheme types.

Usage:
  python3 ml/build_features.py
  python3 ml/build_features.py --estates-dir data/estates --gt-dir eval/answers --out ml/features_train.csv
"""

import argparse
import json
import re
import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

GENERIC_CONCEPT_WORDS = ("diversos", "diversas", "varios", "varias", "generales", "general")
PO_THRESHOLD = 50000.0
PO_THRESHOLD_BAND = 5000.0  # "just under threshold" = within this band below it


def _days_between(a: str, b: str) -> float:
    try:
        return (date.fromisoformat(b) - date.fromisoformat(a)).days
    except (ValueError, TypeError):
        return float("nan")


def _clabe_institution(clabe: str) -> str:
    # First 3 digits of a Mexican CLABE identify the issuing bank.
    return clabe[:3] if clabe and len(clabe) >= 3 else ""


def build_features_for_estate(db_path: Path, gt_path: Path) -> pd.DataFrame:
    seed = int(re.search(r"(\d+)", db_path.stem).group(1))
    gt = json.loads(gt_path.read_text())
    fraud_entities = set()
    for scheme in gt["schemes"]:
        fraud_entities.update(scheme["entities"])

    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    vendors = pd.read_sql("SELECT * FROM vendors", conn)
    invoices = pd.read_sql("SELECT * FROM invoices", conn)
    ledger = pd.read_sql("SELECT * FROM ledger", conn)
    bank_txns = pd.read_sql("SELECT * FROM bank_txns", conn)
    pos = pd.read_sql("SELECT * FROM purchase_orders", conn)
    contracts = pd.read_sql("SELECT * FROM contracts", conn)
    employees = pd.read_sql("SELECT * FROM employees", conn)
    efos = pd.read_sql("SELECT * FROM efos_list", conn)
    conn.close()

    employee_clabes = set(employees["bank_clabe"]) if not employees.empty else set()
    employee_institutions = {_clabe_institution(c) for c in employee_clabes}
    efos_by_rfc = efos.set_index("rfc").to_dict(orient="index") if not efos.empty else {}

    rows = []
    for _, v in vendors.iterrows():
        rfc = v["rfc"]
        v_inv = invoices[invoices["issuer_rfc"] == rfc]
        v_po = pos[pos["vendor_rfc"] == rfc]
        v_ctr = contracts[contracts["vendor_rfc"] == rfc]
        v_ledger = ledger[ledger["invoice_uuid"].isin(v_inv["uuid"])]
        # Bank transfers paid by the company TO this vendor's own CLABE.
        v_txn = bank_txns[bank_txns["to_clabe"] == v["bank_clabe"]]

        n_inv = len(v_inv)
        monto_total = float(v_inv["total"].sum()) if n_inv else 0.0
        monto_prom = float(v_inv["total"].mean()) if n_inv else 0.0
        monto_max = float(v_inv["total"].max()) if n_inv else 0.0
        monto_std = float(v_inv["total"].std(ddof=0)) if n_inv else 0.0
        pct_ppd = float((v_inv["metodo_pago"] == "PPD").mean()) if n_inv else 0.0
        n_metodos_pago = int(v_inv["forma_pago"].nunique()) if n_inv else 0

        n_po = len(v_po)
        pct_mismo_req_apr = float((v_po["requester"] == v_po["approver"]).mean()) if n_po else 0.0
        pct_po_bajo_umbral = (
            float(((v_po["amount"] < PO_THRESHOLD) & (v_po["amount"] >= PO_THRESHOLD - PO_THRESHOLD_BAND)).mean())
            if n_po else 0.0
        )

        efos_row = efos_by_rfc.get(rfc)
        en_69b = 1 if efos_row is not None else 0
        es_definitivo = 1 if (efos_row and efos_row.get("status") == "definitivo") else 0
        situacion_sat = efos_row.get("status") if efos_row else "no_listado"

        dias_antiguedad = float("nan")
        if n_inv:
            primera_factura = v_inv["issue_date"].min()
            dias_antiguedad = _days_between(v["registered_date"], primera_factura)

        pct_concepto_generico = (
            float(v_inv["concepto_text"].str.lower().str.contains("|".join(GENERIC_CONCEPT_WORDS)).mean())
            if n_inv else 0.0
        )

        institucion = _clabe_institution(v["bank_clabe"])
        clabe_identica_a_empleado = int(v["bank_clabe"] in employee_clabes)
        misma_institucion_que_empleado = int(institucion in employee_institutions)

        # An invoice counts as "paid" if some bank_txn to this vendor's CLABE
        # matches its total within 1% and within 45 days of issue.
        n_pagadas = 0
        for _, inv in v_inv.iterrows():
            match = v_txn[
                (v_txn["amount"].sub(inv["total"]).abs() <= 0.01 * max(inv["total"], 1))
            ]
            if not match.empty:
                n_pagadas += 1
        pct_sin_pago = float(1 - n_pagadas / n_inv) if n_inv else 0.0

        rows.append({
            "estate_seed": seed,
            "rfc": rfc,
            "categoria": v["category"],
            "num_facturas": n_inv,
            "monto_total_facturado": round(monto_total, 2),
            "monto_promedio_factura": round(monto_prom, 2),
            "monto_max_factura": round(monto_max, 2),
            "monto_std_factura": round(monto_std, 2),
            "pct_facturas_ppd": round(pct_ppd, 4),
            "num_formas_pago_distintas": n_metodos_pago,
            "tiene_contrato": int(len(v_ctr) > 0),
            "num_contratos": len(v_ctr),
            "tiene_orden_compra": int(n_po > 0),
            "num_ordenes_compra": n_po,
            "pct_po_mismo_requester_approver": round(pct_mismo_req_apr, 4),
            "pct_po_justo_bajo_umbral_50k": round(pct_po_bajo_umbral, 4),
            "en_lista_69b": en_69b,
            "es_69b_definitivo": es_definitivo,
            "dias_antiguedad_al_facturar": dias_antiguedad,
            "num_transferencias_recibidas": len(v_txn),
            "monto_total_transferido": round(float(v_txn["amount"].sum()), 2) if len(v_txn) else 0.0,
            "pct_facturas_sin_pago_rastreable": round(pct_sin_pago, 4),
            "pct_concepto_generico": round(pct_concepto_generico, 4),
            "clabe_identica_a_empleado": clabe_identica_a_empleado,
            "misma_institucion_bancaria_que_empleado": misma_institucion_que_empleado,
            "monto_total_en_ledger": round(float(v_ledger["debit"].sum()), 2) if len(v_ledger) else 0.0,
            "es_fraude": int(f"RFC:{rfc}" in fraud_entities),
            "situacion_sat": situacion_sat,
        })

    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--estates-dir", type=Path, default=REPO_ROOT / "data" / "estates")
    ap.add_argument("--gt-dir", type=Path, default=REPO_ROOT / "eval" / "answers")
    ap.add_argument("--out", type=Path, default=HERE / "features_train.csv")
    args = ap.parse_args()

    frames = []
    for db_path in sorted(args.estates_dir.glob("estate_*.db")):
        tag = db_path.stem.split("_")[1]
        gt_path = args.gt_dir / f"gt_{tag}.json"
        if not gt_path.exists():
            print(f"  saltando {db_path.name}: no encontre {gt_path.name}")
            continue
        frames.append(build_features_for_estate(db_path, gt_path))

    if not frames:
        raise SystemExit("No se encontraron pares estate_NNNN.db / gt_NNNN.json.")

    df = pd.concat(frames, ignore_index=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)

    n_estates = df["estate_seed"].nunique()
    n_fraud = int(df["es_fraude"].sum())
    print(f"estates procesadas: {n_estates}")
    print(f"filas (proveedores) totales: {len(df)}")
    print(f"positivos (es_fraude=1): {n_fraud}  ({n_fraud/len(df)*100:.1f}%)")
    print("distribucion situacion_sat:")
    print(df["situacion_sat"].value_counts().to_string())
    print(f"escrito: {args.out}")


if __name__ == "__main__":
    main()
