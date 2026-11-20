"""Evalúa qué tan bien coincide Jev con etiquetas humanas en español.

Lee `data/eval/sinteticas.csv`, envía cada interacción a Jev (o a un doble
sin red en modo `--fake`) usando `rubrics/soporte_es.json`, y escribe un
informe con métricas por ítem, coste real y los peores desacuerdos.

En modo `--fake` el informe se escribe en `data/eval/informe_fake.md` (nunca
pisa el informe real). En vivo se escribe en `data/eval/informe.md`.

Las funciones de métricas son puras y no dependen de red ni de E/S, para
poder testearlas por separado (ver `tests/test_eval_metrics.py`).

Códigos de salida de `main()`:
    0 = todas las filas se evaluaron y todos los ítems tienen acuerdo >= 85 %.
    2 = el CSV de entrada no es válido (columna de ítem faltante, etiqueta
        que no es 0/1, o id duplicado).
    3 = modo en vivo sin credenciales válidas (falta TYPESAFE_API_KEY o la
        API respondió 401): se aborta antes de escribir ningún informe.
    4 = una o más filas fallaron al evaluarse (no se completó el 100 %).
    5 = todas las filas se evaluaron, pero algún ítem quedó por debajo del
        85 % de acuerdo (punto de decisión de la Fase 2).
"""

from __future__ import annotations

import csv
import hashlib
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from jevqa import rubric as rubric_mod
from jevqa.jev_client import JevAuthError, JevClient, JevError

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
RUBRIC_PATH = os.path.join(REPO_ROOT, "rubrics", "soporte_es.json")
CSV_PATH = os.path.join(REPO_ROOT, "data", "eval", "sinteticas.csv")
INFORME_PATH = os.path.join(REPO_ROOT, "data", "eval", "informe.md")
INFORME_FAKE_PATH = os.path.join(REPO_ROOT, "data", "eval", "informe_fake.md")

CONFIANZA_MINIMA = 0.7
UMBRAL_DECISION = 0.85
PRECIO_ENTRADA_POR_MILLON = 0.042  # USD por millón de tokens de entrada; salida no se factura.

EXIT_OK = 0
EXIT_CSV_INVALIDO = 2
EXIT_AUTH_ERROR = 3
EXIT_FILAS_FALLIDAS = 4
EXIT_DEBAJO_UMBRAL = 5


# --------------------------------------------------------------------------
# Métricas puras
# --------------------------------------------------------------------------

def confianza_de(probabilidad: float) -> float:
    """Confianza de un Noul: |2p - 1|.

    0 cuando p = 0,5 (máxima incertidumbre), 1 cuando p = 0 o p = 1 (máxima
    certeza). Es la misma escala que `confidence` de las preguntas Choice y
    Score de Jev, para que el umbral `CONFIANZA_MINIMA` sea comparable.
    """
    return abs(2 * probabilidad - 1)


def prediccion_de(probabilidad: float) -> int:
    """Decisión "cumple" (1) / "no cumple" (0) con umbral 0,5."""
    return 1 if probabilidad >= 0.5 else 0


def item_metrics(records: list[dict]) -> dict:
    """Calcula métricas de un ítem a partir de sus registros por fila.

    Cada registro es `{"etiqueta": 0|1, "prediccion": 0|1, "confianza": float}`.
    Devuelve `None` en cualquier métrica cuyo denominador sea 0, en vez de
    dividir por cero.
    """
    n = len(records)
    acuerdo = (
        sum(1 for r in records if r["etiqueta"] == r["prediccion"]) / n
        if n
        else None
    )

    predichos_no_cumple = [r for r in records if r["prediccion"] == 0]
    precision_no_cumple = (
        sum(1 for r in predichos_no_cumple if r["etiqueta"] == 0) / len(predichos_no_cumple)
        if predichos_no_cumple
        else None
    )

    reales_no_cumple = [r for r in records if r["etiqueta"] == 0]
    exhaustividad_no_cumple = (
        sum(1 for r in reales_no_cumple if r["prediccion"] == 0) / len(reales_no_cumple)
        if reales_no_cumple
        else None
    )

    alta_confianza = [r for r in records if r["confianza"] >= CONFIANZA_MINIMA]
    acuerdo_alta_confianza = (
        sum(1 for r in alta_confianza if r["etiqueta"] == r["prediccion"]) / len(alta_confianza)
        if alta_confianza
        else None
    )

    return {
        "n": n,
        "n_alta_confianza": len(alta_confianza),
        "acuerdo": acuerdo,
        "precision_no_cumple": precision_no_cumple,
        "exhaustividad_no_cumple": exhaustividad_no_cumple,
        "acuerdo_alta_confianza": acuerdo_alta_confianza,
    }


