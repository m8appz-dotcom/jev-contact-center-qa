"""Informe semanal: un HTML por campaña a partir del CSV de resultados.

Lee lo que deja `python -m jevqa auditar`, califica cada interacción con
`jevqa.scoring` y escribe, por campaña, cuatro secciones: ranking de agentes,
peores interacciones, cola de revisión y coste de Jev del periodo.

Todo lo que viene del CSV se escapa antes de entrar al HTML. Los nombres de
agente, las campañas y los mensajes de error los escribe un sistema ajeno o
una persona, y un `<script>` en cualquiera de ellos no puede ejecutarse en el
navegador de quien abre el informe.
"""

from __future__ import annotations

import csv
import datetime
import html
import os
import re
import unicodedata

from jevqa.jev_client import coste_usd
from jevqa.scoring import (
    ESTADO_SUSPENSO,
    SIN_CAMPANA,
    ErrorScoring,
    agregar,
    calificar,
    cola_de_revision,
    resolver_umbrales,
)

ESTADO_OK = "ok"

#: Cuántas interacciones enseña la sección de peores interacciones.
PEORES = 10


class ErrorResultados(Exception):
    """El CSV de resultados no existe o no tiene la forma que deja `auditar`."""


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------

def _numero(valor: str | None) -> float:
    return float(valor) if valor not in (None, "") else 0.0


def _resultado_desde_fila(fila: dict, rubrica: dict) -> dict:
    """Rehace, desde las columnas del CSV, lo que `calificar` necesita."""
    items = {}
    for item in rubrica["items"]:
        items[item["id"]] = {
            "probabilidad": float(fila[f"{item['id']}_prob"]),
            "confianza": float(fila[f"{item['id']}_conf"]),
        }
    return {
        "rubrica": rubrica["id"],
        "version_rubrica": rubrica["version"],
        "items": items,
        "riesgo": {
            "nivel": fila.get("riesgo_nivel", ""),
            "etiqueta": fila.get("riesgo_etiqueta", ""),
        },
        "motivo": {"valor": fila.get("motivo", "")},
    }


def leer_resultados(
    ruta: str,
    rubrica: dict,
    *,
    desde: str | None = None,
    hasta: str | None = None,
    umbrales: dict | None = None,
) -> dict:
    """Lee el CSV de `auditar` y califica cada interacción auditada.

    Devuelve las calificaciones y, aparte, las filas que no se pudieron
    calificar (error de Jev, demasiado larga, columnas vacías), porque también
    son parte de lo que se entrega: una interacción sin auditar no puede
    desaparecer del informe en silencio.

    `desde` y `hasta` filtran por la columna fecha (AAAA-MM-DD, inclusivos).
    """
    if not os.path.exists(ruta):
        raise ErrorResultados(f"no existe el archivo de resultados {ruta}")
    umbrales = umbrales if umbrales is not None else resolver_umbrales(rubrica)

    with open(ruta, encoding="utf-8-sig", newline="") as archivo:
        lector = csv.DictReader(archivo)
        if lector.fieldnames is None:
            raise ErrorResultados(f"{ruta} está vacío")
        faltan = [
            columna
            for columna in ("id", "agente", "campaña", "fecha", "estado")
            if columna not in lector.fieldnames
        ]
        if faltan:
            raise ErrorResultados(
                f"{ruta} no parece una salida de `auditar`: faltan {', '.join(faltan)}"
            )
        filas = list(lector)

    calificaciones: list[dict] = []
    sin_calificar: list[dict] = []
    for fila in filas:
        fecha = (fila.get("fecha") or "").strip()
        if desde and fecha < desde:
            continue
        if hasta and fecha > hasta:
            continue

        if fila.get("estado") != ESTADO_OK:
            sin_calificar.append(_sin_calificar(fila, fila.get("error") or fila.get("estado", "")))
            continue
        try:
            tokens = int(_numero(fila.get("tokens_entrada")))
            calificacion = calificar(
                rubrica,
                _resultado_desde_fila(fila, rubrica),
                meta=fila,
                umbrales=umbrales,
            )
        except (KeyError, ValueError, ErrorScoring) as exc:
            sin_calificar.append(_sin_calificar(fila, f"no se pudo calificar: {exc}"))
            continue
        calificacion["tokens_entrada"] = tokens
        calificacion["coste_usd"] = _numero(fila.get("coste_usd")) or coste_usd(tokens)
        calificaciones.append(calificacion)

    return {"calificaciones": calificaciones, "sin_calificar": sin_calificar}


def _sin_calificar(fila: dict, motivo: str) -> dict:
    return {
        "id": (fila.get("id") or "").strip(),
        "agente": (fila.get("agente") or "").strip(),
        "campaña": (fila.get("campaña") or "").strip() or SIN_CAMPANA,
        "fecha": (fila.get("fecha") or "").strip(),
        "estado": fila.get("estado", ""),
        "motivo": motivo,
    }


