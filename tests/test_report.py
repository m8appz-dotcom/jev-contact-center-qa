"""Tests del informe HTML por campaña (fase 6)."""

from __future__ import annotations

import csv
import io
import json
import os
import tempfile
import unittest

from jevqa.pipeline import cabecera_salida
from jevqa.report import (
    ErrorResultados,
    generar_informes,
    leer_resultados,
    nombre_de_archivo,
    peores_interacciones,
    ranking_de_agentes,
)
from jevqa.rubric import load_rubric

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Rúbrica mínima: un ítem crítico de peso 60 y uno normal de peso 40, para
#: que las notas posibles sean 0, 40, 60 y 100 y se puedan razonar a mano.
RUBRICA = {
    "id": "mini",
    "version": "1",
    "items": [
        {"id": "respeto", "pregunta": "¿Trata con respeto?", "peso": 60, "critico": True},
        {"id": "cierre", "pregunta": "¿Se despide?", "peso": 40, "critico": False},
    ],
    "riesgo": {"pregunta": "¿Riesgo?", "niveles": ["Ninguno", "Bajo", "Medio", "Alto"]},
    "motivo": {"pregunta": "¿Motivo?", "opciones": {"soporte": "Soporte", "otro": "Otro"}},
}

SECCIONES = (
    "Ranking de agentes",
    "Peores interacciones",
    "Cola de revisión",
    "Coste de Jev del periodo",
)


def rubrica() -> dict:
    ruta = os.path.join(tempfile.mkdtemp(), "mini.json")
    with open(ruta, "w", encoding="utf-8") as archivo:
        json.dump(RUBRICA, archivo, ensure_ascii=False)
    return load_rubric(ruta)


def fila(
    ident: str,
    *,
    agente: str = "Rosa Delgado",
    campana: str = "telco",
    fecha: str = "2026-08-03",
    respeto: float = 0.95,
    cierre: float = 0.95,
    estado: str = "ok",
    error: str = "",
    tokens: int = 1000,
) -> dict:
    datos = {
        "id": ident,
        "agente": agente,
        "campaña": campana,
        "fecha": fecha,
        "estado": estado,
        "error": error,
        "modelo": "jev-1.13.0",
        "motivo": "soporte",
        "motivo_confianza": 0.9,
        "riesgo_nivel": 0,
        "riesgo_etiqueta": "Ninguno",
        "riesgo_confianza": 0.9,
        "tokens_entrada": tokens if estado == "ok" else 0,
        "tokens_salida": 20,
        "coste_usd": tokens * 42 / 1e9 if estado == "ok" else 0.0,
    }
    for item, p in (("respeto", respeto), ("cierre", cierre)):
        datos[f"{item}_prob"] = p if estado == "ok" else ""
        datos[f"{item}_conf"] = abs(2 * p - 1) if estado == "ok" else ""
    return datos


def escribir_resultados(filas: list[dict], rub: dict) -> str:
    ruta = os.path.join(tempfile.mkdtemp(), "resultados.csv")
    with io.open(ruta, "w", encoding="utf-8", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=cabecera_salida(rub))
        escritor.writeheader()
        escritor.writerows(filas)
    return ruta


def leer(ruta: str) -> str:
    with open(ruta, encoding="utf-8") as archivo:
        return archivo.read()


class Caso(unittest.TestCase):
    def setUp(self):
        self.rubrica = rubrica()
        self.carpeta = tempfile.mkdtemp()


class TestEnglishReport(Caso):
    def setUp(self):
        super().setUp()
        self.rubrica["idioma"] = "en"

    def test_english_report_keeps_native_critical_failure_and_sample_rules(self):
        self.rubrica["items"][0]["peso"] = 10
        self.rubrica["items"][1]["peso"] = 90
        source = escribir_resultados([fila("critical", respeto=0.05)], self.rubrica)
        report = leer(generar_informes(source, self.carpeta, self.rubrica)[0])
        self.assertIn('<html lang="en">', report)
        self.assertIn("Agent ranking", report)
        self.assertIn("Insufficient sample", report)
        self.assertIn("Needs attention", report)
        self.assertIn("90.0", report)
        self.assertNotIn("90,0", report)
        self.assertIn("Failed interactions", report)
        self.assertNotIn("Below threshold", report)
        self.assertIn("do not make personnel decisions", report)

    def test_uncertain_judgment_remains_in_review_queue_and_errors_unscored(self):
        source = escribir_resultados([
            fila("uncertain", respeto=0.49),
            fila("error-row", estado="error", error="Provider unavailable"),
        ], self.rubrica)
        report = leer(generar_informes(source, self.carpeta, self.rubrica)[0])
        self.assertIn("Human review queue (1)", report)
        self.assertIn("Low model confidence", report)
        self.assertIn("Ambiguous probability", report)
        self.assertIn("Unscored interactions", report)
        self.assertIn("Provider unavailable", report)

    def test_english_localization_escapes_data_without_translating_it(self):
        source = escribir_resultados([
            fila("safe", agente='Ranking de agentes<script>alert(1)</script>',
                 campana='<img src=x onerror=alert(1)>'),
        ], self.rubrica)
        report = leer(generar_informes(source, self.carpeta, self.rubrica, note='<script>note</script>')[0])
        self.assertIn("&lt;script&gt;note&lt;/script&gt;", report)
        self.assertNotIn("<script>", report)
        self.assertNotIn("<img src=x", report)
        self.assertIn("Ranking de agentes&lt;script&gt;", report)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", report)


