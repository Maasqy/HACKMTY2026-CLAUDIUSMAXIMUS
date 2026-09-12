# CLAUDE.md

Guía para Claude Code en este repositorio.
**Equipo CLAUDIUS MAXIMUS · HackMTY 2026 · Reto Infosys "The Forensic Auditor".**

## Qué construimos

Un programa que recibe la ruta de un estate SQLite con los libros de una empresa que nunca
ha visto y escribe un `submission.json` con los fraudes que encontró **y que puede probar**,
más los sospechosos que descartó y por qué.

```bash
python3 -m src.run --estate <ruta> --out submission.json
```

La ruta se recibe en tiempo de ejecución. Rutas hardcodeadas reprueban.

## La especificación oficial manda

Los archivos en `docs/spec/` son de Infosys y no se modifican. Ante cualquier duda de
formato, ellos deciden:

- `estate_schema.sql` — las ocho tablas del estate y sus nombres exactos de columna.
  Los jueces las leen directamente. No traducir, no renombrar.
- `submission_schema.json` — el formato de salida.
- `case_file_structure.md` — las secciones obligatorias del expediente.
- `validate_format.py` — validador oficial. Corre en el build; si sale distinto de cero,
  el build falla.

Los cinco tipos de esquema son un enum cerrado: `phantom_vendor`, `kickback`,
`round_tripping`, `threshold_splitting`, `revenue_inflation`.

## Invariantes — nunca los rompas

1. **Aislamiento del ground truth.** La cadena `ground_truth` no aparece en ningún archivo
   bajo `src/`. Los jueces corren
   `grep -r 'ground_truth' your_project/src/ --include='*.py'`. Si se filtra, Results se
   topa en 2 sin importar los números. El generador vive en `estate_gen/`, el arnés de
   evaluación en `eval/`. Ninguno de los dos se importa desde `src/`.
2. **Ninguna acusación sale sin validar.** Todo `record_id` citado debe existir en el
   estate; mínimo tres exhibits, al menos uno de una tabla con monto; `peso_amount`
   reconcilia con la suma por tabla dentro del 2%; `rule_broken` nombra una regla concreta,
   no un patrón estadístico; narrativa bajo 150 palabras; cada entidad acusada con al menos
   un exhibit que sustente su participación. Esto es código en `src/forensic/validator.py`,
   nunca un prompt.
3. **Acusar a un inocente cuesta tanto como no encontrar un fraude.** Los estates traen
   hasta diez señuelos: entidades que disparan un detector y están limpias. Ante la duda,
   el lead va a `leads_not_pursued` con su razón específica.
4. **Constantes en código.** Umbrales, tolerancias y límites viven en `src/config.py`.
   Un juez va a pedir abrir el archivo donde está definida la constante.
5. **Determinismo y replay sin red.** Misma semilla, mismo resultado. Toda llamada al
   modelo pasa por caché en disco, para poder reproducir una corrida con la conectividad
   apagada.
6. **Tres números siempre.** `llm_calls`, `mxn_cost`, `wall_clock_seconds` en
   `run_metadata` de cada corrida. "No sabemos" califica bajo en Feasibility.

## Estructura

```
estate_gen/    generador del estate y de la clave de respuestas (fuera de src)
eval/          arnés: submission de referencia y scorer (fuera de src, único que lee la clave)
src/
  config.py    todas las constantes de negocio
  tools/       consultas tipadas sobre el estate; devuelven evidencia citable con record_id
  detectors/   señales deterministas; producen leads, nunca acusaciones
  scoring/     modelo de leads (carga el modelo ya entrenado; no toca la clave)
  forensic/    loop de investigación + validator
  casefile/    render del expediente con el money trail como diagrama
  metrics/     contador de llamadas, costo y tiempo
data/estates/  los .db
eval/answers/  las claves de respuestas, en directorio distinto al de los estates
docs/spec/     el pack oficial de Infosys
```

## Cómo se evalúa

```bash
pytest
python3 validate_format.py --submission out/submission.json --estate <ruta>
python3 eval/harness.py score --submission out/submission.json \
    --answers eval/answers/gt_NNNN.json --estate <ruta> --csv
```

Semillas de tuning: 1–50. Semillas de reporte: 901–905, selladas, nadie las abre durante
el desarrollo. Ambos conjuntos se nombran en el pitch y deben ser disjuntos.

## Convenciones

- Python 3.11+, tipos en funciones públicas, `ruff` para formato.
- Los detectores y el validator siempre llevan tests. El loop se prueba con escenarios.
- Nunca inventes identificadores ni métricas. Si no está medido, escribe
  `PENDIENTE — medir con {script}`.
- Commits: `feat|fix|docs|eval|data(scope): mensaje`.
- `data/estates/` y `data/raw/` no se commitean pesados; se regeneran con el generador.

## Antes de decir que algo está terminado

- [ ] `pytest` verde
- [ ] `validate_format.py` sale cero
- [ ] El scorer produce la fila del results table
- [ ] La tasa de falsas acusaciones está medida. Objetivo: cero.
