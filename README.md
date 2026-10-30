# Paperdesk README media

Screenshots and GIFs for the READMEs on `main`, which link to them as
`https://raw.githubusercontent.com/HojooonKim/PaperDesk/media/<lang>/<file>`.
They live on this separate branch so that installs and updates, which clone only `main`, never download them.
Never merge this branch into `main`.

| Folder | UI language | Translation and answers |
| --- | --- | --- |
| `en/` | English | Korean |
| `ko/` | 한국어 | Korean |
| `zh/` | 简体中文 | Chinese (Simplified) |
| `ja/` | 日本語 | Japanese |

Every folder holds the same five files:

| File | What it shows |
| --- | --- |
| `reader.png` | The main screenshot at 2× |
| `scroll.gif` | Scrolling with side-by-side translation |
| `preview.gif` | Previews of a figure and a citation |
| `ask.gif` | Selecting a sentence and choosing Explain |
| `dark-overlay.png` | Dark theme, with the translation over the original, at 2× |

The paper shown is "Attention Is All You Need" (Vaswani et al., 2017, arXiv:1706.03762).

## Regenerating

You need Google Chrome, Node 22 or later, and ffmpeg. The scripts in `tools/` drive headless Chrome over the DevTools protocol.

1. Run a Paperdesk server on a temporary library. Never use your real one:

   ```sh
   PAPERDESK_HOME=/tmp/demo PYTHONPATH=src python3 -m paperdesk serve --port 47711
   ```

   For layout analysis, set `PAPERDESK_ANALYSIS_PYTHON` to a Python that has Docling installed.
2. Import the PDF with `POST /api/documents`. Choose an AI connection, set each target language, and run `node tools/warm.mjs <base> <docId> <outDir>` once per language. This opens the paper so its translation job is queued. Wait until the jobs finish.
3. For each folder, run:

   ```sh
   node tools/capture.mjs <base> <docId> <outDir> <ui-lang> <target-language>
   ```
