"""English presentation of the native campaign report; scoring stays in report.py."""
from __future__ import annotations

import datetime
import html


def render_campaign(campaign, rubric, thresholds, scores, unscored,
                    total, ranking, queue, cost, start, end, note=""):
    # Imported only after report.py has loaded. Both languages use the same
    # aggregation, review queue, ranking rules, escaping contract and CSS.
    from jevqa.report import CSS, _tabla

    def escape(value):
        return html.escape("" if value is None else str(value), quote=True)

    def number(value, decimals=1):
        return f"{value:,.{decimals}f}"

    def percent(value):
        return f"{number(value)}%"

    def table(headers, rows, empty):
        return _tabla(headers, rows, empty)

    def state(score):
        failed = score["estado"] == "suspenso"
        return f'<span class="estado {"mal" if failed else "bien"}">{"Needs attention" if failed else "Pass"}</span>'

    labels = {
        "saludo": "Greeting", "verifica_identidad": "Identity verification",
        "escucha_activa": "Active listening", "diagnostico": "Diagnosis",
        "solucion_o_derivacion": "Resolution or escalation",
        "tono_respetuoso": "Respectful tone",
        "compromiso_realista": "Realistic commitments", "cierre": "Closing",
    }

    def items(values):
        return escape(", ".join(labels.get(value, value.replace("_", " ")) for value in values) or "—")

    def agent_rows(groups, positions):
        return [([str(i)] if positions else []) + [
            escape(group["clave"] or "Unassigned agent"), str(group["interacciones"]),
            number(group["nota_media"]), percent(group["porcentaje_criticas"]),
            percent(group["porcentaje_suspensos"]), str(group["cola"]),
        ] for i, group in enumerate(groups, 1)]

    headers = ["Agent", "Interactions", "Average score", "Critical failures", "Failed interactions", "Review queue"]
    sections = ['<section><h2>Agent ranking</h2><p>Highest average first. Check critical failures alongside the score.</p>'
                + table(["#"] + headers, agent_rows(ranking["con_muestra"], True),
                        "No agent has enough audited interactions for a ranking yet.")]
    if ranking["sin_muestra"]:
        sections.append('<h3>Insufficient sample</h3><p>Fewer than five audited interactions: these agents remain outside the ranking.</p>'
                        + table(headers, agent_rows(ranking["sin_muestra"], False), ""))
    sections.append("</section>")

    from jevqa.report import peores_interacciones
    sections.append('<section><h2>Interactions needing attention</h2><p>Critical failures come first, followed by the lowest scores.</p>'
                    + table(["Interaction", "Agent", "Date", "Score", "Status", "Critical failures", "Risk", "Contact reason"], [
                        [escape(s["id"]), escape(s["agente"]), escape(s["fecha"]), number(s["nota"]), state(s),
                         items(s["criticas_falladas"]), escape((s.get("riesgo") or {}).get("etiqueta", "")),
                         escape((s.get("motivo") or {}).get("valor", ""))]
                        for s in peores_interacciones(scores)
                    ], "No audited interactions in this period.") + "</section>")
    reasons = {"confianza_baja": "Low model confidence", "probabilidad_ambigua": "Ambiguous probability"}
    sections.append(f'<section><h2>Human review queue ({len(queue)})</h2><p>Review uncertain judgments, starting with critical failures and then the lowest scores.</p>'
                    + table(["Interaction", "Agent", "Score", "Status", "Criteria to review", "Review reason"], [
                        [escape(s["id"]), escape(s["agente"]), number(s["nota"]), state(s), items(s["items_a_revisar"]),
                         escape(", ".join(reasons.get(r, r.replace("_", " ")) for r in s["motivos_revision"]))]
                        for s in queue
                    ], "The review queue is empty.") + "</section>")
    sections.append('<section><h2>JEV usage for this period</h2>' + table(["Measure", "Value"], [
        ["Audited interactions", str(cost["auditadas"])],
        ["Unscored interactions", str(cost["sin_calificar"])],
        ["Input tokens", number(cost["tokens_entrada"], 0)],
        ["Estimated input-token cost", f'US$ {number(cost["coste_usd"], 6)}'],
        ["Estimated cost per 1,000 interactions", f'US$ {number(cost["coste_por_mil"], 4)}'],
    ], "") + '<p>Calculated from reported input tokens at US$42 per billion tokens. Output tokens are free.</p></section>')
    if unscored:
        sections.append('<section><h2>Unscored interactions</h2>' + table(
            ["Interaction", "Agent", "Date", "Status", "Reason"],
            [[escape(s["id"]), escape(s["agente"]), escape(s["fecha"]),
              escape({"error": "Error", "demasiado_larga": "Transcript too long"}.get(s["estado"], s["estado"])),
              escape(s["motivo"])] for s in unscored], "") + "</section>")
    summary = '<dl class="resumen">' + "".join(
        f'<div><dt>{label}</dt><dd>{value}</dd></div>' for label, value in [
            ("Interactions", total["interacciones"]), ("Average score", number(total["nota_media"])),
            ("Critical failures", percent(total["porcentaje_criticas"])),
            ("Failed interactions", percent(total["porcentaje_suspensos"])),
            ("Human review", percent(total["porcentaje_cola"])),
        ]) + "</dl>"
    return f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Quality review · {escape(campaign)}</title><style>{CSS}</style></head><body><main>
<header><p class="sobre">Quality review with JEV</p><h1>{escape(campaign)}</h1>
<p class="meta">{escape(start or "—")} to {escape(end or "—")} · {escape(rubric["id"])} v{escape(rubric["version"])} · pass threshold {number(thresholds["aprobado"], 0)}, with no critical failures · generated {datetime.date.today().isoformat()}</p></header>
{f'<p class="meta">{escape(note)}</p>' if note else ''}
{summary}{"".join(sections)}
<footer>A model scores these interactions. A reviewer must assess uncertain judgments; do not make personnel decisions from this report alone.</footer>
</main></body></html>
'''
