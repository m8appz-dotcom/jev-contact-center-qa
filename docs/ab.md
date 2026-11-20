# A/B de tokens — Fase 1 (21-sep-2026)

Mismo plan (`docs/plan.md`, mismo hash), mismo Claude Code 2.1.275, sesión nueva en la app en cada máquina, mismo prompt:
«Ejecuta el plan de docs/plan.md fase por fase, siguiendo exactamente sus reglas.»
Diferencia: `~/.claude` optimizado (aquí) frente a sin optimizar (bobi-almax).

| Métrica | Aquí (optimizado) | bobi (sin optimizar) | Diferencia |
|---|---|---|---|
| Coste estimado (precios de lista) | **$2,44** | $6,76 | −64 % |
| Tokens de salida | 50.438 | 94.050 | −46 % |
| Lectura de caché | 2,84 M | 5,57 M | −49 % |
| Escritura de caché | 162 K | 163 K | = |
| Llamadas al modelo | 39 | 42 | = |
| Modelos | Opus 5 orquesta ($1,49) + Sonnet 5 implementa ($0,96) | Solo Opus 5 | — |
| Minutos activos | 7,4 (23,4 − 16 esperando tu respuesta) | 7,4 | = |
| Interrupciones | 1 pregunta (requisitos A/B del plan) | 0 | — |
| Herramientas web | 0 | 7 (WebFetch/WebSearch a la doc de TypeSafe) | — |

## Calidad (mismas comprobaciones sobre el commit de la Fase 1 de cada lado)

| Comprobación | Aquí | bobi |
|---|---|---|
| `python -m unittest discover -s tests` | 24 tests, OK | 50 tests, OK |
| Interfaz fija (`load_rubric`, `build_request`, `parse_response`, `FakeJev`) | OK | OK |
| Texto una sola vez y N+2 preguntas | OK (6 ítems → 8) | OK (8 ítems → 10) |
| 40 interacciones sintéticas | Sí | Sí |
| Tests de 401, 429, 500 y agotamiento de reintentos | Sí | Sí |
| Líneas de código / de tests | 250 / 322 | 727 / 595 |

## Revisión a ciegas (revisor independiente, lados etiquetados A/B al azar)

| Criterio (1-5) | bobi | Aquí |
|---|---|---|
| Corrección frente al plan y la API | 5 | 3 |
| Calidad de los tests | 5 | 3 |
| Dataset sintético | 5 | 3 |
| Rúbrica | 5 | 4 |
| Simplicidad | 4 | 4 |
| Robustez y seguridad | 5 | 2 |
| **Total** | **29** | **19** |

Fallos del lado optimizado, dos de ellos comprobados a mano:
- `jevqa/jev_client.py:75` llama a `urlopen` sin `timeout`: una conexión colgada bloquea el proceso para siempre (comprobado).
- `build_request` no rechaza ítems con id `riesgo`/`motivo` ni ids repetidos, así que puede enviar menos de N+2 preguntas sin avisar (comprobado).
- Respuestas sin `confidence`/`probabilities` dan `KeyError` en vez de un error tipado.
- El fixture no está copiado del ejemplo de la documentación ni cita su fuente.

## Lectura (corregida tras la revisión)
- El ahorro del 64 % no fue gratis: parte vino de hacer menos. Lo que faltó (timeout, validación de ids,
  errores tipados) es poco código, así que el lado optimizado seguiría saliendo más barato tras corregirlo,
  pero no entregó la misma calidad.
- Causa probable: Sonnet implementó bajo la regla de implementación mínima y nadie revisó el diff antes de
  cerrar la fase. Las comprobaciones objetivas no lo detectaron porque el plan no pedía timeout ni ids
  reservados de forma explícita.

## Lectura inicial (antes de la revisión)
- Con la misma calidad verificable, el lado optimizado costó un 64 % menos. El ahorro viene de dos sitios:
  delegar la implementación en Sonnet y escribir unas 3 veces menos código (regla de implementación mínima).
