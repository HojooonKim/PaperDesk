from __future__ import annotations

from pathlib import Path
from typing import Callable
import json
import tempfile

from ..domain.errors import ProviderFailed, ProviderUnavailable
from ..domain.models import Completion, Prompt
from ..ports.ai import CommandResult, OptionField
from .cli import WINDOWS, CliProvider, binary_option
from ..i18n import _


class CodexCliProvider(CliProvider):
    """Runs the user's own Codex CLI non-interactively (codex exec), an integration path OpenAI documents.

    Uses whatever login the CLI already has (ChatGPT plan or API key). PaperDesk never sees the credentials.
    Interactive replies use the same CLI's app-server to receive answer deltas.
    """

    id = "codex-cli"
    label = "Codex CLI"
    description = _("내 컴퓨터에 설치·로그인된 Codex CLI(codex exec)를 실행합니다. Codex 로그인(ChatGPT 요금제 또는 API 키) 사용량으로 처리됩니다.")
    docs_url = "https://developers.openai.com/codex/noninteractive"
    executable = "codex"
    supports_images = True
    # The Codex desktop app's own CLI; on Windows it lives in a per-version folder.
    extra_dirs = (("%LOCALAPPDATA%/OpenAI/Codex/bin/*",) if WINDOWS else
                  ("/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS",
                   "/Applications/Codex.app/Contents/Resources"))
    login_args = ("login", "status")
    options = (
        OptionField("model", _("모델"), placeholder=_("비워 두면 Codex 기본 모델")),
        binary_option("codex"),
    )

    def available_models(self) -> list[str]:
        path = self.locate()
        return self.context.runner.codex_models(path) if path else []

    def interpret_login(self, result: CommandResult) -> tuple[bool, str]:
        line = (result.stdout or result.stderr).strip().splitlines()[:1]
        if result.returncode == 0 and line:
            return True, line[0]
        return False, _("Codex에 로그인되어 있지 않아요. 터미널에서 'codex login'을 실행하세요.")

    def complete_stream(self, prompt: Prompt, on_delta: Callable[[str], None]) -> Completion:
        path = self.locate()
        if not path:
            raise ProviderUnavailable(self.status().detail)
        argv = [path, 'app-server', '--stdio']
        for feature in ('hooks', 'plugins', 'apps', 'shell_tool', 'unified_exec', 'multi_agent', 'shell_snapshot'):
            argv.extend(('--disable', feature))
        argv.extend(('-c', 'web_search=disabled', '-c', 'notify=[]', '-c', 'project_doc_max_bytes=0'))
        with tempfile.TemporaryDirectory(prefix="paperdesk-chat-") as folder:
            with self.context.runner.codex_session(argv, Path(folder), self.timeout) as (send, receive):
                def next_event():
                    while True:
                        event = receive()
                        if 'method' not in event or 'id' not in event:
                            return event
                        # The reader never grants tools, credentials or interactive approvals.
                        send({'id': event['id'], 'error': {'code': -32601, 'message': 'Unsupported request'}})

                def rpc(number, method, params):
                    send({'id': number, 'method': method, 'params': params})
                    while True:
                        event = next_event()
                        if event.get('id') == number:
                            if 'error' in event:
                                raise self.failure(CommandResult(1, '', str(event['error'])))
                            return event['result']

                # app-server merges configuration tables. Disable each configured MCP server before starting a thread.
                config = rpc(2, 'config/read', {'cwd': folder})['config']
                servers = {name: {'enabled': False} for name in (config.get('mcp_servers') or {})}
                thread = rpc(3, 'thread/start', {'cwd': folder, 'ephemeral': True, 'sandbox': 'read-only',
                    'approvalPolicy': 'never', 'modelProvider': 'openai', 'model': self.model or None,
                    'baseInstructions': prompt.system, 'config': {'mcp_servers': servers}})
                thread_id = thread['thread']['id']
                inputs = [{'type': 'text', 'text': prompt.user}]
                inputs.extend({'type': 'image', 'url': image.data_url} for image in prompt.images)
                send({'id': 4, 'method': 'turn/start', 'params': {'threadId': thread_id, 'input': inputs}})
                parts, answer, ignored = [], '', set()
                while True:
                    event = next_event()
                    if event.get('id') == 4 and 'error' in event:
                        raise self.failure(CommandResult(1, '', str(event['error'])))
                    params = event.get('params', {})
                    if params.get('threadId') != thread_id:
                        continue
                    method = event.get('method')
                    item = params.get('item', {})
                    if method == 'item/started' and item.get('phase') == 'commentary':
                        ignored.add(item['id'])
                    elif method == 'item/agentMessage/delta' and params['itemId'] not in ignored:
                        parts.append(params['delta'])
                        on_delta(params['delta'])
                    elif method == 'item/completed' and item.get('type') == 'agentMessage' and item.get('phase') != 'commentary':
                        answer = item.get('text', '')
                    elif method == 'turn/completed':
                        turn = params['turn']
                        if turn['status'] != 'completed':
                            raise self.failure(CommandResult(1, '', str(turn.get('error') or turn['status'])))
                        break
        text = answer or ''.join(parts)
        if not text.strip():
            raise ProviderFailed(_("{name}가 빈 응답을 돌려줬어요.", name=self.label))
        return Completion(text, self.id, thread.get('model') or self.model)

    def build_command(self, path: str, prompt: Prompt, workdir: Path) -> list[str]:
        argv = [
            path, "exec",
            "--ignore-user-config",
            "--disable", "shell_tool",
            "--disable", "unified_exec",
            "--disable", "multi_agent",
            "--disable", "shell_snapshot",
            "--skip-git-repo-check",
            "--ephemeral",
            "--sandbox", "read-only",
            "--color", "never",
            "--output-last-message", str(workdir / "last-message.txt"),
        ]
        if self.model:
            argv += ["--model", self.model]
        if prompt.response_schema:
            schema = workdir / "response-schema.json"
            schema.write_text(json.dumps(prompt.response_schema), encoding="utf-8")
            argv += ["--output-schema", str(schema)]
        for number, image in enumerate(prompt.images, start=1):
            path_ = workdir / f"image-{number}.{'jpg' if image.media_type == 'image/jpeg' else 'png'}"
            path_.write_bytes(image.data)
            argv.append(f"--image={path_}")  # '=' form: --image takes several values and would swallow '-'
        argv.append("-")  # prompt comes from stdin
        return argv

    def parse_output(self, result: CommandResult, workdir: Path) -> str:
        last = workdir / "last-message.txt"
        if last.exists() and last.read_text(encoding="utf-8").strip():
            return last.read_text(encoding="utf-8")
        return result.stdout

