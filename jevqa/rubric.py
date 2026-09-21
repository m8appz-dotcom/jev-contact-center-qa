"""Rúbrica de auditoría: carga, petición a Jev y lectura tipada de la respuesta.

Una interacción se evalúa con **una sola** petición a `POST /v1/systemone`: el
texto viaja una vez en `state` y cada juicio es una pregunta tipada. Para una
rúbrica de N ítems se envían N+2 preguntas: un Noul por ítem, más el Score
`riesgo` y el Choice `motivo`.

Referencia de la API: https://docs.typesafe.ai/api
"""

from __future__ import annotations

import json
from typing import Any

MODELO_POR_DEFECTO = "jev-latest"

#: Ids reservados: son las dos preguntas que se añaden a los ítems de la rúbrica.
ID_RIESGO = "riesgo"
ID_MOTIVO = "motivo"
IDS_RESERVADOS = (ID_RIESGO, ID_MOTIVO)

#: La API acepta entre 2 y 10 niveles en un Score y hasta 255 opciones en un Choice.
MIN_NIVELES, MAX_NIVELES = 2, 10
MAX_OPCIONES = 255

#: Toda rúbrica debe ofrecer una salida para lo que no encaja en ninguna categoría.
OPCION_OTRO = "otro"


class ErrorRubrica(Exception):
    """Base de los errores de este módulo."""


class RubricaInvalida(ErrorRubrica):
    """El archivo de rúbrica no cumple el formato esperado."""


class RespuestaIncompleta(ErrorRubrica):
    """Jev no devolvió una respuesta para alguna de las preguntas enviadas."""

    def __init__(self, faltantes: list[str]) -> None:
        self.faltantes = list(faltantes)
        super().__init__("faltan respuestas para: " + ", ".join(self.faltantes))


class RespuestaInvalida(ErrorRubrica):
    """La respuesta llegó, pero no tiene la forma que documenta la API."""


# ---------------------------------------------------------------------------
# Carga de la rúbrica
# ---------------------------------------------------------------------------

def load_rubric(path: str) -> dict:
    """Lee y valida un archivo JSON de rúbrica.

    Devuelve un diccionario normalizado con `items`, `riesgo` y `motivo`. Lanza
    `RubricaInvalida` con un mensaje concreto si algo no cuadra.
    """
    try:
        with open(path, encoding="utf-8") as archivo:
            crudo = json.load(archivo)
    except FileNotFoundError as exc:
        raise RubricaInvalida(f"no existe la rúbrica {path}") from exc
    except json.JSONDecodeError as exc:
        raise RubricaInvalida(f"{path} no es JSON válido: {exc}") from exc

    if not isinstance(crudo, dict):
        raise RubricaInvalida(f"{path}: la rúbrica debe ser un objeto JSON")

    return {
        "id": _texto(crudo.get("id"), "id", contexto=path),
        "nombre": crudo.get("nombre") or crudo.get("id"),
        "version": str(crudo.get("version", "0")),
        "idioma": crudo.get("idioma", "es"),
        "items": _validar_items(crudo.get("items"), path),
        "riesgo": _validar_riesgo(crudo.get("riesgo"), path),
        "motivo": _validar_motivo(crudo.get("motivo"), path),
        "ruta": path,
    }


def _texto(valor: Any, campo: str, *, contexto: str) -> str:
    if not isinstance(valor, str) or not valor.strip():
        raise RubricaInvalida(f"{contexto}: {campo} debe ser un texto no vacío")
    return valor.strip()


def _criterios(valor: Any, contexto: str) -> dict | None:
    if valor is None:
        return None
    if not isinstance(valor, dict):
        raise RubricaInvalida(f"{contexto}: criterios debe ser un objeto")
    sobran = set(valor) - {"true", "false"}
    if sobran:
        raise RubricaInvalida(
            f"{contexto}: criterios solo admite true y false; sobra: "
            + ", ".join(sorted(sobran))
        )
    return {clave: valor[clave] for clave in ("true", "false") if clave in valor}


def _validar_items(valor: Any, contexto: str) -> list[dict]:
    if not isinstance(valor, list) or not valor:
        raise RubricaInvalida(
            f"{contexto}: items debe ser una lista con al menos un ítem"
        )

    items: list[dict] = []
    vistos: set[str] = set()
    for posicion, crudo in enumerate(valor):
        donde = f"{contexto}: items[{posicion}]"
        if not isinstance(crudo, dict):
            raise RubricaInvalida(f"{donde} debe ser un objeto")
        item_id = _texto(crudo.get("id"), "id", contexto=donde)
        if item_id in IDS_RESERVADOS:
            raise RubricaInvalida(
                f"{donde}: {item_id} es un id reservado para la pregunta de "
                f"{item_id}; usa otro id"
            )
        if item_id in vistos:
            raise RubricaInvalida(f"{donde}: el id {item_id} está repetido")
        vistos.add(item_id)

        peso = crudo.get("peso", 1)
        if isinstance(peso, bool) or not isinstance(peso, (int, float)) or peso <= 0:
            raise RubricaInvalida(f"{donde}: peso debe ser un número mayor que cero")
        critico = crudo.get("critico", False)
        if not isinstance(critico, bool):
            raise RubricaInvalida(f"{donde}: critico debe ser true o false")

        items.append(
            {
                "id": item_id,
                "pregunta": _texto(crudo.get("pregunta"), "pregunta", contexto=donde),
                "criterios": _criterios(crudo.get("criterios"), donde),
                "peso": peso,
                "critico": critico,
            }
        )
    return items


