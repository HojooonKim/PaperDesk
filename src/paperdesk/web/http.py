from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from ..domain.errors import InvalidInput, NotFound, ReaderError
from ..i18n import _, translate


class MethodNotAllowed(ReaderError):
    status = 405
    code = "method_not_allowed"


@dataclass
class Request:
    method: str
    path: str
    query: Mapping[str, str]
    headers: Mapping[str, str]
    body: bytes = b""
    params: dict[str, str] = field(default_factory=dict)
    lang: str = "ko"

    def json(self) -> dict:
        if not self.body:
            return {}
        try:
            data = json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise InvalidInput(_("요청 형식이 올바르지 않아요.")) from error
        if not isinstance(data, dict):
            raise InvalidInput(_("요청 형식이 올바르지 않아요."))
        return data


@dataclass
class Response:
    status: int = 200
    body: bytes = b""
    content_type: str = "application/json; charset=utf-8"
    headers: dict[str, str] = field(default_factory=dict)
    file: Path | None = None
    stream: Callable[[Callable[[dict], None]], None] | None = None

    @classmethod
    def json(cls, data: Any, status: int = 200) -> "Response":
        return cls(status, json.dumps(data, ensure_ascii=False).encode("utf-8"))

    @classmethod
    def error(cls, error: ReaderError, lang: str = "ko") -> "Response":
        message = translate(error.args[0], lang) if error.args else ""
        return cls.json({"error": {"code": error.code, "message": message}}, error.status)

    @classmethod
    def send_file(cls, path: Path, content_type: str, headers: dict[str, str] | None = None) -> "Response":
        return cls(200, b"", content_type, dict(headers or {}), path)


Handler = Callable[[Request], Response]


class Router:
    """Tiny path router: '/api/documents/{id}' style patterns."""

    def __init__(self) -> None:
        self._routes: list[tuple[str, re.Pattern[str], Handler]] = []

    def add(self, method: str, pattern: str, handler: Handler) -> None:
        regex = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[A-Za-z0-9_-]+)", pattern) + "$")
        self._routes.append((method.upper(), regex, handler))

    def resolve(self, method: str, path: str) -> tuple[Handler, dict[str, str]]:
        allowed = False
        for route_method, regex, handler in self._routes:
            found = regex.match(path)
            if found:
                if route_method == method:
                    return handler, found.groupdict()
                allowed = True
        if allowed:
            raise MethodNotAllowed(_("허용되지 않은 요청이에요."))
        raise NotFound(_("없는 주소예요."))

