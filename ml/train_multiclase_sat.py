#!/usr/bin/env python3
"""
ml/train_multiclase_sat.py — HACKMTY2026 Forensic Auditor track.

Trains a pruned CART (DecisionTreeClassifier) to predict `situacion_sat` —
the vendor's REAL SAT Articulo 69-B legal status (Definitivo / Presunto /
Desvirtuado / Favorable / No listado) — instead of the planted-scheme binary
label `es_fraude` that train_cart.py uses. This is a genuinely different
target: it is not "is this vendor part of a fraud scheme I planted", it is
"what does the real government classification of this RFC look like, given
only its transactional behavior".

IMPORTANT — feature leakage guard: `en_lista_69b` and `es_69b_definitivo`
(in features_train.csv) are computed from the exact same efos_list lookup
that produces `situacion_sat`. `es_69b_definitivo` is in fact identical to
the one-hot indicator for the 'definitivo' class. Both columns are EXCLUDED
from the feature set here — training on them would just be the model
reading the label off a copy of itself. Every other column (amounts, payment
traceability, PO patterns, dates, ledger totals, contract presence...) stays,
since those are the actual observable signals a real classifier would have
if the 69-B status were unknown.

Like build_features.py, this lives OUTSIDE src/ as part of the offline
training flow. Split: by estate (seed), not row, same as train_cart.py.

Outputs (in --out-dir, default ml/artifacts_multiclase/):
  modelo_cart_multiclase.pkl        pickled (tree, feature_names, classes, ccp_alpha)
  metrics_comparison.csv            accuracy + macro precision/recall/f1/roc_auc_ovr, 3 models
  classification_report.csv         per-class precision/recall/f1/support (CART)
  confusion_matrix_multiclase.png
  roc_curve_per_clase_cart.png       one-vs-rest ROC, one curve per class, CART podado
  roc_curve_comparison_multiclase.png  macro-average one-vs-rest ROC, CART vs Bagging vs Boosting

Note on ROC in a multiclass setting: there is no single ROC curve the way
there is for binary es_fraude. Each class gets its own one-vs-rest curve
(e.g. "definitivo vs everything else"); roc_auc_score(..., multi_class="ovr")
averages those per-class AUCs (macro) into one comparable number per model.

Usage:
  python3 ml/train_multiclase_sat.py
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
TARGET_COL = "situacion_sat"
CATEGORICAL_COLS = ["categoria"]
# Excluded because they are computed from the same efos_list lookup that
# produces the label itself (es_69b_definitivo IS the 'definitivo' class).
LEAKY_COLS = ["en_lista_69b", "es_69b_definitivo"]
# es_fraude is a different label (planted-scheme membership), not a feature.
OTHER_LABEL_COLS = ["es_fraude"]


def load_xy(features_path: Path):
    df = pd.read_csv(features_path)
    dias_median = float(df["dias_antiguedad_al_facturar"].median())
    df["dias_antiguedad_al_facturar"] = df["dias_antiguedad_al_facturar"].fillna(dias_median)
    categoria_values = sorted(df["categoria"].dropna().unique().tolist())
    df = pd.get_dummies(df, columns=CATEGORICAL_COLS, prefix="cat")
    drop_cols = ID_COLS + [TARGET_COL] + LEAKY_COLS + OTHER_LABEL_COLS
    feature_cols = [c for c in df.columns if c not in drop_cols]
    # Preprocessing metadata needed to reproduce this exact feature vector at
    # inference time on a SINGLE new vendor (where get_dummies alone would
    # only ever produce the one category column that vendor happens to have,
    # not all the columns the model was trained on).
    preprocess = {"dias_antiguedad_median": dias_median, "categoria_values": categoria_values}
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
    ap.add_argument("--out-dir", type=Path, default=HERE / "artifacts_multiclase")
    ap.add_argument("--test-seeds-frac", type=float, default=0.25)
    ap.add_argument("--random-state", type=int, default=0)
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    df, feature_cols, preprocess = load_xy(args.features)
    train_df, test_df, test_seeds = split_by_estate(df, args.test_seeds_frac, args.random_state)
    print(f"estates train: {train_df['estate_seed'].nunique()}  "
          f"estates test (held-out): {len(test_seeds)}")
    print(f"filas train: {len(train_df)}  filas test: {len(test_df)}")
    print("distribucion situacion_sat (train):")
    print(train_df[TARGET_COL].value_counts().to_string())
    print("\nfeatures excluidas por fuga (derivadas del mismo lookup que la etiqueta):", LEAKY_COLS)

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
        "categoria_values": preprocess["categoria_values"],
        "target_col": TARGET_COL,
        "leaky_cols_excluded": LEAKY_COLS,
    }
    with open(args.out_dir / "modelo_cart_multiclase.pkl", "wb") as f:
        pickle.dump(model_bundle, f)
    print(f"  wrote {args.out_dir / 'modelo_cart_multiclase.pkl'}")

    y_pred_cart = cart.predict(X_test)
    report = classification_report(y_test, y_pred_cart, output_dict=True, zero_division=0)
    report_df = pd.DataFrame(report).transpose()
    report_path = args.out_dir / "classification_report.csv"
    report_df.to_csv(report_path)
    print(f"\n{report_df.round(4).to_string()}")
    print(f"  wrote {report_path}")

    labels_sorted = sorted(y_test.unique())
    cm = confusion_matrix(y_test, y_pred_cart, labels=labels_sorted)
    fig, ax = plt.subplots(figsize=(6, 6))
    ConfusionMatrixDisplay(cm, display_labels=labels_sorted).plot(
        ax=ax, colorbar=False, cmap="Blues", xticks_rotation=30
    )
    ax.set_title("CART podado (multiclase) — situacion_sat, estates held-out")
    fig.tight_layout()
    fig.savefig(args.out_dir / "confusion_matrix_multiclase.png", dpi=150)
    plt.close(fig)
    print(f"  wrote {args.out_dir / 'confusion_matrix_multiclase.png'}")

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
    fig, ax = plt.subplots(figsize=(6, 5.5))
    for i, cls in enumerate(all_classes):
        if y_test_bin[:, i].sum() == 0:
            continue  # class absent from this held-out split, nothing to plot
        fpr, tpr, _ = roc_curve(y_test_bin[:, i], cart_proba[:, i])
        auc = roc_auc_score(y_test_bin[:, i], cart_proba[:, i])
        ax.plot(fpr, tpr, label=f"{cls} (AUC={auc:.3f})")
    ax.plot([0, 1], [0, 1], linestyle="--", color="grey", linewidth=1)
    ax.set_xlabel("Tasa de falsos positivos")
    ax.set_ylabel("Tasa de verdaderos positivos")
    ax.set_title("ROC one-vs-rest por clase — CART podado (situacion_sat)")
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    fig.savefig(args.out_dir / "roc_curve_per_clase_cart.png", dpi=150)
    plt.close(fig)
    print(f"  wrote {args.out_dir / 'roc_curve_per_clase_cart.png'}")

    # ---- ROC 2: macro-average one-vs-rest ROC, CART vs Bagging vs Boosting ----
    fig, ax = plt.subplots(figsize=(5.5, 5))
    for name, model in models.items():
        proba = proba_aligned(model, X_test, all_classes)
        # Macro-average ROC: interpolate each class's OVR curve onto a
        # common FPR grid, then average TPR across classes (standard
        # one-vs-rest macro-average ROC construction for multiclass).
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
    fig.savefig(args.out_dir / "roc_curve_comparison_multiclase.png", dpi=150)
    plt.close(fig)
    print(f"  wrote {args.out_dir / 'roc_curve_comparison_multiclase.png'}")

    print("\nImportancia de features (CART podado, top 10):")
    importances = pd.Series(cart.feature_importances_, index=feature_cols).sort_values(ascending=False)
    print(importances.head(10).round(4).to_string())


if __name__ == "__main__":
    main()
