"""CLI avanzada de uc-drive-downloader.

Subcomandos
-----------
``info``     Detalle corto de la share (título, tamaño, stoken).

``list``     Lista el contenido; con ``--recursive`` recorre subcarpetas.

``view``     Detalle de un elemento (archivo o carpeta), con ``--url`` añade
             la URL directa + MD5 del archivo.

``raw``      Salida "avanzada" en JSON para scripts; con ``--field`` imprime
             solo un campo (ej. la URL) y con ``--url`` resuelve el enlace.

``download`` Descarga real (recursiva, reanudable). Muestra fases endpoint →
             conexión → descarga (con %, velocidad, ETA) → verificación MD5.

``test``     Diagnóstico de conexión (DNS, latencia, servidor).

Cualquier comando acepta el ``id`` corto o una URL completa::

    python3 -m uc_drive.cli info https://uc-share.com/s/577cf9ba429a4?la=es-la

Opciones globales: ``--verbose`` (log interno de cada petición en stderr),
``--no-color`` y ``--version``.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

from uc_drive.api import CLOUD_DRIVE_URL, ApiError, UcDriveIntlClient, USER_AGENT
from uc_drive.downloader import DownloadError, ResumableDownloader
from uc_drive.errors import describe
from uc_drive.ui import Renderer
from uc_drive.util import (
    TIPOS,
    TIPO_NOMBRE,
    format_bytes,
    format_epoch_ms,
    human_time,
    normalize_share_ref,
    tipo_de,
    tipo_legible,
)

__version__ = "1.1.0"

TIPO_CHOICES = sorted(set(TIPOS) | {"all"})


# ---------------------------------------------------------------------------
# Helpers comunes
# ---------------------------------------------------------------------------
def _cliente(args: argparse.Namespace) -> UcDriveIntlClient:
    return UcDriveIntlClient(verbose=getattr(args, "verbose", False))


def _pwd(args: argparse.Namespace) -> Optional[str]:
    try:
        pwd = normalize_share_ref(args.ref)
    except ValueError as exc:
        print(f"✗ {exc}")
        return None
    args.pwd_id = pwd
    return pwd


def _reportar(r: Renderer, exc: Exception) -> None:
    """Imprime un error tipificado de forma clara y accionable."""
    if isinstance(exc, (ApiError, DownloadError)):
        print(r.fail(exc.message))
        print(r.DIM("  ↳ " + describe(exc.kind, exc.code)))
    else:
        print(r.fail(str(exc)))


def _banner(r: Renderer) -> str:
    return r.panel("uc-drive-downloader  " + __version__, [
        r.DIM("Descarga shares públicas de UC Drive (internacional), sin cuenta"),
    ])


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------
def cmd_info(args: argparse.Namespace, r: Renderer) -> int:
    pwd = _pwd(args)
    if not pwd:
        return 1
    client = _cliente(args)
    try:
        client.get_share_token(pwd)
        _, items = client.list_share(pwd, pdir_fid="0")
        título = (items[0] if items else {}).get("file_name", "(sin título)")
        total = sum((i.get("size") or 0) for i in items if not i.get("dir"))
    except ApiError as exc:
        _reportar(r, exc)
        return 1

    print(_banner(r))
    print()
    print(r.panel("Información de la share", [
        f"Share   : {pwd}",
        f"Título  : {título}",
        f"Raíz    : {len(items)} elemento(s) · {format_bytes(total)}",
        f"Stoken  : {r.DIM(client.stoken or '-')}",
    ]))
    print()
    print(r.hint("explora:") + f" list <id> --recursive    "
          + r.hint("detalle:") + f" view <id>    "
          + r.hint("descarga:") + f" download <id> --all")
    return 0


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------
def cmd_list(args: argparse.Namespace, r: Renderer) -> int:
    pwd = _pwd(args)
    if not pwd:
        return 1
    client = _cliente(args)
    try:
        if args.recursive:
            archivos = list(client.walk_share(pwd))
            filas = [_fila_archivo(r, ruta.replace("/", "  »  "), it)
                     for ruta, it in archivos]
            título = f"Contenido ({len(archivos)} archivo(s))"
        else:
            fid = args.fid or "0"
            _, items = client.list_share(pwd, pdir_fid=fid)
            filas = [_fila_raiz(r, it) for it in items]
            título = f"Raíz ({len(items)} elemento(s))" if fid == "0" \
                else f"Carpeta {fid[:12]}… ({len(items)} elemento(s))"
    except ApiError as exc:
        _reportar(r, exc)
        return 1

    print(_banner(r))
    print()
    print(r.panel(título, filas))
    print()
    print(r.hint("detalle:") + f" view {pwd} --fid <id>    "
          + r.hint("descargar todo:") + f" download {pwd} --all")
    return 0


def _fila_raiz(r: Renderer, item: dict) -> str:
    nombre = item.get("file_name", "?")
    return f"{r.tipo_badge(item):<12}  {nombre}  {r.file_dim(item)}"


def _fila_archivo(r: Renderer, ruta: str, item: dict) -> str:
    badge = r.tipo_badge(item)
    return f"{badge:<12}  {ruta}  {r.file_dim(item)}"


# ---------------------------------------------------------------------------
# view (detalle)
# ---------------------------------------------------------------------------
def cmd_view(args: argparse.Namespace, r: Renderer) -> int:
    pwd = _pwd(args)
    if not pwd:
        return 1
    client = _cliente(args)
    try:
        client.get_share_token(pwd)
        if args.fid or args.file:
            objetivo = _buscar(r, client, args)
            if objetivo is None:
                r.fail("no se encontró el elemento pedido")
                return 1
            ruta, item = objetivo
            filas = _detalle_item(r, client, args, pwd, ruta, item)
            print(_banner(r))
            print()
            print(r.panel("Detalle del elemento", filas))
            return 0

        # Sin --fid/--file: resumen de la share + listado de la raíz.
        _, items = client.list_share(pwd, pdir_fid="0")
        total = sum((i.get("size") or 0) for i in items if not i.get("dir"))
        título = (items[0] if items else {}).get("file_name", "(sin título)")
        filas = [f"Share : {pwd}", f"Título: {título}",
                 f"Raíz  : {len(items)} elemento(s) · {format_bytes(total)}"]
        filas += ["", *[_fila_raiz(r, it) for it in items]]
        print(_banner(r))
        print()
        print(r.panel("Vista de la share", filas))
        print()
        print(r.hint("detalle de un archivo:") + f" view {pwd} --fid <id> --url")
        return 0
    except ApiError as exc:
        _reportar(r, exc)
        return 1


def _detalle_item(r: Renderer, client, args, pwd: str, ruta: str, item: dict) -> List[str]:
    """Columnas de detalle de un elemento (archivo o carpeta)."""
    es_dir = bool(item.get("dir"))
    filas = [
        f"Tipo       : {r.tipo_badge(item)}",
        f"Nombre     : {item.get('file_name', '?')}",
        f"Ruta       : {ruta}",
        f"Fid        : {item.get('fid')}",
    ]
    if es_dir:
        filas.append(f"Elementos  : {item.get('include_items', 0) or 0} en total")
    else:
        filas += [
            f"Tamaño     : {format_bytes(item.get('size') or 0)} ({item.get('size')} B)",
            f"Tipo MIME  : {item.get('format_type') or '—'}",
            f"Categoría  : {item.get('category', 0)} · file_type={item.get('file_type', 0)}",
        ]
        if item.get("duration"):
            filas.append(f"Duración   : {item.get('duration')} s")
        if item.get("video_width"):
            filas.append(f"Resolución : {item.get('video_width')}x{item.get('video_height')}")
    filas += [
        f"Creado     : {format_epoch_ms(item.get('created_at') or 0)}",
        f"Modificado : {format_epoch_ms(item.get('updated_at') or 0)}",
    ]
    if args.url and not es_dir:
        try:
            entry = client.get_download_url(item["fid"], pwd)
        except ApiError as exc:
            filas.append(f"URL        : {r.R('no se pudo resolver: ' + exc.message)}")
            return filas
        filas += [
            f"URL directa: {r.C(entry.get('download_url', ''))}",
            f"  caduca   : {r.DIM('~3 h (firmada OSS)')}",
            f"MD5 (b64)  : {entry.get('md5', '—')}",
        ]
    return filas


def _buscar(r: Renderer, client: UcDriveIntlClient,
            args: argparse.Namespace) -> Optional[Tuple[str, dict]]:
    """Busca un elemento por fid o nombre dentro del árbol de la share."""
    for ruta, it in _walk_items(client, args.pwd_id):
        if args.fid and it.get("fid") == args.fid:
            return ruta, it
        if args.file and it.get("file_name") == args.file:
            return ruta, it
    return None


def _walk_items(client, pwd_id, pdir_fid="0", pila=()):
    """Recorre share incluyendo carpetas (para view/raw)."""
    _, items = client.list_share(pwd_id, pdir_fid=pdir_fid)
    for it in items:
        ruta = "/".join(pila + (it.get("file_name", ""),))
        yield ruta, it
        if it.get("dir"):
            yield from _walk_items(client, pwd_id, it.get("fid", ""),
                                   pila + (it.get("file_name", ""),))


# ---------------------------------------------------------------------------
# raw (salida avanzada JSON)
# ---------------------------------------------------------------------------
def cmd_raw(args: argparse.Namespace, r: Renderer) -> int:
    pwd = _pwd(args)
    if not pwd:
        return 1
    client = _cliente(args)
    try:
        client.get_share_token(pwd)
        _, raiz = client.list_share(pwd, pdir_fid="0")
        título = (raiz[0] if raiz else {}).get("file_name", "")

        if args.url or args.field:
            if not (args.fid or args.file):
                r.fail("--url y --field requieren --fid o --file (un solo archivo)")
                return 1
            objetivo = _buscar(r, client, args)
            if objetivo is None or objetivo[1].get("dir"):
                r.fail("no se encontró el archivo pedido")
                return 1
            ruta, item = objetivo
            entry = client.get_download_url(item["fid"], pwd)
            values = {
                "fid": item.get("fid"),
                "name": item.get("file_name"),
                "path": ruta,
                "size": entry.get("size") or item.get("size"),
                "size_h": format_bytes(entry.get("size") or item.get("size") or 0),
                "type": tipo_legible(item),
                "format_type": entry.get("format_type") or item.get("format_type"),
                "md5": entry.get("md5"),
                "url": entry.get("download_url"),
            }
            if args.field in values:
                print(values.get(args.field) or "—")
                return 0
            print(json.dumps(values, ensure_ascii=False, indent=2))
            return 0

        # JSON del árbol completo de la share.
        items = []
        total = 0
        for ruta, it in _walk_items(client, pwd):
            es_dir = bool(it.get("dir"))
            if not es_dir:
                total += it.get("size") or 0
            items.append({
                "fid": it.get("fid"),
                "name": it.get("file_name"),
                "path": ruta,
                "dir": es_dir,
                "size": it.get("size") if not es_dir else None,
                "size_h": format_bytes(it.get("size") or 0) if not es_dir else None,
                "type": tipo_legible(it) if not es_dir else None,
                "format_type": it.get("format_type"),
                "category": it.get("category"),
            })
        salida = {
            "script": "uc-drive-downloader",
            "version": __version__,
            "pwd_id": pwd,
            "title": título,
            "stoken": client.stoken,
            "count": len(items),
            "size": total,
            "size_h": format_bytes(total),
            "items": items,
        }
        print(json.dumps(salida, ensure_ascii=False, indent=2))
        return 0
    except ApiError as exc:
        _reportar(r, exc)
        return 1


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------
def cmd_download(args: argparse.Namespace, r: Renderer) -> int:
    pwd = _pwd(args)
    if not pwd:
        return 1
    client = _cliente(args)
    out_dir = Path(args.out)
    t0 = time.time()

    try:
        client.get_share_token(pwd)
        _, raiz = client.list_share(pwd, pdir_fid="0")
        título = (raiz[0] if raiz else {}).get("file_name", "")

        archivos = [(ruta, it) for ruta, it in client.walk_share(pwd)
                    if _pasa_filtro(it, args.type)]
        if not archivos:
            r.fail("no hay archivos que cumplan los criterios")
            return 1

        elegidos = _elegir(r, archivos, args)
        if elegidos is None:
            r.fail("no se encontró el archivo pedido (--file/--fid)")
            return 1
        if not elegidos:
            return 0  # menú cancelado

        total_bytes = sum(it.get("size") or 0 for _, it in elegidos)
        filas = [
            f"Share    : {pwd}",
            f"Título   : {título or '(sin título)'}",
            f"Archivos : {len(elegidos):d} de {len(archivos):d} · {format_bytes(total_bytes)}",
        ]
        if args.type:
            filas.append(f"Filtro   : {', '.join(args.type)}")
        filas.append(f"Destino  : {out_dir}")
        print(_banner(r))
        print()
        print(r.panel("Destino de descarga", filas))
        print()

        for n, (ruta, item) in enumerate(elegidos, 1):
            _descargar_uno(r, client, args, out_dir / ruta, item, n, len(elegidos))

        dur = time.time() - t0
        media = (total_bytes / dur / 1e6) if dur else 0.0
        print()
        print(r.panel("RESUMEN FINAL", [
            f"Archivos    : {len(elegidos)}/{len(elegidos)}",
            f"Bytes       : {format_bytes(total_bytes)}",
            f"Tiempo total: {human_time(dur)}",
            f"Vel. media  : {media:.2f} MB/s",
            f"Destino     : {out_dir}",
        ]))
        return 0

    except ApiError as exc:
        _reportar(r, exc)
        return 1
    except KeyboardInterrupt:
        r.fail("interrumpido por el usuario (la descarga guardó el progreso)")
        return 130


def _pasa_filtro(item: dict, tipos: Optional[List[str]]) -> bool:
    if not tipos or "all" in tipos:
        return True
    return tipo_de(item) in tipos


def _elegir(r: Renderer, archivos: List, args) -> Optional[List]:
    if args.file:
        res = [(rt, it) for rt, it in archivos if it.get("file_name") == args.file]
        return res or None
    if args.fid:
        res = [(rt, it) for rt, it in archivos if it.get("fid") == args.fid]
        return res or None
    if args.files is not None:
        idx = _parse_indices(args.files, len(archivos))
        if idx is None:
            r.fail(f"selección inválida: {args.files!r} (formato '1,3-5')")
            return []
        return [archivos[i] for i in idx if 0 <= i < len(archivos)]
    if len(archivos) > 1 and r.tty and not args.all:
        return _menu_interactivo(r, archivos)
    return archivos


def _parse_indices(especificacion: str, total: int) -> Optional[List[int]]:
    indices: List[int] = []
    try:
        for parte in especificacion.split(","):
            parte = parte.strip()
            if not parte:
                continue
            if "-" in parte:
                a, b = (int(x) for x in parte.split("-", 1))
                indices.extend(range(a, b + 1))
            else:
                indices.append(int(parte))
    except ValueError:
        return None
    return [i - 1 for i in indices]


def _menu_interactivo(r: Renderer, archivos: List) -> List:
    filas = [
        f"{n:>3} │ {it.get('file_name')}  {r.file_dim(it)}"
        for n, (_, it) in enumerate(archivos, 1)
    ]
    filas.append(f"  0 │ {r.G('TODO')} ({len(archivos)} archivo(s))")
    print()
    print(r.panel("Selección de archivos", filas))
    print(r.DIM("formato: '0' = todo · '1,3-5' · '2' · q = cancelar"))

    while True:
        try:
            raw = input(r.C("  selección > ")).strip()
        except (EOFError, KeyboardInterrupt):
            return archivos
        if not raw or raw.lower() in ("all", "*", "0"):
            return archivos
        if raw.lower() == "q":
            return []
        idx = _parse_indices(raw, len(archivos))
        if idx is not None:
            return [archivos[i] for i in idx if 0 <= i < len(archivos)]
        print(r.Y("  expresión no válida; prueba algo como '1,3-5'"))


def _descargar_uno(r: Renderer, client: UcDriveIntlClient, args, destino: Path,
                   item: dict, n: int, total: int) -> None:
    """Descarga un archivo mostrando fases y barra de progreso normalizada."""
    nombre = item.get("file_name", "?")
    tam = format_bytes(item.get("size") or 0)
    print(f" {r.tipo_badge(item)}  {r.B(f'[{n}/{total}] {nombre}  ({tam})')}")
    print(r.hint("obteniendo endpoint … ", "dim"), end="", flush=True)

    try:
        entry = client.get_download_url(item["fid"], args.pwd_id)
    except ApiError as exc:
        print(r.fail("fallo al resolver el endpoint", extra=str(exc)))
        return
    print(r.ok("endpoint obtenido", extra="URL firmada (~3 h)"))

    url = entry["download_url"]
    expected_size = entry.get("size") or item.get("size")
    expected_md5 = None if args.no_verify else entry.get("md5")

    if destino.exists() and expected_size and destino.stat().st_size >= expected_size:
        print(r.ok("ya descargado y completo; se omite"))
        print()
        return

    dl = ResumableDownloader(url, destino, expected_size=expected_size,
                             expected_md5_b64=expected_md5)
    t0 = time.time()
    ema = [0.0]

    def _ev(nombre_ev: str, datos: dict) -> None:
        if nombre_ev == "connecting":
            estado = ("reanudando" if datos.get("resume_from", 0) else "conectando")
            print(r.hint(f"{estado}… ", "dim"), end="", flush=True)
        elif nombre_ev == "streaming":
            extra = (f"reanudado desde {format_bytes(datos.get('resumed_from', 0))}"
                     if datos.get("resumed_from", 0) else "")
            print(r.ok("lista la conexión", extra=extra))
            print(r.DIM("  ⤓ iniciando descarga (servidor OSS) …"))
        elif nombre_ev == "verifying":
            print(r.hint("verificando integridad (MD5) … ", "dim"), end="", flush=True)
        elif nombre_ev == "verify_progress":
            r.clear()
            pct = datos.get("percent", 0.0) / 100.0
            print(r.progress(int(pct * 1000), 1000, 0, time.time() - t0,
                             label="MD5 ", show_eta=False), end="", flush=True)
        elif nombre_ev == "done":
            r.clear()
            print(r.ok("completado", extra=f"{format_bytes(datos.get('size', 0))} en "
                       + human_time(datos.get("seconds", 0))))

    def _prog(done: int, total_b: int, speed: float) -> None:
        ema[0] = (0.8 * ema[0] + 0.2 * speed) if ema[0] else speed
        r.clear()
        print(r.progress(done, total_b or done, ema[0], time.time() - t0,
                         label="↓ " + nombre), end="", flush=True)

    try:
        dl.download(progress=_prog, on_event=_ev, resume=True)
    except DownloadError as exc:
        r.clear()
        _reportar(r, exc)
    print()


# ---------------------------------------------------------------------------
# test (diagnóstico)
# ---------------------------------------------------------------------------
def cmd_test(args: argparse.Namespace, r: Renderer) -> int:
    print(_banner(r))
    print()
    filas: List[str] = []
    ok = True

    # 1) DNS + conectividad TCP al host.
    host = CLOUD_DRIVE_URL.split("://")[1]
    try:
        t0 = time.time()
        info = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
        ip = info[0][4][0]
        filas.append(f"DNS        : {r.ok('resolvido')}  {ip}  ({r.DIM(f'{host}')})")
    except socket.gaierror as exc:
        filas.append(f"DNS        : {r.fail(str(exc))}")
        ok = False

    client = _cliente(args)
    if args.ref:
        pwd = _pwd(args)
        if not pwd:
            return 1
        try:
            t0 = time.time()
            client.get_share_token(pwd)
            lat = (time.time() - t0) * 1000
            _, items = client.list_share(pwd, pdir_fid="0")
            título = (items[0] if items else {}).get("file_name", "(sin título)")
            filas += [
                f"API token   : {r.ok('ok', extra=f'{lat:.0f} ms')}",
                f"Share       : {pwd}  ·  {título}  ·  "
                f"{len(items)} el. en la raíz",
                f"Stoken      : {r.DIM(client.stoken or '—')}",
            ]
        except ApiError as exc:
            filas.append(f"API         : {r.fail(exc.message)}")
            filas.append(r.DIM("  ↳ " + describe(exc.kind, exc.code)))
            ok = False
    else:
        client.verbose = True
        try:
            t0 = time.time()
            client.get_share_token("000000000000")
            lat = (time.time() - t0) * 1000
            filas.append(f"API token   : {r.ok('ok', extra=f'{lat:.0f} ms (reachable)')}")
        except ApiError as exc:
            lat = (time.time() - t0) * 1000
            filas.append(f"API token   : {r.fail(exc.message, extra=f'{lat:.0f} ms')}")
            filas.append(r.DIM("  ↳ " + describe(exc.kind, exc.code)))
            ok = False

    navegador = USER_AGENT.split("Safari/")[0].split(" ")[-1]
    filas.append(f"Herramienta : {r.B(navegador)} {r.DIM(USER_AGENT)}")
    filas.append(f"Estado final: {r.ok('todo correcto') if ok else r.R('se detectaron fallos')}")
    print(r.panel("Diagnóstico de conexión", filas))
    print()
    print(r.hint("si hay timeouts/limitación, espera unos minutos y reintenta; "
                 "usa --verbose para ver cada petición."))
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------
def _add_ref(sp: argparse.ArgumentParser):
    sp.add_argument("ref",
                    help="'id corto' o URL como https://uc-share.com/s/<id>?la=es-la")


def _global_flags() -> argparse.ArgumentParser:
    g = argparse.ArgumentParser(add_help=False)
    g.add_argument("--no-color", action="store_true", help="Desactivar colores ANSI")
    g.add_argument("--verbose", action="store_true",
                   help="Log interno (stderr) de cada petición a la API")
    g.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return g


def build_parser() -> argparse.ArgumentParser:
    flags = _global_flags()
    p = argparse.ArgumentParser(
        prog="uc-drive-downloader",
        description="Descarga archivos (cualquier tipo) de shares públicas de UC "
                    "Drive internacional, sin cuenta. Acepta id corto o URL.",
        parents=[flags],
    )

    sub = p.add_subparsers(dest="command", required=True)

    p_info = sub.add_parser("info", help="Detalle corto de la share.", parents=[flags])
    _add_ref(p_info)
    p_info.set_defaults(func=cmd_info)

    p_list = sub.add_parser("list", help="Lista el contenido de la share.", parents=[flags])
    _add_ref(p_list)
    p_list.add_argument("--fid", help="Listar solo esta carpeta (fid).")
    p_list.add_argument("--recursive", action="store_true", help="Recorre subcarpetas.")
    p_list.set_defaults(func=cmd_list)

    p_v = sub.add_parser("view", help="Detalle de un elemento (con --url, resuelve URL).",
                         parents=[flags])
    _add_ref(p_v)
    p_v.add_argument("--fid", help="Fid del elemento a detallar.")
    p_v.add_argument("--file", help="Nombre del archivo a detallar.")
    p_v.add_argument("--url", action="store_true", help="Resolver también la URL directa.")
    p_v.set_defaults(func=cmd_view)

    p_r = sub.add_parser("raw", help="Salida avanzada JSON (para scripts).", parents=[flags])
    _add_ref(p_r)
    p_r.add_argument("--fid", help="Solo este archivo.")
    p_r.add_argument("--file", help="Solo el archivo con este nombre.")
    p_r.add_argument("--url", action="store_true", help="Incluir download_url/MD5.")
    p_r.add_argument("--field", metavar="CAMPO",
                     help="Imprimir solo un campo: fid name path size size_h type "
                          "format_type md5 url")
    p_r.set_defaults(func=cmd_raw)

    p_dl = sub.add_parser("download", help="Descarga archivos (recursivo, reanudable).",
                          parents=[flags])
    _add_ref(p_dl)
    p_dl.add_argument("--all", action="store_true",
                      help="Descargar todo sin preguntar.")
    p_dl.add_argument("--files", metavar="1,3-5",
                      help="Seleccionar por índice del listado.")
    p_dl.add_argument("--file", help="Descargar solo este nombre.")
    p_dl.add_argument("--fid", help="Descargar solo este fid.")
    p_dl.add_argument("--type", choices=TIPO_CHOICES, nargs="+",
                      help="Filtrar por tipo: video audio image document all.")
    p_dl.add_argument("--out", default="./descargas", help="Carpeta de destino.")
    p_dl.add_argument("--no-verify", action="store_true",
                      help="Omitir verificación de tamaño/MD5.")
    p_dl.set_defaults(func=cmd_download)

    p_t = sub.add_parser("test", help="Diagnóstico de conexión (DNS/latencia/servidor).",
                         parents=[flags])
    _add_ref(p_t)
    p_t.set_defaults(func=cmd_test)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    r = Renderer(use_color=False if args.no_color else None)
    try:
        return args.func(args, r)
    except ApiError as exc:
        _reportar(r, exc)
        return 1
    except ValueError as exc:
        print(f"✗ {exc}")
        return 1
    except KeyboardInterrupt:
        print("✗ interrumpido")
        return 130


if __name__ == "__main__":
    sys.exit(main())