# ---------------------------------------------------------------------------
# Datos del informe
# ---------------------------------------------------------------------------

def por_campana(leido: dict) -> dict[str, dict]:
    """Reparte calificaciones y filas sin calificar por campaña."""
    campanas: dict[str, dict] = {}

    def cubo(nombre: str) -> dict:
        return campanas.setdefault(nombre, {"calificaciones": [], "sin_calificar": []})

    for calificacion in leido["calificaciones"]:
        cubo(calificacion.get("campaña") or SIN_CAMPANA)["calificaciones"].append(calificacion)
    for fila in leido["sin_calificar"]:
        cubo(fila["campaña"])["sin_calificar"].append(fila)
    return dict(sorted(campanas.items()))


def ranking_de_agentes(calificaciones: list[dict]) -> dict:
    """Mejor nota primero, pero solo entre quien tiene muestra suficiente.

    Un agente con una sola llamada auditada no encabeza el ranking con un 100:
    va aparte, en su propia tabla, hasta que tenga interacciones suficientes.
    """
    agentes = agregar(calificaciones)["agentes"]
    orden = lambda g: (-g["nota_media"], g["porcentaje_criticas"], g["clave"])  # noqa: E731
    return {
        "con_muestra": sorted((g for g in agentes if g["muestra_suficiente"]), key=orden),
        "sin_muestra": sorted((g for g in agentes if not g["muestra_suficiente"]), key=orden),
    }


def peores_interacciones(calificaciones: list[dict], cuantas: int = PEORES) -> list[dict]:
    """Suspensos con críticas primero, después la nota más baja."""
    return sorted(
        calificaciones,
        key=lambda c: (
            not c["criticas_falladas"],
            c["estado"] != ESTADO_SUSPENSO,
            c["nota"],
            c["id"],
        ),
    )[:cuantas]


def coste_del_periodo(calificaciones: list[dict], sin_calificar: list[dict]) -> dict:
    tokens = sum(c.get("tokens_entrada", 0) for c in calificaciones)
    coste = sum(c.get("coste_usd", 0.0) for c in calificaciones)
    auditadas = len(calificaciones)
    return {
        "auditadas": auditadas,
        "sin_calificar": len(sin_calificar),
        "tokens_entrada": tokens,
        "coste_usd": coste,
        "coste_por_mil": (coste / auditadas * 1000) if auditadas else 0.0,
    }


def periodo(calificaciones: list[dict], sin_calificar: list[dict], desde=None, hasta=None) -> tuple[str, str]:
    fechas = sorted(
        f for f in (r.get("fecha", "") for r in [*calificaciones, *sin_calificar]) if f
    )
    inicio = desde or (fechas[0] if fechas else "")
    fin = hasta or (fechas[-1] if fechas else "")
    return inicio, fin


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def _e(valor) -> str:
    """Escapa cualquier valor para meterlo en HTML, comillas incluidas."""
    return html.escape("" if valor is None else str(valor), quote=True)


def _num(valor: float, decimales: int = 1) -> str:
    """Número con coma decimal, como se lee en Ecuador."""
    return f"{valor:,.{decimales}f}".replace(",", " ").replace(".", ",").replace(" ", ".")


def _pct(valor: float) -> str:
    return f"{_num(valor)} %"


def _tabla(cabeceras: list[str], filas: list[list[str]], vacio: str) -> str:
    if not filas:
        return f'<p class="vacio">{_e(vacio)}</p>'
    cabeza = "".join(f"<th>{_e(c)}</th>" for c in cabeceras)
    # Las celdas llegan ya escapadas: aquí solo se ensamblan.
    cuerpo = "".join("<tr>" + "".join(f"<td>{celda}</td>" for celda in fila) + "</tr>" for fila in filas)
    return f'<div class="tabla"><table><thead><tr>{cabeza}</tr></thead><tbody>{cuerpo}</tbody></table></div>'


def _filas_ranking(grupos: list[dict], con_posicion: bool) -> list[list[str]]:
    filas = []
    for posicion, grupo in enumerate(grupos, start=1):
        filas.append(
            ([str(posicion)] if con_posicion else [])
            + [
                _e(grupo["clave"] or "(sin agente)"),
                str(grupo["interacciones"]),
                _num(grupo["nota_media"]),
                _pct(grupo["porcentaje_criticas"]),
                _pct(grupo["porcentaje_suspensos"]),
                str(grupo["cola"]),
            ]
        )
    return filas


def _estado(calificacion: dict) -> str:
    clase = "mal" if calificacion["estado"] == ESTADO_SUSPENSO else "bien"
    return f'<span class="estado {clase}">{_e(calificacion["estado"])}</span>'


