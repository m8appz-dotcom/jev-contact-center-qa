"""Informe semanal por campaña a partir del CSV auditado (fase 6).

Lee el CSV de `jevqa.pipeline.auditar`, puntúa las filas con `jevqa.scoring`
y escribe un HTML por campaña con el ranking de agentes, las peores
interacciones, la cola de revisión y el coste estimado del periodo. No hace
llamadas a Jev ni conoce la CLI.
"""

from __future__ import annotations

import csv
import html
import math
import os
import re

from jevqa import scoring
from jevqa.pipeline import OUTPUT_HEADER_BASE

# 29.899 tokens de entrada facturados en las 40 llamadas de la corrida en
# vivo de la fase 2, a $0,042 por millón de tokens de entrada (la salida no
# se factura). Ver data/eval/informe.md. Overridable desde la CLI.
COSTE_POR_LLAMADA_USD = 29899 / 40 * 0.042 / 1_000_000


class InformeError(Exception):
    """El CSV de resultados no tiene el formato esperado para generar el informe."""


def _item_ids(rubric: dict) -> list:
    return [item["id"] for item in rubric["items"]]


def _slug(nombre) -> str:
    """Nombre de archivo seguro (sin separadores ni `..`) para `nombre`.

    Lleva el prefijo `informe_` para no chocar con nombres reservados de
    Windows (`CON`, `NUL`, ...).
    """
    texto = str(nombre) if nombre is not None else ""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", texto).strip("_")
    return f"informe_{slug or 'campana'}"


def _orden_agente(item) -> tuple:
    _, stats = item
    nota = stats["nota_media"]
    return (nota is None, -nota if nota is not None else 0.0)


def render_campaña(
    rubric: dict,
    campaña: str,
    filas: list,
    coste_por_llamada: float = COSTE_POR_LLAMADA_USD,
) -> str:
    """Construye el HTML del informe de una campaña. No hace I/O.

    Lanza `InformeError` si alguna fila no se puede puntuar (probabilidad
    ausente, no numérica o fuera de rango).
    """
    try:
        puntuadas, _sin_nota = scoring.puntuar_lote(rubric, filas)
        resumen_por_campaña = scoring.agregar(rubric, filas, "campaña")
        ranking = scoring.agregar(rubric, filas, "agente")
    except scoring.ScoringError as exc:
        raise InformeError(str(exc)) from exc

    resumen = resumen_por_campaña.get(
        campaña, {"n": 0, "sin_nota": 0, "nota_media": None, "pct_criticas": 0.0, "cola": 0}
    )
    fila_por_id = {f.get("id"): f for f in filas}

    partes = [
        "<!DOCTYPE html>",
        '<html lang="es">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>Informe — {html.escape(str(campaña))}</title>",
        "</head>",
        "<body>",
        f"<h1>Informe de campaña: {html.escape(str(campaña))}</h1>",
    ]

    partes.append('<section id="resumen">')
    partes.append("<h2>Resumen</h2>")
    partes.append("<ul>")
    partes.append(f"<li>Interacciones: {len(filas)}</li>")
    partes.append(f"<li>Puntuadas: {resumen['n']}</li>")
    partes.append(f"<li>Sin nota (error/demasiado_larga): {resumen['sin_nota']}</li>")
    nota_media_txt = resumen["nota_media"] if resumen["nota_media"] is not None else "sin datos"
    partes.append(f"<li>Nota media: {nota_media_txt}</li>")
    partes.append(f"<li>% críticas: {resumen['pct_criticas']}</li>")
    partes.append(f"<li>Cola de revisión: {resumen['cola']}</li>")
    partes.append("</ul>")
    partes.append("</section>")

    partes.append('<section id="ranking-de-agentes">')
    partes.append("<h2>Ranking de agentes</h2>")
    if ranking:
        partes.append("<table>")
        partes.append(
            "<tr><th>Agente</th><th>Nota media</th><th>% críticas</th>"
            "<th>Cola</th><th>N</th></tr>"
        )
        for agente, stats in sorted(ranking.items(), key=_orden_agente):
            nota_txt = stats["nota_media"] if stats["nota_media"] is not None else "sin datos"
            partes.append(
                f"<tr><td>{html.escape(str(agente))}</td><td>{nota_txt}</td>"
                f"<td>{stats['pct_criticas']}</td><td>{stats['cola']}</td>"
                f"<td>{stats['n']}</td></tr>"
            )
        partes.append("</table>")
    else:
        partes.append("<p>sin datos</p>")
    partes.append("</section>")

    partes.append('<section id="peores-interacciones">')
    partes.append("<h2>Peores interacciones</h2>")
    peores = sorted(puntuadas, key=lambda r: r["nota"])[:10]
    if peores:
        partes.append("<table>")
        partes.append(
            "<tr><th>Id</th><th>Agente</th><th>Fecha</th><th>Nota</th>"
            "<th>Estado</th><th>Críticos fallidos</th><th>Motivo</th></tr>"
        )
        for r in peores:
            fila = fila_por_id.get(r["id"], {})
            partes.append(
                "<tr>"
                f"<td>{html.escape(str(r['id']))}</td>"
                f"<td>{html.escape(str(r['agente']))}</td>"
                f"<td>{html.escape(str(fila.get('fecha', '')))}</td>"
                f"<td>{r['nota']}</td>"
                f"<td>{html.escape(str(r['estado']))}</td>"
                f"<td>{html.escape(', '.join(r['criticos_fallidos']))}</td>"
                f"<td>{html.escape(str(fila.get('motivo', '')))}</td>"
                "</tr>"
            )
        partes.append("</table>")
    else:
        partes.append("<p>sin datos</p>")
    partes.append("</section>")

    partes.append('<section id="cola-de-revision">')
    partes.append("<h2>Cola de revisión</h2>")
    cola = [r for r in puntuadas if r["revision"]]
    if cola:
        partes.append("<table>")
        partes.append("<tr><th>Id</th><th>Agente</th><th>Nota</th><th>Motivos de revisión</th></tr>")
        for r in cola:
            partes.append(
                "<tr>"
                f"<td>{html.escape(str(r['id']))}</td>"
                f"<td>{html.escape(str(r['agente']))}</td>"
                f"<td>{r['nota']}</td>"
                f"<td>{html.escape(', '.join(r['motivos_revision']))}</td>"
                "</tr>"
            )
        partes.append("</table>")
    else:
        partes.append("<p>sin datos</p>")
    partes.append("</section>")

    partes.append('<section id="filas-sin-nota">')
    partes.append("<h2>Filas sin nota</h2>")
    sin_nota_filas = [f for f in filas if f.get("estado") != "ok"]
    if sin_nota_filas:
        partes.append("<table>")
        partes.append("<tr><th>Id</th><th>Estado</th><th>Detalle</th></tr>")
        for f in sin_nota_filas:
            partes.append(
                "<tr>"
                f"<td>{html.escape(str(f.get('id', '')))}</td>"
                f"<td>{html.escape(str(f.get('estado', '')))}</td>"
                f"<td>{html.escape(str(f.get('detalle', '')))}</td>"
                "</tr>"
            )
        partes.append("</table>")
    else:
        partes.append("<p>sin datos</p>")
    partes.append("</section>")

    partes.append('<section id="coste-de-jev">')
    partes.append("<h2>Coste de Jev del periodo</h2>")
    fechas = [f.get("fecha", "") for f in filas if f.get("fecha")]
    periodo = f"{min(fechas)} – {max(fechas)}" if fechas else "sin datos"
    llamadas = sum(1 for f in filas if f.get("estado") == "ok")
    coste = llamadas * coste_por_llamada
    partes.append("<ul>")
    partes.append(f"<li>Periodo: {html.escape(periodo)}</li>")
    partes.append(f"<li>Llamadas facturadas: {llamadas}</li>")
    partes.append(f"<li>Coste estimado: ${coste:.4f}</li>")
    partes.append("</ul>")
    partes.append("</section>")

    partes.append("</body>")
    partes.append("</html>")
    return "\n".join(partes)


