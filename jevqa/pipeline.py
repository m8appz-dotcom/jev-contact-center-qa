"""Auditoría por lotes: de un CSV de transcripciones a un CSV de resultados.

Cada fila se anonimiza y se envía a Jev en una sola petición. Tres cosas que
el lote garantiza y que conviene no romper:

* **Anonimizar antes de llamar.** El texto crudo no sale de este proceso.
* **Un fallo no tumba el lote.** La fila queda marcada con su error y el
  resto sigue; un lote de mil interacciones no se pierde por una.
* **Relanzar no cuesta dinero.** Los ids que ya están en el archivo de
  salida se saltan sin llamar a Jev.
"""

from __future__ import annotations

import csv
import math
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable

from jevqa.anonymize import anonymize
from jevqa.jev_client import (
    LIMITE_PETICIONES_POR_MINUTO,
    LIMITE_TOKENS_ESTADO,
    ErrorJev,
    coste_usd,
)
from jevqa.rubric import ErrorRubrica, build_request, parse_response

#: Columnas que tiene que traer el CSV de entrada.
COLUMNAS = ("id", "agente", "campaña", "fecha", "texto")

#: Nombres alternativos que se aceptan para una columna. Un CSV exportado de
#: un sistema que no maneja tildes trae `campana`, y es la misma columna.
ALIAS = {"campaña": ("campana", "campania", "campaign")}

#: Columna opcional: si viene, su nombre también se tapa en el texto.
COLUMNA_CLIENTE = "cliente"

ESTADO_OK = "ok"
ESTADO_ERROR = "error"
ESTADO_LARGA = "demasiado_larga"

#: Caracteres por token en español. Es una estimación grosera y deliberadamente
#: conservadora: sirve para no mandar una fila que la API va a rechazar, no
#: para contar tokens. El conteo real lo devuelve `usage` en la respuesta.
CARACTERES_POR_TOKEN = 3.0

#: El módulo csv corta los campos en 131.072 caracteres y revienta el lote
#: entero con un error opaco. Una transcripción larga tiene que poder leerse
#: para que la marque nuestra propia comprobación, no para que se caiga todo.
#: Diez millones de caracteres sobran: el tope de la API son ~96.000.
LIMITE_CAMPO_CSV = 10_000_000

#: Se deja margen bajo el límite publicado de 1.200 peticiones por minuto.
PETICIONES_POR_MINUTO = int(LIMITE_PETICIONES_POR_MINUTO * 0.8)
CONCURRENCIA = 8


class ErrorEntrada(Exception):
    """El CSV de entrada no sirve: no existe, está vacío o le faltan columnas."""


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------

def _resolver_columnas(cabecera: Iterable[str]) -> dict[str, str]:
    """Empareja cada columna obligatoria con su nombre real en el archivo."""
    presentes = {nombre.strip(): nombre for nombre in cabecera if nombre}
    resueltas: dict[str, str] = {}
    faltan: list[str] = []
    for columna in COLUMNAS:
        for candidato in (columna, *ALIAS.get(columna, ())):
            if candidato in presentes:
                resueltas[columna] = presentes[candidato]
                break
        else:
            faltan.append(columna)
    if faltan:
        raise ErrorEntrada(
            "al CSV de entrada le faltan columnas: "
            + ", ".join(faltan)
            + ". Se esperaban: "
            + ", ".join(COLUMNAS)
            + f". Se encontraron: {', '.join(presentes) or 'ninguna'}"
        )
    if COLUMNA_CLIENTE in presentes:
        resueltas[COLUMNA_CLIENTE] = presentes[COLUMNA_CLIENTE]
    return resueltas


def leer_entrada(ruta: str) -> tuple[list[dict], dict[str, str]]:
    """Lee el CSV y devuelve sus filas normalizadas más el mapa de columnas."""
    if not os.path.exists(ruta):
        raise ErrorEntrada(f"no existe el archivo de entrada {ruta}")

    anterior = csv.field_size_limit(LIMITE_CAMPO_CSV)
    try:
        with open(ruta, encoding="utf-8-sig", newline="") as archivo:
            lector = csv.DictReader(archivo)
            if lector.fieldnames is None:
                raise ErrorEntrada(f"{ruta} está vacío: no tiene ni cabecera")
            columnas = _resolver_columnas(lector.fieldnames)
            crudas = list(lector)
    except csv.Error as exc:
        raise ErrorEntrada(f"{ruta} no se pudo leer como CSV: {exc}") from exc
    finally:
        csv.field_size_limit(anterior)

    filas = []
    for numero, cruda in enumerate(crudas, start=2):  # la 1 es la cabecera
        fila = {campo: (cruda.get(origen) or "").strip() for campo, origen in columnas.items()}
        if not fila["id"]:
            raise ErrorEntrada(f"{ruta}, línea {numero}: la columna id está vacía")
        fila["_linea"] = numero
        filas.append(fila)

    repetidos = _repetidos(f["id"] for f in filas)
    if repetidos:
        raise ErrorEntrada(f"{ruta}: hay ids repetidos: {', '.join(repetidos)}")
    return filas, columnas


