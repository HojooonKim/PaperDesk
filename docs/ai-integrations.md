# AI 연동 방식과 근거 (2026-10-28 확인)

PaperDesk는 사용자가 이미 가진 AI 접근 수단을 연결한다. 원칙: 다른 회사의 로그인 정보를 읽거나 보관하거나 대신 처리하지 않는다.

## OpenAI / Codex

- **Codex CLI (`codex exec`)**: OpenAI가 비대화형 작업용으로 안내하는 연동 방식. PaperDesk는 사용자가 설치·로그인한 CLI를
  `codex exec --ephemeral --sandbox read-only --skip-git-repo-check --output-last-message <file> -`로 실행하고, 로그인 확인에는 `codex login status`를 쓴다(토큰 소모 없음).
  대화 패널은 같은 CLI의 `codex app-server`에서 읽기 전용 임시 대화를 열고, 답변 텍스트가 도착할 때마다 화면에 표시한다.
  - https://developers.openai.com/blog/codex-as-a-platform
  - https://learn.chatgpt.com/docs/app-server
- **Sign in with ChatGPT – ChatGPT plan usage (프리뷰)**: 오픈소스·로컬 앱이 사용자의 ChatGPT 요금제로 Responses API를 호출하는 공식 경로.
  `dynamic_agent_client`로 동적 등록, 호스트별 `ext_agent_host_id` 저장, PKCE + 루프백 콜백, `store:false`·`stream:true` 필수.
  유료·원격 호스팅 앱은 별도 신청이 필요하다. UI 지침: “Continue with ChatGPT” 버튼, 첫 로그인 안내, “Using ChatGPT plan” 표시, Manage usage 링크.
  현재 배포 앱에서는 제외한다. 로그인 흐름과 토큰 갱신이 미완성이며, 추론 실험 코드는 `experiments/chatgpt_plan.py`에 보관한다. ChatGPT 요금제를 연결하려면 현재 지원되는 Codex CLI를 사용한다.
  - https://developers.openai.com/siwc/token-sharing-open-source
  - https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations
  - https://developers.openai.com/siwc/ui-ux-guidelines
- **OpenAI API 키**: Responses API. 키는 macOS 키체인에 저장하고 `OPENAI_API_KEY` 환경 변수가 있으면 그것을 쓴다.

## Anthropic / Claude

- **Claude API 키**: 외부 앱·오픈소스에 권장되는 방식.
  - https://platform.claude.com/docs/en/get-api-key
- **Claude Code (`claude -p`)**: Anthropic은 외부 개발자가 Claude.ai 로그인을 자기 앱에 넣거나 요금제 인증 정보를 대신 처리하는 것을 금지하지만,
  사용자가 수정하지 않은 Claude Code에 자기 구독으로 직접 로그인하는 것은 막지 않는다고 명시한다. PaperDesk는 사용자가 설치·로그인한 `claude`를
  도구 없이(`--tools ""`) 실행만 하고 자격 증명에는 접근하지 않는다. 로그인 확인은 `claude auth status`. 사용량은 사용자의 Claude 요금제 한도에 집계된다.
  Claude Code 이름·로고는 제품명이나 로고에 쓰지 않는다(“Claude Code로 실행” 같은 사실 설명만 허용).
  - https://code.claude.com/docs/en/legal-and-compliance
  - https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan
- **Claude 데스크톱**: 앱이 Claude 데스크톱에 질문을 보내는 공식 경로는 없다. 대신 PaperDesk가 MCP 서버(`paperdesk mcp`)를 제공해
  Claude 데스크톱이 논문 목록·본문·검색을 도구로 호출한다. 추후 `.mcpb` 데스크톱 확장으로 묶어 한 번에 설치할 수 있다.
  - https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop
  - https://github.com/modelcontextprotocol/mcpb

## 로컬·자체 서버

- **Ollama**: `http://localhost:11434/v1`의 OpenAI 호환 API. 문서가 컴퓨터 밖으로 나가지 않는다.
- **vLLM·LM Studio·llama.cpp server**: OpenAI 호환 `/v1/models`, `/v1/chat/completions`. 모델을 비우면 서버의 첫 모델을 쓴다. `<think>…</think>`로 시작하는 추론 블록은 제거한다.

