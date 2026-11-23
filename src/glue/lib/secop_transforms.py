# SPDX-License-Identifier: AGPL-3.0-or-later
"""Transformaciones puras de PySpark para el lakehouse SECOP (arquitectura Medallion).

No depende de awsglue, así que se prueba localmente con pytest + pyspark.
Los jobs de Glue la cargan con --extra-py-files.

El pipeline responde tres objetivos, y cada capa guarda solo lo necesario para ellos:
  1. Panorama de la contratación: por departamento, sector, año y mes; % de contratación directa.
  2. Índice de patrones irregulares por entidad y por departamento, a partir de alertas por contrato.
  3. Ley de Garantías 2026: contratación directa antes, durante y después de la restricción.

Bronce: respuesta completa de la API (91 columnas), sin cambios.
Plata:  solo las 16 columnas que usan los tres objetivos, limpias y tipadas (+ valor_confiable).
Oro:    una tabla (o dos) por objetivo.

Nombres de columna verificados contra la API (dataset jbjy-vk9h) en noviembre de 2026:
https://www.datos.gov.co/resource/jbjy-vk9h.json?$limit=1
"""

from __future__ import annotations

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F
from pyspark.sql import types as T

# ---------------------------------------------------------------------------
# Columnas de plata: columna en la API (bronce) -> columna en plata, y para qué se usa
# ---------------------------------------------------------------------------
COLUMN_MAP: dict[str, str] = {
    "id_contrato": "id_contrato",  # llave del contrato (deduplicación)
    "nit_entidad": "nit_entidad",  # obj. 2 y 3: agrupar por entidad
    "nombre_entidad": "nombre_entidad",  # obj. 2 y 3: nombre en los rankings
    "departamento": "departamento",  # obj. 1, 2 y 3
    "sector": "sector",  # obj. 1
    "modalidad_de_contratacion": "modalidad_contratacion",  # obj. 1, 2 y 3: % contratación directa
    "tipo_de_contrato": "tipo_contrato",  # obj. 2: alerta de valor atípico por tipo
    "documento_proveedor": "documento_proveedor",  # obj. 2: concentración, fraccionamiento, no identificado
    "fecha_de_firma": "fecha_firma",  # obj. 1, 2 y 3
    "fecha_de_inicio_del_contrato": "fecha_inicio",  # obj. 2: inicio antes de firma, adiciones
    "fecha_de_fin_del_contrato": "fecha_fin",  # obj. 2: adiciones
    "dias_adicionados": "dias_adicionados",  # obj. 2: adiciones
    "valor_del_contrato": "valor_contrato",  # obj. 1, 2 y 3
    "valor_de_pago_adelantado": "valor_anticipo",  # obj. 2: anticipo > 50 % (Ley 80, art. 40)
    "codigo_de_categoria_principal": "codigo_unspsc",  # obj. 2: fraccionamiento del mismo bien o servicio
    "justificacion_modalidad_de": "justificacion_modalidad",  # obj. 3: excepciones de la Ley 996 de 2005
}

DATE_COLUMNS = ["fecha_firma", "fecha_inicio", "fecha_fin"]
UPPER_COLUMNS = [
    "nombre_entidad", "departamento", "sector", "modalidad_contratacion", "tipo_contrato",
    "justificacion_modalidad",
]
MODALIDADES_DIRECTAS = ["CONTRATACIÓN DIRECTA", "CONTRATACIÓN DIRECTA (CON OFERTAS)"]

# ---------------------------------------------------------------------------
# Objetivo 3: Ley de Garantías 2026 (Ley 996 de 2005, art. 33)
# Sin contratación directa desde 4 meses antes de la elección presidencial (31 de mayo de 2026)
# hasta la segunda vuelta (21 de junio de 2026). Se compara con el mismo mes de 2025.
# ---------------------------------------------------------------------------
LEY_GARANTIAS_PERIODOS = [
    ("0_mismo_mes_2025_sin_elecciones", "2024-12-31", "2025-01-30"),
    ("1_mes_antes_de_la_restriccion", "2025-12-31", "2026-01-30"),
    ("2_restriccion", "2026-01-31", "2026-06-21"),
    ("3_mes_despues_de_la_restriccion", "2026-06-22", "2026-07-22"),
]
LEY_GARANTIAS_VENTANA_DIARIA = ("2024-10-01", "2026-10-31")

