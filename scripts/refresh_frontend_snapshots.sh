#!/usr/bin/env bash
# scripts/refresh_frontend_snapshots.sh — copia la salida del pipeline hacia
# frontend/public/out/, que es de donde el frontend hace fetch() en dev y en
# build (ver frontend/src/hooks/useSubmission.ts y useEventStream.ts:
# fetch("/out/submission.json") / fetch("/out/events.jsonl")).
#
# El frontend NO lee out/ en la raiz del repo directamente — Vite sirve
# frontend/public/ como publicDir, asi que el archivo tiene que vivir ahi
# adentro. .gitignore ignora out/ en general pero explicita
# "!frontend/public/out/" para que ESTA copia si se versione (referida desde
# vite.config.ts, que documenta este script por nombre).
#
# Uso:
#   bash scripts/refresh_frontend_snapshots.sh                     # copia out/submission.json y out/events.jsonl
#   bash scripts/refresh_frontend_snapshots.sh --submission ruta.json --events ruta.jsonl
#
# Genera primero la salida con, por ejemplo:
#   python3 -m src.run --estate data/estates/mis_proveedores.db \
#       --out out/submission.json --events out/events.jsonl
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUBMISSION="${REPO_ROOT}/out/submission.json"
EVENTS="${REPO_ROOT}/out/events.jsonl"

while [ $# -gt 0 ]; do
  case "$1" in
    --submission) SUBMISSION="$2"; shift 2 ;;
    --events) EVENTS="$2"; shift 2 ;;
    *) echo "argumento no reconocido: $1" >&2; exit 1 ;;
  esac
done

DEST="${REPO_ROOT}/frontend/public/out"
mkdir -p "$DEST"

if [ ! -f "$SUBMISSION" ]; then
  echo "No existe $SUBMISSION — corre el pipeline primero:" >&2
  echo "    python3 -m src.run --estate data/estates/<tu_estate>.db --out out/submission.json --events out/events.jsonl" >&2
  exit 1
fi
cp "$SUBMISSION" "$DEST/submission.json"
echo "copiado: $SUBMISSION -> $DEST/submission.json"

if [ -f "$EVENTS" ]; then
  cp "$EVENTS" "$DEST/events.jsonl"
  echo "copiado: $EVENTS -> $DEST/events.jsonl"
else
  echo "aviso: no existe $EVENTS — el frontend sigue funcionando sin el," \
       "solo no tendra timeline de eventos (es opcional, ver frontend/README.md)" >&2
fi

echo
echo "Listo. Con 'npm run dev' corriendo en frontend/, refresca el navegador."
