import contextlib
import csv
import io
import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

from jevqa import pipeline
from jevqa import rubric as rubric_mod
from jevqa.__main__ import EXIT_ENTRADA_INVALIDA, EXIT_OK
from jevqa.__main__ import main as cli_main
from jevqa.anonymize import anonymize
from jevqa.jev_client import FakeJev, JevAuthError, JevRetriesExhaustedError

RUBRIC_PATH = os.path.join(os.path.dirname(__file__), "..", "rubrics", "soporte_es.json")
MINI_CSV_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "mini.csv")
RUBRIC = rubric_mod.load_rubric(RUBRIC_PATH)
ITEM_IDS = [item["id"] for item in RUBRIC["items"]]
COLUMNAS = ["id", "agente", "campaña", "fecha", "texto"]


def escribir_csv(path, filas, columnas=None):
    columnas = columnas or COLUMNAS
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columnas)
        writer.writeheader()
        for row in filas:
            writer.writerow(row)


def fila(id_, texto=None, agente="Ana Perez", campaña="soporte_tecnico", fecha="2026-01-01", **extra):
    if texto is None:
        texto = f"Hola, gracias por contactarnos, ¿en qué puedo ayudarle? (caso {id_})"
    d = {"id": id_, "agente": agente, "campaña": campaña, "fecha": fecha, "texto": texto}
    d.update(extra)
    return d


def respuesta_valida(score=1, choice="soporte_tecnico"):
    answers = {item_id: {"type": "noul", "noul": 0.8} for item_id in ITEM_IDS}
    answers[rubric_mod.RIESGO_ID] = {
        "type": "score",
        "score": score,
        "confidence": 0.9,
        "probabilities": {"0": 0.1, "1": 0.7, "2": 0.1, "3": 0.1},
    }
    answers[rubric_mod.MOTIVO_ID] = {
        "type": "choice",
        "choice": choice,
        "confidence": 0.8,
        "probabilities": {op: round(1 / len(RUBRIC["motivo"]["opciones"]), 4)
                           for op in RUBRIC["motivo"]["opciones"]},
    }
    return {"model": "fake", "answers": answers}


class ClienteConFallosPorEstado:
    """Doble de Jev: falla para los `state` dados, responde `default_response` al resto."""

    def __init__(self, default_response, fallos_por_estado=None):
        self.default_response = default_response
        self.fallos_por_estado = fallos_por_estado or {}
        self.calls = []

    def evaluate(self, request):
        self.calls.append(request)
        state = request.get("state")
        if state in self.fallos_por_estado:
            raise self.fallos_por_estado[state]
        return self.default_response


class FakeReloj:
    """Reloj y espera falsos acoplados: dormir avanza el reloj, nada espera de verdad."""

    def __init__(self):
        self.now = 0.0
        self.waits = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.now += seconds


def leer_salida(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class TmpDirTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)

    def path(self, name):
        return os.path.join(self.tmpdir, name)


