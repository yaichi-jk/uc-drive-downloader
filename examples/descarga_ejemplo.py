"""Ejemplo completo de uso de uc-drive-downloader como librería.

Ejecuta::

    python3 examples/descarga_ejemplo.py <pwd_id> [--file NOMBRE] [--out DIR]

Descarga el primer archivo (o el indicado con --file) de la share y verifica
la integridad automáticamente.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from uc_drive import UcDriveIntlClient, ResumableDownloader


def encontrar_archivo(client: UcDriveIntlClient, pwd_id: str, nombre: Optional[str]):
    """Devuelve la entrada del archivo objetivo de la raíz de la share."""
    _, items = client.list_share(pwd_id, pdir_fid="0")
    archivos = [i for i in items if not i.get("dir")]
    if nombre:
        objetivo = next((i for i in archivos if i.get("file_name") == nombre), None)
        if objetivo is None:
            raise SystemExit(f"archivo '{nombre}' no encontrado en la raíz")
        return objetivo
    if not archivos:
        raise SystemExit("la share no expone archivos en su raíz")
    return archivos[0]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pwd_id", help="id corto de la share (ej. e8ccf39f80024)")
    parser.add_argument("--file", help="nombre exacto del archivo a descargar")
    parser.add_argument("--out", default="./descargas", help="carpeta de destino")
    args = parser.parse_args(argv)

    client = UcDriveIntlClient()

    # 1) stoken
    client.get_share_token(args.pwd_id)
    print(f"stoken obtenido para share {args.pwd_id}")

    # 2) archivo objetivo
    archivo = encontrar_archivo(client, args.pwd_id, args.file)
    print(f"objetivo: {archivo['file_name']} ({archivo.get('size')} bytes)")

    # 3) URL directa firmada
    entry = client.get_download_url(archivo["fid"], args.pwd_id)
    print("download_url obtenida:", entry["download_url"][:72], "…")

    # 4) descarga reanudable + verificación
    dest = Path(args.out) / entry["file_name"]
    destino = ResumableDownloader(
        entry["download_url"],
        dest,
        expected_size=entry.get("size"),
        expected_md5_b64=entry.get("md5"),
    ).download()

    print(f"\n✓ descarga completa en: {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())