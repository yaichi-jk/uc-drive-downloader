# uc-drive-downloader

Descargador **sin cuenta** de enlaces de compartir públicos de **UC Drive**
(plataforma internacional: `https://uc-share.com`, `https://drive.ucweb.com`).

Resuelve la share, obtiene la **URL directa firmada** de cada archivo y la
descarga de forma **reanudable** con verificación de tamaño y MD5.

> Herramienta educativa / de uso personal. Úsala solo con contenido que tengas
> derecho a descargar. No está afiliada a UC/Alibaba.

## Características

- Sin cuenta, sin app, sin cookies de sesión.
- 100 % **librería estándar** de Python (`urllib`), sin dependencias.
- Obtiene la URL directa (OSS/Alibaba) firmada de cada archivo.
- Descarga **reanudable** (HTTP `Range`): reinicias y sigue desde donde quedó.
- Verificación opcional de **tamaño** y **MD5** (el servidor los publica).
- Comandos CLIs: `info`, `list` (recursivo) y `download`.
- Funciona con shares internacionales (`uc-share.com/s/<id>`).

## Requisitos

- Python 3.8 o superior.
- Conexión a internet (los enlaces de descarga caducan a las ~3 horas).

## Instalación

```bash
git clone <tu-repositorio> uc-drive-downloader
cd uc-drive-downloader
# sin dependencias externas; basta con Python 3.8+
```

O simplemente copia la carpeta a cualquier equipo con Python.

## Uso rápido (CLI)

```bash
cd uc-drive-downloader

# 1) Ver título y stoken de la share
python3 -m uc_drive.cli info e8ccf39f80024

# 2) Listar el contenido (raíz)
python3 -m uc_drive.cli list e8ccf39f80024

# 3) Listar todo de forma recursiva
python3 -m uc_drive.cli list e8ccf39f80024 --recursive

# 4) Descargar un archivo por nombre
python3 -m uc_drive.cli download e8ccf39f80024 --file "mi_video.mp4" --out ./descargas

# 5) Descargar por fid
python3 -m uc_drive.cli download e8ccf39f80024 --fid 992d0757255a47d799fa8f8634fb9ce8

# 6) Descargar el primer archivo de la raíz
python3 -m uc_drive.cli download e8ccf39f80024 --out ./descargas
```

La descarga muestra progreso en vivo y, si se interrumpe, basta con repetir el
mismo comando: **continúa desde donde quedó**.

## Uso como librería

```python
from pathlib import Path
from uc_drive import UcDriveIntlClient, ResumableDownloader

PWD_ID = "e8ccf39f80024"

client = UcDriveIntlClient()

# 1) stoken de la share
client.get_share_token(PWD_ID)

# 2) listar la raíz
_, items = client.list_share(PWD_ID, pdir_fid="0")
archivo = next(i for i in items if not i["dir"])   # primer archivo

# 3) URL directa firmada
entry = client.get_download_url(archivo["fid"], PWD_ID)
print(entry["file_name"], entry["size"], entry["md5"])

# 4) descargar (reanudable + verificación)
dest = Path("descargas") / entry["file_name"]
ResumableDownloader(
    entry["download_url"],
    dest,
    expected_size=entry["size"],
    expected_md5_b64=entry["md5"],
).download()
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
  cliente guarda automáticamente el último visto (`UcDriveIntlClient.stoken`) y
  siempre usa un `stoken` fresco antes de pedir el `download_url`.
- **Caducidad de la URL**: el enlace firmado expira a las ~3 horas
  (`Expires`), suficiente para descargar en una pasada o reanudando.

## Estructura del proyecto

```
uc-drive-downloader/
├── README.md            # este documento
├── requirements.txt     # sin dependencias (anotación informativa)
├── .gitignore
├── uc_drive/
│   ├── __init__.py      # exporta la API pública
│   ├── api.py           # UcDriveIntlClient (token, listar, download_url)
│   ├── downloader.py    # ResumableDownloader (rango + verificación)
│   └── cli.py           # CLI: info / list / download
└── examples/
    └── descarga_ejemplo.py   # script de ejemplo completo
```

## Limitaciones conocidas

- Solo funciona con shares de la plataforma **internacional** de UC Drive.
  Las shares de `drive.uc.cn` (CN) usan otros hosts y flujos.
- Solo descarga archivos de la **raíz** (sin recorrer subcarpetas todavía en el
  comando `download`; usa `--fid` si necesitas algo concreto).
- Los enlaces caducan (~3 h); para archivos enormes hay que reanudar antes de
  que expire la URL, o re-solicitar la URL con `get_download_url`.

## Hoja de ruta

- [x] Resolución de share sin cuenta (stoken + listado).
- [x] Obtención de URL directa firmada.
- [x] Descarga reanudable con verificación de integridad.
- [x] CLI documentado (`info`, `list`, `download`).
- [ ] Descarga de árboles completos (recursivo en `download`).
- [ ] Repositorio privado en GitHub + releases binarios (pendiente).

## Licencia

Solo para fines educativos. El código de este proyecto no está afiliado,
respaldado ni patrocinado por UC Web / Alibaba Group.