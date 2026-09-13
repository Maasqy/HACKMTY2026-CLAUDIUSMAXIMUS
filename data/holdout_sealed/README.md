# Holdout sellado — seeds 921-925

Generador: estate_gen/generate_estate.py, version con los fixes de
varianza-cero de SOBRE_EL_MODELO.md secciones 12 y 13 (efos_list solo
definitivo/presunto; montos de round_tripping en banda compartida; texto
generico, cobro de clientes, conteo de facturas y firma de ordenes como
distribuciones y no constantes; decoys gemelos dibujados de las mismas
distribuciones que su esquema).

## Por que 921-925

Es el tercer report set de este repo, y las dos rotaciones anteriores estan
documentadas a proposito:

  901-905  reportado una vez (30/30, 0/65) contra un generador con tres
           separadores perfectos de una sola feature. Retirado.
  911-915  reportado una vez (30/30 top-N, 0/70) contra un generador que
           todavia tenia cuatro fingerprints constantes. Retirado.
  921-925  ACTUAL.

La regla que se sigue en las dos rotaciones es la misma: una vez que vi el
resultado sobre unas seeds, esas seeds ya no sirven para un reporte ciego;
si ademas cambia el generador, los datos viejos tampoco representan el
pipeline actual. Se retiran y se generan otras.

## Regla

- **Tuning set**: seeds 1-200 (data/estates/, eval/answers/) — entrenar y
  ajustar modelo, detectores y agente.
- **Report set**: seeds 921-925 (data/holdout_sealed/, eval/holdout_sealed/)
  — UNICAMENTE la corrida final que se reporta en el pitch.

Ambos conjuntos son disjuntos y ambos se nombran en el pitch, como exige la
spec ("Report on seeds you did not tune on. Name both sets in the pitch.").

## Estado: REPORTADO (una vez, autorizado) — eval/holdout_sealed/report_seeds_921_925.csv

  30/30 entidades plantadas aparecen en la lista de leads   (100%)
  29/30 dentro del top-10                                    (97%)
  24/30 dentro del top-N estricto (N = entidades plantadas)  (80%)
   6/70 decoys colados en ese top-N

Se reportan las tres cifras a proposito. El top-N estricto es la medida mas
dura (exige que las 6 entidades plantadas ocupen los 6 primeros lugares);
"en la lista" es la que corresponde a como trabaja realmente el
investigator, que baja por los leads en orden. Las 6 entidades que salen
del top-N son revenue_inflation (rank 7-16 en las 5 seeds) y un
round_tripping: con clientes honestos que tambien dejan facturas sin cobrar
al cierre, esa senal dejo de decidir por si sola, que es justo lo que se
buscaba al corregir el generador.

**A partir de aqui este conjunto queda sellado.** Nada se vuelve a correr
contra el durante el desarrollo — para eso esta el tuning set. Si hace falta
otro reporte final (por ejemplo tras construir el investigator), se usan
seeds nuevas (931-935) y se documenta aqui igual que esto, retirando
921-925.

## Regla original (para referencia)

- Nadie abre estate_09NN.db para explorar datos fuera de la corrida final.
- Nadie corre build_features.py, el modelo ni ningun detector "para ver que
  pasa" contra estos archivos, fuera de esa corrida.
- Nadie lee gt_09NN.json fuera del harness de evaluacion final.

Si alguien los inspecciona para otro fin, el conjunto queda contaminado: se
borra y se regeneran otras 5 estates con seeds nuevas.

## Verificacion de aislamiento (metadatos, no contenido, antes de la corrida)

data/holdout_sealed/estates/estate_0921.db: efos_list statuses={'definitivo', 'presunto'} schema_ok=True
data/holdout_sealed/estates/estate_0922.db: efos_list statuses={'definitivo', 'presunto'} schema_ok=True
data/holdout_sealed/estates/estate_0923.db: efos_list statuses={'definitivo', 'presunto'} schema_ok=True
data/holdout_sealed/estates/estate_0924.db: efos_list statuses={'definitivo', 'presunto'} schema_ok=True
data/holdout_sealed/estates/estate_0925.db: efos_list statuses={'definitivo', 'presunto'} schema_ok=True
