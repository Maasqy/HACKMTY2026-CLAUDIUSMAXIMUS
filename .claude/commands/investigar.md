---
description: "Corre una investigacion forense completa sobre un patrimonio de datos y produce el expediente."
argument-hint: "[ruta al directorio del escenario]"
---

Investiga el patrimonio en `$ARGUMENTS`.

Antes de empezar consulta las skills `evidence-standard`, `sat-69b-rules` y
`fraud-typologies`.

Procede asi:

1. Carga el patrimonio y reporta que tablas encontraste y cuantas filas. Si falta alguna,
   detente y dilo.
2. Corre los detectores deterministas. Reporta los leads ordenados por score, con su razon.
3. Delega en el subagente `investigator` el lead mas prometedor. Deja que declare
   hipotesis, que la confirmaria y que la mataria.
4. Usa `money-tracer` cuando haya que seguir un monto.
5. Antes de elevar cualquier hallazgo, invoca a `challenger`. Si degrada o
   rechaza, registra la razon y sigue.
6. Repite hasta agotar leads con score relevante o hasta el limite de pasos.
7. Delega en `case-writer` la redaccion del expediente.

NO mires `ground_truth.json` durante la investigacion. Solo despues, para reportar.

Si no encuentras nada que puedas probar, el resultado correcto es un expediente que lo
dice, con los leads que revisaste y por que ninguno sostuvo una acusacion.
