# Lakehouse SECOP II en AWS (arquitectura Medallion)

Pipeline que extrae los contratos públicos de **SECOP II – Contratos Electrónicos** (datos.gov.co,
5,7 millones de contratos desde 2015) y los procesa en **bronce → plata → oro** para responder tres
objetivos:

1. **Panorama de la contratación:** cuánto contrata el Estado por departamento, sector y año; qué % es
   contratación directa y cómo cambia; estacionalidad (pico de diciembre).
2. **Índice de patrones irregulares por entidad y por departamento:** ranking a partir de 9 alertas por contrato.
3. **Ley de Garantías 2026:** contratación directa antes, durante y después de la restricción
   (31 de enero a 21 de junio de 2026), comparada con el mismo mes de 2025.

```
API datos.gov.co ─► Lambda ─► S3 bronce ─► Glue bronze_to_silver ─► plata (Iceberg) ─► Glue silver_to_gold ─► oro (Iceberg) ─► Athena
                     └──── orquestado por Step Functions, iniciado cada lunes por EventBridge Scheduler ────┘
oro ─► Lambda secop-web-export (Athena) ─► S3 web/data/*.json ─► CloudFront ─► navegador   (último paso del pipeline)
```

**Web de resultados:** https://d48p8jbrfjaba.cloudfront.net (ver [11. Web de resultados](#11-web-de-resultados)).

## Contenido

```
├── src/
│   ├── lambda_ingest/handler.py      Lambda: API → S3 bronce
│   ├── lambda_web_export/            Lambda: oro → JSON de la web (handler.py y políticas de IAM)
│   └── glue/
│       ├── bronze_to_silver.py       Job Glue: bronce → plata (16 columnas, calidad, MERGE)
│       ├── silver_to_gold.py         Job Glue: plata → oro (una tabla por objetivo)
│       └── lib/secop_transforms.py   Transformaciones, alertas y umbrales (los usan los dos jobs)
├── stepfunctions/
│   ├── pipeline_diario.asl.json      Carga semanal (últimos 90 días, por el retraso de la API)
│   ├── iam_*.json                    Políticas de IAM del pipeline semanal y del Scheduler
│   ├── carga_historica.asl.json      Carga histórica completa (un mes por Lambda, en paralelo)
│   └── solo_bronce.asl.json          Solo descarga el histórico a bronce, sin Glue
├── scripts/
│   ├── backfill.py                   Arma la entrada de la carga histórica y la inicia
│   ├── benchmark_descarga.py         Speedup de la Lambda sobre un mismo tramo
│   ├── benchmark_historico.py        Experimento A: descarga completa con 1, 2, 4 y 8 hilos
│   ├── benchmark_spark.py            Experimento B: una serie de Spark con 2, 4, 8 y 10 workers
│   ├── agrega_spark.py               Une las series y calcula mediana, speedup y eficiencia
│   └── publicar_web.py               Sube la carpeta web/ al bucket de la web
├── web/                              Sitio estático (HTML, CSS y JS sin librerías); web/data/ lo llena la Lambda
├── resultados_benchmark_*.csv        Resultados medidos que usa el informe
├── informe/                          Informe IEEE (LaTeX y PDF)
├── sql/consultas_datamart.sql        Consultas de Athena para los tres objetivos
├── mineria/                          Minería de datos: EDA, nulos/outliers, K-means y Apriori (ver mineria/README.md)
└── terraform/                        Infraestructura como código (ingeniería inversa de la consola)
```

## Capas

| Capa | Contenido |
|---|---|
| **Bronce** (`s3://<BUCKET_LAKE>/bronze/secop_contratos/load=<carga>/part-NNNNN.jsonl.gz`) | Respuesta completa de la API (91 columnas), sin cambios |
| **Plata** (`silver_contratos`) | Solo las 16 columnas que usan los objetivos: `id_contrato`, `nit_entidad`, `nombre_entidad`, `departamento`, `sector`, `modalidad_contratacion`, `tipo_contrato`, `documento_proveedor`, `fecha_firma`, `fecha_inicio`, `fecha_fin`, `dias_adicionados`, `valor_contrato`, `valor_anticipo`, `codigo_unspsc`, `justificacion_modalidad` (+ `es_contratacion_directa`, `load_id`) |
| **Oro** | Objetivo 1: `gold_panorama_contratacion` · Objetivo 2: `gold_alertas_contratos`, `gold_riesgo_entidades`, `gold_riesgo_departamentos` · Objetivo 3: `gold_ley_garantias_diario`, `gold_ley_garantias_entidades` |

