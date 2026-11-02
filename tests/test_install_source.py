import os
import plistlib
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .test_updates import ROOT, script


class SourceInstallTests(unittest.TestCase):
    def setUp(self):
        self.installer = script('install_source')

    def test_each_system_installs_its_window_lock_and_the_shared_docling_versions(self):
        with mock.patch.multiple(self.installer, WINDOWS=True, MACOS=False):
            self.assertEqual([p.name for p in self.installer.locks()], ['windows-app.lock', 'docling-windows.lock'])
            self.assertEqual(self.installer.environment_python(Path('env'), window=True), Path('env/Scripts/pythonw.exe'))
        with mock.patch.multiple(self.installer, WINDOWS=False, MACOS=True):
            self.assertEqual([p.name for p in self.installer.locks()], ['macos-app.lock', 'docling-macos.lock'])
            self.assertEqual(self.installer.environment_python(Path('env')), Path('env/bin/python'))
        for lock in ('windows-app.lock', 'macos-app.lock'):
            pins = (ROOT/'requirements'/lock).read_text(encoding='utf-8')
            self.assertIn('pywebview==6.2.1', pins)
        # The Windows Docling lock differs from macOS only by Windows-only packages.
        mac = set((ROOT/'requirements/docling-macos.lock').read_text(encoding='utf-8').split())
        windows = set((ROOT/'requirements/docling-windows.lock').read_text(encoding='utf-8').split())
        self.assertEqual({line.split('==')[0] for line in windows - mac}, {'colorama', 'pywin32'})
        self.assertEqual(mac - windows, set())

    @unittest.skipUnless(os.name == 'nt', 'Windows Start menu shortcut')
    def test_windows_shortcut_shares_the_apps_taskbar_id_and_replaces_the_earlier_one_only_once_saved(self):
        import subprocess
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(os.environ, {'APPDATA': str(Path(folder)/'Roaming')}):
            prefix = Path(folder)/"O'Brien"/'Paperdesk-beta'
            prefix.mkdir(parents=True)
            earlier = self.installer.shortcut_path('Paperdesk (beta).lnk')
            earlier.parent.mkdir(parents=True)
            earlier.write_bytes(b'0.2.0 shortcut')
            with mock.patch.object(self.installer, 'write_shortcut', side_effect=OSError('not allowed')), self.assertRaises(OSError):
                self.installer.create_shortcut(prefix, prefix/'venv')
            self.assertTrue(earlier.exists(), 'the only shortcut that opens the app was removed')
            link = self.installer.create_shortcut(prefix, prefix/'venv')
            self.assertEqual(link.name, 'PaperDesk.lnk')
            self.assertFalse(earlier.exists())
            q = self.installer.quote
            read = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', '; '.join([
                f'$s = (New-Object -ComObject WScript.Shell).CreateShortcut({q(link)})',
                f'$f = (New-Object -ComObject Shell.Application).NameSpace({q(link.parent)}).ParseName({q(link.name)})',
                "$s.TargetPath; $s.Arguments; $s.IconLocation; $f.ExtendedProperty('System.AppUserModel.ID')"])],
                capture_output=True, text=True, encoding='utf-8', timeout=60).stdout.splitlines()
            self.assertEqual(read, [str(prefix/'venv'/'Scripts'/'pythonw.exe'), '-m paperdesk', f"{prefix/'Paperdesk.ico'},0",
                                    'org.paperdesk.Paperdesk.source'])  # what desktop._windows_app_identity sets

    def test_powershell_literals_escape_quotes(self):
        self.assertEqual(self.installer.quote("C:/Users/O'Brien/Paperdesk"), "'C:/Users/O''Brien/Paperdesk'")

    def test_only_environments_made_for_python_312_are_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            environment = Path(folder)
            python = self.installer.environment_python(environment)
            python.parent.mkdir(parents=True)
            python.touch()
            (environment/'pyvenv.cfg').write_text('home = x\nversion = 3.12.10\n', encoding='utf-8')
            self.assertTrue(self.installer.matching_environment(environment))
            (environment/'pyvenv.cfg').write_text('home = x\nversion_info = 3.13.2\n', encoding='utf-8')
            self.assertFalse(self.installer.matching_environment(environment))
            self.assertFalse(self.installer.matching_environment(environment/'missing'))

    @unittest.skipIf(os.name == 'nt', 'macOS app bundle with POSIX paths')
    def test_macos_app_opens_the_environment_and_only_its_own_copy_is_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            system, personal = Path(folder)/'Applications', Path(folder)/'home-Applications'
            system.mkdir()
            with mock.patch.object(self.installer, 'applications_folders', return_value=[system, personal]):
                # 0.2.0 and earlier named it "Paperdesk (beta)"; a reinstall replaces that copy with the new name.
                earlier = system/'Paperdesk (beta).app'
                (earlier/'Contents').mkdir(parents=True)
                (earlier/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'org.paperdesk.Paperdesk.source'}))
                app = self.installer.create_app_bundle(Path('/opt/Paper desk/venv'))
                self.assertEqual(app, system/'PaperDesk.app')
                self.assertFalse(earlier.exists())
                info = plistlib.loads((app/'Contents/Info.plist').read_bytes())
                self.assertEqual((info['CFBundleExecutable'], info['CFBundleIdentifier']), ('PaperDesk', 'org.paperdesk.Paperdesk.source'))
                self.assertTrue((app/'Contents/Resources'/info['CFBundleIconFile']).is_file())
                launcher = app/'Contents/MacOS/PaperDesk'
                self.assertEqual(launcher.read_text(encoding='utf-8'), "#!/bin/sh\nexec '/opt/Paper desk/venv/bin/python' -m paperdesk\n")
                self.assertTrue(os.access(launcher, os.X_OK))
                self.assertEqual(self.installer.create_app_bundle(Path('/opt/Paper desk/venv')), app)  # reinstalling replaces it
                self.installer.remove_app_bundles()
                self.assertFalse(app.exists())
                # Someone else's app with the same name is never replaced or removed.
                (app/'Contents').mkdir(parents=True)
                (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'example.other'}))
                with mock.patch('sys.stderr'):
                    self.assertIsNone(self.installer.create_app_bundle(Path('venv')))
                self.installer.remove_app_bundles()
                self.assertTrue(app.exists())

    def test_uninstall_from_the_installs_own_copy_reads_the_library_path_before_removing_it(self):
        # INSTALL.md lets the downloaded folder go; uninstalling then runs prefix/source/scripts/install_source.py,
        # whose code (needed to find the library path) disappears with the prefix.
        with tempfile.TemporaryDirectory() as folder, mock.patch.multiple(self.installer, WINDOWS=False, MACOS=False):
            prefix = Path(folder)/'Paperdesk-beta'
            (prefix/'source'/'src').mkdir(parents=True)
            (prefix/self.installer.MARKER).touch()
            def library():
                self.assertTrue((prefix/'source').exists(), 'the library path was looked up after the code was removed')
                return Path('library')
            with mock.patch.object(self.installer, 'data_folder', side_effect=library), mock.patch('builtins.print') as shown:
                self.installer.uninstall(prefix)
            self.assertFalse(prefix.exists())
            self.assertIn('library', shown.call_args.args[0])

    def test_uninstall_never_removes_a_folder_it_did_not_create(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.multiple(self.installer, WINDOWS=False, MACOS=False), \
                mock.patch.object(self.installer, 'data_folder', return_value=Path('library')):
            mine, other = Path(folder)/'mine', Path(folder)/'other'
            for path in (mine, other):
                (path/'venv').mkdir(parents=True)
            (mine/self.installer.MARKER).touch()
            with self.assertRaises(SystemExit):
                self.installer.uninstall(other)
            self.assertTrue(other.exists())
            # Git object files are read-only; Windows refuses to delete them unless that is cleared.
            objects = mine/'source'/'.git'/'objects'/'00'
            objects.mkdir(parents=True)
            (objects/'585fb4').write_text('blob', encoding='utf-8')
            os.chmod(objects/'585fb4', stat.S_IREAD)
            (mine/'Paperdesk.ico').touch()
            os.chmod(mine/'Paperdesk.ico', stat.S_IREAD)
            with mock.patch('builtins.print'):
                self.installer.uninstall(mine)
            self.assertFalse(mine.exists())


if __name__ == '__main__':
    unittest.main()
