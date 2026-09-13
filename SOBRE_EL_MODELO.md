
12. El ROC de la etapa 11 tampoco era de fiar — otra vez varianza cero, esta vez en tres esquemas distintos

Al revisar el ROC de scheme_type con el mismo escepticismo que en la etapa 6 (un AUC de 1.0 en las seis clases es una bandera, no un logro), repetí el chequeo de "rango sin traslape por clase" de esa etapa. Encontré tres separadores perfectos, cada uno un artefacto del generador distinto — no señal real:

  - phantom_vendor / es_69b_definitivo: el generador solo escribe efos_list.status='definitivo' para el vendor phantom; ningún otro vendor llega nunca a 'definitivo'. La feature identificaba el esquema con 100% de certeza por construcción, no por comportamiento.
  - revenue_inflation / num_facturas_venta: los clientes de fondo recibían exactamente 1 factura cada uno (un client_rfc nuevo por factura), mientras revenue_inflation siempre planta 3-5 facturas al mismo cliente — rango 0-1 contra 3-5, sin traslape.
  - round_tripping / monto_promedio_factura: el mismo bug de banda-disjunta de las etapas 3-4, reintroducido en una ruta distinta. cycle_pesos(scale=...) multiplicaba montos crudos de AMLSim por un scale arbitrario sin pasar por el helper amounts_in_range ya corregido, dejando los montos de round_tripping en 972,912-1,735,989 pesos mientras todo lo demas (fraude u honesto) caia entre 0 y ~174,000.

Peor aun: al investigar round_tripping encontre que AMLSimSeed.__init__() nunca recibe el seed de la estate — recorre siempre el mismo archivo de muestra y encuentra el mismo ciclo fijo (cycle_amounts = [334.92, 165.16, 18.23]) en las 200 estates. Cualquier transformacion afin de esa lista fija da el MISMO resultado en las 200 estates — confirme que monto_promedio_factura de round_tripping era, literalmente, la constante 232000.0 en las 200 estates, sin excepcion.

Fixes aplicados:
  - cycle_pesos_in_range(rng, n, low, high) reemplaza la transformacion afin fija: ancla el primer eslabon con un monto real de AMLSim normalizado a la MISMA banda que cualquier otra factura (via amounts_in_range, que si usa el rng de la estate), y encadena los siguientes eslabones con una variacion de +-15% (representa comision/perdida en cada salto) en vez de una lista fija de 3 valores. round_tripping ahora varia por estate (152 valores distintos en 200 estates) y su rango se traslapa con el resto.
  - Los clientes de fondo ahora reciben una cantidad VARIABLE de facturas (1-5, sobre ~14 clientes en vez de 25 clientes de 1 factura fija), asi que "cuantas facturas tiene este cliente" ya no separa perfecto a revenue_inflation.
  - Se planta un decoy nuevo (efos_definitivo_relacion_terminada): un segundo RFC real 'definitivo', pero cuya relacion comercial termino antes del periodo auditado (cero facturas/POs/pagos en el periodo). Rompe el 1:1 entre es_69b_definitivo=1 y "es el esquema phantom_vendor activo".

Verificacion: repeti el chequeo de traslape por feature sobre las 200 estates regeneradas — cero separadores perfectos restantes. Reentrene scheme_type: CART bajo de 100% a 99.79% accuracy (recall macro 99.96%, revenue_inflation en precision 0.91 en vez de 1.0 — la primera confusion real del modelo). situacion_sat se mantuvo igual (no toca estas tres features).

El reporte final sobre el holdout sellado tambien se repitio, con seeds NUEVAS (911-915, no 901-905): al haber visto ya el resultado del primer reporte y haber cambiado el generador, reusar 901-905 ya no habria sido un reporte ciego. Resultado, mas honesto que el 30/30 anterior: 25/30 esquemas plantados dentro del top-N (83%), 5/70 decoys falsos en ese top. Los 5 "faltantes" (EMP:0013, el lado empleado de kickback, en 4/5 seeds) son el lado del esquema que el modelo ML no puntua (solo entidades RFC reciben scheme_type) — el lado proveedor del mismo esquema si aparece. Los 5 falsos positivos son, en las 5 seeds, exactamente el decoy nuevo efos_definitivo_relacion_terminada: una tension real y esperada, no un bug — un RFC confirmado 'definitivo' por el SAT es razonablemente sospechoso aunque la relacion con esta empresa ya haya terminado, y es exactamente el tipo de caso que un auditor humano tambien revisaria antes de descartarlo. Ver eval/holdout_sealed/report_seeds_911_915.csv.

