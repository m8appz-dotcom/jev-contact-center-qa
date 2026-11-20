"""Carga de rúbricas y traducción hacia/desde el formato de la API de Jev.

Una rúbrica describe una única petición al endpoint `systemone` de Jev por
interacción: un ítem "noul" (sí/no) por cada elemento de `items`, más una
pregunta "score" de riesgo (4 niveles) y una pregunta "choice" de motivo
(con opción "otro").
"""

from __future__ import annotations

import json

MODEL = "jev-latest"

# Ids reservados que toda rúbrica añade además de sus ítems.
RIESGO_ID = "riesgo"
MOTIVO_ID = "motivo"


class RubricError(Exception):
    """La rúbrica no tiene el formato esperado."""


class RespuestaIncompletaError(Exception):
    """La respuesta de Jev no contiene una respuesta para una pregunta esperada."""

    def __init__(self, question_id: str):
        self.question_id = question_id
        super().__init__(f"falta la respuesta para la pregunta '{question_id}'")


def load_rubric(path: str) -> dict:
    """Carga y valida una rúbrica JSON desde `path`."""
    with open(path, "r", encoding="utf-8") as f:
        rubric = json.load(f)

    if not isinstance(rubric, dict):
        raise RubricError("la rúbrica debe ser un objeto JSON")

    items = rubric.get("items")
    if not isinstance(items, list) or not items:
        raise RubricError("la rúbrica debe tener al menos un ítem en 'items'")

    seen_ids = set()
    for item in items:
        if not isinstance(item, dict):
            raise RubricError(f"cada ítem debe ser un objeto: {item!r}")
        for field in ("id", "pregunta", "peso", "critico"):
            if field not in item:
                raise RubricError(f"ítem sin campo requerido '{field}': {item}")
        item_id = item["id"]
        if not isinstance(item_id, str) or not item_id:
            raise RubricError(f"el id del ítem debe ser una cadena no vacía: {item!r}")
        if item_id in (RIESGO_ID, MOTIVO_ID):
            raise RubricError(
                f"el id de ítem '{item_id}' está reservado para 'riesgo'/'motivo'"
            )
        if item_id in seen_ids:
            raise RubricError(f"id de ítem duplicado: '{item_id}'")
        seen_ids.add(item_id)

    riesgo = rubric.get("riesgo")
    if not isinstance(riesgo, dict) or "pregunta" not in riesgo or "niveles" not in riesgo:
        raise RubricError("la rúbrica debe tener 'riesgo' con 'pregunta' y 'niveles'")
    if not isinstance(riesgo["niveles"], list) or len(riesgo["niveles"]) != 4:
        raise RubricError("'riesgo' debe tener exactamente 4 niveles")

    motivo = rubric.get("motivo")
    if not isinstance(motivo, dict) or "pregunta" not in motivo or "opciones" not in motivo:
        raise RubricError("la rúbrica debe tener 'motivo' con 'pregunta' y 'opciones'")
    if not isinstance(motivo["opciones"], dict):
        raise RubricError("'motivo.opciones' debe ser un objeto")
    if "otro" not in motivo["opciones"]:
        raise RubricError("'motivo' debe incluir la opción 'otro'")

    return rubric


def build_request(rubric: dict, text: str) -> dict:
    """Construye el cuerpo de la petición a Jev para una interacción.

    El texto de la interacción se envía una sola vez en `state`. `questions`
    contiene un Noul por ítem de la rúbrica más las preguntas `riesgo` y
    `motivo`: exactamente N + 2 preguntas para N ítems.
    """
    questions = {}
    for item in rubric["items"]:
        questions[item["id"]] = {
            "type": "noul",
            "instructions": item["pregunta"],
        }

    questions[RIESGO_ID] = {
        "type": "score",
        "instructions": rubric["riesgo"]["pregunta"],
        "criteria": rubric["riesgo"]["niveles"],
    }

    questions[MOTIVO_ID] = {
        "type": "choice",
        "instructions": rubric["motivo"]["pregunta"],
        "criteria": rubric["motivo"]["opciones"],
    }

    request = {
        "state": text,
        "model": MODEL,
        "questions": questions,
    }
    # `load_rubric` ya rechaza ids duplicados/reservados, pero se comprueba de
    # nuevo aquí para que el invariante N+2 nunca se rompa en silencio, ni
    # siquiera con una rúbrica construida a mano sin pasar por `load_rubric`.
    if len(questions) != len(rubric["items"]) + 2:
        raise RubricError(
            "la rúbrica tiene ids de pregunta duplicados o reservados: "
            "se esperaban exactamente N+2 preguntas"
        )
    return request


