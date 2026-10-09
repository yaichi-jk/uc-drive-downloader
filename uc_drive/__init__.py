"""uc-drive-downloader: descarga shares públicas de UC Drive (internacional).

Uso como librería::

    from uc_drive import UcDriveIntlClient, ResumableDownloader

    client = UcDriveIntlClient()
    entry = client.get_download_url("992d0757255a47d799fa8f8634fb9ce8", "e8ccf39f80024")
    ResumableDownloader(entry["download_url"], "mi_video.mp4",
                        expected_size=entry["size"],
                        expected_md5_b64=entry["md5"]).download()

Errores tipificados (``.kind``, ``.code``, ``.http``, ``.friendly``)::

    from uc_drive import ApiError, DownloadError
    from uc_drive.errors import describe

También expone helpers de interfaz y utilidades::

    from uc_drive.ui import Renderer
    from uc_drive.util import normalize_share_ref, format_bytes, human_time, tipo_de
"""

from uc_drive.api import ApiError, UcDriveIntlClient, USER_AGENT, CLOUD_DRIVE_URL
from uc_drive.downloader import (
    DownloadError,
    EventCallback,
    ProgressCallback,
    ResumableDownloader,
)
from uc_drive.errors import (
    UCError,
    KIND_AUTH,
    KIND_FORBIDDEN,
    KIND_HTTP,
    KIND_INVALID,
    KIND_NETWORK,
    KIND_NOT_FOUND,
    KIND_RATE_LIMIT,
    KIND_SERVER,
    KIND_TIMEOUT,
    KIND_UNKNOWN,
    describe,
)
from uc_drive.ui import Renderer
from uc_drive.util import (
    TIPOS,
    format_bytes,
    format_epoch_ms,
    format_speed,
    human_time,
    normalize_share_ref,
    tipo_de,
    tipo_legible,
)

__version__ = "1.1.0"

__all__ = [
    "ApiError",
    "UcDriveIntlClient",
    "DownloadError",
    "EventCallback",
    "ProgressCallback",
    "ResumableDownloader",
    "Renderer",
    "UCError",
    "describe",
    "normalize_share_ref",
    "format_bytes",
    "format_speed",
    "format_epoch_ms",
    "human_time",
    "tipo_de",
    "tipo_legible",
    "TIPOS",
    "USER_AGENT",
    "CLOUD_DRIVE_URL",
    "KIND_AUTH",
    "KIND_FORBIDDEN",
    "KIND_HTTP",
    "KIND_INVALID",
    "KIND_NETWORK",
    "KIND_NOT_FOUND",
    "KIND_RATE_LIMIT",
    "KIND_SERVER",
    "KIND_TIMEOUT",
    "KIND_UNKNOWN",
]