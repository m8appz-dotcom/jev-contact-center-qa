#!/usr/bin/env python
"""Mide cuánto coincide Jev con las etiquetas humanas en español.

Evalúa las interacciones sintéticas de `data/eval/sinteticas.csv` con una
petición por interacción y compara el resultado, ítem por ítem, con la
etiqueta que pusimos a mano. Escribe `data/eval/informe.md`.

    python scripts/eval_jev.py --fake     # sin red, sin coste
    python scripts/eval_jev.py            # en vivo, con TYPESAFE_API_KEY

El objetivo es decidir antes de construir nada más: si algún ítem baja del
85 % de acuerdo, hay que reformularlo, traducirlo o quitarlo.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import os
import sys
from typing import Iterable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jevqa.jev_client import ErrorJev, FakeJev, JevClient, coste_usd  # noqa: E402
from jevqa.rubric import (  # noqa: E402
    ErrorRubrica,
    build_request,
    load_rubric,
    parse_response,
)

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUBRICA = os.path.join(RAIZ, "rubrics", "soporte_es.json")
DATOS = os.path.join(RAIZ, "data", "eval", "sinteticas.csv")
INFORME = os.path.join(RAIZ, "data", "eval", "informe.md")

#: Un noul por encima de este valor se lee como "cumple".
UMBRAL = 0.5
#: Por debajo de esta confianza la respuesta no se considera firme.
UMBRAL_CONFIANZA = 0.7
#: Umbral de decisión del plan: por debajo, el ítem no sirve como está.
ACUERDO_MINIMO = 0.85

ETIQUETA_CUMPLE = "cumple"
ETIQUETA_NO = "no"


# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------

def metricas_item(
    observaciones: Iterable[tuple[bool, float, float]],
    *,
    umbral: float = UMBRAL,
    umbral_confianza: float = UMBRAL_CONFIANZA,
) -> dict:
    """Compara las respuestas de Jev con las etiquetas humanas de un ítem.

    Cada observación es `(humano_cumple, probabilidad, confianza)`. La clase
    positiva es el "no cumple", que es lo que le interesa a una auditoría:
    detectar la falla, no confirmar el acierto.

    Las razones que no están definidas valen `None` en lugar de cero: un ítem
    sin ningún "no cumple" no tiene precisión del 0 %, no tiene precisión.
    """
    observaciones = list(observaciones)
    total = len(observaciones)
    if total == 0:
        return {
            "n": 0,
            "acuerdos": 0,
            "acuerdo": None,
            "no_cumple_humano": 0,
            "no_cumple_jev": 0,
            "aciertos_no_cumple": 0,
            "precision_no_cumple": None,
            "exhaustividad_no_cumple": None,
            "n_confiables": 0,
            "acuerdo_confiables": None,
        }

    acuerdos = 0
    no_humano = no_jev = aciertos = 0
    confiables = acuerdos_confiables = 0

    for humano_cumple, probabilidad, confianza in observaciones:
        jev_cumple = probabilidad >= umbral
        coinciden = jev_cumple == humano_cumple
        acuerdos += coinciden
        no_humano += not humano_cumple
        no_jev += not jev_cumple
        aciertos += (not humano_cumple) and (not jev_cumple)
        if confianza >= umbral_confianza:
            confiables += 1
            acuerdos_confiables += coinciden

    return {
        "n": total,
        "acuerdos": acuerdos,
        "acuerdo": acuerdos / total,
        "no_cumple_humano": no_humano,
        "no_cumple_jev": no_jev,
        "aciertos_no_cumple": aciertos,
        "precision_no_cumple": (aciertos / no_jev) if no_jev else None,
        "exhaustividad_no_cumple": (aciertos / no_humano) if no_humano else None,
        "n_confiables": confiables,
        "acuerdo_confiables": (acuerdos_confiables / confiables) if confiables else None,
    }


def metricas_por_item(rubrica: dict, evaluaciones: list[dict], **opciones) -> dict:
    """Aplica `metricas_item` a cada ítem de la rúbrica."""
    return {
        item["id"]: metricas_item(
            (
                (
                    ev["etiquetas"][item["id"]],
                    ev["resultado"]["items"][item["id"]]["probabilidad"],
                    ev["resultado"]["items"][item["id"]]["confianza"],
                )
                for ev in evaluaciones
                if ev["resultado"] is not None and item["id"] in ev["etiquetas"]
            ),
            **opciones,
        )
        for item in rubrica["items"]
    }


def peores_desacuerdos(
    rubrica: dict, evaluaciones: list[dict], *, cuantos: int = 5, umbral: float = UMBRAL
) -> list[dict]:
    """Los desacuerdos en los que Jev estuvo más seguro de lo contrario."""
    desacuerdos = []
    for ev in evaluaciones:
        if ev["resultado"] is None:
            continue
        for item in rubrica["items"]:
            registro = ev["resultado"]["items"][item["id"]]
            humano_cumple = ev["etiquetas"].get(item["id"])
            if humano_cumple is None:
                continue
            if (registro["probabilidad"] >= umbral) == humano_cumple:
                continue
            desacuerdos.append(
                {
                    "id": ev["id"],
                    "item": item["id"],
                    "humano": ETIQUETA_CUMPLE if humano_cumple else ETIQUETA_NO,
                    "jev": ETIQUETA_CUMPLE if registro["probabilidad"] >= umbral else ETIQUETA_NO,
                    "probabilidad": registro["probabilidad"],
                    "confianza": registro["confianza"],
                    "ambiguo": ev["fila"].get("ambiguo") == "si",
                    "texto": ev["fila"].get("texto", ""),
                    "notas": ev["fila"].get("notas", ""),
                }
            )
    desacuerdos.sort(key=lambda d: d["confianza"], reverse=True)
    return desacuerdos[:cuantos]


# ---------------------------------------------------------------------------
# Ejecución
# ---------------------------------------------------------------------------

def cargar_interacciones(ruta: str, rubrica: dict) -> list[dict]:
    with open(ruta, encoding="utf-8", newline="") as archivo:
        filas = list(csv.DictReader(archivo))
    if not filas:
        raise SystemExit(f"{ruta} no tiene ninguna fila")

    faltan = {"id", "texto"} - set(filas[0])
    if faltan:
        raise SystemExit(f"{ruta}: faltan las columnas {', '.join(sorted(faltan))}")

    ids_item = [item["id"] for item in rubrica["items"]]
    sin_etiqueta = [qid for qid in ids_item if qid not in filas[0]]
    if sin_etiqueta:
        raise SystemExit(
            f"{ruta}: faltan las columnas de etiqueta {', '.join(sin_etiqueta)}"
        )
    return filas


def evaluar(rubrica: dict, filas: list[dict], cliente) -> list[dict]:
    """Una petición por interacción. Un fallo se registra y el lote sigue."""
    evaluaciones = []
    for posicion, fila in enumerate(filas, start=1):
        etiquetas = {
            item["id"]: fila[item["id"]].strip().lower() == ETIQUETA_CUMPLE
            for item in rubrica["items"]
            if fila.get(item["id"])
        }
        registro = {
            "id": fila["id"],
            "fila": fila,
            "etiquetas": etiquetas,
            "resultado": None,
            "error": None,
        }
        try:
            respuesta = cliente.evaluar(build_request(rubrica, fila["texto"]))
            registro["resultado"] = parse_response(rubrica, respuesta)
        except (ErrorJev, ErrorRubrica) as exc:
            registro["error"] = f"{type(exc).__name__}: {exc}"
            print(f"  [{posicion}/{len(filas)}] {fila['id']}: {registro['error']}", file=sys.stderr)
        else:
            print(f"  [{posicion}/{len(filas)}] {fila['id']}: ok")
        evaluaciones.append(registro)
    return evaluaciones


def uso_total(evaluaciones: list[dict]) -> dict:
    entrada = sum(
        ev["resultado"]["uso"]["tokens_entrada"]
        for ev in evaluaciones
        if ev["resultado"] is not None
    )
    salida = sum(
        ev["resultado"]["uso"]["tokens_salida"]
        for ev in evaluaciones
        if ev["resultado"] is not None
    )
    return {
        "tokens_entrada": entrada,
        "tokens_salida": salida,
        "coste_usd": coste_usd(entrada),
    }


# ---------------------------------------------------------------------------
# Informe
# ---------------------------------------------------------------------------

def _pct(valor: float | None) -> str:
    return "—" if valor is None else f"{valor * 100:.1f} %"


def _recorte(texto: str, limite: int = 260) -> str:
    plano = " ".join(texto.split())
    return plano if len(plano) <= limite else plano[: limite - 1] + "…"


def escribir_informe(
    ruta: str,
    rubrica: dict,
    evaluaciones: list[dict],
    metricas: dict,
    *,
    modo: str,
    umbral: float,
    umbral_confianza: float,
) -> list[str]:
    """Escribe el informe y devuelve los ítems que no llegan al mínimo."""
    correctas = [ev for ev in evaluaciones if ev["resultado"] is not None]
    fallidas = [ev for ev in evaluaciones if ev["resultado"] is None]
    uso = uso_total(evaluaciones)
    bajo_minimo = [
        qid
        for qid, m in metricas.items()
        if m["acuerdo"] is not None and m["acuerdo"] < ACUERDO_MINIMO
    ]

    lineas = [
        "# ¿Funciona Jev en español? — informe de la fase 2",
        "",
        f"- Fecha: {datetime.date.today().isoformat()}",
        f"- Modo: **{modo}**",
        f"- Rúbrica: `{rubrica['id']}` v{rubrica['version']} ({len(rubrica['items'])} ítems)",
        f"- Interacciones evaluadas: **{len(correctas)}** de {len(evaluaciones)}",
        f"- Umbral de cumplimiento: noul ≥ {umbral} · umbral de confianza: {umbral_confianza}",
        f"- Tokens de entrada: {uso['tokens_entrada']:,} · de salida: {uso['tokens_salida']:,}",
        f"- Coste: ${uso['coste_usd']:.6f}",
        "",
    ]

    if modo == "fake":
        lineas += [
            "> **Este informe no mide nada.** Está generado con `FakeJev`, que inventa",
            "> números deterministas a partir del texto. Sirve para comprobar que el",
            "> evaluador corre de punta a punta; las cifras de acuerdo son ruido.",
            "",
        ]

    lineas += [
        "## Acuerdo por ítem",
        "",
        "La clase positiva es el **no cumple**: lo que una auditoría necesita detectar.",
        "",
        "| Ítem | Crítico | n | Acuerdo | Precisión «no» | Exhaustividad «no» | «no» humano | «no» Jev | n conf. ≥ umbral | Acuerdo conf. |",
        "| --- | :-: | --: | --: | --: | --: | --: | --: | --: | --: |",
    ]
    for item in rubrica["items"]:
        m = metricas[item["id"]]
        lineas.append(
            "| `{id}` | {critico} | {n} | {acuerdo} | {prec} | {exh} | {nh} | {nj} | {nc} | {ac} |".format(
                id=item["id"],
                critico="sí" if item["critico"] else "",
                n=m["n"],
                acuerdo=_pct(m["acuerdo"]),
                prec=_pct(m["precision_no_cumple"]),
                exh=_pct(m["exhaustividad_no_cumple"]),
                nh=m["no_cumple_humano"],
                nj=m["no_cumple_jev"],
                nc=m["n_confiables"],
                ac=_pct(m["acuerdo_confiables"]),
            )
        )

    lineas += ["", "## Punto de decisión", ""]
    if bajo_minimo:
        lineas += [
            f"**{len(bajo_minimo)} ítem(s) por debajo del {ACUERDO_MINIMO:.0%} de acuerdo:** "
            + ", ".join(f"`{qid}`" for qid in bajo_minimo),
            "",
            "Opciones, según el plan: reformular el ítem en inglés, traducir el texto",
            "antes de enviarlo, o quitar el ítem de la rúbrica.",
        ]
    else:
        lineas.append(
            f"Todos los ítems llegan al {ACUERDO_MINIMO:.0%} de acuerdo. Se puede seguir."
        )

    lineas += ["", "## Los 5 peores desacuerdos", ""]
    peores = peores_desacuerdos(rubrica, evaluaciones, umbral=umbral)
    if not peores:
        lineas.append("No hubo desacuerdos.")
    for numero, d in enumerate(peores, start=1):
        lineas += [
            f"### {numero}. `{d['item']}` en {d['id']}"
            + (" · marcada como ambigua" if d["ambiguo"] else ""),
            "",
            f"- Humano: **{d['humano']}** · Jev: **{d['jev']}** "
            f"(noul {d['probabilidad']:.2f}, confianza {d['confianza']:.2f})",
            f"- Nota de la etiqueta: {d['notas']}" if d["notas"] else "",
            "",
            f"> {_recorte(d['texto'])}",
            "",
        ]

    if fallidas:
        lineas += ["## Interacciones que fallaron", ""]
        for ev in fallidas:
            lineas.append(f"- `{ev['id']}`: {ev['error']}")
        lineas.append("")

    lineas += [
        "## Límites conocidos",
        "",
        "- Los textos los escribimos nosotros, así que sobreestiman el acierto: no",
        "  tienen los cortes, muletillas ni errores de una transcripción real. La",
        "  validación de verdad es el piloto de la fase 6.",
        "- Las etiquetas humanas son de un solo anotador, sin segunda opinión.",
        "- El «no cumple» es minoritario en casi todos los ítems, así que la",
        "  exhaustividad se calcula sobre pocos casos y se mueve mucho.",
        "- El acuerdo depende del umbral de 0,5; un ítem puede mejorar solo con",
        "  moverlo. La fase 5 fija los umbrales definitivos a partir de aquí.",
        "",
    ]

    with open(ruta, "w", encoding="utf-8", newline="\n") as archivo:
        archivo.write("\n".join(linea for linea in lineas if linea is not None) + "\n")
    return bajo_minimo


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fake", action="store_true", help="usa FakeJev, sin red ni coste")
    parser.add_argument("--rubrica", default=RUBRICA)
    parser.add_argument("--datos", default=DATOS)
    parser.add_argument("--salida", default=INFORME)
    parser.add_argument("--umbral", type=float, default=UMBRAL)
    parser.add_argument("--umbral-confianza", type=float, default=UMBRAL_CONFIANZA)
    parser.add_argument("--limite", type=int, default=0, help="evalúa solo las primeras N filas")
    args = parser.parse_args(argv)

    rubrica = load_rubric(args.rubrica)
    filas = cargar_interacciones(args.datos, rubrica)
    if args.limite:
        filas = filas[: args.limite]

    if args.fake:
        cliente, modo = FakeJev(), "fake"
    else:
        cliente, modo = JevClient(), "en vivo"
        if not cliente.clave:
            print(
                "falta TYPESAFE_API_KEY en el entorno; para probar sin red usa --fake",
                file=sys.stderr,
            )
            return 2

    print(f"Evaluando {len(filas)} interacciones en modo {modo}...")
    evaluaciones = evaluar(rubrica, filas, cliente)
    metricas = metricas_por_item(
        rubrica,
        evaluaciones,
        umbral=args.umbral,
        umbral_confianza=args.umbral_confianza,
    )
    bajo_minimo = escribir_informe(
        args.salida,
        rubrica,
        evaluaciones,
        metricas,
        modo=modo,
        umbral=args.umbral,
        umbral_confianza=args.umbral_confianza,
    )

    uso = uso_total(evaluaciones)
    correctas = sum(1 for ev in evaluaciones if ev["resultado"] is not None)
    print(f"\n{correctas}/{len(evaluaciones)} interacciones evaluadas.")
    print(f"Tokens de entrada: {uso['tokens_entrada']:,} · coste ${uso['coste_usd']:.6f}")
    print(f"Informe: {args.salida}")
    if bajo_minimo and modo != "fake":
        print(
            "\nPUNTO DE DECISIÓN: por debajo del "
            f"{ACUERDO_MINIMO:.0%} de acuerdo: {', '.join(bajo_minimo)}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
