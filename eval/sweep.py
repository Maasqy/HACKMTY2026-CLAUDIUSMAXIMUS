#!/usr/bin/env python3
"""Sweep: corre src.run sobre un rango de semillas y las califica.

VIVE EN eval/. No lo importa nadie de src/.

    python eval/sweep.py --seeds 1-50 --label baseline
    python eval/sweep.py --seeds 901-905 --label holdout
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from eval.harness import score  # noqa: E402
from src.run import main as run_main  # noqa: E402


COLUMNS = [
    "seed", "findings", "leads", "recall_num", "recall_den",
    "false_accusations", "peso_error_pct", "wall_clock",
]


def parse_range(spec: str) -> list[int]:
    out: list[int] = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            lo, hi = chunk.split("-", 1)
            out.extend(range(int(lo), int(hi) + 1))
        else:
            out.append(int(chunk))
    return sorted(set(out))


def _row_for_seed(seed: int, tmp_dir: Path) -> dict | None:
    estate = REPO_ROOT / f"data/estates/estate_{seed:04d}.db"
    answers = REPO_ROOT / f"eval/answers/gt_{seed:04d}.json"
    if not estate.exists() or not answers.exists():
        return None

    out_path = tmp_dir / f"submission_{seed:04d}.json"
    t0 = time.monotonic()
    rc = run_main(["--estate", str(estate), "--out", str(out_path)])
    wall = round(time.monotonic() - t0, 2)
    if rc != 0 or not out_path.exists():
        return {
            "seed": seed, "findings": 0, "leads": 0,
            "recall_num": 0, "recall_den": 0,
            "false_accusations": 0, "peso_error_pct": 0.0,
            "wall_clock": wall,
        }

    sub = json.loads(out_path.read_text(encoding="utf-8"))
    res = score(out_path, answers, estate)

    denom = max(float(res["peso_actual"]), 1.0)
    peso_error_pct = round(
        100 * abs(float(res["peso_claimed"]) - float(res["peso_actual"])) / denom, 2
    )
    return {
        "seed": seed,
        "findings": len(sub.get("findings", [])),
        "leads": len(sub.get("leads_not_pursued", [])),
        "recall_num": res["schemes_found"],
        "recall_den": res["schemes_planted"],
        "false_accusations": res["decoys_accused"],
        "peso_error_pct": peso_error_pct,
        "wall_clock": wall,
    }


def _aggregate(rows: list[dict]) -> dict:
    if not rows:
        return {c: "" for c in COLUMNS}
    n = len(rows)
    total_found = sum(r["recall_num"] for r in rows)
    total_planted = sum(r["recall_den"] for r in rows)
    return {
        "seed": f"AGG_n={n}",
        "findings": sum(r["findings"] for r in rows),
        "leads": sum(r["leads"] for r in rows),
        "recall_num": total_found,
        "recall_den": total_planted,
        "false_accusations": sum(r["false_accusations"] for r in rows),
        "peso_error_pct": round(sum(r["peso_error_pct"] for r in rows) / n, 2),
        "wall_clock": round(sum(r["wall_clock"] for r in rows), 2),
    }


def run(seeds: Iterable[int], label: str, out_dir: Path, tmp_dir: Path) -> Path:
    rows: list[dict] = []
    skipped: list[int] = []
    for seed in seeds:
        row = _row_for_seed(seed, tmp_dir)
        if row is None:
            skipped.append(seed)
            continue
        rows.append(row)

    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"sweep_{label}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
        w.writerow(_aggregate(rows))

    total_found = sum(r["recall_num"] for r in rows)
    total_planted = sum(r["recall_den"] for r in rows)
    recall_pct = 100 * total_found / max(total_planted, 1)
    total_fa = sum(r["false_accusations"] for r in rows)
    print()
    print(f"[sweep_{label}]  seeds={len(rows)}  recall={total_found}/{total_planted}"
          f" ({recall_pct:.1f}%)  falsas_acusaciones={total_fa}")
    if skipped:
        print(f"[sweep_{label}]  saltadas: {skipped}")
    print(f"[sweep_{label}]  csv -> {csv_path}")
    return csv_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python eval/sweep.py")
    ap.add_argument("--seeds", required=True, help="p. ej. 1-50 o 1,5,10-15")
    ap.add_argument("--label", required=True)
    ap.add_argument("--out-dir", type=Path, default=REPO_ROOT / "eval" / "runs")
    ap.add_argument("--tmp-dir", type=Path, default=REPO_ROOT / "out" / "sweep")
    args = ap.parse_args(argv)

    args.tmp_dir.mkdir(parents=True, exist_ok=True)
    seeds = parse_range(args.seeds)
    run(seeds, args.label, args.out_dir, args.tmp_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
