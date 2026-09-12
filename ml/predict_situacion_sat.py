#!/usr/bin/env python3
"""
ml/predict_situacion_sat.py — HACKMTY2026 Forensic Auditor track.

Loads modelo_cart_multiclase.pkl (produced by train_multiclase_sat.py) and
scores a SINGLE vendor's feature dict, handling the two things that break
naive inference on one row at a time:

  1. One-hot encoding of `categoria`: pd.get_dummies on a single row only
     ever produces the one column for that row's own category. This
     reconstructs the full column set the model was trained on (using
     `categoria_values` saved in the bundle) and zero-fills the rest.
  2. Missing `dias_antiguedad_al_facturar` (a vendor with zero invoices has
     no first-invoice date to compute it from): filled with the training
     median saved in the bundle, exactly like at training time.

This file lives in ml/ (outside src/), same as the rest of the training
flow — it is the "how to use this artifact" counterpart to the .pkl, not
part of the investigator agent itself. If a live detector needs this at
inference time, wrap `predict_one` in a typed function under src/tools/
(the same access-layer pattern as everything else the agent is allowed to
call) rather than importing this module directly from src/.

Usage as a library:
    from ml.predict_situacion_sat import load_bundle, predict_one
    bundle = load_bundle("ml/artifacts_multiclase/modelo_cart_multiclase.pkl")
    label, proba = predict_one(bundle, vendor_features_dict)

Usage from the CLI (scores every row of a features CSV, for a sanity check):
    python3 ml/predict_situacion_sat.py --features ml/features_train.csv --n 5
"""

from __future__ import annotations

import argparse
import pickle
from pathlib import Path
from typing import Any

import pandas as pd

HERE = Path(__file__).resolve().parent
DEFAULT_MODEL_PATH = HERE / "artifacts_multiclase" / "modelo_cart_multiclase.pkl"


def load_bundle(model_path: Path | str = DEFAULT_MODEL_PATH) -> dict:
    with open(model_path, "rb") as f:
        return pickle.load(f)


def _vector_for_row(bundle: dict, row: dict[str, Any]) -> pd.DataFrame:
    """Builds a one-row DataFrame with exactly the columns/order the model
    was trained on (bundle['feature_names']), reconstructing the categoria
    one-hot columns and filling missing dias_antiguedad_al_facturar."""
    row = dict(row)  # don't mutate the caller's dict

    dias = row.get("dias_antiguedad_al_facturar")
    if dias is None or (isinstance(dias, float) and pd.isna(dias)):
        row["dias_antiguedad_al_facturar"] = bundle["dias_antiguedad_median"]

    categoria = row.pop("categoria", None)
    for cat_value in bundle["categoria_values"]:
        row[f"cat_{cat_value}"] = 1 if categoria == cat_value else 0

    # Any leaky/id/label columns the caller passed by accident are ignored;
    # any expected feature column the caller didn't pass defaults to 0.
    vector = {col: row.get(col, 0) for col in bundle["feature_names"]}
    return pd.DataFrame([vector], columns=bundle["feature_names"])


def predict_one(bundle: dict, vendor_features: dict[str, Any]) -> tuple[str, dict[str, float]]:
    """Returns (predicted_label, {class_name: probability, ...})."""
    X = _vector_for_row(bundle, vendor_features)
    model = bundle["model"]
    proba = model.predict_proba(X)[0]
    proba_by_class = {cls: round(float(p), 4) for cls, p in zip(model.classes_, proba)}
    label = model.classes_[proba.argmax()]
    return label, proba_by_class


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", type=Path, default=DEFAULT_MODEL_PATH)
    ap.add_argument("--features", type=Path, default=HERE / "features_train.csv")
    ap.add_argument("--n", type=int, default=5, help="How many sample rows to score, as a sanity check.")
    args = ap.parse_args()

    bundle = load_bundle(args.model)
    df = pd.read_csv(args.features)
    print(f"modelo cargado: {args.model}  (clases: {bundle['classes']})")
    sample = df.sample(min(args.n, len(df)), random_state=0)
    hits = 0
    for _, row in sample.iterrows():
        vendor_features = row.drop(labels=["estate_seed", "situacion_sat", "es_fraude"], errors="ignore").to_dict()
        label, proba = predict_one(bundle, vendor_features)
        real = row.get("situacion_sat", "?")
        ok = "OK" if label == real else "  "
        hits += int(label == real)
        print(f"[{ok}] rfc={row.get('rfc','?')}  real={real:12s}  predicho={label:12s}  proba={proba}")
    print(f"\n{hits}/{len(sample)} coincidencias en esta muestra (no es el accuracy de test, solo un sanity check)")


if __name__ == "__main__":
    main()