def html_campana(
    campana: str,
    datos: dict,
    rubrica: dict,
    umbrales: dict,
    *,
    desde: str | None = None,
    hasta: str | None = None,
    note: str = "",
) -> str:
    calificaciones = datos["calificaciones"]
    sin_calificar = datos["sin_calificar"]
    total = agregar(calificaciones)["total"]
    ranking = ranking_de_agentes(calificaciones)
    cola = cola_de_revision(calificaciones)
    coste = coste_del_periodo(calificaciones, sin_calificar)
    inicio, fin = periodo(calificaciones, sin_calificar, desde, hasta)

    if rubrica.get("idioma") == "en":
        from jevqa.report_en import render_campaign

        return render_campaign(
            campana, rubrica, umbrales, calificaciones, sin_calificar,
            total, ranking, cola, coste, inicio, fin, note,
        )

    cabeceras_ranking = ["Agente", "Interacciones", "Nota media", "Con crítica fallada", "Suspensos", "En cola"]
    secciones = []

    secciones.append(
        '<section><h2>Ranking de agentes</h2>'
        + "<p>Mejor nota primero. La columna de críticas es la que manda: una nota alta "
        "con una crítica fallada no es un buen trabajo.</p>"
        + _tabla(["#"] + cabeceras_ranking, _filas_ranking(ranking["con_muestra"], True),
                 "Ningún agente tiene todavía interacciones suficientes para el ranking.")
        + (
            "<h3>Con muestra insuficiente</h3><p>Menos de 5 interacciones auditadas: su "
            "promedio todavía es una anécdota y no entra en el ranking.</p>"
            + _tabla(cabeceras_ranking, _filas_ranking(ranking["sin_muestra"], False), "")
            if ranking["sin_muestra"]
            else ""
        )
        + "</section>"
    )

    peores = peores_interacciones(calificaciones)
    secciones.append(
        "<section><h2>Peores interacciones</h2>"
        + "<p>Las que fallaron una crítica van primero; después, la nota más baja.</p>"
        + _tabla(
            ["Interacción", "Agente", "Fecha", "Nota", "Estado", "Críticas falladas", "Riesgo", "Motivo"],
            [
                [
                    _e(c["id"]),
                    _e(c["agente"]),
                    _e(c["fecha"]),
                    _num(c["nota"]),
                    _estado(c),
                    _e(", ".join(c["criticas_falladas"]) or "—"),
                    _e((c.get("riesgo") or {}).get("etiqueta", "")),
                    _e((c.get("motivo") or {}).get("valor", "")),
                ]
                for c in peores
            ],
            "No hay interacciones auditadas en este periodo.",
        )
        + "</section>"
    )

    secciones.append(
        f"<section><h2>Cola de revisión ({len(cola)})</h2>"
        + "<p>Lo que el modelo no vio claro. Se revisa en este orden: primero las que "
        "fallaron una crítica, después las de peor nota.</p>"
        + _tabla(
            ["Interacción", "Agente", "Nota", "Estado", "Ítems a revisar", "Motivo"],
            [
                [
                    _e(c["id"]),
                    _e(c["agente"]),
                    _num(c["nota"]),
                    _estado(c),
                    _e(", ".join(c["items_a_revisar"])),
                    _e(", ".join(m.replace("_", " ") for m in c["motivos_revision"])),
                ]
                for c in cola
            ],
            "La cola está vacía.",
        )
        + "</section>"
    )

    secciones.append(
        "<section><h2>Coste de Jev del periodo</h2>"
        + _tabla(
            ["Concepto", "Valor"],
            [
                ["Interacciones auditadas", str(coste["auditadas"])],
                ["Sin auditar (error o demasiado largas)", str(coste["sin_calificar"])],
                ["Tokens de entrada", _num(coste["tokens_entrada"], 0)],
                ["Coste", f"US$ {_num(coste['coste_usd'], 6)}"],
                ["Coste por 1.000 interacciones", f"US$ {_num(coste['coste_por_mil'], 4)}"],
            ],
            "",
        )
        + "<p>Jev cobra solo los tokens de entrada (US$ 42 por cada mil millones).</p>"
        + "</section>"
    )

    if sin_calificar:
        secciones.append(
            "<section><h2>Interacciones sin auditar</h2>"
            + _tabla(
                ["Interacción", "Agente", "Fecha", "Estado", "Motivo"],
                [[_e(f["id"]), _e(f["agente"]), _e(f["fecha"]), _e(f["estado"]), _e(f["motivo"])] for f in sin_calificar],
                "",
            )
            + "</section>"
        )

    resumen = (
        f'<dl class="resumen">'
        f"<div><dt>Interacciones</dt><dd>{total['interacciones']}</dd></div>"
        f"<div><dt>Nota media</dt><dd>{_num(total['nota_media'])}</dd></div>"
        f"<div><dt>Con crítica fallada</dt><dd>{_pct(total['porcentaje_criticas'])}</dd></div>"
        f"<div><dt>Suspensos</dt><dd>{_pct(total['porcentaje_suspensos'])}</dd></div>"
        f"<div><dt>En cola de revisión</dt><dd>{_pct(total['porcentaje_cola'])}</dd></div>"
        f"</dl>"
    )

    generado = datetime.date.today().isoformat()
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Calidad · {_e(campana)}</title>
<style>{CSS}</style>
</head>
<body>
<main>
<header>
<p class="sobre">Auditoría de calidad con Jev</p>
<h1>{_e(campana)}</h1>
<p class="meta">Periodo {_e(inicio or "—")} a {_e(fin or "—")} · rúbrica {_e(rubrica["id"])} v{_e(rubrica["version"])} · aprueba con {_num(umbrales["aprobado"], 0)} y sin críticas falladas · generado {_e(generado)}</p>
{f'<p class="meta">{_e(note)}</p>' if note else ''}
</header>
{resumen}
{"".join(secciones)}
<footer>Las notas las pone un modelo. La cola de revisión existe para que una persona mire lo que el modelo no vio claro; ninguna decisión sobre un agente debería tomarse solo con este informe.</footer>
</main>
</body>
</html>
"""


CSS = """
:root{--fondo:#fbfaf7;--texto:#1d1d1b;--suave:#6b6a64;--linea:#e4e1d8;--caja:#fff;--bien:#2f6f4f;--mal:#a3362a;--acento:#35527a}
@media (prefers-color-scheme:dark){:root{--fondo:#17181a;--texto:#ecebe6;--suave:#a19f97;--linea:#33342f;--caja:#1f2023;--bien:#7cc49c;--mal:#ef8a7c;--acento:#9db8e0}}
*{box-sizing:border-box}
body{margin:0;background:var(--fondo);color:var(--texto);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1040px;margin:0 auto;padding:32px 16px 48px}
h1{font-size:28px;margin:0 0 4px}
h2{font-size:19px;margin:36px 0 8px;padding-top:16px;border-top:1px solid var(--linea)}
h3{font-size:15px;margin:20px 0 6px}
.sobre{margin:0;color:var(--acento);font-size:13px;font-weight:600;letter-spacing:.04em;text-transform:uppercase}
.meta,.vacio,footer,section>p{color:var(--suave)}
.resumen{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:24px 0 0}
.resumen div{background:var(--caja);border:1px solid var(--linea);border-radius:8px;padding:12px 14px}
.resumen dt{color:var(--suave);font-size:13px}
.resumen dd{margin:2px 0 0;font-size:22px;font-weight:600;font-variant-numeric:tabular-nums}
.tabla{overflow-x:auto;border:1px solid var(--linea);border-radius:8px;background:var(--caja)}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:8px 10px;text-align:left;border-bottom:1px solid var(--linea);white-space:nowrap}
th{font-size:13px;color:var(--suave);font-weight:600}
tr:last-child td{border-bottom:0}
.estado{font-weight:600}.estado.bien{color:var(--bien)}.estado.mal{color:var(--mal)}
footer{margin-top:40px;font-size:13px}
"""


# ---------------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------------

def nombre_de_archivo(campana: str) -> str:
    """Un nombre de archivo seguro para cualquier nombre de campaña."""
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFKD", campana) if not unicodedata.combining(c)
    )
    plano = re.sub(r"[^A-Za-z0-9_-]+", "_", sin_tildes.strip()).strip("_")
    return f"informe_{plano or 'sin_campana'}.html"


def generar_informes(
    resultados: str,
    carpeta: str,
    rubrica: dict,
    *,
    desde: str | None = None,
    hasta: str | None = None,
    note: str = "",
) -> list[str]:
    """Escribe un HTML por campaña en `carpeta` y devuelve sus rutas."""
    umbrales = resolver_umbrales(rubrica)
    leido = leer_resultados(resultados, rubrica, desde=desde, hasta=hasta, umbrales=umbrales)
    os.makedirs(carpeta, exist_ok=True)

    rutas = []
    usados: set[str] = set()
    for campana, datos in por_campana(leido).items():
        nombre = nombre_de_archivo(campana)
        base, extension = os.path.splitext(nombre)
        contador = 2
        while nombre in usados:  # dos campañas que se aplanan al mismo nombre
            nombre = f"{base}_{contador}{extension}"
            contador += 1
        usados.add(nombre)

        ruta = os.path.join(carpeta, nombre)
        with open(ruta, "w", encoding="utf-8", newline="\n") as archivo:
            archivo.write(html_campana(campana, datos, rubrica, umbrales, desde=desde, hasta=hasta, note=note))
        rutas.append(ruta)
    return rutas