def peores_desacuerdos(entradas: list[dict], top: int = 5) -> list[dict]:
    """Las `top` entradas con mayor |probabilidad - etiqueta|, solo desacuerdos reales.

    Un desacuerdo real es aquel donde `prediccion != etiqueta`; las entradas
    donde Jev acertó (aunque con baja confianza) no cuentan como desacuerdo y
    se descartan. Si no hay ninguna, devuelve una lista vacía. Cada entrada es
    `{"id":, "item":, "etiqueta":, "prediccion":, "probabilidad":, "texto":}`.
    """
    desacuerdos = [e for e in entradas if e["prediccion"] != e["etiqueta"]]
    return sorted(
        desacuerdos, key=lambda e: abs(e["probabilidad"] - e["etiqueta"]), reverse=True
    )[:top]


def costo_dolares(tokens_entrada: int) -> float:
    """Coste real en USD: solo se facturan los tokens de entrada.

    Los tokens de salida son gratis en la API de Jev, así que no entran en
    el cálculo (ver `PRECIO_ENTRADA_POR_MILLON`).
    """
    return tokens_entrada * PRECIO_ENTRADA_POR_MILLON / 1_000_000


# --------------------------------------------------------------------------
# Datos y ejecución
# --------------------------------------------------------------------------

class CsvValidationError(Exception):
    """El CSV de entrada no tiene el formato esperado (columna, fila y motivo)."""

    def __init__(self, fila: int, columna: str, mensaje: str):
        self.fila = fila
        self.columna = columna
        super().__init__(f"fila {fila}, columna '{columna}': {mensaje}")


def item_ids(rubric: dict) -> list[str]:
    return [item["id"] for item in rubric["items"]]


def read_synthetic_csv(path: str, ids: list[str]) -> list[dict]:
    """Lee `sinteticas.csv`: cada fila trae id, texto y una etiqueta 0/1 por ítem.

    Valida, fila por fila: que exista la columna de cada ítem, que la
    etiqueta sea '0' o '1' (una celda vacía no es válida), y que el id no
    esté repetido. Cualquier problema lanza `CsvValidationError` nombrando
    la fila y la columna.
    """
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = []
        seen_ids: set[str] = set()
        for numero_fila, row in enumerate(reader, start=2):
            row_id = row.get("id")
            if row_id in seen_ids:
                raise CsvValidationError(numero_fila, "id", f"id duplicado: '{row_id}'")
            seen_ids.add(row_id)

            etiquetas = {}
            for item_id in ids:
                if item_id not in row:
                    raise CsvValidationError(
                        numero_fila, item_id, f"falta la columna del ítem '{item_id}'"
                    )
                valor = row[item_id]
                if valor not in ("0", "1"):
                    raise CsvValidationError(
                        numero_fila, item_id, f"la etiqueta debe ser 0 o 1, no {valor!r}"
                    )
                etiquetas[item_id] = int(valor)

            rows.append(
                {
                    "id": row_id,
                    "texto": row["texto"],
                    "ambiguo": row.get("ambiguo", "0") == "1",
                    "etiquetas": etiquetas,
                }
            )
        return rows


