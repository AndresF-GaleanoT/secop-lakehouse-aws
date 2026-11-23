# SPDX-License-Identifier: AGPL-3.0-or-later
"""Mide el speedup y la eficiencia de la descarga paralela (computación paralela).

Invoca la Lambda `secop-ingest` en AWS sobre el MISMO tramo de datos con 1, 2, 4 y 8 hilos y
calcula, con el tiempo que reporta la propia Lambda (sin contar la red de tu PC):

    speedup(n)    = T(1) / T(n)
    eficiencia(n) = speedup(n) / n

La descarga se hace en AWS, no en tu PC: este script solo envía las órdenes y recoge los tiempos.
Los archivos del benchmark se guardan aparte, en bronze/_benchmark/, para no mezclarse con los datos.

Requisitos: AWS CLI configurada (sirve tu PC o AWS CloudShell) y la Lambda con al menos 2048 MB
de memoria (8 hilos tienen hasta 8 páginas en memoria a la vez).

Uso:
    python scripts/benchmark_descarga.py                                   # septiembre 2026, 2 repeticiones
    python scripts/benchmark_descarga.py --start 2026-08-01 --end 2026-08-31 --workers 1 2 4 8 16 --reps 3
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def invoke(function: str, payload: dict) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.json"
        cmd = [
            "aws", "lambda", "invoke",
            "--function-name", function,
            "--cli-binary-format", "raw-in-base64-out",
            "--cli-read-timeout", "900",
            "--payload", json.dumps(payload),
            str(out),
        ]
        meta = json.loads(subprocess.run(cmd, check=True, capture_output=True, text=True).stdout)
        result = json.loads(out.read_text(encoding="utf-8"))
        if meta.get("FunctionError"):
            raise RuntimeError(f"La Lambda falló: {result}")
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--function", default="secop-ingest")
    parser.add_argument("--start", default="2026-09-01")
    parser.add_argument("--end", default="2026-09-30")
    parser.add_argument("--workers", type=int, nargs="+", default=[1, 2, 4, 8])
    parser.add_argument("--reps", type=int, default=2, help="Repeticiones por configuración (se usa la mediana).")
    parser.add_argument("--out", default=str(ROOT / "resultados_benchmark_descarga.csv"))
    args = parser.parse_args(argv)

    workers = sorted(set(args.workers))
    if workers[0] != 1:
        workers = [1, *workers]  # T(1) es la base del speedup

    print(f"Tramo {args.start} a {args.end} · hilos {workers} · {args.reps} repeticiones\n")
    rows = []
    for w in workers:
        times, records = [], None
        for rep in range(1, args.reps + 1):
            r = invoke(args.function, {
                "start_date": args.start, "end_date": args.end, "workers": w,
                "bronze_prefix": f"bronze/_benchmark/w{w}",
            })
            times.append(r["seconds"])
            records = r["records"]
            print(f"  hilos={w:2d} rep={rep}: {r['seconds']:7.2f} s · {r['records']} registros · {r['pages']} páginas")
        rows.append({"hilos": w, "registros": records, "tiempo_s": round(statistics.median(times), 2)})

    t1 = rows[0]["tiempo_s"]
    for row in rows:
        row["speedup"] = round(t1 / row["tiempo_s"], 2)
        row["eficiencia"] = round(row["speedup"] / row["hilos"], 2)

    print("\n| Hilos | Registros | Tiempo (s) | Speedup | Eficiencia |")
    print("|---|---|---|---|---|")
    for row in rows:
        print(f"| {row['hilos']} | {row['registros']} | {row['tiempo_s']} | {row['speedup']} | {row['eficiencia']} |")

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nResultados guardados en {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