Los datos personales del dataset (cédulas de supervisores, cuentas bancarias, etc.) se quedan en bronce.

**Alertas del objetivo 2** (umbrales en `secop_transforms.py`): contratación directa, firma en fin de
semana, inicio antes de la firma, valor atípico, posible fraccionamiento (misma entidad, contratista y
código UNSPSC en 30 días), concentración en un contratista, adiciones altas, contratista no identificado y
anticipo mayor al 50 % (Ley 80 de 1993, art. 40). **Marcan patrones irregulares para priorizar la revisión;
no califican conductas.**

**Objetivo 3:** la contratación directa se separa en exceptuada y no exceptuada de la restricción de la
Ley 996 de 2005, art. 33. Las excepciones se aproximan con los datos: defensa y seguridad (bienes sujetos a
reserva), crédito público, emergencias (urgencia manifiesta) y entidades sanitarias y hospitalarias (por NIT).
Dos excepciones de la ley (reconstrucción de infraestructura afectada y gastos inaplazables) no se pueden
detectar con los datos.

---

## Guía para crear los servicios en AWS (consola)

Región sugerida: `us-east-1`. Sustituye `<CUENTA>` por tu número de cuenta.

### 0. Control de costos (primero)
- **AWS Budgets → Crear presupuesto** mensual de 10–20 USD con alerta por correo al 80 %.
- Glue no está en la capa gratuita: prueba con un mes antes de la carga completa.

### 1. S3
Crea **dos buckets** (privados, con cifrado SSE-S3):
- `<BUCKET_LAKE>`: el lago. Las carpetas `bronze/`, `silver/` y `gold/` se crean solas.
- `<BUCKET_ARTEFACTOS>`: sube ahí los scripts de Glue y usa `athena-results/` para Athena:
  - `glue/bronze_to_silver.py`
  - `glue/silver_to_gold.py`
  - `glue/lib/secop_transforms.py`

Opcional: regla de ciclo de vida para pasar `bronze/` a Standard-IA a los 30 días.

### 2. Glue Data Catalog
**Glue → Databases → Add database:** `secop_lakehouse_db`.

### 3. Alertas
No se usa SNS: si una ejecución falla, queda en estado **Failed** (rojo) en la consola de Step Functions,
con el estado y el error que la detuvieron.

### 4. Roles de IAM

| Rol | Servicio de confianza | Permisos |
|---|---|---|
| `secop-lambda-ingest` | Lambda | `AWSLambdaBasicExecutionRole` + `s3:PutObject` en `arn:aws:s3:::<BUCKET_LAKE>/bronze/*` |
| `secop-glue` | Glue | `AWSGlueServiceRole` + `s3:GetObject/PutObject/DeleteObject` en `<BUCKET_LAKE>/*`, `s3:GetObject` en `<BUCKET_ARTEFACTOS>/*`, `s3:ListBucket` en ambos buckets, y `glue:GetDatabase, GetTable, GetTables, CreateTable, UpdateTable, DeleteTable` sobre el catálogo, la base `secop_lakehouse_db` y sus tablas |
| `secop-scheduler` | EventBridge Scheduler | `states:StartExecution` en `secop-pipeline-diario` (`stepfunctions/iam_scheduler_*.json`) |
| `secop-web-export` | Lambda | `AWSLambdaBasicExecutionRole` + `src/lambda_web_export/iam_politica.json`: Athena en el workgroup `secop`, lectura del catálogo, de `silver/*` y `gold/*`, resultados en `athena-results/*` y escritura solo en `secop-web-<CUENTA>/data/*` |
| `secop-stepfunctions` | Step Functions | `lambda:InvokeFunction` en las dos Lambdas (`stepfunctions/iam_invocar_lambdas.json`); `glue:StartJobRun, GetJobRun, GetJobRuns, BatchStopJobRun` en los dos jobs (`stepfunctions/iam_pipeline_diario.json`); y, si activas logs, `logs:CreateLogDelivery, GetLogDelivery, UpdateLogDelivery, DeleteLogDelivery, ListLogDeliveries, PutResourcePolicy, DescribeResourcePolicies, DescribeLogGroups` sobre `*` |

