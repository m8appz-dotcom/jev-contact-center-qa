# ¿Funciona Jev en español? — informe de la fase 2

- Fecha: 2026-09-21
- Modo: **fake**
- Rúbrica: `soporte_es` v1.0 (8 ítems)
- Interacciones evaluadas: **40** de 40
- Umbral de cumplimiento: noul ≥ 0.5 · umbral de confianza: 0.7
- Tokens de entrada: 55,401 · de salida: 4,000
- Coste: $0.002327

> **Este informe no mide nada.** Está generado con `FakeJev`, que inventa
> números deterministas a partir del texto. Sirve para comprobar que el
> evaluador corre de punta a punta; las cifras de acuerdo son ruido.

## Acuerdo por ítem

La clase positiva es el **no cumple**: lo que una auditoría necesita detectar.

| Ítem | Crítico | n | Acuerdo | Precisión «no» | Exhaustividad «no» | «no» humano | «no» Jev | n conf. ≥ umbral | Acuerdo conf. |
| --- | :-: | --: | --: | --: | --: | --: | --: | --: | --: |
| `saludo` |  | 40 | 55.0 % | 14.3 % | 100.0 % | 3 | 21 | 18 | 66.7 % |
| `verifica_identidad` | sí | 40 | 52.5 % | 14.3 % | 75.0 % | 4 | 21 | 12 | 58.3 % |
| `escucha_activa` |  | 40 | 50.0 % | 9.5 % | 66.7 % | 3 | 21 | 7 | 28.6 % |
| `diagnostico` |  | 40 | 42.5 % | 4.3 % | 50.0 % | 2 | 23 | 9 | 44.4 % |
| `solucion_o_derivacion` |  | 40 | 55.0 % | 11.1 % | 50.0 % | 4 | 18 | 16 | 50.0 % |
| `tono_respetuoso` | sí | 40 | 47.5 % | 9.5 % | 50.0 % | 4 | 21 | 13 | 38.5 % |
| `compromiso_realista` | sí | 40 | 40.0 % | 8.3 % | 50.0 % | 4 | 24 | 12 | 16.7 % |
| `cierre` |  | 40 | 55.0 % | 10.5 % | 66.7 % | 3 | 19 | 12 | 66.7 % |

## Punto de decisión

**8 ítem(s) por debajo del 85% de acuerdo:** `saludo`, `verifica_identidad`, `escucha_activa`, `diagnostico`, `solucion_o_derivacion`, `tono_respetuoso`, `compromiso_realista`, `cierre`

Opciones, según el plan: reformular el ítem en inglés, traducir el texto
antes de enviarlo, o quitar el ítem de la rúbrica.

## Los 5 peores desacuerdos

### 1. `saludo` en INT-036 · marcada como ambigua

- Humano: **cumple** · Jev: **no** (noul 0.00, confianza 0.99)
- Nota de la etiqueta: AMBIGUO: verifica con un dato débil (solo el número de póliza) y el compromiso queda en el límite.

> Agente: Seguros Andinos, buenos días, le habla Andrés Villamar. Cliente: Buenos días, me subió la prima y no me avisaron. Agente: Lo reviso. ¿Me da su número de póliza? Cliente: 1009876543. Agente: Gracias, señora Mantilla. Entonces usted vio un incremento en…

### 2. `solucion_o_derivacion` en INT-017

- Humano: **cumple** · Jev: **no** (noul 0.01, confianza 0.98)
- Nota de la etiqueta: Alta de dependiente, todo correcto.

> Agente: Seguros Andinos, buenas tardes, le habla Mishell Quiroz. Cliente: Buenas, quiero incluir a mi esposa en la póliza. Agente: Con gusto. ¿Me confirma su cédula, por favor? Cliente: 1302345614. Agente: Gracias, señor Cabrera. Entonces desea agregar a su c…

### 3. `escucha_activa` en INT-017

- Humano: **cumple** · Jev: **no** (noul 0.01, confianza 0.98)
- Nota de la etiqueta: Alta de dependiente, todo correcto.

> Agente: Seguros Andinos, buenas tardes, le habla Mishell Quiroz. Cliente: Buenas, quiero incluir a mi esposa en la póliza. Agente: Con gusto. ¿Me confirma su cédula, por favor? Cliente: 1302345614. Agente: Gracias, señor Cabrera. Entonces desea agregar a su c…

### 4. `solucion_o_derivacion` en INT-021

- Humano: **no** · Jev: **cumple** (noul 0.99, confianza 0.98)
- Nota de la etiqueta: Promete una visita que no puede agendar y no deja plazo ni área reales.

> Agente: Telco Hogar, buenas tardes, le habla Jhoanna Pérez. Cliente: Buenas, llevo cuatro días sin internet. Agente: Qué molestia, lo reviso. ¿Me confirma su cédula? Cliente: 2403456789. Agente: Gracias, señor Tapia. Entonces son cuatro días completos sin ser…

### 5. `compromiso_realista` en INT-030

- Humano: **cumple** · Jev: **no** (noul 0.01, confianza 0.98)
- Nota de la etiqueta: Consulta de aumento de cupo con expectativa bien manejada.

> Agente: Banco del Litoral, buenos días, le atiende Andrés Villamar. Cliente: Buenos días, quiero pedir aumento de cupo. Agente: Claro. ¿Me confirma su cédula? Cliente: 1102233440. Agente: Gracias, señora Robles. Entonces solicita una ampliación del cupo de su…

## Límites conocidos

- Los textos los escribimos nosotros, así que sobreestiman el acierto: no
  tienen los cortes, muletillas ni errores de una transcripción real. La
  validación de verdad es el piloto de la fase 6.
- Las etiquetas humanas son de un solo anotador, sin segunda opinión.
- El «no cumple» es minoritario en casi todos los ítems, así que la
  exhaustividad se calcula sobre pocos casos y se mueve mucho.
- El acuerdo depende del umbral de 0,5; un ítem puede mejorar solo con
  moverlo. La fase 5 fija los umbrales definitivos a partir de aquí.

