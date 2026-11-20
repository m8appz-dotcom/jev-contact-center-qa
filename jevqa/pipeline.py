"""Auditoría por lotes: CSV de interacciones -> CSV de resultados.

Cada fila se anonimiza (ver `jevqa.anonymize`) antes de construir la petición
a Jev, de modo que el texto sin anonimizar nunca llega al cliente. El lote es
reanudable: si la salida ya existe, las filas con estado `ok` o
`demasiado_larga` se conservan y no se vuelven a pagar; las de estado `error`
se descartan y se reintentan. La escritura de la salida la hace siempre el
hilo principal; la concurrencia hacia Jev está limitada por `RateLimiter`.
"""

from __future__ import annotations

import csv
import json
import math
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from jevqa import rubric as rubric_mod
from jevqa.anonymize import anonymize
from jevqa.jev_client import JevAuthError, JevError

REQUIRED_COLUMNS = ["id", "agente", "campaña", "fecha", "texto"]
OUTPUT_HEADER_BASE = ["id", "agente", "campaña", "fecha", "estado", "detalle"]

MAX_TOKENS = 32000
MAX_WORKERS = 8
# <= 1.000 llamadas/min, con margen bajo el límite de 1.200 del plan.
MIN_INTERVAL_SECONDS = 60.0 / 1000

ESTADO_OK = "ok"
ESTADO_DEMASIADO_LARGA = "demasiado_larga"
ESTADO_ERROR = "error"


class EntradaInvalidaError(Exception):
    """El CSV de entrada no tiene el formato esperado."""


class SalidaInvalidaError(Exception):
    """La salida existente tiene una cabecera distinta a la esperada."""


class RateLimiter:
    """Espacia llamadas para no superar `min_interval` segundos entre ellas.

    `clock` y `sleep` son inyectables para que los tests no esperen de
    verdad. Seguro para llamarse desde varios hilos a la vez.
    """

    def __init__(self, min_interval: float, clock=time.monotonic, sleep=time.sleep):
        self.min_interval = min_interval
        self.clock = clock
        self.sleep = sleep
        self._lock = threading.Lock()
        self._proximo = None

    def esperar(self) -> None:
        with self._lock:
            ahora = self.clock()
            if self._proximo is None:
                self._proximo = ahora
            espera = self._proximo - ahora
            if espera > 0:
                self.sleep(espera)
                ahora = self._proximo
            self._proximo = max(ahora, self._proximo) + self.min_interval


def _item_ids(rubric: dict) -> list:
    return [item["id"] for item in rubric["items"]]


def _output_header(rubric: dict) -> list:
    return OUTPUT_HEADER_BASE + _item_ids(rubric) + ["riesgo", "motivo"]


def _estimar_tokens(request: dict) -> int:
    """Estimación conservadora: ceil(len(JSON de la petición) / 3)."""
    return math.ceil(len(json.dumps(request, ensure_ascii=False)) / 3)


def leer_entrada(path: str) -> list:
    """Lee y valida el CSV de entrada. Lanza `EntradaInvalidaError` si algo falla."""
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                raise EntradaInvalidaError(f"el CSV de entrada está vacío: {path}")
            faltantes = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
            if faltantes:
                raise EntradaInvalidaError(
                    f"faltan columnas requeridas en {path}: {', '.join(faltantes)}"
                )
            rows = list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise EntradaInvalidaError(f"no se puede leer {path} como CSV UTF-8: {exc}") from exc

    if not rows:
        raise EntradaInvalidaError(f"el CSV de entrada no tiene filas: {path}")

    seen_ids = set()
    for numero_fila, row in enumerate(rows, start=2):
        # DictReader pone None en las columnas que faltan y la clave None en las que sobran.
        if None in row or None in row.values():
            raise EntradaInvalidaError(
                f"fila {numero_fila}: número de campos distinto al de la cabecera"
            )
        row_id = (row.get("id") or "").strip()
        if not row_id:
            raise EntradaInvalidaError(f"fila {numero_fila}: el id está vacío")
        if row_id in seen_ids:
            raise EntradaInvalidaError(f"fila {numero_fila}: id repetido '{row_id}'")
        seen_ids.add(row_id)
        row["id"] = row_id
    return rows


