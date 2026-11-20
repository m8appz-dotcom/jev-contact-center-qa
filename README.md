# Auditoría QA de contact centers con Jev

Auditoria automática de interacciones de soporte al cliente en español usando la API TypeSafe de Jev.

## Requisitos

- Python 3.14 (o compatible)
- Biblioteca estándar de Python solamente (sin dependencias adicionales)
- `TYPESAFE_API_KEY` para auditorías en vivo (no necesaria con `--fake`)

## Instalación y configuración

1. **Clonar el repositorio:**
   ```bash
   git clone <repo-url>
   cd jev-qa
   ```

2. **Configurar la clave de API (solo para auditorías en vivo):**

   PowerShell:
   ```powershell
   $env:TYPESAFE_API_KEY = "tu-clave-api-aqui"
   ```

   Bash:
   ```bash
   export TYPESAFE_API_KEY="tu-clave-api-aqui"
   ```

## Flujo de trabajo

1. Prepara un CSV con transcripciones (`id, agente, campaña, fecha, texto`)
2. Ejecuta `auditar` para enviar cada interacción a Jev (con anonimización automática)
3. Ejecuta `informe` para generar un HTML resumen por campaña
4. Ejecuta `comparar` para validar contra auditoría humana (opcional)

## Formatos de entrada

### CSV de transcripciones (auditar)

UTF-8, obligatorio `id, agente, campaña, fecha, texto`; opcional `cliente` (se anonimiza):

```
id,agente,campaña,fecha,texto
1,Maria Lopez,soporte_tecnico,2026-01-05,"Buenos días, gracias por comunicarse. ¿En qué puedo ayudarle?"
2,Carlos Ruiz,facturacion,2026-01-05,"Entiendo su reclamo sobre la factura..."
```

- `id`: único, no vacío
- `agente`, `cliente`: nombres (no se anonimiza si no están en columnas)
- `fecha`: formato libre (ej: `2026-01-05`, `05/01/2026`)
- `texto`: la interacción (se anonimiza: cédulas, RUC, teléfonos, correos, tarjetas)

### CSV de auditoría humana (comparar)

Columna `id` + una por ítem (0/1). Se ignoran `texto, ambiguo, agente, campaña, fecha, cliente, notas`:

```
id,saludo,escucha,resolucion,trato_respetuoso,proteccion_datos,despedida
1,1,1,1,1,1,1
2,0,1,1,1,1,0
```

Ítems de la rúbrica: `saludo, escucha, resolucion, trato_respetuoso, proteccion_datos, despedida`.

## Comandos

### 1. Auditar (entrada → resultados)

```bash
python -m jevqa auditar <entrada.csv> [--salida <salida.csv>] [--fake]
```

Envía cada interacción a Jev, anónimamente. Salida: CSV con `id, agente, campaña, fecha, estado, detalle`, una columna por ítem de la rúbrica con la probabilidad de que se cumpla (`saludo`, `escucha`, …) y `riesgo`, `motivo`. `estado` es `ok`, `error` o `demasiado_larga`; `detalle` explica los dos últimos. 

- `--salida`: archivo de salida (por defecto `<entrada>.auditado.csv`)
- `--fake`: modo sin red (pruebas, no cobra)
- Reanudable: relanzar salta ids ya auditados

Códigos de salida:
- `0`: completado sin errores
- `2`: entrada inválida (columnas, CSV vacío, ids)
- `3`: autenticación Jev fallida (se abortó)
- `4`: lote con filas en error (pero continuó)

### 2. Informe (resultados → HTML)

```bash
python -m jevqa informe <resultados.csv> [--salida-dir <dir>] [--coste-por-llamada <usd>]
```

Genera un HTML por campaña con ranking de agentes, peores interacciones, cola de revisión y coste estimado.

- `--salida-dir`: directorio de salida (por defecto `<resultados>_informes/`)
- `--coste-por-llamada`: $USD por interacción para estimación (por defecto $0,0000314)

### 3. Comparar (humano vs resultados)

