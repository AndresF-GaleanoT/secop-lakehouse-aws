# SPDX-License-Identifier: AGPL-3.0-or-later
# ---------------------------------------------------------------------------
# Orquestación: Step Functions + EventBridge Scheduler
# Las definiciones ASL son los mismos JSON de la carpeta stepfunctions/.
# ---------------------------------------------------------------------------

# Descarga del histórico completo a bronce: Map con 3 Lambdas en paralelo (computación distribuida).
resource "aws_sfn_state_machine" "solo_bronce" {
  name       = "secop-solo-bronce"
  role_arn   = aws_iam_role.stepfunctions.arn
  type       = "STANDARD"
  definition = file("${path.module}/../stepfunctions/solo_bronce.asl.json")
}

# Pipeline diario: Lambda (últimos N días) -> bronze_to_silver (2 workers) -> silver_to_gold.
resource "aws_sfn_state_machine" "pipeline_diario" {
  name       = "secop-pipeline-diario"
  role_arn   = aws_iam_role.stepfunctions.arn
  type       = "STANDARD"
  definition = file("${path.module}/../stepfunctions/pipeline_diario.asl.json")
}

# Todos los días a las 6:00 a. m. hora Colombia.
resource "aws_scheduler_schedule" "pipeline_diario" {
  name                         = "secop-pipeline-diario-6am"
  description                  = "Pipeline diario SECOP: ultimos 10 dias, 6:00 a. m. hora Colombia"
  schedule_expression          = "cron(0 6 * * ? *)"
  schedule_expression_timezone = "America/Bogota"
  state                        = "ENABLED"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_sfn_state_machine.pipeline_diario.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ lookback_days = var.lookback_days })

    retry_policy {
      maximum_retry_attempts       = 2
      maximum_event_age_in_seconds = 3600
    }
  }
}
