#!/usr/bin/env bash
# scripts/verificar_frontend_aplicado.sh
#
# Corre esto DESDE LA RAIZ DE TU REPO REAL (no en la nube, en tu Mac) para
# confirmar, archivo por archivo, si el codigo que te mande de verdad quedo
# en disco -- en vez de adivinar por que "sigue lo mismo" en el navegador.
#
# Uso:
#   bash scripts/verificar_frontend_aplicado.sh

set -u
FALTAN=0

check() {
  local archivo="$1" marcador="$2" descripcion="$3"
  if [ ! -f "$archivo" ]; then
    echo "  [FALTA]  $archivo no existe"
    FALTAN=1
    return
  fi
  if grep -q -- "$marcador" "$archivo" 2>/dev/null; then
    echo "  [OK]     $archivo ($descripcion)"
  else
    echo "  [VIEJO]  $archivo existe pero NO tiene '$marcador' -- es una version anterior"
    FALTAN=1
  fi
}

echo "=== Verificando que el codigo del flujo estate-en-navegador este aplicado ==="
check "frontend/src/App.tsx" "function VerificationPanel" "panel de reconciliacion de pesos"
check "frontend/src/App.tsx" "function EstateCard" "tarjeta de estate cargado en Overview"
check "frontend/src/App.tsx" "function ExhibitBadge" "insignia de verificacion por exhibit"
check "frontend/src/hooks/useSubmission.ts" "applySubmission" "puente para investigar sin recargar"
check "frontend/src/hooks/useSubmission.ts" "SubmissionSource" "banner de origen/frescura de los datos"
check "frontend/src/lib/loadSubmission.ts" 'cache: "no-store"' "fix del cache del navegador"
check "frontend/src/lib/estateStore.ts" "function reconcile" "reconciliacion de pesos en el navegador"
check "frontend/src/hooks/useEstate.ts" "EstateProvider" "estate persistido en IndexedDB"
check "frontend/src/lib/apiClient.ts" "startInvestigation" "cliente del servidor local"
check "frontend/src/lib/buildEstate.ts" "sql-wasm.wasm" "wasm de sql.js local (no CDN)"
check "frontend/src/routes/Upload.tsx" "InvestigatePanel" "boton de 'Run investigation'"
check "frontend/src/vite-env.d.ts" "vite/client" "tipos de Vite (requerido por buildEstate.ts)"
check "src/api.py" "ThreadingHTTPServer" "servidor local stdlib-only"

echo
echo "=== Verificando el submission.json que Overview/Case Files leen ==="
SUB="frontend/public/out/submission.json"
if [ ! -f "$SUB" ]; then
  echo "  [FALTA]  $SUB no existe -- por eso ves el mock (DEMO MODE), nunca tu corrida."
  FALTAN=1
else
  python3 -c "
import json
d = json.load(open('$SUB'))
print(f'  [OK]     $SUB tiene findings={len(d.get(\"findings\", []))}  leads_not_pursued={len(d.get(\"leads_not_pursued\", []))}')
if len(d.get('findings', [])) == 0:
    print('  [OJO]    findings=0 -- si esperabas ver Case Files con datos, este NO es el submission.json con los 2 findings que te mande.')
"
fi

echo
if [ "$FALTAN" -eq 0 ]; then
  echo "Todo el codigo esta aplicado. Si el navegador sigue sin mostrar nada:"
  echo "  1. Para npm run dev (Ctrl+C) y vuelve a correrlo -- Vite a veces cachea el public/ viejo."
  echo "  2. En el navegador, hard refresh: Cmd+Shift+R (Mac) para saltarte el cache del navegador."
  echo "  3. Abre la consola del navegador (F12) y ve si hay un error en rojo al cargar /case o /."
  echo "     Copiame ese error exacto -- con eso encuentro el bug real, en vez de adivinar."
else
  echo "Hay archivos viejos o faltantes (marcados arriba). Extrae aplica_esto.zip"
  echo "otra vez, sobre estas mismas rutas, y vuelve a correr este script para confirmar."
fi
