"""Interfaz de línea de comandos de uc-drive-downloader.

Subcomandos disponibles::

    python3 -m uc_drive.cli info <pwd_id>                  # título + stoken
    python3 -m uc_drive.cli list <pwd_id> [--recursive]    # contenido de la share
    python3 -m uc_drive.cli download <pwd_id>              # descarga todo
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
    """Lista el contenido de la share (raíz o recursiva)."""
    client = UcDriveIntlClient()
    try:
        _recursive(client, args.pwd_id, "", depth=1 if args.recursive else 0)
    except ApiError as exc:
        _print_error(f"no se pudo listar: {exc}")
        return 1
    return 0


def _recursive(client: UcDriveIntlClient, pwd_id: str, pdir_fid: str,
               depth: int) -> None:
    """Imprime la jerarquía de carpetas/archivos de la share."""
    _, items = client.list_share(pwd_id, pdir_fid=pdir_fid)
    for item in items:
        is_dir = bool(item.get("dir"))
        name = item.get("file_name", "?")
        if is_dir:
            print(f"{'  ' * depth}[DIR ] {name}  (fid={item.get('fid')})")
            if depth:
                _recursive(client, pwd_id, item.get("fid", ""), depth + 1)
        else:
            size = format_bytes(item.get("size") or 0)
            print(f"{'  ' * depth}[FILE] {name}  ({size})  fid={item.get('fid')}")


def cmd_download(args: argparse.Namespace) -> int:
    """Descarga un archivo (o el primero que coincida con --file)."""
    client = UcDriveIntlClient()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1) Listamos la raíz para encontrar el archivo pedido.
        stoken, items = client.list_share(args.pwd_id, pdir_fid="0")
        target: Optional[dict] = None
        if args.fid:
            for item in items:
                if item.get("fid") == args.fid and not item.get("dir"):
                    target = item
                    break
            if target is None:
                _print_error(f"no se encontró el archivo fid={args.fid}")
                return 1
        elif args.file:
            match = [i for i in items if not i.get("dir") and i.get("file_name") == args.file]
            if not match:
                _print_error(f"no se encontró el archivo '{args.file}' en la raíz")
                return 1
            target = match[0]
        else:
            files = [i for i in items if not i.get("dir")]
            if not files:
                _print_error("la share no expone archivos en su raíz")
                return 1
            target = files[0]
            print(f"→ Sin --file, se descarga el primero: {target.get('file_name')}")

        fid = target["fid"]
        filename = target["file_name"]
        print(f"Descargando: {filename} ({format_bytes(target.get('size') or 0)})")
        print(f"  megafid   : {fid}")

        # 2) Obtenemos la URL directa (firmada, caduca en ~3 h).
        entry = client.get_download_url(fid, args.pwd_id)
        url = entry["download_url"]
        expected_size = entry.get("size")
        expected_md5 = entry.get("md5")

        dest = out_dir / filename
        if dest.exists() and expected_size and dest.stat().st_size >= expected_size:
            print("  Ya existe y parece completo; no se descarga de nuevo.")
            return 0

        # 3) Descarga reanudable con progreso.
        dl = ResumableDownloader(
            url, dest,
            expected_size=expected_size,
            expected_md5_b64=expected_md5,
        )

        def _progress(done: int, total: int, speed: float) -> None:
            pct = (done / total * 100) if total else 0.0
            line = f"  {format_bytes(done)} / {format_bytes(total)} ({pct:.1f}%)  {format_bytes(speed)}/s"
            print(f"\r{line:<60}", end="", flush=True)

        try:
            path = dl.download(progress=_progress if not args.quiet else None)
        except DownloadError as exc:
            print()
            _print_error(f"descarga fallida: {exc}")
            return 1

    except ApiError as exc:
        print()
        _print_error(f"error de API: {exc}")
        return 1

    print()
    print(f"✓ Descargado: {path}")
    if not args.no_verify:
        print("✓ Integridad verificada (tamaño y MD5).")
    return 0


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

    p_dl = sub.add_parser("download", help="Descarga archivos de la share.")
    p_dl.add_argument("pwd_id")
    p_dl.add_argument("--file", help="Nombre exacto del archivo en la raíz.")
    p_dl.add_argument("--fid", help="Fid exacto del archivo en la raíz.")
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