import shutil
import subprocess
import tempfile
import unittest
import types
from unittest.mock import Mock, patch
from paperdesk.desktop import NativeWindowShell, _macos_settings_shortcut
from paperdesk.platforms import MacPlatform, WindowsPlatform
from .helpers import build_app
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class ReaderUIRegressionTests(unittest.TestCase):
    def test_windows_initial_theme_waits_for_the_native_window(self):
        window = Mock()
        webview = types.SimpleNamespace(settings={}, create_window=Mock(return_value=window), start=Mock())
        order = []
        window.events.shown.wait.side_effect = lambda timeout: order.append('shown') or True
        preferences = Mock()
        with tempfile.TemporaryDirectory() as directory, patch.dict('sys.modules', {'webview': webview}), \
                patch('paperdesk.desktop._windows_app_identity'), \
                patch('paperdesk.desktop._windows_follow_theme', side_effect=lambda *args: order.append('theme')):
            NativeWindowShell(WindowsPlatform(), Path(directory), preferences).run('http://127.0.0.1:1234/')
            webview.start.call_args.kwargs['func']()
        self.assertEqual(order, ['shown', 'theme'])
        window.events.shown.wait.assert_called_once_with(15)

    def test_windows_title_bar_follows_saved_and_changed_app_theme(self):
        from paperdesk.desktop import _windows_follow_theme
        application, tmp = build_app()
        self.addCleanup(tmp.cleanup)
        preferences = application.preferences
        preferences.update({'theme': 'light'})
        window = Mock()
        class Event:
            def __iadd__(self, callback): self.callback = callback; return self
        event = Event()
        with patch('paperdesk.desktop._windows_appearance') as appearance, patch.dict('sys.modules', {
            'Microsoft': types.SimpleNamespace(),
            'Microsoft.Win32': types.SimpleNamespace(SystemEvents=types.SimpleNamespace(UserPreferenceChanged=event)),
        }):
            _windows_follow_theme(window, preferences)
            appearance.assert_called_once_with(window, 'light')
            for theme in ('dark', 'system', 'light'):
                preferences.update({'theme': theme})
                appearance.assert_called_with(window, theme)
            count = appearance.call_count
            preferences.update({'sidebar_width': 300})
            self.assertEqual(appearance.call_count, count)
            event.callback(None, None)
            appearance.assert_called_with(window, 'light')
            preferences.update({'theme': 'system'})
            event.callback(None, None)
            appearance.assert_called_with(window, 'system')

    def test_windows_window_uses_paperdesk_icon_and_taskbar_identity(self):
        webview = types.SimpleNamespace(settings={}, create_window=Mock(), start=Mock())
        with tempfile.TemporaryDirectory() as directory, patch.dict('sys.modules', {'webview': webview}), \
                patch('paperdesk.desktop._windows_app_identity') as identity:
            NativeWindowShell(WindowsPlatform(), Path(directory)).run('http://127.0.0.1:1234/')
        identity.assert_called_once_with()
        self.assertTrue(Path(webview.start.call_args.kwargs['icon']).is_file())
        self.assertEqual(Path(webview.start.call_args.kwargs['icon']).suffix, '.ico')

    @unittest.skipUnless(shutil.which('node'), 'Node.js is needed for the reader regression suite')
    def test_reader_interactions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'package.json').write_text('{"type":"module"}')
            shutil.copytree(ROOT/'src/paperdesk/web/static/js', root/'src/paperdesk/web/static/js')
            (root/'tests/js').mkdir(parents=True)
            shutil.copyfile(ROOT/'tests/js/reader_ui.mjs', root/'tests/js/reader_ui.mjs')
            result = subprocess.run(['node', '--test', str(root/'tests/js/reader_ui.mjs')], capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


    def test_native_settings_menu_opens_the_existing_settings_page(self):
        class Menu:
            def __init__(self, title, items): self.title, self.items = title, items
        class MenuAction:
            def __init__(self, title, function): self.title, self.function = title, function
        webview = types.SimpleNamespace(settings={}, create_window=Mock(), start=Mock())
        info = {'CFBundleName': 'Python'}
        bundle = Mock(); bundle.localizedInfoDictionary.return_value = None; bundle.infoDictionary.return_value = info
        app = Mock()
        appkit = types.SimpleNamespace(NSApplication=types.SimpleNamespace(sharedApplication=lambda: app),
                                       NSAppearance=types.SimpleNamespace(appearanceNamed_=lambda name: 'appearance:' + name),
                                       NSAppearanceNameAqua='Aqua', NSAppearanceNameDarkAqua='DarkAqua')
        application, tmp = build_app()
        self.addCleanup(tmp.cleanup)
        preferences = application.preferences
        preferences.update({'theme': 'light'})
        with tempfile.TemporaryDirectory() as directory, patch.dict('sys.modules', {
            'webview':webview, 'webview.menu':types.SimpleNamespace(Menu=Menu,MenuAction=MenuAction),
            'Foundation':types.SimpleNamespace(NSBundle=types.SimpleNamespace(mainBundle=lambda: bundle)),
            'AppKit':appkit, 'PyObjCTools':types.SimpleNamespace(),
            'PyObjCTools.AppHelper':types.SimpleNamespace(callAfter=lambda function, *args: function(*args)),
        }):
            NativeWindowShell(MacPlatform(),Path(directory),preferences).run('http://127.0.0.1:1234/')
            app.setAppearance_.assert_not_called()  # AppKit would reset it while launching
            with patch('paperdesk.desktop._macos_settings_shortcut'):
                webview.start.call_args.kwargs['func']()
            # macOS draws the title bar and translucent backdrop: they follow the saved theme, not only the system.
            app.setAppearance_.assert_called_with('appearance:Aqua')
            for theme, expected in (('dark', 'appearance:DarkAqua'), ('system', None)):
                preferences.update({'theme': theme})
                app.setAppearance_.assert_called_with(expected)
            calls = app.setAppearance_.call_count
            preferences.update({'sidebar_width': 300})
            self.assertEqual(app.setAppearance_.call_count, calls)
        options = webview.start.call_args.kwargs
        # Started by python, the Dock and app menu would otherwise say "Python" with Python's icon.
        self.assertEqual(info['CFBundleName'], 'PaperDesk')
        self.assertEqual(Path(options['icon']).name, 'Paperdesk.icns')
        self.assertEqual(options['menu'][0].title,'__app__')
        action = options['menu'][0].items[0]
        self.assertEqual(action.title,'Settings…')
        action.function()
        webview.create_window.return_value.load_url.assert_called_once_with('http://127.0.0.1:1234/settings?shell=native')
        self.assertFalse(webview.create_window.call_args.kwargs['frameless'])

    def test_native_settings_menu_has_command_comma_shortcut(self):
        about, settings = Mock(), Mock()
        about.title.return_value = 'About Paperdesk'
        settings.title.return_value = 'Settings…'
        app = Mock()
        app.mainMenu.return_value.itemAtIndex_.return_value.submenu.return_value.itemArray.return_value = [about, settings]
        with patch.dict('sys.modules', {'AppKit':types.SimpleNamespace(
            NSApplication=types.SimpleNamespace(sharedApplication=lambda:app), NSEventModifierFlagCommand=1<<20)}):
            _macos_settings_shortcut()
        settings.setKeyEquivalent_.assert_called_once_with(',')
        settings.setKeyEquivalentModifierMask_.assert_called_once_with(1<<20)