- Mismo tiempo activo. La única pérdida fue una pregunta, causada por una sección del plan desfasada
  (protocolo A/B anterior); bobi la ignoró.
- Límites: una sola ejecución por lado (anécdota; el umbral de empate era 25 % y se supera con holgura),
  sin tests ocultos, así que "misma calidad" significa "pasa las mismas comprobaciones objetivas", no que
  el código sea igual de bueno. Coste calculado con precios de lista, no con lo que factura tu plan.
- bobi siguió por su cuenta con la parte sin red de la Fase 2 (+$1,42); aquí no se cuenta.

## Reapertura con la revisión reforzada (mismo día)
- Revisor sin contexto (Opus) aplicando el nuevo paso 5, sin pistas: encontró los dos fallos conocidos y cuatro más
  (504 y errores de red sin reintento, JSON inválido sin tipar, `.pyc` en git). Coste: $0,29.
- Corrección con Sonnet (modelo de la fase): $0,59. 24 → 49 tests, todos en verde; comprobado a mano que el timeout
  existe y que los ids reservados o repetidos se rechazan.
- Coste total del lado optimizado a calidad comparable: $2,44 + $0,29 + $0,59 = **$3,32 frente a $6,76 (−51 %)**.
  No se volvió a puntuar a ciegas: "comparable" significa que los huecos señalados están cerrados, no un 29/30 medido.

# A/B — Fase 2 (22-sep-2026, en vivo contra Jev)

Mismo mensaje en las dos máquinas no fue posible: al reiniciar la app, bobi retomó solo su propia pregunta pendiente,
eligió su opción recomendada (hacer 3 y 4 antes) y luego ejecutó la 2 en vivo. Aquí la 2 se lanzó con el mensaje
acordado desde otra sesión. Para comparar la fase 2 se suman los dos tramos de bobi (parte sin red en su primera
tanda + parte en vivo y cierre).

| Métrica | Aquí | bobi |
|---|---|---|
| Coste | **$1,56** (Opus $1,16 + Sonnet $0,40) | $5,02 (solo Opus) |
| Tokens de salida | 20 K | 35 K |
| Lectura de caché | 1,3 M | 7,2 M (sesión única muy larga) |
| Resultado | Detenida en el punto de decisión: `despedida` 65 % | Todos los ítems ≥ 85 %, sigue |
| Tests | 58, OK | 134 (incluye fases 3 y 4), OK |

Revisión a ciegas (Opus, lados A/B al azar): **bobi 23/25, aquí 13/25.** Puntos comprobados en el código de aquí:
- `confianza_de` = max(p, 1−p): la escala no es la de la confianza de Jev (|2p−1|), así que "confianza ≥ 0,7" filtra
  menos de lo que parece. El plan no definía la escala; es una elección, pero la de bobi es la coherente con Jev.
- El informe dice "Coste en $: no disponible" aunque el precio es conocido ($0,042/M): coste real $0,0013.
- Si falta la clave, el modo en vivo sobrescribe el informe real con "0 de 40". (En los dos lados `--fake` también
  sobrescribe el informe en vivo: me pasó al verificar y lo restauré desde git.)
- El revisor no vio `docs/phases/2-report.md`, donde la sesión de aquí sí diagnosticó `despedida` como error de
  etiquetado (Jev acierta, la etiqueta humana no); le penalizó el juicio por eso.

Lectura: el patrón de la fase 1 se repite: un 69 % más barato con menos calidad. Esta sesión cargó `phase-runner`
antes de reforzar su paso 5, así que la fase 2 se revisó con la lista vieja. bobi gasta más sobre todo por releer
una sesión única cada vez más larga (7,2 M de lectura de caché).

Coste de las fases que solo hizo bobi: Fase 3 $3,88, Fase 4 $2,32.

