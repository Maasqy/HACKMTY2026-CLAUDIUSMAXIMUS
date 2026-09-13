1. El síntoma inicial: 100% de accuracy en todo

Cuando entrenamos el primer CART sobre es_fraude (binario), los tres modelos (CART, RandomForest, GradientBoosting) dieron accuracy/F1 cercano a 100%. Eso, en cualquier ejercicio de ML, es una bandera roja — no una buena noticia. Un modelo perfecto casi siempre significa que el dataset tiene una fuga (leakage), no que el problema sea fácil.

2. Las tres hipótesis — probadas empíricamente, no aceptadas por argumento

Cuando propusiste tres explicaciones posibles, mi regla fue: cada hipótesis se prueba con un experimento controlado antes de tocar el generador, porque "creo que es X" y "es X" son cosas distintas y cada fix cuesta tiempo.

H1 (pocos registros, 240 filas): Regeneré 158 estates adicionales (41→199 estates, 240→4,776 filas) sin cambiar nada más, y reentrené. Accuracy se mantuvo en ~100%. Refutada — si fuera un problema de muestra pequeña, más datos habría bajado el overfitting; no bajó nada.
H2 (features que "delatan" directamente): Quité tiene_contrato, pct_facturas_ppd, dias_antiguedad_al_facturar y los one-hot de categoria (quedaron 20 features) y reentrené. Accuracy se mantuvo en ~99.9–100%. Refutada — si el problema fuera esas columnas específicas, quitarlas debía bajar el accuracy notablemente.
H3 (AMLSim subutilizado): Separé las features en dos grupos — "solo montos" (6 columnas) vs "solo proceso/documentación" (12 columnas) — y entrené cada grupo por separado. Ambos grupos solos llegaron a ~99.7–99.9%. Eso probó que el problema no era falta de realismo de AMLSim específicamente: cualquier subconjunto de features ya bastaba para separar perfecto, lo cual apunta a que el problema está en la estructura de los datos, no en qué feature se usa.
3. Diagnóstico real (primera ronda)

Con las tres hipótesis descartadas, miré las distribuciones reales de montos y fechas por clase (es_fraude=0 vs 1) y encontré que no se traslapaban en absoluto — fraude vivía en un rango de pesos y honesto en otro completamente distinto, igual con fechas de registro. Esto no es una señal estadística sutil, es una regla de construcción: el generador literalmente les daba bandas de números diferentes a cada clase. Cualquier árbol encuentra eso con un solo split.

Aplicaste el fix → compartí las distribuciones de montos (draw_amount, bandas BAND_SERVICIO_RECURRENTE/BAND_REVENUE) y de fechas (draw_registered_date) entre fraude y honesto, verifiqué que la reconciliación de pesos seguía en 0.00% (no rompí la lógica contable), regeneré las 200 estates y reentrené.

4. Seguía en 100% — pero por una razón nueva

Aquí es donde la metodología importa: no asumí que el fix no funcionó. Volví a mirar la distribución de CADA feature por clase, no solo montos. Encontré que pct_facturas_sin_pago_rastreable (facturas sin transferencia bancaria correspondiente) era exactamente 0.0 en las 800 filas de fraude, sin una sola excepción — varianza cero de un lado. Eso es la firma inconfundible de una regla de código, no de un patrón real: build_schemes() siempre generaba el bank_txn pareado a cada factura de fraude (porque el esquema de lavado lo necesita), mientras que build_background() solo pagaba una fracción aleatoria de las facturas honestas.

Cuando preguntaste "¿aumentar a 14 mil registros ayudaría?" — la respuesta usó el mismo principio del experimento H1: varianza cero no se diluye con más filas. Si un valor es SIEMPRE 0 en una clase y NUNCA 0 en la otra, tener 800 o 80,000 ejemplos de fraude no cambia que la regla siga siendo perfecta — se multiplica exactamente igual. Esto es matemáticamente distinto a "hay señal real pero poca muestra" (que sí mejora con más datos).

5. Fix dirigido a las dos features que pediste

Corregí pct_facturas_sin_pago_rastreable (di cobertura de bank_txn a los 6 decoys que nunca la tenían, y agregué ~12% de probabilidad de pago no rastreado dentro de los esquemas de fraude) y pct_po_mismo_requester_approver (agregué 8% de probabilidad de que el mismo empleado sea requester y approver en compras normales, no solo en el decoy dedicado). Verifiqué con estadísticas de media/desviación estándar antes de reentrenar — no me fié de la intuición, confirmé que ambas features ya no tenían varianza cero de un lado.