# Excepciones a la restricción (Ley 996 de 2005, art. 33).
# 1) Por la causal publicada en justificacion_modalidad_de (valores reales de la API).
#    Se evalúan en orden: gana la primera que se cumple.
LEY_GARANTIAS_EXCEPCIONES = [
    ("emergencia", r"URGENCIA MANIFIESTA"),  # emergencias y desastres
    ("credito_publico", r"CR[EÉ]DITO P[UÚ]BLICO"),  # contratos de crédito público
    ("defensa_y_seguridad", r"RESERVA"),  # bienes y servicios sujetos a reserva
]
# 2) Entidades sanitarias y hospitalarias (aproximación: el dataset no marca si la entidad es un
#    hospital). Se decide por NIT: si algún contrato de la entidad es del sector salud o su nombre
#    parece de hospital, cuenta toda la entidad (una misma entidad publica con nombres distintos,
#    por ejemplo "UNIDAD PRESTADORA DE SALUD ARAUCA" y "METUN"). Los hospitales de la Policía y el
#    Ejército están en el sector defensa, por eso también se mira el nombre.
PATRON_SECTOR_SALUD = r"^SALUD Y PROTECCI"
PATRON_NOMBRE_SALUD = r"HOSPITAL|DISPENSARIO|CL[IÍ]NICA|PRESTADORA DE SALUD|EMPRESA SOCIAL DEL ESTADO|\bE\.?S\.?E\b"

# ---------------------------------------------------------------------------
# Objetivo 2: umbrales de las alertas de patrones irregulares
# Cada alerta marca un patrón fuera de lo habitual o de un tope legal, para priorizar qué revisar.
# No califica conductas: un contrato con alertas puede tener una explicación válida.
# ---------------------------------------------------------------------------
UMBRAL_FRACCIONAMIENTO_CONTRATOS = 3  # contratos de la misma entidad, contratista y código UNSPSC...
UMBRAL_FRACCIONAMIENTO_DIAS = 30  # ...dentro de esta ventana de días
UMBRAL_CONCENTRACION_PCT = 30  # % del valor de una entidad que se lleva un solo contratista
UMBRAL_CONCENTRACION_MIN_CONTRATOS = 10  # solo en entidades con al menos este número de contratos
UMBRAL_ADICION_PCT = 50  # días adicionados como % del plazo original
# Calidad: un contrato individual de más de 1 billón de COP casi siempre es un error de digitación
# (en los datos hay contratos de 10^14 a 10^17 COP). Esos valores no se suman; el contrato se conserva
# con valor_confiable = false para revisarlo aparte.
UMBRAL_VALOR_CONFIABLE = 1_000_000_000_000
UMBRAL_ANTICIPO_PCT = 50  # tope legal del anticipo (Ley 80 de 1993, art. 40, parágrafo)
FACTOR_VALOR_ATIPICO = 3  # valor > Q3 + FACTOR * IQR del mismo tipo de contrato
MIN_CONTRATOS_RANKING = 20  # entidades con menos contratos no entran al ranking (porcentajes inestables)

ALERTAS = {
    "alerta_contratacion_directa": "Adjudicado sin competencia (contratación directa)",
    "alerta_fin_de_semana": "Firmado en sábado o domingo",
    "alerta_inicio_antes_de_firma": "La ejecución empezó antes de la firma",
    "alerta_valor_atipico": "Valor muy superior al habitual para ese tipo de contrato",
    "alerta_posible_fraccionamiento": "Varios contratos del mismo bien o servicio (UNSPSC), contratista y entidad en pocos días",
    "alerta_concentracion": "El contratista concentra gran parte de lo que contrata la entidad",
    "alerta_adiciones_altas": "Prórrogas mayores a la mitad del plazo original",
    "alerta_contratista_no_identificado": "No se publicó un documento válido del contratista",
    "alerta_anticipo_alto": "Anticipo mayor al 50 % del valor del contrato (Ley 80, art. 40)",
}


