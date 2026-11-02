#!/usr/bin/env python3
"""Install PaperDesk from this source folder (beta; there is no signed installer yet).

    Windows:  py -3.12 scripts/install_source.py
    macOS:    python3.12 scripts/install_source.py

Creates a separate Python environment with the same pinned packages as the release builds
(native window and Docling analysis, about 1.3 GB), clones this repository's origin into the install
folder and installs PaperDesk from that clone (editable), and adds "PaperDesk" to Applications
(macOS) or the Start menu (Windows). With automatic updates on (asked once, or --auto-update), the app
fetches new releases from GitHub in the background and applies them the next time it opens; running this
script again also updates. --uninstall removes the environment, the clone and the app or shortcut. Your
library (PDFs, notes, translations, settings) lives in a separate data folder and is never touched.

On Windows use Python 3.12 from python.org: its python.exe is signed, so Smart App Control lets it
run. Smart App Control blocks unsigned programs, including ones you build yourself.
"""
from __future__ import annotations

import argparse
import os
import plistlib
import shlex
import shutil
import stat
import subprocess
import sys
import uuid
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"
PYTHON = (3, 12)  # the pinned window and Docling locks are resolved for Python 3.12
MARKER = "paperdesk-source-install.txt"
SHORTCUT = "PaperDesk.lnk"
APP_BUNDLE = "PaperDesk.app"
EARLIER_NAME = "Paperdesk (beta)"  # the app and shortcut up to 0.2.0; replaced on reinstall, removed on uninstall


def default_prefix() -> Path:
    if WINDOWS:
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Programs" / "Paperdesk-beta"
    return Path.home() / ".paperdesk-beta"


def locks() -> list[Path]:
    if WINDOWS:
        names = ("windows-app.lock", "docling-windows.lock")
    elif MACOS:
        names = ("macos-app.lock", "docling-macos.lock")
    else:
        raise SystemExit("Source installs are for Windows and macOS. On Linux run `pip install -e .` and `paperdesk serve`.")
    return [ROOT / "requirements" / name for name in names]


def environment_python(environment: Path, *, window: bool = False) -> Path:
    if WINDOWS:
        return environment / "Scripts" / ("pythonw.exe" if window else "python.exe")
    return environment / "bin" / "python"


def quote(value) -> str:
    """A PowerShell single-quoted literal."""
    return "'" + str(value).replace("'", "''") + "'"


def powershell(script: str, *, check: bool = True) -> subprocess.CompletedProcess:
    # An inline command, not a .ps1 file, so the PowerShell execution policy does not apply.
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True, timeout=120, check=check)


def signature_status(path: Path) -> str:
    try:
        return powershell(f"(Get-AuthenticodeSignature -LiteralPath {quote(path)}).Status", check=False).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def shortcut_path(name: str = SHORTCUT) -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / name


def write_shortcut(link: Path, target: Path, arguments: str, folder: Path, icon: Path, description: str,
                   app_id: str) -> None:
    """Save a shortcut through the Shell's COM interfaces. Unlike WScript.Shell they also set the AppUserModelID, the
    one the running app gives its window: the taskbar then shows the window, this shortcut and a pin made from either
    as one PaperDesk button. No PowerShell either, which a locked-down shell may not run."""
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("bytes", ctypes.c_ubyte * 16)]

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]

    class PROPVARIANT(ctypes.Structure):
        _fields_ = [("vt", ctypes.c_ushort), ("reserved", ctypes.c_ushort * 3), ("value", ctypes.c_void_p),
                    ("rest", ctypes.c_void_p)]

    def guid(text):
        return GUID((ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(text).bytes_le))

    def method(interface, index, *argtypes, restype=ctypes.HRESULT):
        table = ctypes.cast(interface, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        function = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(table[index])
        return lambda *args: function(interface, *args)

    def query(interface, iid):
        result = ctypes.c_void_p()
        method(interface, 0, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(guid(iid)), ctypes.byref(result))
        opened.append(result)
        return result

    ole32 = ctypes.WinDLL("ole32")
    ole32.CoCreateInstance.restype = ctypes.HRESULT
    initialized = ole32.CoInitialize(None) >= 0  # otherwise this thread already has COM
    opened = []
    try:
        shell_link = ctypes.c_void_p()
        ole32.CoCreateInstance(ctypes.byref(guid("00021401-0000-0000-C000-000000000046")), None, 1,  # ShellLink
                               ctypes.byref(guid("000214F9-0000-0000-C000-000000000046")), ctypes.byref(shell_link))
        opened.append(shell_link)
        text = wintypes.LPCWSTR
        method(shell_link, 20, text)(str(target))  # IShellLinkW::SetPath
        method(shell_link, 11, text)(arguments)  # SetArguments
        method(shell_link, 9, text)(str(folder))  # SetWorkingDirectory
        method(shell_link, 17, text, ctypes.c_int)(str(icon), 0)  # SetIconLocation
        method(shell_link, 7, text)(description)  # SetDescription
        store = query(shell_link, "886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")  # IPropertyStore
        value = ctypes.create_unicode_buffer(app_id)
        key = PROPERTYKEY(guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), 5)  # PKEY_AppUserModel_ID
        variant = PROPVARIANT(vt=31, value=ctypes.cast(value, ctypes.c_void_p))  # VT_LPWSTR
        method(store, 6, ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT))(ctypes.byref(key), ctypes.byref(variant))
        method(store, 7)()  # Commit
        persist = query(shell_link, "0000010B-0000-0000-C000-000000000046")  # IPersistFile
        method(persist, 6, text, wintypes.BOOL)(str(link), True)  # Save
    finally:
        for interface in reversed(opened):
            if interface:
                method(interface, 2, restype=ctypes.c_ulong)()  # Release
        if initialized:
            ole32.CoUninitialize()


