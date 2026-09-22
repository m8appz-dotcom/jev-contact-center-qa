"""Nota de la interacción, umbrales y cola de revisión humana.

De las probabilidades que devuelve Jev a las tres cosas que una auditoría
necesita decidir:

* **Nota 0–100.** Suma ponderada por los pesos de la rúbrica. Es el número que
  compara a un agente con otro, así que se calcula siempre igual y no se toca
  por ningún otro motivo.
* **Estado.** Aprobado o suspenso. Un ítem crítico en «no cumple» fuerza el
  suspenso aunque la nota sea alta: son las tres cosas que no se negocian
  (verificar identidad, tratar bien al cliente, no prometer de más).
* **Cola de revisión.** Lo que el modelo no vio claro lo mira una persona.

La nota **no** se pone a cero cuando falla una crítica. Un cero borraría la
diferencia entre una interacción por lo demás correcta y un desastre, y el
informe de la fase 6 necesita distinguirlas: por eso van separadas la nota
(cuánto de la rúbrica se cumplió) y el estado (si la interacción pasa). El
porcentaje de críticas de los agregados es lo que impide que una nota alta con
una crítica fallada se lea como un buen trabajo.

Los umbrales salen del informe de la fase 2 (`data/eval/informe.md`) y se
pueden cambiar por rúbrica, en su bloque `umbrales`.
"""

from __future__ import annotations

from typing import Iterable

# ---------------------------------------------------------------------------
# Umbrales
# ---------------------------------------------------------------------------

#: Desde esta probabilidad el ítem se da por cumplido. La fase 2 midió el
#: acuerdo con las etiquetas humanas justo en 0,5 y los 8 ítems pasaron el
#: 85 %, así que se queda como valor por defecto.
UMBRAL_CUMPLE = 0.5

#: Por debajo de esta confianza la respuesta no se da por buena sola y la
#: interacción va a revisión. Es el mismo umbral con el que la fase 2 midió el
#: «acuerdo con confianza», donde ningún ítem bajó del 93 %.
UMBRAL_CONFIANZA = 0.7

#: Banda de probabilidad que se considera indecisa (valores del plan). Para un
#: Noul esta banda ya cae dentro de la regla de confianza —la confianza de un
#: Noul es |2p−1|, así que 0,35–0,65 equivale a una confianza de 0 a 0,3— y
#: solo empieza a decidir sola si una rúbrica baja `confianza` por debajo de
#: 0,3. Se evalúa y se registra aparte para que el motivo de la revisión se lea
#: tal como está escrito en el plan.
AMBIGUO_MIN = 0.35
AMBIGUO_MAX = 0.65

#: Nota mínima para aprobar. No sale de la fase 2 —allí no se midió ninguna
#: nota—, sino de la práctica habitual de los contact centers; es lo primero
#: que hay que calibrar con el cliente en el piloto de la fase 6.
NOTA_APROBADO = 70.0

#: Por debajo de estas interacciones, el promedio de un agente es una anécdota.
#: `agregar` lo marca para que el ranking del informe no ponga arriba a quien
#: solo tiene una llamada auditada.
MUESTRA_MINIMA = 5

#: Claves admitidas en `umbrales`, además de `cumple_<id de ítem>`.
CLAVES_UMBRALES = ("cumple", "confianza", "ambiguo_min", "ambiguo_max", "aprobado")

#: Prefijo para fijar el umbral de cumplimiento de un solo ítem:
#: `"cumple_verifica_identidad": 0.75`. La fase 2 encontró que con el umbral
#: general de 0,5 ese ítem crítico detecta 1 de cada 4 fallas reales, así que
#: antes del piloto toca afinarlo aquí, por ítem, sin mover a los demás.
PREFIJO_ITEM = "cumple_"

ESTADO_APROBADO = "aprobado"
ESTADO_SUSPENSO = "suspenso"

