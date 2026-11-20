import io
import json
import unittest
import urllib.error

from jevqa import jev_client
from jevqa.jev_client import FakeJev, JevAuthError, JevClient, JevRetriesExhaustedError


class FakeResponse:
    """Doble de la respuesta de `urllib.request.urlopen`."""

    def __init__(self, data):
        self._data = json.dumps(data).encode("utf-8")

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class ScriptedOpener:
    """Transporte falso: cada llamada consume el siguiente elemento del guion.

    Un `int` produce un `HTTPError` con ese código; cualquier otro valor se
    devuelve como cuerpo JSON de una respuesta exitosa.
    """

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.timeouts = []

    def __call__(self, request, timeout=None):
        self.calls.append(request)
        self.timeouts.append(timeout)
        item = self.script.pop(0)
        if isinstance(item, int):
            raise urllib.error.HTTPError(
                request.full_url, item, f"error {item}", {}, io.BytesIO(b"")
            )
        return FakeResponse(item)


class RecordingSleep:
    """Función de espera falsa: no duerme de verdad, solo registra las llamadas."""

    def __init__(self):
        self.waits = []

    def __call__(self, seconds):
        self.waits.append(seconds)


class NonJsonResponse:
    """Doble de respuesta HTTP 200 cuyo cuerpo no es JSON válido."""

    def read(self):
        return b"esto no es json"

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class NonJsonOpener:
    def __call__(self, request, timeout=None):
        self.timeout = timeout
        return NonJsonResponse()


class NetworkErrorOpener:
    """Transporte falso: cada llamada consume el siguiente elemento del guion.

    Un `Exception` se lanza como fallo de red; cualquier otro valor se
    devuelve como cuerpo JSON de una respuesta exitosa.
    """

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def __call__(self, request, timeout=None):
        self.calls.append(request)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return FakeResponse(item)


SUCCESS_BODY = {"model": "jev-1.13.0", "answers": {}, "usage": {"input_tokens": 1, "output_tokens": 1}}
REQUEST = {"state": "hola", "model": "jev-latest", "questions": {}}


