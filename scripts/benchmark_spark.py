# SPDX-License-Identifier: AGPL-3.0-or-later
"""Speedup y eficiencia de Spark en AWS Glue sobre todo el histórico (experimento B).

Ejecuta el trabajo `secop-silver-to-gold` varias veces, una después de otra, en modo Standard y
con distinto número de workers G.1X. En Glue un worker es el driver, así que n workers son n-1
ejecutores:

    speedup(n)    = T(2) / T(n)
    eficiencia(n) = speedup(n) / (n - 1)

T(n) es la duración de ejecución que registra Glue, sin la espera de arranque. El trabajo reconstruye
oro desde plata con reemplazo atómico; el script cuenta las filas con Athena antes y después de cada
ejecución para comprobar que los datos de entrada y de salida no cambiaron.

Cada llamada es una serie. Para repetir el experimento se lanzan varias series con otro orden de
workers y otro archivo de salida, y se compara la mediana de los tiempos.

Uso:  python scripts/benchmark_spark.py [--workers 2 4 8 10] [--out resultados_benchmark_spark.csv]
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JOB = "secop-silver-to-gold"
DATABASE = "secop_lakehouse_db"
WORKGROUP = "secop"
USD_DPU_HORA_STANDARD = 0.44


def aws(*args: str) -> dict:
    out = subprocess.run(["aws", *args, "--output", "json"], check=True, capture_output=True, text=True).stdout
    return json.loads(out) if out.strip() else {}


def contar(tabla: str) -> int:
    query = aws("athena", "start-query-execution", "--work-group", WORKGROUP,
                "--query-execution-context", f"Database={DATABASE}",
                "--query-string", f"SELECT count(*) FROM {tabla}")["QueryExecutionId"]
    while True:
        status = aws("athena", "get-query-execution", "--query-execution-id", query)["QueryExecution"]["Status"]
        if status["State"] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            break
        time.sleep(2)
    if status["State"] != "SUCCEEDED":
        raise RuntimeError(f"Athena no pudo contar {tabla}: {status}")
    rows = aws("athena", "get-query-results", "--query-execution-id", query)["ResultSet"]["Rows"]
    return int(rows[1]["Data"][0]["VarCharValue"])


def run(workers: int) -> dict:
    plata_antes = contar("silver_contratos")
    run_id = aws("glue", "start-job-run", "--job-name", JOB, "--execution-class", "STANDARD",
                 "--worker-type", "G.1X", "--number-of-workers", str(workers))["JobRunId"]
    print(f"[{datetime.now():%H:%M:%S}] {workers} workers: {run_id} iniciada", flush=True)
    while True:
        job = aws("glue", "get-job-run", "--job-name", JOB, "--run-id", run_id)["JobRun"]
        if job["JobRunState"] not in {"STARTING", "RUNNING", "STOPPING", "WAITING"}:
            break
        time.sleep(30)

    time.sleep(30)  # Glue publica DPUSeconds poco después de terminar
    job = aws("glue", "get-job-run", "--job-name", JOB, "--run-id", run_id)["JobRun"]
    dpu_s = job.get("DPUSeconds") or job.get("ExecutionTime", 0) * workers
    result = {
        "workers": workers,
        "ejecutores": workers - 1,
        "estado": job["JobRunState"],
        "modo": job.get("ExecutionClass", ""),
        "tiempo_s": job.get("ExecutionTime", 0),
        "dpu_s": dpu_s,
        "costo_usd": round(dpu_s / 3600 * USD_DPU_HORA_STANDARD, 3),
        "filas_plata_antes": plata_antes,
        "filas_plata_despues": contar("silver_contratos"),
        "filas_alertas": contar("gold_alertas_contratos"),
        "ejecucion": run_id,
        "error": job.get("ErrorMessage", ""),
    }
    print(f"[{datetime.now():%H:%M:%S}] {json.dumps(result)}", flush=True)
    return result


def guardar(results: list[dict], path: str) -> None:
    base = next((r["tiempo_s"] for r in results if r["workers"] == 2 and r["estado"] == "SUCCEEDED"), None)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0]) + ["speedup", "eficiencia"])
        writer.writeheader()
        for r in results:
            ok = base and r["estado"] == "SUCCEEDED" and r["tiempo_s"]
            s = round(base / r["tiempo_s"], 2) if ok else ""
            writer.writerow({**r, "speedup": s, "eficiencia": round(s / r["ejecutores"], 2) if ok else ""})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workers", type=int, nargs="+", default=[2, 4, 8, 10])
    parser.add_argument("--out", default=str(ROOT / "resultados_benchmark_spark.csv"))
    args = parser.parse_args(argv)

    results = []
    for workers in args.workers:
        results.append(run(workers))
        guardar(results, args.out)  # se guarda tras cada ejecución
        if results[-1]["estado"] != "SUCCEEDED":
            print("Ejecución fallida: se detiene el experimento.", flush=True)
            return 1
    print(f"Resultados en {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
