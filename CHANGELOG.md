# Changelog

Todos los cambios notables de este proyecto se documentan aquí.

El formato sigue [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) y la
versión sigue [SemVer](https://semver.org/lang/es/).

## [1.1.0] - 2026-10-09

### Añadido
- Comandos completos del CLI: `info`, `list`, `view`, `raw`, `download` y `test`.
- Soporte de URLs completas (`https://uc-share.com/s/<id>?la=es-la`).
- Flags globales `--no-color`, `--verbose` y `--version`.
- Menú interactivo de selección de archivos (`0`=todo, `1,3-5`, `q`=cancelar).
- Barra de progreso con %, MiB descargados, velocidad normalizada, ETA y
  tiempo transcurrido.
- Errores tipificados (`UCError`/`ApiError`/`DownloadError`) con códigos de
  negocio mapeados (404, 403/41027, 429, timeouts, red, 5xx) y reintentos.
- Descarga reanudable (Range) y verificación de tamaño + MD5.
- `raw --field <campo>` y `view --url` para obtener URLs directas firmadas.
- `test` como diagnóstico de conexión (DNS, latencia, stoken, share).

### Cambiado
- Unificación de versiones (1.1.0) en `__init__` y CLI.
- Normalización de velocidad/pesos humanos (`format_speed`, `format_bytes`).

## [1.0.0] - 2026-10-09

### Añadido
- Primera versión funcional: resolución de shares públicas de UC Drive
  (internacional), extracción de URL OSS firmada y descarga con verificación.
- Estructura de paquete: `uc_drive/{api,downloader,errors,ui,util,cli}.py`.

## [0.1.0] - 2026-10-08

### Añadido
- Bootstrap: flujo manual de descubrimiento de la API (token → detail → download).