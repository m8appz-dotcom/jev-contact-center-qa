"""Comparación contra auditorías humanas: acuerdo, kappa y matriz de confusión.

Es la prueba que se entrega en el piloto: el cliente audita a mano una muestra
(el plan pide 100 interacciones), se pasa la misma muestra por `auditar`, y se
mide ítem por ítem cuánto coinciden las dos auditorías.

    python -m jevqa comparar humano.csv resultados.csv

El CSV humano lleva una columna `id` y una columna por ítem de la rúbrica con
`cumple` o `no`. `data/eval/sinteticas.csv` tiene exactamente esa forma.

El kappa de Cohen importa más que el acuerdo: si el 95 % de las interacciones
cumple un ítem, un auditor que diga siempre «cumple» acierta el 95 % sin mirar
nada, y su kappa es 0.
"""

from __future__ import annotations

import csv
import datetime
import os

from jevqa.scoring import resolver_umbrales, umbral_de_item

CUMPLE = "cumple"
NO = "no"
ETIQUETAS = (CUMPLE, NO)

#: Muestra que pide el plan para el piloto. Por debajo, el kappa se mueve mucho.
MUESTRA_PILOTO = 100


class ErrorComparacion(Exception):
    """Alguno de los dos CSV no existe o no tiene la forma esperada."""


# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------

def matriz(pares: list[tuple[bool, bool]]) -> dict:
    """Matriz de confusión 2×2. Filas: humano; columnas: Jev."""
    celdas = {
        "cumple_cumple": 0,
        "cumple_no": 0,
        "no_cumple": 0,
        "no_no": 0,
    }
    for humano, jev in pares:
        clave = f"{CUMPLE if humano else NO}_{CUMPLE if jev else NO}"
        celdas[clave] += 1
    return celdas


def kappa(pares: list[tuple[bool, bool]]) -> float | None:
    """Kappa de Cohen para dos evaluadores y dos clases.

    Devuelve None cuando no está definido: si los dos dicen siempre lo mismo y
    nunca cambian de clase, el acuerdo esperado por azar es 1 y el kappa es
    0/0. Poner un 1 ahí sería afirmar un acuerdo que la muestra no puede
    demostrar.
    """
    total = len(pares)
    if not total:
        return None
    observado = sum(1 for humano, jev in pares if humano == jev) / total
    humano_cumple = sum(1 for humano, _ in pares if humano) / total
    jev_cumple = sum(1 for _, jev in pares if jev) / total
    esperado = humano_cumple * jev_cumple + (1 - humano_cumple) * (1 - jev_cumple)
    if esperado >= 1.0:
        return None
    return (observado - esperado) / (1 - esperado)


def metricas(pares: list[tuple[bool, bool]]) -> dict:
    total = len(pares)
    acuerdos = sum(1 for humano, jev in pares if humano == jev)
    return {
        "n": total,
        "acuerdos": acuerdos,
        "acuerdo": acuerdos / total if total else None,
        "kappa": kappa(pares),
        "matriz": matriz(pares),
    }


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------

def _leer(ruta: str, que: str) -> tuple[list[str], list[dict]]:
    if not os.path.exists(ruta):
        raise ErrorComparacion(f"no existe el CSV {que} {ruta}")
    with open(ruta, encoding="utf-8-sig", newline="") as archivo:
        lector = csv.DictReader(archivo)
        if lector.fieldnames is None:
            raise ErrorComparacion(f"el CSV {que} {ruta} está vacío")
        if "id" not in lector.fieldnames:
            raise ErrorComparacion(f"el CSV {que} {ruta} no tiene columna id")
        return list(lector.fieldnames), list(lector)


