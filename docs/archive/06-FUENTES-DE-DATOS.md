# 06 — Fuentes de datos: hallazgos verificados y plan de ensamblado

Investigación hecha el 11 de septiembre de 2026. Verifiquen fechas y URLs antes de
descargar: el SAT reorganiza rutas con frecuencia.

## Veredicto rápido

| Fuente | Qué aporta | Costo de arranque | Veredicto |
|---|---|---|---|
| **Listado 69-B del SAT** | RFCs y razones sociales reales de EFOS, con estatus | Ya lo tienen en el repo | **Núcleo. Úsenla.** |
| **Catálogos y XSD del CFDI 4.0 (Anexo 20)** | Realismo del esquema de facturas | Bajo | **Núcleo. Úsenla.** |
| **IBM AML-Data** | Transacciones con tipologías de lavado **etiquetadas**, en CSV listo | Bajo — descarga directa | **Núcleo. Úsenla.** |
| IBM AMLSim | Generador de anillos y fachadas configurable | **Alto** — requiere Java, MASON, PaySim, compilación | Solo si sobra tiempo |
| CompraNet histórico (datos.gob.mx) | Nombres reales de proveedores, montos, fechas de contratos | Medio | Opcional, da realismo |
| Directorio de Proveedores Sancionados (SFP) | Segunda lista negra para cruce | Bajo | Opcional, buen detalle |
| IEEE-CIS (Kaggle) | Baseline de detección de anomalías en tarjetas | Bajo | **Poco útil aquí** |

---

## Detalle por fuente

### 1. Listado del artículo 69-B — SAT (núcleo)

El SAT publica en datos abiertos el listado de contribuyentes bajo el artículo 69-B del
CFF. <cite index="2-1">Cuando la autoridad fiscal detecta que un contribuyente emitió comprobantes sin contar con los activos, personal, infraestructura o capacidad material para prestar los servicios o producir y entregar los bienes que amparan tales comprobantes, o cuando no se le localiza, se presume la inexistencia de las operaciones amparadas</cite>.

- Portal: `omawww.sat.gob.mx/cifras_sat/paginas/datos/vinculo.html?page=ListCompleta69.html`
- Ustedes ya tienen `Listado_completo_69-B.csv` en el repo. Ese es el archivo correcto.
- **Lo crítico para el criterio Judgment:** el listado no es binario. Los estatus son
  <cite index="5-1">presunto (el SAT presume que emitió facturas falsas), definitivo (el SAT confirmó que las operaciones fueron inexistentes) y sentencia favorable (un tribunal ordenó al SAT eliminarlo del listado)</cite>. <cite index="5-1">El SAT actualiza los listados de manera periódica, generalmente cada trimestre, aunque puede hacerlo con mayor frecuencia cuando hay resoluciones nuevas</cite>.
- Modélenlo así: el estatus + la fecha de publicación contra la fecha de la operación
  determina la fuerza del hallazgo. Deducir de un proveedor que apareció en la lista
  **tres años después** no es lo mismo que deducir de uno que ya estaba publicado.
- Hay una asimetría que vale mencionar en el pitch: <cite index="6-1">las EDOS tienen un plazo de 30 días posteriores a que se publique como definitivo el estatus de una EFOS con la que hayan operado</cite>. Ese reloj es el dolor real del cliente.

### 2. CFDI 4.0 / Anexo 20 (núcleo)

- XSD base: `http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd`
- <cite index="23-1">A partir del 1 de abril de 2023 la única versión válida es la 4.0. La versión 4.0 incorpora como obligatorios el régimen fiscal y el domicilio fiscal del receptor, y añade el campo de exportación</cite>.
- No necesitan firmar ni timbrar nada. Necesitan que **los campos y catálogos sean
  reales**: `UUID`, `RFC` emisor/receptor, `Fecha`, `SubTotal`, `Total`, `FormaPago`,
  `MetodoPago`, `UsoCFDI`, `ClaveProdServ`, `TipoDeComprobante`, `RegimenFiscal`.
- Señal de humo clásica y fácil de modelar: `ClaveProdServ` genérica de servicios
  profesionales + `MetodoPago` PUE + montos redondos + sin contrato ni entregable.
- Si necesitan XMLs de ejemplo válidos contra el XSD, hay colecciones públicas de
  ejemplos de CFDI 4.0 con valores de prueba.

### 3. IBM AML-Data (núcleo, en lugar de AMLSim)

Esta es la corrección más importante de esta investigación. El reto sugiere AMLSim, pero
AMLSim <cite index="13-1">es una aplicación Java que requiere MASON versión 18, Commons-Math 3.6.1 y compilar PaySim desde el repositorio</cite>. En un hackathon de 36 horas eso puede costarles media noche.

