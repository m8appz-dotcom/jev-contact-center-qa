import csv
import json
import os
import unittest

from jevqa import rubric

RUBRIC_PATH = os.path.join(
    os.path.dirname(__file__), "..", "rubrics", "soporte_es.json"
)
FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "fixtures", "respuesta_jev.json"
)
SINTETICAS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "eval", "sinteticas.csv"
)


def one_item_rubric():
    return {
        "items": [
            {"id": "saludo", "pregunta": "¿Saluda?", "peso": 1.0, "critico": False}
        ],
        "riesgo": {
            "pregunta": "¿Riesgo?",
            "niveles": ["nulo", "bajo", "alto", "critico"],
        },
        "motivo": {
            "pregunta": "¿Motivo?",
            "opciones": {"a": "opcion a", "otro": "otra cosa"},
        },
    }


class LoadRubricTests(unittest.TestCase):
    def test_carga_la_rubrica_del_repo(self):
        r = rubric.load_rubric(RUBRIC_PATH)
        self.assertGreaterEqual(len(r["items"]), 1)
        self.assertEqual(len(r["riesgo"]["niveles"]), 4)
        self.assertIn("otro", r["motivo"]["opciones"])

    def test_rubrica_sin_niveles_de_riesgo_correctos_falla(self):
        bad = one_item_rubric()
        bad["riesgo"]["niveles"] = ["solo dos", "niveles"]
        path = "_tmp_bad_rubric.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(bad, f)
        try:
            with self.assertRaises(rubric.RubricError):
                rubric.load_rubric(path)
        finally:
            os.remove(path)

    def test_rubrica_sin_opcion_otro_falla(self):
        bad = one_item_rubric()
        del bad["motivo"]["opciones"]["otro"]
        path = "_tmp_bad_rubric2.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(bad, f)
        try:
            with self.assertRaises(rubric.RubricError):
                rubric.load_rubric(path)
        finally:
            os.remove(path)

    def _load_bad(self, bad, name):
        path = f"_tmp_{name}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(bad, f)
        try:
            with self.assertRaises(rubric.RubricError):
                rubric.load_rubric(path)
        finally:
            os.remove(path)

    def test_rubrica_que_no_es_un_objeto_falla(self):
        path = "_tmp_bad_rubric_list.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(["no", "es", "un", "objeto"], f)
        try:
            with self.assertRaises(rubric.RubricError):
                rubric.load_rubric(path)
        finally:
            os.remove(path)

    def test_ids_de_item_duplicados_falla(self):
        bad = one_item_rubric()
        bad["items"].append(dict(bad["items"][0]))
        self._load_bad(bad, "dup_ids")

    def test_id_de_item_igual_a_riesgo_falla(self):
        bad = one_item_rubric()
        bad["items"][0]["id"] = "riesgo"
        self._load_bad(bad, "id_riesgo")

    def test_id_de_item_igual_a_motivo_falla(self):
        bad = one_item_rubric()
        bad["items"][0]["id"] = "motivo"
        self._load_bad(bad, "id_motivo")

    def test_items_no_es_una_lista_falla(self):
        bad = one_item_rubric()
        bad["items"] = {"saludo": "no es lista"}
        self._load_bad(bad, "items_not_list")

    def test_niveles_de_riesgo_no_es_lista_falla(self):
        bad = one_item_rubric()
        bad["riesgo"]["niveles"] = "no es lista"
        self._load_bad(bad, "niveles_not_list")

    def test_opciones_de_motivo_no_es_objeto_falla(self):
        bad = one_item_rubric()
        bad["motivo"]["opciones"] = ["no", "es", "objeto"]
        self._load_bad(bad, "opciones_not_obj")


class BuildRequestTests(unittest.TestCase):
    def test_una_rubrica_de_un_item_da_n_mas_dos_preguntas(self):
        r = one_item_rubric()
        request = rubric.build_request(r, "hola, texto de prueba")
        self.assertEqual(len(request["questions"]), 1 + 2)
        self.assertEqual(request["model"], "jev-latest")

    def test_una_rubrica_de_n_items_da_n_mas_dos_preguntas(self):
        r = rubric.load_rubric(RUBRIC_PATH)
        request = rubric.build_request(r, "hola, texto de prueba")
        n = len(r["items"])
        self.assertEqual(len(request["questions"]), n + 2)

    def test_el_texto_aparece_una_sola_vez_en_el_cuerpo(self):
        r = rubric.load_rubric(RUBRIC_PATH)
        text = "El texto único de la interacción, sin repetirse en ningún otro lado."
        request = rubric.build_request(r, text)
        serialized = json.dumps(request, ensure_ascii=False)
        self.assertEqual(serialized.count(text), 1)
        self.assertEqual(request["state"], text)

    def test_incluye_preguntas_riesgo_y_motivo_con_tipos_correctos(self):
        r = rubric.load_rubric(RUBRIC_PATH)
        request = rubric.build_request(r, "texto")
        self.assertEqual(request["questions"]["riesgo"]["type"], "score")
        self.assertEqual(len(request["questions"]["riesgo"]["criteria"]), 4)
        self.assertEqual(request["questions"]["motivo"]["type"], "choice")
        self.assertIn("otro", request["questions"]["motivo"]["criteria"])

    def test_cada_item_se_convierte_en_una_pregunta_noul(self):
        r = rubric.load_rubric(RUBRIC_PATH)
        request = rubric.build_request(r, "texto")
        for item in r["items"]:
            question = request["questions"][item["id"]]
            self.assertEqual(question["type"], "noul")
            self.assertEqual(question["instructions"], item["pregunta"])

    def test_item_con_id_reservado_no_rompe_en_silencio_el_invariante_n_mas_2(self):
        r = one_item_rubric()
        r["items"].append(
            {"id": "riesgo", "pregunta": "¿Otra?", "peso": 1.0, "critico": False}
        )
        with self.assertRaises(rubric.RubricError):
            rubric.build_request(r, "texto")


