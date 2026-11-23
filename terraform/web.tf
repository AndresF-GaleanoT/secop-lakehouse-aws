# SPDX-License-Identifier: AGPL-3.0-or-later
# ---------------------------------------------------------------------------
# Web de resultados: bucket privado + CloudFront (OAC) + Lambda que exporta la capa oro a JSON.
# Ingeniería inversa de lo creado con la AWS CLI el 23 de noviembre de 2026.
# Los archivos del sitio (web/) los sube scripts/publicar_web.py y los JSON de data/ los escribe la
# Lambda cada semana: no se declaran aquí.
# ---------------------------------------------------------------------------
locals {
  web_bucket = "secop-web-${data.aws_caller_identity.actual.account_id}"
}

resource "aws_s3_bucket" "web" {
  bucket = local.web_bucket
}

resource "aws_s3_bucket_server_side_encryption_configuration" "web" {
  bucket = aws_s3_bucket.web.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = false
  }
}

resource "aws_s3_bucket_public_access_block" "web" {
  bucket                  = aws_s3_bucket.web.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Solo CloudFront (esta distribución) puede leer el bucket.
resource "aws_s3_bucket_policy" "web" {
  bucket = aws_s3_bucket.web.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "SoloCloudFrontDeLaWeb"
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.web.arn}/*"
      Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.web.arn } }
    }]
  })
}

resource "aws_cloudfront_origin_access_control" "web" {
  name                              = "secop-web-oac"
  description                       = "CloudFront lee el bucket privado de la web"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "web" {
  comment             = "Web de vigilancia SECOP II: sitio y datos (data/) desde S3"
  enabled             = true
  default_root_object = "index.html"
  price_class         = "PriceClass_100"
  http_version        = "http2and3"
  is_ipv6_enabled     = true

  origin {
    origin_id                = "s3-secop-web"
    domain_name              = aws_s3_bucket.web.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.web.id
  }

  default_cache_behavior {
    target_origin_id       = "s3-secop-web"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true
    # Políticas administradas por AWS: CachingOptimized (respeta el Cache-Control de cada archivo)
    # y SecurityHeadersPolicy (HSTS, X-Frame-Options, X-Content-Type-Options...).
    cache_policy_id            = "658327ea-f89d-4fab-a63d-7e88639e58f6"
    response_headers_policy_id = "67f7725c-6f97-4210-82d7-5512b31e9d03"
  }

  # S3 responde 403 a un archivo que no existe (CloudFront no puede listar el bucket).
  dynamic "custom_error_response" {
    for_each = [403, 404]
    content {
      error_code            = custom_error_response.value
      response_code         = 404
      response_page_path    = "/404.html"
      error_caching_min_ttl = 60
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

# --- Lambda de exportación: capa oro (Athena) -> JSON en s3://<web>/data/ -----------------------
resource "aws_iam_role" "web_export" {
  name               = "secop-web-export"
  description        = "Lambda que exporta la capa oro a JSON para la web"
  assume_role_policy = file("${path.module}/../src/lambda_web_export/iam_confianza.json")
}

resource "aws_iam_role_policy_attachment" "web_export_logs" {
  role       = aws_iam_role.web_export.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Athena en el workgroup del proyecto, lectura de plata y oro, y escritura solo en data/ de la web.
resource "aws_iam_role_policy" "web_export" {
  name   = "exportar-oro-a-web"
  role   = aws_iam_role.web_export.id
  policy = file("${path.module}/../src/lambda_web_export/iam_politica.json")
}

data "archive_file" "web_export" {
  type        = "zip"
  output_path = "${path.module}/build/secop-web-export.zip"

  source {
    content  = file("${path.module}/../src/lambda_web_export/handler.py")
    filename = "handler.py"
  }
}

resource "aws_lambda_function" "web_export" {
  function_name    = "secop-web-export"
  description      = "Exporta la capa oro a JSON para la web (S3 + CloudFront)"
  role             = aws_iam_role.web_export.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.web_export.output_path
  source_code_hash = data.archive_file.web_export.output_base64sha256
  memory_size      = 512
  timeout          = 300

  environment {
    variables = {
      WEB_BUCKET       = aws_s3_bucket.web.id
      ATHENA_WORKGROUP = aws_athena_workgroup.secop.name
      GLUE_DATABASE    = var.glue_database
    }
  }
}
