# jev-qa — auditoría de calidad de contact centers con Jev

Audita transcripciones de llamadas de soporte en español con una rúbrica fija
y deja, por interacción, una nota de 0 a 100, un estado (aprobado o suspenso) y,
si el modelo no lo vio claro, un aviso para que la revise una persona.

El flujo completo:

```
CSV de transcripciones → anonimizar → 1 petición a Jev por interacción
                       → nota y cola de revisión → CSV de resultados → informe HTML
```

Nada sale hacia Jev sin anonimizar. Las cédulas, los RUC, los teléfonos, los
correos, las tarjetas y los nombres del agente y del cliente se tapan antes de
cada llamada.

## Requisitos

- Python 3.12 o superior. Solo usa la biblioteca estándar: no hay nada que
  instalar.
- Una clave de la API de TypeSafe en la variable de entorno `TYPESAFE_API_KEY`.
  Sin la clave, todos los comandos funcionan con `--fake`, que no usa la red
  ni cuesta dinero, pero da números inventados.

En PowerShell:

```powershell
$env:TYPESAFE_API_KEY = "tu-clave"
```

En bash:

```bash
export TYPESAFE_API_KEY="tu-clave"
```

No guardes la clave en ningún archivo del repositorio.

## Prueba rápida sin red

Estos comandos usan los datos de ejemplo del repositorio y no gastan nada.
Sirven para comprobar que todo funciona antes de tocar datos del cliente.

```bash
python -m jevqa auditar tests/fixtures/mini.csv --salida salidas/mini_resultados.csv --fake
```

```bash
python -m jevqa informe salidas/mini_resultados.csv --salida salidas --fake
```

```bash
python -m jevqa auditar data/eval/sinteticas.csv --salida salidas/sinteticas_resultados.csv --fake
```

```bash
python -m jevqa comparar data/eval/sinteticas.csv salidas/sinteticas_resultados.csv --salida salidas/comparacion.md --fake
```

Los archivos quedan en `salidas/`, que git ignora. Con `--fake` las notas son
ruido: sirven para ver la forma del informe, no para leerlo.

## Cómo correr un piloto

### 1. Preparar el CSV de entrada

Un CSV en UTF-8 con una fila por interacción y estas columnas:

| Columna | Obligatoria | Contenido |
| --- | :-: | --- |
| `id` | sí | Identificador único de la interacción. No se puede repetir. |
| `agente` | sí | Nombre del agente. Se tapa en el texto antes de enviarlo. |
| `campaña` | sí | Campaña o cola. También se acepta `campana`. Hay un informe por campaña. |
| `fecha` | sí | Fecha de la interacción en formato `AAAA-MM-DD`. |
| `texto` | sí | La transcripción completa, con cada turno en su línea (`Agente: …`, `Cliente: …`). |
| `cliente` | no | Nombre del cliente final. Si viene, también se tapa en el texto. |

`tests/fixtures/mini.csv` es un ejemplo de tres filas con esta forma.

### 2. Auditar

```bash
python -m jevqa auditar tests/fixtures/mini.csv --salida salidas/resultados.csv --fake
```

Para la corrida real, cambia el archivo de entrada por el del cliente y
quita `--fake`. El comando:

- anonimiza cada transcripción y la evalúa con **una sola** petición a Jev;
- escribe una fila por interacción en el CSV de salida, con la probabilidad y
  la confianza de cada ítem, el motivo del contacto y el nivel de riesgo;
- si una fila falla (error de la API, transcripción demasiado larga), la
  marca y sigue con el resto;
- **se puede relanzar sin pagar dos veces**: salta los ids que ya están en el
  archivo de salida. Si el lote se corta, vuelve a ejecutar el mismo comando.

Opciones útiles: `--concurrencia` (8 por defecto) y `--por-minuto` (960 por
defecto; el límite de la API es 1.200 y el comando no deja pasar de ahí).

### 3. Generar el informe semanal

```bash
python -m jevqa informe salidas/resultados.csv --salida salidas --desde 2026-08-01 --hasta 2026-08-31 --fake
```

Escribe un HTML por campaña (`salidas/informe_<campaña>.html`) con:

- **Ranking de agentes**, mejor nota primero. Los agentes con menos de 5
  interacciones auditadas van en una tabla aparte: su promedio todavía es una
  anécdota.
- **Peores interacciones**: las que fallaron un ítem crítico primero, después
  la nota más baja.
- **Cola de revisión**: lo que una persona tiene que mirar, en orden de
  urgencia.
- **Coste de Jev del periodo**.

`--desde` y `--hasta` son opcionales; sin ellos entra todo el archivo.

### 4. Comparar con la auditoría humana

Es la prueba que se entrega en el piloto. El equipo de calidad del cliente
audita a mano unas 100 interacciones, las mismas se pasan por `auditar`, y se
comparan:

```bash
python -m jevqa comparar data/eval/sinteticas.csv salidas/sinteticas_resultados.csv --salida salidas/comparacion.md --fake
```

El CSV humano lleva una columna `id` y una columna por ítem de la rúbrica
(`saludo`, `verifica_identidad`, …) con `cumple` o `no`.
`data/eval/sinteticas.csv` tiene exactamente esa forma.

El resultado da, por ítem, el acuerdo, el **kappa de Cohen** y la matriz de
confusión. Fíjate en el kappa más que en el acuerdo: si casi todas las
llamadas cumplen un ítem, un auditor que diga siempre «cumple» acierta el
95 % sin mirar nada, y su kappa es 0.

`comparar` e `informe` no llaman a Jev, así que no gastan nada: `--fake` no
tiene efecto en ellos.

## La rúbrica