La alternativa del mismo IBM: **`IBM/AML-Data`**. <cite index="16-1">Los datos representan transacciones financieras —transferencias bancarias, compras, transacciones con tarjeta, cheques— donde la mayoría son legítimas y unas pocas representan lavado de dinero. Están en formato CSV y se generan con un modelo multiagente de mundo virtual, por lo que son completamente sintéticos y no se basan en ofuscar ni anonimizar individuos reales</cite>.

Traducción: CSV listo, con etiquetas, sin compilar nada, sin problema de privacidad.

Si de todos modos quieren AMLSim, lo que vale de ahí son las **tipologías**: <cite index="10-1">define patrones de transacciones de alerta como ciclos, fan-in/fan-out y redes bipartitas con relaciones no obvias</cite>. Pueden implementar esos patrones directamente en su propio generador en Python en una hora, sin tocar Java. Recomiendo esa ruta.

### 4. CompraNet histórico — datos.gob.mx (opcional, alto valor de realismo)

- Dataset: contratos y expedientes del sistema histórico de CompraNet. <cite index="35-1">Contiene contratos y expedientes de compras públicas de 2010 a 2022, con datos sobre proveedores, contratos, importes, tipo de moneda y fechas de duración</cite>.
- Para qué sirve: sacar **nombres de proveedores y distribuciones de montos reales** para
  que su empresa sintética no se vea como un `faker` de manual. Los jueces de Infosys
  trabajan con datos mexicanos; lo van a notar.

### 5. Directorio de Proveedores y Contratistas Sancionados — SFP (opcional)

- <cite index="33-1">Se publica en datos.gob.mx como listado de proveedores y contratistas sancionados, con actualización diaria</cite>, y <cite index="28-1">existe además el Directorio de Proveedores y Contratistas Sancionados con impedimento para presentar propuestas o celebrar contratos</cite>.
- Para qué sirve: demostrar que el agente **cruza múltiples fuentes de autoridad**, no
  solo una lista. Es un detalle pequeño que suena muy bien en la demo.

### 6. IEEE-CIS Fraud Detection (Kaggle) — probablemente no

El reto lo menciona como baseline de anomalías, pero es fraude de tarjeta de crédito
transaccional. Su estructura no se parece a un libro contable y no aporta a "seguir el
dinero". Úsenlo solo si quieren una línea base numérica de comparación en el reporte, y
aun así probablemente no valga las horas.

---

## Plan de ensamblado del patrimonio de datos

El reto dice literalmente que los equipos ensamblan el patrimonio a partir de estas
piezas. Así lo armaría yo:

```
suppliers.csv     ← nombres y RFCs: mezcla de CompraNet (limpios) + 69-B (sucios)
                    + fachadas inventadas con RFC válido en formato
cfdi.csv/.xml     ← esquema CFDI 4.0 real, catálogos reales del Anexo 20
ledger.csv        ← pólizas contables que referencian UUIDs de cfdi
bank.csv          ← movimientos; los flujos de fraude siguen las tipologías de AMLSim
                    (ciclo, fan-out, bipartita) implementadas en Python
ground_truth.json ← qué esquema se inyectó, qué proveedores, qué monto, qué documentos
```

### Lo que decide el resultado: el inyector de esquemas

Escriban un **generador de escenarios parametrizado**, no un dataset fijo. Debe poder
producir un caso nuevo con una semilla distinta en segundos, porque:

1. **Los jueces van a esconder un esquema fresco.** Si su agente solo funciona con el
   dataset que ustedes miraron, se cae en vivo. Necesitan un conjunto **hold-out** que
   nadie del equipo abre durante el desarrollo.
2. La métrica de "Results" es recall sobre datos no vistos. Sin generador no tienen forma
   de medirlo, y sin medirlo no pueden afirmarlo ante el jurado.
3. **Incluyan escenarios sin fraude.** Un dataset limpio donde el agente debe terminar
   diciendo "no encontré nada que pueda probar" es la demostración más fuerte posible del
   criterio Judgment. Ningún otro equipo va a llevar eso.

### Reparto de dificultad de los escenarios

- **Fácil**: proveedor en lista 69-B definitiva, pagos directos, monto grande.
- **Medio**: fachada no listada, pero con pagos que no cuadran con facturas y un ciclo
  de dos saltos.
- **Difícil**: kickback con proveedor legítimo de fachada, montos por debajo del umbral
  de autorización, esparcido en 6 meses.
- **Trampa**: proveedor que se ve rarísimo (nuevo, montos redondos, servicios genéricos)
  pero es legítimo. Si el agente lo acusa, pierde.
