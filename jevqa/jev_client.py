"""Cliente HTTP de Jev y un doble inyectable para los tests.

Solo biblioteca estándar: `urllib` para la llamada, `json` para el cuerpo. El
cliente real reintenta los estados que la documentación marca como temporales
(429 y 5xx, incluido el 529 de sobrecarga) y falla de inmediato en los que no
tiene sentido repetir, como el 401.

Referencia: https://docs.typesafe.ai/api  ·  https://docs.typesafe.ai/models
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Callable

URL_BASE = "https://api.typesafe.ai"
RUTA_SYSTEMONE = "/v1/systemone"
VARIABLE_CLAVE = "TYPESAFE_API_KEY"
MODELO_POR_DEFECTO = "jev-latest"

#: Jev cobra 42 USD por cada mil millones de tokens de entrada; la salida no se cobra.
PRECIO_USD_POR_TOKEN_ENTRADA = 42.0 / 1_000_000_000

#: Límites publicados de jev-1.13: 1.200 peticiones por minuto y 32k tokens
#: para el `state` más la pregunta más larga.
LIMITE_PETICIONES_POR_MINUTO = 1200
LIMITE_TOKENS_ESTADO = 32_000


class ErrorJev(Exception):
    """Base de los errores del cliente."""

    def __init__(self, mensaje: str, estado: int | None = None) -> None:
        super().__init__(mensaje)
        self.estado = estado
        #: Segundos que pide la cabecera `retry-after`, si la respuesta la traía.
        self.reintentar_tras: float | None = None


class ErrorAutenticacion(ErrorJev):
    """401: falta la clave o no es válida. Reintentar no arregla nada."""


class ErrorSolicitud(ErrorJev):
    """422 y demás errores 4xx: el cuerpo enviado está mal formado."""


class ErrorLimite(ErrorJev):
    """429: se superó el límite de peticiones o de tokens por segundo."""


class ErrorServidor(ErrorJev):
    """5xx, incluido el 529 de sobrecarga."""


class ErrorConexion(ErrorJev):
    """La petición no llegó a completarse (red, DNS, tiempo de espera)."""


class ReintentosAgotados(ErrorJev):
    """Se acabaron los intentos y el último siguió fallando."""

    def __init__(self, intentos: int, causa: BaseException) -> None:
        super().__init__(
            f"la petición falló tras {intentos} intentos: {causa}",
            getattr(causa, "estado", None),
        )
        self.intentos = intentos
        self.causa = causa


def coste_usd(tokens_entrada: int) -> float:
    """Coste en dólares de una cantidad de tokens de entrada."""
    return tokens_entrada * PRECIO_USD_POR_TOKEN_ENTRADA


class JevClient:
    """Cliente síncrono de `POST /v1/systemone`.

    `abridor` y `dormir` se inyectan en los tests para no tocar la red ni
    esperar de verdad; por defecto son `urllib.request.urlopen` y `time.sleep`.
    """

    def __init__(
        self,
        clave: str | None = None,
        *,
        url_base: str = URL_BASE,
        intentos: int = 4,
        espera_base: float = 0.5,
        espera_maxima: float = 30.0,
        tiempo_limite: float = 60.0,
        abridor: Callable[..., Any] | None = None,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self.clave = clave if clave is not None else os.environ.get(VARIABLE_CLAVE, "")
        self.url = url_base.rstrip("/") + RUTA_SYSTEMONE
        self.intentos = max(1, intentos)
        self.espera_base = espera_base
        self.espera_maxima = espera_maxima
        self.tiempo_limite = tiempo_limite
        self._abridor = abridor or urllib.request.urlopen
        self._dormir = dormir
        #: Esperas aplicadas, en segundos. Útil para comprobar el backoff.
        self.esperas: list[float] = []

    def evaluar(self, peticion: dict) -> dict:
        """Envía una petición y devuelve la respuesta ya decodificada."""
        if not self.clave:
            raise ErrorAutenticacion(
                f"falta la clave de Jev: define la variable de entorno {VARIABLE_CLAVE}",
                401,
            )

        ultimo: ErrorJev | None = None
        for intento in range(1, self.intentos + 1):
            try:
                return self._enviar(peticion)
            except (ErrorLimite, ErrorServidor, ErrorConexion) as exc:
                ultimo = exc
                if intento == self.intentos:
                    break
                self._esperar(intento, getattr(exc, "reintentar_tras", None))
        assert ultimo is not None
        raise ReintentosAgotados(self.intentos, ultimo)

    def _esperar(self, intento: int, reintentar_tras: float | None) -> None:
        if reintentar_tras is not None:
            espera = min(reintentar_tras, self.espera_maxima)
        else:
            espera = min(self.espera_base * (2 ** (intento - 1)), self.espera_maxima)
        self.esperas.append(espera)
        self._dormir(espera)

    def _enviar(self, peticion: dict) -> dict:
        cuerpo = json.dumps(peticion, ensure_ascii=False).encode("utf-8")
        solicitud = urllib.request.Request(
            self.url,
            data=cuerpo,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.clave}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with self._abridor(solicitud, timeout=self.tiempo_limite) as respuesta:
                crudo = respuesta.read()
        except urllib.error.HTTPError as exc:
            raise self._error_http(exc) from exc
        except urllib.error.URLError as exc:
            raise ErrorConexion(f"no se pudo contactar con Jev: {exc.reason}") from exc
        except TimeoutError as exc:
            raise ErrorConexion("se agotó el tiempo de espera de Jev") from exc

        try:
            return json.loads(crudo)
        except json.JSONDecodeError as exc:
            raise ErrorServidor(f"Jev devolvió algo que no es JSON: {exc}") from exc

    def _error_http(self, exc: urllib.error.HTTPError) -> ErrorJev:
        estado = exc.code
        detalle = _detalle(exc)
        if estado == 401:
            return ErrorAutenticacion(
                f"401: la clave de {VARIABLE_CLAVE} no es válida. {detalle}".strip(),
                estado,
            )
        if estado == 429:
            error = ErrorLimite(f"429: límite de peticiones superado. {detalle}".strip(), estado)
            error.reintentar_tras = _reintentar_tras(exc)
            return error
        if estado >= 500:
            error = ErrorServidor(f"{estado}: Jev no pudo responder. {detalle}".strip(), estado)
            error.reintentar_tras = _reintentar_tras(exc)
            return error
        return ErrorSolicitud(f"{estado}: la petición no es válida. {detalle}".strip(), estado)


def _detalle(exc: urllib.error.HTTPError) -> str:
    try:
        crudo = exc.read()
    except Exception:  # pragma: no cover - el cuerpo es opcional
        return ""
    if not crudo:
        return ""
    texto = crudo.decode("utf-8", "replace").strip()
    return texto[:500]


def _reintentar_tras(exc: urllib.error.HTTPError) -> float | None:
    cabeceras = getattr(exc, "headers", None)
    if cabeceras is None:
        return None
    valor = cabeceras.get("retry-after")
    if valor is None:
        return None
    try:
        return max(0.0, float(valor))
    except (TypeError, ValueError):
        return None


class FakeJev:
    """Doble de Jev sin red, determinista y con la misma interfaz `evaluar`.

    Por defecto inventa una respuesta a partir de la propia petición: el mismo
    texto y la misma pregunta dan siempre el mismo número, así que los tests y
    el modo `--fake` son reproducibles. Con `respuestas` se le puede dar un
    guion fijo, y con `errores` una lista de fallos a lanzar en orden.
    """

    def __init__(
        self,
        respuestas: list[dict] | Callable[[dict], dict] | None = None,
        *,
        errores: list[BaseException | None] | None = None,
        semilla: str = "jev-qa",
        modelo: str = "jev-1.13.0-fake",
    ) -> None:
        self._respuestas = respuestas
        self._errores = list(errores or [])
        self.semilla = semilla
        self.modelo = modelo
        #: Peticiones recibidas, en orden. Sirve para comprobar qué se envió.
        self.llamadas: list[dict] = []

    def evaluar(self, peticion: dict) -> dict:
        self.llamadas.append(peticion)

        if self._errores:
            error = self._errores.pop(0)
            if error is not None:
                raise error

        if callable(self._respuestas):
            return self._respuestas(peticion)
        if isinstance(self._respuestas, list) and self._respuestas:
            return self._respuestas.pop(0)

        return self._inventar(peticion)

    def _inventar(self, peticion: dict) -> dict:
        estado = json.dumps(peticion.get("state", ""), ensure_ascii=False, sort_keys=True)
        preguntas = peticion.get("questions") or {}
        respuestas: dict[str, dict] = {}

        for qid, pregunta in preguntas.items():
            tipo = pregunta.get("type")
            if tipo == "noul":
                respuestas[qid] = {
                    "type": "noul",
                    "noul": round(self._fraccion(estado, qid), 4),
                }
            elif tipo == "choice":
                opciones = list((pregunta.get("criteria") or {}))
                respuestas[qid] = _respuesta_categorica("choice", opciones, self._pesos(estado, qid, opciones))
            elif tipo == "score":
                niveles = list(pregunta.get("criteria") or [])
                claves = [str(i) for i in range(len(niveles))]
                respuesta = _respuesta_categorica("score", claves, self._pesos(estado, qid, claves))
                respuesta["legend"] = {str(i): texto for i, texto in enumerate(niveles)}
                respuestas[qid] = respuesta
            else:
                raise ErrorSolicitud(f"422: tipo de pregunta desconocido en {qid}: {tipo}", 422)

        entrada = max(1, (len(estado) + len(json.dumps(preguntas, ensure_ascii=False))) // 4)
        return {
            "model": self.modelo,
            "answers": respuestas,
            "usage": {"input_tokens": entrada, "output_tokens": 10 * len(respuestas)},
        }

    def _fraccion(self, estado: str, *partes: str) -> float:
        semilla = chr(0).join((self.semilla, estado, *partes)).encode("utf-8")
        digesto = hashlib.sha256(semilla).digest()[:8]
        return int.from_bytes(digesto, "big") / 2**64

    def _pesos(self, estado: str, qid: str, claves: list[str]) -> list[float]:
        return [self._fraccion(estado, qid, clave) for clave in claves]


def _respuesta_categorica(tipo: str, claves: list[str], pesos: list[float]) -> dict:
    if not claves:
        raise ErrorSolicitud(f"422: una pregunta {tipo} necesita al menos una opción", 422)
    total = sum(pesos) or 1.0
    probabilidades = {clave: round(peso / total, 4) for clave, peso in zip(claves, pesos)}
    # El redondeo desvía la suma; el resto se carga sobre la opción más probable.
    ganadora = max(probabilidades, key=lambda clave: probabilidades[clave])
    probabilidades[ganadora] = round(
        probabilidades[ganadora] + 1.0 - sum(probabilidades.values()), 4
    )

    maxima = probabilidades[ganadora]
    cantidad = len(claves)
    confianza = 1.0 if cantidad == 1 else (cantidad * maxima - 1.0) / (cantidad - 1)
    respuesta: dict[str, Any] = {
        "type": tipo,
        "probabilities": probabilidades,
        "confidence": round(max(0.0, min(1.0, confianza)), 4),
    }
    if tipo == "choice":
        respuesta["choice"] = ganadora
    else:
        respuesta["score"] = round(
            sum(int(clave) * prob for clave, prob in probabilidades.items()), 4
        )
    return respuesta
