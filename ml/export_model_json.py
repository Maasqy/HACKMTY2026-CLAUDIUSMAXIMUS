#!/usr/bin/env python3
"""
ml/export_model_json.py

Convierte un CART entrenado (.pkl de sklearn) a JSON plano, para que
src/scoring/ pueda predecir SIN sklearn.

Por que existe. Un pickle de sklearn solo carga de forma confiable con la
misma version de sklearn con la que se creo; entre versiones distintas
puede fallar o —peor— cargar y predecir distinto en silencio. Eso hacia que
la corrida dependiera de que cada maquina del equipo y la de los jueces
tuvieran exactamente la misma version, que es una condicion que no se
sostiene.

Un arbol de decision no necesita sklearn para evaluarse: es una estructura
de nodos con una feature, un umbral y dos hijos. Se exporta esa estructura
tal cual y se evalua con un bucle de diez lineas (src/scoring/model.py).
Resultado: el runtime del agente no depende de sklearn, ni de pandas, ni de
numpy — solo de la libreria estandar. sklearn sigue haciendo falta para
ENTRENAR (ml/), que es otra cosa.

Uso:
    python3 ml/export_model_json.py            # exporta los dos modelos
"""

from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

MODELOS = [
    (HERE / "artifacts_scheme_type" / "modelo_cart_scheme_type.pkl",
     REPO / "src" / "scoring" / "model" / "modelo_cart_scheme_type.json"),
    (HERE / "artifacts_situacion_sat" / "modelo_cart_situacion_sat.pkl",
     REPO / "src" / "scoring" / "model" / "modelo_cart_situacion_sat.json"),
]


def exportar(pkl_path: Path, json_path: Path) -> dict:
    with open(pkl_path, "rb") as f:
        bundle = pickle.load(f)

    modelo = bundle["model"]
    t = modelo.tree_

    # `value` trae, por nodo, la distribucion de clases. Segun la version de
    # sklearn viene como conteos (ponderados por class_weight) o ya
    # normalizada a fracciones; se normaliza aqui para que el predictor no
    # tenga que saber cual de las dos recibio.
    valores = []
    for fila in t.value.tolist():
        dist = fila[0]
        total = sum(dist)
        valores.append([v / total for v in dist] if total > 0
                       else [1.0 / len(dist)] * len(dist))

    datos = {
        "_formato": "cart-json-v1",
        "_nota": "Arbol exportado desde sklearn para evaluarse sin sklearn. "
                 "Ver ml/export_model_json.py.",
        "target_col": bundle.get("target_col"),
        "classes": [str(c) for c in modelo.classes_],
        "feature_names": list(bundle["feature_names"]),
        "categorical_cols": bundle.get("categorical_cols", []),
        "categoria_values": bundle.get("categoria_values", []),
        "dias_antiguedad_median": bundle.get("dias_antiguedad_median"),
        "dias_a_cierre_periodo_venta_median": bundle.get("dias_a_cierre_periodo_venta_median"),
        "entrenado_con_sklearn": bundle.get("sklearn_version"),
        "arbol": {
            "children_left": t.children_left.tolist(),
            "children_right": t.children_right.tolist(),
            "feature": t.feature.tolist(),
            "threshold": t.threshold.tolist(),
            "value": valores,
        },
    }

    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    return datos


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verificar", action="store_true",
                    help="compara las predicciones JSON contra sklearn sobre "
                         "todo features_train.csv y falla si difieren")
    args = ap.parse_args()

    for pkl, js in MODELOS:
        if not pkl.exists():
            print(f"  saltando {pkl.name}: no existe (reentrena primero)")
            continue
        d = exportar(pkl, js)
        print(f"  {pkl.name} -> {js.relative_to(REPO)}  "
              f"({len(d['arbol']['feature'])} nodos, {len(d['classes'])} clases)")

    if args.verificar:
        return _verificar()
    return 0


def _verificar() -> int:
    """Predice cada fila del set de entrenamiento con sklearn y con el
    predictor JSON, y exige que coincidan. Es la unica prueba que demuestra
    que la conversion no cambio el modelo."""
    import sys
    sys.path.insert(0, str(REPO))
    import pandas as pd
    from src.scoring.model import _cargar_json, _predecir_json

    sys.path.insert(0, str(HERE))
    from train_scheme_type import load_xy

    df, feature_cols, _ = load_xy(HERE / "features_train.csv")
    pkl_bundle = pickle.load(open(MODELOS[0][0], "rb"))
    modelo = pkl_bundle["model"]
    X = df[feature_cols]

    proba_sk = modelo.predict_proba(X)
    arbol = _cargar_json(MODELOS[0][1])

    # La tolerancia es 1e-6 porque _predecir_json redondea la probabilidad a
    # 6 decimales (suficiente de sobra para rankear leads). Compararla contra
    # 1e-9 hacia que la prueba fallara contra su propio redondeo y reportara
    # 1824 "diferencias" que no existian.
    TOLERANCIA = 1e-6
    etiquetas_sk = modelo.predict(X)
    dif_proba = dif_etiqueta = 0
    peor = 0.0
    for i in range(len(X)):
        fila = {c: X.iloc[i][c] for c in feature_cols}
        etiqueta_js, proba_js = _predecir_json(arbol, fila, ya_vectorizado=True)
        if etiqueta_js != str(etiquetas_sk[i]):
            dif_etiqueta += 1
        for k, cls in enumerate(modelo.classes_):
            d = abs(proba_js.get(str(cls), 0.0) - proba_sk[i][k])
            peor = max(peor, d)
            if d > TOLERANCIA:
                dif_proba += 1
                break

    print(f"\nverificacion contra sklearn sobre {len(X):,} filas:")
    print(f"  etiquetas distintas          : {dif_etiqueta}")
    print(f"  probabilidades fuera de {TOLERANCIA:.0e}: {dif_proba}")
    print(f"  discrepancia numerica maxima : {peor:.2e}")
    ok = dif_etiqueta == 0 and dif_proba == 0
    print("  " + ("OK: el JSON predice identico al .pkl" if ok else "FALLA: la conversion cambio el modelo"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