class ParseResponseTests(unittest.TestCase):
    def setUp(self):
        self.r = rubric.load_rubric(RUBRIC_PATH)
        with open(FIXTURE_PATH, encoding="utf-8") as f:
            self.fixture = json.load(f)

    def test_respuesta_completa_se_interpreta_sin_perder_campos(self):
        result = rubric.parse_response(self.r, self.fixture)
        for question_id, raw_answer in self.fixture["answers"].items():
            parsed = result[question_id]
            for key, value in raw_answer.items():
                self.assertIn(key, parsed)
                self.assertEqual(parsed[key], value)

    def test_noul_expone_probabilidad(self):
        result = rubric.parse_response(self.r, self.fixture)
        self.assertEqual(result["saludo"]["probabilidad"], 0.95)

    def test_score_expone_confianza_y_distribucion(self):
        result = rubric.parse_response(self.r, self.fixture)
        riesgo = result["riesgo"]
        self.assertEqual(riesgo["confianza"], 0.92)
        self.assertEqual(riesgo["distribucion"], self.fixture["answers"]["riesgo"]["probabilities"])
        self.assertEqual(riesgo["probabilidad"], 1.05)

    def test_choice_expone_confianza_y_distribucion(self):
        result = rubric.parse_response(self.r, self.fixture)
        motivo = result["motivo"]
        self.assertEqual(motivo["confianza"], 0.81)
        self.assertEqual(motivo["distribucion"], self.fixture["answers"]["motivo"]["probabilities"])
        self.assertEqual(motivo["probabilidad"], 0.88)

    def test_respuesta_sin_una_pregunta_lanza_error_tipado(self):
        incompleta = json.loads(json.dumps(self.fixture))
        del incompleta["answers"]["despedida"]
        with self.assertRaises(rubric.RespuestaIncompletaError):
            rubric.parse_response(self.r, incompleta)

    def test_tipo_esperado_viene_de_la_rubrica_no_del_campo_type_de_la_respuesta(self):
        # El campo "type" de la respuesta es incorrecto para "saludo" (item -> noul
        # esperado), así que debe fallar como respuesta mal formada, no aceptarse.
        mala = json.loads(json.dumps(self.fixture))
        mala["answers"]["saludo"]["type"] = "score"
        with self.assertRaises(rubric.RespuestaIncompletaError):
            rubric.parse_response(self.r, mala)

    def test_noul_sin_campo_noul_lanza_error_tipado_no_keyerror(self):
        mala = json.loads(json.dumps(self.fixture))
        del mala["answers"]["saludo"]["noul"]
        with self.assertRaises(rubric.RespuestaIncompletaError):
            rubric.parse_response(self.r, mala)

    def test_score_sin_probabilities_lanza_error_tipado_no_keyerror(self):
        mala = json.loads(json.dumps(self.fixture))
        del mala["answers"]["riesgo"]["probabilities"]
        with self.assertRaises(rubric.RespuestaIncompletaError):
            rubric.parse_response(self.r, mala)

    def test_score_con_confidence_no_numerico_lanza_error_tipado_no_typeerror(self):
        mala = json.loads(json.dumps(self.fixture))
        mala["answers"]["riesgo"]["confidence"] = "alta"
        with self.assertRaises(rubric.RespuestaIncompletaError):
            rubric.parse_response(self.r, mala)

    def test_choice_sin_choice_lanza_error_tipado_no_keyerror(self):
        mala = json.loads(json.dumps(self.fixture))
        del mala["answers"]["motivo"]["choice"]
        with self.assertRaises(rubric.RespuestaIncompletaError):
            rubric.parse_response(self.r, mala)

    def test_choice_con_valor_ausente_en_probabilities_lanza_error_tipado(self):
        mala = json.loads(json.dumps(self.fixture))
        mala["answers"]["motivo"]["choice"] = "no_existe_esta_opcion"
        with self.assertRaises(rubric.RespuestaIncompletaError):
            rubric.parse_response(self.r, mala)

    def test_respuesta_sin_answers_lanza_error_tipado(self):
        with self.assertRaises(rubric.RespuestaIncompletaError):
            rubric.parse_response(self.r, {"model": "jev-1.13.0"})


class SinteticasCsvTests(unittest.TestCase):
    def test_tiene_40_filas_y_columnas_por_item(self):
        r = rubric.load_rubric(RUBRIC_PATH)
        item_ids = [item["id"] for item in r["items"]]
        with open(SINTETICAS_PATH, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            fieldnames = reader.fieldnames

        self.assertEqual(len(rows), 40)
        for expected_column in ["id", "texto", "ambiguo"] + item_ids:
            self.assertIn(expected_column, fieldnames)

        for row in rows:
            self.assertTrue(row["texto"].strip())
            for item_id in item_ids:
                self.assertIn(row[item_id], ("0", "1"))
            self.assertIn(row["ambiguo"], ("0", "1"))

    def test_incluye_al_menos_un_caso_ambiguo(self):
        with open(SINTETICAS_PATH, encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        ambiguous = [row for row in rows if row["ambiguo"] == "1"]
        self.assertGreater(len(ambiguous), 0)


if __name__ == "__main__":
    unittest.main()
