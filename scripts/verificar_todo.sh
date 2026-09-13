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

echo "== 5a. el investigador nunca manda 'tools' a Ollama"
# Regresion real, con el modelo real: gemma3 (el que este proyecto usa) no
# esta en la lista corta de modelos a los que Ollama les soporta 'tools'
# nativo. Mandarselo de todos modos no degrada nada: 400 en CADA llamada,
# "does not support tools", cero findings, sin decir por que (hasta que
# tambien se arreglo client.py para mostrar el cuerpo del error). El fix fue
# describir las herramientas en el prompt y pedir el llamado como JSON
# plano — un servidor falso aqui comprueba que ESE payload nunca vuelve a
# llevar la llave 'tools', sin necesitar Ollama real para probarlo.
python3 - <<'PY' >/tmp/_nottools.log 2>&1
import json, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, ".")

visto_tools = {"si": False}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if "tools" in body:
            visto_tools["si"] = True
        out = {"es_fraude": False, "reason_if_not": "prueba"}
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"message": {"role": "assistant",
                         "content": json.dumps(out)}}).encode())

srv = HTTPServer(("127.0.0.1", 0), H)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

from src.forensic.client import LLMClient
from src.forensic.investigator import investigar_lead
from src.scoring import generar_leads
from src.tools import EstateDB

# cache_dir propio y desechable: si reutiliza .llm_cache/, un cache hit de
# otra comprobacion (mismo lead, mismos mensajes) hace que el mock nunca
# reciba el request y el check pase por razones equivocadas.
with EstateDB("data/estates/estate_0001.db") as estate:
    leads = generar_leads(estate)
    client = LLMClient(base_url=f"http://127.0.0.1:{port}",
                       cache_dir=tempfile.mkdtemp())
    investigar_lead(estate, leads[0], client)

srv.shutdown()
sys.exit(1 if visto_tools["si"] else 0)
PY
if [ $? = 0 ]; then
  ok "el investigador no manda 'tools' (funciona en gemma3 y en cualquier modelo)"
else
  malo "el investigador volvio a mandar 'tools' — revienta en gemma3 (ver /tmp/_nottools.log)"
fi

echo "== 5a2. cada llamada pide una ventana de contexto explicita (num_ctx)"
# Regresion real: sin esto Ollama usa su default (4096, confirmado con
# `ollama ps`), y un lead de varios turnos de tool-calling lo llena con el
# prompt de sistema + catalogo + resultados de herramientas — el modelo se
# queda sin presupuesto para terminar de escribir su conclusion y la
# respuesta se corta a la mitad del JSON. Se vio literal en .llm_cache/ en
# una corrida real: JSON valido hasta cierto punto y despues nada.
python3 - <<'PY' >/tmp/_numctx.log 2>&1
import json, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, ".")

visto = {"num_ctx": None, "llamadas": 0}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        visto["num_ctx"] = body.get("options", {}).get("num_ctx")
        visto["llamadas"] += 1
        out = {"es_fraude": False, "reason_if_not": "prueba"}
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"message": {"role": "assistant",
                         "content": json.dumps(out)}}).encode())

srv = HTTPServer(("127.0.0.1", 0), H)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

from src.config import LLM_NUM_CTX
from src.forensic.client import LLMClient
from src.forensic.investigator import investigar_lead
from src.scoring import generar_leads
from src.tools import EstateDB

# cache_dir propio (ver el comentario del check 5a): sin esto, el cache
# hit del check anterior le esconde el request al mock de este check.
with EstateDB("data/estates/estate_0001.db") as estate:
    leads = generar_leads(estate)
    client = LLMClient(base_url=f"http://127.0.0.1:{port}",
                       cache_dir=tempfile.mkdtemp())
    investigar_lead(estate, leads[0], client)

srv.shutdown()
sys.exit(0 if (visto["llamadas"] > 0 and visto["num_ctx"] == LLM_NUM_CTX) else 1)
PY
if [ $? = 0 ]; then
  ok "cada llamada pide num_ctx explicito (no depende del default de Ollama)"
else
  malo "num_ctx no viaja en el request (ver /tmp/_numctx.log) — riesgo de respuestas cortadas"
fi

echo "== 5b. reconciliacion de pesos: por tabla, no sumada entre tablas"
# Regresion real: el validador interno sumaba invoices + bank_txns como si
# fueran pesos distintos, cuando una factura y la transferencia que la pago
# son el mismo monto visto dos veces. Eso dejaba pasar aqui hallazgos que
# LUEGO fallaban validate_format.py (el validador de los jueces), que si
# reconcilia por tabla. Un finding que cita una factura y su pago, con
# peso_amount = solo el monto real (no el doble), debe validar OK; el mismo
# finding con peso_amount duplicado debe ser rechazado.
python3 - <<'PY' >/tmp/_recon.log 2>&1
import sys; sys.path.insert(0, ".")
from src.forensic.validator import validar
from src.forensic.investigator import FindingDraft
from src.tools import EstateDB

