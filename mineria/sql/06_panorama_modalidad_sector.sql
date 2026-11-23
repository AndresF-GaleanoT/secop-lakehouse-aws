-- SPDX-License-Identifier: AGPL-3.0-or-later
SELECT 'modalidad' AS dimension, modalidad_contratacion AS categoria,
       SUM(contratos) AS contratos, SUM(valor_total) AS valor_total
FROM gold_panorama_contratacion GROUP BY modalidad_contratacion
UNION ALL
SELECT 'sector', sector, SUM(contratos), SUM(valor_total)
FROM gold_panorama_contratacion GROUP BY sector
ORDER BY 1, 3 DESC
