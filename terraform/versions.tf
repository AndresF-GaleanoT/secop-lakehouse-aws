# SPDX-License-Identifier: AGPL-3.0-or-later
# Terraform del lakehouse SECOP II en AWS.
# Obtenido por ingeniería inversa: cada recurso replica la configuración que se creó a mano en la
# consola (leída con la AWS CLI el 13 de noviembre de 2026). Ver README.md de esta carpeta.

terraform {
  required_version = ">= 1.5" # bloques import {}

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.6"
    }
  }

  # Estado local por defecto. Para trabajo en equipo se movería a un backend S3:
  # backend "s3" { bucket = "<bucket-de-estado>" key = "secop/terraform.tfstate" region = "us-east-1" }
}

provider "aws" {
  region = var.region

  # Etiquetas para todos los recursos: desactivadas para adoptar la infraestructura sin modificarla.
  # Al activarlas, el siguiente apply etiqueta todo (útil para filtrar costos por proyecto).
  # default_tags {
  #   tags = {
  #     Proyecto = "secop-lakehouse"
  #     Gestion  = "terraform"
  #   }
  # }
}

data "aws_caller_identity" "actual" {}
