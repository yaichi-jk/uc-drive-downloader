"""Cliente de la API pública de UC Drive (plataforma internacional).

Descripción general
-------------------
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

Sólo utiliza la biblioteca estándar de Python (``urllib``), por lo que no
necesita dependencias externas.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

# Host base de la API de UC Drive internacional (descubierto en el bundle web).
CLOUD_DRIVE_URL = "https://m-intldrive.ucweb.com"

# User-Agent moderno basado en Chrome; el servidor lo usa como "primer filtro".
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Referer/Origin que manda la página oficial; mejora la compatibilidad.
REFERER = "https://drive.ucweb.com/"


class ApiError(Exception):
    """Error devuelto por la API de UC Drive (status HTTP y/o code JSON)."""

    def __init__(self, message: str, http_status: Optional[int] = None,
                 code: Optional[int] = None, req_id: Optional[str] = None):
        super().__init__(message)
        self.http_status = http_status
        self.code = code
        self.req_id = req_id

    def __str__(self) -> str:  # pragma: no cover
        detail = f"[HTTP {self.http_status}]" if self.http_status else ""
        if self.code:
            detail += f" [code {self.code}]"
        if self.req_id:
            detail += f" (req_id {self.req_id})"
        return f"{detail} {self.args[0]}".strip()


class UcDriveIntlClient:
    """Cliente de bajo nivel contra la API de UC Drive internacional.

    Cada método recibe y devuelve los campos según vienen del servidor. El
    estado relevante (``stoken``) se actualiza automáticamente cuando el
    servidor lo rota en alguna respuesta.
    """

    def __init__(self, base_url: str = CLOUD_DRIVE_URL, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.stoken: Optional[str] = None

    # ------------------------------------------------------------------
    # Helpers HTTP
    # ------------------------------------------------------------------
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
                ``code != 0``).
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

        req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                encoding = resp.headers.get("X-U-Content-Encoding")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            encoding = exc.headers.get("X-U-Content-Encoding")
            http_status = exc.code
        except urllib.error.URLError as exc:
            raise ApiError(f"error de red: {exc.reason}")

        if encoding:
            # No debería pasar porque pedimos "no"; si ocurre lo marcamos claro.
            raise ApiError(
                f"el servidor respondió cifrado wg (inicio {raw[:16]!r}); "
                "omite/inspecciona la llamada 'X-U-Req-Res-Encoding'",
                http_status=locals().get("http_status"),
            )

        try:
            parsed: Dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            raise ApiError(f"respuesta no JSON: {raw[:120]!r}", http_status=locals().get("http_status"))

        status = parsed.get("status")
        code = parsed.get("code")
        if status != 200 or code != 0:
            raise ApiError(
                parsed.get("message") or parsed.get("error") or "error desconocido",
                http_status=locals().get("http_status"),
                code=code,
                req_id=parsed.get("req_id"),
            )

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