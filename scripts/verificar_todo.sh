#!/usr/bin/env bash
# scripts/verificar_todo.sh — comprueba que el proyecto corre de punta a punta.
#
# Existe porque este repo ya sufrio dos veces la misma clase de regresion: una
# ruta que apunta a un archivo que alguien movio, y que nadie nota hasta que
# la demo falla. Cada paso aqui es algo que ya se rompio en la practica.
#
#   bash scripts/verificar_todo.sh            # sin modelo (rapido, no requiere Ollama)
#   bash scripts/verificar_todo.sh --con-modelo
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

CON_MODELO=0
[ "${1:-}" = "--con-modelo" ] && CON_MODELO=1
FALLOS=0

ok()   { printf '  \033[32mOK\033[0m    %s\n' "$1"; }
malo() { printf '  \033[31mFALLA\033[0m %s\n' "$1"; FALLOS=$((FALLOS+1)); }

echo "== 1. dependencias de Python"
for m in requests sklearn pandas numpy; do
  python3 -c "import $m" 2>/dev/null && ok "$m" || malo "$m  (pip install -r requirements.txt)"
done

echo "== 2. insumos del generador en su sitio"
for f in data/raw/Listado_completo_69-B.csv AMLSim/sample/20K_cycle200.tgz docs/spec/estate_schema.sql; do
  [ -f "$f" ] && ok "$f" || malo "$f no existe"
done

echo "== 3. modelos entrenados"
for f in src/scoring/model/modelo_cart_scheme_type.pkl src/scoring/model/modelo_cart_situacion_sat.pkl; do
  [ -f "$f" ] && ok "$(basename "$f")" || malo "$f (reentrena: python3 ml/train_scheme_type.py)"
done
python3 -c "
import pickle, sklearn, sys
b=pickle.load(open('src/scoring/model/modelo_cart_scheme_type.pkl','rb'))
v=b.get('sklearn_version')
sys.exit(0 if v==sklearn.__version__ else 1)
" 2>/dev/null && ok "version de scikit-learn coincide con la del entrenamiento" \
  || malo "scikit-learn distinto al del entrenamiento (las predicciones pueden diferir)"

echo "== 4. el generador corre"
if python3 estate_gen/generate_estate.py --seed 1 >/dev/null 2>&1; then
  ok "estate_0001.db generado"
else
  malo "el generador fallo: python3 estate_gen/generate_estate.py --seed 1"
fi

echo "== 5. etapas deterministas (SQLite -> CART)"
if python3 -m src.run --estate data/estates/estate_0001.db --out /tmp/_v.json --sin-modelo >/dev/null 2>&1; then
  N=$(python3 -c "import json;print(len(json.load(open('/tmp/_v.json'))['leads_not_pursued']))" 2>/dev/null)
  [ "${N:-0}" -gt 0 ] && ok "$N leads generados" || malo "0 leads: el CART no esta puntuando"
else
  malo "el pipeline determinista fallo"
fi

echo "== 6. validador oficial de los jueces"
python3 validate_format.py --submission /tmp/_v.json --estate data/estates/estate_0001.db 2>&1 \
  | grep -q PASS && ok "submission conforme al formato" || malo "el submission no pasa validate_format.py"

echo "== 7. expediente forense"
if python3 -m src.casefile --submission /tmp/_v.json --estate data/estates/estate_0001.db \
     --out-dir /tmp/_vcf >/dev/null 2>&1 && [ -f /tmp/_vcf/case_file.md ]; then
  ok "case_file.md y case_file.html generados"
else
  malo "el renderizador del expediente fallo"
fi

if [ "$CON_MODELO" = "1" ]; then
  echo "== 8. modelo local (Ollama)"
  bash scripts/setup_llm.sh --check >/dev/null 2>&1 && ok "modelo disponible" \
    || malo "modelo no disponible (bash scripts/setup_llm.sh)"
  echo "== 9. pipeline COMPLETO con LLM"
  if python3 -m src.run --estate data/estates/estate_0001.db --out /tmp/_vf.json --max-leads 3 >/dev/null 2>&1; then
    ok "corrida completa"
    python3 validate_format.py --submission /tmp/_vf.json --estate data/estates/estate_0001.db 2>&1 \
      | grep -q PASS && ok "submission con findings reales pasa el validador" \
      || malo "el submission con LLM no pasa el validador"
  else
    malo "la corrida con LLM fallo"
  fi
fi

echo
if [ "$FALLOS" = "0" ]; then
  printf '\033[32mTODO OK\033[0m — el proyecto corre de punta a punta.\n'
  [ "$CON_MODELO" = "0" ] && echo "(sin probar el LLM; corre con --con-modelo cuando tengas Ollama)"
  exit 0
fi
printf '\033[31m%s comprobacion(es) fallaron.\033[0m Arregla lo de arriba y vuelve a correr.\n' "$FALLOS"
exit 1
