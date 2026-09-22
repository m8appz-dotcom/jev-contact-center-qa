"""Tests de la auditoría por lotes."""

from __future__ import annotations

import csv
import io
import os
import tempfile
import unittest

from jevqa.jev_client import ErrorServidor, FakeJev, ReintentosAgotados
from jevqa.pipeline import (
    ESTADO_ERROR,
    ESTADO_LARGA,
    ESTADO_OK,
    ErrorEntrada,
    Limitador,
    auditar,
    auditar_fila,
    demasiado_larga,
    estimar_tokens,
    ids_ya_auditados,
    leer_entrada,
)
from jevqa.rubric import load_rubric

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUBRICA = os.path.join(RAIZ, "rubrics", "soporte_es.json")
MINI = os.path.join(RAIZ, "tests", "fixtures", "mini.csv")

COLUMNAS = ["id", "agente", "cliente", "campaña", "fecha", "texto"]
TEXTO = (
    "Agente: Telco Hogar, buenos días, le habla Rosa Delgado.\n"
    "Cliente: Soy María López, mi cédula es 1712345675 y mi celular 0991234567.\n"
    "Agente: Gracias, señora López. ¿Qué ocurre?\n"
    "Cliente: El internet se corta y pago $19,90.\n"
    "Agente: Le agendo un técnico. ¿Algo más?\n"
    "Cliente: No, gracias.\n"
    "Agente: Buen día."
)
#: Los datos personales que van sembrados en TEXTO y no deben salir del proceso.
SEMBRADOS = ("1712345675", "0991234567", "María López", "Rosa Delgado")


def sin_esperas() -> Limitador:
    """Un limitador que reparte igual pero no duerme, para que los tests vuelen."""
    return Limitador(960, dormir=lambda _: None)


def escribir_csv(filas: list[dict], columnas: list[str] | None = None) -> str:
    ruta = os.path.join(tempfile.mkdtemp(), "entrada.csv")
    with io.open(ruta, "w", encoding="utf-8", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=columnas or COLUMNAS)
        escritor.writeheader()
        escritor.writerows(filas)
    return ruta


def fila(numero: int, **extra) -> dict:
    base = {
        "id": f"INT-{numero:03d}",
        "agente": "Rosa Delgado",
        "cliente": "María López",
        "campaña": "telco_hogar",
        "fecha": "2026-08-03",
        "texto": TEXTO,
    }
    base.update(extra)
    return base


def leer_salida(ruta: str) -> list[dict]:
    with open(ruta, encoding="utf-8", newline="") as archivo:
        return list(csv.DictReader(archivo))


class Caso(unittest.TestCase):
    def setUp(self):
        self.rubrica = load_rubric(RUBRICA)
        self.salida = os.path.join(tempfile.mkdtemp(), "resultados.csv")


