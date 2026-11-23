-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Serie mensual: contratos y valor (solo valores confiables), total y por contratación directa.
SELECT anio, mes,
       SUM(contratos) AS contratos,
       SUM(CASE WHEN es_contratacion_directa THEN contratos ELSE 0 END) AS contratos_directa,
       SUM(valor_total) AS valor_total
FROM gold_panorama_contratacion
GROUP BY anio, mes
ORDER BY anio, mes