Está en `rubrics/soporte_es.json`: ocho ítems con peso (suman 100), tres de
ellos críticos, más una pregunta de nivel de riesgo y otra de motivo del
contacto.

| Ítem | Peso | Crítico |
| --- | --: | :-: |
| `saludo` | 5 | |
| `verifica_identidad` | 10 | sí |
| `escucha_activa` | 10 | |
| `diagnostico` | 15 | |
| `solucion_o_derivacion` | 20 | |
| `tono_respetuoso` | 15 | sí |
| `compromiso_realista` | 15 | sí |
| `cierre` | 10 | |

- **Nota**: suma de los pesos de los ítems que se cumplen.
- **Estado**: aprueba con nota 70 o más y ningún crítico fallado. Un crítico
  en «no cumple» suspende la interacción aunque la nota sea alta; la nota no
  se pone a cero, para que el informe distinga un fallo puntual de un
  desastre.
- **Cola de revisión**: va a revisión la interacción que tenga algún ítem con
  confianza por debajo de 0,7 o con probabilidad entre 0,35 y 0,65.

Los umbrales se cambian en el bloque `umbrales` de la rúbrica:

```json
"umbrales": {
  "cumple": 0.5,
  "confianza": 0.7,
  "ambiguo_min": 0.35,
  "ambiguo_max": 0.65,
  "aprobado": 70,
  "cumple_verifica_identidad": 0.75
}
```

`cumple_<id de ítem>` fija el umbral de un solo ítem sin mover a los demás.

## Costes

Jev cobra solo los tokens de entrada: 42 US$ por cada mil millones.

Medido en vivo sobre las 40 interacciones de ejemplo (950 caracteres de
media): **1.673 tokens por interacción**, es decir, **unos 0,07 US$ por cada
1.000 interacciones**. El coste crece con el largo de la transcripción: las
preguntas de la rúbrica se mandan en cada petición y son una parte fija, el
texto es la parte variable. Una llamada real de 10 minutos es bastante más
larga que las de ejemplo, así que conviene medir el coste en la primera
semana del piloto en lugar de extrapolar esta cifra.

El informe de cada campaña trae el coste real del periodo y lo proyecta a
1.000 interacciones.

A 960 peticiones por minuto, 1.000 interacciones tardan algo más de un
minuto.

## Validación de la rúbrica en español

```bash
python scripts/eval_jev.py --fake --salida salidas/informe_eval_fake.md
```

Sin `--fake` (y con la clave) mide en vivo cuánto coincide Jev con las
etiquetas humanas de `data/eval/sinteticas.csv` y escribe
`data/eval/informe.md`. La última medición en vivo está en ese archivo: los 8
ítems pasan del 85 % de acuerdo.

## Límites conocidos

Léelos antes de presentar resultados a un cliente.

- **Los nombres que no están en las columnas se escapan.** El anonimizador
  tapa el agente y el cliente de la fila, pero si en la conversación aparece
  un tercero («mi hermano Freddy Coello»), ese nombre llega a Jev tal cual.
  Hay un test que lo documenta.
- **La validación se hizo con datos sintéticos.** Las 40 interacciones de
  ejemplo las escribimos nosotros y no tienen cortes, muletillas ni errores de
  transcripción. El acierto real se mide en el piloto, con `comparar`.
- **`verifica_identidad` detecta pocas fallas.** Es un ítem crítico, y en la
  validación Jev detectó 1 de 4 casos en que el agente no verificó. Las tres
  que se escaparon tenían confianza baja, así que caen en la cola de revisión
  en vez de pasar en silencio, pero antes del piloto conviene subir su umbral
  con `cumple_verifica_identidad` y medir el efecto con `comparar`.
- **La cola de revisión puede ser grande.** En la validación, Jev contestó
  `compromiso_realista` con confianza de 0,7 o más en solo 12 de 40
  interacciones. Con el umbral de confianza por defecto, eso manda a revisión
  como mínimo el 70 % de las llamadas. Hay que calibrar ese umbral en la
  primera semana del piloto según cuántas revisiones pueda absorber el equipo.
- **La nota de aprobado (70) no sale de ningún dato.** Es la práctica habitual
  de los contact centers; hay que acordarla con el cliente.
- **Jev lee las preguntas al pie de la letra.** Si el agente hizo *una*
  pregunta concreta, `diagnostico` se cumple aunque la llamada entera sea
  mala. Si eso no es lo que se quiere, hay que escribirlo en el criterio del
  ítem.
- **Solo español.** Las preguntas y los criterios están en español; el inglés
  para BPO nearshore está fuera de este MVP.
- **Antes del primer piloto con datos reales** falta el contrato y el
  registro de transferencia de datos que exige la Ley Orgánica de Protección
  de Datos Personales de Ecuador. Anonimizar reduce lo que se transfiere, pero
  no sustituye ese trámite.

## Desarrollo

```bash
python -m unittest discover -s tests
```

| Módulo | Qué hace |
| --- | --- |
| `jevqa/rubric.py` | Carga la rúbrica, arma la petición y lee la respuesta. |
| `jevqa/jev_client.py` | Cliente HTTP con reintentos, y `FakeJev` para probar sin red. |
| `jevqa/anonymize.py` | Tapa los datos personales antes de cada llamada. |
| `jevqa/pipeline.py` | El lote de `auditar`: reanudable, con límite de peticiones. |
| `jevqa/scoring.py` | Nota, estado, cola de revisión y agregados. |
| `jevqa/report.py` | El informe HTML por campaña. |
| `jevqa/compare.py` | Acuerdo, kappa y matriz contra la auditoría humana. |

El plan del proyecto, fase por fase, está en `docs/plan.md`.
