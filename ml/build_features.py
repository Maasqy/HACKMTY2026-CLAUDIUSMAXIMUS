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
purchase_orders, contracts, employees, efos_list) and produces labels:

  scheme_type    multiclass, THE PRIMARY TARGET — one of the five official
                 scheme_type enum values (phantom_vendor, kickback,
                 round_tripping, threshold_splitting, revenue_inflation)
                 if this vendor's RFC appears in a planted scheme's
                 `entities` list, else 'no_esquema'. This is the actual
                 judged task: "what kind of fraud scheme, if any, is this
                 entity part of" — not a proxy for it. Note: if a scheme is
                 entangled (two schemes sharing an entity, which the spec
                 allows judges to test but our own generator doesn't yet
                 plant), this takes the FIRST matching scheme_type; true
                 multi-label handling is scope for later, flagged in
                 main()'s output if it ever occurs on this dataset.

  es_fraude      binary convenience label, 1 iff scheme_type != 'no_esquema'.
                 Kept for anyone who wants a binary cut instead of the
                 5-class one; not itself the primary target anymore.

  situacion_sat  multiclass SECONDARY signal, NOT the fraud target — the
                 vendor's REAL SAT Articulo 69-B status. Only 'definitivo',
                 'presunto' and 'no_listado' can occur: estate_schema.sql
                 defines efos_list.status as ONLY 'definitivo' | 'presunto',
                 so 'desvirtuado'/'favorable' vendors (real, government-
                 confirmed CLEARED taxpayers, still planted as decoy
                 material) are recorded in gt_NNNN.json's `decoys`, never in
                 efos_list — they cannot appear as a situacion_sat value.
                 Rationale for keeping this at all: a model that flags a
                 vendor as EFOS-shaped BEFORE the SAT publishes it is a real
                 pain point ("por el tiempo que tarda en salir en definitivo,
                 la empresa ya dedujo") — worth reporting as a secondary
                 signal in the pitch, never as the scheme detector itself.

Scope note: features are computed per ENTITY (RFC), over the UNION of
vendor RFCs and client RFCs (invoice receiver_rfc where the issuer is the
audited company) — not vendor RFCs alone. Earlier this script only iterated
`vendors`, which made it structurally impossible for `revenue_inflation` to
ever appear as a label: that scheme's accused entity is a CLIENT
(receiver_rfc), and the generator does not currently make vendor RFCs and
client RFCs overlap, but nothing about the real world (or a judge's own
estate) guarantees that they never do — an entity can buy from and sell to
the same company. So every entity gets BOTH a purchase-side feature group
(populated if it appears in `vendors`) and a sales-side feature group
(populated if it appears as an invoice `receiver_rfc` from the company);
whichever side doesn't apply is filled with neutral defaults (0 counts,
NaN for the age feature), the same way a vendor that has no PO history
already gets 0 orden_compra features today. `categoria` is "cliente" for
an entity with no vendor row at all.

kickback's employee side (EMP:xxxx) is a second entity on that scheme that
is neither a vendor nor a client RFC — it does not get a feature row here.
That is a known, separate limitation (employee-level features are future
work); it does not block the vendor-RFC side of that same scheme from being
labeled and trained on.

