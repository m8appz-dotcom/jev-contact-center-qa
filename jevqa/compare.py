"""Comparación contra 100 auditorías humanas (fase 6).

Lee un CSV humano (columna `id` + una columna 0/1 por ítem, con columnas de
metadatos a ignorar) y el CSV auditado de `jevqa.pipeline.auditar`, y calcula
acuerdo y kappa de Cohen por ítem, más la matriz de confusión. La matriz y el
acuerdo se calculan con el humano como primer clasificador y Jev como
segundo: `matriz[(humano, jev)]`. No hace I/O de más ni conoce la CLI.
"""

from __future__ import annotations

import csv
import math

from jevqa.pipeline import OUTPUT_HEADER_BASE

# Columnas del CSV humano que no son ítems de la rúbrica.
METADATA_COLUMNS = {"texto", "ambiguo", "agente", "campaña", "fecha", "cliente", "notas"}


class ComparacionError(Exception):
    """El CSV humano o el de resultados no tienen el formato esperado para comparar."""


def _leer_humano(path: str) -> tuple:
    """Lee el CSV humano. Devuelve `(items, {id: {item: bool}})`."""
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                raise ComparacionError(f"el CSV humano está vacío: {path}")
            if "id" not in reader.fieldnames:
                raise ComparacionError(f"falta la columna 'id' en {path}")
            items = [c for c in reader.fieldnames if c != "id" and c not in METADATA_COLUMNS]
            filas = list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise ComparacionError(f"no se puede leer {path} como CSV UTF-8: {exc}") from exc

    humano = {}
    for fila in filas:
        id_ = (fila.get("id") or "").strip()
        if not id_:
            raise ComparacionError(f"id vacío en {path}")
        if id_ in humano:
            raise ComparacionError(f"id repetido en {path}: '{id_}'")
        valores = {}
        for item in items:
            valor = (fila.get(item) or "").strip()
            if valor not in ("0", "1"):
                raise ComparacionError(
                    f"valor inválido para el id '{id_}', columna '{item}': {valor!r}"
                )
            valores[item] = valor == "1"
        humano[id_] = valores
    return items, humano


def _leer_resultados(path: str) -> tuple:
    """Lee el CSV auditado. Devuelve `(items, {id: {item: bool}})` solo para filas `ok`."""
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            if fieldnames is None:
                raise ComparacionError(f"el CSV de resultados está vacío: {path}")
            base = len(OUTPUT_HEADER_BASE)
            if (
                fieldnames[:base] != OUTPUT_HEADER_BASE
                or fieldnames[-2:] != ["riesgo", "motivo"]
                or len(fieldnames) < base + 2
            ):
                raise ComparacionError(f"cabecera inesperada en {path}")
            items = fieldnames[base:-2]
            filas = list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise ComparacionError(f"no se puede leer {path} como CSV UTF-8: {exc}") from exc

    jev = {}
    for fila in filas:
        if fila.get("estado") != "ok":
            continue
        id_ = (fila.get("id") or "").strip()
        valores = {}
        for item in items:
            valor = fila.get(item)
            try:
                p = float(valor)
            except (TypeError, ValueError):
                raise ComparacionError(
                    f"probabilidad no numérica para el id '{id_}', ítem '{item}': {valor!r}"
                )
            if not (math.isfinite(p) and 0 <= p <= 1):
                raise ComparacionError(
                    f"probabilidad fuera de [0, 1] para el id '{id_}', ítem '{item}': {valor!r}"
                )
            valores[item] = p >= 0.5
        jev[id_] = valores
    return items, jev


def _kappa(matriz: dict, n: int):
    """Kappa de Cohen. Devuelve `None` (indefinido) si `pe == 1`."""
    po = (matriz[("cumple", "cumple")] + matriz[("no_cumple", "no_cumple")]) / n
    p_humano_cumple = (matriz[("cumple", "cumple")] + matriz[("cumple", "no_cumple")]) / n
    p_jev_cumple = (matriz[("cumple", "cumple")] + matriz[("no_cumple", "cumple")]) / n
    pe = p_humano_cumple * p_jev_cumple + (1 - p_humano_cumple) * (1 - p_jev_cumple)
    if pe == 1:
        return None
    return (po - pe) / (1 - pe)


