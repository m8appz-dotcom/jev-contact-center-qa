import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import eval_jev

RUBRIC_MINIMA = {
    "items": [{"id": "item1", "pregunta": "?", "peso": 1.0, "critico": False}],
    "riesgo": {"pregunta": "?", "niveles": ["a", "b", "c", "d"]},
    "motivo": {"pregunta": "?", "opciones": {"otro": "otro"}},
}


class ItemMetricsTests(unittest.TestCase):
    def test_acuerdo_total(self):
        records = [
            {"etiqueta": 1, "prediccion": 1, "confianza": 0.9},
            {"etiqueta": 0, "prediccion": 0, "confianza": 0.8},
            {"etiqueta": 1, "prediccion": 1, "confianza": 0.6},
        ]

        m = eval_jev.item_metrics(records)

        self.assertEqual(m["acuerdo"], 1.0)
        self.assertEqual(m["precision_no_cumple"], 1.0)
        self.assertEqual(m["exhaustividad_no_cumple"], 1.0)

    def test_acuerdo_nulo(self):
        records = [
            {"etiqueta": 1, "prediccion": 0, "confianza": 0.9},
            {"etiqueta": 0, "prediccion": 1, "confianza": 0.8},
        ]

        m = eval_jev.item_metrics(records)

        self.assertEqual(m["acuerdo"], 0.0)
        self.assertEqual(m["precision_no_cumple"], 0.0)
        self.assertEqual(m["exhaustividad_no_cumple"], 0.0)

    def test_item_sin_ningun_no_cumple_no_divide_por_cero(self):
        records = [
            {"etiqueta": 1, "prediccion": 1, "confianza": 0.9},
            {"etiqueta": 1, "prediccion": 1, "confianza": 0.8},
        ]

        m = eval_jev.item_metrics(records)

        self.assertEqual(m["acuerdo"], 1.0)
        self.assertIsNone(m["precision_no_cumple"])
        self.assertIsNone(m["exhaustividad_no_cumple"])

    def test_lista_vacia_no_divide_por_cero(self):
        m = eval_jev.item_metrics([])

        self.assertIsNone(m["acuerdo"])
        self.assertIsNone(m["precision_no_cumple"])
        self.assertIsNone(m["exhaustividad_no_cumple"])
        self.assertIsNone(m["acuerdo_alta_confianza"])

    def test_filtro_de_confianza_mayor_o_igual_a_0_7(self):
        records = [
            {"etiqueta": 1, "prediccion": 1, "confianza": 0.9},  # entra, acierta
            {"etiqueta": 1, "prediccion": 0, "confianza": 0.6},  # no entra (confianza baja)
            {"etiqueta": 0, "prediccion": 1, "confianza": 0.7},  # entra (limite), falla
        ]

        m = eval_jev.item_metrics(records)

        self.assertEqual(m["n_alta_confianza"], 2)
        self.assertEqual(m["acuerdo_alta_confianza"], 0.5)

    def test_ningun_registro_con_confianza_alta_no_divide_por_cero(self):
        records = [
            {"etiqueta": 1, "prediccion": 1, "confianza": 0.6},
        ]

        m = eval_jev.item_metrics(records)

        self.assertIsNone(m["acuerdo_alta_confianza"])
        self.assertEqual(m["n_alta_confianza"], 0)


class PrediccionYConfianzaTests(unittest.TestCase):
    def test_prediccion_usa_umbral_0_5(self):
        self.assertEqual(eval_jev.prediccion_de(0.5), 1)
        self.assertEqual(eval_jev.prediccion_de(0.49), 0)

    def test_confianza_es_valor_absoluto_de_2p_menos_1(self):
        # Misma escala que confidence de Choice/Score: 0 = incertidumbre
        # total (p=0.5), 1 = certeza total (p=0 o p=1).
        self.assertAlmostEqual(eval_jev.confianza_de(0.9), 0.8)
        self.assertAlmostEqual(eval_jev.confianza_de(0.1), 0.8)
        self.assertAlmostEqual(eval_jev.confianza_de(0.5), 0.0)
        self.assertAlmostEqual(eval_jev.confianza_de(1.0), 1.0)
        self.assertAlmostEqual(eval_jev.confianza_de(0.0), 1.0)
        self.assertAlmostEqual(eval_jev.confianza_de(0.85), 0.7)


