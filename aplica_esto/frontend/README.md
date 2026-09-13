# CLAUDIUS MAXIMUS · Frontend

UI del auditor forense. Team CLAUDIUS MAXIMUS · HackMTY 2026 · Infosys Track.

## Stack

Vite + React 18 + TypeScript + Tailwind CSS + shadcn/ui + Zod + reactflow + recharts + framer-motion.

Design system persistido en `../design-system/claudius-maximus-forensic-auditor/MASTER.md`.

## Contrato con el backend

El frontend **no importa código Python**. Hay dos modos, y funciona en los dos.

**Con servidor local (recomendado).** `python3 -m src.api` expone el
pipeline en `http://127.0.0.1:8000` sin dependencias extra (biblioteca
estándar: el proyecto presume de una sola dependencia de runtime y eso no
se cambia por tres endpoints). Con él corriendo, la pantalla Upload
investiga el estate sin salir del navegador y el dashboard se actualiza
solo:

- `GET /api/health` — si Ollama responde y si el modelo está instalado
- `POST /api/investigate` — cuerpo = el `.db` crudo; devuelve un `job_id`
- `GET /api/jobs/{id}?desde=N` — progreso en vivo y, al terminar, el submission

**Sin servidor.** Lee archivos estáticos, como siempre:

- `out/submission.json` — schema oficial de Infosys (`docs/spec/submission_schema.json`)
- `out/events.jsonl` — un JSON por línea, timeline del run (opcional, con `--events`)
- `eval/runs/sweep_*.csv` — batch de sweeps

Vite sirve `frontend/public/` como `publicDir`, así que esos archivos van
en `frontend/public/out/`. `bash scripts/refresh_frontend_snapshots.sh` los
copia desde `out/`; el servidor local escribe ahí también, para que un
reload conserve los hallazgos.

## El estate vive en el navegador

La pantalla Upload construye el `.db` con sql.js y **lo conserva** (en
IndexedDB, porque el flujo sin servidor exige recargar la página). Eso es
lo que permite que un exhibit se abra al registro real de la base en vez de
a la nota que escribió el propio modelo, y que la reconciliación de pesos
se recalcule a la vista — ver `src/lib/estateStore.ts`. Sin estate cargado
la UI sigue mostrando los hallazgos, pero dice claramente que no puede
comprobarlos.

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
