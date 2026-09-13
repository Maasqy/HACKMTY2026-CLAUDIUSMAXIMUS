#!/usr/bin/env bash
# scripts/rebuild_estates.sh — HACKMTY2026 Forensic Auditor track.
#
# data/estates/*.db and eval/answers/*.json (the 200-estate tuning set) and
# data/holdout_sealed/estates/*.db + eval/holdout_sealed/answers/*.json (the
# 5-estate sealed report set, seeds 921-925) are NOT committed — they are
# entirely reproducible from estate_gen/generate_estate.py plus a seed, and
# committing 50MB of regenerable data is exactly what a generator exists to
# avoid. Run this once after cloning (or any time --clean is needed) to
# rebuild both sets.
#
# Usage:
#   scripts/rebuild_estates.sh              # tuning (1-200) + holdout (921-925)
#   scripts/rebuild_estates.sh --tuning-only
#   scripts/rebuild_estates.sh --holdout-only
#
# IMPORTANT — the sealed holdout set: seeds 921-925 exist to be reported on
# ONCE, at the end, on seeds nobody tuned on or debugged against (see
# data/holdout_sealed/README.md). Running this script regenerates them
# byte-for-byte identically (the generator is deterministic per seed) — it
# does NOT "look at" them, but if you are re-running this because you
# suspect the holdout was inspected or trained on, treat that as
# contamination per this repo's own rule: stop, do not regenerate, ask
# before touching seeds 921-925 again.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

TUNING=1
HOLDOUT=1
case "${1:-}" in
  --tuning-only) HOLDOUT=0 ;;
  --holdout-only) TUNING=0 ;;
  "") ;;
  *) echo "uso: $0 [--tuning-only|--holdout-only]" >&2; exit 1 ;;
esac

mkdir -p data/estates eval/answers data/holdout_sealed/estates eval/holdout_sealed/answers

if [ "$TUNING" = "1" ]; then
  echo "Regenerando tuning set (seeds 1-200) en data/estates/ + eval/answers/ ..."
  for seed in $(seq 1 200); do
    python3 estate_gen/generate_estate.py --seed "$seed"
  done
  echo "  listo: $(ls data/estates/*.db 2>/dev/null | wc -l | tr -d ' ') estates, $(ls eval/answers/*.json 2>/dev/null | wc -l | tr -d ' ') ground-truth files"
fi

if [ "$HOLDOUT" = "1" ]; then
  echo "Regenerando holdout sellado (seeds 921-925) en data/holdout_sealed/ ..."
  for seed in 921 922 923 924 925; do
    python3 estate_gen/generate_estate.py --seed "$seed" \
      --db-dir data/holdout_sealed/estates --gt-dir eval/holdout_sealed/answers
  done
  echo "  listo: $(ls data/holdout_sealed/estates/*.db 2>/dev/null | wc -l | tr -d ' ') estates sellados"
  echo "  NO abras eval/holdout_sealed/answers/*.json salvo para el reporte final autorizado — ver data/holdout_sealed/README.md"
fi
