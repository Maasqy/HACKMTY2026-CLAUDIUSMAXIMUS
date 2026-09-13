"""
src/scoring/

Combines src.detectors' deterministic Signals with two exported ML models
(model/modelo_cart_scheme_type.pkl — PRIMARY, trained by
ml/train_scheme_type.py — and model/modelo_cart_situacion_sat.pkl —
SECONDARY, trained by ml/train_multiclase_sat.py) into ranked Lead objects
— see leads.py. features.py recomputes both models' input features using
only src.tools.EstateDB (never raw SQL/pandas over the .db file, since this
runs as part of the agent under investigation).

Nothing here imports eval/ or references the evaluation answer key.
"""

from .leads import Lead, generar_leads
from .model import predict_scheme_type, predict_situacion

__all__ = ["Lead", "generar_leads", "predict_scheme_type", "predict_situacion"]
