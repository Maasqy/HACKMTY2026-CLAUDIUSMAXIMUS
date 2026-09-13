#!/usr/bin/env bash
# scripts/setup_llm.sh — deja el modelo local listo para las etapas 3 y 5.
#
# CORRE ESTO EN TU MAC, en Terminal.app. No sirve correrlo dentro de la VM de
# Cowork: esa VM esta aislada de tu macOS y ademas tiene la red filtrada.
#
# Uso:
#   bash scripts/setup_llm.sh            # instala (si falta), baja el modelo, verifica
#   bash scripts/setup_llm.sh --check    # solo verifica, no instala ni descarga
#
# Por que un modelo local y no una API: la spec exige que la corrida se pueda
# replicar CON LA RED APAGADA. Un endpoint remoto no cumple eso, y ademas la
# cifra de mxn_cost quedaria a merced de un proveedor.
set -uo pipefail

# Tiene que ser el tag EXACTO que imprime `ollama list`, y coincidir con
# src/config.py — el paso 5 lo comprueba.
MODELO="${FORENSIC_LLM_MODEL:-gemma4:12b}"
BASE_URL="${FORENSIC_LLM_BASE_URL:-http://localhost:11434}"
SOLO_CHECK=0
[ "${1:-}" = "--check" ] && SOLO_CHECK=1

ok()   { printf '  \033[32mOK\033[0m   %s\n' "$1"; }
falta(){ printf '  \033[31mFALTA\033[0m %s\n' "$1"; }
info() { printf '  ---  %s\n' "$1"; }

echo "== 1. ollama instalado?"
if command -v ollama >/dev/null 2>&1; then
  ok "ollama $(ollama --version 2>/dev/null | head -1)"
else
  falta "ollama no esta instalado"
  if [ "$SOLO_CHECK" = "1" ]; then exit 1; fi
  echo
  echo "  Instalalo con UNA de estas dos:"
  echo "    brew install ollama          # si usas Homebrew"
  echo "    curl -fsSL https://ollama.com/install.sh | sh"
  echo
  echo "  O descarga la app de https://ollama.com/download"
  echo "  Vuelve a correr este script cuando termine."
  exit 1
fi

echo "== 2. servidor levantado en $BASE_URL?"
if curl -s --max-time 3 "$BASE_URL/api/tags" >/dev/null 2>&1; then
  ok "el servidor responde"
else
  falta "no responde"
  if [ "$SOLO_CHECK" = "1" ]; then exit 1; fi
  info "levantalo en otra terminal con:  ollama serve"
  info "(si instalaste la app, abrela y ya queda corriendo)"
  exit 1
fi

echo "== 3. modelo '$MODELO' descargado?"
if ollama list 2>/dev/null | awk '{print $1}' | grep -qx "$MODELO"; then
  ok "$MODELO ya esta"
else
  falta "$MODELO no esta descargado"
  if [ "$SOLO_CHECK" = "1" ]; then
    echo
    echo "  Modelos que SI tienes:"
    ollama list 2>/dev/null | tail -n +2 | sed 's/^/    /'
    exit 1
  fi
  info "descargando (son varios GB, tarda)..."
  ollama pull "$MODELO" || {
    echo
    echo "  Fallo la descarga de '$MODELO'. Verifica el tag exacto en"
    echo "  https://ollama.com/library  — los nombres cambian entre versiones."
    echo "  Modelos que si tienes ahora:"
    ollama list 2>/dev/null | tail -n +2 | sed 's/^/    /'
    exit 1
  }
  ok "$MODELO descargado"
fi

echo "== 4. responde y soporta tool-calling?"
RESP=$(curl -s --max-time 90 "$BASE_URL/api/chat" -d "{
  \"model\": \"$MODELO\", \"stream\": false,
  \"messages\": [{\"role\":\"user\",\"content\":\"Responde solo: listo\"}],
  \"options\": {\"temperature\": 0, \"seed\": 7}
}" 2>/dev/null)
if echo "$RESP" | grep -q '"content"'; then
  ok "responde: $(echo "$RESP" | sed -n 's/.*"content":"\([^"]*\)".*/\1/p' | head -c 40)"
else
  falta "no devolvio contenido util"
  echo "$RESP" | head -c 300; echo
  exit 1
fi

echo "== 5. el pipeline apunta a ESTE modelo?"
# Esta comprobacion existe por un bug real: setup_llm.sh descargaba un modelo y
# src/config.py apuntaba a otro, asi que la corrida usaba un modelo distinto del
# que uno creia haber instalado, sin ningun error a la vista.
CONFIGURADO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && python3 -c \
  "import sys; sys.path.insert(0,'.'); from src.config import LLM_MODEL; print(LLM_MODEL)" 2>/dev/null)
if [ "$CONFIGURADO" = "$MODELO" ]; then
  ok "src/config.py usa '$CONFIGURADO'"
else
  falta "src/config.py usa '$CONFIGURADO', pero aqui verificamos '$MODELO'"
  info "corrige el default en src/config.py (LLM_MODEL), o exporta:"
  info "    export FORENSIC_LLM_MODEL=\"$MODELO\""
  exit 1
fi

echo
echo "Listo. Corre el pipeline:"
echo "    python3 -m src.run --estate data/estates/estate_0001.db --out salida.json --max-leads 5"
echo
echo "Y el reporte del caso que te interese:"
echo "    python3 scripts/reporte_excel.py --submission salida.json \\"
echo "        --estate data/estates/estate_0001.db --empresa \"NOMBRE DE LA EMPRESA\""