def _validar_riesgo(valor: Any, contexto: str) -> dict:
    donde = f"{contexto}: riesgo"
    if not isinstance(valor, dict):
        raise RubricaInvalida(f"{donde} debe ser un objeto con pregunta y niveles")
    niveles = valor.get("niveles")
    if not isinstance(niveles, list) or not all(
        isinstance(nivel, str) and nivel.strip() for nivel in niveles
    ):
        raise RubricaInvalida(f"{donde}: niveles debe ser una lista de textos")
    if not MIN_NIVELES <= len(niveles) <= MAX_NIVELES:
        raise RubricaInvalida(
            f"{donde}: la API admite entre {MIN_NIVELES} y {MAX_NIVELES} niveles, "
            f"hay {len(niveles)}"
        )
    return {
        "pregunta": _texto(valor.get("pregunta"), "pregunta", contexto=donde),
        "niveles": list(niveles),
    }


def _validar_motivo(valor: Any, contexto: str) -> dict:
    donde = f"{contexto}: motivo"
    if not isinstance(valor, dict):
        raise RubricaInvalida(f"{donde} debe ser un objeto con pregunta y opciones")
    opciones = valor.get("opciones")
    if not isinstance(opciones, dict) or len(opciones) < 2:
        raise RubricaInvalida(
            f"{donde}: opciones debe ser un objeto con al menos dos opciones"
        )
    if len(opciones) > MAX_OPCIONES:
        raise RubricaInvalida(f"{donde}: la API admite hasta {MAX_OPCIONES} opciones")
    if OPCION_OTRO not in opciones:
        raise RubricaInvalida(
            f"{donde}: falta la opción {OPCION_OTRO}; sin ella el modelo tiene que "
            "forzar una categoría cuando ninguna encaja"
        )
    return {
        "pregunta": _texto(valor.get("pregunta"), "pregunta", contexto=donde),
        "opciones": dict(opciones),
    }


# ---------------------------------------------------------------------------
# Construcción de la petición
# ---------------------------------------------------------------------------

def build_request(rubric: dict, text: str, modelo: str = MODELO_POR_DEFECTO) -> dict:
    """Arma el cuerpo de la petición: el texto una vez en `state`, N+2 preguntas.

    El texto de la interacción no se repite dentro de las preguntas. Jev lee el
    `state` una sola vez y evalúa todas las preguntas contra él en paralelo, así
    que repetirlo solo costaría tokens y precisión.
    """
    if not isinstance(text, str) or not text.strip():
        raise RubricaInvalida("el texto de la interacción está vacío")

    preguntas: dict[str, dict] = {}
    for item in rubric["items"]:
        pregunta = {"type": "noul", "instructions": item["pregunta"]}
        if item["criterios"]:
            pregunta["criteria"] = item["criterios"]
        preguntas[item["id"]] = pregunta

    preguntas[ID_RIESGO] = {
        "type": "score",
        "instructions": rubric["riesgo"]["pregunta"],
        "criteria": list(rubric["riesgo"]["niveles"]),
    }
    preguntas[ID_MOTIVO] = {
        "type": "choice",
        "instructions": rubric["motivo"]["pregunta"],
        "criteria": dict(rubric["motivo"]["opciones"]),
    }

    return {"state": text, "model": modelo, "questions": preguntas}


def ids_esperados(rubric: dict) -> list[str]:
    """Los N+2 ids de pregunta que se envían y que deben volver en la respuesta."""
    return [item["id"] for item in rubric["items"]] + [ID_RIESGO, ID_MOTIVO]


# ---------------------------------------------------------------------------
# Lectura de la respuesta
# ---------------------------------------------------------------------------

