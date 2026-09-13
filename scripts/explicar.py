#!/usr/bin/env python3
"""
scripts/explicar.py — abre la caja negra del pipeline determinista.

Muestra, para una estate o para una entidad concreta, exactamente por que
quedo donde quedo: que reglas dispararon, con que evidencia, que predijo el
CART, y como se compuso el score. Es la herramienta para verificar el flujo
y para probar datos nuevos sin correr el LLM.

    # ranking completo de una estate
    python3 scripts/explicar.py --estate data/estates/estate_0001.db

    # una entidad, con el detalle de sus 41 features
    python3 scripts/explicar.py --estate data/estates/estate_0001.db --entidad RFC:XAXX010101000

    # solo el modelo, sobre features escritas a mano (para probar hipotesis)
    python3 scripts/explicar.py --features '{"num_facturas": 8, "en_lista_69b": 1, "es_69b_definitivo": 1, "pct_concepto_generico": 0.9, "categoria": "Consultoria"}'

Nota sobre el ultimo modo: el modelo predice sobre ENTIDADES, no sobre
transacciones. Sus features son agregados (cuantas facturas, que porcentaje
sin orden de compra, si aparece en el 69-B...). Pasarle "una transaccion"
no tiene sentido; lo que se le pasa es el perfil acumulado de un proveedor
o un cliente. Las features que no menciones se rellenan con 0, o con la
mediana del entrenamiento en el caso de las dos de antiguedad.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.detectors import rules  # noqa: E402
from src.scoring import generar_leads, predict_scheme_type, predict_situacion  # noqa: E402
from src.scoring.features import construir_features_entidad  # noqa: E402
from src.scoring.leads import ML_DEFINITIVO_BONUS, ML_SCHEME_BONUS  # noqa: E402
from src.tools import EstateDB  # noqa: E402


def explicar_entidad(estate, entidad: str) -> None:
    rfc = entidad.split(":", 1)[1] if ":" in entidad else entidad
    company = estate.identificar_empresa()

    print(f"\n{'=' * 68}\n  {entidad}\n{'=' * 68}")

    feats = construir_features_entidad(estate, rfc, company=company)
    rol = []
    if feats["es_proveedor"]:
        rol.append("proveedor")
    if feats["es_cliente"]:
        rol.append("cliente")
    print(f"  rol: {' + '.join(rol) or 'NO aparece en esta estate'}")

    print("\n  --- FEATURES (lo que ve el modelo) ---")
    for k, v in feats.items():
        if isinstance(v, float) and v != v:
            v = "NaN (se rellena con la mediana del entrenamiento)"
        elif isinstance(v, float):
            v = f"{v:,.4f}".rstrip("0").rstrip(".")
        if v not in (0, "0", 0.0):
            print(f"    {k:42s} {v}")
    print("    (las features en cero se omiten)")

    print("\n  --- ETAPA 2a: REGLAS DETERMINISTAS ---")
    disparadas = []
    for fn in (rules.detectar_69b, rules.detectar_texto_generico, rules.detectar_sin_respaldo,
               rules.detectar_fraccionamiento, rules.detectar_mismo_solicitante_aprobador,
               rules.detectar_pago_no_rastreable):
        sig = fn(estate, rfc)
        if sig:
            disparadas.append(sig)
    for grupo in (rules.detectar_ciclo_transferencias(estate, company),
                  rules.detectar_kickback(estate, company),
                  rules.detectar_ingreso_fin_periodo_sin_cobro(estate, company)):
        disparadas.extend(s for s in grupo if s.entity == entidad)

    if not disparadas:
        print("    ninguna regla disparo")
    for s in disparadas:
        print(f"    [{s.detector}]  fuerza {s.strength}  -> {s.scheme_hint or 'transversal'}")
        print(f"      {s.description}")
        for ex in s.evidence[:3]:
            print(f"        evidencia: {ex.source_table}/{ex.record_id}")

    print("\n  --- ETAPA 2b: MODELO (CART) ---")
    lab, proba = predict_scheme_type(feats)
    print(f"    scheme_type predicho: {lab}")
    for c, p in sorted(proba.items(), key=lambda kv: -kv[1]):
        if p > 0:
            print(f"      {c:22s} {p:6.1%}")
    if feats["es_proveedor"]:
        lab2, proba2 = predict_situacion(feats)
        print(f"    situacion_sat (secundario): {lab2}")

    print("\n  --- COMPOSICION DEL SCORE (noisy-OR) ---")
    duda = 1.0
    for s in disparadas:
        duda *= (1 - s.strength)
        print(f"    {s.detector:42s} x(1-{s.strength}) -> duda={duda:.4f}")
    bs = ML_SCHEME_BONUS if lab not in (None, "no_esquema") else 0.0
    bd = ML_DEFINITIVO_BONUS if (feats["es_proveedor"] and predict_situacion(feats)[0] == "definitivo") else 0.0
    if bs:
        duda *= (1 - bs)
        print(f"    {'modelo predice ' + lab:42s} x(1-{bs}) -> duda={duda:.4f}")
    if bd:
        duda *= (1 - bd)
        print(f"    {'situacion_sat = definitivo':42s} x(1-{bd}) -> duda={duda:.4f}")
    print(f"    SCORE = 1 - {duda:.6f} = {1 - duda:.6f}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--estate", type=Path)
    ap.add_argument("--entidad", help="RFC:XXX o EMP:0001")
    ap.add_argument("--features", help="JSON con features, para probar el modelo solo")
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()

    if args.features:
        feats = json.loads(args.features)
        lab, proba = predict_scheme_type(feats)
        print(f"\nfeatures dadas: {list(feats)}")
        print(f"(las demas se rellenan con 0 o con la mediana del entrenamiento)\n")
        print(f"scheme_type predicho: {lab}\n")
        for c, p in sorted(proba.items(), key=lambda kv: -kv[1]):
            barra = "#" * int(p * 40)
            print(f"  {c:22s} {p:6.1%}  {barra}")
        print("\nRecordatorio: esto es una hipotesis para rankear, no una acusacion.")
        return 0

    if not args.estate:
        ap.error("hace falta --estate o --features")

    with EstateDB(args.estate) as estate:
        if args.entidad:
            explicar_entidad(estate, args.entidad)
            return 0

        leads = generar_leads(estate)
        print(f"\n{len(leads)} leads en {args.estate.name}, de mayor a menor sospecha:\n")
        print(f"  {'#':>3} {'entidad':24s} {'score':>9s}  {'modelo':20s} senales")
        print("  " + "-" * 92)
        for i, l in enumerate(leads[:args.top], 1):
            dets = ", ".join(sorted({s.detector.replace("detectar_", "") for s in l.signals}))
            print(f"  {i:>3} {l.entity:24s} {l.score:9.6f}  {str(l.ml_scheme_type):20s} {dets[:44]}")
        if len(leads) > args.top:
            print(f"  ... y {len(leads) - args.top} mas (usa --top)")
        print(f"\nDetalle de una: python3 scripts/explicar.py --estate {args.estate} "
              f"--entidad {leads[0].entity}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