with EstateDB("data/estates/estate_0001.db") as estate:
    inv = estate._query("SELECT * FROM invoices LIMIT 1")[0]
    txn = estate._query("SELECT * FROM bank_txns LIMIT 1")[0]
    exhibits = [
        {"exhibit_id": "EX-01", "source_table": "invoices", "record_id": inv["uuid"], "note": "x"},
        {"exhibit_id": "EX-02", "source_table": "invoices", "record_id": inv["uuid"], "note": "x"},
        {"exhibit_id": "EX-03", "source_table": "invoices", "record_id": inv["uuid"], "note": "x"},
        {"exhibit_id": "EX-04", "source_table": "bank_txns", "record_id": txn["txn_id"], "note": "x"},
    ]
    base = dict(entity="RFC:X", entities=("RFC:X",), es_fraude=True,
                scheme_type="phantom_vendor", confidence="probable",
                rule_broken="x", narrative="x " * 5, reason_if_not="",
                exhibits=tuple(exhibits), tool_calls_made=())
    correcto = FindingDraft(peso_amount=float(inv["total"]), **base)
    doble = FindingDraft(peso_amount=float(inv["total"]) + float(txn["amount"]), **base)
    r1 = validar(estate, correcto)
    r2 = validar(estate, doble)
    ok1 = r1.ok or all("reconcilia" not in m for m in r1.motivos)
    sys.exit(0 if (ok1 and not r2.ok) else 1)
PY
if [ $? = 0 ]; then
  ok "peso_amount reconcilia por tabla (monto real pasa, monto duplicado se rechaza)"
else
  malo "reconciliacion de pesos incorrecta (ver /tmp/_recon.log) — riesgo de que"
  malo "  un finding pase aqui y falle validate_format.py"
fi

echo "== 5c. source_table: enum centralizado y listado explicito en el prompt"
# Regresion real: Gemma, trabajando en espanol, tradujo "bank_txns" como
# "transferencias" al citar un exhibit — el validador (correctamente) lo
# rechazo, pero el hallazgo se perdio. La causa era que el prompt solo
# mostraba UN ejemplo de source_table ("invoices"), nunca el enum completo.
# Este check exige que validator.py y prompts.py usen el MISMO objeto de
# src/config.py (no una copia que se pueda desincronizar) y que el prompt
# liste, literalmente, cada uno de los 8 nombres de tabla en ingles.
python3 - <<'PY' >/tmp/_srctab.log 2>&1
import sys; sys.path.insert(0, ".")
from src.config import SOURCE_TABLES as cfg_tables
from src.forensic.validator import SOURCE_TABLES as val_tables
from src.forensic.prompts import system_with_tools

assert val_tables is cfg_tables, "validator.py tiene su propia copia de SOURCE_TABLES"

spec = [{"function": {"name": "foo", "parameters": {"properties": {}, "required": []},
                       "description": "x"}}]
prompt = system_with_tools(spec)
faltan = [t for t in cfg_tables if t not in prompt]
sys.exit(1 if faltan else 0)
PY
if [ $? = 0 ]; then
  ok "source_table: un solo enum (src/config.py), listado explicito en el prompt"
else
  malo "source_table desincronizado o no listado en el prompt (ver /tmp/_srctab.log)"
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

# El reporte en Excel sobre el submission determinista (sin findings, pero con
# leads descartados): comprueba que el libro se arma y que la busqueda por
# nombre de empresa resuelve a un RFC.
NOMBRE=$(python3 -c "
import sqlite3
c=sqlite3.connect('data/estates/estate_0001.db')
r=c.execute('select legal_name from vendors where legal_name is not null limit 1').fetchone()
print(r[0] if r else '')" 2>/dev/null)
if python3 scripts/reporte_excel.py --submission /tmp/_v.json \
     --estate data/estates/estate_0001.db --empresa "$NOMBRE" \
     --salida /tmp/_rep.xlsx >/dev/null 2>&1 && [ -f /tmp/_rep.xlsx ]; then
  ok "reporte_excel.py: busca por nombre y escribe el libro"
else
  malo "reporte_excel.py fallo"
fi

# El generador de ejemplo debe producir un phantom_vendor y un kickback
# reconocibles SIN LLM (solo reglas + CART) — es la prueba de que alguien
# sin datos propios puede probar la arquitectura de punta a punta.
if python3 scripts/generar_ejemplo_proveedores.py --salida /tmp/_ejemplo.xlsx >/dev/null 2>&1 \
     && python3 scripts/excel_a_estate.py --entrada /tmp/_ejemplo.xlsx \
          --salida /tmp/_ejemplo.db --puntuar >/tmp/_ejemplo.log 2>&1 \
     && grep -q "RFC:AAA120730823.*phantom_vendor" /tmp/_ejemplo.log \
     && grep -q "RFC:SVP200815KL9.*kickback" /tmp/_ejemplo.log; then
  ok "generar_ejemplo_proveedores.py: el phantom_vendor y el kickback se detectan"
else
  malo "generar_ejemplo_proveedores.py no reproduce los casos sembrados (ver /tmp/_ejemplo.log)"
fi

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
