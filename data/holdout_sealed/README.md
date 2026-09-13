# Holdout sellado — seeds 901-905

Generado: ver `git log` / fecha de este commit.
Generador usado: estate_gen/generate_estate.py, version corregida (efos_list
solo definitivo/presunto, ver CORRECCION 2a).

## Regla

Este conjunto es el "report set" exigido por la spec:
"Report on seeds you did not tune on. Name both sets in the pitch.
They must be disjoint."

- **Tuning set**: seeds 1-200 (data/estates/, eval/answers/) — usado para
  entrenar y ajustar el modelo, los detectores y el agente.
- **Report set**: seeds 901-905 (data/holdout_sealed/, eval/holdout_sealed/)
  — usado UNICAMENTE para la corrida final que se reporta en el pitch.

## Estado: REPORTADO (una vez, autorizado) — ver eval/holdout_sealed/report_seeds_901_905.csv

La corrida de reporte autorizada ya se hizo (Correccion 3, paso 4): se
corrio `src.scoring.generar_leads()` sobre los 5 estates sellados y se
comparo contra sus gt_090X.json para el UNICO proposito de reportar
metricas en el pitch — no se reentreno ni reajusto nada con esos resultados.

Resultado (ver el CSV para el detalle por seed):

  30/30 esquemas plantados dentro del top-N de su propio estate (100%)
  0/65  decoys que aparecieron falsamente en ese top-N

Antes de esa corrida, la regla de abajo se sostuvo sin excepcion: nadie
abrio estos archivos, nadie entreno ni depuro contra ellos. La UNICA
inspeccion previa fue la verificacion de metadatos (schema-compliance de
efos_list, sin leer contenido de negocio) registrada mas abajo.

**A partir de ahora este conjunto sigue sellado para cualquier otro uso.**
No se vuelve a correr nada contra el para "ver que tal va" el modelo o el
agente — si hace falta medir de nuevo durante el desarrollo, se usa el
tuning set (1-200). Solo se vuelve a tocar 901-905 si se necesita otra
corrida de reporte final (y en ese caso, documentarla aqui igual que esta).

## Regla original (para referencia)

- Nadie abre estate_090X.db para explorar datos.
- Nadie corre build_features.py, el modelo, ni ningun detector "para ver
  que pasa" contra estos archivos, fuera de la corrida de reporte final.
- Nadie lee gt_090X.json fuera del harness de evaluacion final.

Si en algun momento alguien inspecciona el contenido de estos archivos
para otro fin (abre un .db, imprime un gt_*.json, corre el pipeline contra
ellos para depurar), este conjunto queda contaminado: se borra y se
regeneran otras 5 estates con seeds nuevas (p. ej. 911-915) para
reemplazarlo.

## Verificacion de aislamiento (inspeccion de metadatos, no contenido, hecha antes de la corrida de reporte)

Conteo de archivos y schema-compliance de efos_list corrido una sola vez,
inmediatamente despues de generar, sin leer ningun campo de negocio:
data/holdout_sealed/estates/estate_0901.db: efos_list statuses={'presunto', 'definitivo'} schema_ok=True
data/holdout_sealed/estates/estate_0902.db: efos_list statuses={'presunto', 'definitivo'} schema_ok=True
data/holdout_sealed/estates/estate_0903.db: efos_list statuses={'presunto', 'definitivo'} schema_ok=True
data/holdout_sealed/estates/estate_0904.db: efos_list statuses={'presunto', 'definitivo'} schema_ok=True
data/holdout_sealed/estates/estate_0905.db: efos_list statuses={'presunto', 'definitivo'} schema_ok=True
