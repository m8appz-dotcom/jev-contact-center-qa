"""Tests del cliente HTTP de Jev y del doble FakeJev. No se toca la red."""

from __future__ import annotations

import email.message
import io
import json
import unittest
import urllib.error

from jevqa.jev_client import (
    LIMITE_PETICIONES_POR_MINUTO,
    ErrorAutenticacion,
    ErrorConexion,
    ErrorServidor,
    ErrorSolicitud,
    FakeJev,
    JevClient,
    ReintentosAgotados,
    coste_usd,
)

PETICION = {
    "state": "Cliente: me cobraron dos veces.",
    "model": "jev-latest",
    "questions": {"cobro": {"type": "noul", "instructions": "¿Hay un cobro duplicado?"}},
}
RESPUESTA = {
    "model": "jev-1.13.0",
    "answers": {"cobro": {"type": "noul", "noul": 0.93}},
    "usage": {"input_tokens": 120, "output_tokens": 10},
}


class RespuestaFalsa(io.BytesIO):
    """Lo mínimo que `urlopen` devuelve: un archivo que además es contexto."""

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
        return False


def error_http(codigo: int, *, cuerpo: str = "", reintentar_tras: str | None = None):
    cabeceras = email.message.Message()
    if reintentar_tras is not None:
        cabeceras["retry-after"] = reintentar_tras
    return urllib.error.HTTPError(
        "https://api.typesafe.ai/v1/systemone",
        codigo,
        "error",
        cabeceras,
        io.BytesIO(cuerpo.encode("utf-8")),
    )


class Abridor:
    """Sustituto de `urlopen`: devuelve en orden lo que se le haya cargado."""

    def __init__(self, guion: list):
        self.guion = list(guion)
        self.solicitudes: list = []

    def __call__(self, solicitud, timeout=None):
        self.solicitudes.append(solicitud)
        self.ultimo_tiempo_limite = timeout
        siguiente = self.guion.pop(0) if self.guion else RESPUESTA
        if isinstance(siguiente, BaseException):
            raise siguiente
        if isinstance(siguiente, (dict, list)):
            return RespuestaFalsa(json.dumps(siguiente).encode("utf-8"))
        return RespuestaFalsa(str(siguiente).encode("utf-8"))


def cliente(guion: list, **extra) -> tuple[JevClient, Abridor, list[float]]:
    abridor = Abridor(guion)
    dormido: list[float] = []
    parametros = {"espera_base": 0.01, "espera_maxima": 0.05}
    parametros.update(extra)
    jev = JevClient("clave-de-prueba", abridor=abridor, dormir=dormido.append, **parametros)
    return jev, abridor, dormido


class TestPeticion(unittest.TestCase):
    def test_envia_cabeceras_y_cuerpo(self):
        jev, abridor, _ = cliente([RESPUESTA])
        self.assertEqual(jev.evaluar(PETICION), RESPUESTA)

        solicitud = abridor.solicitudes[0]
        self.assertEqual(solicitud.full_url, "https://api.typesafe.ai/v1/systemone")
        self.assertEqual(solicitud.get_method(), "POST")
        self.assertEqual(solicitud.get_header("Authorization"), "Bearer clave-de-prueba")
        self.assertEqual(solicitud.get_header("Content-type"), "application/json")
        self.assertEqual(json.loads(solicitud.data.decode("utf-8")), PETICION)

    def test_sin_clave_no_sale_ninguna_peticion(self):
        abridor = Abridor([RESPUESTA])
        jev = JevClient("", abridor=abridor)
        with self.assertRaises(ErrorAutenticacion) as ctx:
            jev.evaluar(PETICION)
        self.assertIn("TYPESAFE_API_KEY", str(ctx.exception))
        self.assertEqual(abridor.solicitudes, [])

    def test_clave_desde_el_entorno(self):
        import os

        anterior = os.environ.get("TYPESAFE_API_KEY")
        os.environ["TYPESAFE_API_KEY"] = "del-entorno"
        try:
            jev = JevClient(abridor=Abridor([RESPUESTA]))
            self.assertEqual(jev.clave, "del-entorno")
        finally:
            if anterior is None:
                del os.environ["TYPESAFE_API_KEY"]
            else:
                os.environ["TYPESAFE_API_KEY"] = anterior


