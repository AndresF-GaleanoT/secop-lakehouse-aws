# SPDX-License-Identifier: AGPL-3.0-or-later
"""Verifica que las cifras de la web publicada sean reales, sin confiar en la capa oro.

Descarga los JSON que sirve CloudFront (lo mismo que ve el público) y los compara con:
  1. Consultas independientes en Athena sobre la capa plata: las reglas (contratación directa, valores
     imposibles, alertas sencillas, excepciones de la Ley de Garantías) se vuelven a escribir en SQL, sin
     usar el código de Glue que llenó la capa oro.
  2. La fuente original: la API de SECOP II en datos.gov.co (conteos totales, por año y de una entidad).
  3. Las mediciones guardadas en el repositorio (resultados_benchmark_*.csv) para las cifras fijas.

Escribe la tabla en resultados_verificacion_web.csv. Uso:
    python scripts/verificar_web.py
"""

from __future__ import annotations

import csv
import json
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

import boto3

RAIZ = Path(__file__).resolve().parent.parent
WEB = "https://d48p8jbrfjaba.cloudfront.net/data/"
API = "https://www.datos.gov.co/resource/jbjy-vk9h.json"
WORKGROUP, DATABASE = "secop", "secop_lakehouse_db"
DIRECTA = "modalidad_contratacion IN ('CONTRATACIÓN DIRECTA', 'CONTRATACIÓN DIRECTA (CON OFERTAS)')"
BILLON = "1000000000000"
ANIOS_ELECCION = {2018, 2022, 2026}
MESES = ["ene.", "feb.", "mar.", "abr.", "may.", "jun.", "jul.", "ago.", "sep.", "oct.", "nov.", "dic."]

athena = boto3.client("athena", region_name="us-east-1")


# ---------------------------------------------------------------- Fuentes
def web(nombre: str):
    with urllib.request.urlopen(f"{WEB}{nombre}.json", timeout=60) as r:
        j = json.load(r)
    return j if "columnas" not in j else [dict(zip(j["columnas"], f)) for f in j["filas"]]