class TestLecturaDeEntrada(Caso):
    def test_archivo_que_no_existe(self):
        with self.assertRaises(ErrorEntrada) as ctx:
            leer_entrada(os.path.join(tempfile.mkdtemp(), "no_existe.csv"))
        self.assertIn("no existe", str(ctx.exception))

    def test_csv_totalmente_vacio(self):
        ruta = os.path.join(tempfile.mkdtemp(), "vacio.csv")
        io.open(ruta, "w", encoding="utf-8").close()
        with self.assertRaises(ErrorEntrada) as ctx:
            leer_entrada(ruta)
        self.assertIn("vacío", str(ctx.exception))

    def test_csv_solo_con_cabecera(self):
        filas, _ = leer_entrada(escribir_csv([]))
        self.assertEqual(filas, [])

    def test_faltan_columnas(self):
        ruta = escribir_csv(
            [{"id": "A", "texto": "hola"}], columnas=["id", "texto"]
        )
        with self.assertRaises(ErrorEntrada) as ctx:
            leer_entrada(ruta)
        mensaje = str(ctx.exception)
        self.assertIn("agente", mensaje)
        self.assertIn("campaña", mensaje)
        self.assertIn("fecha", mensaje)

    def test_acepta_campana_sin_tilde(self):
        columnas = ["id", "agente", "campana", "fecha", "texto"]
        ruta = escribir_csv(
            [{"id": "A", "agente": "Rosa", "campana": "telco", "fecha": "2026-08-03", "texto": "x"}],
            columnas=columnas,
        )
        filas, _ = leer_entrada(ruta)
        self.assertEqual(filas[0]["campaña"], "telco")

    def test_id_vacio(self):
        with self.assertRaises(ErrorEntrada) as ctx:
            leer_entrada(escribir_csv([fila(1, id="")]))
        self.assertIn("id está vacía", str(ctx.exception))

    def test_ids_repetidos(self):
        with self.assertRaises(ErrorEntrada) as ctx:
            leer_entrada(escribir_csv([fila(1), fila(1)]))
        self.assertIn("repetidos", str(ctx.exception))

    def test_la_columna_cliente_es_opcional(self):
        columnas = ["id", "agente", "campaña", "fecha", "texto"]
        ruta = escribir_csv(
            [{"id": "A", "agente": "Rosa", "campaña": "t", "fecha": "2026-08-03", "texto": TEXTO}],
            columnas=columnas,
        )
        filas, resueltas = leer_entrada(ruta)
        self.assertNotIn("cliente", resueltas)
        self.assertEqual(len(filas), 1)


class TestFilaSuelta(Caso):
    def test_se_anonimiza_antes_de_llamar(self):
        cliente = FakeJev()
        auditar_fila(fila(1), self.rubrica, cliente)

        enviado = cliente.llamadas[0]["state"]
        for dato in SEMBRADOS:
            with self.subTest(dato=dato):
                self.assertNotIn(dato, enviado)
        self.assertIn("[CEDULA]", enviado)
        self.assertIn("$19,90", enviado, "el importe no se debe tapar")

    def test_fila_sin_texto(self):
        resultado, estado, error = auditar_fila(fila(1, texto=""), self.rubrica, FakeJev())
        self.assertIsNone(resultado)
        self.assertEqual(estado, ESTADO_ERROR)
        self.assertIn("no tiene texto", error)

    def test_fila_demasiado_larga_no_llama_a_jev(self):
        cliente = FakeJev()
        larga = fila(1, texto="palabra " * 20_000)

        resultado, estado, error = auditar_fila(larga, self.rubrica, cliente)

        self.assertIsNone(resultado)
        self.assertEqual(estado, ESTADO_LARGA)
        self.assertIn("32,000", error)
        self.assertEqual(cliente.llamadas, [], "no se gasta una llamada que la API rechaza")

    def test_el_limite_se_mide_con_el_state_y_la_pregunta_mas_larga(self):
        self.assertFalse(demasiado_larga(self.rubrica, "x" * 90_000))
        self.assertTrue(demasiado_larga(self.rubrica, "x" * 96_000))
        self.assertEqual(estimar_tokens("x" * 300), 100)

    def test_un_error_de_jev_se_registra_en_la_fila(self):
        cliente = FakeJev(errores=[ReintentosAgotados(4, ErrorServidor("500: caído", 500))])
        resultado, estado, error = auditar_fila(fila(1), self.rubrica, cliente)
        self.assertIsNone(resultado)
        self.assertEqual(estado, ESTADO_ERROR)
        self.assertIn("ReintentosAgotados", error)