class EntradaInvalidaTests(TmpDirTestCase):
    def test_csv_completamente_vacio(self):
        entrada = self.path("entrada.csv")
        with open(entrada, "w", encoding="utf-8"):
            pass

        with self.assertRaises(pipeline.EntradaInvalidaError):
            pipeline.leer_entrada(entrada)

    def test_csv_con_cabecera_pero_sin_filas(self):
        entrada = self.path("entrada.csv")
        escribir_csv(entrada, [])

        with self.assertRaises(pipeline.EntradaInvalidaError):
            pipeline.leer_entrada(entrada)

    def test_columnas_faltantes_se_nombran_en_el_mensaje(self):
        entrada = self.path("entrada.csv")
        escribir_csv(entrada, [{"id": "1", "agente": "A", "fecha": "2026-01-01", "texto": "hola"}],
                      columnas=["id", "agente", "fecha", "texto"])

        with self.assertRaises(pipeline.EntradaInvalidaError) as ctx:
            pipeline.leer_entrada(entrada)
        self.assertIn("campaña", str(ctx.exception))

    def test_id_repetido(self):
        entrada = self.path("entrada.csv")
        escribir_csv(entrada, [fila("1"), fila("1")])

        with self.assertRaises(pipeline.EntradaInvalidaError):
            pipeline.leer_entrada(entrada)

    def test_id_vacio(self):
        entrada = self.path("entrada.csv")
        escribir_csv(entrada, [fila(" ")])

        with self.assertRaises(pipeline.EntradaInvalidaError):
            pipeline.leer_entrada(entrada)


    def test_fichero_inexistente(self):
        with self.assertRaises(pipeline.EntradaInvalidaError):
            pipeline.leer_entrada(self.path("no_existe.csv"))

    def test_fichero_no_utf8(self):
        entrada = self.path("entrada.csv")
        with open(entrada, "w", encoding="cp1252", newline="") as f:
            f.write("id,agente,campaña,fecha,texto\n1,Ana,soporte,2026-01-01,hola\n")

        with self.assertRaises(pipeline.EntradaInvalidaError):
            pipeline.leer_entrada(entrada)

    def test_fila_con_campos_de_menos_o_de_mas(self):
        for linea in ("2,Ana,soporte,2026-01-01", "2,Ana,soporte,2026-01-01,hola,extra"):
            with self.subTest(linea=linea):
                entrada = self.path("entrada.csv")
                with open(entrada, "w", encoding="utf-8", newline="") as f:
                    f.write("id,agente,campaña,fecha,texto\n1,Ana,soporte,2026-01-01,hola\n")
                    f.write(linea + "\n")

                with self.assertRaises(pipeline.EntradaInvalidaError) as ctx:
                    pipeline.leer_entrada(entrada)
                self.assertIn("fila 3", str(ctx.exception))


