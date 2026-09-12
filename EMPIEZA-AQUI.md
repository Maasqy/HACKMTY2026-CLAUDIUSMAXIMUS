# EMPIEZA AQUÍ

Este archivo reemplaza a todos los demás. Los otros documentos se mueven a
`docs/archive/` y no se leen hasta que alguien los necesite. Si algo no está aquí,
hoy no importa.

---

## El proyecto en una frase

Un programa que recibe la ruta de una base de datos con los libros de una empresa y
escribe un archivo JSON con los fraudes que encontró y que puede probar.

```
python3 -m src.run --estate data/estates/estate_0042.db --out submission.json
```

Ese comando es el proyecto. Todo lo que hacemos existe para que ese comando funcione.

---

## Las cuatro cajas

| Quién | Recibe | Entrega |
|---|---|---|
| **Persona 1** | nada | `estate_0042.db` — los libros, con fraudes escondidos |
| **Persona 2** | `estate.db` | `leads.json` — lista de sospechosos con su razón |
| **Persona 3** | `leads.json` | `submission.json` — acusaciones probadas |
| **Santi** | `submission.json` | `case_file.md` — lo que lee el juez |

Nadie necesita saber cómo funciona la caja de al lado. Solo el archivo que entra y el
que sale.

---

## Qué hace cada quien HOY

### Persona 1 — los datos

Ya te di el generador funcionando. Tu trabajo hoy es correrlo y sellar las pruebas.

```bash
python3 estate_gen/generate_estate.py --seed 42 --schemes 5 --decoys 8 \
  --estate data/estates/estate_0042.db --answers eval/answers/gt_0042.json
```

**Terminado hoy cuando:** existen seis archivos `.db` (uno para trabajar, cinco para
probar con semillas 901 a 905) y están commiteados.

Regla única: los cinco de prueba **nadie los abre**. Ni para depurar.

### Persona 2 — los sospechosos

Escribe un script que lea el `.db` y escupa una lista de sospechosos. Empieza con **un
solo detector**, el más tonto que existe:

> ¿Hay algún proveedor en la tabla `efos_list` que aparezca en la tabla `invoices`?

Eso es todo. Un SELECT con un JOIN. Cada resultado se escribe como:

```json
{"entity": "RFC:LET1202152A1", "signal": "efos_list_match",
 "reason": "Proveedor en listado 69-B definitivo con 8 facturas por 2,734,344.90 MXN",
 "invoices": ["..."], "amount": 2734344.90}
```

**Terminado hoy cuando:** `leads.json` existe y tiene al menos un sospechoso real.
Mañana agregas más detectores y el modelo.

### Persona 3 — las acusaciones

Escribe un script que lea `leads.json` y escriba `submission.json` con el formato de
`submission_schema.json`. Hoy **sin agente y sin LLM**: convierte cada lead en un finding,
buscando en el `.db` las facturas y transferencias que lo respaldan.

Antes de escribir cada finding, revisa cuatro cosas. Si alguna falla, el lead va a
`leads_not_pursued` en lugar de a `findings`:

1. ¿Los `record_id` que voy a citar existen de verdad en el `.db`?
2. ¿Tengo al menos tres exhibits?
3. ¿La suma de los montos citados es igual al `peso_amount` que reclamo (±2%)?
4. ¿Tengo una regla concreta violada, no una impresión?

**Terminado hoy cuando:** esto sale `PASS`:

```bash
python3 validate_format.py --submission submission.json --estate data/estates/estate_0042.db
```

Mañana ese script se convierte en el agente. Hoy es un `if`.

### Santi — el expediente

Escribe un script que lea `submission.json` y escriba un `.md` con las secciones de
`case_file_structure.md`. Para el flujo del dinero, genera Mermaid como texto.

**Terminado hoy cuando:** existe un `case_file.md` que abre en GitHub, se lee de corrido,
y muestra un diagrama del dinero.

---

## La regla que importa más que todas

**Acusar a un proveedor honesto cuesta tanto como no encontrar un fraude.**

Los jueces esconden hasta diez señuelos: proveedores que se ven culpables y están limpios.
Si dudan de si acusar o no, **no acusen**. El lead se va a `leads_not_pursued` con su
razón y eso suma puntos, no los resta.

---

## La otra regla

La palabra `ground_truth` no puede aparecer en ningún archivo dentro de `src/`. Los jueces
corren un grep. Si aparece, perdemos la mitad de un criterio sin importar qué tan bien
funcione el sistema.

Traducción práctica: el generador vive en `estate_gen/`, la medición en `eval/`. `src/` es
territorio del agente y ahí no entra la clave de respuestas.

---

## Cuándo se juntan

**Hoy en la noche.** Cada quien tiene su archivo generado, aunque sea feo. Nadie conectó
nada con nadie.

**Mañana a mediodía.** Los cuatro scripts corren en cadena con un solo comando y producen
un `submission.json` que pasa el validador. El recall va a ser pésimo y no importa: desde
ese momento toda mejora es medible.

**Mañana en la noche.** Se mide con los cinco hold-out, se llena la tabla de resultados,
se ensaya la demo. Se congela.

---

## Si algo se atora

Pregunta una sola cosa: *¿puedo generar mi archivo de salida aunque el contenido sea
malo?* Si la respuesta es no, eso es lo único que hay que arreglar. Si es sí, genéralo feo
y sigue.