class TestLote(Caso):
    def test_cincuenta_filas_dan_cincuenta_filas(self):
        entrada = escribir_csv([fila(n) for n in range(1, 51)])
        cliente = FakeJev()

        resumen = auditar(
            entrada, self.salida, self.rubrica, cliente, limitador=sin_esperas()
        )

        self.assertEqual(resumen["filas"], 50)
        self.assertEqual(resumen["auditadas"], 50)
        self.assertEqual(resumen["errores"], 0)
        self.assertEqual(len(cliente.llamadas), 50)

        salida = leer_salida(self.salida)
        self.assertEqual(len(salida), 50)
        self.assertEqual([f["id"] for f in salida], [f"INT-{n:03d}" for n in range(1, 51)])
        self.assertTrue(all(f["estado"] == ESTADO_OK for f in salida))

    def test_la_salida_trae_una_columna_por_item(self):
        entrada = escribir_csv([fila(1)])
        auditar(entrada, self.salida, self.rubrica, FakeJev(), limitador=sin_esperas())

        salida = leer_salida(self.salida)[0]
        for item in self.rubrica["items"]:
            self.assertIn(f"{item['id']}_prob", salida)
            self.assertIn(f"{item['id']}_conf", salida)
        self.assertIn(salida["motivo"], self.rubrica["motivo"]["opciones"])
        self.assertIn(salida["riesgo_etiqueta"], ["Ninguno", "Bajo", "Medio", "Alto"])
        self.assertGreater(float(salida["tokens_entrada"]), 0)

    def test_ningun_dato_personal_sale_en_el_lote(self):
        entrada = escribir_csv([fila(n) for n in range(1, 6)])
        cliente = FakeJev()

        auditar(entrada, self.salida, self.rubrica, cliente, limitador=sin_esperas())

        enviado = "\n".join(llamada["state"] for llamada in cliente.llamadas)
        for dato in SEMBRADOS:
            with self.subTest(dato=dato):
                self.assertNotIn(dato, enviado)

    def test_una_fila_con_error_500_no_detiene_el_lote(self):
        entrada = escribir_csv([fila(n) for n in range(1, 4)])
        cliente = FakeJev(
            errores=[None, ReintentosAgotados(4, ErrorServidor("500: caído", 500)), None]
        )

        resumen = auditar(
            entrada, self.salida, self.rubrica, cliente,
            concurrencia=1, limitador=sin_esperas(), registrar=lambda _: None,
        )

        self.assertEqual(resumen["auditadas"], 2)
        self.assertEqual(resumen["errores"], 1)
        salida = leer_salida(self.salida)
        self.assertEqual(len(salida), 3)
        self.assertEqual([f["estado"] for f in salida], [ESTADO_OK, ESTADO_ERROR, ESTADO_OK])
        self.assertIn("500", salida[1]["error"])

    def test_una_fila_demasiado_larga_queda_marcada_y_el_lote_sigue(self):
        entrada = escribir_csv(
            [fila(1), fila(2, texto="palabra " * 20_000), fila(3)]
        )
        cliente = FakeJev()

        resumen = auditar(
            entrada, self.salida, self.rubrica, cliente,
            concurrencia=1, limitador=sin_esperas(), registrar=lambda _: None,
        )

        self.assertEqual(resumen["auditadas"], 2)
        self.assertEqual(resumen["demasiado_largas"], 1)
        self.assertEqual(len(cliente.llamadas), 2)
        self.assertEqual(leer_salida(self.salida)[1]["estado"], ESTADO_LARGA)

    def test_el_coste_sale_de_los_tokens_devueltos(self):
        entrada = escribir_csv([fila(n) for n in range(1, 4)])
        resumen = auditar(
            entrada, self.salida, self.rubrica, FakeJev(), limitador=sin_esperas()
        )
        tokens = sum(int(f["tokens_entrada"]) for f in leer_salida(self.salida))
        self.assertEqual(resumen["tokens_entrada"], tokens)
        self.assertAlmostEqual(resumen["coste_usd"], tokens * 42 / 1e9)


