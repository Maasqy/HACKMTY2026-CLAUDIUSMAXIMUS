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
# El runtime solo necesita requests: el CART se evalua desde JSON con la
# libreria estandar. sklearn/pandas/numpy son solo para reentrenar.
python3 -c "import requests" 2>/dev/null && ok "requests (unica dependencia del runtime)" \
  || malo "requests  (pip install -r requirements.txt)"
for m in sklearn pandas numpy; do
  python3 -c "import $m" 2>/dev/null && ok "$m (opcional, solo para reentrenar)" \
    || printf '  ---   %s ausente (opcional: solo hace falta para ml/)\n' "$m"
done

echo "== 2. insumos del generador en su sitio"
for f in data/raw/Listado_completo_69-B.csv AMLSim/sample/20K_cycle200.tgz docs/spec/estate_schema.sql; do
  [ -f "$f" ] && ok "$f" || malo "$f no existe"
done

echo "== 3. modelos entrenados"
for f in src/scoring/model/modelo_cart_scheme_type.json src/scoring/model/modelo_cart_situacion_sat.json; do
  [ -f "$f" ] && ok "$(basename "$f")" \
    || malo "$f  (exporta con: python3 ml/export_model_json.py)"
done
python3 -c "
import sys; sys.path.insert(0,'.')
from src.scoring.model import predict_scheme_type
lab, proba = predict_scheme_type({'num_facturas': 5, 'categoria': 'Consultoria'})
sys.exit(0 if lab and proba else 1)
" 2>/dev/null && ok "el modelo carga y predice sin sklearn" || malo "el modelo no predice"

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

echo "== 8. herramientas de inspeccion y de datos propios"
python3 scripts/explicar.py --estate data/estates/estate_0001.db --top 3 >/dev/null 2>&1 \
  && ok "scripts/explicar.py corre" || malo "scripts/explicar.py fallo"
# Ida y vuelta: vuelca una estate a CSV, la reimporta y exige el MISMO ranking.
# Si el importador pierde o deforma un dato, los scores cambian y esto falla.
python3 - <<'PY' >/tmp/_imp.log 2>&1
import csv, sqlite3, subprocess, sys, tempfile
from pathlib import Path
d = Path(tempfile.mkdtemp())
con = sqlite3.connect("data/estates/estate_0001.db"); con.row_factory = sqlite3.Row
for t in ("vendors","invoices","ledger","bank_txns","purchase_orders","contracts","employees","efos_list"):
    rows = con.execute(f"select * from {t}").fetchall()
    if not rows: continue
    with open(d / f"{t}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(rows[0].keys())
        for r in rows: w.writerow([r[c] for c in rows[0].keys()])
subprocess.run([sys.executable, "scripts/excel_a_estate.py", "--entrada", str(d),
                "--salida", str(d / "rt.db")], check=True, capture_output=True)
sys.path.insert(0, ".")
from src.scoring import generar_leads
from src.tools import EstateDB
def ranking(p):
    with EstateDB(p) as e:
        return [(l.entity, l.score) for l in generar_leads(e)]
a, b = ranking("data/estates/estate_0001.db"), ranking(d / "rt.db")
sys.exit(0 if a == b else 1)
PY
[ $? = 0 ] && ok "excel_a_estate.py: ida y vuelta reproduce el ranking exacto" \
  || malo "excel_a_estate.py deforma los datos (ver /tmp/_imp.log)"

if [ "$CON_MODELO" = "1" ]; then
  echo "== 9. modelo local (Ollama)"
  bash scripts/setup_llm.sh --check >/dev/null 2>&1 && ok "modelo disponible" \
    || malo "modelo no disponible (bash scripts/setup_llm.sh)"
  echo "== 10. pipeline COMPLETO con LLM"
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
