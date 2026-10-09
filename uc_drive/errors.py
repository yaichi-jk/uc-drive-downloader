"""Taxonomía de errores de uc-drive-downloader.

Todos los fallos (API o descarga) se tipifican con un ``kind`` para que la
interfaz pueda explicar al usuario qué pasó y qué hacer:

- ``network``     : red caída, DNS, conexión interrumpida.
- ``timeout``     : agotó el tiempo de espera (servidor lento/saturado).
- ``http``        : error HTTP sin clasificar.
- ``rate_limit``  : limitación del servidor (posible agotamiento de IP),
                    se recomienda esperar y reintentar.
- ``forbidden``   : 403 — acceso denegado (share caducada o sin permisos).
- ``not_found``   : 404 — no existe (share/archivo movido o expirado).
- ``server``      : 5xx — error interno del servidor.
- ``auth``        : fallo de autenticación del enlace (stoken caducado).
- ``invalid``     : solicitud inválida (fid/stoken incorrectos).
- ``unknown``     : error inesperado.
"""

from __future__ import annotations

KIND_NETWORK = "network"
KIND_TIMEOUT = "timeout"
KIND_HTTP = "http"
KIND_RATE_LIMIT = "rate_limit"
KIND_FORBIDDEN = "forbidden"
KIND_NOT_FOUND = "not_found"
KIND_SERVER = "server"
KIND_AUTH = "auth"
KIND_INVALID = "invalid"
KIND_UNKNOWN = "unknown"

DESCRIPCION = {
    KIND_NETWORK: "error de red (conexión interrumpida o DNS). Revisa tu conexión.",
    KIND_TIMEOUT: "se agotó el tiempo de espera: la red puede estar saturada o el "
                  "servidor lento. Reintenta en unos segundos.",
    KIND_RATE_LIMIT: "el servidor está limitando las peticiones (posible agotamiento "
                     "de IP). Espera unos minutos y reintenta.",
    KIND_FORBIDDEN: "acceso denegado (403): la share puede haber caducado o requerir "
                    "permisos.",
    KIND_NOT_FOUND: "no encontrado (404): el archivo o la share pudo expirar o ser movido.",
    KIND_SERVER: "error interno del servidor (5xx). Reintenta en unos segundos.",
    KIND_AUTH: "fallo de autenticación del enlace (stoken caducado). Reintenta la operación.",
    KIND_INVALID: "solicitud inválida (fid o stoken incorrectos para esta share).",
    KIND_UNKNOWN: "error inesperado. Consulta la salida detallada con --verbose.",
}

# Códigos de negocio observados en UC Drive intl.
BUSINESS = {
    41027: KIND_FORBIDDEN,   # "The shared does not exist" (o expiró)
    41020: KIND_NOT_FOUND,   # elemento inexistente
    40001: KIND_INVALID,     # parámetros inválidos
    40003: KIND_FORBIDDEN,   # sin permisos
    40005: KIND_RATE_LIMIT,  # frecuencia limitada
}


def describe(kind: str, code=None) -> str:
    """Devuelve una explicación legible para un ``kind`` de error."""
    texto = DESCRIPCION.get(kind, DESCRIPCION[KIND_UNKNOWN])
    if code is not None:
        return f"{texto} (código {code})"
    return texto


class UCError(Exception):
    """Error base tipificado del proyecto.

    Attributes:
        message: descripción corta en español.
        kind: categoría (ver constantes KIND_*).
        code: código de negocio del servidor (si existe).
        http: código HTTP (si existe).
    """

    def __init__(self, message: str, kind: str = KIND_UNKNOWN,
                 code=None, http=None):
        super().__init__(message)
        self.message = message
        self.kind = kind
        self.code = code
        self.http = http

    @property
    def friendly(self) -> str:
        """Mensaje completo: causa + explicación para el usuario."""
        return f"{self.message} — {describe(self.kind, self.code)}"