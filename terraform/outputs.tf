# SPDX-License-Identifier: AGPL-3.0-or-later
output "lake_bucket" {
  value = aws_s3_bucket.lake.id
}

output "lambda_ingest_arn" {
  value = aws_lambda_function.ingest.arn
}

output "pipeline_diario_arn" {
  value = aws_sfn_state_machine.pipeline_diario.arn
}

output "solo_bronce_arn" {
  value = aws_sfn_state_machine.solo_bronce.arn
}

output "athena_workgroup" {
  value = aws_athena_workgroup.secop.name
}

output "web_url" {
  value = "https://${aws_cloudfront_distribution.web.domain_name}"
}

output "web_distribution_id" {
  value = aws_cloudfront_distribution.web.id
}
