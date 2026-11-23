# SPDX-License-Identifier: AGPL-3.0-or-later
"""Verificación sin AWS: limpieza y transformación con Spark local, speedup y eficiencia.

Descarga un mes de la API pública de SECOP II con los hilos de la Lambda y lo guarda en datos_local/.
Después ejecuta las mismas transformaciones de los trabajos de Glue (src/glue/lib/secop_transforms.py)
con Spark en modo local[n], donde n es el número de núcleos:

    limpieza         bronce -> plata: normalización, deduplicación y reglas de calidad
    transformación   plata -> oro: las seis tablas analíticas

Cada medición corre en un proceso nuevo, para que ninguna aproveche una JVM ya caliente. Las tablas
se calculan completas, pero no se escriben (formato noop): esta prueba no usa S3, Glue ni Iceberg.
Los tiempos sirven para comprobar el código en un equipo y no reemplazan los del clúster en AWS.

Requisitos: Python 3.12, Java 17 y `pip install -r requirements-local.txt`.

Uso:  python scripts/verificar_spark_local.py [--mes 2026-09] [--nucleos 1 2 4 8] [--repeticiones 3]
"""

from __future__ import annotations

import argparse
import calendar
import csv
import gzip
import json
import os
import re
import statistics
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src" / "glue" / "lib"), str(ROOT / "src" / "lambda_ingest")]

DATASET = "jbjy-vk9h"
CAMPO_FECHA = "fecha_de_firma"
HILOS_DESCARGA = 4
PARTICIONES_SHUFFLE = 16  # fijas: así solo cambia el número de núcleos
JAVA_ADMITIDOS = {8, 11, 17}  # versiones que admite Spark 3.5
LIMITE_MEDICION_S = 1800


def comprobar_java() -> None:
    java_home = os.environ.get("JAVA_HOME")
    java = str(Path(java_home) / "bin" / "java") if java_home else "java"
    try:
        salida = subprocess.run([java, "-version"], capture_output=True, text=True).stderr
    except OSError:
        raise SystemExit(f"No se encontró Java en {java}. Instala Java 17 o corrige JAVA_HOME.")
    version = re.search(r'version "(\d+)(?:\.(\d+))?', salida)
    mayor = int(version.group(2) if version and version.group(1) == "1" else version.group(1)) if version else 0
    if mayor not in JAVA_ADMITIDOS:
        raise SystemExit(f"Spark 3.5 necesita Java 8, 11 o 17, y {java} es Java {mayor}. Ajusta JAVA_HOME.")


def descargar_mes(mes: str, destino: Path) -> dict:
    """Guarda el mes como archivos JSONL comprimidos. Si ya está completo, lo reutiliza."""
    marca = destino / "_COMPLETO.json"
    if marca.exists():
        return json.loads(marca.read_text(encoding="utf-8"))

    from handler import LoadWindow, build_where, download_parallel

    anio, numero = map(int, mes.split("-"))
    ventana = LoadWindow(
        load_id=f"local-{mes}",
        start=date(anio, numero, 1),
        end=date(anio, numero, calendar.monthrange(anio, numero)[1]),
    )
    destino.mkdir(parents=True, exist_ok=True)

    def escribir(parte: int, pagina: list[dict]) -> None:
        with gzip.open(destino / f"part-{parte:05d}.jsonl.gz", "wt", encoding="utf-8") as f:
            for fila in pagina:
                f.write(json.dumps(fila, ensure_ascii=False) + "\n")

    inicio = time.perf_counter()
    registros, paginas = download_parallel(
        DATASET, build_where(CAMPO_FECHA, ventana), escribir, HILOS_DESCARGA
    )
    if not registros:
        raise SystemExit(f"La API no devolvió contratos para {mes}.")
    info = {"mes": mes, "registros": registros, "paginas": paginas,
            "descarga_s": round(time.perf_counter() - inicio, 1)}
    marca.write_text(json.dumps(info), encoding="utf-8")
    return info