class TestLectura(Caso):
    def test_califica_las_filas_ok_y_aparta_las_demas(self):
        ruta = escribir_resultados(
            [
                fila("A"),
                fila("B", estado="error", error="ReintentosAgotados: 500"),
                fila("C", estado="demasiado_larga", error="demasiado larga"),
            ],
            self.rubrica,
        )
        leido = leer_resultados(ruta, self.rubrica)
        self.assertEqual([c["id"] for c in leido["calificaciones"]], ["A"])
        self.assertEqual([f["id"] for f in leido["sin_calificar"]], ["B", "C"])
        self.assertIn("500", leido["sin_calificar"][0]["motivo"])

    def test_nota_y_estado(self):
        ruta = escribir_resultados(
            [fila("bien"), fila("sin_cierre", cierre=0.05), fila("maltrato", respeto=0.05)],
            self.rubrica,
        )
        por_id = {c["id"]: c for c in leer_resultados(ruta, self.rubrica)["calificaciones"]}
        self.assertEqual(por_id["bien"]["nota"], 100.0)
        self.assertEqual(por_id["sin_cierre"]["nota"], 60.0)
        self.assertEqual(por_id["sin_cierre"]["estado"], "suspenso", "60 < 70")
        self.assertEqual(por_id["maltrato"]["nota"], 40.0)
        self.assertEqual(por_id["maltrato"]["criticas_falladas"], ["respeto"])

    def test_filtra_por_periodo(self):
        ruta = escribir_resultados(
            [fila("julio", fecha="2026-07-30"), fila("agosto", fecha="2026-08-10"), fila("sept", fecha="2026-09-02")],
            self.rubrica,
        )
        leido = leer_resultados(ruta, self.rubrica, desde="2026-08-01", hasta="2026-08-31")
        self.assertEqual([c["id"] for c in leido["calificaciones"]], ["agosto"])

    def test_fila_con_numeros_ilegibles_no_tumba_el_informe(self):
        mala = fila("mala")
        mala["respeto_prob"] = "no-es-numero"
        ruta = escribir_resultados([fila("buena"), mala], self.rubrica)
        leido = leer_resultados(ruta, self.rubrica)
        self.assertEqual([c["id"] for c in leido["calificaciones"]], ["buena"])
        self.assertIn("no se pudo calificar", leido["sin_calificar"][0]["motivo"])

    def test_archivo_que_no_existe(self):
        with self.assertRaises(ErrorResultados):
            leer_resultados(os.path.join(self.carpeta, "no.csv"), self.rubrica)

    def test_csv_que_no_es_de_auditar(self):
        ruta = os.path.join(self.carpeta, "otro.csv")
        with open(ruta, "w", encoding="utf-8") as archivo:
            archivo.write("id,texto\nA,hola\n")
        with self.assertRaises(ErrorResultados) as ctx:
            leer_resultados(ruta, self.rubrica)
        self.assertIn("estado", str(ctx.exception))


class TestSecciones(Caso):
    def test_ranking_deja_fuera_a_quien_tiene_poca_muestra(self):
        filas = [fila(f"R{i}", agente="Rosa", cierre=0.05) for i in range(5)]
        filas += [fila(f"K{i}", agente="Kevin") for i in range(6)]
        filas += [fila("B1", agente="Byron")]  # una sola llamada, nota 100
        ruta = escribir_resultados(filas, self.rubrica)
        ranking = ranking_de_agentes(leer_resultados(ruta, self.rubrica)["calificaciones"])

        self.assertEqual([g["clave"] for g in ranking["con_muestra"]], ["Kevin", "Rosa"])
        self.assertEqual([g["clave"] for g in ranking["sin_muestra"]], ["Byron"])

    def test_peores_interacciones_ponen_primero_las_criticas(self):
        ruta = escribir_resultados(
            [fila("nota60", cierre=0.05), fila("critica", respeto=0.05), fila("bien")],
            self.rubrica,
        )
        peores = peores_interacciones(leer_resultados(ruta, self.rubrica)["calificaciones"])
        self.assertEqual([c["id"] for c in peores], ["critica", "nota60", "bien"])


