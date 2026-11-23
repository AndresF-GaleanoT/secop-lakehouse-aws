# SPDX-License-Identifier: AGPL-3.0-or-later
"""Une las series de benchmark_spark.py y calcula mediana, speedup, eficiencia y Karp-Flatt.

Genera <out>.csv con todas las ejecuciones y <out>_resumen.csv con una fila por número de workers.
La línea base es la mediana con 2 workers, es decir, un ejecutor.

Uso:  python scripts/agrega_spark.py serie1.csv serie2.csv serie3.csv --out resultados_benchmark_spark
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys


def leer(series: list[str]) -> list[dict]:
    rows = []
    for repeticion, path in enumerate(series, 1):
        with open(path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                row.pop("speedup", None)
                row.pop("eficiencia", None)
                rows.append({"repeticion": repeticion, **row})
    rows.sort(key=lambda r: (int(r["workers"]), r["repeticion"]))
    return rows


def resumir(rows: list[dict]) -> list[dict]:
    resumen = []
    for workers in sorted({int(r["workers"]) for r in rows}):
        grupo = [r for r in rows if int(r["workers"]) == workers]
        tiempos = [int(r["tiempo_s"]) for r in grupo]
        fila = {"workers": workers, "ejecutores": workers - 1}
        fila.update({f"t{i}": t for i, t in enumerate(tiempos, 1)})
        fila.update({
            "mediana_s": statistics.median(tiempos),
            "min_s": min(tiempos),
            "max_s": max(tiempos),
            "dpu_s_mediana": statistics.median(float(r["dpu_s"]) for r in grupo),
        })
        resumen.append(fila)

    base = resumen[0]["mediana_s"]
    for fila in resumen:
        p = fila["ejecutores"]
        speedup = base / fila["mediana_s"]
        fila["speedup"] = round(speedup, 2)
        fila["eficiencia"] = round(speedup / p, 2)
        fila["karp_flatt"] = round((1 / speedup - 1 / p) / (1 - 1 / p), 2) if p > 1 else ""
    return resumen


def escribir(rows: list[dict], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("series", nargs="+")
    parser.add_argument("--out", default="resultados_benchmark_spark")
    args = parser.parse_args(argv)

    rows = leer(args.series)
    fallidas = [r["ejecucion"] for r in rows if r["estado"] != "SUCCEEDED"]
    if fallidas:
        print(f"Hay ejecuciones fallidas: {fallidas}", file=sys.stderr)
        return 1
    resumen = resumir(rows)
    escribir(rows, f"{args.out}.csv")
    escribir(resumen, f"{args.out}_resumen.csv")
    for fila in resumen:
        print(fila)
    return 0


if __name__ == "__main__":
    sys.exit(main())
