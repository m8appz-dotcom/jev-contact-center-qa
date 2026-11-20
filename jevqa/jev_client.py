"""Cliente HTTP para el endpoint `systemone` de Jev (TypeSafe).

Usa únicamente `urllib` de la biblioteca estándar. La API key se lee de la
variable de entorno `TYPESAFE_API_KEY` salvo que se pase explícitamente.
Reintenta con espera en 429 (rate limit) y en errores 5xx/529 (sobrecarga);
no reintenta en 401 (credenciales inválidas).

Para tests, tanto el transporte HTTP (`opener`) como la función de espera
(`sleep`) son inyectables, de modo que nada de esto toca la red de verdad.
`FakeJev` es un doble de todo el cliente: sirve respuestas predefinidas sin
pasar por HTTP en absoluto.
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from time import sleep as _real_sleep

API_URL = "https://api.typesafe.ai/v1/systemone"
API_KEY_ENV = "TYPESAFE_API_KEY"
DEFAULT_TIMEOUT_SECONDS = 60


def _is_retryable_status(code: int) -> bool:
    return code == 429 or (500 <= code < 600)


class JevError(Exception):
    """Error genérico al llamar a la API de Jev."""


class JevAuthError(JevError):
    """401: API key ausente o inválida. Nunca se reintenta."""


class JevRetriesExhaustedError(JevError):
    """Se agotaron los reintentos sin obtener una respuesta válida."""


class JevClient:
    """Cliente real del endpoint `systemone`, con reintento en 429/5xx."""

    def __init__(
        self,
        api_key: str | None = None,
        opener=None,
        sleep=None,
        max_retries: int = 5,
        backoff_seconds: float = 1.0,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        self.api_key = api_key if api_key is not None else os.environ.get(API_KEY_ENV)
        self.opener = opener if opener is not None else urllib.request.urlopen
        self.sleep = sleep if sleep is not None else _real_sleep
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.timeout = timeout

    def evaluate(self, request: dict) -> dict:
        """Envía `request` (de `rubric.build_request`) y devuelve el JSON de respuesta."""
        if not self.api_key:
            raise JevAuthError(f"no hay API key: define {API_KEY_ENV} o pásala al cliente")

        body = json.dumps(request).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        attempt = 0
        while True:
            http_request = urllib.request.Request(
                API_URL, data=body, headers=headers, method="POST"
            )
            try:
                with self.opener(http_request, timeout=self.timeout) as response:
                    raw_body = response.read()
                try:
                    return json.loads(raw_body)
                except ValueError as exc:
                    raise JevError(
                        "respuesta de Jev con código 200 pero cuerpo no es JSON válido"
                    ) from exc
            except urllib.error.HTTPError as exc:
                if exc.code == 401:
                    raise JevAuthError("401 Unauthorized: API key inválida") from exc
                if _is_retryable_status(exc.code):
                    if attempt < self.max_retries:
                        attempt += 1
                        self.sleep(self._wait_seconds(attempt, exc))
                        continue
                    raise JevRetriesExhaustedError(
                        f"se agotaron los {self.max_retries} reintentos "
                        f"(último error: {exc.code})"
                    ) from exc
                raise JevError(f"error de Jev: {exc.code} {exc.reason}") from exc
            except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
                if attempt < self.max_retries:
                    attempt += 1
                    self.sleep(self._wait_seconds(attempt, None))
                    continue
                raise JevRetriesExhaustedError(
                    f"se agotaron los {self.max_retries} reintentos "
                    f"(último error de red: {exc})"
                ) from exc

    def _wait_seconds(self, attempt: int, exc: urllib.error.HTTPError | None) -> float:
        """Backoff exponencial: `backoff_seconds * 2 ** (attempt - 1)`.

        Si `exc` trae una cabecera `Retry-After` numérica, se respeta en su lugar.
        """
        if exc is not None:
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            if retry_after is not None:
                try:
                    return float(retry_after)
                except ValueError:
                    pass
        return self.backoff_seconds * (2 ** (attempt - 1))


class FakeJev:
    """Doble de pruebas de un cliente Jev: sirve respuestas predefinidas sin red.

    `responses` mapea el `state` de la petición a la respuesta cruda que se
    debe devolver. `default_response`, si se da, se usa para cualquier
    `state` que no esté en `responses`. Cada petición recibida se registra
    en `self.calls` para poder inspeccionarla en los tests.
    """

    def __init__(self, responses: dict | None = None, default_response: dict | None = None):
        self.responses = responses or {}
        self.default_response = default_response
        self.calls: list = []

    def evaluate(self, request: dict) -> dict:
        self.calls.append(request)
        state = request.get("state")
        if state in self.responses:
            return self.responses[state]
        if self.default_response is not None:
            return self.default_response
        raise JevError(f"FakeJev no tiene respuesta configurada para state={state!r}")
