#!/usr/bin/env bash
# Deja el repo listo para la primera sesion de Claude Code.
# Uso: bash fix-repo.sh   (desde la raiz del repo)
set -euo pipefail

[ -d .git ] || { echo "Corre esto desde la raiz del repo." >&2; exit 1; }

echo "1. Carpetas"
mkdir -p docs/spec data/raw data/estates eval/answers eval/runs \
         estate_gen src/tools src/detectors src/scoring src/forensic \
         src/casefile src/metrics docs/archive

echo "2. El listado 69-B a donde lo busca el generador"
[ -f Listado_completo_69-B.csv ] && git mv Listado_completo_69-B.csv data/raw/ 2>/dev/null || true

echo "3. Referencias muertas en la capa .claude"
sed -i.bak 's/evidence-gatekeeper/challenger/g; s/ledger-investigator/investigator/g' \
    .claude/agents/*.md .claude/commands/*.md
sed -i.bak 's|docs/00-setup/08-CONTRATO-DATOS.md|docs/spec/submission_schema.json|g' \
    .claude/agents/*.md .claude/commands/*.md
rm -f .claude/agents/*.bak .claude/commands/*.bak

echo "4. Documentos que ya no aplican, al archivo"
for f in 03-SETUP-CLAUDE-CODE-ECC 04-PROMPTS-MAESTROS 06-FUENTES-DE-DATOS; do
  [ -f "docs/00-setup/$f.md" ] && git mv "docs/00-setup/$f.md" "docs/archive/$f.md" 2>/dev/null || true
done

echo "5. .gitignore"
cat > .gitignore <<'EOF'
__pycache__/
*.pyc
.venv/
venv/
.llm_cache/
out/
eval/runs/*.json
!eval/runs/.gitkeep
EOF
touch eval/runs/.gitkeep

echo "6. Constantes de negocio (un juez va a pedir abrir este archivo)"
[ -f src/config.py ] || cat > src/config.py <<'EOF'
"""Constantes de negocio del sistema forense.

Viven en codigo, nunca en un prompt. La especificacion de Infosys lo exige
explicitamente y un juez puede pedir abrir este archivo.
"""

# Limite de autorizacion de compra. Arriba de esto se requiere segunda firma.
APPROVAL_LIMIT_MXN = 50_000.00

# Tolerancia de reconciliacion entre peso_amount y la suma de exhibits citados.
PESO_TOLERANCE = 0.02

# Minimo de exhibits por acusacion.
MIN_EXHIBITS = 3

# Maximo de palabras de la narrativa de un finding.
MAX_NARRATIVE_WORDS = 150

# Tipos de esquema. Enum cerrado por la especificacion oficial.
SCHEME_TYPES = ("phantom_vendor", "kickback", "round_tripping",
                "threshold_splitting", "revenue_inflation")

# Tablas del estate que llevan monto, usadas para reconciliar.
AMOUNT_TABLES = {"invoices": "total", "bank_txns": "amount",
                 "purchase_orders": "amount", "contracts": "value"}

# Limites del loop de investigacion.
MAX_STEPS_PER_RUN = 60
MAX_LLM_CALLS_PER_RUN = 120
EOF

[ -f src/__init__.py ] || touch src/__init__.py
for d in tools detectors scoring forensic casefile metrics; do
  [ -f "src/$d/__init__.py" ] || touch "src/$d/__init__.py"
done

echo "7. El comando que tiene que existir"
[ -f src/run.py ] || cat > src/run.py <<'EOF'
"""Punto de entrada. La ruta del estate se recibe en tiempo de ejecucion.

    python3 -m src.run --estate data/estates/estate_0042.db --out submission.json
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--estate", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    if not args.estate.exists():
        raise SystemExit(f"No existe el estate: {args.estate}")

    started = time.time()

    # PENDIENTE: detectores -> leads -> investigator -> challenger -> validator
    findings: list[dict] = []
    leads_not_pursued: list[dict] = []

    submission = {
        "seed": args.seed,
        "findings": findings,
        "leads_not_pursued": leads_not_pursued,
        "run_metadata": {
            "llm_calls": 0,
            "mxn_cost": 0.0,
            "wall_clock_seconds": round(time.time() - started, 2),
            "cost_by_role": {},
            "deterministic": True,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(submission, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"{args.out}  findings={len(findings)}  leads={len(leads_not_pursued)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
EOF

echo
echo "8. Falta copiar a mano (los tienes descargados):"
miss=0
check() { [ -f "$1" ] && echo "   ok   $1" || { echo "   FALTA $1"; miss=1; }; }
check docs/spec/estate_schema.sql
check docs/spec/submission_schema.json
check docs/spec/ground_truth_schema.json
check docs/spec/case_file_structure.md
check docs/spec/results_table_template.csv
check validate_format.py
check estate_gen/generate_estate.py
check eval/harness.py
check EMPIEZA-AQUI.md

echo
if [ "$miss" = "1" ]; then
  echo "Copia los que faltan y vuelve a correr este script para verificar."
else
  echo "Todo en su lugar. Prueba de humo:"
  echo "  python3 estate_gen/generate_estate.py --seed 42 --schemes 5 --decoys 8 \\"
  echo "      --estate data/estates/estate_0042.db --answers eval/answers/gt_0042.json"
  echo "  python3 eval/harness.py reference --estate data/estates/estate_0042.db \\"
  echo "      --answers eval/answers/gt_0042.json --out eval/runs/reference_0042.json"
  echo "  python3 validate_format.py --submission eval/runs/reference_0042.json \\"
  echo "      --estate data/estates/estate_0042.db"
  echo "  python3 -m src.run --estate data/estates/estate_0042.db --out out/submission.json"
fi