def _ruido_determinista(clave: str) -> float:
    """Ruido determinista en [-1, 1] a partir de un hash de `clave` (sin red ni azar)."""
    digest = hashlib.sha256(clave.encode("utf-8")).hexdigest()
    entero = int(digest[:8], 16)
    return (entero % 2001 - 1000) / 1000.0


def fake_raw_response(rubric: dict, row: dict) -> dict:
    """Respuesta cruda determinista de FakeJev a partir de las etiquetas humanas.

    Genera probabilidades cercanas a la etiqueta con algo de ruido
    determinista (más ruido si la interacción está marcada como ambigua),
    para ejercitar el flujo completo y las métricas sin red.
    """
    answers = {}
    for item in rubric["items"]:
        item_id = item["id"]
        etiqueta = row["etiquetas"][item_id]
        amplitud = 0.35 if row["ambiguo"] else 0.1
        ruido = _ruido_determinista(f"{row['id']}:{item_id}") * amplitud
        base = 0.85 if etiqueta == 1 else 0.15
        p = min(0.99, max(0.01, base + ruido))
        answers[item_id] = {"type": "noul", "noul": round(p, 4)}

    answers[rubric_mod.RIESGO_ID] = {
        "type": "score",
        "score": 0,
        "confidence": 0.9,
        "probabilities": {"0": 0.9, "1": 0.06, "2": 0.03, "3": 0.01},
    }
    opciones = list(rubric["motivo"]["opciones"].keys())
    probabilities = {op: round(1.0 / len(opciones), 4) for op in opciones}
    answers[rubric_mod.MOTIVO_ID] = {
        "type": "choice",
        "choice": opciones[0],
        "confidence": 0.6,
        "probabilities": probabilities,
    }

    input_tokens = max(1, len(row["texto"]) // 4)
    return {
        "model": "fake-jev",
        "answers": answers,
        "usage": {"input_tokens": input_tokens, "output_tokens": 40},
    }


class FakeJevPorFila:
    """Doble de pruebas de Jev que responde según el orden de las filas.

    A diferencia de indexar por el `state` de la petición (el texto), esto
    evita que dos filas con texto idéntico pero id distinto reciban la misma
    respuesta por accidente: cada llamada a `evaluate` consume la siguiente
    respuesta de la cola, en el mismo orden en que se construyó a partir de
    las filas.
    """

    def __init__(self, respuestas_por_id: dict, orden_ids: list[str]):
        self._cola = [respuestas_por_id[row_id] for row_id in orden_ids]
        self.calls: list = []

    def evaluate(self, request: dict) -> dict:
        self.calls.append(request)
        return self._cola.pop(0)


def build_fake_client(rubric: dict, rows: list[dict]) -> FakeJevPorFila:
    respuestas_por_id = {row["id"]: fake_raw_response(rubric, row) for row in rows}
    orden_ids = [row["id"] for row in rows]
    return FakeJevPorFila(respuestas_por_id, orden_ids)


def run_evaluation(rubric: dict, rows: list[dict], client) -> dict:
    """Evalúa todas las filas con `client` (FakeJev o JevClient real).

    Devuelve `{"resultados": [...], "fallos": [...], "tokens_entrada": int,
    "tokens_salida": int}`. Un fallo en una fila no detiene el resto, salvo
    `JevAuthError` (credenciales inválidas o ausentes): esa se propaga de
    inmediato, porque reintentar fila por fila no tiene sentido y no debe
    llegar a escribirse ningún informe con datos parciales.
    """
    resultados = []
    fallos = []
    tokens_entrada = 0
    tokens_salida = 0

    for row in rows:
        request = rubric_mod.build_request(rubric, row["texto"])
        try:
            raw = client.evaluate(request)
            parsed = rubric_mod.parse_response(rubric, raw)
        except JevAuthError:
            raise
        except (JevError, rubric_mod.RespuestaIncompletaError) as exc:
            fallos.append({"id": row["id"], "error": str(exc)})
            continue

        usage = raw.get("usage") if isinstance(raw, dict) else None
        if isinstance(usage, dict):
            tokens_entrada += usage.get("input_tokens") or 0
            tokens_salida += usage.get("output_tokens") or 0

        por_item = {}
        for item_id in item_ids(rubric):
            probabilidad = parsed[item_id]["probabilidad"]
            por_item[item_id] = {
                "etiqueta": row["etiquetas"][item_id],
                "prediccion": prediccion_de(probabilidad),
                "probabilidad": probabilidad,
                "confianza": confianza_de(probabilidad),
            }
        resultados.append({"id": row["id"], "texto": row["texto"], "por_item": por_item})

    return {
        "resultados": resultados,
        "fallos": fallos,
        "tokens_entrada": tokens_entrada,
        "tokens_salida": tokens_salida,
    }


# --------------------------------------------------------------------------
# Informe
# --------------------------------------------------------------------------

def render_informe(rubric: dict, evaluacion: dict, filas_totales: int, modo: str) -> tuple[str, list[str]]:
    """Arma el informe en Markdown.

    Devuelve `(texto, items_bajo_umbral)`: el texto del informe y la lista de
    ítems cuyo acuerdo quedó por debajo de `UMBRAL_DECISION`, para que quien
    llama pueda decidir el código de salida sin reimplementar el cálculo.
    """
    ids = item_ids(rubric)
    resultados = evaluacion["resultados"]
    fallos = evaluacion["fallos"]

    metrics_por_item = {}
    entradas_desacuerdo = []
    for item_id in ids:
        records = []
        for r in resultados:
            info = r["por_item"][item_id]
            records.append(
                {
                    "etiqueta": info["etiqueta"],
                    "prediccion": info["prediccion"],
                    "confianza": info["confianza"],
                }
            )
            entradas_desacuerdo.append(
                {
                    "id": r["id"],
                    "item": item_id,
                    "etiqueta": info["etiqueta"],
                    "prediccion": info["prediccion"],
                    "probabilidad": info["probabilidad"],
                    "texto": r["texto"],
                }
            )
        metrics_por_item[item_id] = item_metrics(records)

    peores = peores_desacuerdos(entradas_desacuerdo, top=5)

    def fmt_pct(v):
        return f"{v * 100:.1f}%" if v is not None else "n/d (sin datos)"

    lineas = []
    lineas.append("# Informe de evaluación de Jev en español (Fase 2)")
    lineas.append("")
    if modo == "fake":
        lineas.append(
            "**Modo fake, no mide nada.** Las respuestas son sintéticas y deterministas "
            "(`FakeJevPorFila`), generadas a partir de las propias etiquetas humanas: no "
            "pasan por Jev ni por la red. Este informe solo sirve para ejercitar el flujo."
        )
        lineas.append("")
    modo_txt = "`--fake` (sin red)" if modo == "fake" else "en vivo (JevClient, TYPESAFE_API_KEY)"
    lineas.append(f"Generado por: modo {modo_txt}, el {datetime.now(timezone.utc).isoformat()}.")
    lineas.append("")
    lineas.append(
        f"Filas evaluadas: {len(resultados)} de {filas_totales}. Filas fallidas: {len(fallos)}."
    )
    if fallos:
        lineas.append("")
        lineas.append("Fallos:")
        for f in fallos:
            lineas.append(f"- {f['id']}: {f['error']}")
    lineas.append("")

    lineas.append("## Métricas por ítem")
    lineas.append("")
    lineas.append(
        "| Ítem | Acuerdo | Precisión no cumple | Exhaustividad no cumple | "
        "Acuerdo confianza ≥ 0,7 (n) | n |"
    )
    lineas.append("|---|---|---|---|---|---|")
    items_bajo_umbral = []
    for item_id in ids:
        m = metrics_por_item[item_id]
        if m["acuerdo"] is not None and m["acuerdo"] < UMBRAL_DECISION:
            items_bajo_umbral.append(item_id)
        lineas.append(
            f"| {item_id} | {fmt_pct(m['acuerdo'])} | {fmt_pct(m['precision_no_cumple'])} | "
            f"{fmt_pct(m['exhaustividad_no_cumple'])} | "
            f"{fmt_pct(m['acuerdo_alta_confianza'])} ({m['n_alta_confianza']}) | {m['n']} |"
        )
    lineas.append("")

    if items_bajo_umbral:
        lineas.append(
            f"**PUNTO DE DECISIÓN:** los ítems {', '.join(items_bajo_umbral)} tienen acuerdo "
            f"por debajo del {UMBRAL_DECISION * 100:.0f}%. Detenerse y decidir: reformular en "
            "inglés, traducir el texto antes de enviarlo, o quitar el ítem."
        )
        lineas.append("")

    lineas.append("## Coste")
    lineas.append("")
    costo = costo_dolares(evaluacion["tokens_entrada"])
    lineas.append(
        f"Tokens de entrada (facturados): {evaluacion['tokens_entrada']}. "
        f"Tokens de salida (no se facturan): {evaluacion['tokens_salida']}."
    )
    lineas.append(
        f"Coste real: ${costo:.6f} "
        f"(tokens de entrada × ${PRECIO_ENTRADA_POR_MILLON}/1M; la salida es gratis)."
    )
    lineas.append("")

    lineas.append("## Los peores desacuerdos")
    lineas.append("")
    if peores:
        lineas.append("| id | ítem | etiqueta | probabilidad | extracto |")
        lineas.append("|---|---|---|---|---|")
        for e in peores:
            extracto = e["texto"][:80].replace("\n", " ").replace("|", "/")
            lineas.append(
                f"| {e['id']} | {e['item']} | {e['etiqueta']} | {e['probabilidad']:.2f} | "
                f"{extracto}... |"
            )
    else:
        lineas.append("No hay desacuerdos: todas las predicciones coinciden con las etiquetas.")
    lineas.append("")

    return "\n".join(lineas), items_bajo_umbral


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    fake = "--fake" in argv

    rubric = rubric_mod.load_rubric(RUBRIC_PATH)
    ids = item_ids(rubric)

    try:
        rows = read_synthetic_csv(CSV_PATH, ids)
    except CsvValidationError as exc:
        print(f"CSV inválido ({CSV_PATH}): {exc}", file=sys.stderr)
        return EXIT_CSV_INVALIDO

    if fake:
        client = build_fake_client(rubric, rows)
    else:
        client = JevClient()

    try:
        evaluacion = run_evaluation(rubric, rows, client)
    except JevAuthError as exc:
        print(f"Error de autenticación con Jev: {exc}", file=sys.stderr)
        print(
            "Define TYPESAFE_API_KEY con una API key válida antes de correr en modo en vivo. "
            "No se escribió ningún informe.",
            file=sys.stderr,
        )
        return EXIT_AUTH_ERROR

    informe_path = INFORME_FAKE_PATH if fake else INFORME_PATH
    informe, items_bajo_umbral = render_informe(
        rubric, evaluacion, len(rows), "fake" if fake else "vivo"
    )

    with open(informe_path, "w", encoding="utf-8") as f:
        f.write(informe)

    print(f"Informe escrito en {informe_path}")
    print(f"Filas evaluadas: {len(evaluacion['resultados'])} de {len(rows)}")
    print(f"Filas fallidas: {len(evaluacion['fallos'])}")
    for f_ in evaluacion["fallos"]:
        print(f"  - {f_['id']}: {f_['error']}")

    if evaluacion["fallos"]:
        return EXIT_FILAS_FALLIDAS
    if items_bajo_umbral:
        return EXIT_DEBAJO_UMBRAL
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
