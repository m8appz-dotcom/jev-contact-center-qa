"""Tests de la nota, los umbrales y la cola de revisión."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from jevqa.jev_client import FakeJev
from jevqa.rubric import build_request, load_rubric, parse_response
from jevqa.scoring import (
    ESTADO_APROBADO,
    ESTADO_SUSPENSO,
    MUESTRA_MINIMA,
    REVISION_AMBIGUA,
    REVISION_CONFIANZA,
    SIN_CAMPANA,
    ResultadoIncompleto,
    UmbralInvalido,
    agregar,
    calificar,
    cola_de_revision,
    describir,
    resolver_umbrales,
    umbral_de_item,
)

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUBRICA_REAL = os.path.join(RAIZ, "rubrics", "soporte_es.json")

#: Rúbrica de tres ítems con los pesos repartidos para que cada caso de prueba
#: dé una nota redonda. `verifica_identidad` pesa poco y es crítico, igual que
#: en la rúbrica real: es el caso que importa, nota alta y suspenso.
ITEMS = [
    {"id": "saludo", "pregunta": "¿Saluda?", "peso": 30, "critico": False},
    {"id": "verifica_identidad", "pregunta": "¿Verifica?", "peso": 10, "critico": True},
    {"id": "cierre", "pregunta": "¿Cierra?", "peso": 60, "critico": False},
]
NIVELES = ["Ninguno: nada pendiente.", "Alto: puede terminar en reclamo."]
OPCIONES = {"informacion": "Una consulta sin gestión.", "otro": "Ninguna de las anteriores."}

#: Probabilidades que dan «cumple» con confianza alta: |2·0,95 − 1| = 0,9.
TODO_BIEN = {"saludo": 0.95, "verifica_identidad": 0.95, "cierre": 0.95}


def escribir_rubrica(**extra) -> str:
    ruta = os.path.join(tempfile.mkdtemp(), "rubrica.json")
    cruda = {
        "id": "prueba",
        "version": "1.0",
        "items": ITEMS,
        "riesgo": {"pregunta": "¿Riesgo?", "niveles": NIVELES},
        "motivo": {"pregunta": "¿Motivo?", "opciones": OPCIONES},
    }
    cruda.update(extra)
    with open(ruta, "w", encoding="utf-8") as archivo:
        json.dump(cruda, archivo, ensure_ascii=False)
    return ruta


def respuesta_api(probabilidades: dict, *, nivel: int = 0, motivo: str = "informacion") -> dict:
    """La respuesta cruda de la API con esas probabilidades por ítem."""
    respuestas = {
        qid: {"type": "noul", "noul": prob} for qid, prob in probabilidades.items()
    }
    respuestas["riesgo"] = {
        "type": "score",
        "score": float(nivel),
        "confidence": 0.9,
        "probabilities": {"0": 0.9, "1": 0.1} if nivel == 0 else {"0": 0.1, "1": 0.9},
        "legend": {str(i): texto for i, texto in enumerate(NIVELES)},
    }
    respuestas["motivo"] = {
        "type": "choice",
        "choice": motivo,
        "confidence": 0.9,
        "probabilities": {"informacion": 0.9, "otro": 0.1},
    }
    return {
        "model": "jev-1.13.0-test",
        "answers": respuestas,
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }


class Caso(unittest.TestCase):
    def setUp(self):
        self.rubrica = load_rubric(escribir_rubrica())

    def calificar(self, probabilidades: dict, *, rubrica=None, **kwargs) -> dict:
        """Del diccionario de probabilidades a la calificación, pasando por la API."""
        rubrica = rubrica if rubrica is not None else self.rubrica
        resultado = parse_response(rubrica, respuesta_api(probabilidades))
        return calificar(rubrica, resultado, **kwargs)


# ---------------------------------------------------------------------------
# Nota y estado
# ---------------------------------------------------------------------------

class Nota(Caso):
    def test_todo_cumple(self):
        calificacion = self.calificar(TODO_BIEN)
        self.assertEqual(calificacion["nota"], 100.0)
        self.assertEqual(calificacion["estado"], ESTADO_APROBADO)
        self.assertEqual(calificacion["criticas_falladas"], [])
        self.assertFalse(calificacion["revisar"])
        self.assertEqual(calificacion["items_a_revisar"], [])

    def test_nota_ponderada_por_los_pesos(self):
        """Falla `saludo`, que pesa 30 de 100: quedan 70 y aprueba justo."""
        calificacion = self.calificar({**TODO_BIEN, "saludo": 0.05})
        self.assertEqual(calificacion["nota"], 70.0)
        self.assertEqual(calificacion["estado"], ESTADO_APROBADO)
        self.assertFalse(calificacion["items"]["saludo"]["cumple"])
        self.assertTrue(calificacion["items"]["cierre"]["cumple"])

    def test_nota_bajo_el_umbral_suspende_sin_criticas(self):
        calificacion = self.calificar({**TODO_BIEN, "cierre": 0.05})
        self.assertEqual(calificacion["nota"], 40.0)
        self.assertEqual(calificacion["estado"], ESTADO_SUSPENSO)
        self.assertEqual(calificacion["criticas_falladas"], [])

    def test_falla_un_critico(self):
        """Nota alta y suspenso: es justo el caso que la crítica tiene que cazar."""
        calificacion = self.calificar({**TODO_BIEN, "verifica_identidad": 0.05})
        self.assertEqual(calificacion["nota"], 90.0)
        self.assertEqual(calificacion["estado"], ESTADO_SUSPENSO)
        self.assertEqual(calificacion["criticas_falladas"], ["verifica_identidad"])

    def test_todo_falla(self):
        calificacion = self.calificar({qid: 0.05 for qid in TODO_BIEN})
        self.assertEqual(calificacion["nota"], 0.0)
        self.assertEqual(calificacion["estado"], ESTADO_SUSPENSO)
        self.assertEqual(calificacion["criticas_falladas"], ["verifica_identidad"])

    def test_la_probabilidad_justa_en_el_umbral_cumple(self):
        calificacion = self.calificar({**TODO_BIEN, "saludo": 0.5})
        self.assertTrue(calificacion["items"]["saludo"]["cumple"])
        self.assertEqual(calificacion["nota"], 100.0)

    def test_meta_se_copia_en_la_calificacion(self):
        meta = {
            "id": "INT-001",
            "agente": "  Rosa Delgado ",
            "campaña": "telco_hogar",
            "fecha": "2026-08-03",
        }
        calificacion = self.calificar(TODO_BIEN, meta=meta)
        self.assertEqual(calificacion["id"], "INT-001")
        self.assertEqual(calificacion["agente"], "Rosa Delgado")
        self.assertEqual(calificacion["campaña"], "telco_hogar")
        self.assertEqual(calificacion["fecha"], "2026-08-03")

    def test_sin_meta_los_campos_quedan_vacios(self):
        calificacion = self.calificar(TODO_BIEN)
        self.assertEqual(calificacion["id"], "")
        self.assertEqual(calificacion["agente"], "")
        self.assertEqual(calificacion["campaña"], "")

    def test_resultado_al_que_le_falta_un_item(self):
        resultado = parse_response(self.rubrica, respuesta_api(TODO_BIEN))
        del resultado["items"]["cierre"]
        with self.assertRaises(ResultadoIncompleto) as contexto:
            calificar(self.rubrica, resultado)
        self.assertEqual(contexto.exception.faltantes, ["cierre"])
        self.assertIn("cierre", str(contexto.exception))

    def test_riesgo_y_motivo_viajan_con_la_calificacion(self):
        """El informe de la fase 6 los necesita y no debe volver a la respuesta cruda."""
        calificacion = self.calificar(TODO_BIEN)
        self.assertEqual(calificacion["motivo"]["valor"], "informacion")
        self.assertEqual(calificacion["riesgo"]["nivel"], 0)


# ---------------------------------------------------------------------------
# Revisión humana
# ---------------------------------------------------------------------------

class Revision(Caso):
    def test_item_ambiguo_va_a_revision(self):
        """0,5 está en la banda 0,35–0,65 y además deja la confianza en 0."""
        calificacion = self.calificar({**TODO_BIEN, "cierre": 0.5})
        self.assertTrue(calificacion["revisar"])
        self.assertEqual(calificacion["items_a_revisar"], ["cierre"])
        self.assertTrue(calificacion["items"]["cierre"]["ambiguo"])
        self.assertEqual(
            calificacion["items"]["cierre"]["motivos_revision"],
            [REVISION_CONFIANZA, REVISION_AMBIGUA],
        )

    def test_poca_confianza_fuera_de_la_banda_ambigua(self):
        """0,8 decide con claridad hacia «cumple», pero |2·0,8 − 1| = 0,6 < 0,7."""
        calificacion = self.calificar({**TODO_BIEN, "saludo": 0.8})
        self.assertTrue(calificacion["revisar"])
        self.assertFalse(calificacion["items"]["saludo"]["ambiguo"])
        self.assertTrue(calificacion["items"]["saludo"]["poca_confianza"])
        self.assertEqual(calificacion["motivos_revision"], [REVISION_CONFIANZA])

    def test_una_ambigua_no_arrastra_a_las_demas(self):
        calificacion = self.calificar({**TODO_BIEN, "cierre": 0.5})
        self.assertFalse(calificacion["items"]["saludo"]["poca_confianza"])
        self.assertFalse(calificacion["items"]["saludo"]["ambiguo"])

    def test_la_cola_pone_las_criticas_primero(self):
        cola = cola_de_revision(
            [
                {"id": "B", "nota": 20.0, "revisar": True, "criticas_falladas": []},
                {"id": "A", "nota": 95.0, "revisar": True, "criticas_falladas": ["x"]},
                {"id": "C", "nota": 10.0, "revisar": False, "criticas_falladas": ["x"]},
                {"id": "D", "nota": 80.0, "revisar": True, "criticas_falladas": []},
            ]
        )
        self.assertEqual([c["id"] for c in cola], ["A", "B", "D"])

    def test_la_cola_vacia_no_falla(self):
        self.assertEqual(cola_de_revision([]), [])
        self.assertEqual(cola_de_revision([self.calificar(TODO_BIEN)]), [])


# ---------------------------------------------------------------------------
# Umbrales
# ---------------------------------------------------------------------------

class Umbrales(Caso):
    def test_por_defecto(self):
        umbrales = resolver_umbrales(self.rubrica)
        self.assertEqual(umbrales["cumple"], 0.5)
        self.assertEqual(umbrales["confianza"], 0.7)
        self.assertEqual(umbrales["ambiguo_min"], 0.35)
        self.assertEqual(umbrales["ambiguo_max"], 0.65)
        self.assertEqual(umbrales["aprobado"], 70.0)

    def test_la_rubrica_manda_sobre_los_valores_por_defecto(self):
        rubrica = load_rubric(escribir_rubrica(umbrales={"aprobado": 95}))
        calificacion = self.calificar({**TODO_BIEN, "saludo": 0.05}, rubrica=rubrica)
        self.assertEqual(calificacion["nota"], 70.0)
        self.assertEqual(calificacion["estado"], ESTADO_SUSPENSO)

    def test_umbral_por_item(self):
        """La fase 2 pide subir el umbral de `verifica_identidad`, no el de todos."""
        rubrica = load_rubric(escribir_rubrica(umbrales={"cumple_verifica_identidad": 0.75}))
        umbrales = resolver_umbrales(rubrica)
        self.assertEqual(umbral_de_item(umbrales, "verifica_identidad"), 0.75)
        self.assertEqual(umbral_de_item(umbrales, "saludo"), 0.5)

        calificacion = self.calificar(
            {**TODO_BIEN, "verifica_identidad": 0.7, "saludo": 0.7}, rubrica=rubrica
        )
        self.assertEqual(calificacion["criticas_falladas"], ["verifica_identidad"])
        self.assertTrue(calificacion["items"]["saludo"]["cumple"])

    def test_extra_manda_sobre_la_rubrica(self):
        rubrica = load_rubric(escribir_rubrica(umbrales={"cumple": 0.9}))
        umbrales = resolver_umbrales(rubrica, {"cumple": 0.4})
        self.assertEqual(umbrales["cumple"], 0.4)

    def test_umbral_desconocido(self):
        rubrica = load_rubric(escribir_rubrica(umbrales={"cumple_inventado": 0.5}))
        with self.assertRaises(UmbralInvalido) as contexto:
            resolver_umbrales(rubrica)
        self.assertIn("cumple_inventado", str(contexto.exception))

    def test_umbral_fuera_de_rango(self):
        rubrica = load_rubric(escribir_rubrica(umbrales={"confianza": 1.5}))
        with self.assertRaises(UmbralInvalido) as contexto:
            resolver_umbrales(rubrica)
        self.assertIn("confianza", str(contexto.exception))

    def test_banda_ambigua_invertida(self):
        rubrica = load_rubric(escribir_rubrica(umbrales={"ambiguo_min": 0.8}))
        with self.assertRaises(UmbralInvalido) as contexto:
            resolver_umbrales(rubrica)
        self.assertIn("ambiguo_min", str(contexto.exception))

    def test_umbral_no_numerico(self):
        with self.assertRaises(UmbralInvalido):
            resolver_umbrales(self.rubrica, {"cumple": "alto"})

    def test_umbrales_se_pueden_reutilizar_entre_llamadas(self):
        umbrales = resolver_umbrales(self.rubrica, {"aprobado": 100})
        calificacion = self.calificar({**TODO_BIEN, "saludo": 0.05}, umbrales=umbrales)
        self.assertEqual(calificacion["estado"], ESTADO_SUSPENSO)


# ---------------------------------------------------------------------------
# Agregados
# ---------------------------------------------------------------------------

def calificacion_falsa(**extra) -> dict:
    base = {
        "id": "INT-000",
        "agente": "Rosa Delgado",
        "campaña": "telco_hogar",
        "nota": 100.0,
        "estado": ESTADO_APROBADO,
        "criticas_falladas": [],
        "revisar": False,
    }
    base.update(extra)
    return base


class Agregados(unittest.TestCase):
    def test_lista_vacia(self):
        agregados = agregar([])
        self.assertEqual(agregados["agentes"], [])
        self.assertEqual(agregados["campanas"], [])
        self.assertEqual(agregados["total"]["interacciones"], 0)
        self.assertEqual(agregados["total"]["nota_media"], 0.0)
        self.assertEqual(agregados["total"]["porcentaje_criticas"], 0.0)

    def test_un_agente_con_una_interaccion_frente_a_otro_con_muchas(self):
        """El de una sola llamada no puede encabezar un ranking: va marcado."""
        calificaciones = [
            calificacion_falsa(id="INT-001", agente="Nuevo", nota=100.0),
        ]
        for numero in range(MUESTRA_MINIMA + 1):
            calificaciones.append(
                calificacion_falsa(
                    id=f"INT-1{numero:02d}",
                    agente="Veterana",
                    nota=80.0 if numero else 50.0,
                )
            )

        agentes = {grupo["clave"]: grupo for grupo in agregar(calificaciones)["agentes"]}
        self.assertEqual(agentes["Nuevo"]["interacciones"], 1)
        self.assertEqual(agentes["Nuevo"]["nota_media"], 100.0)
        self.assertFalse(agentes["Nuevo"]["muestra_suficiente"])

        self.assertEqual(agentes["Veterana"]["interacciones"], MUESTRA_MINIMA + 1)
        self.assertEqual(agentes["Veterana"]["nota_media"], 75.0)
        self.assertEqual(agentes["Veterana"]["nota_minima"], 50.0)
        self.assertEqual(agentes["Veterana"]["nota_maxima"], 80.0)
        self.assertTrue(agentes["Veterana"]["muestra_suficiente"])

    def test_el_peor_va_primero(self):
        agregados = agregar(
            [
                calificacion_falsa(id="A", agente="Buena", nota=90.0),
                calificacion_falsa(id="B", agente="Mala", nota=40.0),
            ]
        )
        self.assertEqual([g["clave"] for g in agregados["agentes"]], ["Mala", "Buena"])

    def test_campana_vacia(self):
        agregados = agregar(
            [
                calificacion_falsa(id="A", campaña=""),
                calificacion_falsa(id="B", campaña="   "),
                calificacion_falsa(id="C", campaña="telco_hogar"),
            ]
        )
        campanas = {grupo["clave"]: grupo for grupo in agregados["campanas"]}
        self.assertEqual(sorted(campanas), sorted([SIN_CAMPANA, "telco_hogar"]))
        self.assertEqual(campanas[SIN_CAMPANA]["interacciones"], 2)

    def test_porcentaje_de_criticas_y_cola(self):
        agregados = agregar(
            [
                calificacion_falsa(id="A", nota=90.0, estado=ESTADO_SUSPENSO,
                                   criticas_falladas=["verifica_identidad"]),
                calificacion_falsa(id="B", nota=100.0, revisar=True),
                calificacion_falsa(id="C", nota=100.0),
                calificacion_falsa(id="D", nota=100.0),
            ]
        )
        total = agregados["total"]
        self.assertEqual(total["interacciones"], 4)
        self.assertEqual(total["criticas"], 1)
        self.assertEqual(total["porcentaje_criticas"], 25.0)
        self.assertEqual(total["suspensos"], 1)
        self.assertEqual(total["porcentaje_suspensos"], 25.0)
        self.assertEqual(total["cola"], 1)
        self.assertEqual(total["porcentaje_cola"], 25.0)
        self.assertEqual(total["nota_media"], 97.5)


# ---------------------------------------------------------------------------
# De punta a punta con la rúbrica real
# ---------------------------------------------------------------------------

class RubricaReal(unittest.TestCase):
    def test_califica_lo_que_devuelve_fakejev(self):
        rubrica = load_rubric(RUBRICA_REAL)
        cliente = FakeJev()
        calificaciones = []
        for numero in range(6):
            texto = f"Agente: buenos días, llamada número {numero}."
            resultado = parse_response(rubrica, cliente.evaluar(build_request(rubrica, texto)))
            calificaciones.append(
                calificar(
                    rubrica,
                    resultado,
                    meta={"id": f"INT-{numero:03d}", "agente": "Rosa", "campaña": "telco"},
                )
            )

        for calificacion in calificaciones:
            self.assertTrue(0.0 <= calificacion["nota"] <= 100.0)
            self.assertIn(calificacion["estado"], (ESTADO_APROBADO, ESTADO_SUSPENSO))
            self.assertEqual(len(calificacion["items"]), len(rubrica["items"]))

        agregados = agregar(calificaciones)
        self.assertEqual(agregados["total"]["interacciones"], 6)
        self.assertTrue(agregados["agentes"][0]["muestra_suficiente"])
        self.assertEqual(
            agregados["total"]["cola"], len(cola_de_revision(calificaciones))
        )

    def test_describir_una_calificacion(self):
        rubrica = load_rubric(escribir_rubrica())
        resultado = parse_response(rubrica, respuesta_api({**TODO_BIEN, "verifica_identidad": 0.05}))
        linea = describir(calificar(rubrica, resultado, meta={"id": "INT-007"}))
        self.assertIn("INT-007", linea)
        self.assertIn("90.0", linea)
        self.assertIn(ESTADO_SUSPENSO, linea)
        self.assertIn("verifica_identidad", linea)


if __name__ == "__main__":
    unittest.main()
