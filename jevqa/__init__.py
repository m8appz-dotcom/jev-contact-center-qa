"""Auditoría de calidad de contact centers con Jev.

El paquete se ordena por capas: `rubric` no sabe nada de la red y `jev_client`
no sabe nada de la rúbrica. El flujo de una interacción es siempre el mismo:

    rubrica = load_rubric("rubrics/soporte_es.json")
    peticion = build_request(rubrica, texto_anonimizado)
    resultado = parse_response(rubrica, cliente.evaluar(peticion))
"""

from jevqa.jev_client import (
    ErrorAutenticacion,
    ErrorConexion,
    ErrorJev,
    ErrorLimite,
    ErrorServidor,
    ErrorSolicitud,
    FakeJev,
    JevClient,
    ReintentosAgotados,
    coste_usd,
)
from jevqa.rubric import (
    ErrorRubrica,
    RespuestaIncompleta,
    RespuestaInvalida,
    RubricaInvalida,
    build_request,
    load_rubric,
    parse_response,
)

__all__ = [
    "ErrorAutenticacion",
    "ErrorConexion",
    "ErrorJev",
    "ErrorLimite",
    "ErrorRubrica",
    "ErrorServidor",
    "ErrorSolicitud",
    "FakeJev",
    "JevClient",
    "ReintentosAgotados",
    "RespuestaIncompleta",
    "RespuestaInvalida",
    "RubricaInvalida",
    "build_request",
    "coste_usd",
    "load_rubric",
    "parse_response",
]

__version__ = "0.1.0"
