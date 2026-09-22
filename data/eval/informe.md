# ¿Funciona Jev en español? — informe de la fase 2

- Fecha: 2026-09-21
- Modo: **en vivo**
- Rúbrica: `soporte_es` v1.0 (8 ítems)
- Interacciones evaluadas: **40** de 40
- Umbral de cumplimiento: noul ≥ 0.5 · umbral de confianza: 0.7
- Texto enviado: **anonimizado** (lo mismo que manda la auditoría en producción)
- Tokens de entrada: 66,924 · de salida: 10,056
- Coste: $0.002811

## Acuerdo por ítem

La clase positiva es el **no cumple**: lo que una auditoría necesita detectar.

| Ítem | Crítico | n | Acuerdo | Precisión «no» | Exhaustividad «no» | «no» humano | «no» Jev | n conf. ≥ umbral | Acuerdo conf. |
| --- | :-: | --: | --: | --: | --: | --: | --: | --: | --: |
| `saludo` |  | 40 | 97.5 % | 75.0 % | 100.0 % | 3 | 4 | 39 | 97.4 % |
| `verifica_identidad` | sí | 40 | 92.5 % | 100.0 % | 25.0 % | 4 | 1 | 36 | 100.0 % |
| `escucha_activa` |  | 40 | 100.0 % | 100.0 % | 100.0 % | 3 | 3 | 38 | 100.0 % |
| `diagnostico` |  | 40 | 95.0 % | — | 0.0 % | 2 | 0 | 37 | 97.3 % |
| `solucion_o_derivacion` |  | 40 | 90.0 % | 50.0 % | 75.0 % | 4 | 6 | 33 | 93.9 % |
| `tono_respetuoso` | sí | 40 | 100.0 % | 100.0 % | 100.0 % | 4 | 4 | 40 | 100.0 % |
| `compromiso_realista` | sí | 40 | 92.5 % | 57.1 % | 100.0 % | 4 | 7 | 12 | 100.0 % |
| `cierre` |  | 40 | 97.5 % | 75.0 % | 100.0 % | 3 | 4 | 40 | 97.5 % |

## Punto de decisión

Todos los ítems llegan al 85% de acuerdo. Se puede seguir.

### Cobertura del «no cumple»

El acuerdo de arriba tapa esto: cuando la falla es rara, un ítem puede
acertar el 95 % de las veces y no detectar casi ninguna. Por debajo del
50% de exhaustividad:

- `verifica_identidad` **(crítico)**: detecta 1 de 4 fallas reales (25.0 %).
  Se le escaparon: INT-019 con 0.70, INT-007 con 0.66, INT-027 con 0.59.
  Subiendo su umbral de cumplimiento por encima de 0.70 se detectarían todas.
- `diagnostico`: detecta 0 de 2 fallas reales (0.0 %).
  Se le escaparon: INT-027 con 0.87, INT-010 con 0.65.
  Subiendo su umbral de cumplimiento por encima de 0.87 se detectarían todas.

Un ítem crítico que no detecta las fallas es el peor caso para una
auditoría: la interacción pasa y nadie la revisa. Antes del piloto hay
que bajarle el umbral de cumplimiento a ese ítem, afinar sus criterios,
o mandarlo siempre a revisión humana.

## Los 5 peores desacuerdos

### 1. `saludo` en INT-035 · marcada como ambigua

- Humano: **cumple** · Jev: **no** (noul 0.08, confianza 0.84)
- Nota de la etiqueta: AMBIGUO: el saludo no dice el nombre del agente hasta el final y el cierre es escueto.

> Agente: Telco Hogar Empresas, buenas tardes. Cliente: Buenas, tengo el servicio del local caído. Agente: Enseguida. ¿Me confirma el RUC de la empresa? Cliente: [RUC]. Agente: Gracias, señor [NOMBRE]. Entonces el enlace del local comercial está sin servicio, ¿…

### 2. `solucion_o_derivacion` en INT-029

- Humano: **cumple** · Jev: **no** (noul 0.10, confianza 0.80)
- Nota de la etiqueta: Consulta comercial, sin gestión de cuenta.

> Agente: Telco Hogar, buenos días, le habla [NOMBRE]. Cliente: Buenos días, quería saber si tienen un plan más rápido que el mío. Agente: Con gusto. ¿Me confirma su cédula para ver qué tiene contratado? Cliente: [CEDULA]. Agente: Gracias, señor [NOMBRE]. Enton…

### 3. `cierre` en INT-035 · marcada como ambigua

- Humano: **cumple** · Jev: **no** (noul 0.11, confianza 0.78)
- Nota de la etiqueta: AMBIGUO: el saludo no dice el nombre del agente hasta el final y el cierre es escueto.

> Agente: Telco Hogar Empresas, buenas tardes. Cliente: Buenas, tengo el servicio del local caído. Agente: Enseguida. ¿Me confirma el RUC de la empresa? Cliente: [RUC]. Agente: Gracias, señor [NOMBRE]. Entonces el enlace del local comercial está sin servicio, ¿…

### 4. `diagnostico` en INT-027

- Humano: **no** · Jev: **cumple** (noul 0.87, confianza 0.74)
- Nota de la etiqueta: Peor caso: falla todo, incluidos los tres críticos.

> Agente: ¿Sí? Cliente: Buenas, tengo un problema grave con mi tarjeta. Agente: Dígame rápido que tengo cola. Cliente: Me clonaron la tarjeta, hay consumos de $780,00 que no hice. Agente: ¿Y usted le dio la tarjeta a alguien? Cliente: No, a nadie. Agente: Segur…

### 5. `solucion_o_derivacion` en INT-021

- Humano: **no** · Jev: **cumple** (noul 0.86, confianza 0.72)
- Nota de la etiqueta: Promete una visita que no puede agendar y no deja plazo ni área reales.

> Agente: Telco Hogar, buenas tardes, le habla [NOMBRE]. Cliente: Buenas, llevo cuatro días sin internet. Agente: Qué molestia, lo reviso. ¿Me confirma su cédula? Cliente: [CEDULA]. Agente: Gracias, señor [NOMBRE]. Entonces son cuatro días completos sin servici…

## Límites conocidos

- Los textos los escribimos nosotros, así que sobreestiman el acierto: no
  tienen los cortes, muletillas ni errores de una transcripción real. La
  validación de verdad es el piloto de la fase 6.
- Las etiquetas humanas son de un solo anotador, sin segunda opinión.
- El «no cumple» es minoritario en casi todos los ítems, así que la
  exhaustividad se calcula sobre pocos casos y se mueve mucho.
- El acuerdo depende del umbral de 0,5; un ítem puede mejorar solo con
  moverlo. La fase 5 fija los umbrales definitivos a partir de aquí.
- Jev lee la pregunta al pie de la letra (ver la documentación de
  jaggedness de jev-1.13). Varios desacuerdos salen de ahí: el agente sí
  hizo *una* pregunta concreta o sí dio *un* plazo, aunque la llamada
  entera fuera mala. Si eso molesta, hay que escribirlo en el criterio,
  no esperar que el modelo lea la intención.

