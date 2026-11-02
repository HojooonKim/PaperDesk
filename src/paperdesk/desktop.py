"""How the UI is shown. The server and web UI do not know which shell is used."""

from __future__ import annotations

import importlib.util
import os
import time
import webbrowser
import zlib
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar
from urllib.parse import urljoin

from . import APP_NAME, SOURCE_APP_ID
from .platforms import Platform
from .services.app_state import PreferenceService


class DesktopShell(ABC):
    name: ClassVar[str]
    blocks: ClassVar[bool]  # True: run() returns when the window closes, so the app can quit

    @classmethod
    @abstractmethod
    def is_available(cls) -> bool: ...

    @abstractmethod
    def run(self, url: str) -> None: ...


def _macos_settings_shortcut() -> None:
    from AppKit import NSApplication, NSEventModifierFlagCommand

    menu = NSApplication.sharedApplication().mainMenu().itemAtIndex_(0).submenu()
    for item in menu.itemArray():
        if item.title() == "Settings…":
            item.setKeyEquivalent_(",")
            item.setKeyEquivalentModifierMask_(NSEventModifierFlagCommand)
            break


MAC_ICON = Path(__file__).resolve().parents[2] / "packaging" / "macos" / "Paperdesk.icns"  # present in source installs
WINDOWS_ICON = Path(__file__).resolve().parents[2] / "packaging" / "windows" / "Paperdesk.ico"


def _windows_app_identity() -> None:
    # Source installs run pythonw.exe. Give the taskbar our identity instead of grouping with Python. The Start menu
    # shortcut carries the same ID (scripts/install_source.py): the window, the shortcut and a pin are one button.
    import ctypes

    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(SOURCE_APP_ID)


LIBRARY_PROPERTY = "PaperDesk.Library"  # window property: which library the window has open


def _library_key(library: Path) -> int:
    return zlib.crc32(os.path.normcase(str(library.resolve())).encode("utf-8")) or 1


def _windows_mark_library(window, library: Path) -> None:
    # A second launch of the same library finds this window by it (show_running_window).
    import ctypes
    from ctypes import wintypes

    native = window.native
    if native is None:
        return
    user32 = ctypes.WinDLL("user32")
    user32.SetPropW.argtypes = (wintypes.HWND, wintypes.LPCWSTR, wintypes.HANDLE)
    user32.SetPropW(native.Handle.ToInt64(), LIBRARY_PROPERTY, _library_key(library))


def _windows_library_window(library: Path) -> int | None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32")
    user32.GetPropW.argtypes = (wintypes.HWND, wintypes.LPCWSTR)
    user32.GetPropW.restype = wintypes.HANDLE
    key, found = _library_key(library), []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        if user32.GetPropW(hwnd, LIBRARY_PROPERTY) == key:
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(visit, 0)
    return found[0] if found else None


def show_running_window(library: Path, wait: float = 15) -> bool:
    """Windows: PaperDesk opened again (the Start menu, a shortcut) brings the window that has this library open to the
    front. Waits a little, since a launch holds the library before its window exists. False elsewhere or if none appears."""
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    deadline = time.monotonic() + wait
    while (hwnd := _windows_library_window(library)) is None:
        if time.monotonic() > deadline:
            return False
        time.sleep(0.25)
    user32 = ctypes.WinDLL("user32")
    user32.IsIconic.argtypes = user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)  # refused without focus rights; Windows then flashes the taskbar button
    return True


def windows_message(text: str) -> None:
    """For pythonw, which the Start menu shortcut runs: it has no console to print to."""
    import ctypes

    ctypes.WinDLL("user32").MessageBoxW(None, text, APP_NAME, 0x40)  # MB_ICONINFORMATION


def _windows_appearance(window, theme: str) -> None:
    # pywebview's title bar follows Windows, independently of the theme chosen in the page.
    # Set caption colors as well: a later Windows theme event must not override an explicit app choice.
    import ctypes
    from ctypes import wintypes
    from System import Action

    native = window.native
    if native is None:
        return

    def apply():
        try:
            dark = theme == "dark"
            if theme == "system":
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                    dark = not winreg.QueryValueEx(key, "AppsUseLightTheme")[0]
            set_attribute = ctypes.WinDLL("dwmapi").DwmSetWindowAttribute
            set_attribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
            set_attribute.restype = ctypes.c_long
            caption = 0x2C2828 if dark else 0xECE8E8
            text = 0xEFECEC if dark else 0x1F1D1D
            for attribute, color in ((20, int(dark)), (35, caption), (36, text)):
                value = wintypes.DWORD(color)
                set_attribute(native.Handle.ToInt64(), attribute, ctypes.byref(value), ctypes.sizeof(value))
        except OSError:
            # Older Windows versions can lack DWM attributes or the personalization key.
            pass

    native.Invoke(Action(apply))


