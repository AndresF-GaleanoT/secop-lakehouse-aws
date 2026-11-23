# SPDX-License-Identifier: AGPL-3.0-or-later
# ---------------------------------------------------------------------------
# Ingeniería inversa: estos bloques "adoptan" en el estado de Terraform los recursos que ya
# existen en la cuenta (creados a mano en la consola), sin recrearlos.
# Después del primer `terraform apply` exitoso se pueden borrar: ya quedan en el estado.
# Para desplegar el proyecto en una cuenta NUEVA, borra este archivo antes de aplicar.
# ---------------------------------------------------------------------------
# S3
import {
  to = aws_s3_bucket.lake
  id = "secop-lake-811136731365"
}
import {
  to = aws_s3_bucket_server_side_encryption_configuration.lake
  id = "secop-lake-811136731365"
}
import {
  to = aws_s3_bucket_public_access_block.lake
  id = "secop-lake-811136731365"
}
import {
  to = aws_s3_object.secop_transforms
  id = "secop-lake-811136731365/glue-scripts/secop_transforms.py"
}
import {
  to = aws_s3_object.job_bronze_to_silver
  id = "aws-glue-assets-811136731365-us-east-1/scripts/secop-bronze-to-silver.py"
}
import {
  to = aws_s3_object.job_silver_to_gold
  id = "aws-glue-assets-811136731365-us-east-1/scripts/secop-silver-to-gold.py"
}

# IAM
import {
  to = aws_iam_role.lambda_ingest
  id = "secop-lambda-ingest"
}
import {
  to = aws_iam_role_policy_attachment.lambda_logs
  id = "secop-lambda-ingest/arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}
import {
  to = aws_iam_role_policy.lambda_escribir_bronce
  id = "secop-lambda-ingest:escribir-bronce"
}
import {
  to = aws_iam_role.glue
  id = "secop-glue"
}
import {
  to = aws_iam_role_policy_attachment.glue_servicio
  id = "secop-glue/arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}
import {
  to = aws_iam_role_policy.glue_lake_y_catalogo
  id = "secop-glue:lake-y-catalogo"
}
import {
  to = aws_iam_role.stepfunctions
  id = "secop-stepfunctions"
}
import {
  to = aws_iam_role_policy.sfn_invocar_lambda
  id = "secop-stepfunctions:invocar-lambda"
}
import {
  to = aws_iam_role_policy.sfn_ejecutar_glue
  id = "secop-stepfunctions:ejecutar-glue-pipeline"
}
import {
  to = aws_iam_role.scheduler
  id = "secop-scheduler"
}
import {
  to = aws_iam_role_policy.scheduler_iniciar_pipeline
  id = "secop-scheduler:iniciar-pipeline-diario"
}
import {
  to = aws_iam_role.budgets_acciones
  id = "secop-budgets-acciones"
}
import {
  to = aws_iam_role_policy_attachment.budgets_acciones
  id = "secop-budgets-acciones/arn:aws:iam::aws:policy/AWSBudgetsActionsWithAWSResourceControlAccess"
}
import {
  to = aws_iam_policy.bloquear_secop
  id = "arn:aws:iam::811136731365:policy/loquear-secop"
}

# Lambda, Glue, Step Functions, Scheduler, Athena
import {
  to = aws_lambda_function.ingest
  id = "secop-ingest"
}
import {
  to = aws_glue_catalog_database.lakehouse
  id = "811136731365:secop_lakehouse_db"
}
import {
  to = aws_glue_job.bronze_to_silver
  id = "secop-bronze-to-silver"
}
import {
  to = aws_glue_job.silver_to_gold
  id = "secop-silver-to-gold"
}
import {
  to = aws_sfn_state_machine.solo_bronce
  id = "arn:aws:states:us-east-1:811136731365:stateMachine:secop-solo-bronce"
}
import {
  to = aws_sfn_state_machine.pipeline_diario
  id = "arn:aws:states:us-east-1:811136731365:stateMachine:secop-pipeline-diario"
}
import {
  to = aws_scheduler_schedule.pipeline_diario
  id = "default/secop-pipeline-diario-6am"
}
import {
  to = aws_athena_workgroup.secop
  id = "secop"
}

# Budgets
import {
  to = aws_budgets_budget.secop
  id = "811136731365:limite-secop-15usd"
}
import {
  to = aws_budgets_budget_action.freno
  id = "811136731365:c45bc528-d4c1-4a9d-88ce-658c65bd8c29:limite-secop-15usd"
}

# Web de resultados (creada con la AWS CLI el 23 de noviembre de 2026)
import {
  to = aws_s3_bucket.web
  id = "secop-web-811136731365"
}
import {
  to = aws_s3_bucket_server_side_encryption_configuration.web
  id = "secop-web-811136731365"
}
import {
  to = aws_s3_bucket_public_access_block.web
  id = "secop-web-811136731365"
}
import {
  to = aws_s3_bucket_policy.web
  id = "secop-web-811136731365"
}
import {
  to = aws_cloudfront_origin_access_control.web
  id = "E31H6LJ20VRCXC"
}
import {
  to = aws_cloudfront_distribution.web
  id = "EXY065CPYI3J"
}
import {
  to = aws_iam_role.web_export
  id = "secop-web-export"
}
import {
  to = aws_iam_role_policy_attachment.web_export_logs
  id = "secop-web-export/arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}
import {
  to = aws_iam_role_policy.web_export
  id = "secop-web-export:exportar-oro-a-web"
}
import {
  to = aws_lambda_function.web_export
  id = "secop-web-export"
}
