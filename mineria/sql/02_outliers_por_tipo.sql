-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Outliers del valor por tipo de contrato: cuartiles y regla Q3 + 3*IQR (la misma de la alerta de valor atípico).
WITH q AS (
  SELECT tipo_contrato,
         COUNT(*) AS contratos,
         approx_percentile(CAST(valor_contrato AS DOUBLE), 0.25) AS q1,
         approx_percentile(CAST(valor_contrato AS DOUBLE), 0.50) AS mediana,
         approx_percentile(CAST(valor_contrato AS DOUBLE), 0.75) AS q3,
         approx_percentile(CAST(valor_contrato AS DOUBLE), 0.99) AS p99,
         MAX(CAST(valor_contrato AS DOUBLE)) AS maximo
  FROM silver_contratos
  GROUP BY tipo_contrato
)
SELECT q.tipo_contrato, q.contratos, q.q1, q.mediana, q.q3, q.p99, q.maximo,
       q.q3 + 3 * (q.q3 - q.q1) AS umbral_atipico,
       SUM(CASE WHEN CAST(s.valor_contrato AS DOUBLE) > q.q3 + 3 * (q.q3 - q.q1) THEN 1 ELSE 0 END) AS atipicos,
       SUM(CASE WHEN NOT s.valor_confiable THEN 1 ELSE 0 END) AS no_confiables
FROM silver_contratos s
JOIN q ON s.tipo_contrato = q.tipo_contrato
GROUP BY q.tipo_contrato, q.contratos, q.q1, q.mediana, q.q3, q.p99, q.maximo
ORDER BY q.contratos DESC
