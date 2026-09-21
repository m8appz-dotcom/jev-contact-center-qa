"""Tests de las métricas de la evaluación en español (fase 2)."""

from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def cargar_script():
    """Importa `scripts/eval_jev.py`, que no es un módulo del paquete."""
    ruta = os.path.join(RAIZ, "scripts", "eval_jev.py")
    especificacion = importlib.util.spec_from_file_location("eval_jev", ruta)
    modulo = importlib.util.module_from_spec(especificacion)
    especificacion.loader.exec_module(modulo)
    return modulo


eval_jev = cargar_script()


# Cada observación es (el humano dice que cumple, probabilidad, confianza).
CUMPLE_SEGURO = (True, 0.95, 0.9)
NO_CUMPLE_SEGURO = (False, 0.05, 0.9)


class TestMetricasItem(unittest.TestCase):
    def test_acuerdo_total(self):
        m = eval_jev.metricas_item([CUMPLE_SEGURO] * 6 + [NO_CUMPLE_SEGURO] * 4)
        self.assertEqual(m["n"], 10)
        self.assertEqual(m["acuerdo"], 1.0)
        self.assertEqual(m["precision_no_cumple"], 1.0)
        self.assertEqual(m["exhaustividad_no_cumple"], 1.0)
        self.assertEqual(m["no_cumple_humano"], 4)
        self.assertEqual(m["no_cumple_jev"], 4)

    def test_acuerdo_nulo(self):
        # Jev dice lo contrario que el humano en las diez interacciones.
        observaciones = [(True, 0.05, 0.9)] * 6 + [(False, 0.95, 0.9)] * 4
        m = eval_jev.metricas_item(observaciones)
        self.assertEqual(m["acuerdo"], 0.0)
        self.assertEqual(m["precision_no_cumple"], 0.0)
        self.assertEqual(m["exhaustividad_no_cumple"], 0.0)

    def test_item_sin_ningun_no_cumple(self):
        # Ni el humano ni Jev marcan una sola falla: las razones no existen,
        # y no se divide por cero.
        m = eval_jev.metricas_item([CUMPLE_SEGURO] * 8)
        self.assertEqual(m["acuerdo"], 1.0)
        self.assertIsNone(m["precision_no_cumple"])
        self.assertIsNone(m["exhaustividad_no_cumple"])

    def test_sin_no_cumple_humano_pero_jev_marca_falla(self):
        m = eval_jev.metricas_item([CUMPLE_SEGURO] * 7 + [(True, 0.10, 0.8)])
        self.assertEqual(m["acuerdo"], 7 / 8)
        self.assertEqual(m["precision_no_cumple"], 0.0)
        self.assertIsNone(m["exhaustividad_no_cumple"])

    def test_sin_no_cumple_de_jev_pero_el_humano_marca_falla(self):
        m = eval_jev.metricas_item([CUMPLE_SEGURO] * 7 + [(False, 0.90, 0.8)])
        self.assertIsNone(m["precision_no_cumple"])
        self.assertEqual(m["exhaustividad_no_cumple"], 0.0)

    def test_sin_observaciones(self):
        m = eval_jev.metricas_item([])
        self.assertEqual(m["n"], 0)
        self.assertIsNone(m["acuerdo"])
        self.assertIsNone(m["precision_no_cumple"])
        self.assertIsNone(m["exhaustividad_no_cumple"])
        self.assertIsNone(m["acuerdo_confiables"])

    def test_acuerdo_solo_sobre_las_respuestas_confiables(self):
        observaciones = [
            (True, 0.95, 0.9),   # confiable y acierta
            (True, 0.20, 0.8),   # confiable y falla
            (True, 0.45, 0.1),   # poco confiable, falla: no cuenta
            (False, 0.48, 0.04),  # poco confiable, acierta: no cuenta
        ]
        m = eval_jev.metricas_item(observaciones, umbral_confianza=0.7)
        self.assertEqual(m["n"], 4)
        self.assertEqual(m["acuerdo"], 0.5)
        self.assertEqual(m["n_confiables"], 2)
        self.assertEqual(m["acuerdo_confiables"], 0.5)

    def test_sin_ninguna_respuesta_confiable(self):
        m = eval_jev.metricas_item([(True, 0.55, 0.1)] * 3, umbral_confianza=0.7)
        self.assertEqual(m["n_confiables"], 0)
        self.assertIsNone(m["acuerdo_confiables"])

    def test_el_umbral_es_inclusivo(self):
        # Justo en 0,5 se lee como cumple.
        self.assertEqual(eval_jev.metricas_item([(True, 0.5, 0.0)])["acuerdo"], 1.0)
        self.assertEqual(eval_jev.metricas_item([(False, 0.5, 0.0)])["acuerdo"], 0.0)

    def test_umbral_configurable(self):
        observaciones = [(False, 0.6, 0.2)]
        self.assertEqual(eval_jev.metricas_item(observaciones)["acuerdo"], 0.0)
        self.assertEqual(eval_jev.metricas_item(observaciones, umbral=0.7)["acuerdo"], 1.0)


