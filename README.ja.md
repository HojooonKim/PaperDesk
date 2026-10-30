<div align="center">

# PaperDesk

**原文のすぐ隣で、自分の言語で論文を読む**

[English](README.md) · [한국어](README.ko.md) · [简体中文](README.zh.md) · **日本語**

</div>

![PaperDesk：PDF と翻訳を並べて表示し、選んだ文を AI アシスタントが説明している画面](https://raw.githubusercontent.com/HojooonKim/PaperDesk/media/ja/reader.png)

PaperDesk は macOS と Windows で論文を読むためのデスクトップアプリです。論文 PDF をテーマ別のフォルダで整理し、論文全体を原文の隣に翻訳し、選んだ部分をいつも使っている AI にその場で質問できます。論文と記録はすべて自分のコンピュータにだけ保存されます。

> **ベータ版**：現在はソースからインストールします。Claude Code や Codex に任せるのがいちばん簡単です。

## コマンド 1 行でインストール

[Claude Code](https://claude.com/claude-code) または [Codex](https://github.com/openai/codex) を使っているなら、ターミナルで次のどちらかを実行してください。

```sh
claude "https://raw.githubusercontent.com/HojooonKim/PaperDesk/main/INSTALL.md に従って、このコンピュータに PaperDesk をインストールして"
```

```sh
codex "https://raw.githubusercontent.com/HojooonKim/PaperDesk/main/INSTALL.md に従って、このコンピュータに PaperDesk をインストールして"
```

エージェントは [INSTALL.md](INSTALL.md) に従ってコンピュータの環境を確認します。Python 3.12 や git のようにシステム全体にインストールするものがあれば先に確認し、最後に開き方と残りの設定を教えてくれます。ログイン情報や API キーは扱いません。

ほかのコーディングエージェントでは、引用符の中の文を貼り付けてください。手動でインストールする場合は[インストール](#インストール)を参照してください。

## 主な機能

### 原文と一緒に動く翻訳

論文を開くと、PaperDesk はまず手元のコンピュータで段組み・見出し・図・数式などのレイアウトを解析し、接続した AI で本文を段落ごとに翻訳します。訳し終えた段落からすぐに表示されます。各ページの翻訳はそのページの隣に並び、スクロールと一緒に動きます。原文の段落にマウスを重ねると対応する訳文が、訳文に重ねると原文が強調されます。

![スクロール：PDF のページと翻訳が一緒に動く様子](https://raw.githubusercontent.com/HojooonKim/PaperDesk/media/ja/scroll.gif)

### 図・表・参考文献のプレビュー

「Figure 2」や「[38, 2, 9]」にマウスを重ねると、読んでいる場所を離れずに図・表・参考文献を確認できます。訳文の中の参照でも同じように使えます。参考文献は**あとで読む**に追加したり、arXiv や Google Scholar で開いたり、どんな論文か AI に聞いたりできます。

![図の参照と参考文献にマウスを重ねた様子](https://raw.githubusercontent.com/HojooonKim/PaperDesk/media/ja/preview.gif)

### 選んで翻訳・説明・質問

テキストを選んで**翻訳**（T）・**説明**（E）・**意味**（W）・**質問**（Q）を選ぶか、**ハイライト**（H）や**メモ**（C）を残せます。回答は **AI アシスタント**に表示され、会話は論文ごとに保存されます。図・表・数式は**範囲選択**でドラッグして質問できます。

![文を選んで「説明」を選ぶ様子](https://raw.githubusercontent.com/HojooonKim/PaperDesk/media/ja/ask.gif)

### 原文の上に翻訳、ライトとダーク

翻訳の表示を**原文の上に**に切り替えると、各段落の位置でそのまま訳文を読めます。**並べて表示**や**翻訳を隠す**も選べます。ダークモードでも PDF の紙面は白いままです。

![ダークモードで原文の上に翻訳を表示した画面](https://raw.githubusercontent.com/HojooonKim/PaperDesk/media/ja/dark-overlay.png)

### そのほか

- テーマ別フォルダ（サブフォルダは無制限）、ドラッグ＆ドロップで整理・取り込み、PDF から論文タイトルを自動認識
- 論文情報と自動整理：著者・年・掲載先・DOI を arXiv と OpenAlex から取得し、フォルダを選ばずに追加した論文は AI が選んだ（または作った）フォルダに入れます。論文 1 件やフォルダ全体の BibTeX をコピーできます。
- 論文の要約、文書内検索、ライブラリ全体の検索
- 別の論文を読んでいる間も翻訳が続き、アプリを開き直したあとに再開可能
- 画面の言語は English・한국어・日本語・简体中文、翻訳と回答の言語は別に選択
- システム・ライト・ダークのテーマ、パネル幅の調整
- Claude デスクトップや Codex からライブラリを読める MCP サーバー
- PDF・メモ・翻訳・会話をまとめてバックアップ・復元

## インストール

必要なもの：Apple Silicon の Mac（macOS 15 以降）または Windows 10/11（x64）、Python 3.12、git、空き容量約 1.5 GB。

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

インストール後、macOS では「アプリケーション」（Applications）から、Windows ではスタートメニューから **PaperDesk** を開きます。Windows では Python は [python.org](https://www.python.org/downloads/windows/) のものを使ってください。Windows 11 のスマート アプリ コントロールが uv や conda でインストールした Python をブロックすることがあります。

`--auto-update` を付けると、新しいバージョンを GitHub からバックグラウンドで受け取り、次にアプリを開いたときに適用します。設定の **今すぐ再起動** を押すとすぐに適用されます。ライブラリはアプリとは別に保存されるので、更新やアンインストールをしても残ります。インストールの確認・アンインストール・トラブルシューティングは [INSTALL.md](INSTALL.md) を参照してください。

## AI の接続

いつも使っている AI をつなぎます。初回起動時に、ログイン済みの Codex CLI または Claude Code を自動で見つけて選びます。

| 接続 | 必要なもの |
| --- | --- |
| Codex CLI | 自分で行った `codex login` |
| Claude Code | 自分で行った Claude Code へのログイン |
| OpenAI API / Claude API | API キー（macOS のキーチェーン・Windows の資格情報マネージャーに保存） |
| Ollama / vLLM・OpenAI 互換サーバー | サーバーのアドレス（必要ならサーバーのキー） |

PaperDesk は Codex や Claude のログイン情報を読み取ったり保存したりしません。詳しくは [docs/ai-integrations.md](docs/ai-integrations.md) を参照してください。

## データは自分のコンピュータだけに

| 内容 | 場所 |
| --- | --- |
| PDF・ライブラリ・翻訳・ハイライト・メモ・会話 | macOS `~/Library/Application Support/Paperdesk`、Windows `%LOCALAPPDATA%\Paperdesk` |
| API キー | macOS のキーチェーン / Windows の資格情報マネージャー |

PDF の閲覧、プレビュー、保存済みの翻訳・メモ・会話はオフラインで使えます。レイアウト解析も手元で Docling を使って行い、最初の 1 回だけ解析モデル（約 170 MB）をダウンロードします。インターネットに接続するのは、選んだ AI（手元の Ollama や vLLM なら不要）、論文情報の取得（タイトルと arXiv 番号・DOI のみ）や論文の検索・ダウンロード時の arXiv と OpenAlex、自分でクリックしたリンク、そしてオンにしている場合のアップデート確認（GitHub）だけです。詳しくは [docs/privacy.md](docs/privacy.md) を参照してください。

## ドキュメント

- [INSTALL.md](INSTALL.md)：インストール・更新・アンインストール・トラブルシューティング（英語）
- [docs/support.md](docs/support.md)：サポート範囲、バックアップと復旧（英語）
- [docs/keyboard-shortcuts.md](docs/keyboard-shortcuts.md)：リーダーのショートカット
- [docs/ai-integrations.md](docs/ai-integrations.md)、[docs/privacy.md](docs/privacy.md)：AI 接続とデータ
- [docs/development.md](docs/development.md)：構成と開発（韓国語）

## ライセンス

[Apache License 2.0](LICENSE) で配布しています。サードパーティ製ソフトウェアにはそれぞれのライセンスが適用されます。[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) を参照してください。

スクリーンショットでは、アプリの機能を示すために論文「Attention Is All You Need」（Vaswani ほか、2017、[arXiv:1706.03762](https://arxiv.org/abs/1706.03762)）を使用しています。
