# CLAUDIUS MAXIMUS · Frontend

UI del auditor forense. Team CLAUDIUS MAXIMUS · HackMTY 2026 · Infosys Track.

## Stack

Vite + React 18 + TypeScript + Tailwind CSS + shadcn/ui + Zod + reactflow + recharts + framer-motion.

Design system persistido en `../design-system/claudius-maximus-forensic-auditor/MASTER.md`.

## Contrato con el backend

El frontend **no importa código Python**. Consume archivos generados por `python -m src.run`:

- `out/submission.json` — schema oficial de Infosys (`docs/spec/submission_schema.json`)
- `out/events.jsonl` — un JSON por línea, timeline del run (opcional, con `--events`)
- `eval/runs/sweep_*.csv` — batch de sweeps

Vite sirve la raíz del repo como `publicDir`, así `fetch("/out/submission.json")` funciona directamente en dev.

## Correr

```powershell
cd frontend
npm install
npm run dev
```

Abre http://localhost:5173.

Si `out/submission.json` no existe, la UI muestra datos mock (ver `src/mocks/`).

## Aislamiento respecto a la rama `origin/modelo`

Esta carpeta no toca `../src/`, `../eval/`, `../estate_gen/` ni `../scripts/`. El único acoplamiento es leer archivos generados. Cuando se mergee `modelo` a `main`, hacer rebase de `feat/frontend` sobre `main` — cero conflictos esperados salvo `.gitignore` (2 líneas).

## Estado del scaffold

- [x] Fase 0 — config (Vite, Tailwind, TS, entry points)
- [ ] Fase 1 — types Zod + loaders + hooks + mocks
- [ ] Fase 2 — CaseFile route
- [ ] Fase 3 — FindingDetail + MoneyTrailGraph
- [ ] Fase 4 — LiveInvestigation + replay
- [ ] Fase 5 — LeadsLog + MetricsDashboard
- [ ] Fase 6 — pulido + a11y
