# Fase 2 — ¿Funciona Jev en español? (DETENIDA en el punto de decisión, sin cerrar)
- Qué cambió: `scripts/eval_jev.py` (métricas puras, modo --fake determinista y modo en vivo), `tests/test_eval_metrics.py`, `data/eval/informe.md` (corrida en vivo, 40/40 filas, 0 fallidas).
- Comando: `python -m unittest discover -s tests -v` → 58 tests, 0 fallos; `--fake` → 40 filas; en vivo → 40 filas, 37.423 tokens (coste en $ sin precio conocido).
- Resultado: 5/6 ítems ≥ 92,5 %; `despedida` 65 % (precisión del "no cumple" 48 %) → punto de decisión.
- Diagnóstico: en los peores casos (int_038 "…yo no se de eso, chao", int_027 "…no puedo hacer nada, adios") Jev acierta y la etiqueta humana está mal: la pregunta exige despedirse bien Y confirmar que no hay más dudas, y las etiquetas marcaron "cumple" con cualquier despedida. Es un error de etiquetado de la fase 1, no de idioma.
- Riesgo: datos sintéticos propios sobreestiman el acierto (límite conocido; se valida en el piloto).
- Reapertura (revisión reforzada): coste real en $ (solo entrada, $0,042/M), códigos de salida distintos (0 = todo evaluado y ≥ 85 %), abortar sin escribir si falla la autenticación, CSV validado (columna, etiqueta 0/1, id repetido), fake por id de fila y en `informe_fake.md` (ya no pisa el informe en vivo), confianza del Noul = |2p−1|. 77 tests, 0 fallos.
- Decisión del usuario: corregir etiquetas de `despedida` (15 de 1 → 0, etiquetadas a ciegas con la pregunta literal: despedida adecuada Y confirmar que no hay más dudas). Nueva medición en vivo: `despedida` 97,5 %, los 6 ítems ≥ 92,5 %, coste $0,0013. Fase cerrada.
- Límite conocido: `escucha` tiene exhaustividad del "no cumple" del 84,6 %; etiquetas sintéticas propias, se valida en el piloto.
