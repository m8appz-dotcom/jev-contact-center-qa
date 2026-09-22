# Registro de la medición A/B

Una fila por fase y por lado. «Aquí» es esta máquina (Claude Code optimizado);
«bobi» es bobi-almax (Claude sin optimizar). Solo las fases 1, 3 y 4 son espejo.

Lectura acordada en el plan: una sola ejecución por lado es una anécdota y las
diferencias menores del 25 % cuentan como empate.

## Fase 1 — Rúbrica, cliente Jev y conjunto de validación

| Campo | Aquí | bobi |
| --- | --- | --- |
| Commit de partida | `base-f1` (565defb) | — |
| Rama medida | `mvp-qa` | `bobi/f1` (pendiente) |
| Modelo(s) usados | Opus 5 (sesión completa; el plan pedía sonnet) | — |
| `claude --version` | no disponible desde la sesión | — |
| Tokens entrada / salida | sin medir | — |
| Caché (lectura / escritura) | sin medir | — |
| Coste | sin medir | — |
| Minutos | ~1 h 50 min de reloj de sesión | — |
| Intervenciones humanas | 0 | — |
| Verificación a la primera | no (2 intentos: un byte nulo en el fuente y una comparación de flotantes) | — |
| Tests ocultos pasados | no ejecutados (no existe el directorio holdout) | — |
| Líneas del diff | 2.123 añadidas, 2 borradas (10 archivos, `base-f1..47789df`) | — |

## Fase 3 — Anonimizador

| Campo | Aquí | bobi |
| --- | --- | --- |
| Commit de partida | `base-f3` (534cd6d^ = adc6a9f… ver nota) | — |
| Rama medida | `mvp-qa` (9b83b8e) | `bobi/f3` (pendiente) |
| Modelo(s) usados | Opus 5 (el plan pedía opus) | — |
| Verificación a la primera | sí (36 tests, 0 fallos en la primera ejecución) | — |
| Intervenciones humanas | 0 | — |
| Líneas del diff | 601 añadidas, 5 borradas (5 archivos) | — |

## Fase 4 — Auditoría por lotes

| Campo | Aquí | bobi |
| --- | --- | --- |
| Commit de partida | `base-f4` (9b83b8e) | — |
| Rama medida | `mvp-qa` (534cd6d) | `bobi/f4` (pendiente) |
| Modelo(s) usados | Opus 5 (el plan pedía sonnet) | — |
| Verificación a la primera | no (1 fallo: el límite de campo de `csv`, que era un fallo real del código, no del test) | — |
| Intervenciones humanas | 0 | — |
| Líneas del diff | 899 añadidas, 3 borradas (5 archivos) | — |

## Fase 2 — no es fase espejo

No se mide: el plan solo compara las fases 1, 3 y 4. Se anota aquí el gasto
real porque es el único de todo el proyecto.

| Concepto | Valor |
| --- | --- |
| Llamadas a Jev | 121 (1 de prueba + 3 pasadas de 40) |
| Tokens de entrada | 202.527 |
| Coste | $0,0085 |
| Resultado | 8 de 8 ítems por encima del 85 % de acuerdo |

Las tres pasadas completas salieron de ir mejorando el informe, no de que
fallara la medición: las respuestas de Jev fueron idénticas en las tres. Si
se vuelve a tocar el informe, conviene guardar las respuestas crudas en vez
de volver a pagar la pasada.

### Qué falta para que la comparación sea válida

Tres piezas del protocolo no existen todavía en esta máquina y hay que
resolverlas antes de dar por buena cualquier lectura:

1. **Sin remoto compartido.** El repo no tiene `origin`, así que la etiqueta
   `base-f1` está solo en local y bobi no puede clonar ni ramificar desde ella.
2. **Sin tests ocultos.** No existe `jev-qa-holdout/`. El plan pide escribirlos
   *antes* de la fase contra la «Interfaz fija»; para la fase 1 ya es tarde, se
   pueden escribir igual y ejecutarlos sobre las dos ramas cuando exista `bobi/f1`.
3. **Sin `claude-metrics.py`.** No está en la máquina, así que las columnas de
   tokens, caché y coste quedan vacías. Los números de una sesión no se pueden
   leer desde dentro de ella misma.

En `C:/Users/video/projects/jev-qa-ab-logs/` hay un intento previo de ejecución
(`run.json`, `run.meta`) que terminó en `exit=1` con `terminal_reason: api_error`
y cero tokens: no sirve como medición de ningún lado.