def create_shortcut(prefix: Path, environment: Path) -> Path:
    link = shortcut_path()
    link.parent.mkdir(parents=True, exist_ok=True)
    icon = prefix / "Paperdesk.ico"
    shutil.copy2(ROOT / "packaging" / "windows" / "Paperdesk.ico", icon)
    write_shortcut(link, environment_python(environment, window=True), "-m paperdesk", prefix, icon,
                   "PaperDesk (installed from source)", source_app_id())
    # Only once the new one is saved: until then the earlier shortcut still opens the app.
    shortcut_path(EARLIER_NAME + ".lnk").unlink(missing_ok=True)
    return link


def applications_folders() -> list[Path]:
    # /Applications when this account may write there (an administrator), otherwise ~/Applications.
    # Launchpad and Spotlight list both.
    return [Path("/Applications"), Path.home() / "Applications"]


def source_app_id() -> str:
    """The macOS app's bundle ID and the Windows shortcut's AppUserModelID. Not the packaged app's identifier, so
    the two never stand in for each other."""
    sys.path.insert(0, str(ROOT / "src"))
    from paperdesk import SOURCE_APP_ID

    return SOURCE_APP_ID


def remove_app_bundles() -> None:
    for folder in applications_folders():
        for name in (APP_BUNDLE, EARLIER_NAME + ".app"):
            app = folder / name
            try:
                ours = plistlib.loads((app / "Contents" / "Info.plist").read_bytes()).get("CFBundleIdentifier") == source_app_id()
            except (OSError, ValueError):
                continue
            if ours:
                shutil.rmtree(app)


def create_app_bundle(environment: Path) -> Path | None:
    """A small macOS app that starts PaperDesk from this environment, so it opens like any other app."""
    sys.path.insert(0, str(ROOT / "src"))
    from paperdesk import APP_NAME, MAC_MINIMUM_VERSION

    remove_app_bundles()
    system, personal = applications_folders()
    folder = system if os.access(system, os.W_OK) else personal
    app = folder / APP_BUNDLE
    if app.exists():
        print(f"Not replacing {app}: this script did not create it.", file=sys.stderr)
        return None
    contents = app / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    (contents / "Resources").mkdir()
    shutil.copy2(ROOT / "packaging" / "macos" / "Paperdesk.icns", contents / "Resources" / "Paperdesk.icns")
    (contents / "Info.plist").write_bytes(plistlib.dumps({
        "CFBundleName": APP_NAME, "CFBundleDisplayName": app.stem, "CFBundleIdentifier": source_app_id(),
        "CFBundleExecutable": APP_NAME, "CFBundleIconFile": "Paperdesk.icns", "CFBundlePackageType": "APPL",
        "LSMinimumSystemVersion": MAC_MINIMUM_VERSION, "NSHighResolutionCapable": True}))
    launcher = contents / "MacOS" / APP_NAME
    launcher.write_text(f"#!/bin/sh\nexec {shlex.quote(str(environment_python(environment)))} -m paperdesk\n", encoding="utf-8")
    launcher.chmod(0o755)
    return app


def data_folder() -> Path:
    sys.path.insert(0, str(ROOT / "src"))
    from paperdesk.config import AppPaths

    return AppPaths.default().root


def updater():
    """The app's own update helpers (git without prompts, the install record), so both sides agree."""
    sys.path.insert(0, str(ROOT / "src"))
    from paperdesk.infrastructure import source_update

    return source_update


