# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lanza la carga histórica de SECOP II: un tramo por mes + los contratos sin fecha de firma.

Arma la entrada de la máquina de estados `carga_historica` (stepfunctions/carga_historica.asl.json)
y la inicia. El ARN se pasa con --state-machine-arn o con la variable SFN_CARGA_HISTORICA_ARN.

Uso (desde la raíz del proyecto, con credenciales de AWS configuradas):

    # Ver los tramos sin ejecutar nada (también sirve para copiar el JSON y pegarlo
    # en la consola de Step Functions, en "Iniciar ejecución")
    python scripts/backfill.py --dry-run

    # Prueba pequeña primero: un solo mes
    python scripts/backfill.py --start 2026-09 --end 2026-09 --state-machine-arn arn:aws:states:...

    # Todo el histórico (desde junio de 2015 hasta el mes actual)
    python scripts/backfill.py --state-machine-arn arn:aws:states:...
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta

FIRST_MONTH = "2015-06"  # primer contrato con fecha de firma en SECOP II

# Meses con más de 100.000 contratos (consulta a la API, noviembre de 2026). A unos 280 contratos
# por segundo, un mes así se acerca o supera el límite de 15 minutos de la Lambda, así que se
# descargan día por día (el día más grande, 30 de enero de 2026, tiene 43.500: unos 3 minutos).
# Enero de 2026 (487.368, pico antes de la Ley de Garantías) lo exige: solo del 22 al 31 hay ~250.000.
MESES_GRANDES = {"2024-02", "2025-01", "2025-02", "2026-01", "2026-07"}


def parse_month(value: str) -> date:
    year, month = value.split("-")
    return date(int(year), int(month), 1)


def _days(first: date, last: date) -> list[dict]:
    """Un tramo por cada día del mes."""
    return [
        {"start_date": d.isoformat(), "end_date": d.isoformat()}
        for d in (first + timedelta(days=i) for i in range((last - first).days + 1))
    ]


def month_windows(start: date, end: date, dividir: set[str] = frozenset()) -> list[dict]:
    """Un tramo {start_date, end_date} por cada mes entre start y end (inclusive).
    Los meses en `dividir` (formato YYYY-MM) se parten día por día."""
    windows = []
    current = start
    while current <= end:
        next_month = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
        last = next_month - timedelta(days=1)
        if current.strftime("%Y-%m") in dividir:
            windows.extend(_days(current, last))
        else:
            windows.append({"start_date": current.isoformat(), "end_date": last.isoformat()})
        current = next_month
    return windows


def build_input(start: str, end: str, include_missing: bool, dividir: set[str] = MESES_GRANDES) -> dict:
    windows = month_windows(parse_month(start), parse_month(end), dividir)
    if include_missing:
        windows.append({"missing_dates": True})
    return {"windows": windows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", default=FIRST_MONTH, help="Primer mes (YYYY-MM). Por defecto %(default)s.")
    parser.add_argument("--end", default=date.today().strftime("%Y-%m"), help="Último mes (YYYY-MM).")
    parser.add_argument("--no-missing", action="store_true", help="No cargar los contratos sin fecha de firma.")
    parser.add_argument("--state-machine-arn", default=os.environ.get("SFN_CARGA_HISTORICA_ARN"),
                        help="ARN de la máquina de estados de carga histórica.")
    parser.add_argument("--dry-run", action="store_true", help="Solo muestra la entrada; no ejecuta nada.")
    args = parser.parse_args(argv)

    payload = build_input(args.start, args.end, include_missing=not args.no_missing)
    print(f"{len(payload['windows'])} tramos: {payload['windows'][0]} ... {payload['windows'][-1]}")

    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return 0
    if not args.state_machine_arn:
        parser.error("falta --state-machine-arn (o la variable SFN_CARGA_HISTORICA_ARN)")

    import boto3  # solo hace falta para ejecutar de verdad

    response = boto3.client("stepfunctions").start_execution(
        stateMachineArn=args.state_machine_arn, input=json.dumps(payload)
    )
    print(f"Ejecución iniciada: {response['executionArn']}")
    print("Síguela en la consola de AWS > Step Functions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