### 5. Lambda de ingesta
**Lambda → Create function** `secop-ingest`:
- Runtime **Python 3.12**, rol `secop-lambda-ingest`.
- Código: pega `src/lambda_ingest/handler.py` como `handler.py`. **Handler:** `handler.lambda_handler`.
- **Configuración general:** timeout **15 min** (900 s), memoria **2048 MB**.
- **Variables de entorno:**

| Variable | Valor |
|---|---|
| `LAKE_BUCKET` | `<BUCKET_LAKE>` |
| `DATASET_ID` | `jbjy-vk9h` |
| `INCREMENTAL_FIELD` | `fecha_de_firma` |
| `BRONZE_PREFIX` | `bronze/secop_contratos` |
| `DEPARTMENT_FILTER` | vacío (todo el país) |
| `PARALLEL_PAGES` | `4` (hilos por Lambda) |
| `SOCRATA_APP_TOKEN` | tu token de aplicación de datos.gov.co (opcional pero recomendado) |

Prueba con el evento `{"ingest_date": "2026-09-30"}`: debe aparecer un archivo en `bronze/`.

### 6. Jobs de Glue
Crea **dos jobs** (Glue → ETL jobs → Script editor → Spark, subiendo el script desde S3):

| Ajuste | `secop-bronze-to-silver` | `secop-silver-to-gold` |
|---|---|---|
| Script | `s3://<BUCKET_ARTEFACTOS>/glue/bronze_to_silver.py` | `s3://<BUCKET_ARTEFACTOS>/glue/silver_to_gold.py` |
| Rol | `secop-glue` | `secop-glue` |
| Versión | Glue 5.0 | Glue 5.0 |
| Workers | G.1X × 10 | G.1X × 5 |
| Clase de ejecución | Flex | Flex |
| Timeout | 60 min | 60 min |
| Concurrencia máxima | 1 | 1 |

**Job parameters** (en ambos):

| Clave | Valor |
|---|---|
| `--datalake-formats` | `iceberg` |
| `--extra-py-files` | `s3://<BUCKET_ARTEFACTOS>/glue/lib/secop_transforms.py` |
| `--LAKE_BUCKET` | `<BUCKET_LAKE>` |
| `--GLUE_DATABASE` | `secop_lakehouse_db` |

Solo en `secop-bronze-to-silver` (Step Functions los reemplaza en cada ejecución):

| Clave | Valor por defecto |
|---|---|
| `--SOURCE_PATH` | `s3://<BUCKET_LAKE>/bronze/secop_contratos/` |
| `--LOAD_ID` | `manual` |

### 7. Step Functions
Crea **dos máquinas de estados** (tipo Standard, rol `secop-stepfunctions`), pegando el JSON de
`stepfunctions/` y reemplazando los marcadores:

| Marcador | Valor |
|---|---|
| `<ARN_LAMBDA_INGESTA>` | ARN de `secop-ingest` |
| `<NOMBRE_JOB_GLUE_BRONZE_TO_SILVER>` | `secop-bronze-to-silver` |
| `<NOMBRE_JOB_GLUE_SILVER_TO_GOLD>` | `secop-silver-to-gold` |
| `<BUCKET_LAKE>` | nombre del bucket del lago |

- `secop-pipeline-diario` ← `pipeline_diario.asl.json` (ya trae los nombres reales; entrada `{"lookback_days": 90}`)
- `secop-carga-historica` ← `carga_historica.asl.json` (usa 10 workers de Glue y 3 meses en paralelo;
  puedes cambiarlo en el JSON)

### 8. Carga histórica
Primero un mes de prueba, luego todo:

```bash
python scripts/backfill.py --start 2026-09 --end 2026-09 --state-machine-arn <ARN_CARGA_HISTORICA>
python scripts/backfill.py --state-machine-arn <ARN_CARGA_HISTORICA>
```

