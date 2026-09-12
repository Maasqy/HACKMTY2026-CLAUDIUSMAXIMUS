---
description: "Ataca el estado actual del proyecto o un expediente como lo haria el juez mas esceptico."
argument-hint: "[ruta al expediente, o vacio para atacar el proyecto completo]"
---

Invoca al subagente `judge-simulator` contra `$ARGUMENTS`.

Si el argumento esta vacio, que ataque el estado general del proyecto: arquitectura,
evaluacion, y la historia que vamos a contar en la demo.

Devuelve las respuestas que deberiamos tener listas, no solo las preguntas.
