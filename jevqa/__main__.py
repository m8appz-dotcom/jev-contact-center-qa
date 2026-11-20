"""CLI de jevqa.

    python -m jevqa auditar <entrada.csv> [--salida <salida.csv>] [--fake]
    python -m jevqa comparar <humano.csv> <resultados.csv> [--salida <archivo.md>]
    python -m jevqa informe <resultados.csv> [--salida-dir <dir>] [--coste-por-llamada <usd>]

Códigos de salida:
    0 = comando completado sin errores (para `auditar`: además, sin filas en
        estado `error`).
    2 = entrada inválida (columnas faltantes, CSV vacío, id vacío o repetido,
        `InformeError`, `ComparacionError` o `RubricError`).
    3 = error de autenticación con Jev: se abortó el lote (conserva lo escrito).
    4 = el lote terminó pero una o más filas quedaron en estado `error`.
    5 = la salida existente tiene una cabecera distinta a la esperada.
"""

from __future__ import annotations

import argparse
import os
import sys

from jevqa import compare
from jevqa import pipeline
from jevqa import report
from jevqa import rubric as rubric_mod
from jevqa.jev_client import FakeJev, JevAuthError, JevClient

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
RUBRIC_PATH = os.path.join(REPO_ROOT, "rubrics", "soporte_es.json")

EXIT_OK = 0
EXIT_ENTRADA_INVALIDA = 2
EXIT_AUTH_ERROR = 3
EXIT_FILAS_CON_ERROR = 4
EXIT_SALIDA_INVALIDA = 5


def _salida_por_defecto(entrada: str) -> str:
    raiz, _ext = os.path.splitext(entrada)
    return f"{raiz}.auditado.csv"


def _comparacion_por_defecto(resultados: str) -> str:
    return f"{resultados}.comparacion.md"


def _informes_por_defecto(resultados: str) -> str:
    raiz, _ext = os.path.splitext(resultados)
    return f"{raiz}_informes"


def _fake_response_por_defecto(rubric: dict) -> dict:
    """Respuesta cruda determinista y válida para la rúbrica, sin red ni azar."""
    answers = {}
    for item in rubric["items"]:
        answers[item["id"]] = {"type": "noul", "noul": 0.9}
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
    return {"model": "fake-jev", "answers": answers}


def _auditar(entrada: str, salida: str | None, fake: bool) -> int:
    rubric = rubric_mod.load_rubric(RUBRIC_PATH)
    salida = salida or _salida_por_defecto(entrada)
    cliente = (
        FakeJev(default_response=_fake_response_por_defecto(rubric)) if fake else JevClient()
    )

    try:
        resumen = pipeline.auditar(entrada, salida, cliente, rubric)
    except pipeline.EntradaInvalidaError as exc:
        print(f"Entrada inválida: {exc}", file=sys.stderr)
        return EXIT_ENTRADA_INVALIDA
    except pipeline.SalidaInvalidaError as exc:
        print(f"Salida inválida: {exc}", file=sys.stderr)
        return EXIT_SALIDA_INVALIDA
    except JevAuthError as exc:
        print(f"Error de autenticación con Jev: {exc}", file=sys.stderr)
        return EXIT_AUTH_ERROR

    print(
        f"ok={resumen['ok']} error={resumen['error']} "
        f"demasiado_larga={resumen['demasiado_larga']} saltadas={resumen['saltadas']} "
        f"llamadas={resumen['llamadas']} -> {salida}"
    )
    return EXIT_FILAS_CON_ERROR if resumen["error"] > 0 else EXIT_OK


def _comparar(humano: str, resultados: str, salida: str | None) -> int:
    salida = salida or _comparacion_por_defecto(resultados)
    try:
        resultado = compare.comparar(humano, resultados)
    except compare.ComparacionError as exc:
        print(f"Error de comparación: {exc}", file=sys.stderr)
        return EXIT_ENTRADA_INVALIDA

    try:
        with open(salida, "w", encoding="utf-8") as f:
            f.write(compare.render_comparacion(resultado))
    except OSError as exc:
        print(f"No se puede escribir {salida}: {exc}", file=sys.stderr)
        return EXIT_ENTRADA_INVALIDA

    for item in resultado["items"]:
        r = resultado["por_item"][item]
        kappa_txt = f"{r['kappa']:.4f}" if r["kappa"] is not None else "indefinido"
        print(f"{item}: acuerdo={r['acuerdo']:.1%} kappa={kappa_txt}")
    print(f"n={resultado['n']} -> {salida}")
    return EXIT_OK


def _informe(entrada: str, salida_dir: str | None, coste_por_llamada: float | None) -> int:
    salida_dir = salida_dir or _informes_por_defecto(entrada)
    kwargs = {} if coste_por_llamada is None else {"coste_por_llamada": coste_por_llamada}
    try:
        rubric = rubric_mod.load_rubric(RUBRIC_PATH)
        rutas = report.generar_informes(rubric, entrada, salida_dir, **kwargs)
    except (report.InformeError, rubric_mod.RubricError) as exc:
        print(f"Error de informe: {exc}", file=sys.stderr)
        return EXIT_ENTRADA_INVALIDA

    for ruta in rutas:
        print(ruta)
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]

    parser = argparse.ArgumentParser(prog="jevqa")
    subparsers = parser.add_subparsers(dest="comando", required=True)

    auditar_parser = subparsers.add_parser(
        "auditar", help="Audita un CSV de interacciones por lotes."
    )
    auditar_parser.add_argument("entrada")
    auditar_parser.add_argument("--salida", default=None)
    auditar_parser.add_argument("--fake", action="store_true")

    comparar_parser = subparsers.add_parser(
        "comparar", help="Compara resultados de Jev contra una auditoría humana."
    )
    comparar_parser.add_argument("humano")
    comparar_parser.add_argument("resultados")
    comparar_parser.add_argument("--salida", default=None)

    informe_parser = subparsers.add_parser(
        "informe", help="Genera un informe HTML por campaña a partir de resultados auditados."
    )
    informe_parser.add_argument("entrada")
    informe_parser.add_argument("--salida-dir", default=None)
    informe_parser.add_argument("--coste-por-llamada", type=float, default=None)

    args = parser.parse_args(argv)

    if args.comando == "auditar":
        return _auditar(args.entrada, args.salida, args.fake)
    if args.comando == "comparar":
        return _comparar(args.humano, args.resultados, args.salida)
    if args.comando == "informe":
        return _informe(args.entrada, args.salida_dir, args.coste_por_llamada)
    return EXIT_ENTRADA_INVALIDA  # inalcanzable: argparse ya exige un subcomando válido.


if __name__ == "__main__":
    raise SystemExit(main())