class PeoresDesacuerdosTests(unittest.TestCase):
    def test_ordena_por_mayor_diferencia_absoluta_entre_desacuerdos_reales(self):
        entradas = [
            # acierta (prediccion == etiqueta): no es un desacuerdo real.
            {"id": "a", "item": "x", "etiqueta": 1, "prediccion": 1, "probabilidad": 0.9, "texto": "a"},
            {"id": "b", "item": "x", "etiqueta": 0, "prediccion": 1, "probabilidad": 0.95, "texto": "b"},
            {"id": "c", "item": "x", "etiqueta": 1, "prediccion": 0, "probabilidad": 0.4, "texto": "c"},
        ]

        peores = eval_jev.peores_desacuerdos(entradas, top=2)

        self.assertEqual([e["id"] for e in peores], ["b", "c"])

    def test_solo_hay_acuerdos_devuelve_lista_vacia(self):
        entradas = [
            {"id": "a", "item": "x", "etiqueta": 1, "prediccion": 1, "probabilidad": 0.9, "texto": "a"},
            {"id": "b", "item": "x", "etiqueta": 0, "prediccion": 0, "probabilidad": 0.1, "texto": "b"},
        ]

        peores = eval_jev.peores_desacuerdos(entradas, top=5)

        self.assertEqual(peores, [])


class CostoDolaresTests(unittest.TestCase):
    def test_costo_proporcional_a_tokens_de_entrada(self):
        self.assertAlmostEqual(eval_jev.costo_dolares(1_000_000), 0.042)

    def test_costo_cero_sin_tokens_de_entrada(self):
        self.assertEqual(eval_jev.costo_dolares(0), 0.0)


class RenderInformeTests(unittest.TestCase):
    def test_costo_real_solo_de_tokens_de_entrada_no_presenta_salida_como_facturada(self):
        evaluacion = {
            "resultados": [],
            "fallos": [],
            "tokens_entrada": 1_000_000,
            "tokens_salida": 500_000,
        }

        texto, _ = eval_jev.render_informe(RUBRIC_MINIMA, evaluacion, 0, "fake")

        self.assertIn("0.042000", texto)
        self.assertIn("500000", texto)
        # No debe existir un "coste total" que sume entrada + salida como si
        # la salida se facturara también.
        self.assertNotIn("1500000", texto)

    def test_indica_cuando_no_hay_desacuerdos(self):
        evaluacion = {
            "resultados": [
                {
                    "id": "r1",
                    "texto": "hola",
                    "por_item": {
                        "item1": {
                            "etiqueta": 1,
                            "prediccion": 1,
                            "probabilidad": 0.9,
                            "confianza": eval_jev.confianza_de(0.9),
                        }
                    },
                }
            ],
            "fallos": [],
            "tokens_entrada": 10,
            "tokens_salida": 5,
        }

        texto, items_bajo_umbral = eval_jev.render_informe(RUBRIC_MINIMA, evaluacion, 1, "fake")

        self.assertIn("No hay desacuerdos", texto)
        self.assertEqual(items_bajo_umbral, [])

    def test_modo_fake_avisa_que_no_mide_nada(self):
        evaluacion = {"resultados": [], "fallos": [], "tokens_entrada": 0, "tokens_salida": 0}

        texto, _ = eval_jev.render_informe(RUBRIC_MINIMA, evaluacion, 0, "fake")

        self.assertIn("modo fake, no mide nada", texto.lower())


