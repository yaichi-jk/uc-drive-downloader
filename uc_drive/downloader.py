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
import socket
import ssl
import time
import urllib.error
import urllib.request
from http.client import RemoteDisconnected
from pathlib import Path
from typing import Callable, Optional

from uc_drive.errors import (
    KIND_FORBIDDEN,
    KIND_HTTP,
    KIND_NETWORK,
    KIND_NOT_FOUND,
    KIND_RATE_LIMIT,
    KIND_SERVER,
    KIND_TIMEOUT,
    KIND_UNKNOWN,
    UCError,
)
from uc_drive.util import format_bytes

CHUNK = 1024 * 1024  # 1 MiB por lectura


class DownloadError(UCError):
    """Error durante la descarga (red, verificación, etc.)."""


ProgressCallback = Callable[[int, int, float], None]
"""firma: progress(downloaded, total_or_0, speed_bps)"""

EventCallback = Callable[[str, dict], None]
"""firma: event(nombre, datos).

Nombres de evento emitidos por ``ResumableDownloader``:

- ``connecting``  -> ``{"resume_from": int}`` (acaba de pedir el rango)
- ``streaming``   -> ``{"total": int, "resumed_from": int}`` (transfiriendo)
- ``verifying``   -> ``{"md5_b64": str}`` (empieza comprobación)
- ``verify_progress`` -> ``{"percent": float}``
- ``done``        -> ``{"path": str, "size": int, "seconds": float}``
"""


def _clasificar_exc(exc: BaseException) -> DownloadError:
    """Convierte excepciones de red/servidor en ``DownloadError`` tipificado."""
    if isinstance(exc, urllib.error.HTTPError):
        return _http_error(exc.code, exc.reason)
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return DownloadError("tiempo de espera agotado en la descarga", kind=KIND_TIMEOUT)
    if isinstance(exc, (socket.gaierror,)):
        return DownloadError(f"no se pudo resolver el host: {exc}", kind=KIND_NETWORK)
    if isinstance(exc, (ssl.SSLError, RemoteDisconnected, ConnectionError, OSError)):
        return DownloadError(f"error de red: {exc}", kind=KIND_NETWORK)
    return DownloadError(f"error inesperado: {exc}", kind=KIND_UNKNOWN)


def _http_error(code: int, reason: str) -> DownloadError:
    """Mapea un código HTTP a un ``DownloadError`` con ``kind`` legible."""
    if code == 404:
        return DownloadError(f"HTTP 404: {reason}", kind=KIND_NOT_FOUND, http=404)
    if code == 403:
        return DownloadError(f"HTTP 403: {reason}", kind=KIND_FORBIDDEN, http=403)
    if code in (429,):
        return DownloadError(f"HTTP 429: {reason}", kind=KIND_RATE_LIMIT, http=429)
    if 500 <= code < 600:
        return DownloadError(f"HTTP {code}: {reason}", kind=KIND_SERVER, http=code)
    return DownloadError(f"HTTP {code}: {reason}", kind=KIND_HTTP, http=code)