def generar_informes(
    rubric: dict,
    resultados_csv: str,
    salida_dir: str,
    coste_por_llamada: float = COSTE_POR_LLAMADA_USD,
) -> list:
    """Genera un HTML por campaña de `resultados_csv` dentro de `salida_dir`.

    Crea `salida_dir` si no existe. El nombre de archivo sale de un slug
    seguro de la campaña (sin separadores de ruta ni `..`); las colisiones
    de slug se resuelven con un sufijo numérico. Devuelve las rutas
    escritas. Lanza `InformeError` si el archivo no se puede leer como CSV
    UTF-8, si falta alguna columna base o de ítem de la rúbrica, si no tiene
    filas, o si alguna fila no se puede puntuar.
    """
    if not (isinstance(coste_por_llamada, (int, float)) and math.isfinite(coste_por_llamada)
            and coste_por_llamada >= 0):
        raise InformeError(f"coste por llamada inválido: {coste_por_llamada!r}")

    item_ids = _item_ids(rubric)
    esperadas = OUTPUT_HEADER_BASE + item_ids + ["riesgo", "motivo"]

    try:
        with open(resultados_csv, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                raise InformeError(f"el CSV de resultados está vacío: {resultados_csv}")
            faltantes = [c for c in esperadas if c not in reader.fieldnames]
            if faltantes:
                raise InformeError(
                    f"faltan columnas en {resultados_csv}: {', '.join(faltantes)}"
                )
            filas = list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise InformeError(f"no se puede leer {resultados_csv} como CSV UTF-8: {exc}") from exc

    if not filas:
        raise InformeError(f"el CSV de resultados no tiene filas: {resultados_csv}")

    por_campaña = {}
    for fila in filas:
        por_campaña.setdefault(fila.get("campaña"), []).append(fila)

    usados = set()
    rutas = []
    try:
        os.makedirs(salida_dir, exist_ok=True)
        for campaña, filas_campaña in por_campaña.items():
            html_doc = render_campaña(rubric, campaña, filas_campaña, coste_por_llamada)
            slug = _slug(campaña)
            nombre, contador = f"{slug}.html", 1
            while nombre.lower() in usados:
                contador += 1
                nombre = f"{slug}_{contador}.html"
            usados.add(nombre.lower())
            ruta = os.path.join(salida_dir, nombre)
            with open(ruta, "w", encoding="utf-8") as f:
                f.write(html_doc)
            rutas.append(ruta)
    except OSError as exc:
        raise InformeError(f"no se puede escribir en {salida_dir}: {exc}") from exc
    return rutas
