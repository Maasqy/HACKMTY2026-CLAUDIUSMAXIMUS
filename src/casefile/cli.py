"""Case file CLI.

Defaults are tuned for the demo: with the submission in out/, run the command
with zero flags.

    python3 -m src.casefile

Optional flags:
    --submission PATH   default: out/submission.json
    --out-dir DIR       default: out/
    --estate PATH       enables company_rfc/period derivation and exhibit lookups
    --company NAME      overrides derived company label
    --period YYYY/YYYY  overrides derived period label
    --method PATH       plain-text file whose contents replace the method paragraph
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, Sequence

from .estate_context import EstateContext
from .loader import load_case_file
from .model import DEFAULT_METHOD, MethodLimits
from .render_html import render as render_html
from .render_md import render as render_md

CASE_FILE_MD = "case_file.md"
CASE_FILE_HTML = "case_file.html"


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    submission_path: Path = args.submission
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    method = _load_method(args.method)

    with EstateContext.open(args.estate) as ctx:
        case = load_case_file(
            submission_path=submission_path,
            ctx=ctx,
            company_flag=args.company,
            period_flag=args.period,
            method=method,
        )

    md_text = render_md(case)
    html_text = render_html(case)

    md_path = out_dir / CASE_FILE_MD
    html_path = out_dir / CASE_FILE_HTML
    md_path.write_text(md_text, encoding="utf-8", newline="\n")
    html_path.write_text(html_text, encoding="utf-8", newline="\n")

    print(f"case_file.md -> {md_path}")
    print(f"case_file.html -> {html_path}")
    return 0


def _parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.casefile",
        description="Render case_file.md and case_file.html from a submission.json",
    )
    parser.add_argument("--submission", type=Path, default=Path("out") / "submission.json")
    parser.add_argument("--out-dir", type=Path, default=Path("out"))
    parser.add_argument("--estate", type=Path, default=None)
    parser.add_argument("--company", type=str, default=None)
    parser.add_argument("--period", type=str, default=None)
    parser.add_argument("--method", type=Path, default=None)
    return parser.parse_args(argv)


def _load_method(path: Optional[Path]) -> MethodLimits:
    if path is None:
        return DEFAULT_METHOD
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return DEFAULT_METHOD
    return MethodLimits(
        architecture=text,
        out_of_scope=DEFAULT_METHOD.out_of_scope,
        cannot_detect=DEFAULT_METHOD.cannot_detect,
        reproducibility=DEFAULT_METHOD.reproducibility,
    )