# ===========================================================================
# BRONCE -> PLATA
# ===========================================================================
def normalize_contracts(raw: DataFrame, load_id: str) -> DataFrame:
    """Selecciona las 16 columnas necesarias, las limpia y las tipa. Las faltantes quedan en null."""
    selected = [
        (F.col(f"`{src}`").cast(T.StringType()) if src in raw.columns else F.lit(None).cast(T.StringType())).alias(dst)
        for src, dst in COLUMN_MAP.items()
    ]
    df = raw.select(*selected)

    # Texto: trim y vacíos -> null.
    for name in COLUMN_MAP.values():
        df = df.withColumn(name, F.when(F.trim(F.col(name)) == "", None).otherwise(F.trim(F.col(name))))
    for name in UPPER_COLUMNS:
        df = df.withColumn(name, F.upper(F.col(name)))

    # NIT y documento: solo dígitos. Sin dígitos ("No Definido", nombre de un consorcio) -> null,
    # para que contratistas distintos no se fundan en uno solo.
    for name in ["nit_entidad", "documento_proveedor"]:
        digits = F.regexp_replace(F.col(name), r"[^0-9]", "")
        df = df.withColumn(name, F.when(digits == "", None).otherwise(digits))

    # Código UNSPSC: "V1.90141701" -> "90141701"; "UNSPECIFIED" -> null.
    # Se toman solo los dígitos del final: el prefijo "V1" también tiene un dígito.
    unspsc = F.regexp_extract(F.col("codigo_unspsc"), r"(\d+)$", 1)
    df = df.withColumn("codigo_unspsc", F.when(unspsc == "", None).otherwise(unspsc))

    for name in DATE_COLUMNS:
        df = df.withColumn(name, F.to_date(F.to_timestamp(F.col(name))))
    for name in ["valor_contrato", "valor_anticipo"]:
        df = df.withColumn(name, F.col(name).cast(T.DecimalType(20, 2)))
    df = df.withColumn("dias_adicionados", F.col("dias_adicionados").cast(T.IntegerType()))
    df = df.withColumn(
        "valor_confiable",
        F.coalesce(F.col("valor_contrato").between(0, UMBRAL_VALOR_CONFIABLE), F.lit(False)),
    )
    df = df.withColumn("es_contratacion_directa", F.col("modalidad_contratacion").isin(MODALIDADES_DIRECTAS))

    df = (
        df.withColumn("load_id", F.lit(load_id))  # trazabilidad: de qué carga vino cada fila
        .withColumn("processed_at", F.current_timestamp())
        .filter(F.col("id_contrato").isNotNull())
    )
    return deduplicate(df)


def deduplicate(df: DataFrame) -> DataFrame:
    """Un registro por contrato: se queda con el de fecha de firma más reciente."""
    window = Window.partitionBy("id_contrato").orderBy(
        F.col("fecha_firma").desc_nulls_last(), F.col("valor_contrato").desc_nulls_last()
    )
    return df.withColumn("_rn", F.row_number().over(window)).filter("_rn = 1").drop("_rn")


# ---------------------------------------------------------------------------
# Calidad de datos (se evalúa sobre plata antes de escribir)
# ---------------------------------------------------------------------------
CRITICAL_RULES = {"id_contrato_nulo", "id_contrato_duplicado"}


def quality_report(df: DataFrame) -> dict[str, int]:
    """Cuenta registros que incumplen cada regla. 0 = la regla se cumple."""
    total = df.count()
    distinct_ids = df.select("id_contrato").distinct().count()
    row = df.agg(
        F.sum(F.col("id_contrato").isNull().cast("int")).alias("id_contrato_nulo"),
        F.sum(F.col("nit_entidad").isNull().cast("int")).alias("nit_entidad_nulo"),
        F.sum(F.col("documento_proveedor").isNull().cast("int")).alias("documento_proveedor_nulo"),
        F.sum(F.col("fecha_firma").isNull().cast("int")).alias("fecha_firma_nula"),
        F.sum(F.col("departamento").isNull().cast("int")).alias("departamento_nulo"),
        F.sum((F.col("valor_contrato") < 0).cast("int")).alias("valor_negativo"),
        F.sum((F.col("valor_contrato") > UMBRAL_VALOR_CONFIABLE).cast("int")).alias("valor_no_confiable"),
        F.sum((F.col("fecha_fin") < F.col("fecha_inicio")).cast("int")).alias("fecha_fin_antes_de_inicio"),
    ).first()
    report = {key: int(value or 0) for key, value in row.asDict().items()}
    report["id_contrato_duplicado"] = total - distinct_ids
    report["total_registros"] = total
    return report


