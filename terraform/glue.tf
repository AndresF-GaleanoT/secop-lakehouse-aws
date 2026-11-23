# SPDX-License-Identifier: AGPL-3.0-or-later
# ---------------------------------------------------------------------------
# Glue: catálogo y los dos jobs Spark (Glue 5.0, Iceberg, ejecución Flex)
# Las tablas silver_contratos y gold_* las crean los propios jobs (Spark + Iceberg),
# por eso no se declaran aquí.
# ---------------------------------------------------------------------------
resource "aws_glue_catalog_database" "lakehouse" {
  name = var.glue_database
}

locals {
  glue_default_arguments = {
    "--datalake-formats"             = "iceberg"
    "--extra-py-files"               = "s3://${aws_s3_bucket.lake.id}/${aws_s3_object.secop_transforms.key}"
    "--LAKE_BUCKET"                  = aws_s3_bucket.lake.id
    "--GLUE_DATABASE"                = aws_glue_catalog_database.lakehouse.name
    "--conf"                         = "spark.eventLog.rolling.enabled=true --conf spark.sql.catalog.glue_catalog.glue.skip-name-validation=true"
    "--job-language"                 = "python"
    "--job-bookmark-option"          = "job-bookmark-disable"
    "--TempDir"                      = "s3://${var.glue_assets_bucket}/temporary/"
    "--enable-metrics"               = ""
    "--enable-spark-ui"              = "true"
    "--spark-event-logs-path"        = "s3://${var.glue_assets_bucket}/sparkHistoryLogs/"
    "--enable-job-insights"          = "true"
    "--enable-observability-metrics" = "true"
  }
}

# Bronce -> plata: limpia, tipa, valida calidad y hace MERGE INTO en silver_contratos.
resource "aws_glue_job" "bronze_to_silver" {
  name              = "secop-bronze-to-silver"
  role_arn          = aws_iam_role.glue.arn
  glue_version      = "5.0"
  worker_type       = "G.1X"
  number_of_workers = 10 # carga histórica; el pipeline semanal lo baja a 2
  timeout           = 60
  max_retries       = 0
  execution_class   = "FLEX" # 0,29 USD/DPU-h en lugar de 0,44

  command {
    name            = "glueetl"
    script_location = "s3://${var.glue_assets_bucket}/${aws_s3_object.job_bronze_to_silver.key}"
    python_version  = "3"
  }

  execution_property {
    max_concurrent_runs = 1
  }

  default_arguments = merge(local.glue_default_arguments, {
    "--SOURCE_PATH" = "s3://${aws_s3_bucket.lake.id}/bronze/secop_contratos/"
    "--LOAD_ID"     = "historica"
  })
}

# Plata -> oro: reconstruye las 6 tablas de los tres objetivos.
resource "aws_glue_job" "silver_to_gold" {
  name              = "secop-silver-to-gold"
  role_arn          = aws_iam_role.glue.arn
  glue_version      = "5.0"
  worker_type       = "G.1X"
  number_of_workers = 5
  timeout           = 60
  max_retries       = 0
  execution_class   = "FLEX"

  command {
    name            = "glueetl"
    script_location = "s3://${var.glue_assets_bucket}/${aws_s3_object.job_silver_to_gold.key}"
    python_version  = "3"
  }

  execution_property {
    max_concurrent_runs = 1
  }

  default_arguments = local.glue_default_arguments
}
