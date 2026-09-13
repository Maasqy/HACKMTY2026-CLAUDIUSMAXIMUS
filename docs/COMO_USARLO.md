# Como usarlo

Cuatro cosas distintas que la gente quiere hacer con esto, y el comando de cada una.

1. [Verificar que todo funciona](#1-verificar-que-todo-funciona)
2. [Ver por que el sistema decidio lo que decidio](#2-abrir-la-caja-negra)
3. [Meter datos propios desde Excel](#3-meter-datos-propios)
4. [Sacar el reporte de un caso y su trazabilidad](#4-un-caso-concreto-en-excel-y-su-trazabilidad)

Antes de nada, una vez:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
bash scripts/rebuild_estates.sh        # regenera las 200 estates de tuning
```

---

## 1. Verificar que todo funciona

```bash
bash scripts/verificar_todo.sh              # sin LLM, ~30 s
bash scripts/verificar_todo.sh --con-modelo # incluye Ollama + Gemma
```

Comprueba, en orden: dependencias, insumos del generador, que los dos CART
cargan y predicen sin sklearn, que el generador corre, que las etapas
deterministas producen leads, que el submission pasa `validate_format.py`
(el validador de los jueces), que el expediente forense se renderiza, y que
las herramientas de abajo funcionan.

Cada comprobacion existe porque esa cosa exacta ya se rompio alguna vez.

### La corrida de verdad

```bash
# solo etapas deterministas (SQLite -> reglas -> CART), sin LLM
python3 -m src.run --estate data/estates/estate_0001.db --out salida.json --sin-modelo

# pipeline completo: SQLite -> CART -> Gemma -> validador -> challenger
ollama serve &                                  # si no esta corriendo
python3 -m src.run --estate data/estates/estate_0001.db --out salida.json --max-leads 5

# el expediente forense (markdown + HTML) a partir del submission
python3 -m src.casefile --submission salida.json \
    --estate data/estates/estate_0001.db --out-dir expediente/
```

`salida.json` es el payload: `findings`, `leads_not_pursued` y
`run_metadata` (llamadas al LLM, costo, segundos). Es lo que consumiria una
interfaz web mas adelante.

---

## 2. Abrir la caja negra

`scripts/explicar.py` responde "¿por que esta entidad y no otra?".

```bash
# ranking completo de sospecha de una estate
python3 scripts/explicar.py --estate data/estates/estate_0001.db

# el detalle de una entidad
python3 scripts/explicar.py --estate data/estates/estate_0001.db \
    --entidad RFC:QYQ230920LR0
```

El detalle imprime las cuatro capas, en el orden en que el sistema las
aplica: las features que el modelo ve, cada regla determinista que disparo
con su evidencia (tabla y `record_id` reales, citables ante un auditor), la
prediccion del CART con sus probabilidades, y la aritmetica del score
—noisy-OR, factor por factor— hasta el numero final.

Para probar una hipotesis sin base de datos de por medio:

```bash
python3 scripts/explicar.py --features \
  '{"num_facturas": 8, "en_lista_69b": 1, "es_69b_definitivo": 1,
    "pct_concepto_generico": 0.9, "categoria": "Consultoria"}'
```

**El modelo clasifica ENTIDADES, no transacciones.** Sus features son
agregados sobre las 8 tablas de la estate: cuantas facturas emitio, que
porcentaje va sin orden de compra, si aparece en el 69-B, cuanto tarda en
cobrar. Una fila de Excel con "una transaccion" no tiene con que predecir.
Lo que se clasifica es el perfil acumulado de un proveedor o un cliente.

---

## 3. Meter datos propios

`scripts/excel_a_estate.py` convierte un Excel o unos CSV en una estate
SQLite valida. A partir de ahi todo lo demas funciona igual.

¿No tienes un Excel a la mano para probar? `scripts/generar_ejemplo_proveedores.py`
escribe uno de prueba con 6 proveedores, dos de ellos con un patron de
fraude sembrado a proposito (un `phantom_vendor` con un RFC real del 69-B,
y un `kickback` que retransfiere a su propio aprobador) para que el
pipeline tenga algo que encontrar:

```bash
python3 scripts/generar_ejemplo_proveedores.py     # -> mis_proveedores.xlsx
```

```bash
# 1. la plantilla con las columnas esperadas (una hoja por tabla)
python3 scripts/excel_a_estate.py --plantilla plantilla.xlsx

# 2. convertir y puntuar de una vez
python3 scripts/excel_a_estate.py --entrada mis_datos.xlsx \
    --salida data/estates/mi_estate.db --puntuar

# 3. el pipeline completo sobre esa estate
python3 -m src.run --estate data/estates/mi_estate.db --out salida.json
```

Acepta un `.xlsx` con una hoja por tabla, una carpeta de CSVs, o un solo
CSV de facturas. Los encabezados se reconocen en espanol o ingles, con o sin
acentos: `RFC Emisor`, `rfc_emisor` e `issuer_rfc` son la misma columna.
Tambien normaliza `$1,234.56`, `15/03/2026` y separadores `;`.

Lo minimo util es una hoja de facturas. Con `bank_txns` ademas se activan
los detectores de ciclos de transferencias y kickbacks; con
`purchase_orders`, los de fraccionamiento y solicitante = aprobador. El
script dice al final que tablas quedaron vacias y que deja de detectar cada
una.

### Lo que rellena y lo que no

Rellena solo lo deducible: los proveedores a partir de quien emitio cada
factura, el IVA al 16% cuando das el subtotal, y el cruce contra el listado
69-B **real** del SAT para los RFC que aparezcan en tu archivo. Cada relleno
se reporta en pantalla.

No inventa evidencia. Si no traes transferencias bancarias, `bank_txns`
queda vacia y esos detectores no disparan — en vez de fabricar movimientos
que nadie podria auditar. Por la misma razon, la regla de "facturas sin
respaldo" se abstiene cuando la estate no trae ninguna orden de compra ni
ningun contrato: ausencia de evidencia no es evidencia de ausencia, y
acusar ahi seria una falsa acusacion contra todos los proveedores a la vez.

Esa disciplina es la misma que sostiene el resto del sistema: un hallazgo
solo sobrevive si el validador determinista confirma cada `record_id` contra
SQLite y reconcilia el monto. Un `record_id` inventado se rechaza.

### Garantia de que el importador no deforma nada

`scripts/verificar_todo.sh` vuelca una estate generada a CSV, la reimporta
y exige que el ranking de sospecha salga **identico**, entidad por entidad y
score por score. Si el importador pierde o deforma un dato, esa comprobacion
falla.

---

## 4. Un caso concreto en Excel, y su trazabilidad

`scripts/reporte_excel.py` toma una corrida y saca el expediente en Excel.
Se le puede pasar **el nombre de la empresa**, no solo el RFC.

```bash
# todo lo de una corrida
python3 scripts/reporte_excel.py --submission salida.json \
    --estate data/estates/estate_0001.db --salida reporte.xlsx

# un caso, por nombre
python3 scripts/reporte_excel.py --submission salida.json \
    --estate data/estates/estate_0001.db --empresa "Servicios Preferentes"

# sin corrida previa: corre el pipeline y reporta de una vez
python3 scripts/reporte_excel.py --estate data/estates/estate_0001.db \
    --empresa "Servicios Preferentes"

# que empresas hay en esta estate
python3 scripts/reporte_excel.py --estate data/estates/estate_0001.db --listar-empresas
```

El nombre se busca sin importar acentos ni mayusculas y acepta un pedazo.
Si coincide con varias, el script las lista y pide elegir en vez de
adivinar. Tambien acepta el RFC directo.

### Las cinco hojas

| Hoja | Que trae |
|---|---|
| Resumen | empresa auditada, periodo, totales, metricas y embudo de la corrida |
| Hallazgos | una fila por acusacion: tipo, confianza, monto, regla, narrativa |
| Trazabilidad | la ruta del dinero paso a paso, con el registro bancario que prueba cada salto |
| Evidencia | cada exhibit con el **contenido crudo** de su fila en SQLite |
| Descartados | los leads que no se acusaron y la razon exacta de cada uno |

### La trazabilidad

Filtrando por una entidad, el script ademas imprime la cadena en la
terminal: la regla violada, la narrativa, cada salto del dinero con su
monto y su fecha, y la evidencia con una marca de si el registro existe de
verdad en la base.

```
  RUTA DEL DINERO
    1. la empresa
       └─ $117,879.83  2026-05-04   [EX-04: bank_txns/BNK-00127]
    → RFC:QYQ230920LR0
    2. RFC:QYQ230920LR0
       └─ $158,666.69  2026-05-06   [EX-05: bank_txns/BNK-00128]
    → EMP:0013 (Ana Sofia Ramirez (compras))
```

La cadena completa es **acusacion → exhibit_id → tabla y record_id → la
fila real**. Ningun eslabon se escribe a mano: la ruta se arma desde
`bank_txns`, no se le pide al modelo, porque un LLM narra un flujo de
dinero que se lee perfecto y no cuadra con la contabilidad. Y el validador
determinista ya confirmo que cada `record_id` existe y que los montos
reconcilian dentro del 2% antes de que el hallazgo se imprimiera.

Si la empresa que buscas **no** fue acusada, el reporte dice por que: que
senal la levanto, quien cerro el lead (investigator, validator o
challenger) y con que razon. Suele ser mas informativo que el hallazgo.

### El mismo caso, narrado y con diagrama

```bash
python3 -m src.casefile --submission salida.json \
    --estate data/estates/estate_0001.db --out-dir expediente/
```

Produce `case_file.md` y `case_file.html`. El HTML dibuja la ruta del
dinero como diagrama SVG —empresa → proveedor → empleado, con montos y
fechas en cada flecha— que es la version para enseñarle a un juez.

### Que modelo corre

`src/config.py` lee el entorno:

```bash
FORENSIC_LLM_MODEL=gemma3:12b python3 -m src.run --estate ... --out salida.json
```

Por defecto es `gemma3:12b`, el mismo que descarga `scripts/setup_llm.sh`.

El tag tiene que ser **exactamente** el que imprime `ollama list`: ollama no
resuelve nombres parecidos, y un tag inexistente no falla al arrancar sino
en la primera llamada al modelo. Para comprobarlo:

```bash
ollama list                       # el tag real, tal cual
bash scripts/setup_llm.sh --check # compara ese tag contra src/config.py
```

El paso 5 de ese script existe por un bug real: descargaba un modelo y
`src/config.py` apuntaba a otro, asi que la corrida usaba un modelo distinto
del que uno creia haber instalado, sin ningun error a la vista.

Cambiar de modelo cambia los hallazgos, asi que el tag queda registrado en
la corrida.
