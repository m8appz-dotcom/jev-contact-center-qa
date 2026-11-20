"""Nota, umbrales y cola de revisión a partir del CSV auditado (fase 4).

Traduce las probabilidades "noul" de cada ítem (una por columna, ya en el CSV
de `jevqa.pipeline.auditar`) en una nota 0-100 ponderada por la rúbrica, un
estado aprobado/suspenso y una marca de revisión humana para los casos
dudosos. Solo puntúa filas con `estado == "ok"`; el resto se cuenta como
`sin_nota` en las agregaciones. No hace I/O ni expone CLI.
"""

from __future__ import annotations

import math

# Umbrales por defecto. `confianza` (= |2p-1|) sale del informe de la fase 2
# (acuerdo medido con confianza >= 0,7); la banda dudosa [0,35, 0,65] la fija
# el plan; `aprobado` = 70 es una decisión de producto sin medir. Todos son
# configurables por rúbrica vía la clave opcional `umbrales`.
DEFAULT_UMBRALES = {
    "confianza": 0.7,
    "dudosa_min": 0.35,
    "dudosa_max": 0.65,
    "aprobado": 70,
}


class ScoringError(Exception):
    """La rúbrica, los umbrales o una fila no tienen el formato esperado para puntuar."""


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def umbrales_de(rubric: dict) -> dict:
    """Umbrales efectivos: `DEFAULT_UMBRALES` con las claves que la rúbrica sobrescribe.

    Lanza `ScoringError` si `umbrales` trae una clave desconocida, un valor no
    numérico, `confianza`/`dudosa_min`/`dudosa_max` fuera de [0,1],
    `dudosa_min` > `dudosa_max` o `aprobado` fuera de [0,100].
    """
    umbrales = dict(DEFAULT_UMBRALES)
    overrides = rubric.get("umbrales", {}) if isinstance(rubric, dict) else {}
    if not isinstance(overrides, dict):
        raise ScoringError("'umbrales' debe ser un objeto")
    for clave, valor in overrides.items():
        if clave not in DEFAULT_UMBRALES:
            raise ScoringError(f"umbral desconocido: '{clave}'")
        if not _is_number(valor):
            raise ScoringError(f"el umbral '{clave}' debe ser numérico")
        umbrales[clave] = valor

    for clave in ("confianza", "dudosa_min", "dudosa_max"):
        if not (0 <= umbrales[clave] <= 1):
            raise ScoringError(f"el umbral '{clave}' debe estar entre 0 y 1")
    if umbrales["dudosa_min"] > umbrales["dudosa_max"]:
        raise ScoringError("'dudosa_min' no puede ser mayor que 'dudosa_max'")
    if not (0 <= umbrales["aprobado"] <= 100):
        raise ScoringError("el umbral 'aprobado' debe estar entre 0 y 100")
    return umbrales


def _validar_items(rubric: dict) -> None:
    """Valida los pesos y el campo `critico` de los ítems de la rúbrica."""
    items = rubric["items"]
    total_peso = 0
    for item in items:
        peso = item["peso"]
        if not _is_number(peso) or not math.isfinite(peso) or peso < 0:
            raise ScoringError(f"peso inválido para el ítem '{item.get('id')}': {peso!r}")
        if not isinstance(item["critico"], bool):
            raise ScoringError(f"'critico' debe ser booleano para el ítem '{item.get('id')}'")
        total_peso += peso
    if total_peso <= 0:
        raise ScoringError("la suma de pesos de la rúbrica debe ser mayor que 0")


def _parse_probabilidad(fila_id, item_id: str, valor) -> float:
    if valor is None or valor == "":
        raise ScoringError(f"fila '{fila_id}': falta la probabilidad del ítem '{item_id}'")
    try:
        p = float(valor)
    except (TypeError, ValueError):
        raise ScoringError(
            f"fila '{fila_id}': probabilidad no numérica para el ítem '{item_id}': {valor!r}"
        )
    if math.isnan(p):
        raise ScoringError(f"fila '{fila_id}': probabilidad NaN para el ítem '{item_id}'")
    if not (0 <= p <= 1):
        raise ScoringError(
            f"fila '{fila_id}': probabilidad fuera de [0,1] para el ítem '{item_id}': {p}"
        )
    return p


