import csv
import os
import shutil
import tempfile
import unittest

from jevqa import report
from jevqa import rubric as rubric_mod
from jevqa.__main__ import EXIT_ENTRADA_INVALIDA, EXIT_OK
from jevqa.__main__ import RUBRIC_PATH as CLI_RUBRIC_PATH
from jevqa.__main__ import main as cli_main

ITEMS = [
    {"id": "saludo", "pregunta": "¿saluda?", "peso": 0.2, "critico": False},
    {"id": "escucha", "pregunta": "¿escucha?", "peso": 0.3, "critico": False},
    {"id": "resolucion", "pregunta": "¿resuelve?", "peso": 0.5, "critico": True},
]
ITEM_IDS = [item["id"] for item in ITEMS]
HEADER = ["id", "agente", "campaña", "fecha", "estado", "detalle"] + ITEM_IDS + ["riesgo", "motivo"]

RUBRIC = {"items": [dict(item) for item in ITEMS]}

CAMPAÑA_A = "<script>alert(1)</script>"
CAMPAÑA_B = "Ventas/../secreto"


def escribir_csv(path, filas):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER)
        writer.writeheader()
        for fila in filas:
            writer.writerow(fila)


def fila_ok(id_, agente, campaña, saludo, escucha, resolucion, fecha="2026-01-01", motivo="soporte"):
    return {
        "id": id_,
        "agente": agente,
        "campaña": campaña,
        "fecha": fecha,
        "estado": "ok",
        "detalle": "",
        "saludo": saludo,
        "escucha": escucha,
        "resolucion": resolucion,
        "riesgo": 0,
        "motivo": motivo,
    }


def fila_sin_nota(id_, agente, campaña, estado, detalle, fecha="2026-01-01"):
    return {
        "id": id_,
        "agente": agente,
        "campaña": campaña,
        "fecha": fecha,
        "estado": estado,
        "detalle": detalle,
        "saludo": "",
        "escucha": "",
        "resolucion": "",
        "riesgo": "",
        "motivo": "",
    }


def filas_muestra():
    return [
        # Campaña A: script-agent (nota 100), Ana (nota 80, en cola), Bea
        # (nota 50, crítico fallido), más una fila de error con script en el
        # detalle.
        fila_ok("s1", "<script>alert(1)</script>", CAMPAÑA_A, 0.9, 0.9, 0.9,
                motivo="<script>alert(1)</script>"),
        fila_ok("s2", "Bea", CAMPAÑA_A, 0.9, 0.9, 0.1),
        fila_ok("s3", "Ana", CAMPAÑA_A, 0.1, 0.55, 0.9),
        fila_sin_nota("s4", "Ana", CAMPAÑA_A, "error", "<script>alert(1)</script>"),
        # Campaña B: una sola fila demasiado larga, sin filas puntuadas.
        fila_sin_nota("v1", "Cade", CAMPAÑA_B, "demasiado_larga", "excede tokens"),
    ]


def _seccion(html_doc, id_):
    inicio = html_doc.index(f'id="{id_}"')
    fin = html_doc.index("</section>", inicio)
    return html_doc[inicio:fin]


