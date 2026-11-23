-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Frecuencia exacta de cada combinación de las 9 alertas (máximo 512 filas): base de las reglas de asociación
-- sobre TODOS los contratos, sin descargarlos.
SELECT alerta_contratacion_directa, alerta_fin_de_semana, alerta_inicio_antes_de_firma,
       alerta_valor_atipico, alerta_posible_fraccionamiento, alerta_concentracion,
       alerta_adiciones_altas, alerta_contratista_no_identificado, alerta_anticipo_alto,
       COUNT(*) AS contratos
FROM gold_alertas_contratos
GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9
ORDER BY contratos DESC