def critical_failures(report: dict[str, int]) -> dict[str, int]:
    """Reglas críticas que fallaron: si hay alguna, el job debe detenerse."""
    return {rule: report[rule] for rule in CRITICAL_RULES if report.get(rule, 0) > 0}


# ===========================================================================
# PLATA -> ORO
# ===========================================================================
def _valor():
    """Valor del contrato solo si es confiable: es lo que se suma en todas las tablas de oro."""
    return F.when(F.col("valor_confiable"), F.col("valor_contrato"))


def _pct(part, total):
    """Porcentaje con un decimal; null si el total es 0 o null."""
    return F.when(total > 0, F.round(part.cast("double") / total.cast("double") * 100, 1))


# ---------------------------------------------------------------------------
# Objetivo 1: panorama de la contratación
# ---------------------------------------------------------------------------
def build_panorama(silver: DataFrame) -> DataFrame:
    """Contratos y valor por año, mes, departamento, sector y modalidad.

    Responde: cuánto contrata el Estado por departamento, sector y año; qué % es contratación
    directa y cómo cambia; y la estacionalidad (por ejemplo, el pico de diciembre).
    """
    return (
        silver.filter(F.col("fecha_firma").isNotNull())
        .groupBy(
            F.year("fecha_firma").alias("anio"),
            F.month("fecha_firma").alias("mes"),
            "departamento",
            "sector",
            "modalidad_contratacion",
            "es_contratacion_directa",
        )
        .agg(
            F.count("*").alias("contratos"),
            F.sum(_valor()).alias("valor_total"),
            F.sum((~F.col("valor_confiable")).cast("int")).alias("contratos_valor_no_confiable"),
        )
    )


# ---------------------------------------------------------------------------
# Objetivo 2: alertas por contrato e índice de riesgo
# ---------------------------------------------------------------------------
def build_alertas(silver: DataFrame) -> DataFrame:
    """Una fila por contrato con cada alerta (true/false) y su puntaje (cuántas tiene)."""
    df = silver.withColumn("_dia", F.datediff(F.col("fecha_firma"), F.lit("2000-01-01")))
    plazo = F.datediff("fecha_fin", "fecha_inicio")

    cuartiles = df.groupBy("tipo_contrato").agg(
        F.percentile_approx("valor_contrato", 0.25).alias("_q1"),
        F.percentile_approx("valor_contrato", 0.75).alias("_q3"),
    )
    df = df.join(cuartiles, on="tipo_contrato", how="left")

    par = Window.partitionBy("nit_entidad", "documento_proveedor")
    # Fraccionamiento: mismo bien o servicio (código UNSPSC). Los contratos sin código quedan juntos.
    mismo_bien = Window.partitionBy("nit_entidad", "documento_proveedor", "codigo_unspsc")
    df = df.withColumn(
        "_contratos_ventana",
        F.count("*").over(mismo_bien.orderBy("_dia").rangeBetween(-UMBRAL_FRACCIONAMIENTO_DIAS, 0)),
    )
    entidad = Window.partitionBy("nit_entidad")
    df = (
        df.withColumn("_valor_entidad", F.sum(_valor()).over(entidad))
        .withColumn("_contratos_entidad", F.count("*").over(entidad))
        .withColumn("pct_valor_entidad", _pct(F.sum(_valor()).over(par), F.col("_valor_entidad")))
    )

    con_proveedor = F.col("documento_proveedor").isNotNull() & F.col("nit_entidad").isNotNull()
    flags = {
        "alerta_contratacion_directa": F.col("es_contratacion_directa"),
        "alerta_fin_de_semana": F.dayofweek("fecha_firma").isin(1, 7),
        "alerta_inicio_antes_de_firma": F.col("fecha_inicio") < F.col("fecha_firma"),
        "alerta_valor_atipico": F.col("valor_contrato")
        > F.col("_q3") + FACTOR_VALOR_ATIPICO * (F.col("_q3") - F.col("_q1")),
        "alerta_posible_fraccionamiento": con_proveedor
        & (F.col("_contratos_ventana") >= UMBRAL_FRACCIONAMIENTO_CONTRATOS),
        "alerta_concentracion": con_proveedor
        & (F.col("_contratos_entidad") >= UMBRAL_CONCENTRACION_MIN_CONTRATOS)
        & (F.col("pct_valor_entidad") >= UMBRAL_CONCENTRACION_PCT),
        "alerta_adiciones_altas": (plazo > 0) & (F.col("dias_adicionados") * 100 > plazo * UMBRAL_ADICION_PCT),
        "alerta_contratista_no_identificado": F.col("documento_proveedor").isNull(),
        "alerta_anticipo_alto": (F.col("valor_contrato") > 0)
        & (F.col("valor_anticipo") * 100 > F.col("valor_contrato") * UMBRAL_ANTICIPO_PCT),
    }
    for name, condition in flags.items():
        df = df.withColumn(name, F.coalesce(condition, F.lit(False)))  # sin dato -> sin alerta

    return df.select(
        "id_contrato",
        "nit_entidad",
        "nombre_entidad",
        "departamento",
        "fecha_firma",
        "valor_contrato",
        "valor_confiable",
        "codigo_unspsc",
        "valor_anticipo",
        "pct_valor_entidad",
        *flags.keys(),
        sum(F.col(name).cast("int") for name in flags).alias("puntaje_riesgo"),
    )


