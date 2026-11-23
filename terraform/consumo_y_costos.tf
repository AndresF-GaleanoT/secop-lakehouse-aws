# SPDX-License-Identifier: AGPL-3.0-or-later
# ---------------------------------------------------------------------------
# Consumo: Athena
# ---------------------------------------------------------------------------
resource "aws_athena_workgroup" "secop" {
  name        = "secop"
  description = "Consultas de los 3 objetivos del lakehouse SECOP"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = 1073741824 # 1 GB por consulta

    engine_version {
      selected_engine_version = "AUTO"
    }

    result_configuration {
      output_location = "s3://${aws_s3_bucket.lake.id}/athena-results/"
      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}

# ---------------------------------------------------------------------------
# Control de costos: presupuesto mensual con alertas y freno automático
# ---------------------------------------------------------------------------
resource "aws_budgets_budget" "secop" {
  name         = "limite-secop-15usd"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_limit_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # En AWS el presupuesto usa los tipos de costo por defecto, que incluyen créditos y reembolsos.
  # Para medir el gasto bruto (el freno saltaría antes si la cuenta usa créditos), descomenta:
  # cost_types {
  #   include_credit = false
  #   include_refund = false
  # }

  dynamic "notification" {
    for_each = [50, 80, 100]
    content {
      notification_type          = "ACTUAL"
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      subscriber_email_addresses = var.budget_emails
    }
  }
}

# Al 100 % del presupuesto aplica "loquear-secop" a los roles del pipeline, sin aprobación manual.
resource "aws_budgets_budget_action" "freno" {
  budget_name        = aws_budgets_budget.secop.name
  action_type        = "APPLY_IAM_POLICY"
  approval_model     = "AUTOMATIC"
  notification_type  = "ACTUAL"
  execution_role_arn = aws_iam_role.budgets_acciones.arn

  action_threshold {
    action_threshold_type  = "PERCENTAGE"
    action_threshold_value = 100
  }

  definition {
    iam_action_definition {
      policy_arn = aws_iam_policy.bloquear_secop.arn
      roles      = [aws_iam_role.stepfunctions.name, aws_iam_role.lambda_ingest.name]
    }
  }

  subscriber {
    address           = var.budget_emails[0]
    subscription_type = "EMAIL"
  }
}