def sql(consulta: str) -> list[dict]:
    qid = athena.start_query_execution(
        QueryString=consulta, WorkGroup=WORKGROUP, QueryExecutionContext={"Database": DATABASE}
    )["QueryExecutionId"]
    while True:
        ej = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]
        if ej["Status"]["State"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        time.sleep(1)
    if ej["Status"]["State"] != "SUCCEEDED":
        raise RuntimeError(ej["Status"].get("StateChangeReason"))
    filas, columnas = [], None
    for pagina in athena.get_paginator("get_query_results").paginate(QueryExecutionId=qid):
        datos = pagina["ResultSet"]["Rows"]
        if columnas is None:
            columnas = [c["VarCharValue"] for c in datos[0]["Data"]]
            datos = datos[1:]
        filas += [{c: d.get("VarCharValue") for c, d in zip(columnas, f["Data"])} for f in datos]
    return filas


def api(**parametros) -> list[dict]:
    url = f"{API}?{urllib.parse.urlencode({'$' + k: v for k, v in parametros.items()})}"
    pedido = urllib.request.Request(url, headers={"User-Agent": "verificacion-secop-lakehouse"})
    with urllib.request.urlopen(pedido, timeout=300) as r:
        return json.load(r)


# ---------------------------------------------------------------- Consultas independientes sobre plata
SQL_TOTALES = f"""
SELECT COUNT(*) AS contratos,
       COUNT(DISTINCT id_contrato) AS ids,
       SUM(CASE WHEN valor_contrato BETWEEN 0 AND {BILLON} THEN valor_contrato END) AS valor,
       SUM(CASE WHEN valor_contrato > {BILLON} THEN 1 ELSE 0 END) AS mayores_billon,
       SUM(CASE WHEN valor_contrato < 0 THEN 1 ELSE 0 END) AS negativos,
       SUM(CASE WHEN valor_contrato IS NULL THEN 1 ELSE 0 END) AS sin_valor,
       SUM(CASE WHEN {DIRECTA} THEN 1 ELSE 0 END) AS directa,
       SUM(CASE WHEN year(fecha_firma) BETWEEN 2015 AND year(current_date)
                 AND valor_contrato BETWEEN 0 AND {BILLON} THEN valor_contrato END) AS valor_anios,
       SUM(CASE WHEN year(fecha_firma) BETWEEN 2015 AND year(current_date) AND {DIRECTA}
                 AND valor_contrato BETWEEN 0 AND {BILLON} THEN valor_contrato END) AS valor_directa_anios,
       SUM(CASE WHEN day_of_week(fecha_firma) IN (6, 7) THEN 1 ELSE 0 END) AS fin_de_semana,
       SUM(CASE WHEN fecha_inicio < fecha_firma THEN 1 ELSE 0 END) AS inicio_antes_de_firma,
       SUM(CASE WHEN documento_proveedor IS NULL THEN 1 ELSE 0 END) AS contratista_no_identificado,
       SUM(CASE WHEN valor_contrato > 0 AND valor_anticipo * 100 > valor_contrato * 50 THEN 1 ELSE 0 END) AS anticipo_alto,
       CAST(MAX(CASE WHEN fecha_firma <= current_date THEN fecha_firma END) AS varchar) AS ultima_firma,
       COUNT(DISTINCT nit_entidad) AS nits
FROM silver_contratos"""

SQL_MESES = f"""
SELECT year(fecha_firma) AS anio, month(fecha_firma) AS mes, COUNT(*) AS contratos
FROM silver_contratos WHERE fecha_firma IS NOT NULL GROUP BY 1, 2"""

# Ley 996 de 2005, art. 33, escrita de nuevo en SQL (misma regla que secop_transforms.py, sin usar su código).
CTE_LEY = f"""
WITH base AS (
  SELECT nit_entidad, fecha_firma, {DIRECTA} AS directa,
         regexp_replace(COALESCE(justificacion_modalidad, ''), '\\s+', ' ') AS just,
         COALESCE(regexp_like(regexp_replace(nombre_entidad, '\\s+', ' '),
           'HOSPITAL|DISPENSARIO|CL[IÍ]NICA|PRESTADORA DE SALUD|EMPRESA SOCIAL DEL ESTADO|\\bE\\.?S\\.?E\\b'), false) AS nombre_salud,
         COALESCE(regexp_like(sector, '^SALUD Y PROTECCI'), false) AS sector_salud
  FROM silver_contratos),
ent AS (
  SELECT nit_entidad,
         MAX(CASE WHEN nombre_salud THEN 1 ELSE 0 END) = 1
           OR AVG(CASE WHEN sector_salud THEN 1.0 ELSE 0.0 END) >= 0.5 AS ent_salud
  FROM base WHERE nit_entidad IS NOT NULL GROUP BY nit_entidad),
marcado AS (
  SELECT b.nit_entidad, b.fecha_firma, COALESCE(b.directa, false) AS directa,
         regexp_like(b.just, 'URGENCIA MANIFIESTA|CR[EÉ]DITO P[UÚ]BLICO|RESERVA')
           OR COALESCE(CASE WHEN b.nit_entidad IS NOT NULL THEN e.ent_salud
                            ELSE b.nombre_salud OR b.sector_salud END, false) AS exceptuado
  FROM base b LEFT JOIN ent e ON b.nit_entidad = e.nit_entidad)"""

SQL_LEY_PERIODOS = CTE_LEY + """
SELECT CASE WHEN fecha_firma BETWEEN DATE '2024-12-31' AND DATE '2025-01-30' THEN '0'
            WHEN fecha_firma BETWEEN DATE '2025-12-31' AND DATE '2026-01-30' THEN '1'
            WHEN fecha_firma BETWEEN DATE '2026-01-31' AND DATE '2026-06-21' THEN '2'
            WHEN fecha_firma BETWEEN DATE '2026-06-22' AND DATE '2026-07-22' THEN '3' END AS periodo,
       SUM(CASE WHEN directa AND NOT exceptuado THEN 1 ELSE 0 END) AS sin_excepcion,
       SUM(CASE WHEN directa AND exceptuado THEN 1 ELSE 0 END) AS exceptuada
FROM marcado WHERE fecha_firma BETWEEN DATE '2024-12-31' AND DATE '2026-07-22'
GROUP BY 1"""

SQL_LEY_SEMANA = CTE_LEY + """
SELECT CAST(date_trunc('week', fecha_firma) AS varchar) AS semana,
       SUM(CASE WHEN directa AND NOT exceptuado THEN 1 ELSE 0 END) AS sin_excepcion
FROM marcado WHERE fecha_firma BETWEEN DATE '2024-10-01' AND DATE '2026-10-31'
GROUP BY 1 ORDER BY 2 DESC LIMIT 1"""


def sql_entidad(nits: list[str]) -> str:
    lista = ", ".join(f"'{n}'" for n in nits)
    return CTE_LEY + f"""
SELECT nit_entidad, COUNT(*) AS contratos,
       SUM(CASE WHEN fecha_firma BETWEEN DATE '2026-01-31' AND DATE '2026-06-21'
                 AND directa AND NOT exceptuado THEN 1 ELSE 0 END) AS restriccion_sin_excepcion
FROM marcado WHERE nit_entidad IN ({lista}) GROUP BY 1"""


# NIT que aparecen con y sin dígito de verificación: 800094386 y 8000943862 son la misma entidad.
SQL_NIT_PARTIDO = """
WITH n AS (SELECT DISTINCT nit_entidad FROM silver_contratos WHERE nit_entidad IS NOT NULL)
SELECT COUNT(*) AS pares FROM n a JOIN n b ON b.nit_entidad = a.nit_entidad || substr(b.nit_entidad, length(b.nit_entidad), 1)
  AND length(b.nit_entidad) = length(a.nit_entidad) + 1 AND length(a.nit_entidad) = 9"""


# ---------------------------------------------------------------- Comparación
resultados: list[dict] = []


def comparar(nombre, valor_web, independiente, fuente, tolerancia=0.0, nota=""):
    """Diferencia relativa dentro de la tolerancia: COINCIDE. tolerancia 0 exige igualdad exacta."""
    try:
        w, i = float(valor_web), float(independiente)
        diferencia = w - i
        ok = abs(diferencia) <= tolerancia * max(abs(i), 1) if tolerancia else abs(diferencia) < 1e-6
    except (TypeError, ValueError):
        diferencia, ok = "", valor_web == independiente
    resultados.append(
        {
            "verificacion": nombre,
            "valor_web": valor_web,
            "valor_independiente": independiente,
            "fuente": fuente,
            "diferencia": diferencia if diferencia == "" else round(diferencia, 4),
            "resultado": "COINCIDE" if ok else "REVISAR",
            "nota": nota,
        }
    )


def main():
    print("Descargando los JSON de la web publicada…")
    meta, resumen = web("meta"), web("resumen")[0]
    anual, mensual, deptos = web("anual"), web("mensual"), web("departamentos")
    entidades, periodos, diario = web("entidades"), web("ley_periodos"), web("ley_diario")
    tot = {k: sum((d[k] or 0) for d in deptos) for k in deptos[0] if k.startswith(("contratos", "valor"))}

    print("Consultando la capa plata en Athena (consultas independientes)…")
    s = sql(SQL_TOTALES)[0]
    meses = sql(SQL_MESES)
    ley = {f["periodo"]: f for f in sql(SQL_LEY_PERIODOS)}
    semana = sql(SQL_LEY_SEMANA)[0]
    nit_partido = sql(SQL_NIT_PARTIDO)[0]["pares"]

    # 1. Totales
    comparar("Contratos únicos (inicio)", resumen["contratos"], s["contratos"], "plata")
    comparar("Sin id_contrato repetido en plata", s["contratos"], s["ids"], "plata")
    comparar("Valor contratado, COP (inicio)", tot["valor_total"], s["valor"], "plata", 1e-9)
    no_conf = int(s["mayores_billon"]) + int(s["negativos"]) + int(s["sin_valor"])
    comparar("Valores imposibles excluidos de las sumas", tot["contratos_valor_no_confiable"], no_conf, "plata", 0,
             f"más de un billón: {s['mayores_billon']}; negativos: {s['negativos']}; sin valor: {s['sin_valor']}")
    comparar("% contratación directa (contratos)", round(100 * tot["contratos_contratacion_directa"] / tot["contratos"], 1),
             round(100 * int(s["directa"]) / int(s["contratos"]), 1), "plata")
    web_valor_dir = 100 * sum(a["valor_directa"] or 0 for a in anual) / sum(a["valor_total"] or 0 for a in anual)
    comparar("% del valor por contratación directa", round(web_valor_dir, 1),
             round(100 * float(s["valor_directa_anios"]) / float(s["valor_anios"]), 1), "plata")
    comparar("Último contrato firmado", resumen["ultima_fecha_firma"], s["ultima_firma"], "plata")

    # 2. Alertas que se pueden recalcular con una sola fila (las demás dependen de ventanas y cuartiles)
    for alerta in ["contratacion_directa", "fin_de_semana", "inicio_antes_de_firma",
                   "contratista_no_identificado", "anticipo_alto"]:
        clave = "directa" if alerta == "contratacion_directa" else alerta
        comparar(f"Alerta {alerta.replace('_', ' ')}", tot[f"contratos_{alerta}"], s[clave], "plata")
    comparar("Contratos con al menos una alerta (consistencia oro)", tot["contratos_con_alerta"],
             sql("SELECT SUM(CASE WHEN puntaje_riesgo > 0 THEN 1 ELSE 0 END) AS n FROM gold_alertas_contratos")[0]["n"],
             "oro: gold_alertas_contratos")

    # 3. Años y meses
    por_anio = defaultdict(int)
    por_mes = defaultdict(dict)
    for f in meses:
        a, m, n = int(f["anio"]), int(f["mes"]), int(f["contratos"])
        por_anio[a] += n
        por_mes[a][m] = n
    for a in anual:
        comparar(f"Contratos firmados en {a['anio']}", a["contratos"], por_anio[a["anio"]], "plata")
    hoy = date.today().year
    picos = {a: max(ms, key=ms.get) for a, ms in por_mes.items() if 2017 <= a <= hoy}
    enero = sorted(a for a, m in picos.items() if m == 1)
    febrero = sorted(a for a, m in picos.items() if m == 2 and a < hoy)
    comparar("Años con pico en enero = años de elección presidencial", ",".join(map(str, enero)),
             ",".join(map(str, sorted(ANIOS_ELECCION))), "plata",
             nota=f"pico de cada año: {picos}; febrero en {len(febrero)} de los demás años completos")

    # 4. Ley de Garantías (excepciones recalculadas en SQL)
    p = {r["periodo"][0]: r for r in periodos}
    for k, nombre in [("0", "mismo mes de 2025"), ("1", "mes antes de la restricción"), ("2", "durante la restricción"), ("3", "mes después")]:
        comparar(f"Ley: directa sin excepción, {nombre}", p[k]["directa_sin_excepcion"], ley[k]["sin_excepcion"], "plata")
        comparar(f"Ley: directa con excepción, {nombre}", p[k]["directa_exceptuada"], ley[k]["exceptuada"], "plata")
    semanas = defaultdict(int)
    for d in diario:
        f = date.fromisoformat(d["fecha_firma"])
        semanas[date.fromordinal(f.toordinal() - f.weekday())] += d["directa_sin_excepcion"]
    lunes, pico = max(semanas.items(), key=lambda x: x[1])
    comparar("Semana con más directa sin excepción", f"{lunes} ({pico})", f"{semana['semana'][:10]} ({semana['sin_excepcion']})", "plata")

    # 5. Entidades de ejemplo: la ficha contra plata y contra la API
    ejemplo = {e["nit_entidad"]: e for e in entidades if e["nit_entidad"] in ("8000943862",)}
    inpec = max(entidades, key=lambda e: e["ley_sin_excepcion_restriccion"])
    nits = ["8000943862", inpec["nit_entidad"]]
    ent = {f["nit_entidad"]: f for f in sql(sql_entidad(nits))}
    for nit in nits:
        e = ejemplo.get(nit) or inpec
        comparar(f"Contratos de {e['nombre_entidad']} (NIT {nit})", e["contratos"], ent[nit]["contratos"], "plata")
    comparar(f"{inpec['nombre_entidad']}: directa sin excepción en la restricción", inpec["ley_sin_excepcion_restriccion"],
             ent[inpec["nit_entidad"]]["restriccion_sin_excepcion"], "plata")

    print("Consultando la API de SECOP II (datos.gov.co)…")
    total_api = int(api(select="count(*) as n")[0]["n"])
    comparar("Registros en la API frente a contratos únicos", resumen["contratos"], total_api, "API SECOP II", 0.005,
             f"la API tiene {total_api - int(resumen['contratos']):,} filas más: duplicados por id_contrato, filas sin id y lo publicado después de la última carga".replace(",", "."))
    # Por año y, en el año en curso, por mes: aquí se ven los contratos que SECOP publicó tarde, después de
    # la ventana que vuelve a leer cada carga. Cualquier faltante se marca para revisar.
    por_anio_api = {int(float(f["anio"])): int(f["n"]) for f in api(select="date_extract_y(fecha_de_firma) as anio, count(*) as n", group="anio") if f.get("anio")}
    for a in anual:
        if a["contratos"] > 1000:
            faltan = por_anio_api.get(a["anio"], 0) - a["contratos"]
            comparar(f"Contratos {a['anio']} frente a la API", a["contratos"], por_anio_api.get(a["anio"], 0), "API SECOP II", 0,
                     f"faltan {faltan} contratos publicados después de la ventana de carga" if faltan > 0 else "")
    anio_actual = max(a["anio"] for a in anual)
    por_mes_api = {int(float(f["mes"])): int(f["n"]) for f in api(select="date_extract_m(fecha_de_firma) as mes, count(*) as n",
                   where=f"date_extract_y(fecha_de_firma) = {anio_actual}", group="mes") if f.get("mes")}
    for m in mensual:
        if m["anio"] == anio_actual:
            faltan = por_mes_api.get(m["mes"], 0) - m["contratos"]
            comparar(f"Contratos {MESES[m['mes'] - 1]} {anio_actual} frente a la API", m["contratos"], por_mes_api.get(m["mes"], 0),
                     "API SECOP II", 0, f"faltan {faltan}" if faltan > 0 else "")
    for nit in ["8000943862"]:
        n_api = int(api(select="count(*) as n", where=f"nit_entidad = '{nit}'")[0]["n"])
        comparar(f"Contratos del NIT {nit} frente a la API", ejemplo[nit]["contratos"], n_api, "API SECOP II", 0.05,
                 "la API repite contratos; plata deja uno por id_contrato")
    resultados.append({"verificacion": "Entidades partidas en dos NIT (con y sin dígito de verificación)", "valor_web": "",
                       "valor_independiente": nit_partido, "fuente": "plata", "diferencia": "", "resultado": "LIMITACIÓN",
                       "nota": "SECOP publica algunas entidades con y sin dígito de verificación; la web las muestra separadas"})

    # 6. Cifras fijas de la web contra las mediciones del repositorio
    with open(RAIZ / "resultados_benchmark_historico.csv", encoding="utf-8") as f:
        bench = {int(r["hilos"]): r for r in csv.DictReader(f)}
    comparar("Speedup de la descarga con 4 hilos (1,86×)", 1.86, float(bench[4]["speedup"]), "resultados_benchmark_historico.csv")
    comparar("Descarga completa con 1 hilo (44,5 min)", 44.5, round(float(bench[1]["tiempo_pared_s"]) / 60, 1), "resultados_benchmark_historico.csv")
    comparar("Descarga completa con 4 hilos (24 min)", 24, round(float(bench[4]["tiempo_pared_s"]) / 60), "resultados_benchmark_historico.csv")
    comparar("Costo por actualización (US$0,07)", 0.07, round(886 / 3600 * 0.29, 2), "886 DPU-s medidos × 0,29 USD/DPU-h")
    comparar("Entidades con ficha", meta["archivos"]["entidades"]["filas"], len(entidades), "data/entidades.json")

    salida = RAIZ / "resultados_verificacion_web.csv"
    with open(salida, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(resultados[0]))
        w.writeheader()
        w.writerows(resultados)
    ancho = max(len(r["verificacion"]) for r in resultados)
    for r in resultados:
        print(f"{r['resultado']:<11} {r['verificacion']:<{ancho}}  web={r['valor_web']}  independiente={r['valor_independiente']}  {r['nota']}")
    revisar = sum(r["resultado"] == "REVISAR" for r in resultados)
    print(f"\n{len(resultados)} verificaciones, {revisar} por revisar. Detalle en {salida.name}")


if __name__ == "__main__":
    main()
