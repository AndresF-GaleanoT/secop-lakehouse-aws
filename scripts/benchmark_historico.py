# SPDX-License-Identifier: AGPL-3.0-or-later
"""Speedup y eficiencia de la descarga paralela sobre TODO el histórico (proceso real).

Ejecuta la máquina `secop-solo-bronce` (3 Lambdas en paralelo) varias veces sobre el histórico
completo, una por cada número de hilos por Lambda (1, 2, 4 y 8), una después de otra para que no
compitan por la API. Cada ejecución escribe en su propia carpeta, bronze/_benchmark/hilos-<p>/,
así que no toca los datos reales de bronce.

Para que la versión de 1 hilo quepa en los 15 minutos de la Lambda, los meses con más de
~110.000 contratos se descargan día por día; todas las configuraciones usan los mismos tramos.

Mide, desde el historial de Step Functions:
    T(p)          tiempo de pared de la ejecución completa
    speedup(p)    T(1) / T(p)
    eficiencia(p) speedup(p) / p
y además la suma del tiempo de las Lambdas y los fallos reintentados.

Uso:  python scripts/benchmark_historico.py [--hilos 1 2 4 8] [--out resultados_benchmark_historico.csv]
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from backfill import FIRST_MONTH, MESES_GRANDES, build_input  # noqa: E402

REGION = "us-east-1"
STATE_MACHINE_NAME = "secop-solo-bronce"
# Meses que con 1 hilo superarían ~7 minutos por Lambda (conteo de la API, noviembre de 2026).
MESES_DIVIDIR = set(MESES_GRANDES) | {"2022-01", "2023-01", "2023-02"}


def aws(*args: str) -> dict:
    out = subprocess.run(["aws", *args, "--output", "json"], check=True, capture_output=True, text=True).stdout
    return json.loads(out) if out.strip() else {}


def state_machine_arn() -> str:
    account = aws("sts", "get-caller-identity")["Account"]
    return f"arn:aws:states:{REGION}:{account}:stateMachine:{STATE_MACHINE_NAME}"


def history(arn: str) -> list[dict]:
    events, token = [], None
    while True:
        args = ["stepfunctions", "get-execution-history", "--execution-arn", arn, "--max-results", "1000"]
        if token:
            args += ["--next-token", token]
        page = aws(*args)
        events += page["events"]
        token = page.get("nextToken")
        if not token:
            return events


def run(hilos: int, tramos: list[dict], state_machine: str) -> dict:
    windows = [{**w, "workers": hilos, "bronze_prefix": f"bronze/_benchmark/hilos-{hilos}/secop_contratos"}
               for w in tramos]
    name = f"bench-hilos-{hilos}-{datetime.now():%Y%m%d-%H%M%S}"
    # La entrada (~50 KB) va en un archivo: en Windows no cabe en la línea de comandos.
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump({"windows": windows}, f)
    try:
        arn = aws("stepfunctions", "start-execution", "--state-machine-arn", state_machine,
                  "--name", name, "--input", f"file://{f.name}")["executionArn"]
    finally:
        Path(f.name).unlink(missing_ok=True)
    print(f"[{datetime.now():%H:%M:%S}] {hilos} hilo(s): {name} iniciada", flush=True)
    while True:
        desc = aws("stepfunctions", "describe-execution", "--execution-arn", arn)
        if desc["status"] != "RUNNING":
            break
        time.sleep(60)

    events = history(arn)
    ok = [json.loads(e["taskSucceededEventDetails"]["output"])["Payload"]
          for e in events if e["type"] == "TaskSucceeded"]
    start = datetime.fromisoformat(desc["startDate"])
    stop = datetime.fromisoformat(desc["stopDate"])
    result = {
        "hilos": hilos,
        "estado": desc["status"],
        "tramos_ok": len(ok),
        "tramos_total": len(windows),
        "registros": sum(o["records"] for o in ok),
        "paginas": sum(o["pages"] for o in ok),
        "tiempo_pared_s": round((stop - start).total_seconds(), 1),
        "suma_lambdas_s": round(sum(o["seconds"] for o in ok), 1),
        "tramo_mas_lento_s": max((o["seconds"] for o in ok), default=0),
        "fallos_reintentados": sum(1 for e in events if e["type"] == "TaskFailed"),
        "ejecucion": name,
    }
    print(f"[{datetime.now():%H:%M:%S}] {json.dumps(result)}", flush=True)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hilos", type=int, nargs="+", default=[1, 2, 4, 8])
    parser.add_argument("--out", default=str(ROOT / "resultados_benchmark_historico.csv"))
    args = parser.parse_args(argv)

    tramos = build_input(FIRST_MONTH, date.today().strftime("%Y-%m"), True, MESES_DIVIDIR)["windows"]
    print(f"{len(tramos)} tramos por ejecución; hilos: {args.hilos}", flush=True)

    state_machine = state_machine_arn()
    results = []
    for hilos in args.hilos:
        results.append(run(hilos, tramos, state_machine))
        with open(args.out, "w", newline="", encoding="utf-8") as f:  # se guarda tras cada ejecución
            writer = csv.DictWriter(f, fieldnames=list(results[0]) + ["speedup", "eficiencia"])
            writer.writeheader()
            base = next((r["tiempo_pared_s"] for r in results if r["hilos"] == 1 and r["estado"] == "SUCCEEDED"), None)
            for r in results:
                s = round(base / r["tiempo_pared_s"], 2) if base else ""
                writer.writerow({**r, "speedup": s, "eficiencia": round(s / r["hilos"], 2) if s else ""})
    print(f"Resultados en {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
