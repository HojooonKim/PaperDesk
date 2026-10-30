from __future__ import annotations

import json
import logging
import mimetypes
import shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from .. import APP_NAME, __version__
from ..app import Application
from ..domain.errors import InvalidInput, NotFound, ReaderError
from .api import MAX_UPLOAD, ApiController
from .http import Request, Response, Router
from ..i18n import _, from_header, translate

STATIC_DIR = Path(__file__).with_name("static")
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]")
APP_ROUTES = ("/", "/library", "/reader", "/settings")  # client-side routes all serve the app shell
CLIENT_HEADER = "X-Paperdesk"
# The bundled file types are fixed here, not taken from mimetypes: on Windows mimetypes reads HKEY_CLASSES_ROOT, where
# another program may have registered .js as text/plain, and with nosniff the web view then runs no script (blank window).
STATIC_TYPES = {".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
                ".json": "application/json", ".txt": "text/plain", ".png": "image/png", ".svg": "image/svg+xml",
                ".woff2": "font/woff2"}
log = logging.getLogger("paperdesk.web")


class Forbidden(ReaderError):
    status = 403
    code = "forbidden"


class PaperdeskServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], app: Application, *, static_dir: Path = STATIC_DIR) -> None:
        super().__init__(address, RequestHandler)
        self.app = app
        self.static_dir = static_dir.resolve()
        self.router = Router()
        ApiController(app).register(self.router)
        app.jobs.start()

    def server_close(self) -> None:
        self.app.analysis.close()
        self.app.jobs.close()
        super().server_close()

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{'127.0.0.1' if host in ('', '0.0.0.0') else host}:{port}/"


class RequestHandler(BaseHTTPRequestHandler):
    server: PaperdeskServer
    server_version = f"{APP_NAME}/{__version__}"
    protocol_version = "HTTP/1.1"

    def handle(self) -> None:
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError):
            # Closing/reloading the local web view can terminate a keep-alive connection mid-response.
            self.close_connection = True

    def do_GET(self) -> None: self._dispatch()
    def do_POST(self) -> None: self._dispatch()
    def do_PUT(self) -> None: self._dispatch()
    def do_PATCH(self) -> None: self._dispatch()
    def do_DELETE(self) -> None: self._dispatch()

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - signature from BaseHTTPRequestHandler
        log.debug("%s %s", self.address_string(), format % args)

    def _dispatch(self) -> None:
        url = urlsplit(self.path)
        lang = from_header(self.headers.get("X-Paperdesk-Lang") or self.headers.get("Accept-Language"))
        self._lang = lang
        try:
            self._check_host()
            if url.path.startswith("/api/"):
                response = self._api(url.path, dict(parse_qsl(url.query)))
            else:
                response = self._static(url.path)
        except ReaderError as error:
            self._drain()
            response = Response.error(error, lang)
        except Exception:  # keep the server alive; details go to the log only
            log.exception("unhandled error for %s %s", self.command, url.path)
            response = Response.json({"error": {"code": "internal", "message": translate(_("예상하지 못한 오류가 났어요."), lang)}}, 500)
        self._send(response)

    def _check_host(self) -> None:
        # Blocks DNS-rebinding: only accept requests addressed to this machine's loopback name.
        host = self.headers.get("Host", "")
        name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
        if name not in LOOPBACK_HOSTS:
            raise Forbidden(_("허용되지 않은 주소예요."))

    def _check_same_origin(self) -> None:
        site = self.headers.get("Sec-Fetch-Site")
        if site and site not in ("same-origin", "none"):
            raise Forbidden(_("다른 사이트에서 온 요청은 받을 수 없어요."))
        if self.command != "GET" and self.headers.get(CLIENT_HEADER) != "1":
            raise Forbidden(_("앱 화면에서 보낸 요청이 아니에요."))

    def _drain(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if 0 < length <= MAX_UPLOAD and not getattr(self, "_body_read", False):
            self.rfile.read(length)
            self._body_read = True

    def _api(self, path: str, query: dict[str, str]) -> Response:
        self._check_same_origin()
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD:
            self.close_connection = True
            raise InvalidInput(_("파일이 너무 커요."))
        body = self.rfile.read(length) if length else b""
        self._body_read = True
        handler, params = self.server.router.resolve(self.command, path)
        return handler(Request(self.command, path, query, self.headers, body, params, self._lang))

    def _static(self, path: str) -> Response:
        if self.command != "GET":
            raise NotFound(_("없는 주소예요."))
        if path == "/boot.js":
            return self._boot_script()
        if path in APP_ROUTES:
            path = "/index.html"
        target = (self.server.static_dir / path.lstrip("/")).resolve()
        if self.server.static_dir not in target.parents or not target.is_file():
            raise NotFound(_("없는 파일이에요."))
        kind = STATIC_TYPES.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if kind.startswith("text/") or kind.endswith("javascript"):
            kind += "; charset=utf-8"
        return Response.send_file(target, kind, {"Cache-Control": "no-cache"})

    def _boot_script(self) -> Response:
        # Loaded synchronously before first paint so the saved theme and panel state apply without a flash.
        # A script file (not inline) keeps the Content-Security-Policy free of 'unsafe-inline'.
        data = json.dumps({'preferences': self.server.app.preferences.all(),
                           'restoreFailed': self.server.app.restore_failed}, ensure_ascii=False).replace("<", "\\u003c")
        body = f"window.paperdeskBoot = {data};\n".encode("utf-8")
        return Response(200, body, "text/javascript; charset=utf-8", {"Cache-Control": "no-store"})

    def _send(self, response: Response) -> None:
        size = response.file.stat().st_size if response.file else len(response.body)
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(size))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
                         "worker-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'")
        for key, value in response.headers.items():
            self.send_header(key, value)
        self.end_headers()
        if response.file:
            with response.file.open("rb") as stream:
                shutil.copyfileobj(stream, self.wfile)
        else:
            self.wfile.write(response.body)


def create_server(app: Application, host: str = "127.0.0.1", port: int = 0) -> PaperdeskServer:
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("보안을 위해 이 컴퓨터(127.0.0.1)에서만 열 수 있어요.")
    return PaperdeskServer((host, port), app)