class TestHTML(Caso):
    def test_un_archivo_por_campana_con_todas_las_secciones(self):
        ruta = escribir_resultados(
            [
                fila("A", campana="telco"),
                fila("B", campana="banca"),
                fila("C", campana="banca", respeto=0.5),  # ambiguo: va a la cola
                fila("D", campana=""),
            ],
            self.rubrica,
        )
        rutas = generar_informes(ruta, self.carpeta, self.rubrica)

        nombres = sorted(os.path.basename(r) for r in rutas)
        self.assertEqual(
            nombres,
            ["informe_banca.html", "informe_sin_campana.html", "informe_telco.html"],
        )
        banca = leer(os.path.join(self.carpeta, "informe_banca.html"))
        for seccion in SECCIONES:
            with self.subTest(seccion=seccion):
                self.assertIn(seccion, banca)
        self.assertIn("Cola de revisión (1)", banca)
        self.assertIn("2026-08-03", banca, "el periodo sale de las fechas")

    def test_se_escapa_el_script(self):
        ataque = "<script>alert('x')</script>"
        ruta = escribir_resultados(
            [
                fila("A", agente=ataque, campana=ataque),
                fila("B", agente="Rosa", campana=ataque, estado="error", error=ataque),
                fila(f"<img src=x onerror=alert(1)>", campana=ataque, respeto=0.05),
            ],
            self.rubrica,
        )
        rutas = generar_informes(ruta, self.carpeta, self.rubrica)
        contenido = leer(rutas[0])

        self.assertNotIn("<script>", contenido)
        self.assertNotIn("<img", contenido)
        self.assertIn("&lt;script&gt;", contenido)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", contenido)
        self.assertEqual(os.path.basename(rutas[0]), "informe_script_alert_x_script.html")

    def test_coste_del_periodo(self):
        ruta = escribir_resultados(
            [fila("A", tokens=1_000_000), fila("B", tokens=1_000_000), fila("C", estado="error", error="x")],
            self.rubrica,
        )
        contenido = leer(generar_informes(ruta, self.carpeta, self.rubrica)[0])
        self.assertIn("Tokens de entrada</td><td>2.000.000", contenido)
        self.assertIn("US$ 0,084000", contenido)  # 2 M tokens a 42 US$ por mil millones
        self.assertIn("Interacciones sin auditar", contenido)

    def test_periodo_sin_interacciones_no_genera_nada(self):
        ruta = escribir_resultados([fila("A", fecha="2026-08-03")], self.rubrica)
        rutas = generar_informes(ruta, self.carpeta, self.rubrica, desde="2027-01-01")
        self.assertEqual(rutas, [])

    def test_nombres_de_archivo(self):
        self.assertEqual(nombre_de_archivo("Campaña Móvil"), "informe_Campana_Movil.html")
        self.assertEqual(nombre_de_archivo("../../etc"), "informe_etc.html")
        self.assertEqual(nombre_de_archivo(""), "informe_sin_campana.html")


class TestCLI(unittest.TestCase):
    def test_informe_sobre_la_salida_de_auditar(self):
        from jevqa.__main__ import main

        carpeta = tempfile.mkdtemp()
        resultados = os.path.join(carpeta, "resultados.csv")
        mini = os.path.join(RAIZ, "tests", "fixtures", "mini.csv")
        self.assertEqual(main(["auditar", mini, "--salida", resultados, "--fake", "--concurrencia", "1"]), 0)
        self.assertEqual(main(["informe", resultados, "--salida", carpeta, "--fake"]), 0)

        html = sorted(f for f in os.listdir(carpeta) if f.endswith(".html"))
        self.assertEqual(
            html,
            ["informe_banca_tarjetas.html", "informe_seguros_salud.html", "informe_telco_hogar.html"],
        )

    def test_resultados_que_no_existen_salen_con_codigo_2(self):
        from jevqa.__main__ import main

        self.assertEqual(main(["informe", os.path.join(tempfile.mkdtemp(), "no.csv")]), 2)


if __name__ == "__main__":
    unittest.main()