def _leer_salida_previa(salida: str, header: list) -> dict:
    """Filas conservables (`ok`/`demasiado_larga`) de una salida previa, por id."""
    if not os.path.exists(salida):
        return {}
    with open(salida, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is not None and reader.fieldnames != header:
            raise SalidaInvalidaError(
                f"la salida existente {salida} tiene una cabecera distinta a la esperada"
            )
        conservadas = {}
        for row in reader:
            if row.get("estado") in (ESTADO_OK, ESTADO_DEMASIADO_LARGA):
                conservadas[row["id"]] = row
    return conservadas


def _escribir_conservadas(salida: str, header: list, rows: list) -> None:
    """Reescribe `salida` solo con `rows` (temporal + `os.replace`)."""
    directorio = os.path.dirname(os.path.abspath(salida)) or "."
    fd, tmp_path = tempfile.mkstemp(dir=directorio, prefix=".jevqa_tmp_", suffix=".csv")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        os.replace(tmp_path, salida)
    except BaseException:
        os.remove(tmp_path)
        raise


def _fila_vacia(salida: dict, item_ids: list) -> None:
    for item_id in item_ids:
        salida[item_id] = ""
    salida["riesgo"] = ""
    salida["motivo"] = ""


def _procesar_fila(row: dict, rubric: dict, cliente, item_ids: list, limiter: RateLimiter):
    """Anonimiza, llama a Jev y arma la fila de salida. Devuelve `(fila, hizo_llamada)`.

    `JevAuthError` se propaga sin capturar: aborta el lote (ver `auditar`).
    """
    salida_fila = {
        "id": row["id"],
        "agente": row.get("agente", ""),
        "campaña": row.get("campaña", ""),
        "fecha": row.get("fecha", ""),
    }

    names = [n for n in (row.get("agente"), row.get("cliente")) if n]
    texto_anonimo = anonymize(row.get("texto", ""), names)
    request = rubric_mod.build_request(rubric, texto_anonimo)

    if _estimar_tokens(request) > MAX_TOKENS:
        salida_fila["estado"] = ESTADO_DEMASIADO_LARGA
        salida_fila["detalle"] = "la interacción supera el límite de 32.000 tokens estimados"
        _fila_vacia(salida_fila, item_ids)
        return salida_fila, False

    limiter.esperar()
    try:
        raw = cliente.evaluate(request)
        parsed = rubric_mod.parse_response(rubric, raw)
    except JevAuthError:
        raise
    except Exception as exc:  # noqa: BLE001 - cualquier fallo de fila se registra y el lote sigue.
        salida_fila["estado"] = ESTADO_ERROR
        salida_fila["detalle"] = str(exc)
        _fila_vacia(salida_fila, item_ids)
        return salida_fila, True

    salida_fila["estado"] = ESTADO_OK
    salida_fila["detalle"] = ""
    for item_id in item_ids:
        salida_fila[item_id] = parsed[item_id]["probabilidad"]
    salida_fila["riesgo"] = parsed[rubric_mod.RIESGO_ID]["score"]
    salida_fila["motivo"] = parsed[rubric_mod.MOTIVO_ID]["choice"]
    return salida_fila, True


def auditar(
    entrada: str,
    salida: str,
    cliente,
    rubric: dict,
    *,
    max_workers: int = MAX_WORKERS,
    min_interval_seconds: float = MIN_INTERVAL_SECONDS,
    clock=time.monotonic,
    sleep=time.sleep,
) -> dict:
    """Audita `entrada` con `cliente` y escribe `salida`. Reanudable.

    Devuelve un resumen `{"ok", "error", "demasiado_larga", "saltadas",
    "llamadas"}` con los conteos de esta corrida: `saltadas` son las filas
    conservadas de una corrida anterior (0 llamadas para ellas); el resto
    cuenta las filas procesadas ahora.
    """
    rows = leer_entrada(entrada)
    item_ids = _item_ids(rubric)
    header = _output_header(rubric)
    ids_entrada = {row["id"] for row in rows}

    # Se conservan también las filas de ids que no están en esta entrada: ya
    # están pagadas y la salida no es de esta función para borrarlas.
    conservadas = _leer_salida_previa(salida, header)
    _escribir_conservadas(salida, header, list(conservadas.values()))

    resumen = {
        "ok": 0,
        "error": 0,
        "demasiado_larga": 0,
        "saltadas": len(ids_entrada & conservadas.keys()),
        "llamadas": 0,
    }

    pendientes = [row for row in rows if row["id"] not in conservadas]
    if not pendientes:
        return resumen

    limiter = RateLimiter(min_interval_seconds, clock=clock, sleep=sleep)

    with open(salida, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_procesar_fila, row, rubric, cliente, item_ids, limiter)
                for row in pendientes
            }
            try:
                for future in as_completed(futures):
                    fila, hizo_llamada = future.result()
                    if hizo_llamada:
                        resumen["llamadas"] += 1
                    resumen[fila["estado"]] += 1
                    writer.writerow(fila)
                    f.flush()
            except JevAuthError:
                executor.shutdown(cancel_futures=True)
                raise

    return resumen
