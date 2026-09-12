---
name: fraud-typologies
description: Las tipologias de fraude en alcance y sus senales observables en datos, mas las senales que parecen fraude y no lo son. Consultar al formar hipotesis o al disenar escenarios.
---

# Tipologias en alcance

## 1. Facturacion de operaciones simuladas

La empresa deduce CFDIs de un proveedor sin capacidad real de prestar el servicio.

Senales observables: proveedor en listado 69-B; conceptos genericos de servicios
profesionales; ausencia de contrato o entregable; alta reciente del RFC; concentracion
subita de gasto; facturas de monto identico repetido.

Se prueba atacando la materialidad.

## 2. Kickback via empresa fachada

Alguien con poder de compra dirige gasto a un proveedor controlado por el o por un
cercano, y parte del dinero regresa.

Senales observables: mismo autorizador en todas las operaciones del proveedor; domicilio
o apoderado compartido con un empleado; precio por encima de mercado; dinero que retorna
a una cuenta relacionada.

Se prueba con la relacion oculta mas el retorno del dinero.

## 3. Round-tripping

El dinero sale y regresa tras dos o tres saltos, para inflar ingresos o justificar salidas.

Senales observables: ciclos en el grafo de pagos; intermediarios sin funcion economica;
montos que se conservan casi intactos a lo largo de la cadena; tiempos cortos entre saltos.

Se prueba con el ciclo completo, salto por salto, con el id de cada movimiento.

# Senales que NO son fraude

Reglas de supresion. El agente debe conocerlas para no acusar a proveedores honestos.

- Proveedor nuevo con gasto alto: puede ser un proyecto nuevo legitimo.
- Montos redondos: comun en iguala mensual y en contratos de servicio.
- Pago por adelantado: legitimo en muchos giros.
- Concentracion en un solo proveedor: normal en industrias con pocos jugadores.

## PENDIENTE — ampliar con la entrevista al experto fiscal

Las senales falsas que mencione el Director de Finanzas se agregan aqui como reglas de
supresion. Esta seccion es la que evita falsas acusaciones y por lo tanto la que protege
el criterio Judgment.