def _open_range(url: str, start: int, timeout: int):
    """Abre un GET con cabecera Range desde ``start`` y devuelve la respuesta.

    Raises:
        DownloadError: cuyos ``kind``/``http`` tipifican el fallo.
    """
    req = urllib.request.Request(url, headers={"Range": f"bytes={start}-"})
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.URLError as exc:
        raise _clasificar_exc(exc.reason if exc.reason else exc)
    except (socket.timeout, TimeoutError) as exc:
        raise DownloadError("tiempo de espera agotado en la descarga",
                            kind=KIND_TIMEOUT) from exc
    except (ssl.SSLError, RemoteDisconnected, ConnectionError, OSError) as exc:
        raise DownloadError(f"error de red en la descarga: {exc}",
                            kind=KIND_NETWORK) from exc
    except urllib.error.HTTPError as exc:  # pragma: no cover (subclase de URLError)
        raise _http_error(exc.code, exc.reason) from exc


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
                 on_event: Optional[EventCallback] = None,
                 resume: bool = True,
                 max_retries: int = 5, retry_delay: float = 2.0) -> str:
        """Descarga el archivo (reanudable) y devuelve la ruta final.

        Args:
            progress: callback(opcional) datos de progreso (bytes/total/velocidad).
            on_event: callback(opcional) con eventos de fase (ver EventCallback).
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
        t0 = time.time()

        start = 0
        if resume and self.dest.exists():
            start = self.dest.stat().st_size
        if self.expected_size is not None and start >= self.expected_size:
            self._verify(self.dest, on_event)  # ya estaba completo
            if on_event:
                on_event("done", {"path": str(self.dest),
                                  "size": int(self.dest.stat().st_size),
                                  "seconds": time.time() - t0})
            return str(self.dest)

        # Si hay archivo parcial, ábrelo en r+b; si no, créalo.
        mode = "r+b" if (start and resume) else "wb"
        if not self.dest.exists():
            self.dest.touch()

        attempts = 0
        while True:
            try:
                self._download(start, mode, progress, on_event)
                break
            except (DownloadError, OSError) as exc:
                attempts += 1
                if attempts > max_retries:
                    raise DownloadError(f"reintentos agotados: {exc}")
                time.sleep(retry_delay)
                # Reanudar desde donde quedó.
                start = self.dest.stat().st_size
                mode = "r+b"

        self._verify(self.dest, on_event)
        if on_event:
            on_event("done", {"path": str(self.dest),
                              "size": int(self.dest.stat().st_size),
                              "seconds": time.time() - t0})
        return str(self.dest)

    # ------------------------------------------------------------------
    # internos
    # ------------------------------------------------------------------
    def _download(self, start: int, mode: str,
                  progress: Optional[ProgressCallback],
                  on_event: Optional[EventCallback]) -> None:
        """Bucle principal: pide Range y escribe los chunks."""
        if on_event:
            on_event("connecting", {"resume_from": start})
        resp = _open_range(self.url, start, self.timeout)
        total = self.expected_size or _content_length(resp)
        if on_event:
            on_event("streaming", {"total": total, "resumed_from": start})

        written = start
        last_report = time.time()
        last_bytes = written
        speed = 0.0

        with open(self.dest, mode) as fh:
            fh.seek(start)
            while True:
                try:
                    block = resp.read(self.chunk)
                except (socket.timeout, TimeoutError) as exc:
                    raise DownloadError(f"tiempo de espera agotado (a partir de "
                                        f"{format_bytes(written)})",
                                        kind=KIND_TIMEOUT) from exc
                except (ssl.SSLError, RemoteDisconnected, ConnectionError, OSError) as exc:
                    raise DownloadError(f"conexión perdida (a partir de "
                                        f"{format_bytes(written)}): {exc}",
                                        kind=KIND_NETWORK) from exc
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

    def _verify(self, path: Path, on_event: Optional[EventCallback] = None) -> None:
        """Comprueba tamaño y MD5 si se conocen los valores esperados.

        Mientras calcula el MD5 emite eventos ``verify_progress`` para que la
        interfaz pueda mostrar su propia barra de progreso.
        """
        size = path.stat().st_size
        if self.expected_size is not None and size != self.expected_size:
            raise DownloadError(
                f"tamaño incorrecto: esperado {self.expected_size}, descargado {size}"
            )
        if self.expected_md5_b64 is not None:
            if on_event:
                on_event("verifying", {"md5_b64": self.expected_md5_b64})
            digest = hashlib.md5()
            with open(path, "rb") as fh:
                processed = 0
                while True:
                    block = fh.read(CHUNK)
                    if not block:
                        break
                    digest.update(block)
                    processed += len(block)
                    if on_event and (processed // CHUNK) % 16 == 0:
                        on_event("verify_progress", {"percent": processed / size * 100.0})
            got = base64.b64encode(digest.digest()).decode()
            if got != self.expected_md5_b64:
                raise DownloadError(
                    f"MD5 no coincide: esperado {self.expected_md5_b64}, obtenido {got}"
                )


def _content_length(resp) -> int:
    """Intenta leer el tamaño total desde las cabeceras de la respuesta."""
    try:
        return int(resp.headers.get("Content-Length") or 0)
    except (TypeError, ValueError):
        return 0