def comparar(humano_csv: str, resultados_csv: str) -> dict:
    """Compara `humano_csv` contra `resultados_csv`.

    Devuelve un dict con `items` (intersección, en el orden de resultados),
    `solo_humano`/`solo_jev` (ítems que faltan en una de las dos rúbricas),
    `ids_sin_resultado` (ids humanos sin fila `ok` en resultados),
    `ids_sin_humano` (ids de resultados sin fila humana), `n` (ids
    comparados) y `por_item`: `{item: {"acuerdo", "kappa", "matriz"}}`, con
    `matriz[(humano, jev)]` en `{"cumple", "no_cumple"}`.

    Lanza `ComparacionError` si no hay ítems en común o si `n == 0`.
    """
    items_humano, humano = _leer_humano(humano_csv)
    items_jev, jev = _leer_resultados(resultados_csv)

    items = [i for i in items_jev if i in items_humano]
    if not items:
        raise ComparacionError("no hay ítems en común entre las dos rúbricas")
    solo_humano = [i for i in items_humano if i not in items_jev]
    solo_jev = [i for i in items_jev if i not in items_humano]

    ids_sin_resultado = [id_ for id_ in humano if id_ not in jev]
    ids_comparables = [id_ for id_ in humano if id_ in jev]
    ids_sin_humano = [id_ for id_ in jev if id_ not in humano]

    n = len(ids_comparables)
    if n == 0:
        raise ComparacionError("no hay ids en común para comparar")

    por_item = {}
    for item in items:
        matriz = {
            ("cumple", "cumple"): 0,
            ("cumple", "no_cumple"): 0,
            ("no_cumple", "cumple"): 0,
            ("no_cumple", "no_cumple"): 0,
        }
        for id_ in ids_comparables:
            h = "cumple" if humano[id_][item] else "no_cumple"
            j = "cumple" if jev[id_][item] else "no_cumple"
            matriz[(h, j)] += 1
        acuerdo = (matriz[("cumple", "cumple")] + matriz[("no_cumple", "no_cumple")]) / n
        por_item[item] = {"acuerdo": acuerdo, "kappa": _kappa(matriz, n), "matriz": matriz}

    return {
        "items": items,
        "solo_humano": solo_humano,
        "solo_jev": solo_jev,
        "ids_sin_resultado": ids_sin_resultado,
        "ids_sin_humano": ids_sin_humano,
        "n": n,
        "por_item": por_item,
    }


def render_comparacion(resultado: dict) -> str:
    """Markdown con la comparación: acuerdo/kappa por ítem, matrices y coberturas."""
    partes = [
        "# Comparación Jev vs. auditoría humana",
        "",
        f"n comparado: {resultado['n']}",
        "",
        "## Acuerdo y kappa por ítem",
        "",
        "| Ítem | Acuerdo | Kappa | N |",
        "| --- | --- | --- | --- |",
    ]
    for item in resultado["items"]:
        r = resultado["por_item"][item]
        kappa_txt = f"{r['kappa']:.4f}" if r["kappa"] is not None else "indefinido"
        partes.append(f"| {item} | {r['acuerdo']:.1%} | {kappa_txt} | {resultado['n']} |")

    partes.append("")
    partes.append("## Matriz de confusión por ítem")
    partes.append("")
    partes.append("(orientación: fila = humano, columna = Jev)")
    for item in resultado["items"]:
        m = resultado["por_item"][item]["matriz"]
        partes.append("")
        partes.append(f"### {item}")
        partes.append("")
        partes.append("| | Jev cumple | Jev no cumple |")
        partes.append("| --- | --- | --- |")
        partes.append(
            f"| Humano cumple | {m[('cumple', 'cumple')]} | {m[('cumple', 'no_cumple')]} |"
        )
        partes.append(
            f"| Humano no cumple | {m[('no_cumple', 'cumple')]} | {m[('no_cumple', 'no_cumple')]} |"
        )

    partes.append("")
    partes.append("## Ítems solo en una rúbrica")
    partes.append("")
    if resultado["solo_humano"] or resultado["solo_jev"]:
        partes.append(f"- Solo en la rúbrica humana: {', '.join(resultado['solo_humano']) or 'ninguno'}")
        partes.append(f"- Solo en la rúbrica de Jev: {', '.join(resultado['solo_jev']) or 'ninguno'}")
    else:
        partes.append("sin datos")

    partes.append("")
    partes.append("## Ids humanos sin resultado")
    partes.append("")
    if resultado["ids_sin_resultado"]:
        for id_ in resultado["ids_sin_resultado"]:
            partes.append(f"- {id_}")
    else:
        partes.append("sin datos")
    partes.append("")

    return "\n".join(partes)
