#!/usr/bin/env bash
# scripts/demo_desde_db.sh — la cadena COMPLETA, de un estate.db al dashboard.
#
# CORRE ESTO EN TU MAC, en Terminal.app (necesita Ollama levantado).
#
# Existe porque la cadena tiene un tramo que es facil de olvidar y que no
# avisa cuando falta:
#
#   CSVs -> (navegador) estate.db -> [ESTE SCRIPT] -> dashboard
#                                     |
#                                     +- python3 -m src.run   (Gemma investiga)
#                                     +- copia a frontend/public/out/
#
# El dashboard NUNCA lee un .db. Lee frontend/public/out/submission.json.
# Descargar el .db desde la pantalla Upload no cambia nada en el overview
# por si solo: ese archivo es el INSUMO de esta parte, no el resultado.
#
# Uso:
#   bash scripts/demo_desde_db.sh                      # toma el estate_*.db mas reciente de ~/Downloads
#   bash scripts/demo_desde_db.sh ruta/al/estate.db    # o le pasas uno explicito
#   bash scripts/demo_desde_db.sh --sin-modelo         # sin Gemma (rapido, 0 findings, solo prueba el cableado)
#
# Al terminar imprime el ANTES y el DESPUES de lo que el dashboard esta
# leyendo, para que se vea si de verdad cambio algo o si quedo igual.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DB=""
MAX_LEADS=4
EXTRA=()

while [ $# -gt 0 ]; do
  case "$1" in
    --sin-modelo) EXTRA+=("--sin-modelo"); shift ;;
    --max-leads)  MAX_LEADS="$2"; shift 2 ;;
    -*)           EXTRA+=("$1"); shift ;;
    *)            DB="$1"; shift ;;
  esac
done

# Sin argumento: el estate_*.db mas reciente en ~/Downloads, que es donde
# cae el que descarga la pantalla Upload del frontend.
if [ -z "$DB" ]; then
  DB="$(ls -t "$HOME"/Downloads/estate_*.db 2>/dev/null | head -1)"
  if [ -z "$DB" ]; then
    echo "No encontre ningun estate_*.db en ~/Downloads." >&2
    echo "Pasale la ruta:  bash scripts/demo_desde_db.sh ruta/al/estate.db" >&2
    exit 1
  fi
  echo "Usando el .db mas reciente de ~/Downloads:"
  echo "    $DB"
  echo
fi

if [ ! -f "$DB" ]; then
  echo "No existe: $DB" >&2
  exit 1
fi

DEST="frontend/public/out/submission.json"

# --- ANTES -----------------------------------------------------------------
echo "== lo que el dashboard esta leyendo AHORA =="
if [ -f "$DEST" ]; then
  python3 - "$DEST" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
print(f"   findings: {len(d['findings'])}   leads_not_pursued: {len(d['leads_not_pursued'])}")
for f in d["findings"]:
    print(f"     - {f['scheme_type']}: {', '.join(f['entities'])}  ${f['peso_amount']:,.2f}")
PY
else
  echo "   (todavia no existe $DEST)"
fi
echo

# --- CORRIDA ---------------------------------------------------------------
echo "== corriendo el pipeline sobre ese .db =="
mkdir -p out
python3 -m src.run --estate "$DB" --out out/submission.json \
    --max-leads "$MAX_LEADS" --events out/events.jsonl "${EXTRA[@]+"${EXTRA[@]}"}"
RC=$?
echo
if [ $RC != 0 ]; then
  echo "El pipeline fallo (codigo $RC). No copio nada: el dashboard se queda como estaba." >&2
  exit $RC
fi

# --- COPIA -----------------------------------------------------------------
mkdir -p frontend/public/out
cp out/submission.json "$DEST"
[ -f out/events.jsonl ] && cp out/events.jsonl frontend/public/out/events.jsonl
echo "== copiado a frontend/public/out/ =="
echo

# --- DESPUES + diagnostico -------------------------------------------------
echo "== lo que el dashboard va a leer DESPUES del refresh =="
python3 - "$DEST" <<'PY'
import json, sys
from collections import Counter
d = json.load(open(sys.argv[1], encoding="utf-8"))
print(f"   findings: {len(d['findings'])}   leads_not_pursued: {len(d['leads_not_pursued'])}")
for f in d["findings"]:
    print(f"     - {f['scheme_type']}: {', '.join(f['entities'])}  ${f['peso_amount']:,.2f}")

if not d["findings"]:
    print()
    print("   0 findings. Por que quedo cada lead fuera:")
    for l in d["leads_not_pursued"]:
        print(f"     - {l['entity']} [{l['closed_by']}]: {l['reason'][:100]}")
    razones = " ".join(l["reason"] for l in d["leads_not_pursued"]).lower()
    print()
    if "no estuvo disponible" in razones or "no se pudo contactar" in razones:
        print("   >> El modelo no respondio. Revisa que Ollama este corriendo:")
        print("        ollama ps        # deberia listar gemma3:12b")
        print("        ollama serve     # si no esta levantado")
    elif "sin modelo" in razones:
        print("   >> Corriste con --sin-modelo: las etapas deterministas no emiten findings.")
        print("      Vuelve a correr sin esa bandera para que Gemma investigue.")
    elif "validador rechazo" in razones:
        print("   >> Gemma si acuso, pero el validador tumbo la acusacion (es su trabajo).")
        print("      El motivo exacto esta arriba; eso es senal honesta, no una falla.")
PY
echo
echo "Listo. Refresca http://localhost:5173 (no hace falta reiniciar npm run dev)."
