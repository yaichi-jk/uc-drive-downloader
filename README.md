# uc-drive-downloader

Descargador **sin cuenta** de enlaces de compartir públicos de **UC Drive**
(plataforma internacional: `https://uc-share.com`, `https://drive.ucweb.com`).

Resuelve la share, obtiene la **URL directa firmada** de cada archivo y lo
descarga de forma **reanudable** con barra de progreso (%, velocidad, ETA) y
verificación de **tamaño y MD5**. Soporta **cualquier extensión** (video,
audio, imagen, documentos…).

> Herramienta educativa / de uso personal. Úsala solo con contenido que tengas
> derecho a descargar. No está afiliada a UC/Alibaba.

## Características

- Sin cuenta, sin app, sin cookies de sesión.
- 100 % **librería estándar** de Python (`urllib`), sin dependencias.
- Acepta el `id` corto **o una URL completa** (`https://uc-share.com/s/<id>?la=es-la`).
- Descarga **reanudable** (HTTP `Range`): si se corta, sigue desde donde quedó.
- Verificación opcional de **tamaño** y **MD5** (el servidor los publica).
- Fases visibles: *obteniendo endpoint → conectando → iniciando descarga →
  verificando MD5*.
- Barra de progreso con **porcentaje**, peso normalizado, **velocidad** y **ETA**.
- Carpetas y archivos diferenciados con etiquetas de color; menú interactivo
  para elegir archivos (por ejemplo `1,3-5`).
- **Errores tipificados**: 404, 403, 429/limitación de IP, timeouts, fallos de
  red y 5xx se explican y, los transitorios, se reintentan solos.
- Subcomandos: `info`, `list`, `view`, `raw`, `download` y `test`.
- Log interno por petición con `--verbose`.

## Requisitos

- Python 3.8 o superior.
- Conexión a internet (los enlaces de descarga caducan a las ~3 horas).

## Instalación

```bash
git clone <tu-repositorio> uc-drive-downloader
cd uc-drive-downloader
# sin dependencias externas; basta con Python 3.8+
```

## Uso rápido (CLI)

```bash
cd uc-drive-downloader

# info: título + tamaño + stoken
python3 -m uc_drive.cli info "https://uc-share.com/s/577cf9ba429a4?la=es-la"

# list: raíz o recursivo (con etiquetas de tipo)
python3 -m uc_drive.cli list 577cf9ba429a4
python3 -m uc_drive.cli list 577cf9ba429a4 --recursive

# view: detalle de un archivo (fid, resolución, fechas, …) + URL directa
python3 -m uc_drive.cli view 577cf9ba429a4 --file "Linternas 1x7.mp4" --url

# download: menú interactivo (0 = todo, o "1,3-5")
python3 -m uc_drive.cli download 577cf9ba429a4 --out ./descargas

# download: todo sin preguntar, solo videos, o un archivo concreto
python3 -m uc_drive.cli download 577cf9ba429a4 --all --type video
python3 -m uc_drive.cli download 577cf9ba429a4 --file "Linternas 1x7.mp4"

# raw: salida avanzada JSON para scripts
python3 -m uc_drive.cli raw 577cf9ba429a4
python3 -m uc_drive.cli raw 577cf9ba429a4 --file "Linternas 1x7.mp4" --url --field url

# test: diagnóstico de conexión (DNS, latencia, stoken)
python3 -m uc_drive.cli test 577cf9ba429a4 --verbose
```

La descarga muestra en vivo `% · MiB / MiB · velocidad · ETA · tiempo`; si se
interrumpe, repetir el mismo comando **continúa desde donde quedó**.

### `raw` para scripts

```bash
# Árbol completo en JSON
python3 -m uc_drive.cli raw 577cf9ba429a4 > share.json

# Solo la URL directa de un archivo (ideal para xargs/curl)
python3 -m uc_drive.cli raw 577cf9ba429a4 --file "x.mp4" --url --field url

# Campos disponibles: fid name path size size_h type format_type md5 url
python3 -m uc_drive.cli raw 577cf9ba429a4 --fid <fid> --url --field size_h
```

## Errores tipificados

Cualquier fallo lleva una categoría (`kind`) que la CLI explica:

| Término       | Caso típico                                      |
|---------------|--------------------------------------------------|
| `not_found`   | 404 · share/archivo expirado o movido            |
| `forbidden`   | 403 · share caducada o sin permisos (41027)      |
| `rate_limit`  | 429 · posibles limitaciones de IP: espera y reintenta |
| `timeout`     | servidor lento o red saturada                    |
| `network`     | DNS o conexión interrumpida                      |
| `server`      | 5xx interno del servidor                         |
| `auth`/`invalid` | stoken caducado o fid incorrecto               |

Los `timeout`, `network`, `rate_limit` y `5xx` se reintentan automáticamente.
`--verbose` muestra cada petición con su latencia en `stderr`.

## Uso como librería

