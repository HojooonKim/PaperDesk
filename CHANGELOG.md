# Changelog

Versions follow [Semantic Versioning](https://semver.org/): new features raise the second number and bug fixes the
third. Before 1.0.0, the first official release, the first number stays 0. The rule and the release steps are in
[docs/development.md](docs/development.md) (in Korean).

## 0.3.2 — 2026-10-30

### Fixed

- Zoomed PDF pages no longer extend beyond the left edge of the scrollable area. Enlarged page rows now grow
  with their content, so horizontal scrolling can reach both edges in all translation display modes.
- **Windows:** light mode no longer shows the dark WebView backdrop through the gaps between cards. The native
  title bar follows the app's selected theme, and browser controls use the same light or dark color scheme.

## 0.3.1 — 2026-10-30

### Fixed

- **Windows blank window:** bundled scripts and other static assets now use fixed Content-Type values instead of
  the system MIME table. If another program registers `.js` as `text/plain`, WebView2 can still execute PaperDesk's
  JavaScript. The Content Security Policy and `nosniff` protections remain enabled.
- Thanks to [CreamMeatball](https://github.com/CreamMeatball) for diagnosing and fixing this in
  [#1](https://github.com/HojooonKim/PaperDesk/pull/1).

## 0.3.0 — 2026-10-30

### Added

- With automatic translation enabled, importing a PDF now starts analysis and translation in the background,
  without first opening it in the reader. Page text is also saved for search and MCP.

### Changed

- The translation menu now shows actions appropriate to the current page and job state, including stopping,
  resuming and translating remaining text.

### Fixed

- **Windows:** the native window uses the PaperDesk icon and its own taskbar app identity instead of Python's.
- Background translation and the reader no longer queue the same paragraph twice for the same language.
- The source installer writes UTF-8 output when piped or saved to a file on Windows.

### Known issues

- A blank window has been reported on Windows with 0.2.1. It has not been reproduced on the test PC;
  this release does not claim to fix it.

## 0.2.1 — 2026-10-30

### Changed

- The app is now called **PaperDesk**: in the window, the Dock and the sidebar, and as the app in Applications (macOS)
  and the Start menu shortcut (Windows), which were "Paperdesk (beta)". Running the install script again renames
  the app and the shortcut and removes the old ones. The library, settings and install folders stay where they are.

## 0.2.0 — 2026-10-30

This is the first tagged release. From now on, installs and automatic updates follow release tags instead of every
commit on main.

### Added

- **Source install** for macOS and Windows with one script (`scripts/install_source.py`) and automatic updates from
  GitHub. A downloaded update applies when the app next starts, or right away with **Restart now** in Settings.
- **macOS:** "Paperdesk (beta)" in Applications. While it runs, it shows Paperdesk's name and icon.
- Resizable sidebar and AI panel.
- READMEs in English, Korean, Chinese and Japanese, with demos.
- [INSTALL.md](INSTALL.md), written for people and for AI agents, plus one-command installs with Claude Code or Codex.

### Changed

- Updates and new installs use the newest release tag (`vX.Y.Z`). Pre-release tags are not offered, and an install is
  never moved back to an older version.
- The sidebar mark is the app logo.
- Packaged builds (macOS DMG with Sparkle updates, Windows installer, Homebrew) are set aside until the first packaged
  release.

### Fixed

- **macOS:** with the light theme on a dark system, the window frame and title bar are no longer black.
- **Settings:** no longer shows a stray "null" when an AI connection works.
- **Windows:** WebView2's files no longer block restoring a backup.
- **Command-line restore:** when a restore is blocked, it now explains why instead of printing a traceback.
- **After an update:** the restart waits until the library is released, so the app no longer quits as "already running".
- **Uninstall:** running it from the install's own copy no longer ends with a traceback after removing everything.

## 0.1.0

Development versions before tagged releases. They were never tagged.
