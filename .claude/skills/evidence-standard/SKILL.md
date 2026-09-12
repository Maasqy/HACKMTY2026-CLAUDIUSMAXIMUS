---
name: evidence-standard
description: El estandar interno de que cuenta como prueba y que no en este proyecto. Consultar antes de emitir, aprobar o redactar cualquier acusacion contra un proveedor.
---

# Estandar de evidencia

## La regla de las cuatro piezas

Una acusacion existe solo si tiene las cuatro. Si falta una, es un lead.

1. `regla_violada` — una regla concreta y nombrable, no una impresion.
2. `monto_mxn` — resultado de sumar documentos reales, no una estimacion.
3. `evidencia[]` — ids de documentos que existen en el patrimonio, cada uno con que prueba.
4. fecha — cuando ocurrio.

## Que SI es una regla violada

- Deduccion de CFDI emitido por contribuyente en listado definitivo del 69-B, publicado
  antes de la fecha de la operacion.
- Pago ejecutado sin CFDI correspondiente.
- Monto pagado distinto al monto facturado, sin nota de credito que lo explique.
- Dinero que sale de la empresa y regresa a ella a traves de intermediarios.

## Que NO es una regla violada

- "Proveedor nuevo con gasto alto." Es una senal, no una falta.
- "Montos redondos." Es una senal.
- "Servicios genericos sin descripcion detallada." Es una senal.
- "Score alto del modelo." No es evidencia de nada ante un tercero.

Las senales apuntan hacia donde investigar. Nunca sostienen una acusacion por si solas,
ni siquiera varias juntas.

## Modulacion por estatus 69-B

| Estatus | Que permite afirmar |
|---|---|
| ninguno | Nada por si mismo |
| presunto | Riesgo, con la palabra "presunto" explicita. No afirmar simulacion |
| definitivo | Afirmar que el SAT determino inexistencia de operaciones |
| desvirtuado / sentencia favorable | Nada. El proveedor gano. No acusar |

Y siempre: comparar fecha de publicacion contra fecha de la operacion. Si la empresa
opero antes de la publicacion, decirlo.

## PENDIENTE — llenar con la entrevista al experto fiscal

Estas secciones se completan con lo que responda el Director de Finanzas (ver
docs/00-setup/05-BRIEF-PARA-EXPERTO-FISCAL.md). Hasta entonces, no inventar contenido aqui.

- Que pruebas de materialidad acepta el SAT en la practica y cuales no sirven.
- Minimo de evidencia con el que un auditor real le reporta a direccion general.
- Senales que parecen fraude y casi nunca lo son (reglas de supresion).
- Umbrales de autorizacion tipicos, para modelar structuring.
