# SPDX-License-Identifier: AGPL-3.0-or-later
# ---------------------------------------------------------------------------
# Lambda de ingesta: API de datos.gov.co -> S3 bronce (ThreadPoolExecutor con N hilos)
# ---------------------------------------------------------------------------
# La consola espera el archivo lambda_function.py (handler lambda_function.lambda_handler).
data "archive_file" "lambda_ingest" {
  type        = "zip"
  output_path = "${path.module}/build/secop-ingest.zip"

  source {
    content  = file("${path.module}/../src/lambda_ingest/handler.py")
    filename = "lambda_function.py"
  }
}

resource "aws_lambda_function" "ingest" {
  function_name    = "secop-ingest"
  role             = aws_iam_role.lambda_ingest.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "lambda_function.lambda_handler"
  filename         = data.archive_file.lambda_ingest.output_path
  source_code_hash = data.archive_file.lambda_ingest.output_base64sha256

  memory_size = 2048 # 4 hilos x ~200 MB por página de 10.000 contratos
  timeout     = 900  # máximo de Lambda (15 min)

  environment {
    variables = {
      LAKE_BUCKET       = aws_s3_bucket.lake.id
      DATASET_ID        = "jbjy-vk9h"
      INCREMENTAL_FIELD = "fecha_de_firma"
      BRONZE_PREFIX     = "bronze/secop_contratos"
      PARALLEL_PAGES    = tostring(var.parallel_pages)
      SOCRATA_APP_TOKEN = var.socrata_app_token
    }
  }
}
