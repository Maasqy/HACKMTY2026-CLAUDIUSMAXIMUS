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
import sklearn
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


# A tree grown until every leaf is PURE returns only 0.0 and 1.0 from
# predict_proba. That is not a probability estimate, it is a hard label
# wearing a probability's clothes — and a ROC built on a score with two
# distinct values has exactly three points, so it can only ever be drawn as
# two straight segments. Requiring a minimum number of samples per leaf
# makes each leaf report a class FREQUENCY estimated from enough rows to
# mean something, which is what src/scoring/leads.py needs: it ranks Leads,
# so it needs a graded score, not a verdict. This is a structural choice,
# not a hyperparameter tuned to maximise F1 — CV would happily pick
# min_samples_leaf=1 and hand back the degenerate 0/1 estimator again.
MIN_SAMPLES_LEAF = 40
# Minimum distinct predict_proba values required per class (see prune_cart).
# Below ~4 the one-vs-rest ROC for that class is a couple of straight
# segments rather than a curve, and the AUC stops being informative.
MIN_PROBA_VALUES_PER_CLASS = 4


def prune_cart(X_train, y_train, cv_folds=5, random_state=0):
    base = DecisionTreeClassifier(class_weight="balanced", random_state=random_state,
                                   min_samples_leaf=MIN_SAMPLES_LEAF)
    path = base.cost_complexity_pruning_path(X_train, y_train)
    alphas = sorted(set(path.ccp_alphas))
    if len(alphas) > 25:
        idx = np.linspace(0, len(alphas) - 1, 25).astype(int)
        alphas = [alphas[i] for i in idx]

    best_alpha, best_score = None, -1.0
    fallback_alpha, fallback_score = 0.0, -1.0
    cv = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=random_state)
    for alpha in alphas:
        clf = DecisionTreeClassifier(class_weight="balanced", random_state=random_state,
                                      min_samples_leaf=MIN_SAMPLES_LEAF, ccp_alpha=alpha)
        scores = cross_val_score(clf, X_train, y_train, cv=cv, scoring="f1_macro")
        mean_score = scores.mean()
        if mean_score > fallback_score:
            fallback_alpha, fallback_score = alpha, mean_score
        # Granularity constraint: this model's job is to RANK entities for
        # src/scoring/leads.py, so an alpha that prunes the tree down to
        # near-pure leaves is useless even if its F1 is high — its
        # predict_proba collapses to a couple of distinct values and the
        # resulting ROC degenerates into straight segments. Only consider
        # alphas whose tree still reports a graded frequency for EVERY class.
        probe = clf.fit(X_train, y_train)
        proba = probe.predict_proba(X_train)
        min_vals = min(len(np.unique(np.round(proba[:, i], 6))) for i in range(proba.shape[1]))
        if min_vals < MIN_PROBA_VALUES_PER_CLASS:
            continue
        if mean_score > best_score:
            best_alpha, best_score = alpha, mean_score

    if best_alpha is None:
        # No alpha satisfied the granularity floor — fall back to plain F1
        # selection rather than failing, and let the granularity report in
        # main() make the degeneracy visible.
        print(f"  AVISO: ningun ccp_alpha alcanzo {MIN_PROBA_VALUES_PER_CLASS} valores "
              f"de probabilidad por clase; usando el mejor por F1.")
        best_alpha, best_score = fallback_alpha, fallback_score

    final = DecisionTreeClassifier(class_weight="balanced", random_state=random_state,
                                    min_samples_leaf=MIN_SAMPLES_LEAF, ccp_alpha=best_alpha)
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
        # Version con la que se serializo: sklearn no garantiza que un
        # pickle cargue entre versiones distintas, y un fallo silencioso
        # al deserializar seria un modelo equivocado, no un error.
        "sklearn_version": sklearn.__version__,
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

    # ---- Confusion matrices: the three models side by side ----
    # One panel per model, same labels and same colour scale, so "where does
    # each model actually confuse things" is readable at a glance instead of
    # only being visible for the CART.
    fig, axes = plt.subplots(1, 3, figsize=(19, 6.2))
    for ax, (name, model) in zip(axes, models.items()):
        cm = confusion_matrix(y_test, model.predict(X_test), labels=labels_sorted)
        ConfusionMatrixDisplay(cm, display_labels=labels_sorted).plot(
            ax=ax, colorbar=False, cmap="Blues", xticks_rotation=45, values_format="d"
        )
        acc = accuracy_score(y_test, model.predict(X_test))
        ax.set_title(f"{name}\naccuracy={acc:.4f}", fontsize=11)
        ax.set_xlabel("Prediccion")
        ax.set_ylabel("Real")
    fig.suptitle("Matriz de confusion por modelo — scheme_type, estates held-out", fontsize=13)
    fig.tight_layout()
    fig.savefig(args.out_dir / "confusion_matrix_scheme_type.png", dpi=150)
    plt.close(fig)
    print(f"  wrote {args.out_dir / 'confusion_matrix_scheme_type.png'}")

    # ---- ROC 1: one panel per class, the three models compared inside it ----
    # A single-panel "one curve per class, CART only" plot answered neither
    # question a reader actually has: which classes are hard, and whether an
    # ensemble ranks them better than one tree. One panel per class with all
    # three models answers both.
    y_test_bin = label_binarize(y_test, classes=all_classes)
    probas = {name: proba_aligned(m, X_test, all_classes) for name, m in models.items()}

    n = len(all_classes)
    ncols = 3
    nrows = int(np.ceil(n / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(5.2 * ncols, 4.8 * nrows))
    axes = np.atleast_1d(axes).ravel()
    for i, cls in enumerate(all_classes):
        ax = axes[i]
        if y_test_bin[:, i].sum() == 0:
            ax.set_visible(False)
            continue
        for name in models:
            fpr, tpr, _ = roc_curve(y_test_bin[:, i], probas[name][:, i])
            auc = roc_auc_score(y_test_bin[:, i], probas[name][:, i])
            ax.plot(fpr, tpr, linewidth=1.6, label=f"{name} (AUC={auc:.3f})")
        ax.plot([0, 1], [0, 1], linestyle="--", color="grey", linewidth=1)
        ax.set_title(f"{cls}  (n={int(y_test_bin[:, i].sum())})", fontsize=11)
        ax.set_xlabel("Tasa de falsos positivos")
        ax.set_ylabel("Tasa de verdaderos positivos")
        ax.legend(loc="lower right", fontsize=7.5)
    for j in range(n, len(axes)):
        axes[j].set_visible(False)
    fig.suptitle("ROC one-vs-rest por clase — CART vs Bagging vs Boosting", fontsize=13)
    fig.tight_layout()
    fig.savefig(args.out_dir / "roc_curve_per_clase_cart.png", dpi=150)
    plt.close(fig)
    print(f"  wrote {args.out_dir / 'roc_curve_per_clase_cart.png'}")

    # ---- ROC 2: macro-average one-vs-rest ROC, CART vs Bagging vs Boosting ----
    fig, ax = plt.subplots(figsize=(6, 5.4))
    for name, model in models.items():
        proba = probas[name]
        grid = np.linspace(0, 1, 200)
        tprs = []
        for i, cls in enumerate(all_classes):
            if y_test_bin[:, i].sum() == 0:
                continue
            fpr, tpr, _ = roc_curve(y_test_bin[:, i], proba[:, i])
            tprs.append(np.interp(grid, fpr, tpr))
        mean_tpr = np.mean(tprs, axis=0)
        auc = roc_auc_score(y_test_bin, proba, average="macro", multi_class="ovr")
        ax.plot(grid, mean_tpr, linewidth=1.8, label=f"{name} (AUC_macro={auc:.3f})")
    ax.plot([0, 1], [0, 1], linestyle="--", color="grey", linewidth=1)
    ax.set_xlabel("Tasa de falsos positivos")
    ax.set_ylabel("Tasa de verdaderos positivos (promedio macro)")
    ax.set_title("ROC macro-promedio (one-vs-rest) — CART vs Bagging vs Boosting")
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    fig.savefig(args.out_dir / "roc_curve_comparison_scheme_type.png", dpi=150)
    plt.close(fig)
    print(f"  wrote {args.out_dir / 'roc_curve_comparison_scheme_type.png'}")

    # ---- Probability granularity check ----
    # Guards against silently going back to a degenerate 0/1 estimator: a
    # ROC drawn from a score with 2 distinct values is 2 straight segments,
    # no matter how good the model is. If this ever prints 2, the tree is
    # growing pure leaves again (see MIN_SAMPLES_LEAF).
    print("\nGranularidad de predict_proba (valores distintos por clase):")
    for name in models:
        nvals = [len(np.unique(np.round(probas[name][:, i], 6))) for i in range(len(all_classes))]
        flag = "  <-- DEGENERADO (ROC saldria recta)" if max(nvals) <= 2 else ""
        print(f"  {name:28s} min={min(nvals):3d}  max={max(nvals):4d}{flag}")

    print("\nImportancia de features (CART podado, top 12):")
    importances = pd.Series(cart.feature_importances_, index=feature_cols).sort_values(ascending=False)
    print(importances.head(12).round(4).to_string())


if __name__ == "__main__":
    main()