def puntuar(rubric: dict, fila: dict) -> dict:
    """Puntúa una fila `estado == "ok"` del CSV auditado.

    Un ítem cumple si `p >= 0,5`; su confianza es `|2p-1|`. Es dudoso si la
    confianza queda por debajo del umbral `confianza` o si `p` cae dentro de
    la banda `[dudosa_min, dudosa_max]`. La fila entra en revisión si algún
    ítem es dudoso. La nota es la suma ponderada de los ítems que cumplen
    sobre la suma de los pesos, 0-100 a un decimal; el estado es "suspenso"
    si algún ítem crítico no cumple o si la nota queda por debajo del umbral
    `aprobado` (la nota reportada no cambia por eso, solo el estado).
    """
    if fila.get("estado") != "ok":
        raise ScoringError(f"fila '{fila.get('id')}': solo se puntúan filas con estado 'ok'")

    _validar_items(rubric)
    umbrales = umbrales_de(rubric)
    fila_id = fila.get("id")

    peso_total = 0.0
    peso_cumple = 0.0
    criticos_fallidos = []
    motivos_revision = []
    for item in rubric["items"]:
        item_id = item["id"]
        peso = item["peso"]
        p = _parse_probabilidad(fila_id, item_id, fila.get(item_id))
        cumple = p >= 0.5
        confianza = abs(2 * p - 1)

        peso_total += peso
        if cumple:
            peso_cumple += peso
        elif item["critico"]:
            criticos_fallidos.append(item_id)

        if confianza < umbrales["confianza"] or umbrales["dudosa_min"] <= p <= umbrales["dudosa_max"]:
            motivos_revision.append(item_id)

    nota = round(100 * peso_cumple / peso_total, 1)
    estado = "suspenso" if criticos_fallidos or nota < umbrales["aprobado"] else "aprobado"

    return {
        "id": fila_id,
        "agente": fila.get("agente"),
        "campaña": fila.get("campaña"),
        "nota": nota,
        "estado": estado,
        "criticos_fallidos": criticos_fallidos,
        "revision": bool(motivos_revision),
        "motivos_revision": motivos_revision,
    }


def puntuar_lote(rubric: dict, filas: list) -> tuple:
    """Puntúa todas las filas `estado == "ok"` de `filas`. Devuelve `(puntuadas, sin_nota)`."""
    puntuadas = []
    sin_nota = 0
    for fila in filas:
        if fila.get("estado") == "ok":
            puntuadas.append(puntuar(rubric, fila))
        else:
            sin_nota += 1
    return puntuadas, sin_nota


def agregar(rubric: dict, filas: list, clave: str) -> dict:
    """Agrega `filas` por `clave` ("agente" o "campaña"). Devuelve `grupo -> estadísticas`.

    Cada grupo tiene `{n, sin_nota, nota_media, pct_criticas, cola}`: `n` son
    las interacciones puntuadas, `nota_media` es `None` si `n == 0`,
    `pct_criticas` es el porcentaje de interacciones puntuadas con al menos
    un ítem crítico fallido (0,0 si `n == 0`) y `cola` cuenta las que quedan
    en revisión. Un grupo sin filas `ok` aparece igual, con `n == 0`.
    """
    if clave not in ("agente", "campaña"):
        raise ScoringError(f"clave de agregación inválida: '{clave}'")

    grupos = {}
    for fila in filas:
        grupo = fila.get(clave)
        stats = grupos.setdefault(
            grupo, {"n": 0, "sin_nota": 0, "notas": [], "criticas": 0, "cola": 0}
        )
        if fila.get("estado") == "ok":
            resultado = puntuar(rubric, fila)
            stats["n"] += 1
            stats["notas"].append(resultado["nota"])
            if resultado["criticos_fallidos"]:
                stats["criticas"] += 1
            if resultado["revision"]:
                stats["cola"] += 1
        else:
            stats["sin_nota"] += 1

    salida = {}
    for grupo, stats in grupos.items():
        n = stats["n"]
        salida[grupo] = {
            "n": n,
            "sin_nota": stats["sin_nota"],
            "nota_media": round(sum(stats["notas"]) / n, 1) if n else None,
            "pct_criticas": round(100 * stats["criticas"] / n, 1) if n else 0.0,
            "cola": stats["cola"],
        }
    return salida
