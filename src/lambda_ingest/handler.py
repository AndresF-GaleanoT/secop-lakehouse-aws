# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ingesta de SECOP II (datos.gov.co, API Socrata) hacia la capa bronze.

Eventos de entrada:
    {}                                                -> carga diaria: el día anterior (hora Colombia)
    {"lookback_days": 90}                             -> los últimos 90 días hasta ayer (pipeline semanal:
                                                         la API publica con unos días de retraso)
    {"ingest_date": "2026-10-31"}                     -> un día puntual
    {"start_date": "2024-03-01", "end_date": "2024-03-31"}  -> un rango (carga histórica, por mes)
    {"missing_dates": true}                           -> contratos sin fecha de firma (también histórica)
Claves opcionales en cualquier evento:
    "workers": 4             -> hilos que descargan páginas en paralelo (por defecto, variable PARALLEL_PAGES)
    "bronze_prefix": "..."   -> otra carpeta de destino (la usa el benchmark de speedup)

Paralelismo (computación paralela):
    Con workers > 1, la Lambda cuenta primero los registros del tramo, reparte las páginas
    (offsets) entre un ThreadPoolExecutor y cada hilo descarga su página y la escribe en S3.
    La descarga es limitada por red (I/O), así que los hilos sí avanzan en paralelo.
    Con workers = 1 se comporta como la versión secuencial original.
Distribución (computación distribuida):
    Step Functions ejecuta varias Lambdas a la vez, una por tramo (MaxConcurrency del Map).

Cada página de la API se escribe como un archivo aparte en
    bronze/secop_contratos/load=<load_id>/part-00000.jsonl.gz
así la memoria de la Lambda no crece con el volumen.

Salida (la usa Step Functions; pages, workers y seconds sirven para medir el speedup):
    {"load_id": "...", "records": 1234, "s3_prefix": "...", "pages": 3, "workers": 4, "seconds": 12.3}

