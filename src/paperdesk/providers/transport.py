"""Default process and HTTP adapters (stdlib only)."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
import queue
import subprocess
import tempfile
import time
import signal
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterator, Mapping

from .. import APP_ID, __version__
from ..domain.errors import ProviderFailed, ProviderUnavailable
from ..ports.ai import CommandResult, CommandRunner, HttpClient
from ..i18n import _

WINDOWS = os.name == "nt"
# cmd.exe re-parses the arguments of .cmd/.bat shims (npm installs CLIs that way); these characters could change the command.
_CMD_SPECIAL = set('"%!^&|<>()\r\n')


def _spawn_options() -> dict:
    """Run CLIs in their own process group (so stopping one also stops what it started), without a console window."""
    if WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}


def _stop(process: subprocess.Popen, force: bool = False) -> None:
    if process.poll() is not None:
        return
    try:
        if WINDOWS:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
        else:
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        pass


def unsafe_for_cmd(argv: list[str]) -> bool:
    return argv[0].lower().endswith((".cmd", ".bat")) and any(_CMD_SPECIAL & set(arg) for arg in argv[1:])


class SubprocessRunner(CommandRunner):
    def __init__(self) -> None:
        self._processes = set()
        self._lock = threading.Lock()
        self._closed = False

    def close(self) -> None:
        with self._lock:
            self._closed = True
            for process in self._processes:
                _stop(process)

    @contextmanager
    def codex_session(self, argv: list[str], cwd: Path, timeout: float):
        if unsafe_for_cmd(argv):
            raise ProviderUnavailable(_("{name}가 .cmd 실행 파일이라 안전하게 실행할 수 없어요. 설정에서 .exe 실행 파일 경로를 지정해 주세요.",
                                        name=Path(argv[0]).name))
        with self._lock:
            if self._closed:
                raise ProviderUnavailable(_("앱을 종료하는 중이에요."))
            try:
                process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                           cwd=cwd, text=True, encoding='utf-8', errors='replace', **_spawn_options())
            except OSError as error:
                raise ProviderUnavailable(_("실행하지 못했어요: {error}", error=str(error))) from error
            self._processes.add(process)
        lines = queue.Queue()
        def read():
            try:
                for line in process.stdout:
                    lines.put(line)
            finally:
                lines.put(None)
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        deadline = time.monotonic() + timeout

        def send(value):
            try:
                process.stdin.write(json.dumps(value) + '\n')
                process.stdin.flush()
            except OSError as error:
                raise ProviderFailed(_("응답이 끝나기 전에 연결이 끊겼어요.")) from error

        def receive():
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise queue.Empty
                line = lines.get(timeout=remaining)
            except queue.Empty as error:
                raise ProviderFailed(_("{seconds}초 안에 응답이 오지 않았어요.", seconds=f"{timeout:.0f}")) from error
            if line is None:
                raise ProviderFailed(_("응답이 끝나기 전에 연결이 끊겼어요."))
            return json.loads(line)

        try:
            send({'id': 1, 'method': 'initialize', 'params': {'clientInfo': {'name': 'paperdesk', 'version': __version__}}})
            reply = receive()
            while reply.get('id') != 1:
                reply = receive()
            if 'error' in reply:
                raise ProviderFailed(_("서버 응답 형식을 이해하지 못했어요."))
            send({'method': 'initialized', 'params': {}})
            yield send, receive
        finally:
            _stop(process)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                _stop(process, force=True)
                process.wait()
            reader.join(timeout=1)
            for stream in (process.stdin, process.stdout):
                try:
                    stream.close()
                except OSError:
                    pass
            with self._lock:
                self._processes.discard(process)

    def codex_models(self, executable: str) -> list[str]:
        with tempfile.TemporaryDirectory(prefix='paperdesk-models-') as folder:
            try:
                with self.codex_session([executable, "app-server", "--stdio"], Path(folder), 15) as (send, receive):
                    send({'id': 2, 'method': 'model/list', 'params': {'includeHidden': False}})
                    while True:
                        value = receive()
                        if value.get('id') == 2:
                            return [str(m['model']) for m in value.get('result', {}).get('data', [])
                                    if m.get('model') and not m.get('hidden', False)]
            except (ProviderFailed, ProviderUnavailable, OSError, ValueError):
                return []

    def run(self, argv: list[str], *, input_text: str, cwd: Path, timeout: float) -> CommandResult:
        process = None
        try:
            with self._lock:
                if self._closed:
                    raise ProviderUnavailable(_("앱을 종료하는 중이에요."))
                if unsafe_for_cmd(argv):
                    raise ProviderUnavailable(_("{name}가 .cmd 실행 파일이라 안전하게 실행할 수 없어요. 설정에서 .exe 실행 파일 경로를 지정해 주세요.",
                                                name=Path(argv[0]).name))
                process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           text=True, encoding='utf-8', errors='replace', cwd=cwd,
                                           env=dict(os.environ, NO_COLOR='1'), **_spawn_options())
                self._processes.add(process)
            stdout, stderr = process.communicate(input_text, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            _stop(process, force=True)
            process.communicate()
            raise ProviderFailed(_("{seconds}초 안에 응답이 오지 않았어요.", seconds=f"{timeout:.0f}")) from error
        except OSError as error:
            raise ProviderUnavailable(_("실행하지 못했어요: {error}", error=str(error))) from error
        finally:
            with self._lock:
                self._processes.discard(process)
        return CommandResult(process.returncode, stdout, stderr)


def _error_text(raw: str) -> str:
    try:
        data = json.loads(raw)
    except ValueError:
        return raw.strip()[:400]
    error = data.get("error", data) if isinstance(data, dict) else data
    if isinstance(error, dict):
        code = error.get("code") or error.get("type") or ""
        message = error.get("message") or json.dumps(error, ensure_ascii=False)
        return f"{code}: {message}" if code else str(message)
    return str(error)[:400]


class UrllibHttpClient(HttpClient):
    def _open(self, method: str, url: str, headers: Mapping[str, str], body: dict | None, timeout: float):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "User-Agent": f"{APP_ID}/{__version__}", **headers},
        )
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            raw = error.read(4000).decode("utf-8", "replace")
            raise ProviderFailed(f"HTTP {error.code} {_error_text(raw)}") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            reason = getattr(error, "reason", error)
            raise ProviderUnavailable(_("연결하지 못했어요: {reason}", reason=str(reason))) from error

    def get_json(self, url: str, *, headers: Mapping[str, str], timeout: float) -> Any:
        with self._open("GET", url, headers, None, timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def post_json(self, url: str, *, headers: Mapping[str, str], body: dict, timeout: float) -> Any:
        with self._open("POST", url, headers, body, timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def stream_sse(self, url: str, *, headers: Mapping[str, str], body: dict, timeout: float) -> Iterator[dict]:
        with self._open("POST", url, {"Accept": "text/event-stream", **headers}, body, timeout) as response:
            lines: list[str] = []
            for raw in response:
                line = raw.decode("utf-8").rstrip("\r\n")
                if line:
                    if line.startswith("data:"):
                        lines.append(line[5:].lstrip())
                    continue
                if lines:
                    payload = "\n".join(lines)
                    lines = []
                    if payload != "[DONE]":
                        yield json.loads(payload)
            if lines and "\n".join(lines) != "[DONE]":
                yield json.loads("\n".join(lines))

