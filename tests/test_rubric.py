"""Tests de la rúbrica: carga, construcción de la petición y lectura tipada."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from jevqa.jev_client import FakeJev
from jevqa.rubric import (
    ID_MOTIVO,
    ID_RIESGO,
    RespuestaIncompleta,
    RespuestaInvalida,
    RubricaInvalida,
    build_request,
    load_rubric,
    parse_answer,
    parse_response,
)

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUBRICA_SOPORTE = os.path.join(RAIZ, "rubrics", "soporte_es.json")
FIXTURES = os.path.join(RAIZ, "tests", "fixtures")

#: Cómo se corresponde cada campo de la respuesta de la API con el registro
#: tipado que devuelve `parse_answer`. Si la API añade un campo y no está aquí,
#: el test de "sin pérdida de campos" falla y hay que decidir qué hacer con él.
EQUIVALENCIAS = {
    "type": "tipo",
    "noul": "valor",
    "choice": "valor",
    "score": "valor",
    "probabilities": "distribucion",
    "confidence": "confianza",
    "legend": "leyenda",
}

RUBRICA_MINIMA = {
    "id": "minima",
    "version": "1",
    "items": [{"id": "saluda", "pregunta": "¿Saluda?", "peso": 1, "critico": False}],
    "riesgo": {"pregunta": "¿Riesgo?", "niveles": ["Ninguno", "Bajo", "Medio", "Alto"]},
    "motivo": {"pregunta": "¿Motivo?", "opciones": {"soporte": "Soporte", "otro": "Otro"}},
}


def escribir_rubrica(datos: dict) -> str:
    """Deja una rúbrica en un archivo temporal y devuelve su ruta."""
    archivo = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    )
    with archivo:
        json.dump(datos, archivo, ensure_ascii=False)
    return archivo.name


def cargar_fixture() -> dict:
    with open(os.path.join(FIXTURES, "respuesta_jev.json"), encoding="utf-8") as archivo:
        return json.load(archivo)


class TestCargaRubrica(unittest.TestCase):
    def test_carga_la_rubrica_de_soporte(self):
        rubrica = load_rubric(RUBRICA_SOPORTE)
        self.assertEqual(rubrica["id"], "soporte_es")
        self.assertEqual(len(rubrica["items"]), 8)
        self.assertEqual(sum(item["peso"] for item in rubrica["items"]), 100)
        self.assertEqual(
            [item["id"] for item in rubrica["items"] if item["critico"]],
            ["verifica_identidad", "tono_respetuoso", "compromiso_realista"],
        )
        self.assertEqual(len(rubrica["riesgo"]["niveles"]), 4)
        self.assertIn("otro", rubrica["motivo"]["opciones"])

    def test_conserva_el_orden_de_los_items(self):
        rubrica = load_rubric(RUBRICA_SOPORTE)
        with open(RUBRICA_SOPORTE, encoding="utf-8") as archivo:
            crudo = json.load(archivo)
        self.assertEqual(
            [item["id"] for item in rubrica["items"]],
            [item["id"] for item in crudo["items"]],
        )

    def test_rubrica_inexistente(self):
        with self.assertRaises(RubricaInvalida):
            load_rubric(os.path.join(RAIZ, "rubrics", "no_existe.json"))

    def test_json_roto(self):
        ruta = os.path.join(tempfile.mkdtemp(), "rota.json")
        with open(ruta, "w", encoding="utf-8") as archivo:
            archivo.write("{esto no es json")
        with self.assertRaises(RubricaInvalida):
            load_rubric(ruta)

    def test_id_de_item_reservado(self):
        datos = json.loads(json.dumps(RUBRICA_MINIMA))
        datos["items"][0]["id"] = ID_RIESGO
        with self.assertRaises(RubricaInvalida) as ctx:
            load_rubric(escribir_rubrica(datos))
        self.assertIn("reservado", str(ctx.exception))

    def test_ids_repetidos(self):
        datos = json.loads(json.dumps(RUBRICA_MINIMA))
        datos["items"].append(dict(datos["items"][0]))
        with self.assertRaises(RubricaInvalida) as ctx:
            load_rubric(escribir_rubrica(datos))
        self.assertIn("repetido", str(ctx.exception))

    def test_motivo_sin_opcion_otro(self):
        datos = json.loads(json.dumps(RUBRICA_MINIMA))
        del datos["motivo"]["opciones"]["otro"]
        datos["motivo"]["opciones"]["ventas"] = "Ventas"
        with self.assertRaises(RubricaInvalida) as ctx:
            load_rubric(escribir_rubrica(datos))
        self.assertIn("otro", str(ctx.exception))

    def test_riesgo_con_un_solo_nivel(self):
        datos = json.loads(json.dumps(RUBRICA_MINIMA))
        datos["riesgo"]["niveles"] = ["Ninguno"]
        with self.assertRaises(RubricaInvalida):
            load_rubric(escribir_rubrica(datos))

    def test_peso_no_positivo(self):
        datos = json.loads(json.dumps(RUBRICA_MINIMA))
        datos["items"][0]["peso"] = 0
        with self.assertRaises(RubricaInvalida):
            load_rubric(escribir_rubrica(datos))

    def test_sin_items(self):
        datos = json.loads(json.dumps(RUBRICA_MINIMA))
        datos["items"] = []
        with self.assertRaises(RubricaInvalida):
            load_rubric(escribir_rubrica(datos))


class TestBuildRequest(unittest.TestCase):
    def test_rubrica_de_un_item_manda_tres_preguntas(self):
        rubrica = load_rubric(escribir_rubrica(RUBRICA_MINIMA))
        cuerpo = build_request(rubrica, "Hola, buenos días.")
        self.assertEqual(len(cuerpo["questions"]), 3)
        self.assertEqual(
            sorted(cuerpo["questions"]), sorted(["saluda", ID_RIESGO, ID_MOTIVO])
        )

    def test_rubrica_de_n_items_manda_n_mas_dos(self):
        rubrica = load_rubric(RUBRICA_SOPORTE)
        cuerpo = build_request(rubrica, "Hola, buenos días.")
        self.assertEqual(len(cuerpo["questions"]), len(rubrica["items"]) + 2)

    def test_el_texto_viaja_una_sola_vez(self):
        rubrica = load_rubric(RUBRICA_SOPORTE)
        texto = 'Agente: "buenos días"\nCliente: mi factura llegó en $42,50 — revísenla.'
        cuerpo = build_request(rubrica, texto)
        self.assertEqual(cuerpo["state"], texto)
        serializado = json.dumps(cuerpo, ensure_ascii=False)
        escapado = json.dumps(texto, ensure_ascii=False)[1:-1]
        self.assertEqual(serializado.count(escapado), 1)

    def test_tipos_y_criterios_de_cada_pregunta(self):
        rubrica = load_rubric(RUBRICA_SOPORTE)
        cuerpo = build_request(rubrica, "Texto de prueba.")
        preguntas = cuerpo["questions"]

        self.assertEqual(cuerpo["model"], "jev-latest")
        for item in rubrica["items"]:
            pregunta = preguntas[item["id"]]
            self.assertEqual(pregunta["type"], "noul")
            self.assertEqual(pregunta["instructions"], item["pregunta"])
            self.assertEqual(sorted(pregunta["criteria"]), ["false", "true"])

        self.assertEqual(preguntas[ID_RIESGO]["type"], "score")
        self.assertEqual(len(preguntas[ID_RIESGO]["criteria"]), 4)
        self.assertEqual(preguntas[ID_MOTIVO]["type"], "choice")
        self.assertIn("otro", preguntas[ID_MOTIVO]["criteria"])

    def test_texto_vacio(self):
        rubrica = load_rubric(RUBRICA_SOPORTE)
        with self.assertRaises(RubricaInvalida):
            build_request(rubrica, "   ")


class TestParseResponse(unittest.TestCase):
    def setUp(self):
        self.rubrica = load_rubric(RUBRICA_SOPORTE)
        self.fixture = cargar_fixture()

    def test_respuesta_completa(self):
        resultado = parse_response(self.rubrica, self.fixture["completa"])

        self.assertEqual(resultado["modelo"], "jev-1.13.0")
        self.assertEqual(len(resultado["items"]), 8)
        self.assertEqual(
            list(resultado["items"]), [item["id"] for item in self.rubrica["items"]]
        )
        self.assertEqual(resultado["uso"], {"tokens_entrada": 1642, "tokens_salida": 96})

        saludo = resultado["items"]["saludo"]
        self.assertAlmostEqual(saludo["probabilidad"], 0.97)
        self.assertAlmostEqual(saludo["confianza"], 0.94)
        self.assertAlmostEqual(sum(saludo["distribucion"].values()), 1.0)
        self.assertEqual(saludo["peso"], 5)
        self.assertFalse(saludo["critico"])
        self.assertTrue(resultado["items"]["verifica_identidad"]["critico"])

        self.assertEqual(resultado["riesgo"]["nivel"], 2)
        self.assertTrue(resultado["riesgo"]["etiqueta"].startswith("Medio"))
        self.assertAlmostEqual(resultado["riesgo"]["valor"], 2.13)
        self.assertEqual(resultado["motivo"]["valor"], "facturacion")
        self.assertAlmostEqual(resultado["motivo"]["probabilidad"], 0.79)

    def test_confianza_derivada_del_noul(self):
        # Un noul de 0,48 está casi en la frontera: confianza casi nula.
        registro = parse_answer("noul", {"type": "noul", "noul": 0.48})
        self.assertAlmostEqual(registro["confianza"], 0.04)
        # Un noul de 0,06 es un "no" claro: confianza alta pese al valor bajo.
        registro = parse_answer("noul", {"type": "noul", "noul": 0.06})
        self.assertAlmostEqual(registro["confianza"], 0.88)

    def test_falta_una_pregunta(self):
        datos = json.loads(json.dumps(self.fixture["completa"]))
        del datos["answers"]["cierre"]
        with self.assertRaises(RespuestaIncompleta) as ctx:
            parse_response(self.rubrica, datos)
        self.assertEqual(ctx.exception.faltantes, ["cierre"])

    def test_faltan_riesgo_y_motivo(self):
        datos = json.loads(json.dumps(self.fixture["completa"]))
        del datos["answers"][ID_RIESGO]
        del datos["answers"][ID_MOTIVO]
        with self.assertRaises(RespuestaIncompleta) as ctx:
            parse_response(self.rubrica, datos)
        self.assertEqual(ctx.exception.faltantes, [ID_RIESGO, ID_MOTIVO])

    def test_respuesta_con_tipo_equivocado(self):
        datos = json.loads(json.dumps(self.fixture["completa"]))
        datos["answers"]["saludo"] = {"type": "choice", "choice": "si"}
        with self.assertRaises(RespuestaInvalida):
            parse_response(self.rubrica, datos)

    def test_respuesta_sin_answers(self):
        with self.assertRaises(RespuestaInvalida):
            parse_response(self.rubrica, {"model": "jev-1.13.0"})

    def test_respuesta_sin_uso(self):
        datos = json.loads(json.dumps(self.fixture["completa"]))
        del datos["usage"]
        resultado = parse_response(self.rubrica, datos)
        self.assertEqual(resultado["uso"], {"tokens_entrada": 0, "tokens_salida": 0})


class TestEjemplosDeLaDocumentacion(unittest.TestCase):
    """La respuesta de ejemplo de la documentación se interpreta sin pérdida."""

    def setUp(self):
        self.documentacion = cargar_fixture()["documentacion"]

    def comprobar_sin_perdida(self, respuesta: dict, registro: dict) -> None:
        for campo, valor in respuesta.items():
            self.assertIn(campo, EQUIVALENCIAS, f"campo nuevo en la API: {campo}")
            destino = EQUIVALENCIAS[campo]
            self.assertIn(destino, registro, f"{campo} se perdió al interpretar")
            if campo == "type":
                self.assertEqual(registro[destino], valor)
            elif campo in ("probabilities", "legend"):
                self.assertEqual(registro[destino], valor)
            else:
                self.assertAlmostEqual(registro[destino], valor)

    def test_ejemplo_noul(self):
        respuesta = self.documentacion["noul"]["answers"]["is_urgent"]
        registro = parse_answer("noul", respuesta)
        self.comprobar_sin_perdida(respuesta, registro)
        self.assertAlmostEqual(registro["distribucion"]["si"], 0.95)
        self.assertAlmostEqual(registro["distribucion"]["no"], 0.05)

    def test_ejemplo_choice(self):
        respuesta = self.documentacion["choice"]["answers"]["department"]
        registro = parse_answer("choice", respuesta)
        self.comprobar_sin_perdida(respuesta, registro)
        self.assertEqual(registro["valor"], "billing")
        self.assertAlmostEqual(registro["probabilidad"], 0.88)

    def test_ejemplo_score(self):
        respuesta = self.documentacion["score"]["answers"]["frustration"]
        registro = parse_answer("score", respuesta)
        self.comprobar_sin_perdida(respuesta, registro)
        self.assertEqual(registro["nivel"], 1)
        self.assertEqual(registro["etiqueta"], "Frustrated")

    def test_score_sin_leyenda_usa_los_niveles_de_la_rubrica(self):
        respuesta = json.loads(json.dumps(self.documentacion["score"]["answers"]["frustration"]))
        del respuesta["legend"]
        registro = parse_answer("score", respuesta, niveles=["Calma", "Molesto", "Furioso"])
        self.assertEqual(registro["etiqueta"], "Molesto")


class TestRecorridoCompleto(unittest.TestCase):
    def test_build_request_fakejev_parse_response(self):
        rubrica = load_rubric(RUBRICA_SOPORTE)
        cliente = FakeJev()
        texto = "Agente: buenos días, le habla Rosa de Telco. Cliente: me cobraron dos veces."

        resultado = parse_response(rubrica, cliente.evaluar(build_request(rubrica, texto)))

        self.assertEqual(len(cliente.llamadas), 1)
        self.assertEqual(len(resultado["respuestas"]), len(rubrica["items"]) + 2)
        for registro in resultado["items"].values():
            self.assertEqual(registro["tipo"], "noul")
            self.assertTrue(0.0 <= registro["probabilidad"] <= 1.0)
        self.assertIn(resultado["motivo"]["valor"], rubrica["motivo"]["opciones"])
        self.assertIn(resultado["riesgo"]["nivel"], range(4))
        self.assertGreater(resultado["uso"]["tokens_entrada"], 0)

    def test_fakejev_es_determinista(self):
        rubrica = load_rubric(RUBRICA_SOPORTE)
        peticion = build_request(rubrica, "El mismo texto siempre.")
        self.assertEqual(FakeJev().evaluar(peticion), FakeJev().evaluar(peticion))


if __name__ == "__main__":
    unittest.main()
