# SPDX-License-Identifier: AGPL-3.0-or-later
"""Exporta las tablas oro a archivos JSON que lee la web (S3 + CloudFront).

Corre al final del pipeline diario, después de silver_to_gold. Cada consulta de Athena lee agregados
de oro (y dos columnas de plata), así que escanea pocos MB. La web solo descarga estos archivos: las
visitas nunca consultan Athena, y el costo no crece con el tráfico.

Archivos que escribe en s3://<WEB_BUCKET>/data/ (meta.json va de último):
    resumen, anual, mensual, sectores, departamentos, entidades, ley_diario, ley_periodos, meta

Formato (compacto; la web lo convierte en filas):
    {"columnas": ["anio", "contratos", ...], "filas": [[2016, 560441, ...], ...]}

Variables de entorno:
    WEB_BUCKET        bucket de la web (obligatoria en Lambda)
    WEB_PREFIX        carpeta de los datos dentro del bucket (por defecto "data/")
    ATHENA_WORKGROUP  workgroup de Athena del proyecto (por defecto "secop")
    GLUE_DATABASE     base del catálogo (por defecto "secop_lakehouse_db")

Uso local (escribe en una carpeta en vez de S3; necesita boto3 y el AWS CLI configurado):
    python src/lambda_web_export/handler.py --destino web/data

Solo usa la librería estándar y boto3 (incluido en el runtime de Lambda).
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

WEB_BUCKET = os.environ.get("WEB_BUCKET", "")
WEB_PREFIX = os.environ.get("WEB_PREFIX", "data/")
WORKGROUP = os.environ.get("ATHENA_WORKGROUP", "secop")
DATABASE = os.environ.get("GLUE_DATABASE", "secop_lakehouse_db")
# CloudFront y el navegador guardan los datos 15 minutos: después de cada carga la web se pone al día sola.
CACHE_CONTROL = "public, max-age=900"
LIMITE_SEGUNDOS_CONSULTA = 300

DIRECTA = "COALESCE(es_contratacion_directa, false)"
# Solo años con sentido para las series: SECOP II arranca en 2015 y hay fechas de firma mal digitadas.
ANIOS_VALIDOS = "anio BETWEEN 2015 AND year(current_date)"

CONSULTAS: dict[str, str] = {
    # Plata: contratos únicos y fecha del contrato más reciente (sin fechas futuras mal digitadas).
    "resumen": """
        SELECT COUNT(*) AS contratos,
               SUM(CASE WHEN fecha_firma IS NULL THEN 1 ELSE 0 END) AS contratos_sin_fecha_firma,
               MAX(CASE WHEN fecha_firma <= current_date THEN fecha_firma END) AS ultima_fecha_firma
        FROM silver_contratos""",
    # Objetivo 1: panorama.
    "anual": f"""
        SELECT anio,
               SUM(contratos) AS contratos,
               SUM(CASE WHEN {DIRECTA} THEN contratos ELSE 0 END) AS contratos_directa,
               SUM(valor_total) AS valor_total,
               SUM(CASE WHEN {DIRECTA} THEN valor_total END) AS valor_directa,
               SUM(contratos_valor_no_confiable) AS contratos_valor_no_confiable
        FROM gold_panorama_contratacion
        WHERE {ANIOS_VALIDOS}
        GROUP BY anio
        ORDER BY anio""",
    "mensual": f"""
        SELECT anio, mes,
               SUM(contratos) AS contratos,
               SUM(CASE WHEN {DIRECTA} THEN contratos ELSE 0 END) AS contratos_directa,
               SUM(valor_total) AS valor_total
        FROM gold_panorama_contratacion
        WHERE {ANIOS_VALIDOS} AND (anio < year(current_date) OR mes <= month(current_date))
        GROUP BY anio, mes
        ORDER BY anio, mes""",
    "sectores": f"""
        SELECT COALESCE(sector, 'NO DEFINIDO') AS sector,
               SUM(contratos) AS contratos,
               SUM(CASE WHEN {DIRECTA} THEN contratos ELSE 0 END) AS contratos_directa,
               SUM(valor_total) AS valor_total
        FROM gold_panorama_contratacion
        GROUP BY COALESCE(sector, 'NO DEFINIDO')
        ORDER BY valor_total DESC""",
    # Objetivo 2: índice de patrones irregulares.
    "departamentos": """
        SELECT * FROM gold_riesgo_departamentos ORDER BY posicion_ranking""",
    "entidades": """
        WITH ley AS (
            SELECT nit_entidad,
                   SUM(CASE WHEN periodo = '0_mismo_mes_2025_sin_elecciones'
                            THEN contratos_directos_no_exceptuados ELSE 0 END) AS ley_sin_excepcion_2025,
                   SUM(CASE WHEN periodo = '1_mes_antes_de_la_restriccion'
                            THEN contratos_directos_no_exceptuados ELSE 0 END) AS ley_sin_excepcion_antes,
                   SUM(CASE WHEN periodo = '2_restriccion'
                            THEN contratos_directos_no_exceptuados ELSE 0 END) AS ley_sin_excepcion_restriccion,
                   SUM(CASE WHEN periodo = '2_restriccion'
                            THEN contratos_directos_exceptuados ELSE 0 END) AS ley_exceptuados_restriccion,
                   SUM(CASE WHEN periodo = '2_restriccion'
                            THEN valor_directos_no_exceptuados END) AS ley_valor_sin_excepcion_restriccion
            FROM gold_ley_garantias_entidades
            GROUP BY nit_entidad
        )
        SELECT e.nit_entidad, e.nombre_entidad, e.departamento, e.contratos, e.valor_total,
               e.contratos_con_alerta, e.contratos_contratacion_directa, e.contratos_fin_de_semana,
               e.contratos_inicio_antes_de_firma, e.contratos_valor_atipico,
               e.contratos_posible_fraccionamiento, e.contratos_concentracion, e.contratos_adiciones_altas,
               e.contratos_contratista_no_identificado, e.contratos_anticipo_alto,
               e.pct_valor_mayor_contratista, e.pct_contratos_con_alerta, e.pct_contratacion_directa,
               e.posicion_ranking,
               COALESCE(l.ley_sin_excepcion_2025, 0) AS ley_sin_excepcion_2025,
               COALESCE(l.ley_sin_excepcion_antes, 0) AS ley_sin_excepcion_antes,
               COALESCE(l.ley_sin_excepcion_restriccion, 0) AS ley_sin_excepcion_restriccion,
               COALESCE(l.ley_exceptuados_restriccion, 0) AS ley_exceptuados_restriccion,
               l.ley_valor_sin_excepcion_restriccion
        FROM gold_riesgo_entidades e
        LEFT JOIN ley l ON e.nit_entidad = l.nit_entidad
        WHERE e.nombre_entidad IS NOT NULL
        ORDER BY e.contratos DESC""",
    # Objetivo 3: Ley de Garantías 2026.
    "ley_diario": f"""
        SELECT fecha_firma,
               SUM(CASE WHEN NOT {DIRECTA} THEN contratos ELSE 0 END) AS no_directa,
               SUM(CASE WHEN {DIRECTA} AND exceptuado_ley_garantias THEN contratos ELSE 0 END)
                   AS directa_exceptuada,
               SUM(CASE WHEN {DIRECTA} AND NOT exceptuado_ley_garantias THEN contratos ELSE 0 END)
                   AS directa_sin_excepcion
        FROM gold_ley_garantias_diario
        WHERE fecha_firma <= current_date
        GROUP BY fecha_firma
        ORDER BY fecha_firma""",
    "ley_periodos": f"""
        SELECT periodo,
               SUM(CASE WHEN {DIRECTA} AND NOT exceptuado_ley_garantias THEN contratos ELSE 0 END)
                   AS directa_sin_excepcion,
               SUM(CASE WHEN {DIRECTA} AND exceptuado_ley_garantias THEN contratos ELSE 0 END)
                   AS directa_exceptuada,
               SUM(CASE WHEN {DIRECTA} AND NOT exceptuado_ley_garantias THEN valor_total END)
                   AS valor_sin_excepcion
        FROM gold_ley_garantias_diario
        WHERE periodo IS NOT NULL
        GROUP BY periodo
        ORDER BY periodo""",
}

# Tipos de Athena que no son texto. Las fechas y los textos se quedan como cadenas.
_CONVERTIR = {
    "tinyint": int,
    "smallint": int,
    "integer": int,
    "bigint": int,
    "float": float,
    "real": float,
    "double": float,
    "decimal": float,
    "boolean": lambda v: v == "true",
}

athena = boto3.client("athena")
s3 = boto3.client("s3")


def _iniciar(sql: str) -> str:
    return athena.start_query_execution(
        QueryString=sql,
        WorkGroup=WORKGROUP,
        QueryExecutionContext={"Database": DATABASE},
    )["QueryExecutionId"]


def _esperar(nombre: str, qid: str) -> dict:
    inicio = time.monotonic()
    while True:
        ejecucion = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]
        estado = ejecucion["Status"]["State"]
        if estado == "SUCCEEDED":
            return ejecucion
        if estado in ("FAILED", "CANCELLED"):
            motivo = ejecucion["Status"].get("StateChangeReason", "sin detalle")
            raise RuntimeError(f"La consulta '{nombre}' terminó en {estado}: {motivo}")
        if time.monotonic() - inicio > LIMITE_SEGUNDOS_CONSULTA:
            athena.stop_query_execution(QueryExecutionId=qid)
            raise TimeoutError(f"La consulta '{nombre}' pasó de {LIMITE_SEGUNDOS_CONSULTA} s")
        time.sleep(1)


def _resultados(qid: str) -> dict:
    """Lee el resultado completo en formato columnas + filas, con números y booleanos ya convertidos."""
    paginas = athena.get_paginator("get_query_results").paginate(
        QueryExecutionId=qid, PaginationConfig={"PageSize": 1000}
    )
    columnas: list[str] = []
    conversores: list = []
    filas: list[list] = []
    for pagina in paginas:
        resultado = pagina["ResultSet"]
        datos = resultado["Rows"]
        if not columnas:
            info = resultado["ResultSetMetadata"]["ColumnInfo"]
            columnas = [c["Name"] for c in info]
            conversores = [_CONVERTIR.get(c["Type"], str) for c in info]
            datos = datos[1:]  # la primera fila de la primera página trae los encabezados
        for fila in datos:
            filas.append(
                [
                    conv(celda["VarCharValue"]) if "VarCharValue" in celda else None
                    for celda, conv in zip(fila["Data"], conversores)
                ]
            )
    return {"columnas": columnas, "filas": filas}


def _guardar(nombre: str, contenido: dict, destino: Path | None) -> int:
    cuerpo = json.dumps(contenido, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if destino is not None:
        (destino / f"{nombre}.json").write_bytes(cuerpo)
    else:
        s3.put_object(
            Bucket=WEB_BUCKET,
            Key=f"{WEB_PREFIX}{nombre}.json",
            Body=cuerpo,
            ContentType="application/json; charset=utf-8",
            CacheControl=CACHE_CONTROL,
        )
    return len(cuerpo)


def exportar(destino: Path | None = None) -> dict:
    """Corre todas las consultas a la vez en Athena y guarda un JSON por consulta, más meta.json."""
    if destino is None and not WEB_BUCKET:
        raise ValueError("Falta la variable de entorno WEB_BUCKET")
    if destino is not None:
        destino.mkdir(parents=True, exist_ok=True)

    inicio = time.monotonic()
    ids = {nombre: _iniciar(sql) for nombre, sql in CONSULTAS.items()}  # Athena las corre en paralelo

    archivos, bytes_escaneados = {}, 0
    for nombre, qid in ids.items():
        ejecucion = _esperar(nombre, qid)
        bytes_escaneados += ejecucion["Statistics"].get("DataScannedInBytes", 0)
        contenido = _resultados(qid)
        archivos[nombre] = {"filas": len(contenido["filas"]), "bytes": _guardar(nombre, contenido, destino)}
        logger.info("%s: %d filas", nombre, len(contenido["filas"]))

    meta = {
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "archivos": archivos,
        "mb_escaneados_athena": round(bytes_escaneados / 1_048_576, 1),
        "segundos": round(time.monotonic() - inicio, 1),
    }
    _guardar("meta", meta, destino)  # de último: si algo falla antes, la web sigue con los datos de ayer
    return meta


def lambda_handler(event, context):
    meta = exportar()
    logger.info(json.dumps(meta))
    return {k: meta[k] for k in ("generado", "mb_escaneados_athena", "segundos")}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Exporta las tablas oro a JSON para la web")
    parser.add_argument("--destino", type=Path, required=True, help="carpeta local de salida, p. ej. web/data")
    print(json.dumps(exportar(parser.parse_args().destino), indent=2, ensure_ascii=False))