def _riesgo(alertas: DataFrame, group_cols: list[str]) -> DataFrame:
    """Agrega las alertas por entidad o por departamento y ordena el ranking."""
    agg = [
        F.count("*").alias("contratos"),
        F.sum(_valor()).alias("valor_total"),
        F.sum((~F.col("valor_confiable")).cast("int")).alias("contratos_valor_no_confiable"),
        F.sum((F.col("puntaje_riesgo") > 0).cast("int")).alias("contratos_con_alerta"),
        *[F.sum(F.col(name).cast("int")).alias(name.replace("alerta_", "contratos_")) for name in ALERTAS],
    ]
    if "nit_entidad" in group_cols:
        # Concentración: la mayor participación de un solo contratista en el valor de la entidad.
        agg.append(F.max("pct_valor_entidad").alias("pct_valor_mayor_contratista"))
    df = (
        alertas.groupBy(*group_cols)
        .agg(*agg)
        .withColumn("pct_contratos_con_alerta", _pct(F.col("contratos_con_alerta"), F.col("contratos")))
        .withColumn("pct_contratacion_directa", _pct(F.col("contratos_contratacion_directa"), F.col("contratos")))
    )
    en_ranking = F.col("contratos") >= MIN_CONTRATOS_RANKING
    orden = Window.partitionBy(en_ranking).orderBy(
        F.col("pct_contratos_con_alerta").desc(), F.col("contratos_con_alerta").desc()
    )
    return df.withColumn("posicion_ranking", F.when(en_ranking, F.row_number().over(orden)))


def build_riesgo_entidades(alertas: DataFrame) -> DataFrame:
    # Una entidad puede aparecer con nombres ligeramente distintos: se usa uno solo por NIT.
    por_nit = Window.partitionBy("nit_entidad")
    unificado = alertas.withColumn("nombre_entidad", F.max("nombre_entidad").over(por_nit)).withColumn(
        "departamento", F.max("departamento").over(por_nit)
    )
    return _riesgo(unificado, ["nit_entidad", "nombre_entidad", "departamento"])


def build_riesgo_departamentos(alertas: DataFrame) -> DataFrame:
    return _riesgo(alertas, ["departamento"])


# ---------------------------------------------------------------------------
# Objetivo 3: Ley de Garantías 2026
# ---------------------------------------------------------------------------
def _periodo_ley_garantias(fecha: str = "fecha_firma"):
    expr = None
    for label, desde, hasta in LEY_GARANTIAS_PERIODOS:
        cond = F.col(fecha).between(F.lit(desde).cast("date"), F.lit(hasta).cast("date"))
        expr = F.when(cond, F.lit(label)) if expr is None else expr.when(cond, F.lit(label))
    return expr


