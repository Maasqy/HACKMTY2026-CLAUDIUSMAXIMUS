#!/usr/bin/env python3
"""
ml/train_cart.py — HACKMTY2026 Forensic Auditor track.

Trains a pruned CART (DecisionTreeClassifier) on ml/features_train.csv to
find fraud rules over vendor-level financial features, then compares it
against a bagging ensemble (RandomForest) and a boosting ensemble
(GradientBoosting) on the same held-out estates.

Like build_features.py, this lives OUTSIDE src/ as part of the offline
training flow — it is allowed to use the es_fraude label (which ultimately
comes from eval/answers/gt_NNNN.json via build_features.py). The agent that
runs during the demo does not import this file, does not import sklearn's
fitted tree logic into its live reasoning path, and never sees a
ground-truth file directly.

Split: estates (seeds), not rows, are split into train/test — all vendor
rows from the same estate stay on the same side, so the model is evaluated
on estates it has never seen, the same standard the hackathon's own judging
rules apply to the agent.

Outputs (in --out-dir, default ml/artifacts/):
  modelo_cart.pkl          pickled (tree, feature_names, threshold) for CART
  metrics_comparison.csv   accuracy/precision/recall/f1/roc_auc, 3 models
  odds_ratios_cart.csv     per-split odds ratio of the pruned CART tree
  confusion_matrix_cart.png
  roc_curve_comparison.png  ROC for CART vs RandomForest vs GradientBoosting

Usage:
  python3 ml/train_cart.py
  python3 ml/train_cart.py --features ml/features_train.csv --test-seeds-frac 0.25
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
    RocCurveDisplay,
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.tree import DecisionTreeClassifier

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

ID_COLS = ["estate_seed", "rfc"]
TARGET_COL = "es_fraude"
CATEGORICAL_COLS = ["categoria"]


def load_xy(features_path: Path):
    df = pd.read_csv(features_path)
    df["dias_antiguedad_al_facturar"] = df["dias_antiguedad_al_facturar"].fillna(
        df["dias_antiguedad_al_facturar"].median()
    )
    df = pd.get_dummies(df, columns=CATEGORICAL_COLS, prefix="cat")
    feature_cols = [c for c in df.columns if c not in ID_COLS + [TARGET_COL]]
    return df, feature_cols


def split_by_estate(df: pd.DataFrame, test_frac: float, seed: int = 0):
    seeds = sorted(df["estate_seed"].unique())
    rng = np.random.RandomState(seed)
    rng.shuffle(seeds)
    n_test = max(1, round(len(seeds) * test_frac))
    test_seeds = set(seeds[:n_test])
    train_mask = ~df["estate_seed"].isin(test_seeds)
    return df[train_mask].copy(), df[~train_mask].copy(), sorted(test_seeds)


def prune_cart(X_train, y_train, cv_folds=5, random_state=0):
    """Cost-complexity pruning: fit the full path of ccp_alphas, pick the
    alpha with the best mean cross-validated F1 on the training set, refit
    the final tree at that alpha. This is the 'pruned tree' the track's
    determinism rule expects — not the unpruned, memorized-the-training-set
    default DecisionTreeClassifier()."""
    base = DecisionTreeClassifier(class_weight="balanced", random_state=random_state)
    path = base.cost_complexity_pruning_path(X_train, y_train)
    alphas = sorted(set(path.ccp_alphas))
    if len(alphas) > 25:  # keep the search cheap
        idx = np.linspace(0, len(alphas) - 1, 25).astype(int)
        alphas = [alphas[i] for i in idx]

    best_alpha, best_score = 0.0, -1.0
    cv = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=random_state)
    for alpha in alphas:
        clf = DecisionTreeClassifier(class_weight="balanced", random_state=random_state, ccp_alpha=alpha)
        scores = cross_val_score(clf, X_train, y_train, cv=cv, scoring="f1")
        mean_score = scores.mean()
        if mean_score > best_score:
            best_alpha, best_score = alpha, mean_score

    final = DecisionTreeClassifier(class_weight="balanced", random_state=random_state, ccp_alpha=best_alpha)
    final.fit(X_train, y_train)
    return final, best_alpha, best_score


def tree_split_odds_ratios(tree_model: DecisionTreeClassifier, feature_names: list[str]) -> pd.DataFrame:
    """For every internal (non-leaf) node of the pruned tree, computes the
    odds ratio of es_fraude=1 between its left and right child.

    CART has no coefficients the way logistic regression does, so 'odds
    ratio' here is defined per split: OR = odds(fraud | left child) /
    odds(fraud | right child), using each child's class distribution over
    the TRAINING rows that reached that node. OR > 1 means the rule
    'feature <= threshold' (left) routes toward fraud relative to the
    right branch; OR < 1 means the opposite. A row is added per internal
    node; leaves are skipped (no split to report an odds ratio for)."""
    t = tree_model.tree_
    rows = []

    def rate(node_id):
        # tree_.value[node] is [[n_class0, n_class1]] under sample_weight;
        # class_weight='balanced' is baked into that count already.
        counts = t.value[node_id][0]
        total = counts.sum()
        return (counts[1] / total) if total > 0 else 0.0

    def odds(p):
        p = min(max(p, 1e-6), 1 - 1e-6)
        return p / (1 - p)

    for node_id in range(t.node_count):
        if t.children_left[node_id] == t.children_right[node_id]:
            continue  # leaf
        left, right = t.children_left[node_id], t.children_right[node_id]
        p_left, p_right = rate(left), rate(right)
        rows.append({
            "node_id": node_id,
            "feature": feature_names[t.feature[node_id]],
            "threshold": round(float(t.threshold[node_id]), 4),
            "n_samples_node": int(t.n_node_samples[node_id]),
            "fraud_rate_left": round(p_left, 4),
            "fraud_rate_right": round(p_right, 4),
            "odds_ratio_left_vs_right": round(odds(p_left) / odds(p_right), 4),
        })
    return pd.DataFrame(rows)


def evaluate(model, X_test, y_test, name: str) -> dict:
    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]
    return {
        "modelo": name,
        "accuracy": round(accuracy_score(y_test, y_pred), 4),
        "precision": round(precision_score(y_test, y_pred, zero_division=0), 4),
        "recall": round(recall_score(y_test, y_pred, zero_division=0), 4),
        "f1": round(f1_score(y_test, y_pred, zero_division=0), 4),
        "roc_auc": round(roc_auc_score(y_test, y_proba), 4),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--features", type=Path, default=HERE / "features_train.csv")
    ap.add_argument("--out-dir", type=Path, default=HERE / "artifacts")
    ap.add_argument("--test-seeds-frac", type=float, default=0.25)
    ap.add_argument("--random-state", type=int, default=0)
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    df, feature_cols = load_xy(args.features)
    train_df, test_df, test_seeds = split_by_estate(df, args.test_seeds_frac, args.random_state)
    print(f"estates train: {train_df['estate_seed'].nunique()}  "
          f"estates test (held-out): {len(test_seeds)}  seeds={test_seeds}")
    print(f"filas train: {len(train_df)} (fraude={train_df[TARGET_COL].sum()})  "
          f"filas test: {len(test_df)} (fraude={test_df[TARGET_COL].sum()})")

    X_train, y_train = train_df[feature_cols], train_df[TARGET_COL]
    X_test, y_test = test_df[feature_cols], test_df[TARGET_COL]

    # ---- CART (pruned) ----
    cart, best_alpha, cv_f1 = prune_cart(X_train, y_train, random_state=args.random_state)
    print(f"\nCART podado: ccp_alpha={best_alpha:.6f}  hojas={cart.get_n_leaves()}  "
          f"profundidad={cart.get_depth()}  F1 (CV en train)={cv_f1:.4f}")

    with open(args.out_dir / "modelo_cart.pkl", "wb") as f:
        pickle.dump({"model": cart, "feature_names": feature_cols, "ccp_alpha": best_alpha}, f)
    print(f"  wrote {args.out_dir / 'modelo_cart.pkl'}")

    odds_df = tree_split_odds_ratios(cart, feature_cols)
    odds_path = args.out_dir / "odds_ratios_cart.csv"
    odds_df.to_csv(odds_path, index=False)
    print(f"  wrote {odds_path} ({len(odds_df)} splits)")

    cm = confusion_matrix(y_test, cart.predict(X_test))
    fig, ax = plt.subplots(figsize=(4.5, 4.5))
    ConfusionMatrixDisplay(cm, display_labels=["no_fraude", "fraude"]).plot(ax=ax, colorbar=False, cmap="Blues")
    ax.set_title("CART podado — matriz de confusion (estates held-out)")
    fig.tight_layout()
    fig.savefig(args.out_dir / "confusion_matrix_cart.png", dpi=150)
    plt.close(fig)
    print(f"  wrote {args.out_dir / 'confusion_matrix_cart.png'}")

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

    results = [evaluate(model, X_test, y_test, name) for name, model in models.items()]
    results_df = pd.DataFrame(results)
    comp_path = args.out_dir / "metrics_comparison.csv"
    results_df.to_csv(comp_path, index=False)
    print(f"\n{results_df.to_string(index=False)}")
    print(f"  wrote {comp_path}")

    fig, ax = plt.subplots(figsize=(5.5, 5))
    for name, model in models.items():
        proba = model.predict_proba(X_test)[:, 1]
        fpr, tpr, _ = roc_curve(y_test, proba)
        auc = roc_auc_score(y_test, proba)
        ax.plot(fpr, tpr, label=f"{name} (AUC={auc:.3f})")
    ax.plot([0, 1], [0, 1], linestyle="--", color="grey", linewidth=1)
    ax.set_xlabel("Tasa de falsos positivos")
    ax.set_ylabel("Tasa de verdaderos positivos")
    ax.set_title("ROC — CART vs Bagging vs Boosting (estates held-out)")
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    fig.savefig(args.out_dir / "roc_curve_comparison.png", dpi=150)
    plt.close(fig)
    print(f"  wrote {args.out_dir / 'roc_curve_comparison.png'}")

    print("\nTop 10 splits del CART por |log(odds ratio)| (senales mas discriminantes):")
    odds_df["abs_log_or"] = np.log(odds_df["odds_ratio_left_vs_right"].clip(lower=1e-9)).abs()
    print(odds_df.sort_values("abs_log_or", ascending=False).head(10)
          .drop(columns="abs_log_or").to_string(index=False))


if __name__ == "__main__":
    main()
