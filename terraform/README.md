# Terraform del lakehouse SECOP II

Infraestructura como código del proyecto, obtenida por **ingeniería inversa**: primero se creó todo a
mano en la consola de AWS y, cuando funcionó, se leyó la configuración real con la AWS CLI y se
escribió aquí, recurso por recurso.

## Qué declara

| Archivo | Recursos |
|---|---|
| `s3.tf` | Bucket del lago (SSE-S3, sin acceso público) y los scripts de Glue |
| `iam.tf` | Roles `secop-lambda-ingest`, `secop-glue`, `secop-stepfunctions`, `secop-scheduler`, `secop-budgets-acciones` y la política de freno `loquear-secop` |
| `lambda.tf` | Lambda `secop-ingest` (Python 3.12, arm64, 2048 MB, 900 s, 4 hilos) |
| `glue.tf` | Base `secop_lakehouse_db` y jobs `secop-bronze-to-silver` (10 workers) y `secop-silver-to-gold` (5 workers), Glue 5.0, Flex, Iceberg |
| `orquestacion.tf` | Step Functions `secop-solo-bronce` y `secop-pipeline-diario`, y el horario `secop-pipeline-diario-6am` (EventBridge Scheduler, 6:00 a. m. hora Colombia) |
| `consumo_y_costos.tf` | Workgroup de Athena `secop` y presupuesto `limite-secop-15usd` (alertas 50/80/100 % y freno automático al 100 %) |
| `web.tf` | Web de resultados: bucket `secop-web-<cuenta>` (privado, SSE-S3, solo CloudFront lo lee), Origin Access Control, distribución de CloudFront y Lambda `secop-web-export` con su rol |
| `imports.tf` | Bloques `import {}` que adoptan los recursos que ya existen |

No se declaran (a propósito):
- Las **tablas** `silver_contratos` y `gold_*`: las crean los jobs de Spark con Iceberg.
- Los **datos** de `bronze/`, `silver/` y `gold/`.
- El bucket `aws-glue-assets-…` (lo crea la consola de Glue); solo se gestionan los dos scripts que contiene.

## Estado actual

Aplicado el 23 de noviembre de 2026: 40 recursos adoptados con los bloques `import {}`, 7 sincronizados
con el repositorio (código de las dos Lambdas, scripts de Glue y descripción de las máquinas de estado) y
`terraform plan` sin cambios. El estado queda en `terraform/terraform.tfstate` (local y fuera del
repositorio, porque contiene el token de datos.gov.co); para trabajar en equipo conviene moverlo al backend
S3 de `versions.tf`. Las etiquetas por defecto y los `cost_types` del presupuesto están comentados para no
cambiar lo que ya existe; ver los comentarios en `versions.tf` y `consumo_y_costos.tf`.

## Uso

Requisitos: Terraform ≥ 1.5 y la AWS CLI configurada con la cuenta del proyecto.

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # y pon tu correo en budget_emails
```

El token de datos.gov.co **no** va en ningún archivo; se pasa como variable de entorno:

```powershell
$env:TF_VAR_socrata_app_token = "<tu token>"
```

```bash
terraform init
terraform plan
terraform apply
```

### En la cuenta actual (adoptar lo que ya existe)
Verificado el 13 de noviembre de 2026 con Terraform 1.17.2 y el proveedor AWS 5.x: `terraform validate`
correcto y `terraform plan` con **30 recursos para importar, 0 nuevos y 0 a destruir**.

Con `imports.tf` presente, `terraform plan` debe mostrar **“to import”** para cada recurso y casi
ningún cambio. Diferencias esperadas y seguras:
- Se agregan las etiquetas `Proyecto` y `Gestion` (bloque `default_tags`).
- El presupuesto pasa de `FilterExpression` (consola) a `cost_types` (sin créditos ni reembolsos):
  es la misma regla escrita de otra forma.
- Los scripts de S3 se vuelven a subir si cambian los saltos de línea del archivo local.

Si `plan` propone **destruir y recrear** algo, no apliques: revisa ese recurso primero.

### En una cuenta nueva
Borra `imports.tf`, cambia `lake_bucket` y `glue_assets_bucket` en `terraform.tfvars` (los nombres de
bucket son únicos en todo S3) y aplica. Después:
1. Descarga el histórico: ejecuta `secop-solo-bronce` con la entrada de `python scripts/backfill.py --dry-run`.
2. Corre `secop-bronze-to-silver` y luego `secop-silver-to-gold`.
3. Desde ahí el horario diario mantiene oro actualizado.

## Costo
Lo declarado aquí no cuesta por existir. El gasto viene de ejecutar: el pipeline diario cuesta unos
0,07 USD por día (≈ 2 USD/mes, casi todo Glue Flex), más el almacenamiento de S3 (≈ 3 GB).
