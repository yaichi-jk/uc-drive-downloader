"""Renderizado de interfaz de terminal para uc-drive-downloader.

Todo usa la biblioteca estándar y se degrada con elegancia cuando la salida no
es una terminal (tuberías/CI): sin colores, sin barra de refresh constante.
"""

from __future__ import annotations

import shutil
import sys
from typing import Optional, Sequence

from uc_drive.util import (
    format_bytes,
    format_speed,
    human_time,
    tipo_legible,
)


# --------------------------------------------------------------------------
# Paleta ANSI
# --------------------------------------------------------------------------
class _Pal:
    _RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    GRAY = "\033[90m"


def _paint(text: str, color: str, on: bool) -> str:
    return f"{color}{text}{_Pal._RESET}" if on else text


# --------------------------------------------------------------------------
# Renderer
# --------------------------------------------------------------------------
class Renderer:
    """Centro de dibujo: conoce el ancho de la terminal y si hay color.

    Args:
        use_color: forzar/desactivar color (None => auto-detectar tty).
    """

    def __init__(self, use_color: Optional[bool] = None):
        self.tty = sys.stdout.isatty()
        self.color = self.tty if use_color is None else use_color

    # -- utilidades básicas -------------------------------------------------
    def width(self) -> int:
        try:
            return shutil.get_terminal_size((100, 30)).columns
        except OSError:
            return 100

    def B(self, text: str) -> str:
        return _paint(text, _Pal.BOLD, self.color)

    def G(self, text: str) -> str:
        return _paint(text, _Pal.GREEN, self.color)

    def R(self, text: str) -> str:
        return _paint(text, _Pal.RED, self.color)

    def Y(self, text: str) -> str:
        return _paint(text, _Pal.YELLOW, self.color)

    def C(self, text: str) -> str:
        return _paint(text, _Pal.CYAN, self.color)

    def M(self, text: str) -> str:
        return _paint(text, _Pal.MAGENTA, self.color)

    def DIM(self, text: str) -> str:
        return _paint(text, _Pal.DIM, self.color)

    # -- cajas --------------------------------------------------------------
    def panel(self, title: str, rows: Sequence[str]) -> str:
        """Dibuja una caja bordeada con título y filas (ya formateadas)."""
        ancho = self.width() - 2
        margen = max(0, min(2, (ancho - len(title)) // 4))
        out = [f"╭─{self.B(' ' + title + ' ')}─" + "─" * margen + "╮"]
        for fila in rows:
            t = fila[:ancho] if self.tty else fila
            out.append(f"│ {t.ljust(ancho, ' ')} │")
        out.append("╰" + "─" * (ancho + 3) + "╯")
        return "\n".join(out)

    def hint(self, text: str, color: str = "cyan") -> str:
        c = getattr(self, color.upper()) if hasattr(self, color.upper()) else self.C
        return f"{c('▸')} {text}"

    def ok(self, text: str, extra: str = "") -> str:
        tail = f"  {self.DIM(extra)}" if extra else ""
        return f"{self.G('✓')} {text}{tail}"

    def fail(self, text: str, extra: str = "") -> str:
        tail = f"  {self.DIM(extra)}" if extra else ""
        return f"{self.R('✗')} {text}{tail}"

    # -- etiquetas ----------------------------------------------------------
    def tipo_badge(self, item: dict) -> str:
        """Etiqueta de color para el tipo de archivo (video, audio, ...)."""
        if item.get("dir"):
            return self.C("[CARPETA]")
        tipo = tipo_legible(item)
        colores = {
            "video": self.C,     # cian
            "audio": self.M,     # magenta
            "image": self.Y,     # amarillo
            "document": self.B,  # bold
            "archivo": self.DIM,
        }
        return colores[tipo](f"[{tipo.upper()}]")

    def file_dim(self, item: dict, falso_total: int = 0) -> str:
        """Metadatos dim de un archivo: tamaño · tipo · fid (truncado)."""
        tam = format_bytes(item.get("size") or 0)
        fid = (item.get("fid") or "")[:12] + "…"
        txt = f"({tam} · {tipo_legible(item)})  {self.DIM('fid=' + fid)}" if not item.get("dir") \
            else f"({tam} · {item.get('include_items', 0) or 0} el.)  {self.DIM('fid=' + fid)}"
        return txt

    # -- barra de progreso --------------------------------------------------
    @staticmethod
    def _bar(frac: float, ancho: int) -> str:
        frac = max(0.0, min(1.0, frac))
        filled = int(frac * ancho)
        return "█" * filled + "░" * (ancho - filled)

    def progress(self, done: int, total: int, speed: float, elapsed: float,
                 label: str = "", show_eta: bool = True) -> str:
        """Devuelve una línea única (sin \\n) con barra, %, velocidad y ETA.

        ``speed`` se interpreta en bytes/s y se normaliza a B/s, KiB/s, MiB/s…
        ``done``/``total`` en bytes se normalizan igual (ej. ``117.5 MiB``).
        """
        total = total or done or 1
        frac = min(1.0, done / total)
        pct = frac * 100.0

        ancho = self.width()
        done_txt = format_bytes(done).rjust(12)
        total_txt = format_bytes(total).rjust(12)
        left_meta = f"{pct:5.1f}% {done_txt}/{total_txt}"

        right_meta = ""
        if speed > 0:
            right_meta += f" ⚡{format_speed(speed)}"
        if show_eta and speed > 0:
            right_meta += f" ETA {human_time((total - done) / max(speed, 1e-9))}"
        right_meta += f" ⏱{human_time(elapsed)}"

        # Reservamos la "cara" de la izquierda: label + barra + meta izquierda.
        fixed = len(left_meta) + len(right_meta) + 3
        resto = ancho - fixed
        # La barra ocupa ~un tercio del resto; el label el resto.
        bar_w = max(8, min(36, resto // 3))
        bar = self._bar(frac, bar_w)

        if label:
            disp = label[: max(0, resto - bar_w - 1)].ljust(max(1, resto - bar_w + 1))
        else:
            disp = " " * 1
        linea = f"\r{disp}{bar} {left_meta}{right_meta}"
        if self.tty:
            linea += " " * max(0, ancho - len(linea))
        return linea

    def clear(self) -> None:
        if self.tty:
            sys.stdout.write("\r" + " " * self.width() + "\r")
            sys.stdout.flush()