def medir(entrada: Path, nucleos: int, memoria: str) -> dict:
    """Una medición completa. Se ejecuta en su propio proceso."""
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F

    from secop_transforms import (
        build_alertas,
        build_ley_garantias_diario,
        build_ley_garantias_entidades,
        build_panorama,
        build_riesgo_departamentos,
        build_riesgo_entidades,
        critical_failures,
        normalize_contracts,
        quality_report,
    )

    spark = (
        SparkSession.builder.master(f"local[{nucleos}]")
        .appName(f"secop-verificacion-{nucleos}")
        .config("spark.driver.memory", memoria)
        .config("spark.sql.shuffle.partitions", PARTICIONES_SHUFFLE)
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("ERROR")

    inicio = time.perf_counter()
    # Lista explícita: en Windows, sin los binarios de Hadoop, un comodín deja bloqueada la lectura.
    crudo = spark.read.json([p.as_uri() for p in sorted(entrada.glob("part-*.jsonl.gz"))])
    plata = normalize_contracts(crudo, "verificacion-local").cache()
    reporte = quality_report(plata)
    fallas = critical_failures(reporte)
    if fallas:
        raise ValueError(f"Fallaron reglas críticas de calidad: {fallas}")
    fin_limpieza = time.perf_counter()

    alertas = build_alertas(plata).cache()
    tablas = {
        "gold_panorama_contratacion": build_panorama(plata),
        "gold_alertas_contratos": alertas,
        "gold_riesgo_entidades": build_riesgo_entidades(alertas),
        "gold_riesgo_departamentos": build_riesgo_departamentos(alertas),
        "gold_ley_garantias_diario": build_ley_garantias_diario(plata),
        "gold_ley_garantias_entidades": build_ley_garantias_entidades(plata),
    }
    for tabla in tablas.values():
        tabla.write.format("noop").mode("overwrite").save()
    fin = time.perf_counter()

    # Controles fuera del tiempo medido.
    resultado = {
        "nucleos": nucleos,
        "limpieza_s": round(fin_limpieza - inicio, 2),
        "transformacion_s": round(fin - fin_limpieza, 2),
        "total_s": round(fin - inicio, 2),
        "filas_bronce": crudo.count(),
        "filas_plata": reporte["total_registros"],
        "filas_alertas": alertas.count(),
        "contratos_con_alerta": alertas.filter(F.col("puntaje_riesgo") > 0).count(),
        "tablas_oro": len(tablas),
    }
    spark.stop()
    return resultado


def medir_en_proceso(entrada: Path, nucleos: int, memoria: str) -> dict:
    entorno = {**os.environ, "PYSPARK_PYTHON": sys.executable, "PYSPARK_DRIVER_PYTHON": sys.executable}
    salida = subprocess.run(
        [sys.executable, __file__, "--medir", str(nucleos), "--entrada", str(entrada), "--memoria", memoria],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=entorno,
        timeout=LIMITE_MEDICION_S,
    )
    lineas = [l for l in salida.stdout.splitlines() if l.startswith("{")]
    if not lineas:
        raise SystemExit(f"Falló la medición con {nucleos} núcleos:\n{salida.stderr[-3000:]}")
    return json.loads(lineas[-1])


def ordenes(nucleos: list[int], repeticiones: int) -> list[list[int]]:
    """Ascendente, descendente y alternado, para no favorecer siempre a la misma configuración."""
    base = [nucleos, nucleos[::-1], nucleos[1::2] + nucleos[0::2]]
    return [base[i % len(base)] for i in range(repeticiones)]


def resumir(filas: list[dict]) -> list[dict]:
    mediana = lambda grupo, campo: round(statistics.median(f[campo] for f in grupo), 2)
    resumen = []
    for n in sorted({f["nucleos"] for f in filas}):
        grupo = [f for f in filas if f["nucleos"] == n]
        resumen.append({
            "nucleos": n,
            "limpieza_s": mediana(grupo, "limpieza_s"),
            "transformacion_s": mediana(grupo, "transformacion_s"),
            "mediana_s": mediana(grupo, "total_s"),
            "min_s": min(f["total_s"] for f in grupo),
            "max_s": max(f["total_s"] for f in grupo),
        })
    base = resumen[0]["mediana_s"]
    for fila in resumen:
        p = fila["nucleos"]
        speedup = base / fila["mediana_s"]
        fila["speedup"] = round(speedup, 2)
        fila["eficiencia"] = round(speedup / p, 2)
        fila["karp_flatt"] = round((1 / speedup - 1 / p) / (1 - 1 / p), 2) if p > 1 else ""
    return resumen


def guardar(filas: list[dict], ruta: Path) -> None:
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=list(filas[0]))
        escritor.writeheader()
        escritor.writerows(filas)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mes", default="2026-09", help="mes a procesar, AAAA-MM")
    parser.add_argument("--nucleos", type=int, nargs="+", default=[1, 2, 4, 8])
    parser.add_argument("--repeticiones", type=int, default=3)
    parser.add_argument("--memoria", default="4g", help="memoria de Spark")
    parser.add_argument("--datos", type=Path, default=ROOT / "datos_local")
    parser.add_argument("--out", type=Path, default=ROOT / "resultados_verificacion_local")
    parser.add_argument("--medir", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--entrada", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.medir:
        print(json.dumps(medir(args.entrada, args.medir, args.memoria)), flush=True)
        return 0

    nucleos = sorted(set(args.nucleos))
    if nucleos[0] != 1:
        parser.error("--nucleos debe incluir 1: es la línea base del speedup")
    comprobar_java()

    entrada = args.datos / args.mes
    info = descargar_mes(args.mes, entrada)
    print(f"Datos: {info['registros']} contratos en {info['paginas']} archivos ({entrada})", flush=True)

    filas = []
    for repeticion, orden in enumerate(ordenes(nucleos, args.repeticiones), 1):
        for n in orden:
            fila = {"repeticion": repeticion, **medir_en_proceso(entrada, n, args.memoria)}
            filas.append(fila)
            print(json.dumps(fila), flush=True)
    filas.sort(key=lambda f: (f["nucleos"], f["repeticion"]))

    controles = {(f["filas_bronce"], f["filas_plata"], f["filas_alertas"]) for f in filas}
    guardar(filas, args.out.with_name(args.out.name + ".csv"))
    if len(controles) != 1:
        print(f"Los conteos cambiaron entre ejecuciones: {controles}", file=sys.stderr)
        return 1

    resumen = resumir(filas)
    guardar(resumen, args.out.with_name(args.out.name + "_resumen.csv"))
    print("Conteos iguales en todas las ejecuciones:", controles.pop(), flush=True)
    for fila in resumen:
        print(fila, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
