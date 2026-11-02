from __future__ import annotations

import argparse
import os
import json
import logging
import shutil
import sys
import threading
import urllib.request
from contextlib import ExitStack, contextmanager
from pathlib import Path

from . import APP_ID, APP_NAME, __version__
from .app import Application
from .i18n import from_header, translate

DEFAULT_PORT = 47615


@contextmanager
def _application(*, restore: bool = False):
    from .config import AppPaths
    from .infrastructure.instance import downgrade_lock, library_access
    paths = AppPaths.default()
    root = paths.root.resolve()
    exclusive = not paths.database.exists() or (restore and (
        (root/'pending-restore.json').exists() or root.with_name('.'+root.name+'-restore.json').exists()))
    with library_access(root, exclusive=exclusive) as stream:
        app = Application.build(paths=paths, restore=restore)
        if exclusive:
            downgrade_lock(stream)
        try:
            yield app
        finally:
            app.analysis.close()
            app.jobs.close()


def _running_instance(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.5) as response:
            return json.load(response).get("app") == APP_ID
    except (OSError, ValueError):
        return False


def command_open(args: argparse.Namespace) -> int:
    from .desktop import choose_shell
    from .web.server import create_server

    from .infrastructure.source_update import SourceInstall, SourceUpdates

    if _running_instance(args.port):
        from .domain.errors import InvalidInput
        from .i18n import _
        raise InvalidInput(_("이 서재를 사용하는 앱이 이미 실행 중이에요. 먼저 앱을 종료해 주세요."))
    # Source installs: commits fetched during the last run (automatically or from Settings) are applied now,
    # before any window or server exists. The automatic setting only controls fetching.
    source = SourceInstall.current()
    if source is not None and source.git is not None and source.apply():
        return RELAUNCH  # main() starts the new version after it releases the library lock
    with _application(restore=True) as app:
        if source is not None:
            app.updates.attach(SourceUpdates(source))
            if source.auto_update:
                threading.Thread(target=source.fetch, name="paperdesk-source-fetch", daemon=True).start()
        shell = choose_shell(args.shell, app.platform, app.platform.webview_storage(app.paths.root), app.preferences,
                             app.paths.root)
        restart = _restartable(app.updates, shell)
        try:
            server = create_server(app, "127.0.0.1", args.port)
        except OSError:
            server = create_server(app, "127.0.0.1", 0)  # port taken by something else
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print(f"{APP_NAME} {server.url} ({shell.name})", flush=True)
        try:
            shell.run(server.url)
            if not shell.blocks:
                print("Press Ctrl+C to quit", flush=True)
                thread.join()
        except KeyboardInterrupt:
            pass
        finally:
            server.shutdown()
            server.server_close()
        return RELAUNCH if restart.is_set() else 0


def _restartable(updates, shell) -> threading.Event:
    """Settings → "Restart now": close the window, and main() starts the app again, which applies the update."""
    restart = threading.Event()
    if hasattr(shell, "close"):  # only the app window; the browser shell has nothing to close
        def restart_now() -> None:
            restart.set()
            threading.Timer(0.3, shell.close).start()  # let the reply reach the page first
        updates.allow_restart(restart_now)
    return restart


RELAUNCH = -1  # command_open: start again (an update was applied, or Settings asked) once the library lock is released


def _relaunch() -> int:
    """Start the updated version. Windows has no in-place exec, so a new process takes over and this one ends.
    Called only after main() released the library lock: a child that found it still held would exit as 'already running'."""
    command = [sys.executable, "-m", "paperdesk", *sys.argv[1:]]
    if os.name == "nt":
        import subprocess
        subprocess.Popen(command, close_fds=True)
        return 0
    os.execv(sys.executable, command)