Sin Python: `python scripts/backfill.py --dry-run` imprime el JSON de entrada; también puedes pegarlo en
**Step Functions → Iniciar ejecución**.

**Solo bronce (sin Glue):** para descargar todo el histórico antes de tener plata y oro, crea la máquina
`secop-solo-bronce` con `stepfunctions/solo_bronce.asl.json` (solo necesita `lambda:InvokeFunction`) y
ejecútala con la misma entrada. Después, la carga histórica completa reprocesa bronce con Glue sin volver
a descargar si en `carga_historica.asl.json` saltas el estado `IngestWindows` (o ejecutas directamente los
jobs de Glue con `--SOURCE_PATH s3://<BUCKET_LAKE>/bronze/secop_contratos/`).

### 9. Ejecución semanal
**EventBridge → Scheduler → Create schedule** `secop-pipeline-diario-6am` (conserva el nombre de cuando era
diario): `cron(0 6 ? * MON *)`, cada lunes a las 6:00 a. m., con zona horaria `America/Bogota`, destino
`secop-pipeline-diario` (Step Functions StartExecution), rol `secop-scheduler`, entrada `{"lookback_days": 90}`.

Se actualiza una vez por semana para reducir costos. La API publica con días de retraso y algunos contratos
aparecen uno o dos meses después de firmados (`scripts/verificar_web.py` encontró 6.434 que faltaban, casi
todos de septiembre de 2026), así que cada lunes se vuelven a descargar los últimos 90 días: el `MERGE INTO` de plata actualiza los contratos que ya estaban y agrega los nuevos, sin duplicados.
Plata corre con 2 workers (solo procesa la carpeta de esa carga) y oro se reconstruye completo.

### 10. Athena
**Athena → Workgroups → Create** `secop` (motor automático) con resultados en
`s3://<BUCKET_LAKE>/athena-results/`, cifrado SSE-S3, **invalidar la configuración del lado del cliente** y
límite de 1 GB escaneado por consulta. Las tablas de plata y oro aparecen en la base `secop_lakehouse_db`.
Las consultas de los tres objetivos están en `sql/consultas_datamart.sql`.

### 11. Web de resultados

Sitio estático en S3 servido por CloudFront. Las visitas solo descargan archivos: nunca consultan Athena,
así que el costo no crece con el tráfico. Cada lunes, el último paso del pipeline (`ExportaWeb`) corre la
Lambda `secop-web-export`, que hace 8 consultas sobre oro (≈ 6 MB escaneados, menos de 20 s) y deja los
JSON en `data/`. CloudFront y el navegador los guardan 15 minutos.

La web tiene una página por tema y cada una descarga solo los JSON que usa:

| Página | Contenido | Datos |
|---|---|---|
| `index.html` | Inicio: cifra total y una tarjeta por página | `meta`, `resumen`, `departamentos`, `ley_periodos` |
| `panorama.html` | Contratos por año, calendario de meses, contratación directa y sectores | `resumen`, `anual`, `mensual`, `sectores` |
| `alertas.html` | Mapa por departamento, frecuencia de cada alerta y ranking de entidades | `departamentos`, `entidades` |
| `entidades.html` | Buscador y ficha de cada entidad; `entidades.html?nit=<NIT>` abre una ficha directamente | `departamentos`, `entidades` |
| `ley.html` | Ley de Garantías 2026: cifras, contratos directos por semana y entidades | `ley_diario`, `ley_periodos`, `entidades` |
| `como-funciona.html` | La cadena en AWS, costos y la última exportación | `departamentos` |

El menú y el pie se escriben una sola vez en `web/app.js` (`montarMarco`) y se insertan en todas las páginas.

| Recurso | Configuración |
|---|---|
| Bucket `secop-web-<CUENTA>` | Privado (bloqueo de acceso público completo), SSE-S3. Política: solo `s3:GetObject` para el servicio CloudFront con `AWS:SourceArn` de la distribución |
| CloudFront | Origen S3 con **Origin Access Control** (`secop-web-oac`), raíz `index.html`, HTTPS obligatorio, compresión, política de caché `CachingOptimized`, cabeceras `SecurityHeadersPolicy`, errores 403 y 404 → `/404.html`, clase de precio 100 |
| Lambda `secop-web-export` | Python 3.12 arm64, 512 MB, 300 s, código `src/lambda_web_export/handler.py`, rol `secop-web-export`. Variables: `WEB_BUCKET`, `ATHENA_WORKGROUP=secop`, `GLUE_DATABASE=secop_lakehouse_db` |
| Step Functions | Estado `ExportaWeb` después de `SilverToGold` en `pipeline_diario.asl.json` |