```bash
python -m jevqa comparar <humano.csv> <resultados.csv> [--salida <archivo.md>]
```

Compara auditoría humana vs Jev: acuerdo, kappa de Cohen y matriz de confusión por ítem.

- `--salida`: archivo Markdown (por defecto `<resultados>.comparacion.md`)

## Prueba rápida sin red

Ejecuta estos comandos en orden desde la raíz del repo. Todos deben salir con código 0:

```bash
# 1. Auditar con datos de ejemplo (modo fake, sin red)
python -m jevqa auditar tests/fixtures/mini.csv --salida resultados.csv --fake

# 2. Generar informe HTML
python -m jevqa informe resultados.csv --salida-dir informes

# 3. Comparar contra auditoría humana
python -m jevqa comparar tests/fixtures/mini_humano.csv resultados.csv --salida comparacion.md
```

Salidas:
- `resultados.csv`: una fila por interacción (id, agente, campaña, fecha, estado, detalle, probabilidad por ítem, riesgo, motivo)
- `informes/informe_<campaña>.html`: resumen, ranking, peores interacciones, cola de revisión
- `comparacion.md`: acuerdo y kappa por ítem, matriz de confusión

## Piloto real (con API de Jev)

Una vez que los comandos de prueba funcionen, ejecuta sin `--fake`:

```bash
# Requiere TYPESAFE_API_KEY configurada
python -m jevqa auditar tu_datos.csv --salida resultados_reales.csv

# Luego, igual que antes
python -m jevqa informe resultados_reales.csv --salida-dir informes
python -m jevqa comparar tu_humanos.csv resultados_reales.csv --salida comparacion_real.md
```

## Costes y rendimiento

- **Coste:** $0,042 por millón de tokens de entrada (TypeSafe, modelo `jev-latest`)
  - ~750 tokens por interacción corta (transcripción de chat)
  - **≈ $0,03 por 1.000 interacciones** (cortas)
  - **≈ $0,13 por 1.000 interacciones** (llamadas de ~5 min, ~3.000 tokens)
- **Rendimiento:** ≤ 1.000 llamadas/min, máx 8 en paralelo
- **Límite:** interacciones > 32.000 tokens estimados se marcan `demasiado_larga` (no se facturan)

## Rúbrica de evaluación

Ítems (peso y crítico):
- `saludo` (10%): agente saluda y se identifica
- `escucha` (15%): agente demuestra entender el problema
- `resolucion` (30%): agente resuelve o encamina efectivamente
- `trato_respetuoso` (25%, **crítico**): sin groserías ni desprecio
- `proteccion_datos` (10%, **crítico**): no solicita datos personales innecesarios
- `despedida` (10%): se despide adecuadamente

**Nota:** 0–100 ponderada por pesos; ítem cumple si p ≥ 0,5; suspende si falla un crítico o nota < 70; a revisión si confianza < 0,7 o probabilidad en [0,35, 0,65].

## Privacidad y límites conocidos

**Anonimización:** antes de enviar a Jev se ocultan cédulas (10 dígitos), RUC (13), teléfonos de Ecuador, correos, tarjetas (Luhn) y nombres de agente/cliente.

**Límites conocidos:**
- Nombres propios NO en columnas `agente`/`cliente` no se anonimizan
- Fechas de 2 dígitos + hora (ej: `09-12-24 10:30`) pueden taparse como teléfono
- Precisión medida: ≥ 92,5% en 40 interacciones sintéticas; la validación real es el piloto con ≥ 100 auditorías humanas
- `escucha` tuvo exhaustividad del "no cumple" del 84,6%
- Umbrales (aprobado 70%) sin calibrar; verificar en el piloto
- Coste del informe estimado, no facturado por TypeSafe
- CSV de salida UTF-8 sin BOM (Excel puede mostrar mal tildes)
- Solo español; sin transcripción de audio

## Tests

```bash
python -m unittest discover -s tests -v
```

## Privacidad de datos

Usar datos reales de clientes requiere antes contrato y registro de transferencias (ley de datos de Ecuador). No usar datos reales hasta obtenerlo.
