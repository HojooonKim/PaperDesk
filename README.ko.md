<div align="center">

# PaperDesk

**원문 바로 옆에서, 내 언어로 읽는 논문 리더**

[English](README.md) · **한국어** · [简体中文](README.zh.md) · [日本語](README.ja.md)

</div>

![PaperDesk: PDF와 번역을 나란히 보고, 선택한 문장을 AI 도우미가 설명하는 화면](https://raw.githubusercontent.com/HojooonKim/PaperDesk/media/ko/reader.png)

PaperDesk는 macOS·Windows에서 논문을 읽는 데스크톱 앱입니다. 논문 PDF를 주제별 폴더로 정리하고, 논문 전체를 원문 옆에 번역하며, 고른 부분을 이미 쓰고 있는 AI에게 바로 물어볼 수 있습니다. 논문과 기록은 모두 내 컴퓨터에만 저장됩니다.

> **베타**: 지금은 소스에서 설치합니다. Claude Code나 Codex에게 맡기면 가장 간단해요.

## 명령 한 줄로 설치

[Claude Code](https://claude.com/claude-code)나 [Codex](https://github.com/openai/codex)를 쓰고 있다면 터미널에서 아래 중 하나를 실행하세요.

```sh
claude "https://raw.githubusercontent.com/HojooonKim/PaperDesk/main/INSTALL.md 를 따라 이 컴퓨터에 PaperDesk를 설치해 줘"
```

```sh
codex "https://raw.githubusercontent.com/HojooonKim/PaperDesk/main/INSTALL.md 를 따라 이 컴퓨터에 PaperDesk를 설치해 줘"
```

에이전트는 [INSTALL.md](INSTALL.md)를 따라 컴퓨터 환경을 확인합니다. Python 3.12나 git처럼 시스템 전체에 설치할 것이 있으면 먼저 물어보고, 마지막에 여는 방법과 남은 설정을 알려 줘요. 로그인 정보와 API 키는 다루지 않습니다.

다른 코딩 에이전트에는 따옴표 안의 문장을 붙여 넣으면 됩니다. 직접 설치하려면 [설치](#설치)를 보세요.

## 주요 기능

### 원문과 함께 움직이는 번역

논문을 열면 내 컴퓨터에서 단·제목·그림·수식 같은 구성을 분석한 뒤, 연결한 AI로 본문을 문단 단위로 번역합니다. 번역은 끝난 문단부터 바로 보입니다. 각 쪽의 번역은 그 쪽 옆에 붙어 스크롤과 함께 움직이고, 원문 문단에 마우스를 올리면 해당 번역이, 번역에 올리면 원문이 표시됩니다.

![스크롤: PDF 쪽과 번역이 함께 움직이는 모습](https://raw.githubusercontent.com/HojooonKim/PaperDesk/media/ko/scroll.gif)

### 그림·표·참고문헌 미리보기

"Figure 2"나 "[38, 2, 9]"에 마우스를 올리면 읽던 위치를 벗어나지 않고 그림·표·참고문헌을 바로 볼 수 있습니다. 번역문 안의 참조에도 똑같이 동작합니다. 참고문헌은 **읽어볼 논문**에 추가하거나, arXiv·Google Scholar에서 열거나, AI에게 어떤 논문인지 물어볼 수 있습니다.

![그림 참조와 참고문헌에 마우스를 올린 모습](https://raw.githubusercontent.com/HojooonKim/PaperDesk/media/ko/preview.gif)

### 선택해서 번역·설명·질문

글을 선택하고 **번역**(T)·**설명**(E)·**뜻**(W)·**질문**(Q)을 고르거나, **하이라이트**(H)·**메모**(C)를 남깁니다. 답은 **AI 도우미**에 나오고 대화는 논문마다 따로 저장됩니다. 그림·표·수식은 **영역 선택**으로 드래그해 물어볼 수 있습니다.

![문장을 선택하고 설명을 고르는 모습](https://raw.githubusercontent.com/HojooonKim/PaperDesk/media/ko/ask.gif)

### 원문 위에 번역, 라이트·다크

번역 표시를 **원문 위에**로 바꾸면 문단 자리에서 바로 번역을 읽을 수 있습니다. **나란히**·**번역 숨기기**도 고를 수 있습니다. 다크 모드에서도 PDF 지면은 흰색 그대로입니다.

![다크 모드에서 원문 위에 번역을 표시한 화면](https://raw.githubusercontent.com/HojooonKim/PaperDesk/media/ko/dark-overlay.png)

### 그 밖에

- 주제별 폴더(하위 폴더 무제한), 끌어다 놓기로 정리·가져오기, PDF에서 논문 제목 자동 인식
- 논문 정보와 자동 정리: 저자·연도·학회·DOI를 arXiv·OpenAlex에서 채우고, 폴더 없이 추가한 논문은 AI가 고른(또는 새로 만든) 폴더에 넣습니다. 논문 한 편이나 폴더 전체의 BibTeX를 복사할 수 있습니다.
- 논문 요약, 문서 내 찾기, 서재 전체 검색
- 다른 논문을 읽는 동안에도 번역이 계속되고, 앱을 다시 열면 이어서 진행할 수 있음
- 화면 언어 English·한국어·日本語·简体中文, 번역·답변 언어는 따로 선택
- 시스템·라이트·다크 테마, 창 비율 조절
- Claude 데스크톱·Codex가 내 서재를 읽을 수 있는 MCP 서버
- PDF·메모·번역·대화를 한꺼번에 백업·복원

## 설치

필요한 것: Apple Silicon Mac(macOS 15 이상) 또는 Windows 10/11(x64), Python 3.12, git, 여유 공간 약 1.5GB.

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

설치가 끝나면 macOS는 응용 프로그램(Applications)에서, Windows는 시작 메뉴에서 **PaperDesk**를 엽니다. Windows에서는 [python.org](https://www.python.org/downloads/windows/)의 Python을 쓰세요. Windows 11의 스마트 앱 컨트롤이 uv·conda로 설치한 Python을 막을 수 있습니다.

`--auto-update`를 붙이면 새 버전을 GitHub에서 백그라운드로 받아 두었다가 다음에 앱을 열 때 적용합니다. 설정에서 **지금 다시 시작**을 누르면 바로 적용돼요. 서재는 앱과 따로 저장되므로 업데이트하거나 제거해도 그대로 남습니다. 설치 확인·제거·문제 해결은 [INSTALL.md](INSTALL.md)를 참고하세요.

## AI 연결

이미 쓰고 있는 AI를 연결합니다. 처음 실행하면 로그인된 Codex CLI나 Claude Code를 자동으로 찾아 고릅니다.

| 연결 | 필요한 것 |
| --- | --- |
| Codex CLI | 직접 한 `codex login` |
| Claude Code | 직접 한 Claude Code 로그인 |
| OpenAI API / Claude API | API 키 (macOS 키체인·Windows 자격 증명 관리자에 보관) |
| Ollama / vLLM·OpenAI 호환 서버 | 서버 주소 (필요하면 서버 키) |

PaperDesk는 Codex·Claude 로그인 정보를 읽거나 저장하지 않습니다. 자세한 근거는 [docs/ai-integrations.md](docs/ai-integrations.md)에 있습니다.

## 데이터는 내 컴퓨터에만

| 항목 | 위치 |
| --- | --- |
| PDF·서재·번역·하이라이트·메모·대화 | macOS `~/Library/Application Support/Paperdesk`, Windows `%LOCALAPPDATA%\Paperdesk` |
| API 키 | macOS 키체인 / Windows 자격 증명 관리자 |

PDF 읽기, 미리보기, 저장된 번역·메모·대화는 오프라인으로 동작합니다. 문서 구조 분석도 내 컴퓨터에서 Docling으로 하며, 처음 한 번만 분석 모델(약 170MB)을 내려받습니다. 외부 연결은 선택한 AI(내 컴퓨터의 Ollama·vLLM이면 필요 없음), 논문 정보 조회(제목과 arXiv 번호·DOI만)나 논문 검색·다운로드를 할 때의 arXiv·OpenAlex, 직접 누른 링크, 그리고 켜 두었을 때의 업데이트 확인(GitHub)에만 씁니다. 자세한 내용은 [docs/privacy.md](docs/privacy.md)를 참고하세요.

## 문서

- [INSTALL.md](INSTALL.md): 설치·업데이트·제거·문제 해결 (영문)
- [docs/support.md](docs/support.md): 지원 범위, 백업과 복구 (영문)
- [docs/keyboard-shortcuts.md](docs/keyboard-shortcuts.md): 리더 단축키
- [docs/ai-integrations.md](docs/ai-integrations.md), [docs/privacy.md](docs/privacy.md): AI 연결과 데이터
- [docs/development.md](docs/development.md): 구조와 개발

## 라이선스

[Apache License 2.0](LICENSE)로 배포합니다. 제3자 소프트웨어에는 각각의 라이선스가 적용되며 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)에서 확인할 수 있습니다.

화면 예시에는 앱 기능을 보여 주기 위해 "Attention Is All You Need"(Vaswani 외, 2017, [arXiv:1706.03762](https://arxiv.org/abs/1706.03762))를 사용했습니다.
