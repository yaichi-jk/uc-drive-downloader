"""Utilidades: normalización de referencias a share y formatos de tiempo."""

from __future__ import annotations

import re

_PWD_IN_URL = re.compile(
    r"(?:/s/|/share/|/m/|\bpwd_id[=/]|\bshare[=/])"
    r"([A-Za-z0-9_-]{6,})"
)


def normalize_share_ref(valor: str) -> str:
    """Acepta distintos formatos y devuelve el ``pwd_id`` de la share.

    Formatos entendidos::

        e8ccf39f80024
        https://uc-share.com/s/e8ccf39f80024
        https://uc-share.com/s/e8ccf39f80024?la=es-la
        https://drive.ucweb.com/s/e8ccf39f80024?la=es

    Raises:
        ValueError: si no se reconoce ningún identificador en ``valor``.
    """
    texto = (valor or "").strip()
    m = _PWD_IN_URL.search(texto)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{6,}", texto):
        return texto
    raise ValueError(
        f"no reconozco el identificador de share en: {valor!r} "
        "(usa el formato uc-share.com/s/<id> o el id corto)"
    )


def human_time(segundos: float) -> str:
    """Convierte segundos a ``HH:MM:SS`` o ``MM:SS`` según el tamaño."""
    secs = int(max(0, round(segundos)))
    h, r = divmod(secs, 3600)
    m, s = divmod(r, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def format_bytes(n: float) -> str:
    """Formatea un número de bytes a una unidad legible (B/KiB/MiB/GiB/TiB)."""
    value = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.2f} TiB"


def format_speed(bytes_por_segundo: float) -> str:
    """Formatea una velocidad en bytes/s a B/s, KiB/s, MiB/s o GiB/s."""
    return format_bytes(bytes_por_segundo) + "/s"


def format_epoch_ms(ms: int) -> str:
    """Convierte una marca de tiempo en milisegundos a ``YYYY-MM-DD HH:MM``."""
    if not ms:
        return "—"
    import datetime

    return datetime.datetime.fromtimestamp(ms / 1000.0).strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# Tipos de archivo reconocidos (la API es genérica: cualquier extensión vale)
# ---------------------------------------------------------------------------
TIPOS = {
    "video": {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv",
              ".m4v", ".ts", ".3gp", ".mpg", ".mpeg"},
    "audio": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".opus", ".wma"},
    "image": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg",
              ".heic", ".tiff"},
    "document": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                 ".txt", ".md", ".csv", ".zip", ".rar", ".7z", ".epub"},
}
_EXT_OF = {ext: nombre for nombre, exts in TIPOS.items() for ext in exts}

# Nombre legible de cada categoría para mostrarlo en la interfaz.
TIPO_NOMBRE = {
    "video": "video",
    "audio": "audio",
    "image": "imagen",
    "document": "documento",
    "other": "archivo",
}


def tipo_de(item: dict) -> str:
    """Devuelve el tipo de archivo según su extensión (video/audio/image/...)."""
    nombre = (item.get("file_name") or "").lower()
    sufijo = "." + nombre.rsplit(".", 1)[-1] if "." in nombre else ""
    return _EXT_OF.get(sufijo, "other")


def tipo_legible(item: dict) -> str:
    """Nombre en español del tipo de archivo."""
    return TIPO_NOMBRE.get(tipo_de(item), TIPO_NOMBRE["other"])