The audited company's own RFC is inferred the same way
src/tools/estate_access.py's identificar_empresa() does at runtime (the
receiver_rfc that appears most often across all invoices) — not read from
gt_NNNN.json — so the features trained on here match exactly what
src/scoring/features.py can compute during a live run with no ground truth
available.

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
    # entity -> scheme_type, for the primary multiclass label. First match
    # wins for an entangled entity (see module docstring) — we log if that
    # ever actually happens on this dataset, in main().
    entity_to_scheme_type: dict[str, str] = {}
    entangled_entities: set[str] = set()
    for scheme in gt["schemes"]:
        for entity in scheme["entities"]:
            if entity in entity_to_scheme_type and entity_to_scheme_type[entity] != scheme["type"]:
                entangled_entities.add(entity)
            else:
                entity_to_scheme_type.setdefault(entity, scheme["type"])
    if entangled_entities:
        print(f"  AVISO {db_path.name}: entidad(es) entangled entre esquemas, tomando el primer match: "
              f"{sorted(entangled_entities)}")

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

    # Company RFC, inferred the same way identificar_empresa() does at
    # runtime: the receiver_rfc that appears most often across all invoices
    # (its own vendors' invoices dominate the count). Never read from gt.
    company_rfc = (
        invoices["receiver_rfc"].value_counts().idxmax() if not invoices.empty else ""
    )
    company_clabe = (
        bank_txns["from_clabe"].value_counts().idxmax() if not bank_txns.empty else ""
    )

    vendor_by_rfc = vendors.set_index("rfc").to_dict(orient="index")
    vendor_rfcs = set(vendor_by_rfc.keys())
    client_rfcs = set(invoices.loc[invoices["issuer_rfc"] == company_rfc, "receiver_rfc"].unique())
    client_rfcs.discard(company_rfc)
    all_entity_rfcs = sorted(vendor_rfcs | client_rfcs)

    fecha_max_ingreso = None
    ingresos_all = invoices[invoices["issuer_rfc"] == company_rfc]
    if not ingresos_all.empty:
        fecha_max_ingreso = max(date.fromisoformat(d) for d in ingresos_all["issue_date"])

    rows = []
    for rfc in all_entity_rfcs:
        v = vendor_by_rfc.get(rfc)
        es_proveedor = v is not None
        es_cliente = rfc in client_rfcs

        # ---- purchase-side (vendor) features — defaults if not a vendor. ----
        v_inv = invoices[invoices["issuer_rfc"] == rfc] if es_proveedor else invoices.iloc[0:0]
        v_po = pos[pos["vendor_rfc"] == rfc] if es_proveedor else pos.iloc[0:0]
        v_ctr = contracts[contracts["vendor_rfc"] == rfc] if es_proveedor else contracts.iloc[0:0]
        v_ledger = ledger[ledger["invoice_uuid"].isin(v_inv["uuid"])]
        # Bank transfers paid by the company TO this vendor's own CLABE.
        v_txn = (
            bank_txns[bank_txns["to_clabe"] == v["bank_clabe"]] if es_proveedor else bank_txns.iloc[0:0]
        )

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
        # Only 'definitivo'/'presunto'/'no_listado' can occur — efos_list
        # never contains 'desvirtuado'/'favorable' (see module docstring).
        situacion_sat = efos_row.get("status") if efos_row else "no_listado"

        scheme_type = entity_to_scheme_type.get(f"RFC:{rfc}", "no_esquema")

        dias_antiguedad = float("nan")
        if es_proveedor and n_inv:
            primera_factura = v_inv["issue_date"].min()
            dias_antiguedad = _days_between(v["registered_date"], primera_factura)

        pct_concepto_generico = (
            float(v_inv["concepto_text"].str.lower().str.contains("|".join(GENERIC_CONCEPT_WORDS)).mean())
            if n_inv else 0.0
        )

        if es_proveedor:
            institucion = _clabe_institution(v["bank_clabe"])
            clabe_identica_a_empleado = int(v["bank_clabe"] in employee_clabes)
            misma_institucion_que_empleado = int(institucion in employee_institutions)
        else:
            clabe_identica_a_empleado = 0
            misma_institucion_que_empleado = 0

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

        # ---- sales-side (client) features — 0/NaN if not a client. ----
        # Revenue invoices the company issued TO this entity.
        c_inv = invoices[
            (invoices["issuer_rfc"] == company_rfc) & (invoices["receiver_rfc"] == rfc)
        ] if es_cliente else invoices.iloc[0:0]
        # Incoming transfers to the company's own account (matched by amount
        # only, same tolerance as the vendor side — not by CLABE naming
        # convention, so this stays robust to how a client's CLABE is
        # represented).
        entrantes = bank_txns[bank_txns["to_clabe"] == company_clabe] if company_clabe else bank_txns.iloc[0:0]

        n_inv_venta = len(c_inv)
        monto_total_venta = float(c_inv["total"].sum()) if n_inv_venta else 0.0
        monto_prom_venta = float(c_inv["total"].mean()) if n_inv_venta else 0.0

        n_cobradas = 0
        for _, inv in c_inv.iterrows():
            match = entrantes[entrantes["amount"].sub(inv["total"]).abs() <= 0.01 * max(inv["total"], 1)]
            if not match.empty:
                n_cobradas += 1
        pct_venta_sin_cobro = float(1 - n_cobradas / n_inv_venta) if n_inv_venta else 0.0

        dias_a_cierre_periodo_venta = float("nan")
        if n_inv_venta and fecha_max_ingreso is not None:
            ultima_venta = max(date.fromisoformat(d) for d in c_inv["issue_date"])
            dias_a_cierre_periodo_venta = (fecha_max_ingreso - ultima_venta).days

        categoria = v["category"] if es_proveedor else "cliente"

        rows.append({
            "estate_seed": seed,
            "rfc": rfc,
            "es_proveedor": int(es_proveedor),
            "es_cliente": int(es_cliente),
            "categoria": categoria,
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
            "num_facturas_venta": n_inv_venta,
            "monto_total_venta": round(monto_total_venta, 2),
            "monto_promedio_venta": round(monto_prom_venta, 2),
            "pct_facturas_venta_sin_cobro": round(pct_venta_sin_cobro, 4),
            "dias_a_cierre_periodo_venta": dias_a_cierre_periodo_venta,
            "scheme_type": scheme_type,
            "es_fraude": int(scheme_type != "no_esquema"),
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
    print("distribucion scheme_type (target primario):")
    print(df["scheme_type"].value_counts().to_string())
    print("distribucion situacion_sat (senal secundaria):")
    print(df["situacion_sat"].value_counts().to_string())
    invalid_sat = set(df["situacion_sat"].unique()) - {"definitivo", "presunto", "no_listado"}
    if invalid_sat:
        print(f"  ERROR: situacion_sat con valores fuera del schema oficial: {invalid_sat}")
    print(f"escrito: {args.out}")


if __name__ == "__main__":
    main()
