# Holdout sellado — seeds 911-915

Generado: ver `git log` / fecha de este commit.
Generador usado: estate_gen/generate_estate.py, version corregida (efos_list
solo definitivo/presunto — Correccion 2a; cycle_pesos_in_range + facturas de
cliente variables + decoy efos_definitivo_relacion_terminada — fix de
varianza-cero en scheme_type, ver SOBRE_EL_MODELO.md seccion 12).

## Por que 911-915 y no 901-905

Este repo ya tuvo un holdout sellado en seeds 901-905, reportado una vez
(30/30 esquemas, 0/65 decoys falsos) contra la version del generador ANTES
del fix de la seccion 12. Ese numero resulto estar inflado por tres
separadores perfectos de una sola feature (ver SOBRE_EL_MODELO.md). Al
corregir el generador, dos cosas dejan de ser validas sobre 901-905:

1. Los datos ya generados con el generador viejo no reflejan el pipeline
   actual — regenerarlos con el generador nuevo bajo los MISMOS seeds
   habria sido tecnicamente reproducible, pero quien ejecuta este cambio
   (yo) ya vio el resultado del primer reporte sobre esos seeds, así que
   reusarlos para "el" reporte final ya no habria sido ciego.
2. Por disciplina, no seeds vistas se retiran: 901-905 quedan retiradas de
   uso como report set. Este conjunto (911-915) es el que se reporta a
   partir de ahora.

## Regla

- **Tuning set**: seeds 1-200 (data/estates/, eval/answers/) — usado para
  entrenar y ajustar el modelo, los detectores y el agente.
- **Report set**: seeds 911-915 (data/holdout_sealed/, eval/holdout_sealed/)
  — usado UNICAMENTE para la corrida final que se reporta en el pitch.

## Estado: REPORTADO (una vez, autorizado) — ver eval/holdout_sealed/report_seeds_911_915.csv

Resultado:

  25/30 esquemas plantados dentro del top-N de leads de su propio estate (83%)
  5/70  decoys que aparecieron falsamente en ese top-N

Los 5 "faltantes" son EMP:0013 (lado empleado de kickback) en 4 de 5 seeds
— el modelo ML no puntua entidades EMP, solo RFC; el lado proveedor del
mismo esquema de kickback si aparece en el top en las 5 seeds. Los 5 falsos
positivos son, en las 5 seeds, el mismo decoy: efos_definitivo_relacion_terminada
(un RFC real 'definitivo' cuya relacion con la empresa termino antes del
periodo) — una tension esperada y documentada, no un bug: ese RFC es
razonablemente sospechoso por su historial real ante el SAT, aunque no
participe del fraude en esta estate.

**A partir de ahora este conjunto sigue sellado para cualquier otro uso.**
No se vuelve a correr nada contra el para "ver que tal va" el modelo o el
agente — si hace falta medir de nuevo durante el desarrollo, se usa el
tuning set (1-200). Si se necesita otra corrida de reporte final (por
ejemplo, tras cambios al agente/investigator), usar seeds nuevas (921-925)
y documentar aqui igual que esta, retirando 911-915.

## Regla original (para referencia)

- Nadie abre estate_09NN.db para explorar datos fuera de la corrida de
  reporte final.
- Nadie corre build_features.py, el modelo, ni ningun detector "para ver
  que pasa" contra estos archivos, fuera de esa corrida.
- Nadie lee gt_09NN.json fuera del harness de evaluacion final.

Si en algun momento alguien inspecciona el contenido de estos archivos
para otro fin, este conjunto queda contaminado: se borra y se regeneran
otras 5 estates con seeds nuevas para reemplazarlo.

## Verificacion de aislamiento (inspeccion de metadatos, no contenido, hecha antes de la corrida de reporte)

data/holdout_sealed/estates/estate_0911.db: efos_list statuses={'definitivo', 'presunto'} schema_ok=True
data/holdout_sealed/estates/estate_0912.db: efos_list statuses={'definitivo', 'presunto'} schema_ok=True
data/holdout_sealed/estates/estate_0913.db: efos_list statuses={'definitivo', 'presunto'} schema_ok=True
data/holdout_sealed/estates/estate_0914.db: efos_list statuses={'definitivo', 'presunto'} schema_ok=True
data/holdout_sealed/estates/estate_0915.db: efos_list statuses={'definitivo', 'presunto'} schema_ok=True
