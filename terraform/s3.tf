# SPDX-License-Identifier: AGPL-3.0-or-later
# ---------------------------------------------------------------------------
# S3: el lago (bronze/ -> silver/ -> gold/) y los scripts de Glue
# ---------------------------------------------------------------------------
resource "aws_s3_bucket" "lake" {
  bucket = var.lake_bucket
}

resource "aws_s3_bucket_server_side_encryption_configuration" "lake" {
  bucket = aws_s3_bucket.lake.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256" # SSE-S3
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "lake" {
  bucket                  = aws_s3_bucket.lake.id
  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = true
  restrict_public_buckets = true
}

# Librería compartida por los dos jobs (--extra-py-files).
resource "aws_s3_object" "secop_transforms" {
  bucket = aws_s3_bucket.lake.id
  key    = "glue-scripts/secop_transforms.py"
  source = "${path.module}/../src/glue/lib/secop_transforms.py"
  etag   = filemd5("${path.module}/../src/glue/lib/secop_transforms.py")
}

# Scripts de los jobs, en la ruta donde los dejó el editor de Glue.
resource "aws_s3_object" "job_bronze_to_silver" {
  bucket = var.glue_assets_bucket
  key    = "scripts/secop-bronze-to-silver.py"
  source = "${path.module}/../src/glue/bronze_to_silver.py"
  etag   = filemd5("${path.module}/../src/glue/bronze_to_silver.py")
}

resource "aws_s3_object" "job_silver_to_gold" {
  bucket = var.glue_assets_bucket
  key    = "scripts/secop-silver-to-gold.py"
  source = "${path.module}/../src/glue/silver_to_gold.py"
  etag   = filemd5("${path.module}/../src/glue/silver_to_gold.py")
}
