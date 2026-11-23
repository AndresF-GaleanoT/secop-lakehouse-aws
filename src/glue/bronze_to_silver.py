# SPDX-License-Identifier: AGPL-3.0-or-later
"""Glue job: bronze (JSON crudo) -> silver (tabla Iceberg limpia, con MERGE/upsert).

Argumentos:
    --LAKE_BUCKET, --GLUE_DATABASE
    --SOURCE_PATH  ruta s3:// a leer. La carga diaria pasa la carpeta de ese día;
                   la carga histórica pasa todo bronze/secop_contratos/.
    --LOAD_ID      etiqueta de la carga (queda en la columna load_id).
"""

import json
import sys

from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark import SparkConf
from pyspark.context import SparkContext
from pyspark.sql import functions as F

from secop_transforms import critical_failures, normalize_contracts, quality_report

args = getResolvedOptions(sys.argv, ["JOB_NAME", "LAKE_BUCKET", "GLUE_DATABASE", "SOURCE_PATH", "LOAD_ID"])
bucket, database = args["LAKE_BUCKET"], args["GLUE_DATABASE"]
source_path, load_id = args["SOURCE_PATH"], args["LOAD_ID"]

# Catálogo Iceberg respaldado por el Glue Data Catalog.
conf = (
    SparkConf()
    .set("spark.sql.extensions", "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions")
    .set("spark.sql.catalog.glue_catalog", "org.apache.iceberg.spark.SparkCatalog")
    .set("spark.sql.catalog.glue_catalog.warehouse", f"s3://{bucket}/silver/")
    .set("spark.sql.catalog.glue_catalog.catalog-impl", "org.apache.iceberg.aws.glue.GlueCatalog")
    .set("spark.sql.catalog.glue_catalog.io-impl", "org.apache.iceberg.aws.s3.S3FileIO")
)
sc = SparkContext(conf=conf)
glue_context = GlueContext(sc)
spark = glue_context.spark_session
job = Job(glue_context)
job.init(args["JOB_NAME"], args)
logger = glue_context.get_logger()

table = f"glue_catalog.{database}.silver_contratos"

# recursiveFileLookup: lee todas las subcarpetas (load=...) sin interpretar particiones.
raw = spark.read.option("recursiveFileLookup", "true").json(source_path)
silver = normalize_contracts(raw, load_id).cache()

# --- Calidad de datos: las reglas críticas detienen el pipeline --------------
report = quality_report(silver)
logger.info(f"Reporte de calidad {load_id}: {json.dumps(report)}")
failures = critical_failures(report)
if failures:
    raise ValueError(f"Fallaron reglas críticas de calidad: {failures}")

# --- Escritura: crear la tabla la primera vez, luego MERGE (upsert) ----------
if not spark.catalog.tableExists(table):
    (
        silver.writeTo(table)
        .using("iceberg")
        .tableProperty("format-version", "2")
        .partitionedBy(F.months("fecha_firma"))  # particiones mensuales: consultas más baratas
        .create()
    )
    logger.info(f"Tabla {table} creada con {report['total_registros']} registros")
else:
    # Evolución de esquema: si plata ganó columnas nuevas, se agregan a la tabla antes del MERGE.
    # Iceberg lo hace sin reescribir datos; las filas existentes quedan en null hasta que el MERGE
    # las actualiza (la carga histórica las actualiza todas).
    existing = set(spark.table(table).columns)
    for field in silver.schema.fields:
        if field.name not in existing:
            spark.sql(f"ALTER TABLE {table} ADD COLUMN {field.name} {field.dataType.simpleString()}")
            logger.info(f"Columna nueva en {table}: {field.name}")
    silver.createOrReplaceTempView("updates")
    spark.sql(
        f"""
        MERGE INTO {table} AS t
        USING updates AS s
        ON t.id_contrato = s.id_contrato
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
        """
    )
    logger.info(f"MERGE en {table}: {report['total_registros']} registros procesados")

job.commit()
