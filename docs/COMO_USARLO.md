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

### Por que la corrida se queda "callada" varios minutos

Un modelo de 12B corriendo local puede tardar 10-40s por turno, y una
entidad puede necesitar varios turnos (pide una herramienta, recibe el
resultado, pide otra, concluye). Sin mas, la terminal se queda muda hasta
el `findings=N` final — varios minutos de silencio identicos a un cuelgue.

Por default, `python3 -m src.run` imprime el progreso a stderr en tiempo
real, uno por lead y uno por turno del modelo:

```
[   0.1s] lead 1/4: RFC:QYQ230920LR0 (score 0.9999, kickback)
[  18.4s]   lead 1/4: llamada #1 (18.3s): pide obtener_facturas({'rfc_emisor': 'QYQ230920LR0'})
[  41.2s]   lead 1/4: llamada #2 (22.8s): concluye (es_fraude=True)
```

Mientras esas líneas sigan apareciendo (aunque tarden), el proceso esta
vivo. Para confirmarlo desde otra terminal sin tocar la que esta corriendo:

```bash
ollama ps   # si muestra el modelo con % de GPU/CPU activo, sigue trabajando
```

`--silencioso` apaga esto (por ejemplo, para no ensuciar la salida en un
script que solo quiere el JSON final).

### Por que el investigador no usa el `tools` nativo de Ollama

Si cambias a otro modelo y de repente vuelves a ver `findings=0` con la
razon `"does not support tools"` en `leads_not_pursued`, es esto: Ollama
solo soporta su API de tool-calling nativa en una lista corta de modelos
(llama3.1, qwen2.5, un puñado mas). Mandarle `tools` a uno fuera de esa
lista no degrada nada — **400 en cada llamada**, sin excepcion.

Por eso el investigador (etapa 3) no usa `tools=`: describe las
herramientas en el prompt y le pide al modelo que las llame respondiendo
con un JSON plano (`{"tool": "...", "arguments": {...}}`), el mismo truco
que se usaba antes de que existiera function-calling nativo. Funciona con
cualquier modelo de chat, gemma3 incluido. El detalle esta en
`src/forensic/prompts.py` y `src/forensic/investigator.py`; el paso 5a de
`verificar_todo.sh` comprueba, con un servidor falso, que la llave `tools`
nunca vuelve a viajar en el request.

### Por que el modelo no escribe texto de comentario, solo JSON

Es a proposito, no una falla. Cada llamada al investigador se hace con
`LLMClient.chat(..., format="json")`, que le pide a Ollama forzar la
salida a JSON valido (funciona con cualquier modelo, a diferencia de
`tools=`), y el prompt del sistema lo pide explicito: "Responde SOLO con
este objeto JSON, sin texto alrededor". Un parrafo de comentario junto al
JSON es exactamente lo que rompe el parseo del siguiente turno, asi que
si ves solo el objeto `{"es_fraude": ...}` o `{"tool": ...}` y nada de
prosa alrededor, el modelo esta haciendo lo correcto. La narrativa legible
del caso no sale de un comentario libre: es el campo `"narrative"` dentro
de ese mismo JSON, y es lo que termina en el expediente.

### Por que un exhibit se rechazaba con "source_table no esta en el enum oficial"

Gemma trabaja en español, y en algún momento citó un exhibit con
`"source_table": "transferencias"` en vez de `"bank_txns"` — no inventó el
dato (el `record_id` era real), tradujo el *nombre de la tabla*. El
validador lo rechazó correctamente (`bank_txns` es el único valor válido
ahí), pero el hallazgo se perdía por una traducción, no por evidencia
mala.

El enum vive en un solo lugar, `SOURCE_TABLES` en `src/config.py`
(`ledger`, `invoices`, `bank_txns`, `vendors`, `efos_list`,
`purchase_orders`, `contracts`, `employees`), y ahora `validator.py` lo
importa de ahí en vez de tener su propia copia, y el prompt del
investigador (`src/forensic/prompts.py`) lo lista explícito, palabra por
palabra, con la instrucción de no traducirlo. El paso 5c de
`verificar_todo.sh` comprueba que ambos archivos usen el mismo objeto y
que los 8 nombres aparezcan, literales, en el prompt.

### Por que una respuesta se corta a la mitad del JSON ("respuesta no era JSON, reintentando")

Si ves ese mensaje en el progreso y quieres confirmar la causa, revisa
`.llm_cache/`: cada respuesta del modelo se guarda ahí tal cual llegó. Una
corrida real mostró varias respuestas que son JSON válido *hasta cierto
punto* y después nada — literalmente cortadas a media palabra, por ejemplo
terminando en `..."source_table": "bank_txns", "record_` sin cerrar
comillas ni llaves. No es el modelo escribiendo texto libre: es la
respuesta truncada antes de terminar.

La causa era la ventana de contexto. `ollama ps` reporta este modelo
corriendo con `CONTEXT 4096` (el default de Ollama si nadie pide otra
cosa). El investigador es un loop de varios turnos: el prompt de sistema,
el catálogo de herramientas, y cada resultado de herramienta (hasta 6000
caracteres, ver `MAX_TOOL_PAYLOAD`) se van acumulando en la misma
conversación. Para la llamada #5 o #6, eso ya ocupa buena parte de una
ventana de 4096 — y al modelo no le queda presupuesto para escribir una
conclusión completa con narrativa y 3+ exhibits, así que se corta.

La corrección: `src/forensic/client.py` ahora manda `num_ctx` explícito en
cada llamada (`LLM_NUM_CTX` en `src/config.py`, default 8192,
sobreescribible con `FORENSIC_LLM_NUM_CTX`) en vez de depender del default
de Ollama. El paso 5a2 de `verificar_todo.sh` comprueba, con un servidor
falso, que `num_ctx` siempre viaja en el request.
