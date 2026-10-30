<div align="center">

# PaperDesk

**Read research papers in your own language, right beside the original.**

**English** · [한국어](README.ko.md) · [简体中文](README.zh.md) · [日本語](README.ja.md)

</div>

![PaperDesk: a PDF with its translation side by side and the AI Assistant explaining a selected sentence](https://raw.githubusercontent.com/HojooonKim/PaperDesk/media/en/reader.png)

PaperDesk is a desktop app for reading research papers on macOS and Windows.

- Keep your PDFs in folders by topic.
- Translate a whole paper beside the original.
- Ask the AI you already use about anything you select.

Your papers and notes stay on your computer.

> **Beta.** PaperDesk is installed from source for now. The quickest way is to let Claude Code or Codex do it.

## Install in one command

If you use [Claude Code](https://claude.com/claude-code) or [Codex](https://github.com/openai/codex), run one of these in a terminal:

```sh
claude "Install PaperDesk on this computer by following https://raw.githubusercontent.com/HojooonKim/PaperDesk/main/INSTALL.md"
```

```sh
codex "Install PaperDesk on this computer by following https://raw.githubusercontent.com/HojooonKim/PaperDesk/main/INSTALL.md"
```

The agent follows [INSTALL.md](INSTALL.md). It checks your computer and asks before installing anything system-wide, such as Python 3.12 or git. At the end it tells you how to open PaperDesk and what is left to set up. It never handles your sign-ins or API keys.

With another coding agent, paste the text in quotes. To install by hand, see [Install](#install).

## Highlights

### A translation that scrolls with the original

When you open a paper, PaperDesk analyzes its layout on your computer (columns, headings, figures and equations), then your AI translates it paragraph by paragraph. Translated paragraphs appear as they finish.

Each page's translation sits beside that page and moves with it as you scroll. Point at a paragraph to highlight its translation, or point at the translation to highlight the original.

![Scrolling: each PDF page and its translation move together](https://raw.githubusercontent.com/HojooonKim/PaperDesk/media/en/scroll.gif)

### Previews for figures, tables and citations

Point at "Figure 2" or "[38, 2, 9]" to see the figure, table or reference without losing your place. The same previews work on references inside the translation.

From a reference preview you can add the paper to your Reading List, open it on arXiv or Google Scholar, or ask the AI what it is about.

![Hovering a figure reference, then a citation](https://raw.githubusercontent.com/HojooonKim/PaperDesk/media/en/preview.gif)

### Select, then translate, explain or ask

Select text and choose **Translate** (T), **Explain** (E), **Define** (W) or **Ask** (Q). You can also **Highlight** it (H) or add a **Note** (C).

Answers appear in the AI Assistant, and each paper keeps its own conversation. To ask about a figure, table or equation, use **Select area** and drag over it.

![Selecting a sentence and choosing Explain](https://raw.githubusercontent.com/HojooonKim/PaperDesk/media/en/ask.gif)

### Over the original, light or dark

Switch the translation to **Over the original** to read it in place of each paragraph, or to **Side by side** or **Hide translation**. In dark mode the PDF pages stay white.

![Dark mode with the translation over the original](https://raw.githubusercontent.com/HojooonKim/PaperDesk/media/en/dark-overlay.png)

### Also included

- **Library:** topic folders nested as deep as you like. Drag and drop to organize or import, and titles are read from the PDF.
- **Paper details and auto-organize:** authors, year, venue and DOI are filled in from arXiv and OpenAlex. Papers added without a folder are sorted into one your AI picks (or creates), and you can copy BibTeX for a paper or a whole folder.
- **Reading tools:** paper summaries, find in the document, and search across your library.
- **Background translation:** jobs keep running while you read other papers, and you can resume them after a restart.
- **Languages:** the interface is in English, 한국어, 日本語 and 简体中文. Translations and answers use the language you choose.
- **Look:** system, light and dark themes, with resizable panes.
- **MCP server:** Claude Desktop and Codex can read your library.
- **Backup and restore:** PDFs, notes, translations and conversations together.

## Install

**You need:**

- an Apple Silicon Mac with macOS 15 or later, or a Windows 10/11 x64 PC;
- Python 3.12;
- git;
- about 1.5 GB of free space.

**macOS**

```sh
git clone --depth 1 https://github.com/HojooonKim/PaperDesk.git
cd PaperDesk
python3.12 scripts/install_source.py --auto-update
```

**Windows**

```bat
git clone --depth 1 https://github.com/HojooonKim/PaperDesk.git
cd PaperDesk
py -3.12 scripts\install_source.py --auto-update
```

Then open **PaperDesk** from Applications on macOS or from the Start menu on Windows. On Windows, use Python from [python.org](https://www.python.org/downloads/windows/): Windows 11 Smart App Control can block Python from uv or conda.

**Updates.** With `--auto-update`, PaperDesk downloads new versions from GitHub in the background and applies them the next time it opens, or right away with **Restart now** in Settings.

**Your library** is stored separately from the app, and is kept when you update or uninstall. For checks, uninstalling and troubleshooting, see [INSTALL.md](INSTALL.md).

## Connect an AI

PaperDesk works with the AI you already have. On first launch it selects a signed-in Codex CLI or Claude Code automatically.

| Connection | What you need |
| --- | --- |
| Codex CLI | Sign in yourself with `codex login` |
| Claude Code | Sign in to Claude Code yourself |
| OpenAI API / Claude API | Your API key, kept in the macOS Keychain or Windows Credential Manager |
| Ollama / vLLM / OpenAI-compatible server | The server address, and a key if the server needs one |

PaperDesk never reads or stores your Codex or Claude sign-ins. See [docs/ai-integrations.md](docs/ai-integrations.md) for details.

## Your data stays on your computer

| What | Where |
| --- | --- |
| PDFs, library, translations, highlights, notes, conversations | macOS `~/Library/Application Support/Paperdesk`, Windows `%LOCALAPPDATA%\Paperdesk` |
| API keys | macOS Keychain / Windows Credential Manager |

**Offline:** reading, previews, and saved translations, notes and conversations. Layout analysis also runs on your computer, using Docling. It downloads a layout model (about 170 MB) the first time.

**Online:** PaperDesk connects only:

- to the AI you chose (no internet is needed for Ollama or vLLM on your own machine);
- to arXiv and OpenAlex, to look up a paper's details (its title and arXiv number or DOI only), or when you search for or download a paper;
- to links you click;
- to GitHub, to check for updates if they are on.

See [docs/privacy.md](docs/privacy.md).

## Documentation

- [INSTALL.md](INSTALL.md): install, update, uninstall and troubleshooting
- [docs/support.md](docs/support.md): what is supported, and how backup and recovery work
- [docs/keyboard-shortcuts.md](docs/keyboard-shortcuts.md): reader shortcuts
- [docs/ai-integrations.md](docs/ai-integrations.md) and [docs/privacy.md](docs/privacy.md): AI connections and data
- [docs/development.md](docs/development.md): architecture and development (in Korean)

## License

PaperDesk is licensed under the [Apache License 2.0](LICENSE). Third-party software keeps its own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

The screenshots show "Attention Is All You Need" (Vaswani et al., 2017, [arXiv:1706.03762](https://arxiv.org/abs/1706.03762)) to demonstrate the app.
