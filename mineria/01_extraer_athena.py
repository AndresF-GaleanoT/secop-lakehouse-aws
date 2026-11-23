# SPDX-License-Identifier: AGPL-3.0-or-later
"""Paso 1: ejecuta las consultas de mineria/sql/ en Athena y guarda los CSV en mineria/datos/.

Uso:  python mineria/01_extraer_athena.py            (todas las consultas)
      python mineria/01_extraer_athena.py 07 08      (solo esas)

Requiere el AWS CLI configurado con acceso al workgroup `secop`. Todo el recorrido de los 5,7 millones
de contratos ocurre en Athena; aquí llegan agregados y una muestra de ~50 mil filas.
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

from athena import run_query

BASE = Path(__file__).resolve().parent
SQL_DIR, DATOS = BASE / "sql", BASE / "datos"


def main(filtros: list[str]) -> None:
    bitacora = DATOS / "bitacora_consultas.csv"
    nuevo = not bitacora.exists()
    DATOS.mkdir(exist_ok=True)
    with bitacora.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if nuevo:
            w.writerow(["fecha_utc", "consulta", "query_id", "mb_escaneados", "segundos_motor", "filas"])
        for sql_file in sorted(SQL_DIR.glob("*.sql")):
            if filtros and not any(sql_file.name.startswith(p) for p in filtros):
                continue
            destino = DATOS / f"{sql_file.stem}.csv"
            info = run_query(sql_file.read_text(encoding="utf-8"), destino)
            filas = sum(1 for _ in destino.open(encoding="utf-8")) - 1
            mb = info["bytes_escaneados"] / 1e6
            print(f"{sql_file.stem:32s} {filas:>8d} filas  {mb:8.1f} MB  {info['ms_motor']/1000:6.1f} s")
            w.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"), sql_file.stem,
                        info["query_id"], f"{mb:.1f}", f"{info['ms_motor']/1000:.1f}", filas])


if __name__ == "__main__":
    main(sys.argv[1:])
