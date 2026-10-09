"""Interfaz de línea de comandos de uc-drive-downloader.

Subcomandos disponibles::

    python3 -m uc_drive.cli info <pwd_id>                  # título + stoken
    python3 -m uc_drive.cli list <pwd_id> [--recursive]    # contenido de la share
    python3 -m uc_drive.cli download <pwd_id>              # descarga todo (recursivo)
        [--file <nombre>]  [--fid <id>]  [--out DIR]  [--no-verify]

Ejemplos::

    python3 -m uc_drive.cli info e8ccf39f80024
    python3 -m uc_drive.cli list e8ccf39f80024 --recursive
    python3 -m uc_drive.cli download e8ccf39f80024 --file "mi_video.mp4" --out ./descargas
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from uc_drive.api import ApiError, UcDriveIntlClient
from uc_drive.downloader import DownloadError, ResumableDownloader, format_bytes


def _print_error(msg: str) -> None:
    print(f"\n✗ {msg}", file=sys.stderr)


def cmd_info(args: argparse.Namespace) -> int:
    """Muestra el título y un stoken fresco de la share."""
    client = UcDriveIntlClient()
    try:
        stoken = client.get_share_token(args.pwd_id)
        _, items = client.list_share(args.pwd_id, pdir_fid="0")
        title = (items[0] if items else {}).get("file_name", "(sin título)")
    except ApiError as exc:
        _print_error(f"no se pudo resolver la share: {exc}")
        return 1
    print(f"Share:   {args.pwd_id}")
    print(f"Título:  {title}")
    print(f"Stoken:  {stoken}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """Lista el contenido de la share (raíz o recursivo)."""
    client = UcDriveIntlClient()
    try:
        if args.recursive:
            for ruta, item in client.walk_share(args.pwd_id):
                _imprimir_item(ruta, item)
        else:
            _, items = client.list_share(args.pwd_id, pdir_fid="0")
            for item in items:
                nombre = item.get("file_name", "?")
                if item.get("dir"):
                    print(f"[DIR ] {nombre}  (fid={item.get('fid')})")
                else:
                    print(f"[FILE] {nombre}  ({format_bytes(item.get('size') or 0)})  fid={item.get('fid')}")
    except ApiError as exc:
        _print_error(f"no se pudo listar: {exc}")
        return 1
    return 0


def _imprimir_item(ruta: str, item: dict) -> None:
    """Imprime una línea para un archivo devuelto por walk_share."""
    if item.get("dir"):
        return
    nombre = item.get("file_name", "?")
    print(f"[FILE] {ruta}  ({format_bytes(item.get('size') or 0)})  fid={item.get('fid')}")


def cmd_download(args: argparse.Namespace) -> int:
    """Descarga los archivos de la share (recursivo, reanudable)."""
    client = UcDriveIntlClient()
    out_dir = Path(args.out)

    try:
        # 1) Recorremos la share para elegir el objetivo.
        objetivos: List = []
        if args.fid:
            for ruta, item in client.walk_share(args.pwd_id):
                if item.get("fid") == args.fid:
                    objetivos = [(ruta, item)]
                    break
            if not objetivos:
                _print_error(f"no se encontró el archivo fid={args.fid}")
                return 1
        elif args.file:
            objetivos = [(r, i) for r, i in client.walk_share(args.pwd_id)
                         if i.get("file_name") == args.file]
            if not objetivos:
                _print_error(f"no se encontró el archivo '{args.file}'")
                return 1
        else:
            objetivos = list(client.walk_share(args.pwd_id))
            if not objetivos:
                _print_error("la share no expone archivos")
                return 1

        # 2) Descargamos cada archivo objetivo.
        for ruta, item in objetivos:
            _descargar_uno(client, args, out_dir / ruta, item)

    except ApiError as exc:
        _print_error(f"error de API: {exc}")
        return 1
    return 0


def _descargar_uno(client: UcDriveIntlClient, args: argparse.Namespace,
                   dest: Path, item: dict) -> None:
    """Descarga un archivo concreto mostrando progreso y verificando (opcional)."""
    fid = item["fid"]
    print(f"\n→ {item.get('file_name')}  ({format_bytes(item.get('size') or 0)})")

    entry = client.get_download_url(fid, args.pwd_id)
    url = entry["download_url"]
    expected_size = entry.get("size")
    expected_md5 = entry.get("md5")

    if dest.exists() and expected_size and dest.stat().st_size >= expected_size:
        print("  ya existe y parece completo; se omite.")
        return

    dl = ResumableDownloader(
        url, dest,
        expected_size=expected_size,
        expected_md5_b64=None if args.no_verify else expected_md5,
    )

    def _progress(done: int, total: int, speed: float) -> None:
        pct = (done / total * 100) if total else 0.0
        line = f"  {format_bytes(done)} / {format_bytes(total)} ({pct:.1f}%)  {format_bytes(speed)}/s"
        print(f"\r{line:<60}", end="", flush=True)

    try:
        final = dl.download(progress=_progress if not args.quiet else None)
    except DownloadError as exc:
        print()
        _print_error(f"descarga fallida: {exc}")
        return
    print()
    print(f"  ✓ {final}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uc-drive-downloader",
        description="Descarga archivos de shares públicas de UC Drive (internacional), sin cuenta.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_info = sub.add_parser("info", help="Muestra título y stoken de la share.")
    p_info.add_argument("pwd_id", help="Identificador corto de la share.")
    p_info.set_defaults(func=cmd_info)

    p_list = sub.add_parser("list", help="Lista el contenido de la share.")
    p_list.add_argument("pwd_id")
    p_list.add_argument("--recursive", action="store_true", help="Recorre subcarpetas.")
    p_list.set_defaults(func=cmd_list)

    p_dl = sub.add_parser("download", help="Descarga archivos de la share (recursivo).")
    p_dl.add_argument("pwd_id")
    p_dl.add_argument("--file", help="Descargar solo el archivo con este nombre.")
    p_dl.add_argument("--fid", help="Descargar solo el archivo con este fid.")
    p_dl.add_argument("--out", default="./descargas", help="Carpeta de destino.")
    p_dl.add_argument("--no-verify", action="store_true", help="No verificar tamaño/MD5.")
    p_dl.add_argument("--quiet", action="store_true", help="Sin barra de progreso.")
    p_dl.set_defaults(func=cmd_download)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())