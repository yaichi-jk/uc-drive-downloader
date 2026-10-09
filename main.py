"""Punto de entrada para empaquetado binario (PyInstaller onefile).

Permite lanzar el CLI igual tanto desde el código fuente como desde el
ejecutable compilado::

    python3 main.py info https://uc-share.com/s/577cf9ba429a4?la=es-la
    ./dist/uc-drive-downloader download 577cf9ba429a4 --all
"""

import sys

from uc_drive.cli import main

if __name__ == "__main__":
    sys.exit(main())