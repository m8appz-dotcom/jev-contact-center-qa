"""Punto de entrada de la CLI: `python -m jevqa`."""

from __future__ import annotations

import argparse
import os
import sys

from jevqa import __version__
from jevqa.jev_client import FakeJev, JevClient
from jevqa.pipeline import ErrorEntrada, Limitador, auditar, imprimir_resumen
from jevqa.rubric import ErrorRubrica, load_rubric

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUBRICA = os.path.join(RAIZ, "rubrics", "soporte_es.json")
CARPETA_SALIDAS = os.path.join(RAIZ, "salidas")


def _salida_por_defecto(entrada: str) -> str:
    nombre = os.path.splitext(os.path.basename(entrada))[0]
    return os.path.join(CARPETA_SALIDAS, f"{nombre}_resultados.csv")


def _cliente(args) -> object | None:
    """Devuelve el cliente a usar, o None si falta la clave en modo real."""
    if args.fake:
        return FakeJev()
    cliente = JevClient()
    if not cliente.clave:
        print(
            "falta TYPESAFE_API_KEY en el entorno; para probar sin red usa --fake",
            file=sys.stderr,
        )
        return None
    return cliente


def _comando_auditar(args) -> int:
    rubrica = load_rubric(args.rubrica)
    cliente = _cliente(args)
    if cliente is None:
        return 2

    salida = args.salida or _salida_por_defecto(args.entrada)
    resumen = auditar(
        args.entrada,
        salida,
        rubrica,
        cliente,
        concurrencia=args.concurrencia,
        limitador=Limitador(args.por_minuto),
    )
    imprimir_resumen(resumen, salida)
    return 0


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m jevqa",
        description="Auditoría de calidad de contact centers con Jev.",
    )
    parser.add_argument("--version", action="version", version=f"jevqa {__version__}")
    comandos = parser.add_subparsers(dest="comando", metavar="comando")

    auditar_cmd = comandos.add_parser(
        "auditar",
        help="audita un CSV de transcripciones y escribe un CSV de resultados",
        description=(
            "Anonimiza cada transcripción y la evalúa con una sola petición a Jev. "
            "Relanzar el mismo comando salta los ids que ya están en la salida, "
            "así que un lote interrumpido no se paga dos veces."
        ),
    )
    auditar_cmd.add_argument("entrada", help="CSV con id, agente, campaña, fecha y texto")
    auditar_cmd.add_argument("--salida", help="CSV de resultados (por defecto, en salidas/)")
    auditar_cmd.add_argument("--rubrica", default=RUBRICA)
    auditar_cmd.add_argument("--fake", action="store_true", help="usa FakeJev, sin red ni coste")
    auditar_cmd.add_argument("--concurrencia", type=int, default=8)
    auditar_cmd.add_argument(
        "--por-minuto",
        type=int,
        default=960,
        dest="por_minuto",
        help="tope de peticiones por minuto (el límite de la API es 1200)",
    )
    auditar_cmd.set_defaults(funcion=_comando_auditar)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = construir_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "funcion", None):
        parser.print_help()
        return 1
    try:
        return args.funcion(args)
    except (ErrorEntrada, ErrorRubrica) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
