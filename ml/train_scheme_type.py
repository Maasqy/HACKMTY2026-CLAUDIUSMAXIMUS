#!/usr/bin/env python3
"""
ml/train_scheme_type.py — HACKMTY2026 Forensic Auditor track.

PRIMARY model. Trains a pruned CART (DecisionTreeClassifier) to predict
`scheme_type` — the actual judged task: "what kind of planted fraud scheme,
if any, is this entity part of", one of the five official scheme_type enum
values (phantom_vendor, kickback, round_tripping, threshold_splitting,
revenue_inflation) or 'no_esquema'. This replaces situacion_sat
(ml/train_multiclase_sat.py, now a demoted SECONDARY signal) as the model
that actually informs src/scoring/leads.py's ranking.

Trained on ALL rows from ml/build_features.py — vendor entities AND client
entities (revenue_inflation's accused entity is a client, never a vendor;
see build_features.py's module docstring) — since restricting to vendors
alone makes that one class structurally impossible to ever predict, no
matter how the model is tuned.

Feature notes:
  - en_lista_69b / es_69b_definitivo ARE kept here (unlike in
    train_multiclase_sat.py). They are not leaky for THIS target: being on
    efos_list does not by itself make an entity part of a planted scheme —
    the 'presunto' vendors planted by build_sat_status_population() are
    real, on efos_list, and NOT part of any scheme (scheme_type ==
    'no_esquema' for them). So these columns are a legitimate, if strong,
    signal for phantom_vendor specifically, same as any other feature.
  - situacion_sat / es_fraude are excluded as FEATURES (they are label
    columns computed for a different purpose, not observable inputs).

IMPORTANT, per the project's own scoring rules: this model's predict_proba
output is a Lead-ranking SIGNAL, never itself a Finding. See
src/scoring/leads.py and src/scoring/model.py for how it is (and, just as
importantly, is NOT) used: "Un score de 0.94 no prueba nada ante un
auditor" — an accusation is built by the investigator and only stands after
a deterministic validator checks it against real exhibits.

Like build_features.py, this lives OUTSIDE src/ as part of the offline
training flow. Split: by estate (seed), not row, so no estate leaks across
train/test.

Outputs (in --out-dir, default ml/artifacts_scheme_type/):
  modelo_cart_scheme_type.pkl        pickled (tree, feature_names, classes, ccp_alpha)
  metrics_comparison.csv             accuracy + macro precision/recall/f1/roc_auc_ovr, 3 models
  classification_report.csv          per-class precision/recall/f1/support (CART)
  confusion_matrix_scheme_type.png
  roc_curve_per_clase_cart.png       one-vs-rest ROC, one curve per class, CART podado
  roc_curve_comparison_scheme_type.png  macro-average one-vs-rest ROC, CART vs Bagging vs Boosting

Usage:
  python3 ml/train_scheme_type.py
"""

import argparse
import pickle
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import (
    ConfusionMatrixDisplay,
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.preprocessing import label_binarize
from sklearn.tree import DecisionTreeClassifier

HERE = Path(__file__).resolve().parent

ID_COLS = ["estate_seed", "rfc"]
TARGET_COL = "scheme_type"
CATEGORICAL_COLS = ["categoria"]
# situacion_sat/es_fraude are label columns for a *different* target, not
# observable features for this one.
OTHER_LABEL_COLS = ["es_fraude", "situacion_sat"]


def load_xy(features_path: Path):
    df = pd.read_csv(features_path)
    dias_median = float(df["dias_antiguedad_al_facturar"].median())
    df["dias_antiguedad_al_facturar"] = df["dias_antiguedad_al_facturar"].fillna(dias_median)
    dias_cierre_median = float(df["dias_a_cierre_periodo_venta"].median())
    df["dias_a_cierre_periodo_venta"] = df["dias_a_cierre_periodo_venta"].fillna(dias_cierre_median)
    categoria_values = sorted(df["categoria"].dropna().unique().tolist())
    df = pd.get_dummies(df, columns=CATEGORICAL_COLS, prefix="cat")
    drop_cols = ID_COLS + [TARGET_COL] + OTHER_LABEL_COLS
    feature_cols = [c for c in df.columns if c not in drop_cols]
    # Preprocessing metadata needed to reproduce this exact feature vector at
    # inference time on a SINGLE new entity (where get_dummies alone would
    # only ever produce the one category column that entity happens to have,
    # not all the columns the model was trained on).
    preprocess = {
        "dias_antiguedad_median": dias_median,
        "dias_a_cierre_periodo_venta_median": dias_cierre_median,
        "categoria_values": categoria_values,
    }
    return df, feature_cols, preprocess


def split_by_estate(df: pd.DataFrame, test_frac: float, seed: int = 0):
    seeds = sorted(df["estate_seed"].unique())
    rng = np.random.RandomState(seed)
    rng.shuffle(seeds)
    n_test = max(1, round(len(seeds) * test_frac))
    test_seeds = set(seeds[:n_test])
    train_mask = ~df["estate_seed"].isin(test_seeds)
    return df[train_mask].copy(), df[~train_mask].copy(), sorted(test_seeds)


def prune_cart(X_train, y_train, cv_folds=5, random_state=0):
    base = DecisionTreeClassifier(class_weight="balanced", random_state=random_state)
    path = base.cost_complexity_pruning_path(X_train, y_train)
    alphas = sorted(set(path.ccp_alphas))
    if len(alphas) > 25:
        idx = np.linspace(0, len(alphas) - 1, 25).astype(int)
        alphas = [alphas[i] for i in idx]

    best_alpha, best_score = 0.0, -1.0
    cv = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=random_state)
    for alpha in alphas:
        clf = DecisionTreeClassifier(class_weight="balanced", random_state=random_state, ccp_alpha=alpha)
        scores = cross_val_score(clf, X_train, y_train, cv=cv, scoring="f1_macro")
        mean_score = scores.mean()
        if mean_score > best_score:
            best_alpha, best_score = alpha, mean_score

    final = DecisionTreeClassifier(class_weight="balanced", random_state=random_state, ccp_alpha=best_alpha)
    final.fit(X_train, y_train)
    return final, best_alpha, best_score