def comparar(humano: str, resultados: str, rubrica: dict) -> dict:
    """Compara la auditoría humana con la de Jev, ítem por ítem.

    Nada se descarta en silencio: los ids humanos sin resultado, los que Jev no
    pudo auditar, las etiquetas humanas vacías o ilegibles y los ítems que solo
    existen en uno de los dos lados salen en el resultado con su motivo.
    """
    umbrales = resolver_umbrales(rubrica)
    columnas_humano, filas_humano = _leer(humano, "humano")
    columnas_jev, filas_jev = _leer(resultados, "de resultados")

    ids_rubrica = [item["id"] for item in rubrica["items"]]
    en_humano = [qid for qid in ids_rubrica if qid in columnas_humano]
    en_jev = [qid for qid in ids_rubrica if f"{qid}_prob" in columnas_jev]
    comparables = [qid for qid in ids_rubrica if qid in en_humano and qid in en_jev]
    items_sin_comparar = [
        {"item": qid, "falta_en": "humano" if qid not in en_humano else "resultados"}
        for qid in ids_rubrica
        if qid not in comparables
    ]
    if not comparables:
        raise ErrorComparacion(
            "no hay ningún ítem en común entre el CSV humano, el de resultados y la rúbrica "
            f"{rubrica['id']}"
        )

    jev_por_id = {}
    jev_con_error = []
    for fila in filas_jev:
        ident = (fila.get("id") or "").strip()
        if fila.get("estado", "ok") != "ok":
            jev_con_error.append(ident)
            continue
        jev_por_id[ident] = fila

    pares: dict[str, list[tuple[bool, bool]]] = {qid: [] for qid in comparables}
    sin_resultado: list[str] = []
    con_error: list[str] = []
    etiquetas_invalidas: list[dict] = []
    comparadas = 0

    for fila in filas_humano:
        ident = (fila.get("id") or "").strip()
        if ident not in jev_por_id:
            (con_error if ident in jev_con_error else sin_resultado).append(ident)
            continue
        fila_jev = jev_por_id[ident]
        comparadas += 1
        for qid in comparables:
            etiqueta = (fila.get(qid) or "").strip().lower()
            if etiqueta not in ETIQUETAS:
                etiquetas_invalidas.append({"id": ident, "item": qid, "valor": etiqueta})
                continue
            try:
                probabilidad = float(fila_jev[f"{qid}_prob"])
            except (TypeError, ValueError):
                etiquetas_invalidas.append({"id": ident, "item": qid, "valor": "(sin dato de Jev)"})
                continue
            pares[qid].append((etiqueta == CUMPLE, probabilidad >= umbral_de_item(umbrales, qid)))

    por_item = {qid: metricas(pares[qid]) for qid in comparables}
    todos = [par for qid in comparables for par in pares[qid]]
    ids_humanos = {(f.get("id") or "").strip() for f in filas_humano}

    return {
        "rubrica": rubrica["id"],
        "humano": humano,
        "resultados": resultados,
        "interacciones_humanas": len(filas_humano),
        "interacciones_comparadas": comparadas,
        "ids_sin_resultado": sin_resultado,
        "ids_con_error_en_jev": con_error,
        "ids_solo_en_resultados": sorted(set(jev_por_id) - ids_humanos),
        "items": por_item,
        "items_sin_comparar": items_sin_comparar,
        "etiquetas_invalidas": etiquetas_invalidas,
        "global": metricas(todos),
        "criticos": [item["id"] for item in rubrica["items"] if item["critico"]],
    }


# ---------------------------------------------------------------------------
# Salida
# ---------------------------------------------------------------------------

def _pct(valor: float | None) -> str:
    return "—" if valor is None else f"{valor * 100:.1f} %"


def _k(valor: float | None) -> str:
    return "sin definir" if valor is None else f"{valor:.3f}"


def _lectura_kappa(valor: float | None) -> str:
    """Escala de Landis y Koch, la que se usa en auditoría de calidad."""
    if valor is None:
        return "sin variación"
    if valor < 0:
        return "peor que el azar"
    for tope, texto in ((0.2, "leve"), (0.4, "aceptable"), (0.6, "moderado"), (0.8, "sustancial")):
        if valor <= tope:
            return texto
    return "casi perfecto"


def _matriz_md(celdas: dict) -> list[str]:
    return [
        "| Humano \\ Jev | cumple | no |",
        "| --- | --: | --: |",
        f"| cumple | {celdas['cumple_cumple']} | {celdas['cumple_no']} |",
        f"| no | {celdas['no_cumple']} | {celdas['no_no']} |",
    ]


