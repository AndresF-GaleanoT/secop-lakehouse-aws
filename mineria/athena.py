# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ejecuta consultas en Amazon Athena con el AWS CLI y guarda el resultado en CSV.

El cómputo pesado (recorrer los 5,7 millones de contratos) lo hace Athena en AWS; aquí solo se
descargan agregados o una muestra pequeña. No necesita boto3: usa el AWS CLI ya configurado.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

REGION = "us-east-1"
WORKGROUP = "secop"
DATABASE = "secop_lakehouse_db"


def _aws(*args: str) -> dict:
    out = subprocess.run(
        ["aws", *args, "--region", REGION, "--output", "json"],
        check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(out) if out.strip() else {}


def run_query(sql: str, destino: Path) -> dict:
    """Ejecuta `sql` en el workgroup del proyecto y copia el CSV de resultados a `destino`."""
    qid = _aws(
        "athena", "start-query-execution",
        "--query-string", sql,
        "--work-group", WORKGROUP,
        "--query-execution-context", f"Database={DATABASE}",
    )["QueryExecutionId"]
    while True:
        ex = _aws("athena", "get-query-execution", "--query-execution-id", qid)["QueryExecution"]
        estado = ex["Status"]["State"]
        if estado in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        time.sleep(2)
    if estado != "SUCCEEDED":
        raise RuntimeError(f"Consulta {qid} {estado}: {ex['Status'].get('StateChangeReason')}")
    destino.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["aws", "s3", "cp", ex["ResultConfiguration"]["OutputLocation"], str(destino),
         "--region", REGION, "--only-show-errors"],
        check=True,
    )
    stats = ex["Statistics"]
    return {
        "query_id": qid,
        "bytes_escaneados": stats.get("DataScannedInBytes", 0),
        "ms_motor": stats.get("EngineExecutionTimeInMillis", 0),
    }