Solo usa la librería estándar y boto3 (incluido en el runtime de Lambda).
"""

from __future__ import annotations

import gzip
import http.client
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SOCRATA_BASE_URL = "https://www.datos.gov.co/resource"
# Contratos por página (y por archivo en bronce). Con 91 columnas, 50.000 por página supera
# 1 GB de memoria en la Lambda; 10.000 usa unos 200 MB. Se puede cambiar con la variable PAGE_SIZE.
PAGE_SIZE = int(os.environ.get("PAGE_SIZE", "10000"))
# Hilos que descargan páginas a la vez. Cada hilo tiene una página en memoria (~200 MB con 10.000
# contratos), así que 4 hilos necesitan ~2 GB de memoria en la Lambda.
PARALLEL_PAGES = int(os.environ.get("PARALLEL_PAGES", "1"))
COLOMBIA_TZ = timezone(timedelta(hours=-5))
MAX_RETRIES = 4


@dataclass(frozen=True)
class LoadWindow:
    """Qué registros traer y con qué nombre guardarlos."""

    load_id: str
    start: date | None = None
    end: date | None = None
    missing_dates: bool = False


def resolve_window(event: dict | None, now: datetime | None = None) -> LoadWindow:
    event = event or {}
    if event.get("missing_dates"):
        return LoadWindow(load_id="sin-fecha", missing_dates=True)
    if event.get("start_date"):
        start = date.fromisoformat(event["start_date"])
        end = date.fromisoformat(event.get("end_date") or event["start_date"])
        if end < start:
            raise ValueError(f"end_date ({end}) es anterior a start_date ({start})")
        return LoadWindow(load_id=f"rango-{start}_{end}", start=start, end=end)
    now = now or datetime.now(COLOMBIA_TZ)
    yesterday = (now.astimezone(COLOMBIA_TZ) - timedelta(days=1)).date()
    if event.get("lookback_days"):
        days = int(event["lookback_days"])
        if days < 1:
            raise ValueError("lookback_days debe ser al menos 1")
        start = yesterday - timedelta(days=days - 1)
        return LoadWindow(load_id=f"diaria-{start}_{yesterday}", start=start, end=yesterday)
    day = date.fromisoformat(event["ingest_date"]) if event.get("ingest_date") else yesterday
    return LoadWindow(load_id=f"diaria-{day}", start=day, end=day)


def build_where(field: str, window: LoadWindow, department: str = "") -> str:
    """Cláusula SoQL $where para la ventana y el filtro de departamento."""
    if window.missing_dates:
        where = f"{field} IS NULL"
    else:
        where = f"{field} between '{window.start}T00:00:00' and '{window.end}T23:59:59.999'"
    if department:
        escaped = department.replace("'", "''")  # comillas escapadas según SoQL
        where += f" AND departamento = '{escaped}'"
    return where


def build_query(where: str, limit: int, offset: int) -> dict[str, str]:
    return {
        "$where": where,
        "$order": ":id",  # orden estable para paginar sin duplicados
        "$limit": str(limit),
        "$offset": str(offset),
    }


def fetch_page(dataset_id: str, params: dict[str, str], opener=urllib.request.urlopen) -> list[dict]:
    """Descarga una página con reintentos y backoff exponencial."""
    url = f"{SOCRATA_BASE_URL}/{dataset_id}.json?{urllib.parse.urlencode(params)}"
    # gzip reduce unas 10 veces los bytes que viajan por la red.
    headers = {"Accept": "application/json", "Accept-Encoding": "gzip", "User-Agent": "secop-lakehouse/1.0"}
    app_token = os.environ.get("SOCRATA_APP_TOKEN")
    if app_token:
        headers["X-App-Token"] = app_token

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            request = urllib.request.Request(url, headers=headers)
            with opener(request, timeout=300) as response:
                body = response.read()
                if (response.headers.get("Content-Encoding") or "").lower() == "gzip":
                    body = gzip.decompress(body)
                return json.loads(body)  # json acepta bytes: evita una copia extra del texto
        # URLError incluye HTTPError (429, 5xx); ConnectionError y HTTPException cubren cortes de la
        # API como "Remote end closed connection without response" o respuestas incompletas.
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException) as exc:
            if attempt == MAX_RETRIES:
                raise
            wait = 2**attempt
            logger.warning("Intento %s falló (%s). Reintentando en %ss", attempt, exc, wait)
            time.sleep(wait)
    return []  # inalcanzable; satisface al type checker


def iter_pages(dataset_id: str, where: str, fetch=fetch_page, page_size: int = PAGE_SIZE):
    """Genera las páginas una por una hasta la última (más corta que page_size)."""
    offset = 0
    while True:
        page = fetch(dataset_id, build_query(where, page_size, offset))
        logger.info("Página offset=%s: %s registros", offset, len(page))
        if page:
            yield page
        if len(page) < page_size:
            return
        offset += page_size


def count_rows(dataset_id: str, where: str, fetch=fetch_page) -> int:
    """Cuántos registros tiene el tramo (lo calcula el servidor de la API)."""
    result = fetch(dataset_id, {"$select": "count(*) as n", "$where": where})
    return int(result[0]["n"]) if result else 0


def download_parallel(dataset_id: str, where: str, write, workers: int, fetch=fetch_page,
                      page_size: int = PAGE_SIZE) -> tuple[int, int]:
    """Descarga las páginas del tramo con `workers` hilos. `write(part, page)` guarda cada página.

    1. Cuenta los registros y calcula los offsets de todas las páginas.
    2. Reparte los offsets entre los hilos: cada uno descarga y escribe su página.
    3. Si la API recibió registros nuevos entre el conteo y la descarga (la última página llegó
       llena), sigue de forma secuencial hasta encontrar una página incompleta.
    Devuelve (registros, páginas).
    """
    total = count_rows(dataset_id, where, fetch)
    offsets = list(range(0, total, page_size))

    def job(item: tuple[int, int]) -> int:
        part, offset = item
        page = fetch(dataset_id, build_query(where, page_size, offset))
        if page:
            write(part, page)
        logger.info("Página %s (offset=%s): %s registros", part, offset, len(page))
        return len(page)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        sizes = list(pool.map(job, enumerate(offsets)))

    records, pages = sum(sizes), sum(1 for s in sizes if s)
    part, offset = len(offsets), len(offsets) * page_size
    while not sizes or sizes[-1] == page_size:  # registros llegados después del conteo
        size = job((part, offset))
        if not size:
            break
        records, pages = records + size, pages + 1
        sizes.append(size)
        part, offset = part + 1, offset + page_size
    return records, pages


def to_jsonl_gz(rows: list[dict]) -> bytes:
    """Serializa a JSON Lines comprimido (formato eficiente para Spark)."""
    body = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    return gzip.compress(body.encode("utf-8"))


def load_prefix(prefix: str, load_id: str) -> str:
    return f"{prefix}/load={load_id}/"


def lambda_handler(event, context, s3_client=None, fetch=fetch_page, page_size: int = PAGE_SIZE):
    started = time.perf_counter()
    event = event or {}
    bucket = os.environ["LAKE_BUCKET"]
    dataset_id = os.environ.get("DATASET_ID", "jbjy-vk9h")
    field = os.environ.get("INCREMENTAL_FIELD", "fecha_de_firma")
    prefix = event.get("bronze_prefix") or os.environ.get("BRONZE_PREFIX", "bronze/secop_contratos")
    department = os.environ.get("DEPARTMENT_FILTER", "").strip()
    workers = max(1, int(event.get("workers") or PARALLEL_PAGES))

    window = resolve_window(event)
    where = build_where(field, window, department)
    s3_prefix = load_prefix(prefix, window.load_id)
    logger.info("Carga %s de %s con %s hilo(s): %s", window.load_id, dataset_id, workers, where)

    if s3_client is None:
        import boto3  # import diferido: los tests no necesitan boto3

        s3_client = boto3.client("s3")  # los clientes de boto3 se pueden usar desde varios hilos

    def write(part: int, page: list[dict]) -> None:
        s3_client.put_object(
            Bucket=bucket,
            Key=f"{s3_prefix}part-{part:05d}.jsonl.gz",
            Body=to_jsonl_gz(page),
            ContentType="application/x-ndjson",
            ContentEncoding="gzip",
        )

    if workers > 1:
        records, pages = download_parallel(dataset_id, where, write, workers, fetch=fetch, page_size=page_size)
    else:
        records = pages = 0
        for part, page in enumerate(iter_pages(dataset_id, where, fetch=fetch, page_size=page_size)):
            write(part, page)
            records, pages = records + len(page), pages + 1

    seconds = round(time.perf_counter() - started, 2)
    logger.info("Carga %s terminada: %s registros, %s páginas, %s hilo(s), %s s en s3://%s/%s",
                window.load_id, records, pages, workers, seconds, bucket, s3_prefix)
    return {"load_id": window.load_id, "records": records, "s3_prefix": s3_prefix,
            "pages": pages, "workers": workers, "seconds": seconds}
