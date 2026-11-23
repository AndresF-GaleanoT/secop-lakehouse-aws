# SPDX-License-Identifier: AGPL-3.0-or-later
# ---------------------------------------------------------------------------
# IAM: un rol por servicio, con mínimo privilegio
# ---------------------------------------------------------------------------
locals {
  account_id = data.aws_caller_identity.actual.account_id
}

data "aws_iam_policy_document" "confianza" {
  for_each = {
    lambda        = "lambda.amazonaws.com"
    glue          = "glue.amazonaws.com"
    stepfunctions = "states.amazonaws.com"
    budgets       = "budgets.amazonaws.com"
  }

  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = [each.value]
    }
  }
}

# --- Lambda de ingesta: solo escribe en bronze/ -----------------------------
resource "aws_iam_role" "lambda_ingest" {
  name               = "secop-lambda-ingest"
  description        = "Allows Lambda functions to call AWS services on your behalf."
  assume_role_policy = data.aws_iam_policy_document.confianza["lambda"].json
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda_ingest.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_escribir_bronce" {
  name = "escribir-bronce"
  role = aws_iam_role.lambda_ingest.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "s3:PutObject"
      Resource = "${aws_s3_bucket.lake.arn}/bronze/*"
    }]
  })
}

# --- Glue: lee y escribe el lago y administra las tablas del catálogo -------
resource "aws_iam_role" "glue" {
  name               = "secop-glue"
  description        = "Allows Glue to call AWS services on your behalf. "
  assume_role_policy = data.aws_iam_policy_document.confianza["glue"].json
}

# Incluye lectura de los buckets aws-glue-* (scripts) y los logs de CloudWatch.
resource "aws_iam_role_policy_attachment" "glue_servicio" {
  role       = aws_iam_role.glue.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_iam_role_policy" "glue_lake_y_catalogo" {
  name = "lake-y-catalogo"
  role = aws_iam_role.glue.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "${aws_s3_bucket.lake.arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.lake.arn
      },
      {
        Effect = "Allow"
        Action = [
          "glue:GetDatabase", "glue:GetTable", "glue:GetTables",
          "glue:CreateTable", "glue:UpdateTable", "glue:DeleteTable",
        ]
        Resource = [
          "arn:aws:glue:${var.region}:${local.account_id}:catalog",
          "arn:aws:glue:${var.region}:${local.account_id}:database/${var.glue_database}",
          "arn:aws:glue:${var.region}:${local.account_id}:table/${var.glue_database}/*",
        ]
      },
    ]
  })
}

# --- Step Functions: invoca la Lambda y corre los dos jobs ------------------
resource "aws_iam_role" "stepfunctions" {
  name               = "secop-stepfunctions"
  description        = "Allows Step Functions to access AWS resources on your behalf."
  assume_role_policy = data.aws_iam_policy_document.confianza["stepfunctions"].json
}

resource "aws_iam_role_policy" "sfn_invocar_lambda" {
  name = "invocar-lambda"
  role = aws_iam_role.stepfunctions.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "InvocarLambdasDelPipeline"
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = [aws_lambda_function.ingest.arn, aws_lambda_function.web_export.arn]
    }]
  })
}

resource "aws_iam_role_policy" "sfn_ejecutar_glue" {
  name = "ejecutar-glue-pipeline"
  role = aws_iam_role.stepfunctions.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "EjecutarJobsGlueDelPipeline"
      Effect   = "Allow"
      Action   = ["glue:StartJobRun", "glue:GetJobRun", "glue:GetJobRuns", "glue:BatchStopJobRun"]
      Resource = [aws_glue_job.bronze_to_silver.arn, aws_glue_job.silver_to_gold.arn]
    }]
  })
}

# --- EventBridge Scheduler: solo puede iniciar el pipeline diario -----------
resource "aws_iam_role" "scheduler" {
  name        = "secop-scheduler"
  description = "EventBridge Scheduler inicia el pipeline diario SECOP"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = local.account_id } }
    }]
  })
}

resource "aws_iam_role_policy" "scheduler_iniciar_pipeline" {
  name = "iniciar-pipeline-diario"
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "IniciarPipelineDiario"
      Effect   = "Allow"
      Action   = "states:StartExecution"
      Resource = aws_sfn_state_machine.pipeline_diario.arn
    }]
  })
}

# --- Budgets: al llegar al 100 % aplica la política que bloquea el pipeline --
resource "aws_iam_role" "budgets_acciones" {
  name               = "secop-budgets-acciones"
  description        = "Allows Budgets to create and manage AWS resources on your behalf"
  assume_role_policy = data.aws_iam_policy_document.confianza["budgets"].json
}

resource "aws_iam_role_policy_attachment" "budgets_acciones" {
  role       = aws_iam_role.budgets_acciones.name
  policy_arn = "arn:aws:iam::aws:policy/AWSBudgetsActionsWithAWSResourceControlAccess"
}

# Política de "freno": niega iniciar ejecuciones, invocar la Lambda y correr Glue.
resource "aws_iam_policy" "bloquear_secop" {
  name = "loquear-secop" # nombre tal como se creó en la consola
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Deny"
      Action   = ["states:StartExecution", "lambda:InvokeFunction", "glue:StartJobRun"]
      Resource = "*"
    }]
  })
}
