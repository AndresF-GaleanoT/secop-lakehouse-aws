# Módulo de minería de datos

Limpieza, EDA, K-means de entidades y reglas de asociación (Apriori) entre las alertas de patrones
irregulares. El trabajo pesado lo hace **Athena en AWS**: en el PC solo se procesan agregados y una muestra
determinista de ~51 mil contratos (0,9 %). No se descarga el conjunto completo.

## Requisitos

- AWS CLI v2 configurado con acceso al workgroup `secop` de Athena (región `us-east-1`, base `secop_lakehouse_db`).
- Python 3.12+ con `pip install -r mineria/requirements.txt`.

## Ejecución (desde la raíz del repositorio)

```bash
python mineria/01_extraer_athena.py      # 9 consultas de mineria/sql/ -> mineria/datos/*.csv (~240 MB escaneados)
python mineria/02_eda.py                 # nulos, outliers, EDA -> mineria/figuras/, mineria/resultados/
python mineria/03_clustering_kmeans.py   # K-means (codo, silhouette, Davies-Bouldin, ARI entre semillas)
python mineria/04_reglas_asociacion.py   # Apriori con soporte exacto sobre todos los contratos
```

Los pasos 2 a 4 solo leen `mineria/datos/`, así que se pueden repetir sin AWS. La semilla es fija (42) y la
muestra se elige con un hash del `id_contrato`, por lo que los resultados son reproducibles. Como la carga
diaria actualiza plata y oro, volver a correr el paso 1 en otra fecha cambia levemente las cifras;
`datos/bitacora_consultas.csv` guarda la fecha y el id de cada consulta.

## Contenido

| Ruta | Qué es |
|---|---|
| `sql/01_calidad_plata.sql` | Nulos por columna y reglas de consistencia sobre toda la tabla de plata |
| `sql/02_outliers_por_tipo.sql` | Cuartiles por tipo de contrato y conteo de la regla Q3 + 3·IQR |
| `sql/03_muestra_plata.sql` | Muestra determinista del 0,9 % |
| `sql/04`–`06` | Agregados de `gold_panorama_contratacion` (serie mensual, departamentos, modalidades y sectores) |
| `sql/07_riesgo_entidades.sql` | Perfil de alertas por entidad (entrada de K-means) |
| `sql/08_combinaciones_alertas.sql` | Contratos por combinación de las 9 alertas (entrada de Apriori) |
| `athena.py` | Ejecuta una consulta con el AWS CLI y baja el CSV |
| `figuras/` | Figuras en PDF (para LaTeX) y PNG |
| `resultados/` | Tablas de resultados (nulos, outliers, perfil de clústeres, reglas…) |

El informe está en `docs/informe_mineria/`. Las alertas marcan patrones irregulares para priorizar
revisiones; no califican conductas.
