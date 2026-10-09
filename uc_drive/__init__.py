"""uc-drive-downloader: descarga shares públicas de UC Drive (internacional).

Uso como librería::

    from uc_drive import UcDriveIntlClient, ResumableDownloader

    client = UcDriveIntlClient()
    client.get_share_token("e8ccf39f80024")
    entry = client.get_download_url("992d0757255a47d799fa8f8634fb9ce8", "e8ccf39f80024")

    ResumableDownloader(entry["download_url"], "mi_video.mp4",
                        expected_size=entry["size"],
                        expected_md5_b64=entry["md5"]).download()
"""

from uc_drive.api import ApiError, UcDriveIntlClient, USER_AGENT, CLOUD_DRIVE_URL
from uc_drive.downloader import DownloadError, ResumableDownloader, format_bytes

__all__ = [
    "ApiError",
    "UcDriveIntlClient",
    "DownloadError",
    "ResumableDownloader",
    "format_bytes",
    "USER_AGENT",
    "CLOUD_DRIVE_URL",
]
__version__ = "1.0.0"