Para publicar cambios del sitio (no toca `data/`):

```bash
python scripts/publicar_web.py                          # tarda hasta 5 min en verse
python scripts/publicar_web.py --invalidar <ID_DISTRIBUCION>   # se ve de inmediato
```

Para probarlo en local con datos reales: `python src/lambda_web_export/handler.py --destino web/data` y
`python -m http.server 8765 --directory web`.

---

## Reproducir las mediciones

Requisitos: Python 3.12+, AWS CLI v2 con acceso a la cuenta, la infraestructura anterior desplegada con plata
cargada y `pip install -r requirements.txt`. Los comandos se ejecutan desde la raíz del proyecto.

**Descarga de un mismo tramo (1, 2, 4 y 8 hilos):**

```bash
python scripts/benchmark_descarga.py
```

**Experimento A, descarga completa.** Cuesta cerca de 1 USD y escribe copias en `bronze/_benchmark/`, que
conviene borrar al terminar:

```bash
python scripts/benchmark_historico.py --hilos 1 2 4 8
```

**Experimento B, Spark.** Son tres series con distinto orden. Costaron cerca de 1,78 USD:

```bash
python scripts/benchmark_spark.py --workers 2 4 8 10 --out serie1.csv
python scripts/benchmark_spark.py --workers 10 8 4 2 --out serie2.csv
python scripts/benchmark_spark.py --workers 4 10 2 8 --out serie3.csv
python scripts/agrega_spark.py serie1.csv serie2.csv serie3.csv --out resultados_benchmark_spark
```

`agrega_spark.py` no necesita AWS. Las cifras de una repetición no serán idénticas a las del informe, porque
el conjunto de datos crece cada día y la latencia de la API y de AWS cambia.

**Informe:** desde `informe/`, ejecuta `pdflatex informe_cpd.tex` tres veces.

## Costo estimado
Carga histórica completa: ≈ 5–10 USD (una vez). Carga semanal: ≈ 0,3 USD/mes (≈ 0,07 USD por ejecución, medido cuando la carga era diaria y costaba ≈ 2,1 USD/mes). Sin ejecuciones: < 0,50 USD/mes
(solo almacenamiento). Son estimaciones; revisa Cost Explorer después de la primera semana.

## Fuente de datos
[SECOP II - Contratos Electrónicos](https://www.datos.gov.co/Gastos-Gubernamentales/SECOP-II-Contratos-Electr-nicos/jbjy-vk9h),
Agencia Nacional de Contratación Pública – Colombia Compra Eficiente. Licencia CC BY-SA 4.0.

## Licencias

Copyright (C) 2026 Andrés Felipe Galeano Téllez, Oscar Esteban Arias López, Juan David Sandoval Bello y
Yeikov Jared Ramos Sánchez. Proyecto integrador, Facultad de Ingeniería de Datos e Inteligencia Artificial,
Universidad Santo Tomás, Tunja.

| Qué | Licencia |
|---|---|
| **Código** (`src/`, `scripts/`, `stepfunctions/`, `terraform/`, `sql/`, `mineria/*.py`, `web/`) | [GNU AGPL 3.0 o posterior](LICENSE) |
| **Datos derivados, figuras, informes y textos** | [CC BY-SA 4.0](LICENCIA-DATOS.md), la misma de SECOP II |

La AGPL permite usar, estudiar y modificar el código, pero quien lo modifique y lo distribuya, o lo ofrezca
como servicio en la web, debe publicar su código con la misma licencia y conservar el crédito de los autores.
Los datos de SECOP II se comparten con CC BY-SA 4.0, así que todo lo que se obtiene de ellos se comparte en
los mismos términos, con crédito a Colombia Compra Eficiente. Detalles y forma de citar en
[`LICENCIA-DATOS.md`](LICENCIA-DATOS.md).