#: Por qué una interacción está en la cola. Se guardan los dos motivos aunque
#: se solapen: no es lo mismo «el modelo duda» que «el modelo está en medio».
REVISION_CONFIANZA = "confianza_baja"
REVISION_AMBIGUA = "probabilidad_ambigua"

#: Etiqueta de las filas sin campaña. Agrupar todos los vacíos en un cubo con
#: nombre es mejor que dejar una fila de agregados con la clave en blanco.
SIN_CAMPANA = "(sin campaña)"

CAMPO_AGENTE = "agente"
CAMPO_CAMPANA = "campaña"


class ErrorScoring(Exception):
    """Base de los errores de este módulo."""


class UmbralInvalido(ErrorScoring):
    """El bloque `umbrales` de la rúbrica tiene un valor que no se puede usar."""


class ResultadoIncompleto(ErrorScoring):
    """Al resultado le falta algún ítem de la rúbrica con la que se califica."""

    def __init__(self, faltantes: list[str]) -> None:
        self.faltantes = list(faltantes)
        super().__init__("el resultado no trae los ítems: " + ", ".join(self.faltantes))


def resolver_umbrales(rubrica: dict, extra: dict | None = None) -> dict:
    """Mezcla los valores por defecto con los de la rúbrica y los valida.

    `extra` gana sobre la rúbrica y la rúbrica gana sobre los valores por
    defecto, para que una corrida puntual pueda mover un umbral sin editar el
    archivo.
    """
    umbrales = {
        "cumple": UMBRAL_CUMPLE,
        "confianza": UMBRAL_CONFIANZA,
        "ambiguo_min": AMBIGUO_MIN,
        "ambiguo_max": AMBIGUO_MAX,
        "aprobado": NOTA_APROBADO,
    }
    ids_items = {item["id"] for item in rubrica.get("items", ())}

    for origen in (rubrica.get("umbrales") or {}, extra or {}):
        for clave_cruda, valor in origen.items():
            clave = str(clave_cruda)
            if isinstance(valor, bool) or not isinstance(valor, (int, float)):
                raise UmbralInvalido(f"umbrales: {clave} debe ser un número")
            if clave not in CLAVES_UMBRALES and not _es_umbral_de_item(clave, ids_items):
                raise UmbralInvalido(
                    f"umbrales: {clave} no es un umbral conocido. Se admiten "
                    + ", ".join(CLAVES_UMBRALES)
                    + f", y {PREFIJO_ITEM}<id de ítem> para un ítem suelto"
                )
            umbrales[clave] = float(valor)

    for clave in ("cumple", "confianza", "ambiguo_min", "ambiguo_max"):
        _validar_rango(umbrales, clave, 0.0, 1.0)
    _validar_rango(umbrales, "aprobado", 0.0, 100.0)
    for clave in umbrales:
        if clave.startswith(PREFIJO_ITEM):
            _validar_rango(umbrales, clave, 0.0, 1.0)
    if umbrales["ambiguo_min"] > umbrales["ambiguo_max"]:
        raise UmbralInvalido(
            f"umbrales: ambiguo_min ({umbrales['ambiguo_min']}) no puede ser mayor "
            f"que ambiguo_max ({umbrales['ambiguo_max']})"
        )
    return umbrales


def _es_umbral_de_item(clave: str, ids_items: set[str]) -> bool:
    return clave.startswith(PREFIJO_ITEM) and clave[len(PREFIJO_ITEM):] in ids_items


def _validar_rango(umbrales: dict, clave: str, minimo: float, maximo: float) -> None:
    valor = umbrales[clave]
    if not minimo <= valor <= maximo:
        raise UmbralInvalido(
            f"umbrales: {clave} debe estar entre {minimo} y {maximo}, llegó {valor}"
        )


def umbral_de_item(umbrales: dict, item_id: str) -> float:
    """El umbral de un ítem: el suyo si lo tiene, si no el general."""
    return float(umbrales.get(PREFIJO_ITEM + item_id, umbrales["cumple"]))


