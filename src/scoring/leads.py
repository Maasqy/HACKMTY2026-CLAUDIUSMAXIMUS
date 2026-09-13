"""
src/scoring/leads.py

Combines deterministic Signals (src.detectors) with two ML models
(src.scoring.model, trained OUTSIDE src/ in ml/train_scheme_type.py and
ml/train_multiclase_sat.py) into one ranked Lead per entity. This is the
last stop before the investigator (LLM, not built yet) takes over: a Lead
is "here is what deterministic rules and trained classifiers noticed",
handed to the LLM to investigate with src.tools, corroborate with exhibits,
and turn into either a Finding or a leads_not_pursued entry.

NON-NEGOTIABLE: a Lead is never itself an accusation and never becomes a
Finding by being emitted here. "Un score de 0.94 no prueba nada ante un
auditor" — the accusation is built by the investigator (who must cite real
exhibits) and only stands once a deterministic validator checks it
(record_id exists, peso_amount reconciles within 2%). This module has no
access to, and makes no claim about, the ground truth — everything in a
Lead is either an observed Signal or a model's own probability estimate.

Score composition is intentionally simple and auditable — no black-box
combination of a raw ML probability into the ranking:

    score = 1 - PRODUCTO(1 - strength_i) * (1 - ML_SCHEME_BONUS) * (1 - ML_DEFINITIVO_BONUS)

donde el producto corre sobre cada Signal de la entidad, y cada factor ML
entra solo si aplica:
          ML_SCHEME_BONUS         (only if the PRIMARY model's top class is
            NOT 'no_esquema' — every model class contributes the same fixed
            bonus regardless of its raw probability, since on our own
            estates this model is close to deterministic and a raw
            probability would carry no real gradient — see
            src.scoring.model's module docstring on why 100% held-out
            accuracy here is not proof of real-world accuracy)
          + ML_DEFINITIVO_BONUS   (only if the SECONDARY model's top class
            is 'definitivo'; every other situacion_sat class contributes 0)

Why a noisy-OR ("1 menos el producto de los complementos") and not the mean
of the strengths it used to be: the mean does not reward ACCUMULATION. An
honest vendor with a single 0.6 signal tied a vendor carrying three 0.6
signals, which is backwards — an auditor gets more suspicious as
independent red flags stack up on the same entity, not equally suspicious.
That flaw was invisible while each detector's signal was effectively
exclusive to one scheme (a single signal WAS proof), and became the
deciding factor once the generator was fixed so that honest entities also
trip individual detectors (vague concepto text, uncollected receivables at
period close, a self-approved purchase order). Reading the formula: each
independent signal of strength s leaves (1 - s) of the doubt standing, so
three mediocre signals (0.5, 0.5, 0.4) reach 0.85 while one strong-looking
signal alone (0.6) stays at 0.60. No probability is claimed — it is a
ranking, and the arithmetic is one line a judge can check by hand.

An entity can get a Lead purely from a model catching something no
detector's rule fired on (det_score=0, ml_bonus>0) — the point of running
the primary model over every vendor AND client, not only over entities a
detector already flagged, is to not silently drop whatever the model
generalizes to that our own deterministic rules didn't anticipate. An
entity with a truly clean signal (no Signal fired, model says
'no_esquema'/'no_listado') never becomes a Lead at all — this list is meant
to be worked, not a printout of the entire estate.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.detectors import rules
from src.detectors.signals import Signal
from src.scoring.features import construir_features_entidad
from src.scoring.model import predict_scheme_type, predict_situacion

ML_SCHEME_BONUS = 0.35
ML_DEFINITIVO_BONUS = 0.15


@dataclass(frozen=True, slots=True)
class Lead:
    """Un Lead NO es una acusacion — es una entidad que vale la pena que el
    investigator revise, con la evidencia (Signals) y las senales de los
    modelos ML que la hicieron subir en la lista. Nunca se escribe
    directamente a un case file: el investigator debe corroborarla con
    exhibits reales de src.tools y un validador deterministico debe
    aprobarla antes de que se convierta en un Finding."""
    entity: str
    score: float
    signals: tuple[Signal, ...]
    scheme_hints: tuple[str, ...]
    ml_scheme_type: str | None
    ml_scheme_proba: dict | None
    ml_situacion_sat: str | None
    ml_proba: dict | None


def generar_leads(estate) -> list["Lead"]:
    """Corre todos los detectores deterministas sobre cada proveedor de la
    estate, agrega sus Signals por entidad, corre el modelo PRIMARIO
    (scheme_type) sobre cada entidad — proveedor o cliente — y el modelo
    SECUNDARIO (situacion_sat) sobre cada proveedor, y devuelve una lista de
    Lead ordenada por score descendente. No emite ninguna acusacion — eso es
    trabajo del investigator."""
    company = estate.identificar_empresa()
    vendors = estate.buscar_proveedores()
    vendor_rfcs = {v.rfc for v in vendors}

    ingresos_empresa = estate.obtener_facturas(rfc_emisor=company.rfc) if company.rfc else []
    client_rfcs = {f.receiver_rfc for f in ingresos_empresa} - {company.rfc}

    signals_by_entity: dict[str, list[Signal]] = {}

    def add(sig: Signal | None):
        if sig is not None:
            signals_by_entity.setdefault(sig.entity, []).append(sig)

    for v in vendors:
        add(rules.detectar_69b(estate, v.rfc))
        add(rules.detectar_texto_generico(estate, v.rfc))
        add(rules.detectar_sin_respaldo(estate, v.rfc))
        add(rules.detectar_fraccionamiento(estate, v.rfc))
        add(rules.detectar_mismo_solicitante_aprobador(estate, v.rfc))
        add(rules.detectar_pago_no_rastreable(estate, v.rfc))

    for sig in rules.detectar_ciclo_transferencias(estate, company):
        add(sig)
    for sig in rules.detectar_kickback(estate, company):
        add(sig)
    for sig in rules.detectar_ingreso_fin_periodo_sin_cobro(estate, company):
        add(sig)

    # Union of every entity worth scoring: anything a detector flagged
    # (vendor RFCs, client RFCs, or an EMP:xxxx from kickback), PLUS every
    # vendor/client RFC so the primary model gets a chance to catch what no
    # detector's rule fired on.
    all_rfcs = (vendor_rfcs | client_rfcs) - {company.rfc}
    all_entities = set(signals_by_entity.keys()) | {f"RFC:{rfc}" for rfc in all_rfcs}

    leads: list[Lead] = []
    for entity in all_entities:
        sigs = signals_by_entity.get(entity, [])

        ml_scheme_label, ml_scheme_proba = None, None
        ml_sat_label, ml_sat_proba = None, None
        if entity.startswith("RFC:"):
            rfc = entity.split(":", 1)[1]
            if rfc in all_rfcs:
                features = construir_features_entidad(estate, rfc, company=company)
                ml_scheme_label, ml_scheme_proba = predict_scheme_type(features)
                if rfc in vendor_rfcs:
                    ml_sat_label, ml_sat_proba = predict_situacion(features)

        ml_scheme_bonus = ML_SCHEME_BONUS if ml_scheme_label not in (None, "no_esquema") else 0.0
        ml_sat_bonus = ML_DEFINITIVO_BONUS if ml_sat_label == "definitivo" else 0.0

        # noisy-OR over EVERYTHING: each deterministic Signal and each model
        # flag independently eats a share of the remaining doubt. The two ML
        # contributions go inside the same product rather than being added
        # on top, because an additive bonus plus a min(...,1.0) cap pinned
        # half the top of the list to exactly 1.0 — and a ranking whose top
        # entries are all tied is not a ranking. Multiplying keeps the score
        # inside [0,1) by construction, with no cap and no ties.
        duda = 1.0
        for s in sigs:
            duda *= (1.0 - s.strength)
        det_score = round(1.0 - duda, 6)
        duda *= (1.0 - ml_scheme_bonus) * (1.0 - ml_sat_bonus)
        # 6 decimals, not 4: with five stacked signals the residual doubt is
        # ~6e-5, so rounding to 4 displayed several distinct entities as a
        # tied 1.0000 and destroyed the ordering at the very top of the list.
        score = round(1.0 - duda, 6)

        # Skip entities with nothing at all to report: no Signal fired, and
        # neither model flagged anything.
        if not sigs and ml_scheme_bonus == 0.0 and ml_sat_bonus == 0.0:
            continue

        scheme_hints = tuple(sorted(
            {s.scheme_hint for s in sigs if s.scheme_hint}
            | ({ml_scheme_label} if ml_scheme_label not in (None, "no_esquema") else set())
        ))

        leads.append(Lead(
            entity=entity,
            score=score,
            signals=tuple(sigs),
            scheme_hints=scheme_hints,
            ml_scheme_type=ml_scheme_label,
            ml_scheme_proba=ml_scheme_proba,
            ml_situacion_sat=ml_sat_label,
            ml_proba=ml_sat_proba,
        ))

    leads.sort(key=lambda l: l.score, reverse=True)
    return leads