class TestRecorridoCompleto(unittest.TestCase):
    """El evaluador corre de punta a punta con FakeJev y escribe el informe."""

    def setUp(self):
        self.salida = os.path.join(tempfile.mkdtemp(), "informe.md")

    def test_modo_fake_sobre_las_40_interacciones(self):
        codigo = eval_jev.main(["--fake", "--salida", self.salida])
        self.assertEqual(codigo, 0)

        with open(self.salida, encoding="utf-8") as archivo:
            informe = archivo.read()
        self.assertIn("Interacciones evaluadas: **40** de 40", informe)
        self.assertIn("Acuerdo por ítem", informe)
        self.assertIn("Este informe no mide nada", informe)
        for item in eval_jev.load_rubric(eval_jev.RUBRICA)["items"]:
            self.assertIn(f"`{item['id']}`", informe)

    def test_una_fila_que_falla_no_detiene_el_lote(self):
        from jevqa.jev_client import ErrorServidor

        rubrica = eval_jev.load_rubric(eval_jev.RUBRICA)
        filas = eval_jev.cargar_interacciones(eval_jev.DATOS, rubrica)[:3]
        cliente = eval_jev.FakeJev(errores=[None, ErrorServidor("500: caído", 500), None])

        evaluaciones = eval_jev.evaluar(rubrica, filas, cliente)

        self.assertEqual(len(evaluaciones), 3)
        self.assertIsNotNone(evaluaciones[0]["resultado"])
        self.assertIsNone(evaluaciones[1]["resultado"])
        self.assertIn("ErrorServidor", evaluaciones[1]["error"])
        self.assertIsNotNone(evaluaciones[2]["resultado"])

        metricas = eval_jev.metricas_por_item(rubrica, evaluaciones)
        self.assertEqual(metricas["saludo"]["n"], 2)

        eval_jev.escribir_informe(
            self.salida, rubrica, evaluaciones, metricas,
            modo="fake", umbral=0.5, umbral_confianza=0.7,
        )
        with open(self.salida, encoding="utf-8") as archivo:
            self.assertIn("Interacciones que fallaron", archivo.read())

    def test_el_coste_sale_de_los_tokens_de_uso(self):
        evaluaciones = [
            {"resultado": {"uso": {"tokens_entrada": 1_000_000, "tokens_salida": 50}}},
            {"resultado": None},
        ]
        uso = eval_jev.uso_total(evaluaciones)
        self.assertEqual(uso["tokens_entrada"], 1_000_000)
        self.assertAlmostEqual(uso["coste_usd"], 0.042)

    def test_sin_clave_el_modo_en_vivo_sale_con_codigo_2(self):
        import os as sistema

        anterior = sistema.environ.pop("TYPESAFE_API_KEY", None)
        try:
            self.assertEqual(eval_jev.main(["--salida", self.salida]), 2)
        finally:
            if anterior is not None:
                sistema.environ["TYPESAFE_API_KEY"] = anterior


class TestPeoresDesacuerdos(unittest.TestCase):
    def test_se_ordenan_por_confianza(self):
        rubrica = {
            "items": [{"id": "saludo", "peso": 1, "critico": False}],
        }
        def evaluacion(ident, probabilidad, confianza):
            return {
                "id": ident,
                "fila": {"texto": f"texto de {ident}", "ambiguo": "no", "notas": ""},
                "etiquetas": {"saludo": True},
                "resultado": {
                    "items": {
                        "saludo": {"probabilidad": probabilidad, "confianza": confianza}
                    }
                },
                "error": None,
            }

        evaluaciones = [
            evaluacion("A", 0.10, 0.80),
            evaluacion("B", 0.02, 0.96),
            evaluacion("C", 0.95, 0.90),  # acuerdo: no entra
            evaluacion("D", 0.45, 0.10),
        ]
        peores = eval_jev.peores_desacuerdos(rubrica, evaluaciones, cuantos=5)
        self.assertEqual([d["id"] for d in peores], ["B", "A", "D"])
        self.assertEqual(peores[0]["humano"], "cumple")
        self.assertEqual(peores[0]["jev"], "no")

    def test_se_limitan_a_cinco(self):
        rubrica = {"items": [{"id": "saludo", "peso": 1, "critico": False}]}
        evaluaciones = [
            {
                "id": f"INT-{i}",
                "fila": {"texto": "t", "ambiguo": "no", "notas": ""},
                "etiquetas": {"saludo": True},
                "resultado": {"items": {"saludo": {"probabilidad": 0.1, "confianza": 0.8}}},
                "error": None,
            }
            for i in range(9)
        ]
        self.assertEqual(len(eval_jev.peores_desacuerdos(rubrica, evaluaciones)), 5)


if __name__ == "__main__":
    unittest.main()
