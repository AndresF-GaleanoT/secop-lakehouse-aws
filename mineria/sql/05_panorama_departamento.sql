-- SPDX-License-Identifier: AGPL-3.0-or-later
SELECT departamento, SUM(contratos) AS contratos, SUM(valor_total) AS valor_total,
       SUM(CASE WHEN es_contratacion_directa THEN contratos ELSE 0 END) AS contratos_directa
FROM gold_panorama_contratacion
GROUP BY departamento
ORDER BY contratos DESC
