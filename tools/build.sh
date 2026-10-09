#!/usr/bin/env bash
# Empaqueta uc-drive-downloader como ejecutable único (PyInstaller --onefile).
#
# Uso:
#   tools/build.sh                -> dist/<sistema>-<arq>/uc-drive-downloader
#   tools/build.sh --version X    -> nombra el binario uc-drive-downloader-X
#
# El binario no necesita Python instalado en el equipo de destino.
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON=${PYTHON:-python3}
VERSION=$("$PYTHON" -c "import uc_drive; print(uc_drive.__version__)")

SYS=$(uname -s | tr '[:upper:]' '[:lower:]')
# Normaliza arquitecturas: x86_64 -> x64, aarch64/arm64 -> arm64
case "$(uname -m)" in
  x86_64)  ARCH="x64" ;;
  amd64)   ARCH="x64" ;;
  arm64|aarch64) ARCH="arm64" ;;
  *)       ARCH="$(uname -m)" ;;
esac

OUT="dist/${SYS}-${ARCH}"
echo "→ Instalando PyInstaller (si falta)…"
"$PYTHON" -m pip install -q -r requirements-build.txt

echo "→ Compilando onefile para ${SYS}/${ARCH} (v${VERSION})…"
rm -rf build/ "$OUT"
"$PYTHON" -m PyInstaller --noconfirm --clean --onefile \
  --name uc-drive-downloader \
  --distpath "$OUT" \
  --workpath build \
  main.py

echo "→ Resultado:"
ls -lh "$OUT/uc-drive-downloader"
echo "✓ Binario listo: $PWD/$OUT/uc-drive-downloader"