def _repetidos(valores: Iterable[str]) -> list[str]:
    vistos: set[str] = set()
    repetidos: list[str] = []
    for valor in valores:
        if valor in vistos and valor not in repetidos:
            repetidos.append(valor)
        vistos.add(valor)
    return repetidos


# ---------------------------------------------------------------------------
# Salida
# ---------------------------------------------------------------------------

def cabecera_salida(rubrica: dict) -> list[str]:
    columnas = [
        "id",
        "agente",
        "campaña",
        "fecha",
        "estado",
        "modelo",
        "motivo",
        "motivo_confianza",
        "riesgo_nivel",
        "riesgo_etiqueta",
        "riesgo_confianza",
        "tokens_entrada",
        "tokens_salida",
        "coste_usd",
        "error",
    ]
    for item in rubrica["items"]:
        columnas += [f"{item['id']}_prob", f"{item['id']}_conf"]
    return columnas


def ids_ya_auditados(ruta: str) -> set[str]:
    """Los ids que ya están en el archivo de salida. Relanzar no los repite."""
    if not os.path.exists(ruta) or os.path.getsize(ruta) == 0:
        return set()
    with open(ruta, encoding="utf-8-sig", newline="") as archivo:
        lector = csv.DictReader(archivo)
        if lector.fieldnames is None or "id" not in lector.fieldnames:
            return set()
        return {(fila.get("id") or "").strip() for fila in lector if fila.get("id")}


def _fila_salida(fila: dict, rubrica: dict, resultado: dict | None, estado: str, error: str) -> dict:
    salida = {
        "id": fila["id"],
        "agente": fila["agente"],
        "campaña": fila["campaña"],
        "fecha": fila["fecha"],
        "estado": estado,
        "modelo": "",
        "motivo": "",
        "motivo_confianza": "",
        "riesgo_nivel": "",
        "riesgo_etiqueta": "",
        "riesgo_confianza": "",
        "tokens_entrada": 0,
        "tokens_salida": 0,
        "coste_usd": 0.0,
        "error": error,
    }
    for item in rubrica["items"]:
        salida[f"{item['id']}_prob"] = ""
        salida[f"{item['id']}_conf"] = ""

    if resultado is None:
        return salida

    salida["modelo"] = resultado["modelo"] or ""
    salida["motivo"] = resultado["motivo"]["valor"]
    salida["motivo_confianza"] = round(resultado["motivo"]["confianza"], 4)
    salida["riesgo_nivel"] = resultado["riesgo"]["nivel"]
    salida["riesgo_etiqueta"] = _etiqueta_corta(resultado["riesgo"]["etiqueta"])
    salida["riesgo_confianza"] = round(resultado["riesgo"]["confianza"], 4)
    salida["tokens_entrada"] = resultado["uso"]["tokens_entrada"]
    salida["tokens_salida"] = resultado["uso"]["tokens_salida"]
    salida["coste_usd"] = round(coste_usd(resultado["uso"]["tokens_entrada"]), 8)
    for item in rubrica["items"]:
        registro = resultado["items"][item["id"]]
        salida[f"{item['id']}_prob"] = round(registro["probabilidad"], 4)
        salida[f"{item['id']}_conf"] = round(registro["confianza"], 4)
    return salida


def _etiqueta_corta(etiqueta: str) -> str:
    """"Medio: el cliente queda sin solución…" se guarda como "Medio"."""
    return etiqueta.split(":", 1)[0].strip()


# ---------------------------------------------------------------------------
# Límite de peticiones
# ---------------------------------------------------------------------------

