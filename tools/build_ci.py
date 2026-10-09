"""Empaqueta el binario onefile y reporta ruta/nombre (usado por CI).

Detecta la plataforma y arquitectura del runner y produce un binario
autocontenido con nombre único::

    uc-drive-downloader-linux-x64
    uc-drive-downloader-linux-arm64
    uc-drive-downloader-macos-x64
    uc-drive-downloader-macos-arm64
    uc-drive-downloader-windows-x64.exe

El archivo generado va a ``dist/<nombre>``; imprime la ruta en la última línea
para que el flujo de CI pueda subirlo como artefacto/release.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys

# La raíz del repo (padre de tools/) debe estar importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _canonical() -> str:
    so = sys.platform
    if so.startswith("win"):
        plat = "windows"
        ext = ".exe"
    elif so.startswith("darwin"):
        plat = "macos"
        ext = ""
    elif so.startswith("linux"):
        plat = "linux"
        ext = ""
    else:
        plat = so
        ext = ""
    arch = platform.machine().lower()
    if arch in ("x86_64", "amd64"):
        arch = "x64"
    elif arch in ("aarch64", "arm64"):
        arch = "arm64"
    return f"uc-drive-downloader-{plat}-{arch}{ext}"


def main() -> int:
    import uc_drive  # leer la versión (raíz del repo en sys.path)

    nombre = _canonical()
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--onefile", "--name", nombre, "--distpath", "dist",
         "--workpath", "build", "main.py"],
        check=True,
    )
    ruta = os.path.join("dist", nombre)
    if os.path.exists(ruta):
        tam = os.path.getsize(ruta)
        print(f"OK {ruta} ({tam} bytes)")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())