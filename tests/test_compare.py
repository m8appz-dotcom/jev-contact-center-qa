import csv
import os
import shutil
import tempfile
import unittest

from jevqa import compare
from jevqa.__main__ import EXIT_ENTRADA_INVALIDA, EXIT_OK
from jevqa.__main__ import main as cli_main
from jevqa.pipeline import OUTPUT_HEADER_BASE

HUMANO_HEADER_BASE = ["id", "texto", "ambiguo"]


def escribir_humano(path, filas, items):
    header = HUMANO_HEADER_BASE + items
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        for fila in filas:
            row = {"id": fila["id"], "texto": "algo de texto", "ambiguo": "no-es-0-1"}
            for item in items:
                row[item] = fila[item]
            writer.writerow(row)


def escribir_resultados(path, filas, items):
    header = OUTPUT_HEADER_BASE + items + ["riesgo", "motivo"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        for fila in filas:
            row = {
                "id": fila["id"],
                "agente": fila.get("agente", "Ana"),
                "campaña": fila.get("campaña", "soporte"),
                "fecha": fila.get("fecha", "2026-01-01"),
                "estado": fila.get("estado", "ok"),
                "detalle": fila.get("detalle", ""),
                "riesgo": 0,
                "motivo": "soporte",
            }
            for item in items:
                row[item] = fila.get(item, "")
            writer.writerow(row)


class TestComparar(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.humano_path = os.path.join(self.tmp, "humano.csv")
        self.resultados_path = os.path.join(self.tmp, "resultados.csv")

    def test_acuerdo_total(self):
        # 5 ids humano=1/jev=cumple, 5 ids humano=0/jev=no_cumple -> acuerdo y kappa = 1.0
        h = [{"id": f"a{i}", "resolucion": "1"} for i in range(5)]
        h += [{"id": f"b{i}", "resolucion": "0"} for i in range(5)]
        j = [{"id": f"a{i}", "resolucion": 0.9} for i in range(5)]
        j += [{"id": f"b{i}", "resolucion": 0.1} for i in range(5)]
        escribir_humano(self.humano_path, h, ["resolucion"])
        escribir_resultados(self.resultados_path, j, ["resolucion"])

        resultado = compare.comparar(self.humano_path, self.resultados_path)
        r = resultado["por_item"]["resolucion"]
        self.assertEqual(resultado["n"], 10)
        self.assertEqual(r["acuerdo"], 1.0)
        self.assertEqual(r["kappa"], 1.0)

    def test_acuerdo_nulo_balanceado(self):
        # 5 ids humano=1/jev=no_cumple, 5 ids humano=0/jev=cumple -> acuerdo 0.0, kappa -1.0
        h = [{"id": f"a{i}", "resolucion": "1"} for i in range(5)]
        h += [{"id": f"b{i}", "resolucion": "0"} for i in range(5)]
        j = [{"id": f"a{i}", "resolucion": 0.1} for i in range(5)]
        j += [{"id": f"b{i}", "resolucion": 0.9} for i in range(5)]
        escribir_humano(self.humano_path, h, ["resolucion"])
        escribir_resultados(self.resultados_path, j, ["resolucion"])

        resultado = compare.comparar(self.humano_path, self.resultados_path)
        r = resultado["por_item"]["resolucion"]
        self.assertEqual(r["acuerdo"], 0.0)
        self.assertEqual(r["kappa"], -1.0)

    def test_kappa_intermedio_calculado_a_mano(self):
        # cc=4, cn=1, nc=1, nn=4, n=10.
        # po = (4+4)/10 = 0.8
        # p_humano_cumple = (4+1)/10 = 0.5 ; p_jev_cumple = (4+1)/10 = 0.5
        # pe = 0.5*0.5 + 0.5*0.5 = 0.5
        # kappa = (0.8 - 0.5) / (1 - 0.5) = 0.6
        h = []
        j = []
        for i in range(4):  # cumple/cumple
            h.append({"id": f"cc{i}", "resolucion": "1"})
            j.append({"id": f"cc{i}", "resolucion": 0.9})
        h.append({"id": "cn0", "resolucion": "1"})  # cumple/no_cumple
        j.append({"id": "cn0", "resolucion": 0.1})
        h.append({"id": "nc0", "resolucion": "0"})  # no_cumple/cumple
        j.append({"id": "nc0", "resolucion": 0.9})
        for i in range(4):  # no_cumple/no_cumple
            h.append({"id": f"nn{i}", "resolucion": "0"})
            j.append({"id": f"nn{i}", "resolucion": 0.1})
        escribir_humano(self.humano_path, h, ["resolucion"])
        escribir_resultados(self.resultados_path, j, ["resolucion"])

        resultado = compare.comparar(self.humano_path, self.resultados_path)
        r = resultado["por_item"]["resolucion"]
        self.assertEqual(r["acuerdo"], 0.8)
        self.assertAlmostEqual(r["kappa"], 0.6)

    def test_raters_constantes_identicos_kappa_indefinido(self):
        h = [{"id": f"a{i}", "resolucion": "1"} for i in range(4)]
        j = [{"id": f"a{i}", "resolucion": 0.9} for i in range(4)]
        escribir_humano(self.humano_path, h, ["resolucion"])
        escribir_resultados(self.resultados_path, j, ["resolucion"])

        resultado = compare.comparar(self.humano_path, self.resultados_path)
        r = resultado["por_item"]["resolucion"]
        self.assertIsNone(r["kappa"])
        self.assertIn("indefinido", compare.render_comparacion(resultado))

    def test_matriz_confusion_conteo_y_orientacion(self):
        h = [
            {"id": "a", "resolucion": "1"},
            {"id": "b", "resolucion": "1"},
            {"id": "c", "resolucion": "0"},
        ]
        j = [
            {"id": "a", "resolucion": 0.9},  # cumple/cumple
            {"id": "b", "resolucion": 0.1},  # cumple/no_cumple
            {"id": "c", "resolucion": 0.9},  # no_cumple/cumple
        ]
        escribir_humano(self.humano_path, h, ["resolucion"])
        escribir_resultados(self.resultados_path, j, ["resolucion"])

        resultado = compare.comparar(self.humano_path, self.resultados_path)
        matriz = resultado["por_item"]["resolucion"]["matriz"]
        self.assertEqual(matriz[("cumple", "cumple")], 1)
        self.assertEqual(matriz[("cumple", "no_cumple")], 1)
        self.assertEqual(matriz[("no_cumple", "cumple")], 1)
        self.assertEqual(matriz[("no_cumple", "no_cumple")], 0)

    def test_id_humano_sin_resultado_reportado_y_excluido(self):
        h = [
            {"id": "a", "resolucion": "1"},
            {"id": "b", "resolucion": "1"},  # sin fila en resultados
            {"id": "c", "resolucion": "0"},  # fila en resultados con estado error
        ]
        j = [
            {"id": "a", "resolucion": 0.9},
            {"id": "c", "resolucion": 0.9, "estado": "error"},
        ]
        escribir_humano(self.humano_path, h, ["resolucion"])
        escribir_resultados(self.resultados_path, j, ["resolucion"])

        resultado = compare.comparar(self.humano_path, self.resultados_path)
        self.assertEqual(resultado["n"], 1)
        self.assertCountEqual(resultado["ids_sin_resultado"], ["b", "c"])

    def test_probabilidad_fuera_de_rango_o_nan_lanza_comparacion_error(self):
        escribir_humano(self.humano_path, [{"id": "a", "resolucion": "1"}], ["resolucion"])
        for valor in ("nan", "1.5", "-0.1", "inf"):
            escribir_resultados(self.resultados_path, [{"id": "a", "resolucion": valor}], ["resolucion"])
            with self.assertRaises(compare.ComparacionError, msg=valor):
                compare.comparar(self.humano_path, self.resultados_path)

    def test_items_solo_en_humano_y_solo_en_jev(self):
        h = [{"id": "a", "resolucion": "1", "saludo_h": "1"}]
        j = [{"id": "a", "resolucion": 0.9, "saludo_j": 0.9}]
        escribir_humano(self.humano_path, h, ["resolucion", "saludo_h"])
        escribir_resultados(self.resultados_path, j, ["resolucion", "saludo_j"])

        resultado = compare.comparar(self.humano_path, self.resultados_path)
        self.assertEqual(resultado["items"], ["resolucion"])
        self.assertEqual(resultado["solo_humano"], ["saludo_h"])
        self.assertEqual(resultado["solo_jev"], ["saludo_j"])

    def test_sin_items_comunes_lanza_comparacion_error(self):
        h = [{"id": "a", "solo_humano": "1"}]
        j = [{"id": "a", "solo_jev": 0.9}]
        escribir_humano(self.humano_path, h, ["solo_humano"])
        escribir_resultados(self.resultados_path, j, ["solo_jev"])
        with self.assertRaises(compare.ComparacionError):
            compare.comparar(self.humano_path, self.resultados_path)

    def test_etiqueta_invalida_lanza_comparacion_error(self):
        for etiqueta in ("2", "sí"):
            h = [{"id": "a", "resolucion": etiqueta}]
            j = [{"id": "a", "resolucion": 0.9}]
            escribir_humano(self.humano_path, h, ["resolucion"])
            escribir_resultados(self.resultados_path, j, ["resolucion"])
            with self.assertRaises(compare.ComparacionError):
                compare.comparar(self.humano_path, self.resultados_path)

    def test_id_humano_repetido_lanza_comparacion_error(self):
        h = [{"id": "a", "resolucion": "1"}, {"id": "a", "resolucion": "0"}]
        j = [{"id": "a", "resolucion": 0.9}]
        escribir_humano(self.humano_path, h, ["resolucion"])
        escribir_resultados(self.resultados_path, j, ["resolucion"])
        with self.assertRaises(compare.ComparacionError):
            compare.comparar(self.humano_path, self.resultados_path)

    def test_columnas_de_metadatos_se_ignoran(self):
        # "texto" y "ambiguo" traen valores que no son 0/1 y no deben fallar.
        h = [{"id": "a", "resolucion": "1"}]
        j = [{"id": "a", "resolucion": 0.9}]
        escribir_humano(self.humano_path, h, ["resolucion"])
        escribir_resultados(self.resultados_path, j, ["resolucion"])
        resultado = compare.comparar(self.humano_path, self.resultados_path)
        self.assertEqual(resultado["n"], 1)


class TestCLIComparar(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.humano_path = os.path.join(self.tmp, "humano.csv")
        self.resultados_path = os.path.join(self.tmp, "resultados.csv")
        h = [{"id": "a", "resolucion": "1"}, {"id": "b", "resolucion": "0"}]
        j = [{"id": "a", "resolucion": 0.9}, {"id": "b", "resolucion": 0.1}]
        escribir_humano(self.humano_path, h, ["resolucion"])
        escribir_resultados(self.resultados_path, j, ["resolucion"])

    def test_cli_comparar_escribe_archivo_con_secciones_y_devuelve_0(self):
        salida = os.path.join(self.tmp, "comparacion.md")
        rc = cli_main(["comparar", self.humano_path, self.resultados_path, "--salida", salida])
        self.assertEqual(rc, EXIT_OK)
        with open(salida, "r", encoding="utf-8") as f:
            contenido = f.read()
        for encabezado in (
            "Acuerdo y kappa por ítem",
            "Matriz de confusión por ítem",
            "Ítems solo en una rúbrica",
            "Ids humanos sin resultado",
        ):
            self.assertIn(encabezado, contenido)

    def test_cli_comparar_devuelve_2_en_entrada_invalida(self):
        rc = cli_main(["comparar", os.path.join(self.tmp, "no-existe.csv"), self.resultados_path])
        self.assertEqual(rc, EXIT_ENTRADA_INVALIDA)

    def test_cli_help_lista_los_tres_comandos(self):
        import contextlib
        import io

        salida = io.StringIO()
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stdout(salida):
                cli_main(["--help"])
        texto = salida.getvalue()
        self.assertIn("auditar", texto)
        self.assertIn("comparar", texto)
        self.assertIn("informe", texto)


if __name__ == "__main__":
    unittest.main()


class CsvConBomTest(unittest.TestCase):
    """Un CSV exportado desde Excel como «CSV UTF-8» lleva BOM y debe leerse igual."""

    def test_csv_humano_con_bom(self):
        import tempfile, os
        from jevqa import compare
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "humano.csv")
            with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
                f.write("id,saludo\n1,1\n")
            items, humano = compare._leer_humano(ruta)
        self.assertEqual(items, ["saludo"])
        self.assertIn("1", humano)
