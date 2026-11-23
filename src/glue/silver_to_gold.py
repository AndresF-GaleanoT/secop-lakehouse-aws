# SPDX-License-Identifier: AGPL-3.0-or-later
"""Glue job: plata -> oro (Iceberg). Una tabla (o dos) por objetivo de análisis.

  Objetivo 1  gold_panorama_contratacion
  Objetivo 2  gold_alertas_contratos, gold_riesgo_entidades, gold_riesgo_departamentos
  Objetivo 3  gold_ley_garantias_diario, gold_ley_garantias_entidades

Reconstruye todas las tablas en cada ejecución: son agregados, así que es simple y barato.

Argumentos: --LAKE_BUCKET, --GLUE_DATABASE
"""

import sys

from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark import SparkConf
from pyspark.context import SparkContext

from secop_transforms import (
    build_alertas,
    build_ley_garantias_diario,
    build_ley_garantias_entidades,
    build_panorama,
    build_riesgo_departamentos,
    build_riesgo_entidades,
)

args = getResolvedOptions(sys.argv, ["JOB_NAME", "LAKE_BUCKET", "GLUE_DATABASE"])
bucket, database = args["LAKE_BUCKET"], args["GLUE_DATABASE"]

conf = (
    SparkConf()
    .set("spark.sql.extensions", "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions")
    .set("spark.sql.catalog.glue_catalog", "org.apache.iceberg.spark.SparkCatalog")
    .set("spark.sql.catalog.glue_catalog.warehouse", f"s3://{bucket}/gold/")
    .set("spark.sql.catalog.glue_catalog.catalog-impl", "org.apache.iceberg.aws.glue.GlueCatalog")
    .set("spark.sql.catalog.glue_catalog.io-impl", "org.apache.iceberg.aws.s3.S3FileIO")
)
sc = SparkContext(conf=conf)
glue_context = GlueContext(sc)
spark = glue_context.spark_session
job = Job(glue_context)
job.init(args["JOB_NAME"], args)
logger = glue_context.get_logger()

silver = spark.table(f"glue_catalog.{database}.silver_contratos").cache()
alertas = build_alertas(silver).cache()

gold_tables = {
    # Objetivo 1
    "gold_panorama_contratacion": build_panorama(silver),
    # Objetivo 2
    "gold_alertas_contratos": alertas,
    "gold_riesgo_entidades": build_riesgo_entidades(alertas),
    "gold_riesgo_departamentos": build_riesgo_departamentos(alertas),
    # Objetivo 3
    "gold_ley_garantias_diario": build_ley_garantias_diario(silver),
    "gold_ley_garantias_entidades": build_ley_garantias_entidades(silver),
}

for name, df in gold_tables.items():
    table = f"glue_catalog.{database}.{name}"
    df.writeTo(table).using("iceberg").tableProperty("format-version", "2").createOrReplace()
    logger.info(f"{table} actualizada")

job.commit()