def _expected_question_ids(rubric: dict) -> list:
    return [item["id"] for item in rubric["items"]] + [RIESGO_ID, MOTIVO_ID]


def _expected_answer_type(question_id: str) -> str:
    """Tipo de respuesta esperado para `question_id` según la rúbrica.

    Viene de la posición del id (ítem -> noul, riesgo -> score, motivo ->
    choice), no del campo `type` de la respuesta.
    """
    if question_id == RIESGO_ID:
        return "score"
    if question_id == MOTIVO_ID:
        return "choice"
    return "noul"


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _parse_answer(question_id: str, expected_type: str, answer) -> dict:
    """Convierte una respuesta cruda de Jev en un resultado tipado.

    `expected_type` viene de la rúbrica; el campo `type` de la respuesta, si
    está presente, solo se usa como comprobación de consistencia. Conserva
    todos los campos originales de la respuesta (sin pérdida) y añade claves
    normalizadas: `probabilidad`, y para score/choice también `confianza` y
    `distribucion`. Cualquier campo ausente o mal formado lanza
    `RespuestaIncompletaError`, nunca `KeyError`/`TypeError`.
    """
    if not isinstance(answer, dict):
        raise RespuestaIncompletaError(question_id)

    answer_type = answer.get("type")
    if answer_type is not None and answer_type != expected_type:
        raise RespuestaIncompletaError(question_id)

    result = dict(answer)

    if expected_type == "noul":
        noul = answer.get("noul")
        if not _is_number(noul):
            raise RespuestaIncompletaError(question_id)
        result["probabilidad"] = noul
    elif expected_type == "score":
        score = answer.get("score")
        confidence = answer.get("confidence")
        probabilities = answer.get("probabilities")
        if not _is_number(score) or not _is_number(confidence) or not isinstance(
            probabilities, dict
        ):
            raise RespuestaIncompletaError(question_id)
        result["probabilidad"] = score
        result["confianza"] = confidence
        result["distribucion"] = probabilities
    else:  # choice
        choice = answer.get("choice")
        confidence = answer.get("confidence")
        probabilities = answer.get("probabilities")
        if (
            not isinstance(choice, str)
            or not _is_number(confidence)
            or not isinstance(probabilities, dict)
            or choice not in probabilities
        ):
            raise RespuestaIncompletaError(question_id)
        result["probabilidad"] = probabilities.get(choice)
        result["confianza"] = confidence
        result["distribucion"] = probabilities

    return result


def parse_response(rubric: dict, data: dict) -> dict:
    """Convierte la respuesta cruda de Jev en un resultado tipado por pregunta.

    Lanza `RespuestaIncompletaError` si falta la respuesta a alguna de las
    preguntas esperadas para la rúbrica, o si alguna respuesta presente tiene
    un campo ausente o mal formado.
    """
    answers = data.get("answers") if isinstance(data, dict) else None
    if not isinstance(answers, dict):
        raise RespuestaIncompletaError("answers")
    result = {}
    for question_id in _expected_question_ids(rubric):
        if question_id not in answers:
            raise RespuestaIncompletaError(question_id)
        expected_type = _expected_answer_type(question_id)
        result[question_id] = _parse_answer(question_id, expected_type, answers[question_id])
    return result