class ReadSyntheticCsvValidationTests(unittest.TestCase):
    def _escribir_csv(self, contenido: str) -> str:
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        f.write(contenido)
        f.close()
        self.addCleanup(os.remove, f.name)
        return f.name

    def test_columna_de_item_faltante(self):
        path = self._escribir_csv("id,texto\nr1,hola\n")

        with self.assertRaises(eval_jev.CsvValidationError) as cm:
            eval_jev.read_synthetic_csv(path, ["item1"])

        self.assertEqual(cm.exception.columna, "item1")
        self.assertEqual(cm.exception.fila, 2)

    def test_etiqueta_que_no_es_0_ni_1(self):
        path = self._escribir_csv("id,texto,item1\nr1,hola,2\n")

        with self.assertRaises(eval_jev.CsvValidationError) as cm:
            eval_jev.read_synthetic_csv(path, ["item1"])

        self.assertEqual(cm.exception.columna, "item1")
        self.assertEqual(cm.exception.fila, 2)

    def test_etiqueta_vacia_no_es_valida(self):
        path = self._escribir_csv("id,texto,item1\nr1,hola,\n")

        with self.assertRaises(eval_jev.CsvValidationError):
            eval_jev.read_synthetic_csv(path, ["item1"])

    def test_id_duplicado(self):
        path = self._escribir_csv("id,texto,item1\nr1,hola,1\nr1,chau,0\n")

        with self.assertRaises(eval_jev.CsvValidationError) as cm:
            eval_jev.read_synthetic_csv(path, ["item1"])

        self.assertEqual(cm.exception.columna, "id")
        self.assertEqual(cm.exception.fila, 3)

    def test_csv_valido_no_lanza_y_convierte_etiquetas_a_entero(self):
        path = self._escribir_csv("id,texto,item1\nr1,hola,1\nr2,chau,0\n")

        filas = eval_jev.read_synthetic_csv(path, ["item1"])

        self.assertEqual(len(filas), 2)
        self.assertEqual(filas[0]["etiquetas"], {"item1": 1})
        self.assertEqual(filas[1]["etiquetas"], {"item1": 0})


class FakeJevPorFilaTests(unittest.TestCase):
    def test_no_colisiona_cuando_dos_filas_tienen_texto_identico(self):
        respuestas = {"r1": {"respuesta": "para r1"}, "r2": {"respuesta": "para r2"}}
        client = eval_jev.FakeJevPorFila(respuestas, ["r1", "r2"])

        primera = client.evaluate({"state": "el mismo texto"})
        segunda = client.evaluate({"state": "el mismo texto"})

        self.assertEqual(primera, {"respuesta": "para r1"})
        self.assertEqual(segunda, {"respuesta": "para r2"})

    def test_build_fake_client_produce_respuestas_distintas_para_texto_identico(self):
        filas = [
            {"id": "r1", "texto": "mismo texto", "ambiguo": False, "etiquetas": {"item1": 1}},
            {"id": "r2", "texto": "mismo texto", "ambiguo": False, "etiquetas": {"item1": 0}},
        ]

        client = eval_jev.build_fake_client(RUBRIC_MINIMA, filas)
        evaluacion = eval_jev.run_evaluation(RUBRIC_MINIMA, filas, client)

        self.assertEqual(len(evaluacion["fallos"]), 0)
        pred_r1 = evaluacion["resultados"][0]["por_item"]["item1"]["prediccion"]
        pred_r2 = evaluacion["resultados"][1]["por_item"]["item1"]["prediccion"]
        self.assertEqual(pred_r1, 1)
        self.assertEqual(pred_r2, 0)


class RunEvaluationAuthErrorTests(unittest.TestCase):
    def test_propaga_error_de_autenticacion_en_lugar_de_registrarlo_como_fallo(self):
        class ClienteQueFallaAuth:
            def evaluate(self, request):
                raise eval_jev.JevAuthError("401 Unauthorized simulado")

        filas = [{"id": "r1", "texto": "hola", "ambiguo": False, "etiquetas": {"item1": 1}}]

        with self.assertRaises(eval_jev.JevAuthError):
            eval_jev.run_evaluation(RUBRIC_MINIMA, filas, ClienteQueFallaAuth())