def origin_url() -> str | None:
    git = updater().find_git()
    if git is None:
        return None
    try:
        done = updater().run_git(git, "-C", str(ROOT), "remote", "get-url", "origin", timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None


def prepare_source(prefix: Path, url: str | None, branch: str) -> Path | None:
    """The install's own clone at the newest release (origin/<branch> without release tags), or None (no git or
    remote): then install from this folder without updates."""
    module, clone = updater(), prefix / "source"
    git = module.find_git()
    if git is None or not url:
        print("Automatic updates need git and a repository with an origin remote; installing this folder as it is.", file=sys.stderr)
        return None
    try:
        if (clone / ".git").is_dir():
            steps = [("fetch", "--quiet", "--no-tags", "origin", branch, "+refs/tags/v*:refs/tags/v*")]
            cwd = clone
        else:
            steps = [("clone", "--quiet", "--config", "core.autocrlf=false", "--branch", branch, "--single-branch", url, str(clone))]
            cwd = prefix
        for step in steps:
            print("+ git", " ".join(step), flush=True)
            done = module.run_git(git, *step, cwd=cwd, timeout=600)
            if done.returncode != 0:
                raise OSError(done.stderr.strip() or f"git {step[0]} failed")
        # Start from the newest release, as the app's own updates do; main between releases is not handed out.
        tags = module.run_git(git, "tag", "--list", "v*", cwd=clone, timeout=60).stdout.split()
        step = ("reset", "--quiet", "--hard", module.latest_release(tags) or f"origin/{branch}")
        print("+ git", " ".join(step), flush=True)
        done = module.run_git(git, *step, cwd=clone, timeout=600)
        if done.returncode != 0:
            raise OSError(done.stderr.strip() or "git reset failed")
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"Could not prepare the update clone ({error}); installing this folder without automatic updates.", file=sys.stderr)
        return None
    return clone


def ask_auto_update(previous: bool | None) -> bool:
    if previous is not None:
        return previous
    if not sys.stdin.isatty():
        return False
    answer = input("Check GitHub for new versions when PaperDesk opens and update automatically? [Y/n] ").strip().lower()
    return answer in ("", "y", "yes")


def record(prefix: Path, source: Path | None, branch: str, auto_update: bool | None) -> bool | None:
    """Write (or, without a clone, remove) the install record that the app reads for updates."""
    module = updater()
    config = prefix / module.CONFIG
    if source is None:
        config.unlink(missing_ok=True)
        return None
    previous = module.SourceInstall.load(prefix)
    enabled = ask_auto_update(auto_update if auto_update is not None else previous.data.get("auto_update") if previous else None)
    git = module.find_git()
    commit = module.run_git(git, "rev-parse", "HEAD", cwd=source).stdout.strip()
    names = [f"requirements/{path.name}" for path in locks()]
    data = {"source": str(source), "branch": branch, "commit": commit, "lock_files": names,
            "locks": module.lock_digest(source, names), "auto_update": enabled, "error": ""}
    module.SourceInstall(prefix, data, git=git).save()
    return enabled


def matching_environment(environment: Path) -> bool:
    try:
        lines = (environment / "pyvenv.cfg").read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    version = next((line.split("=", 1)[1].strip() for line in lines if line.split("=", 1)[0].strip() in ("version", "version_info")), "")
    return version.split(".")[:2] == [str(n) for n in PYTHON] and environment_python(environment).is_file()


def run(*args) -> None:
    print("+", " ".join(str(arg) for arg in args), flush=True)
    subprocess.run([str(arg) for arg in args], check=True)


