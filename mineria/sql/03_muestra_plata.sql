-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Muestra determinista de ~0,9 % de los contratos (hash del id_contrato): reproducible y pequeña (~50 mil filas).
SELECT id_contrato, departamento, sector, modalidad_contratacion, tipo_contrato,
       es_contratacion_directa, fecha_firma, fecha_inicio, fecha_fin, dias_adicionados,
       CAST(valor_contrato AS DOUBLE) AS valor_contrato, valor_confiable,
       documento_proveedor IS NULL AS sin_documento_proveedor
FROM silver_contratos
WHERE abs(from_big_endian_64(xxhash64(to_utf8(id_contrato))) % 1000) < 9
