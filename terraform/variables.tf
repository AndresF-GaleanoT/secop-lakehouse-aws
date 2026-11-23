# SPDX-License-Identifier: AGPL-3.0-or-later
variable "region" {
  description = "Región de AWS del proyecto."
  type        = string
  default     = "us-east-1"
}

variable "lake_bucket" {
  description = "Bucket del lago (bronze/, silver/, gold/, glue-scripts/, athena-results/)."
  type        = string
  default     = "secop-lake-811136731365"
}

variable "glue_assets_bucket" {
  description = "Bucket que la consola de Glue crea para los scripts de los jobs (no lo gestiona Terraform)."
  type        = string
  default     = "aws-glue-assets-811136731365-us-east-1"
}

variable "glue_database" {
  description = "Base de datos del Glue Data Catalog donde viven las tablas Iceberg."
  type        = string
  default     = "secop_lakehouse_db"
}

variable "socrata_app_token" {
  description = "Token de aplicación de datos.gov.co. Se pasa con TF_VAR_socrata_app_token; nunca se escribe en archivos."
  type        = string
  sensitive   = true
}

variable "parallel_pages" {
  description = "Hilos por Lambda para descargar páginas (benchmark: 4 es el punto óptimo)."
  type        = number
  default     = 4
}

variable "lookback_days" {
  description = "Días hacia atrás que descarga el pipeline diario (la API publica con retraso)."
  type        = number
  default     = 10
}

variable "budget_limit_usd" {
  description = "Límite mensual del presupuesto en USD."
  type        = number
  default     = 15
}

variable "budget_emails" {
  description = "Correos que reciben las alertas del presupuesto (50 %, 80 % y 100 %)."
  type        = list(string)
}