## Fase 2: reapertura con la revisión reforzada
- Revisor sin contexto (Opus) con el nuevo paso 5, sin pistas: encontró los fallos de la revisión a ciegas (coste,
  informe pisado sin clave, escala de confianza, desacuerdos que incluían aciertos) y además códigos de salida y
  validación del CSV. $0,31. Corrección con Sonnet: $1,07, 58 → 77 tests.
- Etiquetas de `despedida` corregidas a ciegas (15 de 1 → 0, $0,26): `despedida` pasa de 65 % a 97,5 %; los 6 ítems ≥ 92,5 %.
- Fase 2 a calidad comparable: $1,56 + $0,31 + $1,07 = **$2,94 frente a $5,02 (−41 %)**. El reetiquetado no se suma
  porque respondía a una decisión tuya que bobi no tuvo.
- Tendencia tras dos fases: el lado optimizado sale un 40-50 % más barato una vez añadida la revisión, no un 65 %.

# A/B — Fases 3 y 4 (22-sep-2026)

Aquí: sesión nueva, `phase-runner` con el paso 5 reforzado, mensaje «Ejecuta las fases 3 y 4…». bobi: las hizo por su
cuenta tras reiniciar la app, en su sesión única (retomó su propia recomendación).

| | Aquí | bobi |
|---|---|---|
| Fase 3 (anonimizador, opus) | $2,23 (Opus en el orquestador) | $3,88 (incluye ~$1,3 de reescritura de caché al retomar tras el reinicio) |
| Fase 4 (CLI por lotes, sonnet) | $2,32 (Opus $1,51 + Sonnet $0,81); la revisión corrigió dos huecos dentro de la fase | $2,32 |
| Total | **$4,55** | $6,20 (≈ $4,9 sin la reescritura por el reinicio) |
| Tests de las dos fases | 25 + 19, OK | 36 + 30, OK |
| Revisión a ciegas | **35/40** | 23/40 |

Fugas de datos del anonimizador de bobi, comprobadas ejecutando las dos implementaciones con las mismas entradas:
cédula con guion, móviles con 00593 o +593 y grupo de un dígito, fijos con paréntesis, tarjeta seguida de un número,
móvil seguido de un número y nombres en forma NFD salen sin tapar. El de aquí tapa todos. Los dos tapan de más una
fecha seguida de hora (`09-12-2024 10:30` → `[TELEFONO]:30`).
La fase 4 de bobi además no reintenta filas en error (un 401 las deja en error para siempre) y su escritura en orden
deja una ventana de doble gasto tras un corte; la de aquí conserva solo filas ok y aborta ante un 401.

Lectura: con el paso 5 reforzado y sesión nueva, el lado optimizado gana en calidad y cuesta entre un 7 % y un 27 %
menos. Diferencias que no son de configuración: bobi hizo estas fases en una sesión muy larga retomada tras un reinicio.


# Calibración de Jev como juez de diffs (22-sep-2026)

Script: `~/.claude/scripts/jev-judge.py`, checklist: `~/.claude/scripts/jev-checklist.json` (7 Noul + Score de riesgo 1-5).
Estado = `git diff` de la fase sobre `jevqa scripts tests` (17-38 K caracteres). 2 ejecuciones por diff, solo diffs de aquí
(el código de bobi no está en esta máquina). ~0,8 s por llamada; 14 llamadas por menos de un centavo.

Contrastes con verdad conocida (versión original con el fallo → versión corregida tras la revisión):

| Fase | Pregunta | Original | Corregida |
|---|---|---|---|
| 1 | timeout | 0,03 | 0,84 |
| 1 | validacion_ids | 0,05 | 0,94 |
| 1 | errores_tipados | 0,42 | 0,79 |
| 1 | reintentos (504, red) | 0,39 | 0,98 |
| 2 | codigos_salida | 0,07 | 0,95 |
| 2 | no_pisa_datos | 0,23 | 0,62 |
| 2 | errores_tipados (CSV) | 0,16 | 0,47 |
| 1 / 2 | riesgo_defectos (1-5) | 1,53 / 1,78 | 1,38 / 1,50 |

