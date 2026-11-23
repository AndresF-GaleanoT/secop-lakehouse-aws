# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sube los archivos de la web (carpeta web/) al bucket que sirve CloudFront.

No toca web/data/: esos JSON los escribe cada día la Lambda secop-web-export al final del pipeline.
Cada archivo va con su tipo y charset, y con caché corta para que un cambio se vea en minutos.

Uso:
    python scripts/publicar_web.py                      # bucket por defecto
    python scripts/publicar_web.py --bucket otro-bucket --invalidar EXY065CPYI3J
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import boto3

RAIZ = Path(__file__).resolve().parent.parent / "web"
BUCKET = "secop-web-811136731365"
TIPOS = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
}
CACHE = "public, max-age=300"  # 5 minutos en CloudFront y en el navegador


def publicar(bucket: str) -> list[str]:
    s3 = boto3.client("s3")
    subidos = []
    for archivo in sorted(RAIZ.rglob("*")):
        relativo = archivo.relative_to(RAIZ).as_posix()
        if archivo.is_dir() or relativo.startswith("data/") or archivo.suffix not in TIPOS:
            continue
        s3.upload_file(
            str(archivo),
            bucket,
            relativo,
            ExtraArgs={"ContentType": TIPOS[archivo.suffix], "CacheControl": CACHE},
        )
        subidos.append(relativo)
        print(f"  {relativo}")
    return subidos


def invalidar(distribucion: str) -> str:
    """Opcional: borra la caché de CloudFront de inmediato (las primeras 1.000 rutas al mes son gratis)."""
    cf = boto3.client("cloudfront")
    respuesta = cf.create_invalidation(
        DistributionId=distribucion,
        InvalidationBatch={
            "Paths": {"Quantity": 1, "Items": ["/*"]},
            # Debe ser única en cada llamada: si se repite, CloudFront devuelve la invalidación anterior.
            "CallerReference": f"publicar-web-{time.time_ns()}",
        },
    )
    return respuesta["Invalidation"]["Id"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bucket", default=BUCKET)
    parser.add_argument("--invalidar", metavar="ID_DISTRIBUCION", help="invalida la caché de CloudFront al terminar")
    args = parser.parse_args()
    print(f"Subiendo web/ a s3://{args.bucket}/")
    publicar(args.bucket)
    if args.invalidar:
        print(f"Invalidación creada: {invalidar(args.invalidar)}")