```python
from pathlib import Path
from uc_drive import UcDriveIntlClient, ResumableDownloader, ApiError

PWD_ID = "e8ccf39f80024"
client = UcDriveIntlClient()

try:
    client.get_share_token(PWD_ID)                      # 1) stoken
    _, items = client.list_share(PWD_ID)                # 2) listar raíz
    archivo = next(i for i in items if not i["dir"])
    entry = client.get_download_url(archivo["fid"], PWD_ID)
    print(entry["file_name"], entry["size"], entry["md5"])

    dest = Path("descargas") / entry["file_name"]       # 3) descargar
    ResumableDownloader(entry["download_url"], dest,
                        expected_size=entry["size"],
                        expected_md5_b64=entry["md5"]).download()
except ApiError as e:
    print(e.message, "→", e.kind, e.code, e.http)       # errores tipificados
```

## Cómo funciona

Endpoints usados (host base `https://m-intldrive.ucweb.com`):

| Paso | Método/Endpoint                       | Body clave                          | Resultado            |
|------|---------------------------------------|-------------------------------------|----------------------|
| 1    | `POST /1/clouddrive/share/sharepage/token` | `{pwd_id, passcode}`          | `stoken` fresco      |
| 2    | `POST /1/clouddrive/share/sharepage/v2/detail` | `{pwd_id, pdir_fid, page, size}` | lista de archivos |
| 3    | `POST /1/clouddrive/file/download`   | `{fids:[fid], pwd_id, stoken}`      | `download_url` firmada |

Detalles de la ingeniería inversa (bundle web v1.0.30):

- **Cifrado `wg`**: por defecto esas respuestas llegan cifradas con la cabecera
  `X-U-Content-Encoding: wg`. El propio web solicita no cifrar la respuesta
  mandando la cabecera **`X-U-Req-Res-Encoding: no`**, y el servidor responde en
  claro. Eso es lo que hace este cliente en cada petición.
- **Rotación de `stoken`**: cada llamada de `detail` emite un `stoken` nuevo. El
  cliente guarda automáticamente el último visto y siempre usa un `stoken`
  fresco antes de pedir el `download_url`.
- **Caducidad de la URL**: el enlace firmado expira a las ~3 horas (`Expires`),
  suficiente para descargar en una pasada o reanudando.

## Estructura del proyecto

```
uc-drive-downloader/
├── README.md            # este documento
├── requirements.txt     # sin dependencias (anotación informativa)
├── .gitignore
├── uc_drive/
│   ├── __init__.py      # exporta la API pública
│   ├── errors.py        # taxonomía de errores (kinds + descripciones)
│   ├── api.py           # UcDriveIntlClient (token, listar, download_url)
│   ├── downloader.py    # ResumableDownloader (rango + verificación)
│   ├── ui.py            # Renderer: cajas, badges, barra de progreso
│   ├── util.py          # format_bytes/speed, tiempo, tipos de archivo
│   └── cli.py           # CLI: info/list/view/raw/download/test
└── examples/
    └── descarga_ejemplo.py   # script de ejemplo completo
```

## Releases (binarios únicos por plataforma)

Cada release publica **ejecutables autocontenidos** (PyInstaller `--onefile`,
sin necesidad de Python instalado) para todos los sistemas/arquitecturas:

| Binario                              | SO / arquitectura                    |
|--------------------------------------|--------------------------------------|
| `uc-drive-downloader-linux-x64`      | Linux x86_64                         |
| `uc-drive-downloader-linux-arm64`    | Linux ARM64 (Raspberry, Termux/proot)|
| `uc-drive-downloader-macos-arm64`    | macOS Apple Silicon                  |
| `uc-drive-downloader-macos-x64`      | macOS Intel                          |
| `uc-drive-downloader-windows-x64.exe`| Windows 64 bits                      |

El flujo CI (`/.github/workflows/release.yml`) compila los 5 al publicar un tag
`v*` y los adjunta al Release automáticamente. Para compilar localmente::

    tools/build.sh                 # detecta SO/arq y genera unique binario
    python tools/build_ci.py       # variante con nombre por plataforma-arm

Utilizar un binario es igual que el CLI::

    ./uc-drive-downloader-linux-x64 info "https://uc-share.com/s/577cf9ba429a4?la=es-la"
    uc-drive-downloader-windows-x64.exe download 577cf9ba429a4 --all

En Android (Termux) el binario `linux-arm64` corre dentro del proot/termux.

## Limitaciones conocidas

- Solo funciona con shares de la plataforma **internacional** de UC Drive.
  Las shares de `drive.uc.cn` (CN) usan otros hosts y flujos.
- Los enlaces caducan (~3 h); para archivos enormes hay que reanudar antes de
  que expire la URL, o re-solicitar la URL con `get_download_url`.

## Hoja de ruta

- [x] Resolución de share sin cuenta (stoken + listado).
- [x] Obtención de URL directa firmada.
- [x] Descarga reanudable con verificación de integridad.
- [x] CLI documentado (`info`, `list`, `view`, `raw`, `download`, `test`).
- [x] Descarga de árboles completos (recursivo en `download`).
- [x] Errores tipificados (404/403/429/timeout/red) con reintentos.
- [ ] Repositorio privado en GitHub + releases binarios (pendiente).

## Licencia

Solo para fines educativos. El código de este proyecto no está afiliado,
respaldado ni patrocinado por UC Web / Alibaba Group.