def proba_aligned(model, X, classes: list) -> np.ndarray:
    """model.predict_proba columns follow model.classes_, which may not be
    in the same order (or cover the same set, if a class is rare/missing
    from a bootstrap) as `classes`. Reindex to a fixed column order so ROC
    curves and roc_auc_score line up across CART/RandomForest/Boosting."""
    proba = model.predict_proba(X)
    df = pd.DataFrame(proba, columns=list(model.classes_))
    return df.reindex(columns=classes, fill_value=0.0).values


def evaluate(model, X_test, y_test, name: str, classes: list) -> dict:
    y_pred = model.predict(X_test)
    y_test_bin = label_binarize(y_test, classes=classes)
    proba = proba_aligned(model, X_test, classes)
    try:
        roc_auc_ovr = roc_auc_score(y_test_bin, proba, average="macro", multi_class="ovr")
    except ValueError:
        roc_auc_ovr = float("nan")
    return {
        "modelo": name,
        "accuracy": round(accuracy_score(y_test, y_pred), 4),
        "precision_macro": round(precision_score(y_test, y_pred, average="macro", zero_division=0), 4),
        "recall_macro": round(recall_score(y_test, y_pred, average="macro", zero_division=0), 4),
        "f1_macro": round(f1_score(y_test, y_pred, average="macro", zero_division=0), 4),
        "roc_auc_macro_ovr": round(roc_auc_ovr, 4),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--features", type=Path, default=HERE / "features_train.csv")
    ap.add_argument("--out-dir", type=Path, default=HERE / "artifacts_scheme_type")
    ap.add_argument("--test-seeds-frac", type=float, default=0.25)
    ap.add_argument("--random-state", type=int, default=0)
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    df, feature_cols, preprocess = load_xy(args.features)
    train_df, test_df, test_seeds = split_by_estate(df, args.test_seeds_frac, args.random_state)
    print(f"estates train: {train_df['estate_seed'].nunique()}  "
          f"estates test (held-out): {len(test_seeds)}")
    print(f"filas train: {len(train_df)}  filas test: {len(test_df)}")
    print("distribucion scheme_type (train):")
    print(train_df[TARGET_COL].value_counts().to_string())

    X_train, y_train = train_df[feature_cols], train_df[TARGET_COL]
    X_test, y_test = test_df[feature_cols], test_df[TARGET_COL]

    # ---- CART (pruned, multiclass) ----
    cart, best_alpha, cv_f1 = prune_cart(X_train, y_train, random_state=args.random_state)
    print(f"\nCART podado: ccp_alpha={best_alpha:.6f}  hojas={cart.get_n_leaves()}  "
          f"profundidad={cart.get_depth()}  F1_macro (CV en train)={cv_f1:.4f}")

    model_bundle = {
        "model": cart,
        "feature_names": feature_cols,
        "classes": list(cart.classes_),
        "ccp_alpha": best_alpha,
        "categorical_cols": CATEGORICAL_COLS,
        "dias_antiguedad_median": preprocess["dias_antiguedad_median"],
        "dias_a_cierre_periodo_venta_median": preprocess["dias_a_cierre_periodo_venta_median"],
        "categoria_values": preprocess["categoria_values"],
        "target_col": TARGET_COL,
    }
    with open(args.out_dir / "modelo_cart_scheme_type.pkl", "wb") as f:
        pickle.dump(model_bundle, f)
    print(f"  wrote {args.out_dir / 'modelo_cart_scheme_type.pkl'}")

    y_pred_cart = cart.predict(X_test)
    report = classification_report(y_test, y_pred_cart, output_dict=True, zero_division=0)
    report_df = pd.DataFrame(report).transpose()
    report_path = args.out_dir / "classification_report.csv"
    report_df.to_csv(report_path)
    print(f"\n{report_df.round(4).to_string()}")
    print(f"  wrote {report_path}")

    labels_sorted = sorted(y_test.unique())
    cm = confusion_matrix(y_test, y_pred_cart, labels=labels_sorted)
    fig, ax = plt.subplots(figsize=(7, 7))
    ConfusionMatrixDisplay(cm, display_labels=labels_sorted).plot(
        ax=ax, colorbar=False, cmap="Blues", xticks_rotation=30
    )
    ax.set_title("CART podado (multiclase) — scheme_type, estates held-out")
    fig.tight_layout()
    fig.savefig(args.out_dir / "confusion_matrix_scheme_type.png", dpi=150)
    plt.close(fig)
    print(f"  wrote {args.out_dir / 'confusion_matrix_scheme_type.png'}")

    # ---- Comparison: bagging (RandomForest) and boosting (GradientBoosting) ----
    models = {
        "CART_podado": cart,
        "Bagging_RandomForest": RandomForestClassifier(
            n_estimators=300, class_weight="balanced", random_state=args.random_state
        ),
        "Boosting_GradientBoosting": GradientBoostingClassifier(random_state=args.random_state),
    }
    for name, model in models.items():
        if name != "CART_podado":
            model.fit(X_train, y_train)

    all_classes = sorted(y_train.unique())
    results = [evaluate(model, X_test, y_test, name, all_classes) for name, model in models.items()]
    results_df = pd.DataFrame(results)
    comp_path = args.out_dir / "metrics_comparison.csv"
    results_df.to_csv(comp_path, index=False)
    print(f"\n{results_df.to_string(index=False)}")
    print(f"  wrote {comp_path}")

    # ---- ROC 1: one curve per class (one-vs-rest), CART podado ----
    y_test_bin = label_binarize(y_test, classes=all_classes)
    cart_proba = proba_aligned(cart, X_test, all_classes)
    fig, ax = plt.subplots(figsize=(6.5, 6))
    for i, cls in enumerate(all_classes):
        if y_test_bin[:, i].sum() == 0:
            continue  # class absent from this held-out split, nothing to plot
        fpr, tpr, _ = roc_curve(y_test_bin[:, i], cart_proba[:, i])
        auc = roc_auc_score(y_test_bin[:, i], cart_proba[:, i])
        ax.plot(fpr, tpr, label=f"{cls} (AUC={auc:.3f})")
    ax.plot([0, 1], [0, 1], linestyle="--", color="grey", linewidth=1)
    ax.set_xlabel("Tasa de falsos positivos")
    ax.set_ylabel("Tasa de verdaderos positivos")
    ax.set_title("ROC one-vs-rest por clase — CART podado (scheme_type)")
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    fig.savefig(args.out_dir / "roc_curve_per_clase_cart.png", dpi=150)
    plt.close(fig)
    print(f"  wrote {args.out_dir / 'roc_curve_per_clase_cart.png'}")

    # ---- ROC 2: macro-average one-vs-rest ROC, CART vs Bagging vs Boosting ----
    fig, ax = plt.subplots(figsize=(5.5, 5))
    for name, model in models.items():
        proba = proba_aligned(model, X_test, all_classes)
        grid = np.linspace(0, 1, 200)
        tprs = []
        for i, cls in enumerate(all_classes):
            if y_test_bin[:, i].sum() == 0:
                continue
            fpr, tpr, _ = roc_curve(y_test_bin[:, i], proba[:, i])
            tprs.append(np.interp(grid, fpr, tpr))
        mean_tpr = np.mean(tprs, axis=0)
        auc = roc_auc_score(y_test_bin, proba, average="macro", multi_class="ovr")
        ax.plot(grid, mean_tpr, label=f"{name} (AUC_macro={auc:.3f})")
    ax.plot([0, 1], [0, 1], linestyle="--", color="grey", linewidth=1)
    ax.set_xlabel("Tasa de falsos positivos")
    ax.set_ylabel("Tasa de verdaderos positivos (promedio macro)")
    ax.set_title("ROC macro-promedio (one-vs-rest) — CART vs Bagging vs Boosting")
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    fig.savefig(args.out_dir / "roc_curve_comparison_scheme_type.png", dpi=150)
    plt.close(fig)
    print(f"  wrote {args.out_dir / 'roc_curve_comparison_scheme_type.png'}")

    print("\nImportancia de features (CART podado, top 12):")
    importances = pd.Series(cart.feature_importances_, index=feature_cols).sort_values(ascending=False)
    print(importances.head(12).round(4).to_string())


if __name__ == "__main__":
    main()
