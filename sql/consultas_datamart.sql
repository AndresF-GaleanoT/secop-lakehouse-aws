-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Consultas sobre la capa oro (Athena, workgroup de Athena del proyecto).
-- Reemplaza secop_lakehouse_db si cambiaste project o environment.
--
-- Las alertas marcan patrones irregulares para priorizar qué revisar; no califican conductas.

-- =========================================================================
-- OBJETIVO 1. Panorama de la contratación (gold_panorama_contratacion)
-- =========================================================================

-- 1.1 ¿Cuánto contrata el Estado por departamento y año?
SELECT anio, departamento, SUM(contratos) AS contratos, SUM(valor_total) AS valor_total
FROM secop_lakehouse_db.gold_panorama_contratacion
GROUP BY anio, departamento
ORDER BY anio, valor_total DESC;

-- 1.2 ¿Cuánto contrata el Estado por sector y año?
SELECT anio, sector, SUM(contratos) AS contratos, SUM(valor_total) AS valor_total
FROM secop_lakehouse_db.gold_panorama_contratacion
GROUP BY anio, sector
ORDER BY anio, valor_total DESC;

-- 1.3 ¿Qué % se adjudica por contratación directa y cómo ha cambiado por año?
SELECT anio,
       SUM(contratos) AS contratos,
       ROUND(100.0 * SUM(CASE WHEN es_contratacion_directa THEN contratos ELSE 0 END) / SUM(contratos), 1)
         AS pct_contratos_directa,
       ROUND(100.0 * SUM(CASE WHEN es_contratacion_directa THEN valor_total ELSE 0 END) / SUM(valor_total), 1)
         AS pct_valor_directa
FROM secop_lakehouse_db.gold_panorama_contratacion
GROUP BY anio
ORDER BY anio;

-- 1.4 Estacionalidad: contratos y valor por mes (¿pico en diciembre?)
SELECT anio, mes, SUM(contratos) AS contratos, SUM(valor_total) AS valor_total
FROM secop_lakehouse_db.gold_panorama_contratacion
GROUP BY anio, mes
ORDER BY anio, mes;

-- =========================================================================
-- OBJETIVO 2. Índice de patrones irregulares por entidad y por departamento
-- =========================================================================

-- 2.1 Ranking de entidades (solo las que tienen al menos 20 contratos)
SELECT posicion_ranking, nombre_entidad, departamento, contratos,
       pct_contratos_con_alerta, pct_contratacion_directa, pct_valor_mayor_contratista,
       contratos_posible_fraccionamiento, contratos_valor_atipico, contratos_contratista_no_identificado,
       contratos_anticipo_alto
FROM secop_lakehouse_db.gold_riesgo_entidades
WHERE posicion_ranking IS NOT NULL
ORDER BY posicion_ranking
LIMIT 50;

-- 2.2 Entidades con más concentración en un solo contratista
SELECT nombre_entidad, departamento, contratos, pct_valor_mayor_contratista
FROM secop_lakehouse_db.gold_riesgo_entidades
WHERE contratos >= 20
ORDER BY pct_valor_mayor_contratista DESC
LIMIT 30;

-- 2.3 Ranking de departamentos
SELECT posicion_ranking, departamento, contratos, pct_contratos_con_alerta, pct_contratacion_directa
FROM secop_lakehouse_db.gold_riesgo_departamentos
ORDER BY posicion_ranking;

-- 2.4 Contratos con más alertas simultáneas de una entidad (detalle del ranking)
SELECT id_contrato, fecha_firma, valor_contrato, puntaje_riesgo,
       alerta_contratacion_directa, alerta_fin_de_semana, alerta_inicio_antes_de_firma,
       alerta_valor_atipico, alerta_posible_fraccionamiento, alerta_concentracion,
       alerta_adiciones_altas, alerta_contratista_no_identificado, alerta_anticipo_alto
FROM secop_lakehouse_db.gold_alertas_contratos
WHERE nombre_entidad LIKE '%NOMBRE DE LA ENTIDAD%'
ORDER BY puntaje_riesgo DESC, valor_contrato DESC
LIMIT 50;

-- =========================================================================
-- OBJETIVO 3. Ley de Garantías 2026
-- Restricción de contratación directa: 31 de enero a 21 de junio de 2026.
-- =========================================================================

-- 3.1 Contratación directa por día alrededor del inicio de la restricción (¿pico antes del 31 de enero?)
SELECT fecha_firma, contratos, valor_total, periodo
FROM secop_lakehouse_db.gold_ley_garantias_diario
WHERE es_contratacion_directa
  AND fecha_firma BETWEEN DATE '2026-01-01' AND DATE '2026-02-15'
ORDER BY fecha_firma;

-- 3.2 Total por periodo: mes antes de la restricción frente al mismo mes de 2025 (sin elecciones)
SELECT periodo, SUM(contratos) AS contratos_directos, SUM(valor_total) AS valor_directos
FROM secop_lakehouse_db.gold_ley_garantias_diario
WHERE es_contratacion_directa AND periodo IS NOT NULL
GROUP BY periodo
ORDER BY periodo;

-- 3.3 ¿En qué entidades? Contratos directos en el mes antes de la restricción frente a enero de 2025
SELECT a.nombre_entidad, a.departamento,
       a.contratos_directos            AS antes_restriccion_2026,
       COALESCE(b.contratos_directos, 0) AS mismo_mes_2025,
       a.valor_directos                AS valor_antes_restriccion_2026
FROM secop_lakehouse_db.gold_ley_garantias_entidades a
LEFT JOIN secop_lakehouse_db.gold_ley_garantias_entidades b
       ON a.nit_entidad = b.nit_entidad AND b.periodo = '0_mismo_mes_2025_sin_elecciones'
WHERE a.periodo = '1_mes_antes_de_la_restriccion'
ORDER BY a.contratos_directos - COALESCE(b.contratos_directos, 0) DESC
LIMIT 50;

-- 3.4 Entidades con contratación directa SIN causal de excepción durante la restricción
--     (Ley 996 de 2005, art. 33). Es un patrón irregular para revisar: la causal pudo publicarse mal.
SELECT nombre_entidad, departamento, contratos_directos,
       contratos_directos_exceptuados, contratos_directos_no_exceptuados, valor_directos_no_exceptuados
FROM secop_lakehouse_db.gold_ley_garantias_entidades
WHERE periodo = '2_restriccion'
ORDER BY contratos_directos_no_exceptuados DESC
LIMIT 50;

-- 3.5 Contratación directa por periodo: exceptuada frente a no exceptuada
SELECT periodo, exceptuado_ley_garantias, SUM(contratos) AS contratos, SUM(valor_total) AS valor
FROM secop_lakehouse_db.gold_ley_garantias_diario
WHERE es_contratacion_directa AND periodo IS NOT NULL
GROUP BY periodo, exceptuado_ley_garantias
ORDER BY periodo, exceptuado_ley_garantias;