13. El ROC seguia mintiendo: AUC de 1.0 y lineas rectas

Revisaste las curvas de la etapa 12 y señalaste dos cosas: seguia saliendo AUC=1.0 en varias clases, y las curvas eran lineas rectas. Son dos problemas con causas distintas, y separarlos fue lo que permitio arreglarlos.

Las LINEAS RECTAS eran del modelo, no de los datos. El CART crecia hasta que cada hoja quedaba pura (ccp_alpha=0.0, 33 hojas), asi que predict_proba solo devolvia 0.0 o 1.0 — dos valores. Un ROC construido sobre un score de dos valores tiene exactamente tres puntos, asi que solo puede dibujarse como dos segmentos rectos: es geometricamente imposible que salga curvo, por bueno que sea el modelo. Lo confirme contando valores distintos de probabilidad por clase antes de tocar nada.

El AUC=1.0 era de los datos. Lo probe: al forzar hojas no puras (min_samples_leaf), el AUC se quedaba en 1.0 igual. Ningun ajuste del modelo puede bajar un AUC de 1.0 cuando las clases no se traslapan.

Tambien encontre un punto ciego en mi propio chequeo de la etapa 12. Ahi reporte "ningun separador perfecto" comparando cada clase contra todas las demas; eso ocultaba los casos donde DOS clases comparten el mismo valor constante. pct_concepto_generico valia exactamente 1.0 en phantom_vendor y en threshold_splitting, y exactamente 0.0 en todo lo demas — varianza cero de los dos lados, invisible para mi test.

Los fingerprints que quedaban, todos constantes en vez de distribuciones:
  - pct_concepto_generico: 1.0 en dos esquemas, 0.0 en todo lo honesto. Ningun proveedor honesto escribia jamas "diversos"/"varios".
  - pct_facturas_venta_sin_cobro: 0.0 en los 2,800 clientes honestos, sin una excepcion. Toda venta honesta se cobraba dentro del periodo, asi que cualquier factura sin cobrar era fraude por construccion.
  - num_facturas: round_tripping tenia EXACTAMENTE 1 factura en las 200 estates.
  - pct_po_mismo_requester_approver: exactamente 1.0 en kickback y threshold_splitting.

Fixes, todos en direccion de mas realismo contable, no de ruido artificial:
  - Un 25% de las facturas honestas usan texto generico y los esquemas un 80% (no 100%): una redaccion vaga es evidencia, no prueba. Ambos lados salen del mismo par de plantillas, solo cambia la probabilidad.
  - Los clientes honestos ya no pagan todo dentro del periodo: la probabilidad de cobro depende de que tan cerca del cierre se emitio la factura (45% dentro de los ultimos 30 dias, 92% antes). Tener cuentas por cobrar vivas al corte es contabilidad normal, no fraude.
  - El proveedor del ciclo de round_tripping tambien factura trabajo ordinario (2-5 facturas extra, fuera del peso_amount del esquema para que la reconciliacion siga exacta).
  - kickback y threshold_splitting firman igual solicitante/aprobador en ~70% de sus ordenes, no en el 100%.

