# Auditoría QA de contact centers con Jev (MVP) — plan
Estado: fases 1, 2, 3 y 4 cerradas el 2026-09-21; fase 5 cerrada el 2026-09-22. La fase 2 se
ejecutó en vivo con aprobación del usuario: 8 de 8 ítems por encima del 85 % de acuerdo, coste real
$0,0085. Fase activa = 6. Rama: mvp-qa. Repo: C:/Users/kenny/projects/jev-qa (nuevo).
Stack: Python 3.14, solo biblioteca estándar (urllib, csv, unittest, html). Sin dependencias nuevas sin aprobación.
Flujo: CSV de transcripciones -> anonimizar -> 1 petición Jev por interacción -> nota y cola de revisión -> CSV + informe.
Fuera de alcance: transcripción de audio, dashboard web, multiusuario, deploy, datos reales de clientes.
Pendientes (no tocar hasta cerrar el plan): transcripción de audio; conectores a plataformas de contact center; soporte en inglés para BPO nearshore; contrato y registro de transferencias (ley de datos de Ecuador) antes del primer piloto real.

Autorización permanente: ejecuta cada fase aprobada completa, incluyendo commits en la rama, sin pedir
confirmación. Detente y pregunta solo por: deploy o release, migración destructiva o base de datos real,
gasto de dinero, credenciales, o si la fase revela que el plan está equivocado.

Criterio de modelo: sonnet para implementación bien especificada; opus para privacidad y juicio fino;
haiku solo para trabajo mecánico. Verificación común: `python -m unittest discover -s tests -v` → 0 fallos.

## Medición A/B (la hace otra sesión; no es requisito para ejecutar ninguna fase)
- Cada fase se ejecuta en una sesión nueva en esta máquina y en bobi-almax con el mismo mensaje. No hay remoto, etiquetas
  obligatorias ni tests ocultos: no los busques ni los crees. Los resultados se registran en `docs/ab.md`.

## Fase 1 — Rúbrica, cliente Jev y conjunto de validación
- Objetivo: a partir de una rúbrica JSON se construye una sola petición Jev por interacción y su respuesta se convierte en un resultado tipado, sin red.
- Modelo: sonnet
- Alcance: `jevqa/__init__.py`, `jevqa/rubric.py`, `jevqa/jev_client.py`, `rubrics/soporte_es.json`, `data/eval/sinteticas.csv`, `tests/test_rubric.py`, `tests/test_client.py`, `tests/fixtures/respuesta_jev.json`
- Pasos:
  - Rúbrica JSON: ítems (id, pregunta Noul, peso, crítico sí/no), Score de riesgo (4 niveles), Choice de motivo con opción "otro".
  - `build_request`: `state` = interacción una sola vez; `questions` = un Noul por ítem + `riesgo` + `motivo`.
  - `parse_response`: probabilidad, confianza y distribución por pregunta; error tipado si falta una respuesta.
  - Cliente HTTP (urllib, `TYPESAFE_API_KEY`, `jev-latest`) con reintento y espera en 429/5xx; `FakeJev` inyectable para tests.
  - 40 interacciones sintéticas en español, etiquetadas a mano por ítem (cumple/no), con casos ambiguos.
- Interfaz fija: `jevqa.rubric.load_rubric(path)`, `jevqa.rubric.build_request(rubric, text) -> dict`, `jevqa.rubric.parse_response(rubric, data) -> dict`, `jevqa.jev_client.FakeJev`.
- Cobertura: rúbrica de 1 ítem y de N; respuesta completa, respuesta sin una pregunta, 401 (error claro, sin reintento), 429 y 500 (reintenta), agotamiento de reintentos.
- Terminado cuando: el cuerpo de la petición contiene el texto una sola vez y exactamente N+2 preguntas; la respuesta de ejemplo de la documentación se interpreta sin pérdida de campos.
- Verificación: `python -m unittest discover -s tests -v` → 0 fallos.
- Riesgo: el formato real de la API difiere del documentado → el test usa una respuesta copiada de la documentación y la fase 2 lo confirma en vivo.
- [x] cerrada

## Fase 2 — ¿Funciona Jev en español? (REQUIERE APROBACIÓN: credenciales y gasto < $0,01)
- Objetivo: medir, por ítem de la rúbrica, cuánto coincide Jev con las etiquetas humanas en español antes de construir nada más.
- Modelo: sonnet
- Alcance: `scripts/eval_jev.py`, `data/eval/informe.md`, `tests/test_eval_metrics.py`
- Pasos:
  - Métricas por ítem: acuerdo, precisión y exhaustividad del "no cumple", acuerdo en las respuestas con confianza ≥ 0,7.
  - Modo `--fake` (sin red) y modo en vivo con `TYPESAFE_API_KEY` del entorno, que el usuario define.
  - Informe con tabla por ítem, coste real (tokens de uso) y los 5 peores desacuerdos citados.
- Cobertura: métricas con acuerdo total, acuerdo nulo, ítem sin ningún "no cumple" (sin división por cero).
- Terminado cuando: existe `data/eval/informe.md` con las 40 filas evaluadas y métricas por ítem. PUNTO DE DECISIÓN: si algún ítem baja del 85 % de acuerdo, detente y reporta (opciones: reformular en inglés, traducir el texto antes de enviarlo, o quitar el ítem).
- Verificación: `python scripts/eval_jev.py --fake` → informe con 40 filas; luego `python scripts/eval_jev.py` (en vivo).
- Riesgo: datos sintéticos escritos por nosotros sobreestiman el acierto → límite conocido; la validación real es el piloto (fase 6).
- [x] cerrada

