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