def a_markdown(resultado: dict) -> str:
    lineas = [
        "# Comparación con la auditoría humana",
        "",
        f"- Fecha: {datetime.date.today().isoformat()}",
        f"- Rúbrica: `{resultado['rubrica']}`",
        f"- Auditoría humana: `{resultado['humano']}` ({resultado['interacciones_humanas']} interacciones)",
        f"- Resultados de Jev: `{resultado['resultados']}`",
        f"- Interacciones comparadas: **{resultado['interacciones_comparadas']}**",
        "",
    ]
    if resultado["interacciones_comparadas"] < MUESTRA_PILOTO:
        lineas += [
            f"> Muestra por debajo de las {MUESTRA_PILOTO} interacciones del piloto: con",
            "> tan pocos casos el kappa se mueve mucho de una muestra a otra.",
            "",
        ]

    lineas += [
        "## Acuerdo y kappa por ítem",
        "",
        "| Ítem | Crítico | n | Acuerdo | Kappa | Lectura |",
        "| --- | :-: | --: | --: | --: | --- |",
    ]
    for qid, m in resultado["items"].items():
        lineas.append(
            f"| `{qid}` | {'sí' if qid in resultado['criticos'] else ''} | {m['n']} | "
            f"{_pct(m['acuerdo'])} | {_k(m['kappa'])} | {_lectura_kappa(m['kappa'])} |"
        )
    g = resultado["global"]
    lineas += [
        f"| **todos** |  | {g['n']} | {_pct(g['acuerdo'])} | {_k(g['kappa'])} | {_lectura_kappa(g['kappa'])} |",
        "",
        "Un kappa «sin definir» quiere decir que los dos lados dieron siempre la",
        "misma clase: coinciden, pero la muestra no tiene ni un caso que lo pruebe.",
        "",
        "## Matriz de confusión (todos los ítems)",
        "",
        *_matriz_md(g["matriz"]),
        "",
        "La celda que importa es **humano «no» / Jev «cumple»**: son las fallas que",
        "la auditoría automática deja pasar.",
        "",
        "## Matriz de confusión por ítem",
        "",
    ]
    for qid, m in resultado["items"].items():
        lineas += [f"### `{qid}`", "", *_matriz_md(m["matriz"]), ""]

    avisos = []
    if resultado["ids_sin_resultado"]:
        avisos.append(
            f"- {len(resultado['ids_sin_resultado'])} ids humanos sin resultado de Jev: "
            + ", ".join(f"`{i}`" for i in resultado["ids_sin_resultado"])
        )
    if resultado["ids_con_error_en_jev"]:
        avisos.append(
            f"- {len(resultado['ids_con_error_en_jev'])} ids que Jev no pudo auditar: "
            + ", ".join(f"`{i}`" for i in resultado["ids_con_error_en_jev"])
        )
    if resultado["ids_solo_en_resultados"]:
        avisos.append(
            f"- {len(resultado['ids_solo_en_resultados'])} ids auditados por Jev sin auditoría humana (no cuentan)."
        )
    for sin in resultado["items_sin_comparar"]:
        avisos.append(f"- Ítem `{sin['item']}` sin comparar: falta en el CSV {sin['falta_en']}.")
    if resultado["etiquetas_invalidas"]:
        avisos.append(
            f"- {len(resultado['etiquetas_invalidas'])} etiquetas vacías o ilegibles, fuera del cálculo."
        )
    if avisos:
        lineas += ["## Lo que quedó fuera", "", *avisos, ""]

    return "\n".join(lineas) + "\n"


def resumen_consola(resultado: dict) -> str:
    lineas = [
        f"{resultado['interacciones_comparadas']} interacciones comparadas "
        f"de {resultado['interacciones_humanas']} auditadas a mano.",
        "",
        f"{'Ítem':<24} {'n':>4} {'Acuerdo':>9} {'Kappa':>12}",
    ]
    for qid, m in resultado["items"].items():
        lineas.append(f"{qid:<24} {m['n']:>4} {_pct(m['acuerdo']):>9} {_k(m['kappa']):>12}")
    g = resultado["global"]
    lineas.append(f"{'todos':<24} {g['n']:>4} {_pct(g['acuerdo']):>9} {_k(g['kappa']):>12}")
    if resultado["ids_sin_resultado"] or resultado["ids_con_error_en_jev"]:
        lineas.append(
            f"\nSin comparar: {len(resultado['ids_sin_resultado'])} ids sin resultado, "
            f"{len(resultado['ids_con_error_en_jev'])} con error en Jev."
        )
    for sin in resultado["items_sin_comparar"]:
        lineas.append(f"Ítem {sin['item']} sin comparar: falta en el CSV {sin['falta_en']}.")
    return "\n".join(lineas)


def escribir(resultado: dict, ruta: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(ruta)), exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="\n") as archivo:
        archivo.write(a_markdown(resultado))
    return ruta
