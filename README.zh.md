<div align="center">

# PaperDesk

**在原文旁边，用你的语言读论文**

[English](README.md) · [한국어](README.ko.md) · **简体中文** · [日本語](README.ja.md)

</div>

![PaperDesk：PDF 与译文并排显示，AI 助手正在解释选中的句子](https://raw.githubusercontent.com/HojooonKim/PaperDesk/media/zh/reader.png)

PaperDesk 是一款在 macOS 和 Windows 上阅读论文的桌面应用。它按主题文件夹整理论文 PDF，把整篇论文翻译在原文旁边，选中任何内容都能直接问你已经在用的 AI。论文和记录都只保存在你自己的电脑上。

> **测试版**：目前从源码安装，交给 Claude Code 或 Codex 最省事。

## 一条命令安装

如果你在用 [Claude Code](https://claude.com/claude-code) 或 [Codex](https://github.com/openai/codex)，在终端运行下面任意一条：

```sh
claude "按照 https://raw.githubusercontent.com/HojooonKim/PaperDesk/main/INSTALL.md 在这台电脑上安装 PaperDesk"
```

```sh
codex "按照 https://raw.githubusercontent.com/HojooonKim/PaperDesk/main/INSTALL.md 在这台电脑上安装 PaperDesk"
```

代理会按照 [INSTALL.md](INSTALL.md) 检查你的电脑。在系统范围安装任何东西（例如 Python 3.12 或 git）之前，它会先征求你的同意；最后告诉你怎么打开 PaperDesk、还需要设置什么。它不会经手你的登录信息或 API 密钥。

使用其他编程代理时，粘贴引号里的文字即可。想手动安装，请看[安装](#安装)。

## 主要功能

### 随原文一起滚动的译文

打开论文后，PaperDesk 先在本机分析版面（分栏、标题、图、公式），再用你连接的 AI 按段落翻译正文，译好的段落会立即显示。每一页的译文都排在该页旁边，随滚动一起移动。把鼠标移到原文段落上会高亮对应译文，移到译文上则高亮原文。

![滚动：PDF 页面与译文一起移动](https://raw.githubusercontent.com/HojooonKim/PaperDesk/media/zh/scroll.gif)

### 图、表与参考文献预览

把鼠标移到 "Figure 2" 或 "[38, 2, 9]" 上，不用离开当前位置就能看到图、表或参考文献；译文中的引用同样可以预览。参考文献可以加入**待读列表**、在 arXiv 或 Google Scholar 中打开，或者让 AI 介绍这篇论文。

![悬停图引用和参考文献](https://raw.githubusercontent.com/HojooonKim/PaperDesk/media/zh/preview.gif)

### 选中即可翻译、解释、提问

选中文字后选择**翻译**（T）、**解释**（E）、**释义**（W）或**提问**（Q），也可以**高亮**（H）或添加**笔记**（C）。回答显示在 **AI 助手**中，每篇论文的对话单独保存。想问图、表或公式时，用**区域选择**拖选即可。

![选中句子并选择“解释”](https://raw.githubusercontent.com/HojooonKim/PaperDesk/media/zh/ask.gif)

### 覆盖在原文上，浅色与深色

把译文显示切换为**覆盖在原文上**，就能在每个段落的位置直接读译文；也可以选择**并排显示**或**隐藏译文**。深色模式下 PDF 页面保持白色。

![深色模式下译文覆盖在原文上](https://raw.githubusercontent.com/HojooonKim/PaperDesk/media/zh/dark-overlay.png)

### 其他功能

- 按主题建文件夹（可无限嵌套），拖放即可整理或导入，自动从 PDF 识别论文标题
- 论文信息与自动整理：从 arXiv 和 OpenAlex 补全作者、年份、发表处和 DOI；未选文件夹添加的论文由 AI 放进它选择（或新建）的文件夹。可以复制单篇论文或整个文件夹的 BibTeX。
- 论文摘要、文档内查找、全库搜索
- 阅读其他论文时翻译继续进行，重新打开应用后可以接着翻译
- 界面语言：English、한국어、日本語、简体中文；译文和回答的语言可单独选择
- 跟随系统、浅色、深色主题，面板宽度可调
- 内置 MCP 服务器，Claude Desktop 和 Codex 可以读取你的论文库
- PDF、笔记、译文和对话一起备份与恢复

## 安装

需要：Apple Silicon Mac（macOS 15 及以上）或 Windows 10/11（x64）、Python 3.12、git，以及约 1.5 GB 可用空间。

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

安装完成后，在 macOS 上从“应用程序”（Applications）、在 Windows 上从开始菜单打开 **PaperDesk**。Windows 上请使用 [python.org](https://www.python.org/downloads/windows/) 的 Python：Windows 11 的智能应用控制可能会拦截 uv 或 conda 安装的 Python。

加上 `--auto-update` 后，PaperDesk 会在后台从 GitHub 下载新版本，并在下次打开时应用；也可以在设置中点 **立即重新启动** 马上应用。论文库与应用分开保存，更新或卸载都不会删除。安装检查、卸载和问题排查见 [INSTALL.md](INSTALL.md)。

## 连接 AI

PaperDesk 使用你已经在用的 AI。首次启动时会自动找到并选择已登录的 Codex CLI 或 Claude Code。

| 连接 | 需要 |
| --- | --- |
| Codex CLI | 你自己完成的 `codex login` |
| Claude Code | 你自己完成的 Claude Code 登录 |
| OpenAI API / Claude API | API 密钥（保存在 macOS 钥匙串或 Windows 凭据管理器中） |
| Ollama / vLLM / OpenAI 兼容服务器 | 服务器地址（需要时提供服务器密钥） |

PaperDesk 不会读取或保存 Codex、Claude 的登录信息。详见 [docs/ai-integrations.md](docs/ai-integrations.md)。

## 数据只在你的电脑上

| 内容 | 位置 |
| --- | --- |
| PDF、论文库、译文、高亮、笔记、对话 | macOS `~/Library/Application Support/Paperdesk`，Windows `%LOCALAPPDATA%\Paperdesk` |
| API 密钥 | macOS 钥匙串 / Windows 凭据管理器 |

阅读 PDF、预览以及已保存的译文、笔记和对话都可以离线使用。版面分析也在本机用 Docling 完成，只在第一次下载分析模型（约 170 MB）。只有以下情况会联网：你选择的 AI（本机的 Ollama 或 vLLM 不需要联网）、查询论文信息（只发送标题和 arXiv 编号或 DOI）或搜索、下载论文时访问 arXiv 和 OpenAlex、你点击的链接，以及开启后的更新检查（GitHub）。详见 [docs/privacy.md](docs/privacy.md)。

## 文档

- [INSTALL.md](INSTALL.md)：安装、更新、卸载与问题排查（英文）
- [docs/support.md](docs/support.md)：支持范围、备份与恢复（英文）
- [docs/keyboard-shortcuts.md](docs/keyboard-shortcuts.md)：阅读器快捷键
- [docs/ai-integrations.md](docs/ai-integrations.md)、[docs/privacy.md](docs/privacy.md)：AI 连接与数据
- [docs/development.md](docs/development.md)：架构与开发（韩文）

## 许可证

本项目采用 [Apache License 2.0](LICENSE)。第三方软件适用各自的许可证，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

截图中为演示应用功能使用了论文 "Attention Is All You Need"（Vaswani 等，2017，[arXiv:1706.03762](https://arxiv.org/abs/1706.03762)）。
