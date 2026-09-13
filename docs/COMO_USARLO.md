# Como usarlo

Tres cosas distintas que la gente quiere hacer con esto, y el comando de cada una.

1. [Verificar que todo funciona](#1-verificar-que-todo-funciona)
2. [Ver por que el sistema decidio lo que decidio](#2-abrir-la-caja-negra)
3. [Meter datos propios desde Excel](#3-meter-datos-propios)

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
las dos herramientas de abajo funcionan.

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