class AuditarTests(TmpDirTestCase):
    def test_fila_demasiado_larga_no_hace_llamada(self):
        entrada = self.path("entrada.csv")
        salida = self.path("salida.csv")
        escribir_csv(entrada, [fila("1")])
        cliente = FakeJev(default_response=respuesta_valida())

        with mock.patch.object(pipeline, "MAX_TOKENS", 5):
            resumen = pipeline.auditar(entrada, salida, cliente, RUBRIC)

        self.assertEqual(resumen["demasiado_larga"], 1)
        self.assertEqual(resumen["llamadas"], 0)
        self.assertEqual(len(cliente.calls), 0)
        filas = leer_salida(salida)
        self.assertEqual(filas[0]["estado"], "demasiado_larga")

    def test_fila_con_error_500_no_detiene_el_lote(self):
        entrada = self.path("entrada.csv")
        salida = self.path("salida.csv")
        filas_in = [fila("1"), fila("2"), fila("3")]
        escribir_csv(entrada, filas_in)

        estado_fallido = anonymize(filas_in[1]["texto"], [filas_in[1]["agente"]])
        cliente = ClienteConFallosPorEstado(
            respuesta_valida(),
            fallos_por_estado={estado_fallido: JevRetriesExhaustedError("500 repetido")},
        )

        resumen = pipeline.auditar(entrada, salida, cliente, RUBRIC, max_workers=1)

        self.assertEqual(resumen["ok"], 2)
        self.assertEqual(resumen["error"], 1)
        filas_out = {f["id"]: f for f in leer_salida(salida)}
        self.assertEqual(filas_out["2"]["estado"], "error")
        self.assertIn("500 repetido", filas_out["2"]["detalle"])
        self.assertEqual(filas_out["1"]["estado"], "ok")
        self.assertEqual(filas_out["3"]["estado"], "ok")

    def test_relanzar_lote_a_medias_solo_llama_para_la_fila_en_error(self):
        entrada = self.path("entrada.csv")
        salida = self.path("salida.csv")
        filas_in = [fila("1"), fila("2"), fila("3")]
        escribir_csv(entrada, filas_in)

        estado_fallido = anonymize(filas_in[1]["texto"], [filas_in[1]["agente"]])
        cliente_1 = ClienteConFallosPorEstado(
            respuesta_valida(),
            fallos_por_estado={estado_fallido: JevRetriesExhaustedError("500")},
        )
        pipeline.auditar(entrada, salida, cliente_1, RUBRIC, max_workers=1)

        cliente_2 = ClienteConFallosPorEstado(respuesta_valida())
        resumen_2 = pipeline.auditar(entrada, salida, cliente_2, RUBRIC, max_workers=1)

        self.assertEqual(resumen_2["saltadas"], 2)
        self.assertEqual(resumen_2["llamadas"], 1)
        self.assertEqual(len(cliente_2.calls), 1)
        self.assertEqual(cliente_2.calls[0]["state"], estado_fallido)

        filas_out = leer_salida(salida)
        self.assertEqual(len(filas_out), 3)
        ids = [f["id"] for f in filas_out]
        self.assertEqual(sorted(ids), ["1", "2", "3"])
        self.assertEqual(len(ids), len(set(ids)))
        estados = {f["id"]: f["estado"] for f in filas_out}
        self.assertEqual(estados, {"1": "ok", "2": "ok", "3": "ok"})

    def test_relanzar_con_otra_entrada_no_borra_resultados_pagados(self):
        salida = self.path("salida.csv")
        entrada_a = self.path("a.csv")
        entrada_b = self.path("b.csv")
        escribir_csv(entrada_a, [fila("1"), fila("2")])
        escribir_csv(entrada_b, [fila("3")])

        pipeline.auditar(entrada_a, salida, ClienteConFallosPorEstado(respuesta_valida()), RUBRIC)
        resumen = pipeline.auditar(
            entrada_b, salida, ClienteConFallosPorEstado(respuesta_valida()), RUBRIC
        )

        self.assertEqual(resumen["saltadas"], 0)
        self.assertEqual(sorted(f["id"] for f in leer_salida(salida)), ["1", "2", "3"])

    def test_50_filas_con_fakejev_dan_50_filas_de_salida_y_relanzar_hace_0_llamadas(self):
        entrada = self.path("entrada.csv")
        salida = self.path("salida.csv")
        filas_in = [fila(str(i), texto=f"Interacción número {i}, gracias por su paciencia.")
                    for i in range(50)]
        escribir_csv(entrada, filas_in)

        cliente_1 = FakeJev(default_response=respuesta_valida())
        resumen_1 = pipeline.auditar(entrada, salida, cliente_1, RUBRIC)
        self.assertEqual(resumen_1["ok"], 50)
        self.assertEqual(resumen_1["llamadas"], 50)
        self.assertEqual(len(leer_salida(salida)), 50)

        cliente_2 = FakeJev(default_response=respuesta_valida())
        resumen_2 = pipeline.auditar(entrada, salida, cliente_2, RUBRIC)
        self.assertEqual(resumen_2["llamadas"], 0)
        self.assertEqual(resumen_2["saltadas"], 50)
        self.assertEqual(len(cliente_2.calls), 0)
        self.assertEqual(len(leer_salida(salida)), 50)

    def test_cuerpo_enviado_no_contiene_datos_personales_sembrados(self):
        entrada = self.path("entrada.csv")
        salida = self.path("salida.csv")
        cedula = "1710034065"  # cédula válida de Pichincha
        tarjeta = "4111111111111111"  # pasa Luhn
        movil = "0991234567"
        correo = "cliente@example.com"
        agente_nombre = "María López"
        agente_sin_tilde_otra_capitalizacion = "maria lopez"

        texto = (
            f"Mi cedula es {cedula} y mi tarjeta {tarjeta}. Llámenme al {movil} "
            f"o escriban a {correo}. Hablé con {agente_sin_tilde_otra_capitalizacion} ayer."
        )
        escribir_csv(entrada, [fila("1", texto=texto, agente=agente_nombre)])

        cliente = FakeJev(default_response=respuesta_valida())
        pipeline.auditar(entrada, salida, cliente, RUBRIC)

        self.assertEqual(len(cliente.calls), 1)
        cuerpo = str(cliente.calls[0])
        cuerpo_solo_digitos = re.sub(r"\D", "", cuerpo)

        self.assertNotIn(cedula, cuerpo)
        self.assertNotIn(tarjeta, cuerpo)
        self.assertNotIn(movil, cuerpo)
        self.assertNotIn(correo, cuerpo)
        self.assertNotIn("maria lopez", cuerpo.lower())
        self.assertNotIn("lopez", cuerpo.lower())
        self.assertNotIn(cedula, cuerpo_solo_digitos)
        self.assertNotIn(tarjeta, cuerpo_solo_digitos)
        self.assertNotIn(movil, cuerpo_solo_digitos)

    def test_jevautherror_aborta_el_lote_y_conserva_lo_escrito(self):
        entrada = self.path("entrada.csv")
        salida = self.path("salida.csv")
        filas_in = [fila("1"), fila("2")]
        escribir_csv(entrada, filas_in)

        estado_2 = anonymize(filas_in[1]["texto"], [filas_in[1]["agente"]])
        cliente = ClienteConFallosPorEstado(
            respuesta_valida(),
            fallos_por_estado={estado_2: JevAuthError("401")},
        )

        with self.assertRaises(JevAuthError):
            pipeline.auditar(entrada, salida, cliente, RUBRIC, max_workers=1)

        filas_out = leer_salida(salida)
        self.assertEqual(len(filas_out), 1)
        self.assertEqual(filas_out[0]["id"], "1")
        self.assertEqual(filas_out[0]["estado"], "ok")

    def test_salida_con_cabecera_distinta_lanza_error_tipado(self):
        entrada = self.path("entrada.csv")
        salida = self.path("salida.csv")
        escribir_csv(entrada, [fila("1")])
        with open(salida, "w", newline="", encoding="utf-8") as f:
            f.write("columna_rara,otra\nvalor,valor\n")

        cliente = FakeJev(default_response=respuesta_valida())
        with self.assertRaises(pipeline.SalidaInvalidaError):
            pipeline.auditar(entrada, salida, cliente, RUBRIC)