Y una segunda tanda, despues de medir otra vez: los decoys "dificiles" estaban dibujados con parametros distintos a los del esquema que debian imitar, asi que siempre quedaba algun rasgo incidental que los delataba. Fueron cayendo uno por uno: pct_po_justo_bajo_umbral_50k (el decoy del flete ponia el monto en el SUBTOTAL, y al sumarle IVA la orden salia arriba del umbral — marcaba 0.0 y nunca competia), pct_facturas_ppd (el decoy tenia metodo_pago="PUE" fijo), dias_antiguedad_al_facturar (fechas de alta hardcodeadas de 2019-2023 en todos los decoys), num_contratos (el decoy siempre tenia contrato y el esquema casi nunca). La leccion general, que es la misma de la etapa 6: cada constante hardcodeada en un decoy termina siendo la feature que lo delata. Ahora los dos decoys gemelos (below_approval_threshold_pattern frente a threshold_splitting, y efos_definitivo_con_materialidad frente a phantom_vendor) se dibujan de las MISMAS distribuciones que su esquema en todo lo observable — banda de montos, conteo de ordenes, concentracion en el tiempo, metodo de pago, texto del concepto, fecha de alta, presencia de contrato. Lo unico que los separa es el ground truth, que es exactamente lo que debe ser un decoy.

Resultado, con 18 celdas (6 clases x 3 modelos): AUC maximo 0.9999, ninguno llega a 1.0, y el peor caso real es round_tripping en 0.92-0.96. El CART bajo de 100% a 84.6% de accuracy y el macro-F1 a 0.74; Bagging y Boosting quedan en 0.97 de accuracy. Esa brecha entre el arbol solo y los ensambles es informacion util para el pitch, no un defecto: aparece justo cuando los datos dejan de ser separables por reglas rigidas.

Sobre las lineas rectas: la solucion no fue solo min_samples_leaf. La busqueda de poda ahora rechaza cualquier ccp_alpha cuyo arbol no produzca al menos 4 valores distintos de probabilidad por clase (MIN_PROBA_VALUES_PER_CLASS), porque este modelo existe para RANKEAR leads y un estimador que solo dice 0 o 1 no sirve para ordenar nada. Hay que ser honesto sobre el limite: el ROC de un arbol siempre es una escalera — ahora tiene entre 4 y 34 peldaños por clase en vez de 2, mientras que Bagging (52-198 valores) y Boosting (152-1516) dan curvas suaves de verdad. Por eso ahora las graficas comparan los tres modelos en la misma figura, tanto en las matrices de confusion como en un panel de ROC por clase.

Un cambio que este rediseño hizo obligatorio, en src/scoring/leads.py: el score de un Lead era el PROMEDIO de las strengths de sus senales, y el promedio no premia la acumulacion — un proveedor honesto con una sola senal de 0.6 empataba con uno que cargaba tres senales de 0.6. Mientras cada senal era practicamente exclusiva de un esquema eso no se notaba (una sola senal ERA la prueba); al volver ambiguas las senales individuales, paso a ser el factor decisivo. Ahora es un noisy-OR: score = 1 - PRODUCTO(1 - strength_i), con las dos senales ML dentro del mismo producto. Cada senal independiente se come una fraccion de la duda restante, tres senales mediocres (0.5, 0.5, 0.4) llegan a 0.85 y una sola aparentemente fuerte (0.6) se queda en 0.60 — que es como razona un auditor, y sigue siendo una linea de aritmetica que un juez puede verificar a mano.

Reporte final sobre holdout sellado, otra vez con seeds nuevas (921-925; 911-915 se retiran porque ya vi su resultado y ademas el generador cambio):

  30/30 entidades plantadas aparecen en la lista de leads (100%)
  29/30 dentro del top-10 (97%)
  24/30 dentro del top-N estricto, N = numero de entidades plantadas (80%)
  6/70 decoys colados en ese top-N

Los 6 que salen del top-N son revenue_inflation (rank 7-16 en las 5 seeds) y un round_tripping. Que revenue_inflation baje es consecuencia directa y esperada del fix: ahora que los clientes honestos tambien tienen facturas sin cobrar al cierre, esa senal dejo de ser decisiva por si sola. Aparece igual en la lista, mas abajo, que es donde un auditor la revisaria despues de las evidentes. El 100% en top-N anterior (30/30 sobre 911-915) media un generador con fugas; este 80% mide deteccion real sobre datos donde ninguna feature sola resuelve el problema.