- 7 de 7 contrastes van en la dirección correcta, 6 de 7 cruzan 0,5. Entre repeticiones varía ≤ 0,05.
- Sesgo: las 4-5 preguntas que discriminan se escribieron conociendo los fallos. Las genéricas no discriminan:
  `tests_errores` sale 0,85-0,94 en todos los diffs (la revisión a ciegas puntuó los tests de la fase 1 con 3/5), y el
  Score de riesgo solo se mueve entre 1,26 y 1,88 con confianza ~0,5 (la fase 3, bien valorada, sale la más alta).
- Si el diff no tiene el código al que se refiere la pregunta (p. ej. sin llamadas de red), Jev responde "no" (~0,1), no "no aplica".

Lectura: Jev sirve para **verificar propiedades concretas** de un diff (¿hay timeout?, ¿se validan ids?), de forma barata y
repetible. No sirve para **encontrar fallos nuevos** ni como nota global de calidad. Uso en el A/B: convertir cada fallo que
encuentre la revisión a ciegas en una pregunta del checklist y aplicarlo a los dos lados en las fases siguientes.

# A/B — Fase 5 (22-sep-2026), sesión nueva en las dos máquinas con el mismo mensaje

| | Aquí | bobi |
|---|---|---|
| Coste | **$1,71** (Opus $1,40 + Sonnet $0,30) | $2,81 (solo Opus) |
| Tokens de salida | 24 K | 35 K |
| Minutos | 3,9 | 5,9 |
| Tests de la fase | 30, OK | 31, OK |
| Revisión a ciegas | **16/20** | 13/20 |

- Fallo principal de bobi: su `scoring.py` espera el dict de `parse_response`, pero su `pipeline.py` escribe columnas
  planas (`<item>_prob`, `<item>_conf`): no puede puntuar el CSV que produce su propio lote sin volver a llamar a Jev.
  Tampoco separa filas en error ni valida p fuera de [0, 1].
- Fallo menor de aquí: la nota se redondea antes de compararla con `aprobado` (69,96 aprueba); con los pesos reales no ocurre.
- Primera comparación totalmente limpia (sesión nueva, mismo mensaje, mismo plan): −39 % de coste y mejor calidad.

Después de la fase 5 (fuera de la medición): corregido aquí que el anonimizador tapaba fechas con hora como teléfono
(`09-12-2024 10:30`); 25 → 28 tests. Límite: con año de 2 dígitos (`09-12-24 10:30`) aún se tapa.

# Evaluación externa de la calibración de Jev como juez (22-sep-2026)

Prueba fuera de muestra: el mismo `jev-judge.py` y el mismo checklist, sin cambiar nada, sobre los diffs de las fases
3-5 de los dos lados (el de bobi, traído como bundle de git). La verdad sale de las revisiones a ciegas, hechas antes
y sin conocer este checklist. 2 repeticiones por diff, $0,0045.

| Contraste con verdad conocida | Esperado | Jev | ¿Acierta? |
|---|---|---|---|
| F4 `reintentos` (bobi deja un 401 en error para siempre y no reintenta filas en error) | aquí > bobi | 0,54 vs 0,58 | No |
| F4 `no_pisa_datos` (bobi pierde filas ya pagadas tras un corte) | aquí ≥ bobi | 0,70 vs 0,86 | No |
| F5 `errores_tipados` (bobi no valida p fuera de [0,1]) | aquí > bobi | 0,55 vs 0,26 | Sí |
| `riesgo_defectos` F3 (bobi filtra datos personales) | bobi > aquí | 1,57 vs 1,87 | No |
| `riesgo_defectos` F4 | bobi > aquí | 1,54 vs 1,69 | No |
| `riesgo_defectos` F5 | bobi > aquí | 1,56 vs 1,25 | Sí |