def _windows_follow_theme(window, preferences: PreferenceService) -> None:
    from Microsoft.Win32 import SystemEvents

    _windows_appearance(window, preferences.all()["theme"])
    preferences.watch(lambda values: "theme" in values and _windows_appearance(window, values["theme"]))

    def system_changed(sender, event):
        _windows_appearance(window, preferences.all()["theme"])

    SystemEvents.UserPreferenceChanged += system_changed


def _macos_app_name() -> None:
    # The process is Python's, so the Dock and the app menu would say "Python". This must run before the window
    # starts: pywebview creates the application and its menus from this dictionary when it loads.
    from Foundation import NSBundle

    bundle = NSBundle.mainBundle()
    (bundle.localizedInfoDictionary() or bundle.infoDictionary())["CFBundleName"] = APP_NAME


def _macos_appearance(theme: str) -> None:
    # macOS draws the title bar and the translucent backdrop behind the page, and they follow the app's appearance:
    # left to the system, the light theme on a dark system sat in a black frame. Main thread only.
    from AppKit import NSAppearance, NSAppearanceNameAqua, NSAppearanceNameDarkAqua, NSApplication

    name = {"light": NSAppearanceNameAqua, "dark": NSAppearanceNameDarkAqua}.get(theme)  # "system": follow macOS
    NSApplication.sharedApplication().setAppearance_(NSAppearance.appearanceNamed_(name) if name else None)


def _macos_follow_theme(preferences: PreferenceService) -> None:
    # The theme is saved by the page; pywebview's JS bridge cannot run under the app's Content-Security-Policy.
    # Called once the app is running: AppKit resets an appearance set while it is still launching.
    from PyObjCTools.AppHelper import callAfter

    callAfter(_macos_appearance, preferences.all()["theme"])
    preferences.watch(lambda values: "theme" in values and callAfter(_macos_appearance, values["theme"]))


class NativeWindowShell(DesktopShell):
    """pywebview: WKWebView on macOS (and Edge WebView2 on Windows later), with the platform's translucency."""

    name = "native"
    blocks = True

    def __init__(self, platform: Platform, storage: Path, preferences: PreferenceService | None = None,
                 library: Path | None = None) -> None:
        self.platform = platform
        self.storage = storage
        self.preferences = preferences
        self.library = library
        self.window = None

    @classmethod
    def is_available(cls) -> bool:
        return importlib.util.find_spec("webview") is not None

    def run(self, url: str) -> None:
        import webview  # optional dependency, imported only when a window is requested
        webview.settings['ALLOW_DOWNLOADS'] = True
        if self.platform.name == "windows":
            _windows_app_identity()

        self.storage.mkdir(parents=True, exist_ok=True)
        window = self.window = webview.create_window(
            APP_NAME,
            url + ("&" if "?" in url else "?") + "shell=native",
            width=1360,
            height=880,
            min_size=(960, 620),
            frameless=False,
            resizable=True,
            text_select=True,  # pywebview disables selection by default; readers need it
            **self.platform.window_options(),
        )
        menu, icon = [], None
        if self.platform.name == "windows":
            icon = str(WINDOWS_ICON) if WINDOWS_ICON.is_file() else None
        if self.platform.name == "macos":
            from webview.menu import Menu, MenuAction
            menu = [Menu("__app__", [MenuAction("Settings…", lambda: window.load_url(urljoin(url, "/settings?shell=native")))])]
            _macos_app_name()
            icon = str(MAC_ICON) if MAC_ICON.is_file() else None

        def started():
            # start(func=) runs before WinForms constructs the native window.
            if self.platform.name == "windows" and window.events.shown.wait(15):
                if self.library is not None:
                    _windows_mark_library(window, self.library)
                if self.preferences is not None:
                    _windows_follow_theme(window, self.preferences)
            if self.platform.name == "macos":
                from PyObjCTools.AppHelper import callAfter
                callAfter(_macos_settings_shortcut)
                if self.preferences is not None:
                    _macos_follow_theme(self.preferences)

        webview.start(func=started, menu=menu, private_mode=False, storage_path=str(self.storage), icon=icon)

    def close(self) -> None:
        """Close the window from any thread; run() then returns."""
        if self.window is not None:
            self.window.destroy()


class BrowserShell(DesktopShell):
    """Development fallback: opens the default browser and keeps serving until Ctrl+C."""

    name = "browser"
    blocks = False

    @classmethod
    def is_available(cls) -> bool:
        return True

    def run(self, url: str) -> None:
        webbrowser.open(url)


def choose_shell(preference: str, platform: Platform, storage: Path, preferences: PreferenceService | None = None,
                 library: Path | None = None) -> DesktopShell:
    if preference in ("auto", "native") and NativeWindowShell.is_available():
        return NativeWindowShell(platform, storage, preferences, library)
    if preference == "native":
        raise RuntimeError("네이티브 창에 필요한 pywebview가 설치되어 있지 않아요.")
    return BrowserShell()