class TestErroresYReintentos(unittest.TestCase):
    def test_401_falla_de_inmediato(self):
        jev, abridor, dormido = cliente([error_http(401, cuerpo='{"error":"clave inválida"}')])
        with self.assertRaises(ErrorAutenticacion) as ctx:
            jev.evaluar(PETICION)
        self.assertEqual(ctx.exception.estado, 401)
        self.assertIn("clave inválida", str(ctx.exception))
        self.assertEqual(len(abridor.solicitudes), 1)
        self.assertEqual(dormido, [])

    def test_422_falla_de_inmediato(self):
        jev, abridor, _ = cliente([error_http(422, cuerpo="falta 'state'")])
        with self.assertRaises(ErrorSolicitud) as ctx:
            jev.evaluar(PETICION)
        self.assertEqual(ctx.exception.estado, 422)
        self.assertEqual(len(abridor.solicitudes), 1)

    def test_429_reintenta_y_acierta(self):
        jev, abridor, dormido = cliente([error_http(429), RESPUESTA])
        self.assertEqual(jev.evaluar(PETICION), RESPUESTA)
        self.assertEqual(len(abridor.solicitudes), 2)
        self.assertEqual(len(dormido), 1)

    def test_500_reintenta_y_acierta(self):
        jev, abridor, dormido = cliente([error_http(500), error_http(500), RESPUESTA])
        self.assertEqual(jev.evaluar(PETICION), RESPUESTA)
        self.assertEqual(len(abridor.solicitudes), 3)
        self.assertEqual(dormido, [0.01, 0.02])

    def test_529_de_sobrecarga_reintenta(self):
        jev, abridor, _ = cliente([error_http(529), RESPUESTA])
        self.assertEqual(jev.evaluar(PETICION), RESPUESTA)
        self.assertEqual(len(abridor.solicitudes), 2)

    def test_espera_crece_de_forma_exponencial(self):
        jev, _, dormido = cliente(
            [error_http(500)] * 3 + [RESPUESTA], espera_base=1.0, espera_maxima=100.0
        )
        jev.evaluar(PETICION)
        self.assertEqual(dormido, [1.0, 2.0, 4.0])

    def test_respeta_la_cabecera_retry_after(self):
        jev, _, dormido = cliente(
            [error_http(429, reintentar_tras="7"), RESPUESTA], espera_maxima=60.0
        )
        jev.evaluar(PETICION)
        self.assertEqual(dormido, [7.0])

    def test_agotamiento_de_reintentos(self):
        jev, abridor, dormido = cliente([error_http(500)] * 4, intentos=4)
        with self.assertRaises(ReintentosAgotados) as ctx:
            jev.evaluar(PETICION)
        self.assertEqual(ctx.exception.intentos, 4)
        self.assertEqual(ctx.exception.estado, 500)
        self.assertIsInstance(ctx.exception.causa, ErrorServidor)
        self.assertEqual(len(abridor.solicitudes), 4)
        self.assertEqual(len(dormido), 3)

    def test_fallo_de_red_reintenta(self):
        jev, abridor, _ = cliente([urllib.error.URLError("sin DNS"), RESPUESTA])
        self.assertEqual(jev.evaluar(PETICION), RESPUESTA)
        self.assertEqual(len(abridor.solicitudes), 2)

    def test_fallo_de_red_persistente(self):
        jev, _, _ = cliente([urllib.error.URLError("sin DNS")] * 2, intentos=2)
        with self.assertRaises(ReintentosAgotados) as ctx:
            jev.evaluar(PETICION)
        self.assertIsInstance(ctx.exception.causa, ErrorConexion)

    def test_respuesta_que_no_es_json(self):
        jev, _, _ = cliente(["<html>502 Bad Gateway</html>"] * 2, intentos=2)
        with self.assertRaises(ReintentosAgotados) as ctx:
            jev.evaluar(PETICION)
        self.assertIsInstance(ctx.exception.causa, ErrorServidor)


class TestFakeJev(unittest.TestCase):
    def test_inventa_una_respuesta_con_la_forma_de_la_api(self):
        datos = FakeJev().evaluar(PETICION)
        self.assertIn("model", datos)
        self.assertIn("usage", datos)
        respuesta = datos["answers"]["cobro"]
        self.assertEqual(respuesta["type"], "noul")
        self.assertTrue(0.0 <= respuesta["noul"] <= 1.0)

    def test_choice_y_score_suman_uno(self):
        peticion = {
            "state": "texto",
            "model": "jev-latest",
            "questions": {
                "motivo": {
                    "type": "choice",
                    "instructions": "¿Motivo?",
                    "criteria": {"a": "A", "b": "B", "otro": "Otro"},
                },
                "riesgo": {
                    "type": "score",
                    "instructions": "¿Riesgo?",
                    "criteria": ["Ninguno", "Bajo", "Medio", "Alto"],
                },
            },
        }
        respuestas = FakeJev().evaluar(peticion)["answers"]

        motivo = respuestas["motivo"]
        self.assertAlmostEqual(sum(motivo["probabilities"].values()), 1.0)
        self.assertEqual(
            motivo["choice"],
            max(motivo["probabilities"], key=motivo["probabilities"].get),
        )
        riesgo = respuestas["riesgo"]
        self.assertAlmostEqual(sum(riesgo["probabilities"].values()), 1.0)
        self.assertEqual(sorted(riesgo["legend"]), ["0", "1", "2", "3"])
        self.assertTrue(0.0 <= riesgo["score"] <= 3.0)

    def test_textos_distintos_dan_respuestas_distintas(self):
        fake = FakeJev()
        una = fake.evaluar(dict(PETICION, state="primer texto"))
        otra = fake.evaluar(dict(PETICION, state="segundo texto"))
        self.assertNotEqual(una["answers"]["cobro"]["noul"], otra["answers"]["cobro"]["noul"])
        self.assertEqual(len(fake.llamadas), 2)

    def test_guion_de_respuestas(self):
        fake = FakeJev([RESPUESTA])
        self.assertEqual(fake.evaluar(PETICION), RESPUESTA)

    def test_guion_de_errores(self):
        fake = FakeJev(errores=[ErrorServidor("500: caído", 500), None])
        with self.assertRaises(ErrorServidor):
            fake.evaluar(PETICION)
        self.assertIn("answers", fake.evaluar(PETICION))
        self.assertEqual(len(fake.llamadas), 2)

    def test_tipo_de_pregunta_desconocido(self):
        peticion = {"state": "x", "questions": {"q": {"type": "texto_libre"}}}
        with self.assertRaises(ErrorSolicitud):
            FakeJev().evaluar(peticion)


class TestCoste(unittest.TestCase):
    def test_precio_publicado(self):
        # 42 USD por cada mil millones de tokens de entrada.
        self.assertAlmostEqual(coste_usd(1_000_000_000), 42.0)
        self.assertAlmostEqual(coste_usd(1_000_000), 0.042)
        self.assertEqual(coste_usd(0), 0.0)

    def test_limite_de_peticiones_publicado(self):
        self.assertEqual(LIMITE_PETICIONES_POR_MINUTO, 1200)


if __name__ == "__main__":
    unittest.main()
