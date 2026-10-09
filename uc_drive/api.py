"""Cliente de la API pública de UC Drive (plataforma internacional).

Descripción general
--------------------
Este módulo implementa las llamadas mínimas que necesita la página web oficial
de UC Drive (https://uc-share.com / https://drive.ucweb.com) para resolver un
enlace de compartir ("share") y obtener la URL directa de descarga de cada
archivo, **sin necesidad de cuenta**.

Flujo descendido de la ingeniería inversa del bundle web (v1.0.30):

    1. ``POST /1/clouddrive/share/sharepage/token``
         -> devuelve un ``stoken`` fresco para la share.

    2. ``POST /1/clouddrive/share/sharepage/v2/detail``
         -> lista el contenido de la share (archivos y carpetas) en claro.

    3. ``POST /1/clouddrive/file/download``
         -> pide la URL de descarga directa (firmada por OSS / Alibaba).

Detalle técnico importante: todas las respuestas de estos endpoints suelen
llegar cifradas (cabecera ``X-U-Content-Encoding: wg``). El propio web solicita
**no** cifrar la respuesta enviando la cabecera ``X-U-Req-Res-Encoding: no``,
que es exactamente lo que hacemos aquí para trabajar 100% en claro.

Errores: todos los fallos se lanzan como :class:`ApiError` tipificados (atributo
``kind``) según :mod:`uc_drive.errors`, con reintentos automáticos ante fallos
transitorios (red, timeout, 5xx y limitación de frecuencia).
"""

from __future__ import annotations

import json
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.client import RemoteDisconnected
from typing import Any, Dict, List, Optional, Tuple

from uc_drive.errors import (
    BUSINESS,
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
    UCError,
)

# Host base de la API de UC Drive internacional (descubierto en el bundle web).
CLOUD_DRIVE_URL = "https://m-intldrive.ucweb.com"

# User-Agent moderno basado en Chrome; el servidor lo usa como "primer filtro".
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Referer/Origin que manda la página oficial; mejora la compatibilidad.
REFERER = "https://drive.ucweb.com/"


class ApiError(UCError):
    """Error devuelto por la API de UC Drive.

    Attributes:
        message: descripción corta (en español cuando la conocemos).
        kind: categoría del error (ver ``uc_drive.errors``).
        code: código JSON de negocio (ej. 41027).
        http: código HTTP (ej. 403).
        req_id: identificador de petición que reporta el servidor (si existe).
    """

    def __init__(self, message: str, kind: str = KIND_UNKNOWN,
                 code: Optional[int] = None, http: Optional[int] = None,
                 req_id: Optional[str] = None):
        super().__init__(message, kind=kind, code=code, http=http)
        self.req_id = req_id

    @property
    def http_status(self) -> Optional[int]:
        return self.http

    def __str__(self) -> str:
        partes = [self.message]
        if self.http:
            partes.append(f"[HTTP {self.http}]")
        if self.code:
            partes.append(f"[code {self.code}]")
        if self.req_id:
            partes.append(f"(req_id {self.req_id})")
        return " ".join(partes)


def _clasificar_http(code: int, reason: str, cuerpo: str = "") -> ApiError:
    """Mapa HTTP/código de negocio -> ApiError tipificado."""
    # Códigos de negocio (JSON) tienen prioridad cuando vienen en el cuerpo.
    try:
        payload = json.loads(cuerpo)
    except (json.JSONDecodeError, ValueError):
        payload = {}
    negocio = payload.get("code") or payload.get("error_code")
    error_msg = (payload.get("message") or payload.get("msg") or reason or "error")

    kind = ""
    if negocio in BUSINESS:
        kind = BUSINESS[negocio]
    elif code == 400:
        kind = KIND_INVALID
    elif code == 401:
        kind = KIND_AUTH
    elif code == 403:
        kind = KIND_FORBIDDEN
    elif code == 404:
        kind = KIND_NOT_FOUND
    elif code == 410:
        kind = KIND_NOT_FOUND
    elif code == 429:
        kind = KIND_RATE_LIMIT
    elif 500 <= code < 600:
        kind = KIND_SERVER
    else:
        kind = KIND_HTTP

    if negocio:
        return ApiError(f"{error_msg}", kind=kind, code=negocio, http=code)
    return ApiError(f"{error_msg}", kind=kind, http=code)