6. Seguía en 100% — pero ya no por una sola feature

Aquí cambié de herramienta de diagnóstico. En vez de seguir revisando feature por feature (whack-a-mole), calculé el AUC de cada feature individual por separado (ajustando un stump de profundidad 2 a cada columna sola). El máximo fue 0.77 — ninguna feature aislada era ya un separador perfecto. Pero luego medí accuracy de entrenamiento en función de la profundidad del árbol: con 1 split ya había 92% de accuracy, con 5 splits llegaba a 100%. Esa combinación de evidencia (ninguna feature sola es perfecta, pero pocos splits combinados sí) me dijo que el problema ya no era una fuga de una columna, sino que los 5 esquemas de fraude son "recetas" rígidas — cada instancia de phantom_vendor en las 200 estates es casi un clon de las demás, así que un árbol solo necesita cercar 5 regiones de space, no aprender un patrón difícil.

7. Tu corrección — el punto de inflexión

Aquí señalaste algo que yo no había considerado: dije "es_69b_definitivo tiene varianza cero del lado honesto, pero es razonable" — y tú me corregiste: el listado 69-B real del SAT no es binario fraude/no-fraude, tiene 4 categorías reales (Definitivo, Presunto, Desvirtuado, Sentencia Favorable), y dos de ellas (Desvirtuado, Sentencia Favorable) son ejemplos reales, confirmados por el gobierno, de contribuyentes investigados y exonerados — no decoys sintéticos, sino RFCs reales con esa situación. Yo estaba tratando "aparece en el 69-B" como sinónimo de sospechoso, cuando el propio listado ya distingue "sospechoso" de "investigado y limpio".

Antes de tocar código, verifiqué los valores reales en el CSV (no supuse la ortografía) y confirmé 4 categorías con conteos reales: Definitivo (11,917), Sentencia Favorable (1,666), Presunto (838), Desvirtuado (340). Te pregunté explícitamente qué debía ser el target porque cambiaba el objetivo del modelo, no era un ajuste menor — elegiste multiclase.

8. Rediseño del target

Separé el parsing en 4 estados reales, agregué build_sat_status_population() para plantar ~6 vendors reales por estate (2 de cada: desvirtuado, favorable, presunto) con comportamiento honesto normal — así cada clase tiene ejemplos reales a nivel de vendor con features completas, no solo una fila suelta en efos_list. En build_features.py, agregué la etiqueta situacion_sat — y excluí explícitamente en_lista_69b y es_69b_definitivo como features, porque son literalmente el mismo lookup que produce la etiqueta (es_69b_definitivo es idéntico al indicador one-hot de la clase "definitivo" — entrenar con eso sería el modelo leyendo la respuesta de una copia de sí misma).

9. El resultado ya es creíble

72–86% de accuracy según el modelo, con definitivo en 100% (explicable: sigue siendo el mismo texto "diversos" del phantom_vendor, una fuga que ya identificamos y no hemos tocado) pero desvirtuado/favorable/presunto con precision 0.20–0.43 — genuinamente difíciles de distinguir entre sí. Eso es exactamente lo que uno esperaría de un clasificador honesto: si una empresa fue exonerada o está bajo investigación sin resolver, su comportamiento financiero normal no debería delatarla con certeza.

10. Las curvas ROC

Como ya no hay una sola clase positiva, no hay una sola curva ROC — construí una curva one-vs-rest por clase (para ver cuál categoría es fácil vs difícil de detectar individualmente) y un promedio macro comparando los 3 modelos, usando roc_auc_score(..., multi_class="ovr") como la métrica agregada.

El hilo conductor en las 10 etapas: nunca acepté "ya se arregló" sin volver a medir, y cada vez que algo daba 100%, cambié de herramienta de diagnóstico (rangos → varianza por clase → AUC por feature → profundidad vs accuracy) en vez de repetir el mismo chequeo. Eso fue lo que permitió encontrar que el problema mutaba de "rangos disjuntos" → "una regla de código determinista" → "recetas rígidas combinadas" → y finalmente que el marco binario mismo estaba mal planteado.
11. situacion_sat no era la tarea — cambio de target a scheme_type

Después de la etapa 9-10 (el modelo de situacion_sat ya era creíble, con las salvedades documentadas ahí), una revisión contra el spec oficial encontró dos problemas que invalidaban ese target como motor de detección, no como diagnóstico de modelado:

Primero, docs/spec/estate_schema.sql define efos_list.status como únicamente 'definitivo' | 'presunto'. 'Desvirtuado' y 'favorable' — las dos clases que hacían el problema multiclase interesante en la etapa 7 — existían en nuestros propios estates porque build_sat_status_population() las plantaba ahí, pero el estate de los jueces jamás va a tener esos dos valores en efos_list: el schema oficial no los admite. Un modelo con 5 clases donde 2 nunca aparecen en producción no es un modelo de 5 clases, es un modelo de 3 con ruido de entrenamiento que nunca se va a usar.

Segundo, aunque el modelo acertara perfecto: "¿qué situación tiene este proveedor ante el SAT?" no es la pregunta que califican los jueces. Califican "¿qué esquemas de fraude hay en este estate y puedes probarlos?" — Results se mide contra scheme_type (phantom_vendor, kickback, round_tripping, threshold_splitting, revenue_inflation), no contra el listado 69-B. situacion_sat es, en el mejor de los casos, una señal correlacionada con UNO de esos cinco esquemas (phantom_vendor), nunca el objetivo en sí.

Fix aplicado, en orden:
  a) efos_list vuelve a solo 'definitivo'/'presunto'. Los vendors 'desvirtuado'/'favorable' se conservan como material de decoy (son ejemplos reales de contribuyentes investigados y exonerados, siguen siendo útiles) pero viven en gt_NNNN.json → decoys, con signal "exonerated_69b_history" — nunca en efos_list.
  b) Se entrena un modelo NUEVO y separado — ml/train_scheme_type.py — sobre scheme_type como target primario: multiclase de los 5 valores oficiales + 'no_esquema', etiquetado a nivel entidad desde gt_NNNN.json["schemes"].
  c) ml/train_multiclase_sat.py (situacion_sat) se conserva pero se reencuadra explícitamente como señal SECUNDARIA — 3 clases únicamente (definitivo/presunto/no_listado) — nunca el motor de detección. Ver su docstring actualizado.
  d) src/scoring/leads.py deja explícito, en el docstring de Lead, que ninguno de los dos modelos produce una acusación — solo una razón más para que el investigator mire una entidad.

Un problema nuevo apareció al construir el dataset para (b): revenue_inflation planta su entidad acusada como CLIENTE (aparece como receiver_rfc en invoices — la empresa le vende a ese cliente y no le cobra), nunca como proveedor. ml/build_features.py originalmente solo iteraba sobre vendors, así que revenue_inflation salía con 0 filas etiquetadas — no era un problema de tuning, la entidad correcta ni siquiera estaba en la población de entrenamiento. Corregido extendiendo build_features.py (y su contraparte en vivo, src/scoring/features.py) para calcular features sobre la UNIÓN de proveedores y clientes, con un grupo de features de "lado venta" (facturas de ingreso sin cobro, días al cierre del periodo) poblado quando la entidad es cliente.

Métricas del modelo scheme_type sobre estates held-out del tuning set (seeds 1-200, split 150/50 por estate): 100% accuracy/F1/recall en las 6 clases. Igual que en la etapa 1 de este documento, un 100% es una bandera a documentar, no a celebrar sin más contexto — pero aquí la explicación es distinta a la de entonces: no hay fuga de una columna (en_lista_69b/es_69b_definitivo se dejan como features legítimas para este target, no leakage, porque no determinan por sí solas la etiqueta — hay vendors 'presunto' que NO participan en ningún esquema). La explicación real es la misma de la etapa 6: nuestro generador planta cada esquema como una "receta" — la topología, los montos y el patrón documental de cada scheme_type son casi clones entre las 200 estates — así que el árbol separa las 6 clases con pocos splits sin necesitar aprender un patrón sutil. Esto mide reconocimiento de plantilla sobre nuestro propio generador, no generalización a un estate independiente construido por alguien más.

Por eso el número que de verdad importa es el de la corrida de reporte sobre el holdout sellado (seeds 901-905, nunca tocado durante tuning ni entrenamiento — ver data/holdout_sealed/README.md y eval/holdout_sealed/report_seeds_901_905.csv): 30/30 esquemas plantados aparecieron dentro del top-N de leads de su propio estate, y 0/65 decoys se colaron en ese mismo top-N. Esa corrida se hizo una sola vez, después de terminar el modelo, y no se usó para ajustar nada — es la métrica que se reporta en el pitch, nombrando ambos conjuntos (tuning: 1-200, report: 901-905) como exige la spec.