def _sin_espacios_dobles(columna: str):
    """Colapsa espacios repetidos: "PRESTADORA  DE SALUD" -> "PRESTADORA DE SALUD"."""
    return F.regexp_replace(F.col(columna), r"\s+", " ")


def _motivo_excepcion_ley_garantias():
    """Causal de la Ley 996 que exceptúa un contrato directo de la restricción; null si no tiene."""
    justificacion = _sin_espacios_dobles("justificacion_modalidad")
    expr = None
    for motivo, patron in LEY_GARANTIAS_EXCEPCIONES:
        cond = justificacion.rlike(patron)
        expr = F.when(cond, F.lit(motivo)) if expr is None else expr.when(cond, F.lit(motivo))
    expr = expr.when(F.col("_entidad_salud"), F.lit("entidad_sanitaria_u_hospitalaria"))
    return F.when(F.col("es_contratacion_directa"), expr)


def _con_excepcion(silver: DataFrame) -> DataFrame:
    """Agrega motivo_excepcion y exceptuado_ley_garantias (solo puede ser true en contratación directa)."""
    nombre_salud = F.coalesce(_sin_espacios_dobles("nombre_entidad").rlike(PATRON_NOMBRE_SALUD), F.lit(False))
    sector_salud = F.coalesce(F.col("sector").rlike(PATRON_SECTOR_SALUD), F.lit(False))
    por_nit = Window.partitionBy("nit_entidad")
    # Nombre: basta un contrato (las variantes de nombre son de la misma entidad).
    # Sector: la mayoría de sus contratos, para que un contrato mal clasificado no exceptúe a una alcaldía.
    entidad_salud = F.when(
        F.col("nit_entidad").isNotNull(),
        (F.max(nombre_salud.cast("int")).over(por_nit) == 1) | (F.avg(sector_salud.cast("int")).over(por_nit) >= 0.5),
    ).otherwise(nombre_salud | sector_salud)  # sin NIT: se decide con el propio contrato
    return (
        silver.withColumn("_entidad_salud", entidad_salud)
        .withColumn("motivo_excepcion", _motivo_excepcion_ley_garantias())
        .withColumn("exceptuado_ley_garantias", F.col("motivo_excepcion").isNotNull())
        .drop("_entidad_salud")
    )


def build_ley_garantias_diario(silver: DataFrame) -> DataFrame:
    """Contratos por día: no directa, directa exceptuada y directa NO exceptuada (Ley 996, art. 33).

    Muestra el pico antes del 31 de enero de 2026 y cuánta contratación directa siguió durante la
    restricción sin una causal de excepción.
    """
    desde, hasta = LEY_GARANTIAS_VENTANA_DIARIA
    return (
        _con_excepcion(silver)
        .filter(F.col("fecha_firma").between(F.lit(desde).cast("date"), F.lit(hasta).cast("date")))
        .groupBy("fecha_firma", "es_contratacion_directa", "exceptuado_ley_garantias")
        .agg(
            F.count("*").alias("contratos"),
            F.sum(_valor()).alias("valor_total"),
            F.sum((~F.col("valor_confiable")).cast("int")).alias("contratos_valor_no_confiable"),
        )
        .withColumn("periodo", _periodo_ley_garantias())
    )


def build_ley_garantias_entidades(silver: DataFrame) -> DataFrame:
    """Contratación directa por entidad en cada periodo: qué entidades firmaron antes de la restricción."""
    no_exceptuado = ~F.col("exceptuado_ley_garantias")
    return (
        _con_excepcion(silver)
        .filter(F.col("es_contratacion_directa"))
        .withColumn("periodo", _periodo_ley_garantias())
        .filter(F.col("periodo").isNotNull())
        .groupBy("periodo", "nit_entidad")
        .agg(
            F.max("nombre_entidad").alias("nombre_entidad"),
            F.max("departamento").alias("departamento"),
            F.count("*").alias("contratos_directos"),
            F.sum(_valor()).alias("valor_directos"),
            F.sum(F.col("exceptuado_ley_garantias").cast("int")).alias("contratos_directos_exceptuados"),
            F.sum(no_exceptuado.cast("int")).alias("contratos_directos_no_exceptuados"),
            F.sum(F.when(no_exceptuado, _valor())).alias("valor_directos_no_exceptuados"),
        )
    )