class UcDriveIntlClient:
    """Cliente de bajo nivel contra la API de UC Drive internacional.

    Cada método recibe y devuelve los campos según vienen del servidor. El
    estado relevante (``stoken``) se actualiza automáticamente cuando el
    servidor lo rota en alguna respuesta.

    Args:
        base_url: host base de la API.
        timeout: segundos de espera por petición HTTP.
        retries: reintentos ante fallos transitorios (red/timeout/5xx/429).
        verbose: si True, imprime log interno de cada petición en stderr.
    """

    def __init__(self, base_url: str = CLOUD_DRIVE_URL, timeout: int = 30,
                 retries: int = 2, verbose: bool = False):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.verbose = verbose
        self.stoken: Optional[str] = None

    # ------------------------------------------------------------------
    # Helpers HTTP
    # ------------------------------------------------------------------
    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"[api] {msg}", file=sys.stderr)

    def _request_json(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
        stoken: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Ejecuta una petición HTTP y devuelve el JSON (ya descifrado).

        Args:
            method: ``"GET"`` o ``"POST"``.
            path: ruta bajo el host base (ej. ``/1/clouddrive/share/sharepage/token``).
            params: query-string opcional.
            body: cuerpo JSON opcional (se serializa).
            stoken: si se pasa, se manda también como cabecera ``x-clouddrive-st``.

        Raises:
            ApiError: si la respuesta no es JSON de éxito (``status != 200`` o
                ``code != 0``), con ``kind`` tipificado.
        """
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)

        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Origin": REFERER,
            "Referer": REFERER,
            "X-U-Req-Res-Encoding": "no",  # pide respuestas SIN cifrado wg
        }
        data = None
        if method.upper() == "POST":
            headers["Content-Type"] = "application/json; charset=UTF-8"
            data = json.dumps(body or {}).encode("utf-8")
        if stoken:
            headers["x-clouddrive-st"] = stoken

        latest: Optional[ApiError] = None
        for intento in range(self.retries + 1):
            t0 = time.time()
            try:
                with urllib.request.urlopen(urllib.request.Request(
                        url, data=data, headers=headers, method=method.upper()),
                        timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8")
                    http_status = resp.status
                    req_id = resp.headers.get("X-U-Web-Req-Time") or None
                dur = (time.time() - t0) * 1000
                self._log(f"{method} {path} -> 200 ({dur:.0f} ms)")
                break
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode("utf-8", "replace")
                http_status = exc.code
                req_id = None
                dur = (time.time() - t0) * 1000
                self._log(f"{method} {path} -> HTTP {http_status} ({dur:.0f} ms)")
                latest = _clasificar_http(http_status, exc.reason or str(exc),
                                          cuerpo=raw)
            except urllib.error.URLError as exc:
                causa = exc.reason if exc.reason else exc
                dur = (time.time() - t0) * 1000
                self._log(f"{method} {path} -> {type(causa).__name__} ({dur:.0f} ms)")
                latest = _clasificar_transitorio(causa)
            except (socket.timeout, TimeoutError) as exc:
                dur = (time.time() - t0) * 1000
                self._log(f"{method} {path} -> timeout ({dur:.0f} ms)")
                latest = ApiError("tiempo de espera agotado", kind=KIND_TIMEOUT)
            except (ssl.SSLError, RemoteDisconnected, ConnectionError, OSError) as exc:
                dur = (time.time() - t0) * 1000
                self._log(f"{method} {path} -> {type(exc).__name__} ({dur:.0f} ms)")
                latest = ApiError(f"error de red: {exc}", kind=KIND_NETWORK)

            # Reintentos solo para fallos transitorios.
            if latest is not None and _es_transitorio(latest):
                espera = 1.0 * (intento + 1)
                self._log(f"  re-intento {intento + 1} en {espera:.0f}s…")
                time.sleep(espera)
                continue
            # Los no transitorios se propagan de inmediato.
            if latest is not None:
                raise latest
        else:
            raise latest or ApiError("petición fallida", kind=KIND_UNKNOWN)

        if "X-U-Content-Encoding" in resp.headers:
            raise ApiError(
                f"el servidor respondió cifrado wg (inicio {raw[:16]!r}); "
                "revisa la cabecera 'X-U-Req-Res-Encoding: no'",
                kind=KIND_UNKNOWN, http=http_status,
            )

        try:
            parsed: Dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            raise ApiError(f"respuesta no JSON: {raw[:120]!r}", kind=KIND_UNKNOWN,
                           http=http_status)

        status = parsed.get("status")
        code = parsed.get("code")
        if status != 200 or code != 0:
            negocio = code or parsed.get("error_code")
            msg = (parsed.get("message") or parsed.get("msg") or parsed.get("error")
                   or "error desconocido")
            kind = BUSINESS.get(negocio, KIND_INVALID if status == 400 else KIND_UNKNOWN)
            raise ApiError(str(msg), kind=kind, code=negocio, http=http_status,
                           req_id=parsed.get("req_id"))

        # Si el servidor rota el stoken (solo en respuestas que traen data dict),
        # lo guardamos automáticamente.
        data = parsed.get("data")
        if isinstance(data, dict):
            tk = data.get("token_info") or {}
            if tk.get("stoken"):
                self.stoken = tk["stoken"]

        return parsed

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------
    def get_share_token(self, pwd_id: str, passcode: str = "") -> str:
        """Obtiene un ``stoken`` válido para una share pública.

        Es el primer paso de todo el flujo. El ``stoken`` caduca a los pocos
        minutos o al rotar con otra llamada de ``detail``.

        Args:
            pwd_id: identificador corto de la share (ej. ``e8ccf39f80024``).
            passcode: contraseña de la share si la tiene ('' si es pública).

        Returns:
            El ``stoken`` recién emitido.
        """
        path = "/1/clouddrive/share/sharepage/token"
        resp = self._request_json("POST", path, body={"pwd_id": pwd_id, "passcode": passcode or ""})
        token = (resp.get("data") or {}).get("stoken")
        if not token:
            raise ApiError("la API no devolvió ningún stoken", code=resp.get("code"))
        self.stoken = token
        return token

    def list_share(self, pwd_id: str, pdir_fid: str = "0", page: int = 1,
                   size: int = 50) -> Tuple[str, List[Dict[str, Any]]]:
        """Lista el contenido de una carpeta dentro de la share.

        Con ``pdir_fid="0"`` lista la raíz de la share. Pasando el ``fid`` de
        una carpeta se listan sus hijos.

        Args:
            pwd_id: identificador de la share.
            pdir_fid: ``fid`` de la carpeta a listar ('' o "0" => raíz).
            page: página (1-indexada).
            size: tamaño de página.

        Returns:
            Tupla ``(stoken_vigente, items)`` donde cada item es el diccionario
            del servidor (con ``fid``, ``file_name``, ``size``, ``dir``, ...).
        """
        path = "/1/clouddrive/share/sharepage/v2/detail"
        body: Dict[str, Any] = {"pwd_id": pwd_id, "page": page, "size": size, "url_type": 1}
        if pdir_fid and pdir_fid != "0":
            body["pdir_fid"] = pdir_fid
        resp = self._request_json("POST", path, body=body, stoken=self.stoken)
        data = resp.get("data") or {}
        items = (data.get("detail_info") or {}).get("list") or []
        return self.stoken, items

    def get_download_url(self, fid: str, pwd_id: str) -> Dict[str, Any]:
        """Pide la URL directa de descarga de un archivo de la share.

        Si el ``stoken`` actual caducó, se refresca solo antes de llamar.

        Args:
            fid: ``fid`` del archivo a descargar (no del directorio).
            pwd_id: identificador de la share.

        Returns:
            Entrada completa que devuelve el servidor para ese archivo,
            incluyendo ``download_url``, ``size``, ``md5`` (base64) y metadatos.

        Raises:
            ApiError: si no se obtiene ``download_url``.
        """
        if not self.stoken:
            self.get_share_token(pwd_id)
        path = "/1/clouddrive/file/download"
        resp = self._request_json(
            "POST", path,
            body={"fids": [fid], "pwd_id": pwd_id, "stoken": self.stoken},
            stoken=self.stoken,
        )
        entries = resp.get("data") or []
        if not entries:
            raise ApiError("la API no devolvió ninguna entrada de descarga", code=resp.get("code"))
        entry = entries[0]
        if not entry.get("download_url"):
            raise ApiError(
                "la entrada no trae download_url (¿es una carpeta?)", code=resp.get("code")
            )
        return entry

    def walk_share(self, pwd_id: str, pdir_fid: str = "0",
                   path_folders: Tuple[str, ...] = ()):
        """Recorre recursivamente la share y devuelve cada archivo.

        Esta es la función que usan ``list --recursive`` y ``download`` para
        encontrar archivos aunque estén metidos en subcarpetas.

        Args:
            pwd_id: identificador de la share.
            pdir_fid: carpeta desde la que empezar ('' o "0" => raíz).
            path_folders: pila de nombres de carpeta (uso interno recursivo).

        Yields:
            Tupla ``(ruta_relativa_str, item)`` para cada archivo (no carpeta).
        """
        _, items = self.list_share(pwd_id, pdir_fid=pdir_fid)
        for item in items:
            ruta = "/".join(path_folders + (item.get("file_name", ""),))
            if item.get("dir"):
                yield from self.walk_share(pwd_id, item.get("fid", ""),
                                           path_folders + (item.get("file_name", ""),))
            else:
                yield ruta, item

    def resolve_share(self, pwd_id: str) -> str:
        """Conveniencia: refresca el stoken y devuelve el título de la share."""
        token = self.get_share_token(pwd_id)
        _, items = self.list_share(pwd_id, pdir_fid="0")
        title = (items[0] if items else {}).get("file_name", pwd_id)
        return title


# ---------------------------------------------------------------------------
# Clasificación de fallos transitorios (reintentables)
# ---------------------------------------------------------------------------
def _es_transitorio(err: ApiError) -> bool:
    return err.kind in (KIND_NETWORK, KIND_TIMEOUT, KIND_SERVER, KIND_RATE_LIMIT)


def _clasificar_transitorio(causa: BaseException) -> ApiError:
    if isinstance(causa, (socket.timeout, TimeoutError)):
        return ApiError("tiempo de espera agotado", kind=KIND_TIMEOUT)
    if isinstance(causa, socket.gaierror):
        return ApiError(f"no se pudo resolver el host: {causa}", kind=KIND_NETWORK)
    if isinstance(causa, (ssl.SSLError, RemoteDisconnected, ConnectionError, OSError)):
        return ApiError(f"error de red: {causa}", kind=KIND_NETWORK)
    return ApiError(f"error de red: {causa}", kind=KIND_NETWORK)