class MainExitCodeTests(unittest.TestCase):
    def setUp(self):
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        self.informe_path = os.path.join(tempdir.name, "informe.md")
        self.informe_fake_path = os.path.join(tempdir.name, "informe_fake.md")

        for patcher in (
            mock.patch.object(eval_jev, "INFORME_PATH", self.informe_path),
            mock.patch.object(eval_jev, "INFORME_FAKE_PATH", self.informe_fake_path),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    @mock.patch("eval_jev.read_synthetic_csv")
    @mock.patch("eval_jev.rubric_mod.load_rubric")
    def test_fake_con_todo_bien_devuelve_0_y_escribe_solo_el_informe_fake(
        self, mock_load_rubric, mock_read_csv
    ):
        mock_load_rubric.return_value = RUBRIC_MINIMA
        mock_read_csv.return_value = [
            {"id": "r1", "texto": "hola", "ambiguo": False, "etiquetas": {"item1": 1}},
            {"id": "r2", "texto": "chau", "ambiguo": False, "etiquetas": {"item1": 0}},
        ]

        codigo = eval_jev.main(["--fake"])

        self.assertEqual(codigo, eval_jev.EXIT_OK)
        self.assertTrue(os.path.exists(self.informe_fake_path))
        self.assertFalse(os.path.exists(self.informe_path))
        with open(self.informe_fake_path, encoding="utf-8") as f:
            contenido = f.read()
        self.assertIn("modo fake, no mide nada", contenido.lower())

    @mock.patch("eval_jev.read_synthetic_csv")
    @mock.patch("eval_jev.rubric_mod.load_rubric")
    def test_csv_invalido_devuelve_2_y_no_escribe_ningun_informe(
        self, mock_load_rubric, mock_read_csv
    ):
        mock_load_rubric.return_value = RUBRIC_MINIMA
        mock_read_csv.side_effect = eval_jev.CsvValidationError(
            2, "item1", "la etiqueta debe ser 0 o 1"
        )

        codigo = eval_jev.main(["--fake"])

        self.assertEqual(codigo, eval_jev.EXIT_CSV_INVALIDO)
        self.assertFalse(os.path.exists(self.informe_fake_path))
        self.assertFalse(os.path.exists(self.informe_path))

    @mock.patch("eval_jev.JevClient")
    @mock.patch("eval_jev.read_synthetic_csv")
    @mock.patch("eval_jev.rubric_mod.load_rubric")
    def test_en_vivo_sin_credenciales_validas_devuelve_3_y_no_escribe_informe(
        self, mock_load_rubric, mock_read_csv, mock_jev_client_cls
    ):
        mock_load_rubric.return_value = RUBRIC_MINIMA
        mock_read_csv.return_value = [
            {"id": "r1", "texto": "hola", "ambiguo": False, "etiquetas": {"item1": 1}},
        ]

        class ClienteFalloAuth:
            def evaluate(self, request):
                raise eval_jev.JevAuthError("401 Unauthorized simulado")

        mock_jev_client_cls.return_value = ClienteFalloAuth()

        codigo = eval_jev.main([])

        self.assertEqual(codigo, eval_jev.EXIT_AUTH_ERROR)
        self.assertFalse(os.path.exists(self.informe_path))
        self.assertFalse(os.path.exists(self.informe_fake_path))

    @mock.patch("eval_jev.render_informe")
    @mock.patch("eval_jev.read_synthetic_csv")
    @mock.patch("eval_jev.rubric_mod.load_rubric")
    def test_items_bajo_umbral_devuelve_5(self, mock_load_rubric, mock_read_csv, mock_render):
        mock_load_rubric.return_value = RUBRIC_MINIMA
        mock_read_csv.return_value = [
            {"id": "r1", "texto": "hola", "ambiguo": False, "etiquetas": {"item1": 1}},
        ]
        mock_render.return_value = ("informe de prueba", ["item1"])

        codigo = eval_jev.main(["--fake"])

        self.assertEqual(codigo, eval_jev.EXIT_DEBAJO_UMBRAL)

    @mock.patch("eval_jev.render_informe")
    @mock.patch("eval_jev.run_evaluation")
    @mock.patch("eval_jev.read_synthetic_csv")
    @mock.patch("eval_jev.rubric_mod.load_rubric")
    def test_filas_fallidas_devuelve_4(
        self, mock_load_rubric, mock_read_csv, mock_run_eval, mock_render
    ):
        mock_load_rubric.return_value = RUBRIC_MINIMA
        mock_read_csv.return_value = [
            {"id": "r1", "texto": "hola", "ambiguo": False, "etiquetas": {"item1": 1}},
        ]
        mock_run_eval.return_value = {
            "resultados": [],
            "fallos": [{"id": "r1", "error": "boom"}],
            "tokens_entrada": 0,
            "tokens_salida": 0,
        }
        mock_render.return_value = ("informe de prueba", [])

        codigo = eval_jev.main(["--fake"])

        self.assertEqual(codigo, eval_jev.EXIT_FILAS_FALLIDAS)


if __name__ == "__main__":
    unittest.main()