class TestGenerarInformes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.csv_path = os.path.join(self.tmp, "resultados.csv")
        escribir_csv(self.csv_path, filas_muestra())
        self.out_dir = os.path.join(self.tmp, "informes")

    def test_genera_un_html_por_campaña(self):
        rutas = report.generar_informes(RUBRIC, self.csv_path, self.out_dir)
        self.assertEqual(len(rutas), 2)
        for ruta in rutas:
            self.assertTrue(os.path.isfile(ruta))

    def test_nombre_de_archivo_seguro_para_campaña_con_barra_y_puntos(self):
        rutas = report.generar_informes(RUBRIC, self.csv_path, self.out_dir)
        for ruta in rutas:
            abs_ruta = os.path.abspath(ruta)
            abs_out = os.path.abspath(self.out_dir)
            self.assertTrue(abs_ruta.startswith(abs_out + os.sep))
            self.assertNotIn("..", os.path.relpath(abs_ruta, abs_out).split(os.sep))

    def test_campañas_con_el_mismo_slug_no_se_pisan(self):
        filas = [fila_ok("x1", "Ana", "a/b", 0.9, 0.9, 0.9), fila_ok("x2", "Ana", "a_b", 0.9, 0.9, 0.9),
                 fila_ok("x3", "Ana", "a_b_2", 0.9, 0.9, 0.9), fila_ok("x4", "Ana", "CON", 0.9, 0.9, 0.9)]
        path = os.path.join(self.tmp, "slugs.csv")
        escribir_csv(path, filas)
        rutas = report.generar_informes(RUBRIC, path, self.out_dir)
        self.assertEqual(len(set(rutas)), 4)
        self.assertEqual(len(os.listdir(self.out_dir)), 4)
        self.assertTrue(all(os.path.basename(r).startswith("informe_") for r in rutas))

    def test_coste_por_llamada_invalido_lanza_informe_error(self):
        for coste in (-0.01, float("nan"), float("inf")):
            with self.assertRaises(report.InformeError, msg=coste):
                report.generar_informes(RUBRIC, self.csv_path, self.out_dir, coste)

    def test_salida_dir_que_es_un_archivo_lanza_informe_error(self):
        with self.assertRaises(report.InformeError):
            report.generar_informes(RUBRIC, self.csv_path, self.csv_path)

    def test_falta_columna_de_ítem_lanza_informe_error(self):
        header_incompleto = [c for c in HEADER if c != "resolucion"]
        path = os.path.join(self.tmp, "sin_item.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=header_incompleto)
            writer.writeheader()
        with self.assertRaises(report.InformeError):
            report.generar_informes(RUBRIC, path, self.out_dir)

    def test_csv_solo_cabecera_lanza_informe_error(self):
        path = os.path.join(self.tmp, "vacio.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=HEADER)
            writer.writeheader()
        with self.assertRaises(report.InformeError):
            report.generar_informes(RUBRIC, path, self.out_dir)

    def test_probabilidad_invalida_nombra_el_id_en_el_error(self):
        filas = [fila_ok("bad1", "Ana", CAMPAÑA_A, "no-numerico", 0.9, 0.9)]
        path = os.path.join(self.tmp, "prob_invalida.csv")
        escribir_csv(path, filas)
        with self.assertRaises(report.InformeError) as ctx:
            report.generar_informes(RUBRIC, path, self.out_dir)
        self.assertIn("bad1", str(ctx.exception))

    def test_cli_informe_exit_2_en_entrada_invalida(self):
        # `informe` en la CLI usa siempre la rúbrica real (RUBRIC_PATH), así
        # que el CSV de esta clase (con una rúbrica reducida de prueba) ya es
        # entrada inválida para ella; el caso de éxito con la rúbrica real
        # está en TestCLIInformeConRubricaReal.
        rc_error = cli_main(["informe", self.csv_path, "--salida-dir", self.out_dir])
        self.assertEqual(rc_error, EXIT_ENTRADA_INVALIDA)
        rc_no_existe = cli_main(["informe", os.path.join(self.tmp, "no-existe.csv")])
        self.assertEqual(rc_no_existe, EXIT_ENTRADA_INVALIDA)


class TestRenderCampaña(unittest.TestCase):
    def setUp(self):
        self.filas = filas_muestra()
        self.filas_a = [f for f in self.filas if f["campaña"] == CAMPAÑA_A]
        self.filas_b = [f for f in self.filas if f["campaña"] == CAMPAÑA_B]

    def test_todas_las_secciones_presentes(self):
        html_doc = report.render_campaña(RUBRIC, CAMPAÑA_A, self.filas_a, 0.001)
        for id_ in (
            "resumen",
            "ranking-de-agentes",
            "peores-interacciones",
            "cola-de-revision",
            "filas-sin-nota",
            "coste-de-jev",
        ):
            self.assertIn(f'id="{id_}"', html_doc)

    def test_orden_del_ranking_por_nota_media_descendente(self):
        html_doc = report.render_campaña(RUBRIC, CAMPAÑA_A, self.filas_a, 0.001)
        ranking = _seccion(html_doc, "ranking-de-agentes")
        # nota media: script-agent=100, Ana=80, Bea=50
        i_script = ranking.index("&lt;script&gt;alert(1)&lt;/script&gt;")
        i_ana = ranking.index("Ana")
        i_bea = ranking.index("Bea")
        self.assertLess(i_script, i_ana)
        self.assertLess(i_ana, i_bea)

    def test_script_escapado_en_agente_campaña_detalle_y_motivo(self):
        html_doc = report.render_campaña(RUBRIC, CAMPAÑA_A, self.filas_a, 0.001)
        self.assertNotIn("<script>alert(1)</script>", html_doc)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html_doc)

    def test_secciones_vacias_muestran_sin_datos(self):
        html_doc = report.render_campaña(RUBRIC, CAMPAÑA_B, self.filas_b, 0.001)
        self.assertIn("sin datos", _seccion(html_doc, "peores-interacciones"))
        self.assertIn("sin datos", _seccion(html_doc, "cola-de-revision"))

    def test_coste_es_filas_ok_por_coste_por_llamada(self):
        coste_por_llamada = 0.0025
        html_doc = report.render_campaña(RUBRIC, CAMPAÑA_A, self.filas_a, coste_por_llamada)
        # 3 filas ok en la campaña A (s1, s2, s3)
        esperado = 3 * coste_por_llamada
        self.assertIn(f"${esperado:.4f}", _seccion(html_doc, "coste-de-jev"))


class TestCLIInformeConRubricaReal(unittest.TestCase):
    """Reproduce el flujo real de la CLI: la rúbrica que usa `informe` es fija."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        rubric = rubric_mod.load_rubric(CLI_RUBRIC_PATH)
        item_ids = [item["id"] for item in rubric["items"]]
        header = ["id", "agente", "campaña", "fecha", "estado", "detalle"] + item_ids + [
            "riesgo",
            "motivo",
        ]
        path = os.path.join(self.tmp, "resultados.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            fila = {
                "id": "int_001",
                "agente": "Ana",
                "campaña": "soporte",
                "fecha": "2026-01-01",
                "estado": "ok",
                "detalle": "",
                "riesgo": 0,
                "motivo": "soporte_tecnico",
            }
            for item_id in item_ids:
                fila[item_id] = 0.9
            writer.writerow(fila)
        self.csv_path = path

    def test_cli_informe_genera_archivo_con_rubrica_real(self):
        out_dir = os.path.join(self.tmp, "informes")
        rc = cli_main(["informe", self.csv_path, "--salida-dir", out_dir])
        self.assertEqual(rc, EXIT_OK)
        self.assertEqual(len(os.listdir(out_dir)), 1)


if __name__ == "__main__":
    unittest.main()