class JevClientRetryTests(unittest.TestCase):
    def test_respuesta_exitosa_sin_reintentos(self):
        opener = ScriptedOpener([SUCCESS_BODY])
        sleep = RecordingSleep()
        client = JevClient(api_key="k", opener=opener, sleep=sleep)

        result = client.evaluate(REQUEST)

        self.assertEqual(result, SUCCESS_BODY)
        self.assertEqual(len(opener.calls), 1)
        self.assertEqual(sleep.waits, [])

    def test_url_metodo_headers_y_cuerpo_de_la_peticion_enviada(self):
        opener = ScriptedOpener([SUCCESS_BODY])
        client = JevClient(api_key="mi-clave-secreta", opener=opener, sleep=RecordingSleep())

        client.evaluate(REQUEST)

        sent = opener.calls[0]
        self.assertEqual(sent.full_url, "https://api.typesafe.ai/v1/systemone")
        self.assertEqual(sent.get_method(), "POST")
        self.assertEqual(sent.get_header("Authorization"), "Bearer mi-clave-secreta")
        self.assertEqual(json.loads(sent.data), REQUEST)

    def test_usa_timeout_por_defecto_de_60_segundos(self):
        opener = ScriptedOpener([SUCCESS_BODY])
        client = JevClient(api_key="k", opener=opener, sleep=RecordingSleep())

        client.evaluate(REQUEST)

        self.assertEqual(opener.timeouts, [60])

    def test_timeout_configurable_se_pasa_al_opener(self):
        opener = ScriptedOpener([SUCCESS_BODY])
        client = JevClient(api_key="k", opener=opener, sleep=RecordingSleep(), timeout=5)

        client.evaluate(REQUEST)

        self.assertEqual(opener.timeouts, [5])

    def test_200_con_cuerpo_no_json_lanza_error_tipado(self):
        client = JevClient(api_key="k", opener=NonJsonOpener(), sleep=RecordingSleep())

        with self.assertRaises(jev_client.JevError):
            client.evaluate(REQUEST)

    def test_error_de_red_reintenta_y_termina_en_error_tipado_si_se_agotan(self):
        opener = NetworkErrorOpener([urllib.error.URLError("boom")] * 4)
        sleep = RecordingSleep()
        client = JevClient(api_key="k", opener=opener, sleep=sleep, max_retries=3)

        with self.assertRaises(JevRetriesExhaustedError):
            client.evaluate(REQUEST)

        self.assertEqual(len(opener.calls), 4)
        self.assertEqual(len(sleep.waits), 3)

    def test_error_de_red_reintenta_y_termina_con_exito(self):
        opener = NetworkErrorOpener([TimeoutError("timed out"), SUCCESS_BODY])
        sleep = RecordingSleep()
        client = JevClient(api_key="k", opener=opener, sleep=sleep)

        result = client.evaluate(REQUEST)

        self.assertEqual(result, SUCCESS_BODY)
        self.assertEqual(len(sleep.waits), 1)

    def test_401_nunca_se_reintenta_aunque_sea_retryable_status(self):
        opener = ScriptedOpener([401])
        sleep = RecordingSleep()
        client = JevClient(api_key="k", opener=opener, sleep=sleep)

        with self.assertRaises(JevAuthError):
            client.evaluate(REQUEST)

        self.assertEqual(sleep.waits, [])

    def test_otro_4xx_no_retryable_no_se_reintenta(self):
        opener = ScriptedOpener([404])
        sleep = RecordingSleep()
        client = JevClient(api_key="k", opener=opener, sleep=sleep)

        with self.assertRaises(jev_client.JevError):
            client.evaluate(REQUEST)

        self.assertEqual(len(opener.calls), 1)
        self.assertEqual(sleep.waits, [])

    def test_backoff_es_exponencial(self):
        opener = ScriptedOpener([500, 500, 500, SUCCESS_BODY])
        sleep = RecordingSleep()
        client = JevClient(api_key="k", opener=opener, sleep=sleep, backoff_seconds=1.0)

        client.evaluate(REQUEST)

        self.assertEqual(sleep.waits, [1.0, 2.0, 4.0])

    def test_honra_retry_after_numerico_del_429(self):
        calls = []

        def opener(request, timeout=None):
            calls.append(request)
            if len(calls) == 1:
                raise urllib.error.HTTPError(
                    request.full_url, 429, "rate limited", {"Retry-After": "7"}, io.BytesIO(b"")
                )
            return FakeResponse(SUCCESS_BODY)

        sleep = RecordingSleep()
        client = JevClient(api_key="k", opener=opener, sleep=sleep)
        client.evaluate(REQUEST)

        self.assertEqual(sleep.waits, [7.0])

    def test_401_lanza_error_claro_sin_reintentar(self):
        opener = ScriptedOpener([401, 401, 401])
        sleep = RecordingSleep()
        client = JevClient(api_key="k", opener=opener, sleep=sleep)

        with self.assertRaises(JevAuthError):
            client.evaluate(REQUEST)

        self.assertEqual(len(opener.calls), 1)
        self.assertEqual(sleep.waits, [])

    def test_sin_api_key_lanza_jevautherror_sin_llamar_al_opener(self):
        opener = ScriptedOpener([SUCCESS_BODY])
        client = JevClient(api_key="", opener=opener, sleep=RecordingSleep())

        with self.assertRaises(JevAuthError):
            client.evaluate(REQUEST)

        self.assertEqual(len(opener.calls), 0)

    def test_429_reintenta_y_espera_antes_de_tener_exito(self):
        opener = ScriptedOpener([429, SUCCESS_BODY])
        sleep = RecordingSleep()
        client = JevClient(api_key="k", opener=opener, sleep=sleep)

        result = client.evaluate(REQUEST)

        self.assertEqual(result, SUCCESS_BODY)
        self.assertEqual(len(opener.calls), 2)
        self.assertEqual(len(sleep.waits), 1)

    def test_500_reintenta_y_espera_antes_de_tener_exito(self):
        opener = ScriptedOpener([500, 500, SUCCESS_BODY])
        sleep = RecordingSleep()
        client = JevClient(api_key="k", opener=opener, sleep=sleep)

        result = client.evaluate(REQUEST)

        self.assertEqual(result, SUCCESS_BODY)
        self.assertEqual(len(opener.calls), 3)
        self.assertEqual(len(sleep.waits), 2)

    def test_agota_reintentos_y_lanza_error_tipado(self):
        opener = ScriptedOpener([429, 429, 429, 429])
        sleep = RecordingSleep()
        client = JevClient(api_key="k", opener=opener, sleep=sleep, max_retries=3)

        with self.assertRaises(JevRetriesExhaustedError):
            client.evaluate(REQUEST)

        self.assertEqual(len(opener.calls), 4)
        self.assertEqual(len(sleep.waits), 3)


class FakeJevTests(unittest.TestCase):
    def test_devuelve_la_respuesta_configurada_para_el_state(self):
        fake = FakeJev(responses={"hola": SUCCESS_BODY})

        result = fake.evaluate({"state": "hola", "model": "jev-latest", "questions": {}})

        self.assertEqual(result, SUCCESS_BODY)
        self.assertEqual(len(fake.calls), 1)

    def test_usa_respuesta_por_defecto_si_el_state_no_esta_registrado(self):
        fake = FakeJev(default_response=SUCCESS_BODY)

        result = fake.evaluate({"state": "cualquier cosa", "model": "jev-latest", "questions": {}})

        self.assertEqual(result, SUCCESS_BODY)

    def test_lanza_error_si_no_hay_respuesta_configurada_ni_por_defecto(self):
        fake = FakeJev()

        with self.assertRaises(jev_client.JevError):
            fake.evaluate({"state": "sin configurar", "model": "jev-latest", "questions": {}})


if __name__ == "__main__":
    unittest.main()