def parse_answer(tipo: str, respuesta: Any, *, niveles: list[str] | None = None) -> dict:
    """Normaliza una respuesta de la API a un registro con la misma forma.

    Todos los tipos devuelven `valor`, `probabilidad`, `confianza` y
    `distribucion`. Un Score añade `nivel`, `etiqueta` y `leyenda`.

    La API no devuelve `confidence` para un Noul: el propio valor ya describe
    toda la distribución. Aquí se deriva con la misma fórmula que la
    documentación usa para una distribución de dos resultados,
    2·max(p, 1−p) − 1, para poder aplicar un único umbral de confianza a todas
    las preguntas.
    """
    if not isinstance(respuesta, dict):
        raise RespuestaInvalida(f"la respuesta de tipo {tipo} no es un objeto")
    devuelto = respuesta.get("type")
    if devuelto is not None and devuelto != tipo:
        raise RespuestaInvalida(
            f"se esperaba una respuesta {tipo} y llegó {devuelto}"
        )

    if tipo == "noul":
        probabilidad = _numero(respuesta.get("noul"), "noul")
        return {
            "tipo": "noul",
            "valor": probabilidad,
            "probabilidad": probabilidad,
            "confianza": abs(2.0 * probabilidad - 1.0),
            "distribucion": {"si": probabilidad, "no": 1.0 - probabilidad},
        }

    if tipo == "choice":
        opcion = respuesta.get("choice")
        if not isinstance(opcion, str):
            raise RespuestaInvalida("falta choice en la respuesta")
        distribucion = _distribucion(respuesta.get("probabilities"))
        return {
            "tipo": "choice",
            "valor": opcion,
            "probabilidad": distribucion.get(opcion, 0.0),
            "confianza": _numero(respuesta.get("confidence"), "confidence"),
            "distribucion": distribucion,
        }

    if tipo == "score":
        valor = _numero(respuesta.get("score"), "score")
        distribucion = _distribucion(respuesta.get("probabilities"))
        leyenda = respuesta.get("legend")
        if not isinstance(leyenda, dict):
            if niveles is None:
                raise RespuestaInvalida("falta legend en la respuesta de score")
            leyenda = {str(i): texto for i, texto in enumerate(niveles)}
        nivel = max(distribucion, key=lambda clave: distribucion[clave])
        return {
            "tipo": "score",
            "valor": valor,
            "nivel": int(nivel),
            "etiqueta": leyenda.get(nivel, nivel),
            "probabilidad": distribucion[nivel],
            "confianza": _numero(respuesta.get("confidence"), "confidence"),
            "distribucion": distribucion,
            "leyenda": {str(clave): texto for clave, texto in leyenda.items()},
        }

    raise RespuestaInvalida(f"tipo de pregunta desconocido: {tipo}")


def parse_response(rubric: dict, data: Any) -> dict:
    """Convierte la respuesta de Jev en un resultado tipado para esta rúbrica.

    Lanza `RespuestaIncompleta` si falta la respuesta de alguna pregunta: sin
    todos los ítems no se puede calcular una nota, así que el fallo es duro y no
    se rellena nada por omisión.
    """
    if not isinstance(data, dict):
        raise RespuestaInvalida("la respuesta no es un objeto JSON")
    respuestas_api = data.get("answers")
    if not isinstance(respuestas_api, dict):
        raise RespuestaInvalida("la respuesta no trae el objeto answers")

    faltantes = [qid for qid in ids_esperados(rubric) if qid not in respuestas_api]
    if faltantes:
        raise RespuestaIncompleta(faltantes)

    items: dict[str, dict] = {}
    for item in rubric["items"]:
        registro = parse_answer("noul", respuestas_api[item["id"]])
        registro["peso"] = item["peso"]
        registro["critico"] = item["critico"]
        items[item["id"]] = registro

    riesgo = parse_answer(
        "score", respuestas_api[ID_RIESGO], niveles=rubric["riesgo"]["niveles"]
    )
    motivo = parse_answer("choice", respuestas_api[ID_MOTIVO])

    respuestas = dict(items)
    respuestas[ID_RIESGO] = riesgo
    respuestas[ID_MOTIVO] = motivo

    return {
        "rubrica": rubric["id"],
        "version_rubrica": rubric["version"],
        "modelo": data.get("model"),
        "items": items,
        "riesgo": riesgo,
        "motivo": motivo,
        "respuestas": respuestas,
        "uso": _uso(data.get("usage")),
    }


def _numero(valor: Any, campo: str) -> float:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise RespuestaInvalida(f"{campo} debe ser un número, llegó {valor!r}")
    return float(valor)


def _distribucion(valor: Any) -> dict[str, float]:
    if not isinstance(valor, dict) or not valor:
        raise RespuestaInvalida("falta probabilities en la respuesta")
    return {str(clave): _numero(prob, "probabilities") for clave, prob in valor.items()}


def _uso(valor: Any) -> dict[str, int]:
    if not isinstance(valor, dict):
        return {"tokens_entrada": 0, "tokens_salida": 0}
    return {
        "tokens_entrada": int(valor.get("input_tokens") or 0),
        "tokens_salida": int(valor.get("output_tokens") or 0),
    }