class TestReanudacion(Caso):
    def test_relanzar_un_lote_completo_no_hace_ninguna_llamada(self):
        entrada = escribir_csv([fila(n) for n in range(1, 51)])
        auditar(entrada, self.salida, self.rubrica, FakeJev(), limitador=sin_esperas())

        segundo = FakeJev()
        resumen = auditar(
            entrada, self.salida, self.rubrica, segundo,
            limitador=sin_esperas(), registrar=lambda _: None,
        )

        self.assertEqual(segundo.llamadas, [], "relanzar no se debe pagar dos veces")
        self.assertEqual(resumen["saltadas"], 50)
        self.assertEqual(resumen["auditadas"], 0)
        self.assertEqual(len(leer_salida(self.salida)), 50)

    def test_relanzar_un_lote_a_medias_solo_audita_lo_que_falta(self):
        mitad = escribir_csv([fila(n) for n in range(1, 26)])
        completo = escribir_csv([fila(n) for n in range(1, 51)])
        auditar(mitad, self.salida, self.rubrica, FakeJev(), limitador=sin_esperas())

        segundo = FakeJev()
        resumen = auditar(
            completo, self.salida, self.rubrica, segundo,
            limitador=sin_esperas(), registrar=lambda _: None,
        )

        self.assertEqual(resumen["saltadas"], 25)
        self.assertEqual(resumen["auditadas"], 25)
        self.assertEqual(len(segundo.llamadas), 25)

        salida = leer_salida(self.salida)
        self.assertEqual(len(salida), 50)
        self.assertEqual(len({f["id"] for f in salida}), 50, "no hay ids repetidos")

    def test_ids_ya_auditados(self):
        self.assertEqual(ids_ya_auditados(self.salida), set())
        entrada = escribir_csv([fila(1), fila(2)])
        auditar(entrada, self.salida, self.rubrica, FakeJev(), limitador=sin_esperas())
        self.assertEqual(ids_ya_auditados(self.salida), {"INT-001", "INT-002"})


class TestLimitador(unittest.TestCase):
    def test_reparte_las_peticiones_en_el_tiempo(self):
        reloj = [0.0]
        dormido: list[float] = []
        limitador = Limitador(
            600, dormir=lambda s: dormido.append(s), reloj=lambda: reloj[0]
        )

        for _ in range(3):
            limitador.esperar()

        # 600 por minuto es una cada 0,1 s: la primera sale ya, las otras esperan.
        self.assertAlmostEqual(limitador.intervalo, 0.1)
        self.assertEqual([round(e, 3) for e in dormido], [0.1, 0.2])

    def test_no_admite_pasarse_del_limite_publicado(self):
        with self.assertRaises(ValueError) as ctx:
            Limitador(5000)
        self.assertIn("1200", str(ctx.exception))

    def test_el_valor_por_defecto_queda_bajo_el_limite(self):
        self.assertLess(60.0 / Limitador().intervalo, 1200)


class TestCLI(Caso):
    def ejecutar(self, argv: list[str]) -> int:
        from jevqa.__main__ import main

        return main(argv)

    def test_auditar_la_fixture_mini(self):
        codigo = self.ejecutar(["auditar", MINI, "--salida", self.salida, "--fake"])
        self.assertEqual(codigo, 0)
        salida = leer_salida(self.salida)
        self.assertEqual([f["id"] for f in salida], ["MINI-1", "MINI-2", "MINI-3"])

    def test_sin_comando_muestra_la_ayuda(self):
        self.assertEqual(self.ejecutar([]), 1)

    def test_entrada_que_no_existe_sale_con_codigo_2(self):
        ruta = os.path.join(tempfile.mkdtemp(), "no_existe.csv")
        self.assertEqual(self.ejecutar(["auditar", ruta, "--fake"]), 2)

    def test_sin_clave_y_sin_fake_sale_con_codigo_2(self):
        anterior = os.environ.pop("TYPESAFE_API_KEY", None)
        try:
            codigo = self.ejecutar(["auditar", MINI, "--salida", self.salida])
        finally:
            if anterior is not None:
                os.environ["TYPESAFE_API_KEY"] = anterior
        self.assertEqual(codigo, 2)

    def test_la_ayuda_menciona_auditar(self):
        from jevqa.__main__ import construir_parser

        self.assertIn("auditar", construir_parser().format_help())


if __name__ == "__main__":
    unittest.main()