# ---------------------------------------------------------------------------
# Nota de una interacción
# ---------------------------------------------------------------------------

def calificar(
    rubrica: dict,
    resultado: dict,
    *,
    meta: dict | None = None,
    umbrales: dict | None = None,
) -> dict:
    """Convierte un resultado de `parse_response` en nota, estado y revisión.

    `meta` son los datos de la fila (id, agente, campaña, fecha) que el lote ya
    conoce; se copian tal cual para que los agregados y el informe no tengan
    que volver al CSV de entrada.
    """
    umbrales = umbrales if umbrales is not None else resolver_umbrales(rubrica)
    respuestas = resultado.get("items") or {}
    faltantes = [item["id"] for item in rubrica["items"] if item["id"] not in respuestas]
    if faltantes:
        raise ResultadoIncompleto(faltantes)

    items: dict[str, dict] = {}
    peso_total = 0.0
    peso_cumplido = 0.0
    criticas: list[str] = []
    a_revisar: list[str] = []

    for item in rubrica["items"]:
        registro = respuestas[item["id"]]
        probabilidad = float(registro["probabilidad"])
        confianza = float(registro["confianza"])
        peso = float(item["peso"])
        umbral = umbral_de_item(umbrales, item["id"])
        cumple = probabilidad >= umbral

        poca_confianza = confianza < umbrales["confianza"]
        ambiguo = umbrales["ambiguo_min"] <= probabilidad <= umbrales["ambiguo_max"]
        motivos = []
        if poca_confianza:
            motivos.append(REVISION_CONFIANZA)
        if ambiguo:
            motivos.append(REVISION_AMBIGUA)

        peso_total += peso
        if cumple:
            peso_cumplido += peso
        elif item["critico"]:
            criticas.append(item["id"])
        if motivos:
            a_revisar.append(item["id"])

        items[item["id"]] = {
            "cumple": cumple,
            "critico": item["critico"],
            "peso": peso,
            "probabilidad": probabilidad,
            "confianza": confianza,
            "umbral": umbral,
            "ambiguo": ambiguo,
            "poca_confianza": poca_confianza,
            "motivos_revision": motivos,
        }

    # peso_total nunca es cero: `load_rubric` exige al menos un ítem y peso > 0.
    nota = round(100.0 * peso_cumplido / peso_total, 2)
    aprueba = nota >= umbrales["aprobado"] and not criticas

    calificacion = {
        "id": "",
        CAMPO_AGENTE: "",
        CAMPO_CAMPANA: "",
        "fecha": "",
        "rubrica": resultado.get("rubrica", rubrica.get("id", "")),
        "version_rubrica": resultado.get("version_rubrica", rubrica.get("version", "")),
        "nota": nota,
        "estado": ESTADO_APROBADO if aprueba else ESTADO_SUSPENSO,
        "criticas_falladas": criticas,
        "revisar": bool(a_revisar),
        "items_a_revisar": a_revisar,
        "motivos_revision": sorted(
            {motivo for qid in a_revisar for motivo in items[qid]["motivos_revision"]}
        ),
        "peso_cumplido": round(peso_cumplido, 4),
        "peso_total": round(peso_total, 4),
        "items": items,
        "riesgo": resultado.get("riesgo"),
        "motivo": resultado.get("motivo"),
    }
    for campo in ("id", CAMPO_AGENTE, CAMPO_CAMPANA, "fecha"):
        valor = (meta or {}).get(campo, "")
        calificacion[campo] = "" if valor is None else str(valor).strip()
    return calificacion


# ---------------------------------------------------------------------------
# Cola de revisión
# ---------------------------------------------------------------------------

