"""Windows adapters. The pure parts run everywhere; tests that call Windows APIs run only on Windows."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest import mock

from paperdesk.domain.errors import InvalidInput, ProviderFailed
from paperdesk.providers import cli
from paperdesk.providers.cli import direct
from paperdesk.providers.codex_cli import CodexCliProvider
from paperdesk.providers.transport import SubprocessRunner, unsafe_for_cmd
from .helpers import build_app, make_pdf
from .test_providers import context, found

WINDOWS = os.name == 'nt'
NATIVE_SHIM = '@ECHO off\r\nGOTO start\r\n:start\r\nSETLOCAL\r\nCALL :find_dp0\r\n"%dp0%\\node_modules\\@anthropic-ai\\claude-code\\bin\\claude.exe"   %*\r\n'
NODE_SHIM = '@ECHO off\r\nSETLOCAL\r\n"%_prog%"  "%dp0%\\node_modules\\@openai\\codex\\bin\\codex.js" %*\r\n'


class CliLocationTests(unittest.TestCase):
    def test_npm_shim_of_a_native_cli_runs_its_exe_directly(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            exe = root/'node_modules'/'@anthropic-ai'/'claude-code'/'bin'/'claude.exe'
            exe.parent.mkdir(parents=True)
            exe.touch()
            (root/'claude.cmd').write_text(NATIVE_SHIM, encoding='utf-8')
            (root/'codex.cmd').write_text(NODE_SHIM, encoding='utf-8')
            self.assertEqual(direct(str(root/'claude.cmd')), str(exe))
            # A shim that starts node.exe with a script keeps the .cmd (and its argument check).
            self.assertEqual(direct(str(root/'codex.cmd')), str(root/'codex.cmd'))
            exe.unlink()
            self.assertEqual(direct(str(root/'claude.cmd')), str(root/'claude.cmd'))
            self.assertEqual(direct(str(root/'missing.cmd')), str(root/'missing.cmd'))
            self.assertEqual(direct('/usr/local/bin/claude'), '/usr/local/bin/claude')

    def test_versioned_install_folders_newest_first(self):
        with tempfile.TemporaryDirectory() as folder:
            older, newer = Path(folder)/'bin'/'aaa', Path(folder)/'bin'/'zzz'
            for index, path in enumerate((newer, older)):
                path.mkdir(parents=True)
                os.utime(path, (time.time() - 100*index,)*2)
            (Path(folder)/'bin'/'file').touch()
            self.assertEqual(cli._folders([str(Path(folder)/'bin'/'*'), '~/plain']),
                             [newer, older, Path('~/plain').expanduser()])
            self.assertEqual(cli._folders(['relative/*']), [])

    def test_windows_looks_for_exe_and_cmd_but_not_the_shell_script(self):
        with mock.patch.object(cli, 'WINDOWS', True):
            self.assertEqual(cli._names('codex'), ('codex.exe', 'codex.cmd'))
            with tempfile.TemporaryDirectory() as folder:
                for name in ('codex', 'codex.cmd'):
                    (Path(folder)/name).write_text(NODE_SHIM, encoding='utf-8')
                    os.chmod(Path(folder)/name, 0o700)
                provider = CodexCliProvider(context('codex-cli'), which=found(None))
                provider.extra_dirs = ()
                with mock.patch.object(cli, 'COMMON_BIN_DIRS', (folder,)):
                    self.assertEqual(provider.locate(), str(Path(folder)/'codex.cmd'))
        with mock.patch.object(cli, 'WINDOWS', False):
            self.assertEqual(cli._names('codex'), ('codex',))

    def test_cmd_arguments_that_cmd_exe_would_reinterpret_are_refused(self):
        self.assertTrue(unsafe_for_cmd(['C:/npm/claude.CMD', '-p', '--system-prompt', 'line one\nline two']))
        self.assertTrue(unsafe_for_cmd(['claude.bat', 'a & calc']))
        self.assertFalse(unsafe_for_cmd(['claude.cmd', 'exec', '--model', 'gpt-6-luna']))
        self.assertFalse(unsafe_for_cmd(['claude.exe', 'line one\nline two & more']))


class ProcessTests(unittest.TestCase):
    def test_cli_output_is_read_as_utf8_whatever_the_system_code_page(self):
        script = "import sys; sys.stdout.buffer.write('번역 ✓ — 完了'.encode('utf-8')); sys.stdin.read()"
        with tempfile.TemporaryDirectory() as folder:
            result = SubprocessRunner().run([sys.executable, '-c', script], input_text='질문', cwd=Path(folder), timeout=30)
        self.assertEqual((result.returncode, result.stdout), (0, '번역 ✓ — 完了'))

    @unittest.skipUnless(WINDOWS, 'Windows process tree')
    def test_timeout_stops_the_cli_and_what_it_started(self):
        child = "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); open('child.pid','w').write(str(p.pid)); time.sleep(60)"
        with tempfile.TemporaryDirectory() as folder:
            started = time.monotonic()
            with self.assertRaises(ProviderFailed):
                SubprocessRunner().run([sys.executable, '-c', child], input_text='', cwd=Path(folder), timeout=3)
            self.assertLess(time.monotonic() - started, 20)
            pid = int((Path(folder)/'child.pid').read_text())
            deadline = time.monotonic() + 10
            while _alive(pid) and time.monotonic() < deadline:
                time.sleep(.2)
            self.assertFalse(_alive(pid))


class WebViewStorageTests(unittest.TestCase):
    def test_windows_keeps_the_web_engine_files_beside_the_library_not_inside_it(self):
        from paperdesk.platforms import LinuxPlatform, MacPlatform, WindowsPlatform
        library = Path('Users')/'me'/'AppData'/'Local'/'Paperdesk'
        self.assertEqual(WindowsPlatform().webview_storage(library), library.with_name('Paperdesk-webview'))
        # WKWebView keeps nothing there and macOS has no folder-swap problem, so its path is unchanged.
        self.assertEqual(MacPlatform().webview_storage(library), library/'webview')
        self.assertEqual(LinuxPlatform().webview_storage(library), library/'webview')


class RelaunchTests(unittest.TestCase):
    def test_restart_after_an_update_waits_until_the_library_lock_is_released(self):
        # On Windows the updated version starts as a new process; if this one still held the lock,
        # the new one would exit as 'already running' and, under pythonw, the app would silently not open.
        from paperdesk import cli as commands
        from paperdesk.infrastructure.instance import library_lock
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)/'library'
            started = []

            def relaunch():
                with library_lock(home):
                    started.append(True)
                return 0

            with mock.patch.dict(os.environ, {'PAPERDESK_HOME': str(home)}), \
                    mock.patch.object(commands, 'command_open', return_value=commands.RELAUNCH), \
                    mock.patch.object(commands, '_relaunch', side_effect=relaunch):
                self.assertEqual(commands.main(['open']), 0)
            self.assertEqual(started, [True])


class SecondLaunchTests(unittest.TestCase):
    def open_while_running(self, shown):
        from paperdesk import cli as commands
        from paperdesk.infrastructure.instance import library_lock
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)/'library'
            with mock.patch.dict(os.environ, {'PAPERDESK_HOME': str(home)}), library_lock(home), \
                    mock.patch('paperdesk.desktop.show_running_window', return_value=shown) as show, \
                    mock.patch.object(commands, 'command_open') as command:
                result = commands.main(['open'])
            command.assert_not_called()
            self.assertEqual(Path(show.call_args.args[0]).resolve(), home.resolve())
            return result

    def test_opening_the_app_again_brings_the_open_window_forward(self):
        with mock.patch('sys.stderr') as errors:
            self.assertEqual(self.open_while_running(True), 0)
        errors.write.assert_not_called()

    def test_without_a_window_to_show_it_says_the_app_is_running(self):
        with mock.patch('sys.stderr') as errors:
            self.assertEqual(self.open_while_running(False), 1)
        self.assertIn('이미 실행 중', ''.join(call.args[0] for call in errors.write.call_args_list))

    @unittest.skipUnless(WINDOWS, 'pythonw message box')
    def test_pythonw_shows_the_message_it_cannot_print(self):
        # The Start menu shortcut runs pythonw, which has no console: the message would otherwise go nowhere.
        with mock.patch('sys.stderr', None), mock.patch('paperdesk.desktop.windows_message') as message:
            self.assertEqual(self.open_while_running(False), 1)
        self.assertIn('이미 실행 중', message.call_args.args[0])

    @unittest.skipUnless(WINDOWS, 'Win32 windows')
    def test_a_window_is_found_by_the_library_it_has_open(self):
        import ctypes
        import types
        from ctypes import wintypes
        from paperdesk.desktop import _windows_library_window, _windows_mark_library
        user32 = ctypes.WinDLL('user32')
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.CreateWindowExW.argtypes = (wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                           wintypes.HINSTANCE, wintypes.LPVOID)
        user32.DestroyWindow.argtypes = (wintypes.HWND,)
        hwnd = user32.CreateWindowExW(0, 'STATIC', 'PaperDesk', 0, 0, 0, 10, 10, None, None, None, None)  # never shown
        self.addCleanup(user32.DestroyWindow, hwnd)
        with tempfile.TemporaryDirectory() as folder:
            library, other = Path(folder)/'Paperdesk', Path(folder)/'Other'
            self.assertIsNone(_windows_library_window(library))
            _windows_mark_library(types.SimpleNamespace(native=types.SimpleNamespace(Handle=types.SimpleNamespace(ToInt64=lambda: hwnd))), library)
            self.assertEqual(_windows_library_window(library), hwnd)
            self.assertEqual(_windows_library_window(Path(folder.upper())/'sub'/'..'/'PAPERDESK'), hwnd)  # same folder
            self.assertIsNone(_windows_library_window(other))


class Utf8StdioTests(unittest.TestCase):
    def test_mcp_speaks_utf8_over_pipes_whatever_the_system_code_page(self):
        # Korean Windows pipes default to cp949, which has neither these characters nor UTF-8 framing.
        app, tmp = build_app()
        self.addCleanup(tmp.cleanup)
        doc, _ = app.library.import_pdf('paper.pdf', make_pdf(['Body text']))
        title = '주의 집중 📄 — Attention ✓'
        app.library.rename(doc.id, title)
        env = {k: v for k, v in os.environ.items() if k not in ('PYTHONUTF8', 'PYTHONIOENCODING')}
        env.update(PAPERDESK_HOME=str(app.paths.root), PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
        messages = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18', 'capabilities': {},
                                                                           'clientInfo': {'name': '클라이언트 ✓', 'version': '1'}}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'search_papers', 'arguments': {'query': '집중 📄'}}},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'list_papers', 'arguments': {}}},
        ]
        done = subprocess.run([sys.executable, '-m', 'paperdesk', 'mcp'], capture_output=True, env=env, timeout=120,
                              input=''.join(json.dumps(m, ensure_ascii=False) + '\n' for m in messages).encode('utf-8'))
        replies = {r.get('id'): r for r in (json.loads(line) for line in done.stdout.decode('utf-8').splitlines() if line.strip())}
        self.assertEqual(sorted(k for k in replies if k), [1, 2, 3], done.stderr.decode('utf-8', 'replace')[-800:])
        self.assertIn(title, replies[3]['result']['content'][0]['text'])


def _alive(pid):
    import ctypes
    kernel32 = ctypes.WinDLL('kernel32')
    handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(handle, 0) == 0x102  # WAIT_TIMEOUT
    finally:
        kernel32.CloseHandle(handle)


class PortableBackupTests(unittest.TestCase):
    def test_cli_paths_from_another_computer_fall_back_to_discovery_on_restore(self):
        app, tmp = build_app()
        self.addCleanup(tmp.cleanup)
        app.library.import_pdf('paper.pdf', make_pdf(['Body']))
        present = app.paths.root/'tools'/('codex.exe' if WINDOWS else 'codex')
        present.parent.mkdir()
        present.touch()
        app.paths.settings_file.write_text(json.dumps({'provider_options': {
            'codex-cli': {'binary': str(present), 'model': 'gpt-6-luna'},
            'claude-code': {'binary': '/opt/homebrew/bin/claude' if WINDOWS else 'C:\\Users\\me\\.local\\bin\\claude.exe'}}}),
            encoding='utf-8')
        checked = app.archives.prepare(app.archives.export())
        stage = app.paths.root/'restore-staging'/checked['token']
        options = json.loads((stage/'settings.json').read_text(encoding='utf-8'))['provider_options']
        self.assertEqual(options['codex-cli'], {'binary': str(present), 'model': 'gpt-6-luna'})
        self.assertNotIn('binary', options.get('claude-code', {}))

    def test_backup_settings_keep_non_ascii_text_on_any_code_page(self):
        app, tmp = build_app()
        self.addCleanup(tmp.cleanup)
        app.settings.update_general(target_language='Korean')
        folder = app.paths.root/'도구 폴더'
        folder.mkdir()
        (folder/'codex').touch()
        app.paths.settings_file.write_text(json.dumps({'target_language': 'Korean', 'provider_options': {
            'codex-cli': {'binary': str(folder/'codex'), 'model': '모델 📄'}}}, ensure_ascii=False), encoding='utf-8')
        archive = app.archives.export()
        with zipfile.ZipFile(archive) as z:
            settings = json.loads(z.read('settings.json').decode('utf-8'))
        self.assertEqual(settings['provider_options']['codex-cli']['model'], '모델 📄')
        checked = app.archives.prepare(archive)
        staged = json.loads((app.paths.root/'restore-staging'/checked['token']/'settings.json').read_text(encoding='utf-8'))
        self.assertEqual(staged['provider_options']['codex-cli']['binary'], str(folder/'codex'))


class InstalledLayoutTests(unittest.TestCase):
    """Commands a Windows source install hands to other programs."""

    def test_source_install_mcp_command_uses_the_signed_console_python(self):
        from paperdesk import cli as commands
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.multiple(sys, create=True, frozen=False, platform='win32', executable=str(Path(folder)/'pythonw.exe')):
            command, arguments = commands._launcher()
        self.assertEqual((Path(command).name, arguments), ('python.exe', ['-m', 'paperdesk', 'mcp']))



@unittest.skipUnless(WINDOWS, 'Windows Credential Manager')
class CredentialManagerTests(unittest.TestCase):
    def test_round_trip_unicode_overwrite_and_delete(self):
        from paperdesk.infrastructure.secrets import CredentialManagerSecretStore
        store = CredentialManagerSecretStore('PaperdeskTest-' + uuid.uuid4().hex)
        self.addCleanup(store.delete, 'api_key')
        self.assertIsNone(store.get('api_key'))
        store.set('api_key', 'sk-첫번째')
        store.set('api_key', 'sk-두번째 ✓')
        self.assertEqual(store.get('api_key'), 'sk-두번째 ✓')
        store.delete('api_key')
        self.assertIsNone(store.get('api_key'))
        store.delete('api_key')  # deleting a missing key is not an error


@unittest.skipUnless(WINDOWS, 'Windows platform services')
class WindowsPlatformTests(unittest.TestCase):
    def test_first_run_language_comes_from_windows_display_languages(self):
        from paperdesk.config import LANGUAGES, language_name
        from paperdesk.platforms import WindowsPlatform, current_platform
        platform = current_platform()
        self.assertIsInstance(platform, WindowsPlatform)
        codes = platform.ui_languages()
        self.assertTrue(codes)
        expected = next((language_name(code) for code in codes if language_name(code)), None)
        self.assertEqual(platform.preferred_language(), expected or 'English')
        self.assertIn(platform.preferred_language(), LANGUAGES.values())
        self.assertEqual(platform.data_dir().parent, Path(os.environ['LOCALAPPDATA']))

    def test_library_lock_is_exclusive_between_processes(self):
        import subprocess
        from paperdesk.infrastructure.instance import library_access, library_lock
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'library'
            probe = ("import sys; from pathlib import Path; from paperdesk.infrastructure.instance import library_access\n"
                     "try:\n    with library_access(Path(sys.argv[1]), exclusive=sys.argv[2]=='1'): print('ok')\n"
                     "except Exception as error: print(type(error).__name__)")
            def other(exclusive):
                env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
                return subprocess.run([sys.executable, '-c', probe, str(root), '1' if exclusive else '0'],
                                      capture_output=True, text=True, encoding='utf-8', env=env, timeout=60).stdout.strip()
            with library_access(root):
                self.assertEqual(other(False), 'ok')
                self.assertEqual(other(True), 'InvalidInput')
            self.assertEqual(other(True), 'ok')
            with library_lock(root):
                with self.assertRaises(InvalidInput):
                    with library_lock(root):
                        pass


if __name__ == '__main__':
    unittest.main()