def install(prefix: Path, *, url: str | None = None, branch: str = "main", auto_update: bool | None = None) -> None:
    if sys.prefix != sys.base_prefix:
        raise SystemExit("Run this with the system Python, not from inside a virtual environment.")
    if sys.version_info[:2] != PYTHON:
        hint = ("winget install Python.Python.3.12, then: py -3.12 scripts/install_source.py" if WINDOWS else
                "brew install python@3.12, then: python3.12 scripts/install_source.py")
        raise SystemExit(f"PaperDesk needs Python 3.12 (this is {sys.version.split()[0]}). {hint}")
    requirements = locks()
    if WINDOWS and signature_status(Path(getattr(sys, "_base_executable", sys.executable))) not in ("Valid", ""):
        print("Warning: this Python is not signed (for example one installed by uv or conda). Windows Smart App Control "
              "may block it; Python from python.org is signed.", file=sys.stderr)
    if prefix.exists() and not (prefix / MARKER).is_file():
        raise SystemExit(f"{prefix} exists and was not created by this script; choose another --prefix.")
    environment = prefix / "venv"
    fresh = not matching_environment(environment)
    prefix.mkdir(parents=True, exist_ok=True)
    (prefix / MARKER).write_text(f"PaperDesk source install from {ROOT}\n", encoding="utf-8")
    if fresh:
        print(f"Creating {environment}", flush=True)
        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
    python = environment_python(environment)
    source = prepare_source(prefix, url or origin_url(), branch)
    tree = source or ROOT
    pip = (python, "-m", "pip", "install", "--disable-pip-version-check", "--require-virtualenv")
    run(*pip, *[arg for lock in requirements for arg in ("-r", tree / "requirements" / lock.name)])
    # PaperDesk itself: dependencies come only from the pinned locks above (they include setuptools, so no
    # build download). The clone is installed editable: an update is then just a checkout of new commits.
    if source:
        run(*pip, "--no-deps", "--no-build-isolation", "-e", source)
    else:
        run(*pip, "--no-deps", "--no-build-isolation", "--force-reinstall", ROOT)
    run(python, "-m", "paperdesk", "--version")
    automatic = record(prefix, source, branch, auto_update)

    print("\nPaperDesk is installed.")
    if WINDOWS:
        try:
            print(f"  Start menu:  {create_shortcut(prefix, environment).stem}")
        except OSError as error:
            print(f"  Start menu:  not added ({error}); run this script again to add it")
        print(f"  or run:      \"{environment_python(environment, window=True)}\" -m paperdesk")
    else:
        app = create_app_bundle(environment)
        if app:
            print(f"  Open:        {app.stem} in {app.parent}")
        print(f"  or run:      {python} -m paperdesk")
    print(f"  MCP setup:   \"{python}\" -m paperdesk mcp-config claude   (or codex)")
    if automatic:
        print(f"  Update:      automatic; new releases from GitHub apply the next time PaperDesk opens (Settings to turn off)")
    elif source:
        print(f"  Update:      Settings → check for updates, or run this script again (automatic updates are off)")
    else:
        print(f"  Update:      not automatic (no git clone with an origin). Get the new version (a new ZIP, or git pull "
              f"in a clone) and run this script again; installing from a git clone enables automatic updates")
    print(f"  Uninstall:   run this script with --uninstall")
    print(f"  Library:     {data_folder()} (kept on update and uninstall)")


def _remove_read_only(function, path, _error) -> None:
    # Git makes its object files read-only, and Windows refuses to delete read-only files.
    os.chmod(path, stat.S_IWRITE)
    function(path)


def uninstall(prefix: Path) -> None:
    # Ask first: run from the install's own copy (prefix/source), the code is gone once the prefix is removed.
    library = data_folder()
    if WINDOWS:
        shortcut_path().unlink(missing_ok=True)
        shortcut_path(EARLIER_NAME + ".lnk").unlink(missing_ok=True)
    if MACOS:
        remove_app_bundles()
    if prefix.exists():
        if not (prefix / MARKER).is_file():
            raise SystemExit(f"{prefix} was not created by this script; not removing it.")
        # Remove the marker last, so an interrupted uninstall can simply be run again.
        for child in sorted(prefix.iterdir(), key=lambda p: p.name == MARKER):
            if child.is_dir() and not child.is_symlink():
                if sys.version_info >= (3, 12):
                    shutil.rmtree(child, onexc=_remove_read_only)
                else:
                    shutil.rmtree(child, onerror=lambda f, p, e: _remove_read_only(f, p, e))
            else:
                _remove_read_only(Path.unlink, child, None)
        prefix.rmdir()
    print(f"Removed {prefix}. Your library in {library} was kept.")


def main() -> int:
    # Piped or saved to a file (as AI agents and logs do), Windows output uses the ANSI code page (cp949 on Korean
    # Windows): UTF-8 readers see broken text, and a character outside it would stop the script.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prefix", type=Path, default=default_prefix(), help="Where to put the Python environment")
    parser.add_argument("--uninstall", action="store_true", help="Remove the environment and shortcut (keeps your library)")
    parser.add_argument("--source-url", help="Repository to clone for updates (default: this folder's origin remote)")
    parser.add_argument("--branch", default="main", help="Branch to clone; updates follow its release tags (vX.Y.Z), or the branch itself if it has none (default: main)")
    parser.add_argument("--auto-update", action=argparse.BooleanOptionalAction, default=None,
                        help="Update automatically from GitHub when the app opens (asked once if omitted)")
    args = parser.parse_args()
    prefix = args.prefix.expanduser().resolve()
    if args.uninstall:
        uninstall(prefix)
    else:
        install(prefix, url=args.source_url, branch=args.branch, auto_update=args.auto_update)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