class RateLimiterTests(unittest.TestCase):
    def test_llamadas_sucesivas_respetan_el_intervalo_minimo(self):
        reloj = FakeReloj()
        limiter = pipeline.RateLimiter(0.06, clock=reloj.clock, sleep=reloj.sleep)

        for _ in range(4):
            limiter.esperar()

        self.assertEqual(reloj.waits, [0.06, 0.06, 0.06])


class CliTests(TmpDirTestCase):
    def test_auditar_fake_sobre_mini_csv_exit_0(self):
        salida = self.path("mini.auditado.csv")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            codigo = cli_main(["auditar", MINI_CSV_PATH, "--salida", salida, "--fake"])

        self.assertEqual(codigo, EXIT_OK)
        self.assertEqual(len(leer_salida(salida)), 5)

    def test_columnas_faltantes_exit_distinto_de_0_y_mensaje_en_stderr(self):
        entrada = self.path("entrada.csv")
        escribir_csv(entrada, [{"id": "1", "agente": "A", "fecha": "2026-01-01", "texto": "hola"}],
                      columnas=["id", "agente", "fecha", "texto"])
        salida = self.path("salida.csv")
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            codigo = cli_main(["auditar", entrada, "--salida", salida, "--fake"])

        self.assertEqual(codigo, EXIT_ENTRADA_INVALIDA)
        self.assertNotEqual(codigo, 0)
        self.assertIn("campaña", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