def command_serve(args: argparse.Namespace) -> int:
    from .web.server import create_server

    with _application(restore=True) as app:
        server = create_server(app, args.host, args.port)
        print(f"{APP_NAME} {server.url}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return 0


def command_mcp(args: argparse.Namespace) -> int:
    from .mcp import StdioMcpServer

    with _application() as app:
        StdioMcpServer.for_app(app).serve()
    return 0


def _launcher() -> tuple[str, list[str]]:
    if sys.platform == "win32":
        # Source install: the signed python.exe (pythonw.exe has no stdio; pip's paperdesk.exe shim is unsigned).
        return str(Path(sys.executable).with_name("python.exe")), ["-m", APP_ID, "mcp"]
    script = shutil.which(APP_ID)
    if script:
        return str(Path(script).resolve()), ["mcp"]
    return sys.executable, ["-m", "paperdesk", "mcp"]


def command_mcp_config(args: argparse.Namespace) -> int:
    command, arguments = _launcher()
    if args.client == "claude":
        print("# Claude Desktop: Settings > Developer > Edit Config (claude_desktop_config.json)")
        print(json.dumps({"mcpServers": {APP_ID: {"command": command, "args": arguments}}}, indent=2))
    else:
        print("# Codex: ~/.codex/config.toml")
        print(f"[mcp_servers.{APP_ID}]\ncommand = {json.dumps(command)}\nargs = {json.dumps(arguments)}")
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    from .desktop import NativeWindowShell

    with _application() as app:
        lang = from_header(os.environ.get("LC_ALL") or os.environ.get("LANG") or "en")
        report = {
            "version": __version__,
            "python": sys.version.split()[0],
            "platform": app.platform.name,
            "platform_supported": app.platform.supported,
            "data_dir": str(app.paths.root),
            "native_window": NativeWindowShell.is_available(),
            "active_provider": app.settings.load().provider or None,
            "providers": {p["id"]: {"available": p["available"], "detail": translate(p["detail"], lang)} for p in app.settings.view()["providers"]},
        }
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            for key, value in report.items():
                if key != "providers":
                    print(f"{key:18} {value}")
            for pid, state in report["providers"].items():
                print(f"  {'✓' if state['available'] else '·'} {pid:18} {state['detail']}")
        return 0


def command_backup(args: argparse.Namespace) -> int:
    from .config import AppPaths
    from .infrastructure.archives import LibraryArchives, apply_pending_restore
    from .infrastructure.sqlite import Database
    paths = AppPaths.default().ensure()
    archive = LibraryArchives(paths)
    if args.action == 'export':
        Database(paths.database)
        source = archive.export()
        destination = Path(args.path).expanduser().resolve()
        if destination.exists():
            raise ValueError('Refusing to overwrite an existing backup')
        shutil.copy2(source, destination)
        print(destination)
    elif args.action == 'inspect':
        print(json.dumps(archive.prepare(Path(args.path).expanduser().resolve()), indent=2))
    else:
        if not args.replace_library:
            raise ValueError('Inspect the backup first; restoring requires --replace-library. Close the app before restoring.')
        checked = archive.prepare(Path(args.path).expanduser().resolve())
        archive.schedule(checked['token'])
        try:
            apply_pending_restore(paths)
        except PermissionError as error:
            # Usually Windows: a file in the library folder is open in another program, so the folder can't be moved.
            from .domain.errors import InvalidInput
            root = paths.root.resolve()
            if root.with_name('.'+root.name+'-restore.json').exists():
                raise InvalidInput('The restore did not finish: the library folder could not be moved. Close PaperDesk and any '
                                   'program that may be using files in it, then run the same command again.') from error
            (root/'pending-restore.json').unlink(missing_ok=True)  # nothing changed, so the next launch must not restore either
            raise InvalidInput(f'Restore failed and your current library was not changed: the library folder could not be moved '
                               f'({root}). Close PaperDesk and any program that may be using files in that folder (File Explorer, '
                               'an editor, sync or antivirus software), then run the restore again.') from error
        print('Restored. Previous library retained in the adjacent .before-restore directory. Recheck AI connections.')
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=APP_ID, description=f"{APP_NAME}: AI paper reader")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command")

    open_cmd = sub.add_parser("open", help="open the app window (default)")
    open_cmd.add_argument("--port", type=int, default=DEFAULT_PORT)
    open_cmd.add_argument("--shell", choices=("auto", "native", "browser"), default="auto")
    open_cmd.set_defaults(func=command_open)

    serve = sub.add_parser("serve", help="run the local server only (development)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.set_defaults(func=command_serve)

    sub.add_parser("mcp", help="MCP server for Claude Desktop and Codex (stdio)").set_defaults(func=command_mcp)

    config = sub.add_parser("mcp-config", help="print MCP client configuration")
    config.add_argument("client", choices=("claude", "codex"))
    config.set_defaults(func=command_mcp_config)

    doctor = sub.add_parser("doctor", help="check the installation and AI connections")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=command_doctor)
    backup = sub.add_parser('backup', help='export, inspect or restore a complete library (close the app first)')
    backup.add_argument('action', choices=('export', 'inspect', 'restore'))
    backup.add_argument('path')
    backup.add_argument('--replace-library', action='store_true')
    backup.set_defaults(func=command_backup)
    return parser


def _utf8_stdio() -> None:
    """MCP messages and command output are UTF-8 everywhere. Windows pipes otherwise use the ANSI code page
    (cp949 on Korean Windows), which garbles titles for MCP clients and cannot encode many characters."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):  # None in the windowed Paperdesk.exe
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING, stream=sys.stderr)
    if not getattr(args, "func", None):
        args = parser.parse_args(["open", *(argv if argv is not None else sys.argv[1:])])
    from .config import AppPaths
    from .infrastructure.instance import LibraryInUse, library_access, library_lock
    from .domain.errors import ReaderError
    try:
        with ExitStack() as stack:
            root = AppPaths.default().root
            if args.command in ('open', 'serve', 'backup'):
                stack.enter_context(library_lock(root))
            if args.command == 'backup':
                stack.enter_context(library_access(root, exclusive=args.action == 'restore'))
            result = args.func(args)
    except ReaderError as error:
        if isinstance(error, LibraryInUse) and args.command == 'open':
            from .desktop import show_running_window
            if show_running_window(root):
                return 0  # opened again: the window already open comes to the front
        if sys.stderr is None and os.name == 'nt':  # pythonw, which the Start menu shortcut runs, has no console
            from .desktop import windows_message
            windows_message(str(error))
        else:
            print(str(error), file=sys.stderr)
        return 1
    return _relaunch() if result == RELAUNCH else result