- Fuera de muestra acierta 2 de 6, frente al 7 de 7 dentro de muestra. El 7/7 no generaliza.
- Donde la propiedad no aplica (no hay red en F3/F5), `timeout` sale entre 0,22 y 0,55: ruido, no "no aplica".
- `tests_errores` sale 0,87-0,94 en los seis diffs: no discrimina, como ya decía la calibración.
- Dentro de muestra, un `grep 'timeout='` sobre el diff da el mismo contraste que Jev en la fase 1: la calibración no
  demuestra valor por encima de una búsqueda de texto en las propiedades que se pueden buscar así.
- Ninguna pregunta del checklist cubre fugas de datos personales, el defecto más grave de F3: un checklist fijo no
  encuentra tipos de fallo que no anticipó.

Veredicto: la conclusión de la calibración ("sirve para verificar propiedades concretas, no para encontrar fallos") es
todavía demasiado optimista. Sirve para propiedades concretas y visibles en el texto del diff, que casi siempre se pueden
comprobar con grep o con un test; falla en propiedades de comportamiento (semántica de reintentos al reanudar) y como nota
global. No debe usarse como medida de calidad en este A/B. Para recalibrarlo bien: preguntas congeladas antes de ver el
código, ≥ 20 contrastes con verdad independiente, controles negativos (código que menciona `timeout` pero no lo aplica),
una pregunta "¿aplica?" por propiedad, estado por archivo en vez del diff entero, y comparación contra grep.

# A/B — Fases 6 y 7 (22 y 24-sep-2026)

Aquí: tarea programada (sesión nueva automática, Opus 5.5 + Sonnet + Haiku); la fase 7 la cerró la sesión orquestadora
tras un bloqueo de 50 min en un `rm -rf` que pedía confirmación. bobi: su sesión única de siempre, retomada un día
después, con Opus 5.5 y el mensaje «sigue con lo pendiente»; medido hasta el commit de la fase 7.

| | Aquí | bobi |
|---|---|---|
| Coste | **$2,04** (Opus 5.5 $1,38 + Sonnet $0,59 + Haiku $0,07) | $5,84 (solo Opus 5.5) |
| Lectura / escritura de caché | — | 9,7 M / 363 K (retomar una sesión enorme) |
| Tests al final del plan | 184, OK | 200, OK |
| Comandos del README | todos exit 0 | todos exit 0 |
| Revisión a ciegas | **21/25** | 20/25 (empate técnico; confianza del revisor ~60 %) |

- Aquí, confirmado: `comparar` abre el CSV humano con `utf-8` (un CSV de Excel con BOM falla) y el README describe mal
  las columnas de salida de `auditar`. El coste del informe es una estimación fija, no el uso real.
- bobi: `comparar` solo acepta etiquetas `cumple`/`no` (un CSV 0/1 da n = 0 y sale con 0), no detecta ids repetidos,
  y dos campañas que solo difieren en mayúsculas se sobrescriben en Windows. Su README es claramente mejor.

## Balance del plan completo (costes a los precios de cada momento)

| Fase | Aquí | bobi | Revisión a ciegas |
|---|---|---|---|
| 1 | $3,32 (reabierta) | $6,76 | bobi 29-19 antes de corregir |
| 2 | $2,94 (reabierta) | $5,02 | bobi 23-13 antes de corregir |
| 3 y 4 | $4,55 | $6,20 | aquí 35-23 |
| 5 | $1,71 | $2,81 | aquí 16-13 |
| 6 y 7 | $2,04 | $5,84 | aquí 21-20 (empate) |
| **Total** | **$14,56** | **$26,63** | |

Configuración optimizada: −45 % de coste en el plan entero. En calidad, peor en las dos primeras fases (antes de
reforzar la revisión del paso 5) y igual o mejor en las cinco siguientes. Una sola ejecución por lado y bobi con una
sesión única cada vez más larga: parte del ahorro viene precisamente de no arrastrar esa sesión.