class Limitador:
    """Reparte las peticiones en el tiempo para no pasar del límite por minuto.

    `dormir` se inyecta en los tests para no esperar de verdad.
    """

    def __init__(
        self,
        por_minuto: int = PETICIONES_POR_MINUTO,
        *,
        dormir: Callable[[float], None] = time.sleep,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        if por_minuto > LIMITE_PETICIONES_POR_MINUTO:
            raise ValueError(
                f"{por_minuto} peticiones por minuto pasa del límite publicado "
                f"de {LIMITE_PETICIONES_POR_MINUTO}"
            )
        self.intervalo = 60.0 / por_minuto if por_minuto > 0 else 0.0
        self._dormir = dormir
        self._reloj = reloj
        self._cerrojo = threading.Lock()
        self._siguiente = 0.0
        #: Esperas aplicadas, en segundos. Los tests comprueban el reparto.
        self.esperas: list[float] = []

    def esperar(self) -> None:
        with self._cerrojo:
            ahora = self._reloj()
            momento = max(ahora, self._siguiente)
            self._siguiente = momento + self.intervalo
            espera = momento - ahora
            self.esperas.append(espera)
        if espera > 0:
            self._dormir(espera)


# ---------------------------------------------------------------------------
# Auditoría
# ---------------------------------------------------------------------------

def estimar_tokens(texto: str) -> int:
    return _tokens_de(len(texto))


def _tokens_de(caracteres: int) -> int:
    return math.ceil(caracteres / CARACTERES_POR_TOKEN)


def demasiado_larga(rubrica: dict, texto: str) -> bool:
    """El límite de la API es el `state` más la pregunta más larga.

    Se compara contra la estimación, no contra el conteo real: la idea es no
    gastar una llamada que la API va a rechazar.
    """
    pregunta_mas_larga = max(
        (len(item["pregunta"]) for item in rubrica["items"]),
        default=0,
    )
    return estimar_tokens(texto) + _tokens_de(pregunta_mas_larga) > LIMITE_TOKENS_ESTADO


def auditar_fila(fila: dict, rubrica: dict, cliente) -> tuple[dict | None, str, str]:
    """Anonimiza, llama a Jev y devuelve `(resultado, estado, error)`."""
    if not fila["texto"]:
        return None, ESTADO_ERROR, "la fila no tiene texto"
    if demasiado_larga(rubrica, fila["texto"]):
        return (
            None,
            ESTADO_LARGA,
            f"la transcripción estima {estimar_tokens(fila['texto']):,} tokens y el "
            f"límite del state es {LIMITE_TOKENS_ESTADO:,}",
        )

    nombres = [fila.get("agente", ""), fila.get(COLUMNA_CLIENTE, "")]
    texto = anonymize(fila["texto"], [nombre for nombre in nombres if nombre])
    try:
        respuesta = cliente.evaluar(build_request(rubrica, texto))
        return parse_response(rubrica, respuesta), ESTADO_OK, ""
    except (ErrorJev, ErrorRubrica) as exc:
        return None, ESTADO_ERROR, f"{type(exc).__name__}: {exc}"


def auditar(
    entrada: str,
    salida: str,
    rubrica: dict,
    cliente,
    *,
    concurrencia: int = CONCURRENCIA,
    limitador: Limitador | None = None,
    registrar: Callable[[str], None] = print,
) -> dict:
    """Audita un CSV entero y deja el resultado en `salida`. Devuelve el resumen."""
    filas, _ = leer_entrada(entrada)
    ya_hechas = ids_ya_auditados(salida)
    pendientes = [fila for fila in filas if fila["id"] not in ya_hechas]

    resumen = {
        "filas": len(filas),
        "saltadas": len(filas) - len(pendientes),
        "auditadas": 0,
        "errores": 0,
        "demasiado_largas": 0,
        "tokens_entrada": 0,
        "tokens_salida": 0,
        "coste_usd": 0.0,
    }
    if resumen["saltadas"]:
        registrar(f"{resumen['saltadas']} interacciones ya estaban auditadas, se saltan.")
    if not pendientes:
        _preparar_salida(salida, rubrica)[1].close()
        return resumen

    limitador = limitador if limitador is not None else Limitador()

    def trabajo(fila: dict) -> tuple[dict, dict | None, str, str]:
        limitador.esperar()
        resultado, estado, error = auditar_fila(fila, rubrica, cliente)
        return fila, resultado, estado, error

    escritor, archivo = _preparar_salida(salida, rubrica)
    try:
        with ThreadPoolExecutor(max_workers=max(1, concurrencia)) as ejecutor:
            for numero, (fila, resultado, estado, error) in enumerate(
                ejecutor.map(trabajo, pendientes), start=1
            ):
                escritor.writerow(_fila_salida(fila, rubrica, resultado, estado, error))
                archivo.flush()  # relanzar después de un corte no repite lo hecho

                if estado == ESTADO_OK:
                    resumen["auditadas"] += 1
                    resumen["tokens_entrada"] += resultado["uso"]["tokens_entrada"]
                    resumen["tokens_salida"] += resultado["uso"]["tokens_salida"]
                elif estado == ESTADO_LARGA:
                    resumen["demasiado_largas"] += 1
                else:
                    resumen["errores"] += 1
                if estado != ESTADO_OK:
                    registrar(f"  [{numero}/{len(pendientes)}] {fila['id']}: {estado} — {error}")
    finally:
        archivo.close()

    resumen["coste_usd"] = coste_usd(resumen["tokens_entrada"])
    return resumen


def _preparar_salida(ruta: str, rubrica: dict):
    """Abre la salida en modo añadir y escribe la cabecera si hace falta."""
    carpeta = os.path.dirname(os.path.abspath(ruta))
    os.makedirs(carpeta, exist_ok=True)
    nueva = not os.path.exists(ruta) or os.path.getsize(ruta) == 0
    archivo = open(ruta, "a", encoding="utf-8", newline="")
    escritor = csv.DictWriter(archivo, fieldnames=cabecera_salida(rubrica))
    if nueva:
        escritor.writeheader()
        archivo.flush()
    return escritor, archivo


def imprimir_resumen(resumen: dict, salida: str, destino=sys.stdout) -> None:
    print(
        f"\n{resumen['auditadas']}/{resumen['filas']} interacciones auditadas"
        f" · {resumen['saltadas']} saltadas"
        f" · {resumen['errores']} con error"
        f" · {resumen['demasiado_largas']} demasiado largas",
        file=destino,
    )
    print(
        f"Tokens de entrada: {resumen['tokens_entrada']:,}"
        f" · coste ${resumen['coste_usd']:.6f}",
        file=destino,
    )
    print(f"Resultados: {salida}", file=destino)