## Fase 3 — Anonimizador (ley de datos de Ecuador)
- Objetivo: ningún dato personal identificable del cliente final sale hacia Jev.
- Modelo: opus
- Alcance: `jevqa/anonymize.py`, `tests/test_anonymize.py`
- Pasos:
  - Cédula (10 dígitos con dígito verificador) y RUC (13) → `[CEDULA]`, `[RUC]`.
  - Teléfonos de Ecuador (09…, +593, fijos), correos y tarjetas (Luhn) → etiquetas.
  - Nombres de agente y cliente tomados de las columnas del CSV, sin distinguir mayúsculas ni tildes.
  - Mapeo reversible solo en memoria, para que el informe muestre el nombre del agente.
- Interfaz fija: `jevqa.anonymize.anonymize(text: str, names: list[str] = []) -> str`.
- Cobertura: cédula válida frente a 10 dígitos inválidos (un importe no se tapa); tarjeta válida frente a inválida; nombre con y sin tilde; texto sin datos personales (queda igual); cantidades y fechas intactas.
- Terminado cuando: sobre las 40 interacciones sintéticas con datos personales sembrados, 0 fugas y 0 importes tapados.
- Verificación: `python -m unittest tests.test_anonymize -v` → 0 fallos.
- Riesgo: los nombres propios que no están en columnas se escapan → test que lo documenta; queda como límite conocido en el README.
- [x] cerrada

## Fase 4 — Auditoría por lotes (CLI)
- Objetivo: `python -m jevqa auditar entrada.csv` produce un CSV de resultados por interacción, anonimizando antes de cada llamada.
- Modelo: sonnet
- Alcance: `jevqa/pipeline.py`, `jevqa/__main__.py`, `tests/test_pipeline.py`, `tests/fixtures/mini.csv`
- Pasos:
  - Validar columnas (id, agente, campaña, fecha, texto) con mensaje claro si faltan.
  - Concurrencia limitada por debajo de 1.200 req/min; estimar tokens y marcar "demasiado larga" si supera 32.000.
  - Reanudable: salta ids ya auditados en la salida, para no pagar dos veces.
  - Un fallo en una fila se registra como error y el lote sigue.
- Interfaz fija: `python -m jevqa auditar <entrada.csv> --salida <salida.csv> [--fake]`.
- Cobertura: CSV vacío, columnas faltantes, fila demasiado larga, fila con error 500, relanzar un lote a medias.
- Terminado cuando: con `FakeJev`, 50 filas de entrada dan 50 filas de salida; al relanzar se hacen 0 llamadas; el cuerpo enviado no contiene datos personales sembrados.
- Verificación: `python -m unittest tests.test_pipeline -v` → 0 fallos; `python -m jevqa auditar tests/fixtures/mini.csv --fake` → exit 0.
- Riesgo: doble gasto al relanzar → cubierto por el test de reanudación.
- [x] cerrada

## Fase 5 — Nota, umbrales y cola de revisión
- Objetivo: cada interacción tiene nota 0–100, las críticas fallan siempre y las dudosas van a revisión humana.
- Modelo: sonnet
- Alcance: `jevqa/scoring.py`, `tests/test_scoring.py`
- Pasos:
  - Nota ponderada por los pesos de la rúbrica; un ítem crítico en "no cumple" fuerza el suspenso.
  - A revisión si algún ítem tiene confianza < umbral o probabilidad entre 0,35 y 0,65.
  - Agregados por agente y campaña: nota media, % de críticas, tamaño de la cola.
- Cobertura: todo cumple; falla un crítico; ítem ambiguo; agente con 1 interacción frente a muchos; campaña vacía.
- Terminado cuando: los casos de cobertura dan la nota, el estado y la cola esperados.
- Verificación: `python -m unittest tests.test_scoring -v` → 0 fallos.
- Riesgo: umbrales mal puestos → configurables en la rúbrica, con valores por defecto sacados del informe de la fase 2.
- [x] cerrada

## Fase 6 — Informe semanal y kit del piloto
- Objetivo: un HTML por campaña y una comparación contra 100 auditorías humanas, que es lo que se entrega en el piloto.
- Modelo: sonnet
- Alcance: `jevqa/report.py`, `jevqa/compare.py`, `tests/test_report.py`, `tests/test_compare.py`
- Pasos:
  - Informe: ranking de agentes, peores interacciones, cola de revisión, coste de Jev del periodo.
  - `python -m jevqa comparar humano.csv resultados.csv`: acuerdo y kappa por ítem, más una matriz de confusión.
- Cobertura: ids humanos que no están en los resultados; ítem que falta en una de las dos rúbricas; acuerdo total y acuerdo nulo.
- Terminado cuando: con los datos de ejemplo se generan los dos archivos con todas sus secciones y la comparación da el kappa esperado en los casos de test.
- Verificación: `python -m unittest tests.test_report tests.test_compare -v` → 0 fallos.
- Riesgo: HTML con texto del cliente sin escapar → test de que se escapa `<script>`.
- [ ] cerrada

## Fase 7 — README de operación
- Objetivo: alguien que no ha visto el código puede correr un piloto siguiendo el README.
- Modelo: haiku
- Alcance: `README.md`
- Pasos: formato del CSV, variable de entorno, comandos auditar/comparar/informe, costes por 1.000 interacciones, límites conocidos (nombres fuera de columnas, datos sintéticos).
- Cobertura: cada comando del README existe en `python -m jevqa --help`.
- Terminado cuando: todos los comandos del README corren con `--fake` y salen con exit 0.
- Verificación: `python -m jevqa --help` → lista auditar, comparar e informe.
- Riesgo: el README se desfasa del código → la verificación ejecuta sus comandos.
- [ ] cerrada