def cola_de_revision(calificaciones: Iterable[dict]) -> list[dict]:
    """Las interacciones que mira una persona, la más urgente primero.

    El orden es el del riesgo para la empresa, no el de llegada: primero las
    que fallaron una crítica, después las de peor nota, y el id desempata para
    que dos corridas sobre los mismos datos den la misma cola.
    """
    return sorted(
        (c for c in calificaciones if c.get("revisar")),
        key=lambda c: (
            not c.get("criticas_falladas"),
            float(c.get("nota", 0.0)),
            str(c.get("id", "")),
        ),
    )


# ---------------------------------------------------------------------------
# Agregados
# ---------------------------------------------------------------------------

def agregar(calificaciones: Iterable[dict]) -> dict:
    """Agrupa las calificaciones por agente y por campaña, más un total.

    Cada grupo trae nota media, porcentaje de interacciones con alguna crítica
    fallada y tamaño de la cola. Una lista vacía devuelve grupos vacíos y un
    total en cero: aquí no hay ninguna división por cero que esperar.
    """
    calificaciones = list(calificaciones)
    return {
        "agentes": _agrupar(calificaciones, CAMPO_AGENTE, ""),
        "campanas": _agrupar(calificaciones, CAMPO_CAMPANA, SIN_CAMPANA),
        "total": _resumen("total", calificaciones),
    }


def _agrupar(calificaciones: list[dict], campo: str, vacio: str) -> list[dict]:
    grupos: dict[str, list[dict]] = {}
    for calificacion in calificaciones:
        clave = str(calificacion.get(campo) or "").strip() or vacio
        grupos.setdefault(clave, []).append(calificacion)
    # Peor nota primero: un informe de calidad se lee por abajo. La clave
    # desempata para que el orden no dependa del orden de entrada.
    return sorted(
        (_resumen(clave, filas) for clave, filas in grupos.items()),
        key=lambda resumen: (resumen["nota_media"], resumen["clave"]),
    )


def _resumen(clave: str, calificaciones: list[dict]) -> dict:
    total = len(calificaciones)
    resumen = {
        "clave": clave,
        "interacciones": total,
        "nota_media": 0.0,
        "nota_minima": 0.0,
        "nota_maxima": 0.0,
        "criticas": 0,
        "porcentaje_criticas": 0.0,
        "suspensos": 0,
        "porcentaje_suspensos": 0.0,
        "cola": 0,
        "porcentaje_cola": 0.0,
        "muestra_suficiente": total >= MUESTRA_MINIMA,
    }
    if not total:
        return resumen

    notas = [float(c.get("nota", 0.0)) for c in calificaciones]
    criticas = sum(1 for c in calificaciones if c.get("criticas_falladas"))
    suspensos = sum(1 for c in calificaciones if c.get("estado") == ESTADO_SUSPENSO)
    cola = sum(1 for c in calificaciones if c.get("revisar"))
    resumen.update(
        {
            "nota_media": round(sum(notas) / total, 2),
            "nota_minima": round(min(notas), 2),
            "nota_maxima": round(max(notas), 2),
            "criticas": criticas,
            "porcentaje_criticas": _porcentaje(criticas, total),
            "suspensos": suspensos,
            "porcentaje_suspensos": _porcentaje(suspensos, total),
            "cola": cola,
            "porcentaje_cola": _porcentaje(cola, total),
        }
    )
    return resumen


def _porcentaje(parte: int, total: int) -> float:
    return round(100.0 * parte / total, 2) if total else 0.0


def describir(calificacion: dict) -> str:
    """Una línea legible para el registro del lote y para el informe."""
    partes = [
        f"{calificacion.get('id') or 'sin id'}: {calificacion['nota']:.1f}",
        calificacion["estado"],
    ]
    if calificacion["criticas_falladas"]:
        partes.append("críticas: " + ", ".join(calificacion["criticas_falladas"]))
    if calificacion["revisar"]:
        partes.append("a revisión: " + ", ".join(calificacion["items_a_revisar"]))
    return " · ".join(partes)
