"""Descargador de archivos reanudable con verificación de integridad.

Implementa descarga por rangos HTTP (Range) con reanudación automática: si el
archivo destino ya existe y tiene ``N`` bytes, la descarga continúa desde el
byte ``N`` en vez de empezar de cero.

Incluye comprobaciones que interesan a los usuarios de UC Drive:

* Tamaño exacto esperado (el servidor lo anuncia en ``size``).
* MD5 en base64 (el servidor lo anuncia en ``md5``), útil para shares grandes.

Solo usa la biblioteca estándar (``urllib`` + ``hashlib``).
"""

from __future__ import annotations

import base64
import hashlib
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

CHUNK = 1024 * 1024  # 1 MiB por lectura


class DownloadError(Exception):
    """Error durante la descarga (red, verificación, etc.)."""


ProgressCallback = Callable[[int, int, float], None]
"""firma: progress(downloaded, total_or_0, speed_bps)"""


def _open_range(url: str, start: int, timeout: int):
    """Abre un GET con cabecera Range desde ``start`` y devuelve la respuesta."""
    req = urllib.request.Request(url, headers={"Range": f"bytes={start}-"})
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        # 416 => rango fuera de límite; lo traduce el llamador.
        if exc.code == 416:
            raise DownloadError("416: rango fuera de límite (¿archivo ya completo?)")
        raise DownloadError(f"HTTP {exc.code}: {exc.reason}")
    except urllib.error.URLError as exc:
        raise DownloadError(f"error de red: {exc.reason}")


class ResumableDownloader:
    """Descarga reanudable con seguimiento de progreso y verificación.

    Args:
        url: URL directa obtenida con ``get_download_url``.
        dest: ruta del archivo destino.
        expected_size: tamaño esperado en bytes (opcional; se verifica al final).
        expected_md5_b64: MD5 esperado en base64 (opcional; se verifica al final).
        chunk: bytes por lectura/escritura.
        timeout: segundos de timeout por socket.
    """

    def __init__(
        self,
        url: str,
        dest: Path,
        expected_size: Optional[int] = None,
        expected_md5_b64: Optional[str] = None,
        chunk: int = CHUNK,
        timeout: int = 30,
    ):
        self.url = url
        self.dest = Path(dest)
        self.expected_size = expected_size
        self.expected_md5_b64 = expected_md5_b64
        self.chunk = chunk
        self.timeout = timeout

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------
    def download(self, progress: Optional[ProgressCallback] = None,
                 resume: bool = True,
                 max_retries: int = 5, retry_delay: float = 2.0) -> str:
        """Descarga el archivo (reanudable) y devuelve la ruta final.

        Args:
            progress: callback(opcional) con bytes descargados/total y velocidad.
            resume: si True, continúa sobre un archivo parcial existente.
            max_retries: reintentos ante errores de red intermitentes.
            retry_delay: segundos de espera entre reintentos.

        Returns:
            La ruta (str) del archivo descargado.

        Raises:
            DownloadError: si tras los reintentos no se puede completar o si la
                verificación de tamaño/MD5 falla.
        """
        self.dest.parent.mkdir(parents=True, exist_ok=True)

        start = 0
        if resume and self.dest.exists():
            start = self.dest.stat().st_size
            if self.expected_size is not None and start >= self.expected_size:
                self._verify(self.dest)  # ya estaba completo
                return str(self.dest)

        # Si hay archivo parcial, ábrelo en r+b; si no, créalo.
        mode = "r+b" if (start and resume) else "wb"
        if not self.dest.exists():
            self.dest.touch()

        attempts = 0
        while True:
            try:
                self._download(start, mode, progress)
                break
            except (DownloadError, OSError) as exc:
                attempts += 1
                if attempts > max_retries:
                    raise DownloadError(f"reintentos agotados: {exc}")
                time.sleep(retry_delay)
                # Reanudar desde donde quedó.
                start = self.dest.stat().st_size
                mode = "r+b"

        self._verify(self.dest)
        return str(self.dest)

    # ------------------------------------------------------------------
    # internos
    # ------------------------------------------------------------------
    def _download(self, start: int, mode: str,
                  progress: Optional[ProgressCallback]) -> None:
        """Bucle principal: pide Range y escribe los chunks."""
        resp = _open_range(self.url, start, self.timeout)
        total = self.expected_size or _content_length(resp)

        written = start
        last_report = time.time()
        last_bytes = written
        speed = 0.0

        with open(self.dest, mode) as fh:
            fh.seek(start)
            while True:
                block = resp.read(self.chunk)
                if not block:
                    break
                fh.write(block)
                written += len(block)

                now = time.time()
                if now - last_report >= 0.5 and progress is not None:
                    speed = (written - last_bytes) / max(now - last_report, 1e-9)
                    progress(written, total or 0, speed)
                    last_report, last_bytes = now, written

        if progress is not None:
            progress(written, total or written, speed)

    def _verify(self, path: Path) -> None:
        """Comprueba tamaño y MD5 si se conocen los valores esperados."""
        size = path.stat().st_size
        if self.expected_size is not None and size != self.expected_size:
            raise DownloadError(
                f"tamaño incorrecto: esperado {self.expected_size}, descargado {size}"
            )
        if self.expected_md5_b64 is not None:
            digest = hashlib.md5()
            with open(path, "rb") as fh:
                for block in iter(lambda: fh.read(CHUNK), b""):
                    digest.update(block)
            got = base64.b64encode(digest.digest()).decode()
            if got != self.expected_md5_b64:
                raise DownloadError(f"MD5 no coincide: esperado {self.expected_md5_b64}, obtenido {got}")


def _content_length(resp) -> int:
    """Intenta leer el tamaño total desde las cabeceras de la respuesta."""
    try:
        return int(resp.headers.get("Content-Length") or 0)
    except (TypeError, ValueError):
        return 0


def format_bytes(n: float) -> str:
    """Formatea bytes a una unidad legible (KiB/MiB/GiB)."""
    value = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} B"