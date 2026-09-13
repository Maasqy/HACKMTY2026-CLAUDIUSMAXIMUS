"""
src/scoring/model.py

Self-contained loaders for the two pruned CARTs trained offline (ml/), one
PRIMARY and one SECONDARY signal for src/scoring/leads.py:

  predict_scheme_type()  PRIMARY — modelo_cart_scheme_type.pkl, trained by
                          ml/train_scheme_type.py on the actual judged task:
                          which of the five official scheme_type values (or
                          'no_esquema') this entity looks like. On our own
                          held-out estates (seeds tuned on, never the sealed
                          901-905 report set) this hits 100% — expected, and
                          NOT proof of real-world accuracy: our schemes are
                          template-generated, so this measures template
                          recognition on our own generator, not
                          generalization to a judge's independently-built
                          estate. That is exactly what the sealed holdout
                          set exists to check, once, at the very end.

  predict_situacion()     SECONDARY — modelo_cart_situacion_sat.pkl, trained
                          by ml/train_multiclase_sat.py on situacion_sat
                          (the vendor's real SAT 69-B status: definitivo /
                          presunto / no_listado). Not the judged task. Used
                          in leads.py only for a small, fixed bonus on a
                          'definitivo' prediction — see ML_DEFINITIVO_BONUS
                          there — never as the primary ranking signal.

This lives in src/ but does NOT import anything from ml/ — the offline
training package is a build-time dependency, not a runtime one. Only the
exported artifacts (model/modelo_cart_scheme_type.pkl,
model/modelo_cart_situacion_sat.pkl, both copied here) are needed at
submission runtime. The row-reconstruction logic in _vector_for_row is
intentionally duplicated from the ml/ predict helpers rather than imported,
so src/ stays self-contained and replayable without ml/ present.

IMPORTANT — NEITHER model's output is a verdict. A Lead's score (see
leads.py) is a ranking hint for the investigator to look into, never
grounds for an accusation on its own: "Un score de 0.94 no prueba nada ante
un auditor." An accusation only becomes a Finding after the investigator
corroborates it with real exhibits and a deterministic validator checks it
(record_id exists, peso_amount reconciles) — that check, not this model,
is what a Finding stands on.
"""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_SCHEME_TYPE_MODEL_PATH = HERE / "model" / "modelo_cart_scheme_type.pkl"
DEFAULT_SITUACION_SAT_MODEL_PATH = HERE / "model" / "modelo_cart_situacion_sat.pkl"

_bundle_cache: dict[str, dict] = {}


def _load_bundle(model_path: Path) -> dict:
    key = str(model_path)
    if key not in _bundle_cache:
        with open(model_path, "rb") as f:
            _bundle_cache[key] = pickle.load(f)
    return _bundle_cache[key]


def _vector_for_row(bundle: dict, row: dict) -> "pd.DataFrame":  # noqa: F821 - pandas imported lazily below
    import pandas as pd

    row = dict(row)  # don't mutate the caller's dict

    dias = row.get("dias_antiguedad_al_facturar")
    if dias is None or (isinstance(dias, float) and dias != dias):  # NaN check without a second import
        row["dias_antiguedad_al_facturar"] = bundle["dias_antiguedad_median"]

    if "dias_a_cierre_periodo_venta_median" in bundle:
        dias_venta = row.get("dias_a_cierre_periodo_venta")
        if dias_venta is None or (isinstance(dias_venta, float) and dias_venta != dias_venta):
            row["dias_a_cierre_periodo_venta"] = bundle["dias_a_cierre_periodo_venta_median"]

    categoria = row.pop("categoria", None)
    for cat_value in bundle["categoria_values"]:
        row[f"cat_{cat_value}"] = 1 if categoria == cat_value else 0

    vector = {col: row.get(col, 0) for col in bundle["feature_names"]}
    return pd.DataFrame([vector], columns=bundle["feature_names"])


def _predict(vendor_features: dict, model_path: Path) -> tuple[str, dict[str, float]]:
    bundle = _load_bundle(model_path)
    X = _vector_for_row(bundle, vendor_features)
    model = bundle["model"]
    proba = model.predict_proba(X)[0]
    proba_by_class = {cls: round(float(p), 4) for cls, p in zip(model.classes_, proba)}
    label = model.classes_[proba.argmax()]
    return label, proba_by_class


def predict_scheme_type(
    entity_features: dict, model_path: Path = DEFAULT_SCHEME_TYPE_MODEL_PATH
) -> tuple[str, dict[str, float]]:
    """PRIMARY signal. Devuelve (etiqueta_predicha, {clase: probabilidad, ...})
    para una entidad, a partir de su dict de features
    (src.scoring.features.construir_features_entidad). Etiqueta es una de
    las cinco scheme_type oficiales o 'no_esquema'."""
    return _predict(entity_features, model_path)


def predict_situacion(
    vendor_features: dict, model_path: Path = DEFAULT_SITUACION_SAT_MODEL_PATH
) -> tuple[str, dict[str, float]]:
    """SECONDARY signal. Devuelve (etiqueta_predicha, {clase: probabilidad, ...})
    para un proveedor, a partir de su dict de features. Etiqueta es
    'definitivo' | 'presunto' | 'no_listado'."""
    return _predict(vendor_features, model_path)
