from contextlib import contextmanager
import json
import unittest
from pathlib import Path

from paperdesk.domain.errors import ProviderFailed
from paperdesk.domain.models import Prompt
from paperdesk.infrastructure.secrets import MemorySecretStore
from paperdesk.ports.ai import CommandResult, CommandRunner, HttpClient, ProviderContext
from paperdesk.providers.anthropic_api import AnthropicApiProvider
from paperdesk.providers.claude_code import ClaudeCodeProvider
from paperdesk.providers.codex_cli import CodexCliProvider
from paperdesk.providers.openai_api import OpenAIApiProvider
from paperdesk.providers.openai_compatible import OllamaProvider, OpenAICompatibleServerProvider
from paperdesk.providers.registry import default_registry

PROMPT = Prompt("SYSTEM", "USER")


class FakeRunner(CommandRunner):
    def __init__(self, result, write_last=None):
        self.result, self.write_last, self.calls = result, write_last, []

    def run(self, argv, *, input_text, cwd, timeout):
        self.calls.append((argv, input_text))
        if self.write_last is not None:
            Path(cwd, "last-message.txt").write_text(self.write_last, encoding="utf-8")
        return self.result


class FakeHttp(HttpClient):
    def __init__(self, get=None, post=None, events=None):
        self.get, self.post, self.events, self.calls = get, post, events or [], []

    def get_json(self, url, *, headers, timeout):
        self.calls.append(("GET", url, headers, None))
        return self.get

    def post_json(self, url, *, headers, body, timeout):
        self.calls.append(("POST", url, headers, body))
        return self.post

    def stream_sse(self, url, *, headers, body, timeout):
        self.calls.append(("SSE", url, headers, body))
        return iter(self.events)


def context(provider_id, values=None, secrets=None, runner=None, http=None, environ=None):
    return ProviderContext(provider_id, values or {}, MemorySecretStore(secrets), runner or FakeRunner(CommandResult(0, "", "")),
                           http or FakeHttp(), environ or {})


def found(path):
    return lambda name: path


class CliProviderTests(unittest.TestCase):
    def test_codex_exec_reads_last_message_and_passes_prompt_on_stdin(self):
        runner = FakeRunner(CommandResult(0, "noise", ""), write_last="번역 결과")
        provider = CodexCliProvider(context("codex-cli", {"model": "gpt-x"}, runner=runner), which=found("/bin/codex"))
        completion = provider.complete(PROMPT)
        argv, stdin = runner.calls[0]
        self.assertEqual(completion.text, "번역 결과")
        self.assertEqual(argv[:2], ["/bin/codex", "exec"])
        self.assertIn("--ephemeral", argv)
        self.assertEqual(argv[argv.index("--sandbox") + 1], "read-only")
        self.assertEqual(argv[argv.index("--model") + 1], "gpt-x")
        self.assertEqual(argv[-1], "-")
        self.assertIn("SYSTEM", stdin)
        self.assertIn("USER", stdin)

    def test_codex_chat_forwards_only_answer_deltas_before_completion(self):
        sent, deltas = [], []
        thread = {'threadId': 'thread'}
        def events():
            yield {'id': 2, 'result': {'config': {'mcp_servers': {'external': {}}}}}
            yield {'id': 3, 'result': {'thread': {'id': 'thread'}, 'model': 'chosen'}}
            yield {'id': 4, 'result': {'turn': {'id': 'turn'}}}
            yield {'method': 'item/started', 'params': {**thread, 'item': {'id': 'c', 'phase': 'commentary'}}}
            yield {'method': 'item/agentMessage/delta', 'params': {**thread, 'itemId': 'c', 'delta': 'comment'}}
            for text in ('첫', ' 문장'):
                yield {'method': 'item/agentMessage/delta', 'params': {**thread, 'itemId': 'a', 'delta': text}}
                self.assertEqual(deltas[-1], text)
            yield {'method': 'turn/completed', 'params': {**thread, 'turn': {'status': 'completed'}}}

        @contextmanager
        def session(path, folder, timeout):
            yield sent.append, events().__next__
        runner = FakeRunner(CommandResult(0, '', ''))
        runner.codex_session = session
        provider = CodexCliProvider(context('codex-cli', {'model': 'chosen'}, runner=runner), which=found('/bin/codex'))
        answer = provider.complete_stream(PROMPT, deltas.append)
        self.assertEqual(deltas, ['첫', ' 문장'])
        self.assertEqual((answer.text, answer.model), ('첫 문장', 'chosen'))
        params = sent[1]['params']
        self.assertTrue(params['ephemeral'])
        self.assertEqual((params['sandbox'], params['approvalPolicy']), ('read-only', 'never'))
        self.assertFalse(params['config']['mcp_servers']['external']['enabled'])
        self.assertEqual(params['model'], 'chosen')

    def test_claude_code_runs_without_tools_and_parses_json(self):
        runner = FakeRunner(CommandResult(0, json.dumps({"result": "설명", "is_error": False}), ""))
        provider = ClaudeCodeProvider(context("claude-code", runner=runner), which=found("/bin/claude"))
        self.assertEqual(provider.complete(PROMPT).text, "설명")
        argv, stdin = runner.calls[0]
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertEqual(argv[argv.index("--system-prompt") + 1], "SYSTEM")
        self.assertIn("--no-session-persistence", argv)
        self.assertEqual(stdin, "USER")

    def test_claude_code_error_payload_raises(self):
        runner = FakeRunner(CommandResult(0, json.dumps({"is_error": True, "result": "Not logged in"}), ""))
        provider = ClaudeCodeProvider(context("claude-code", runner=runner), which=found("/bin/claude"))
        with self.assertRaises(ProviderFailed):
            provider.complete(PROMPT)

    def test_login_status_is_checked_without_spending_tokens(self):
        runner = FakeRunner(CommandResult(1, json.dumps({"loggedIn": False, "authMethod": "none"}), ""))
        provider = ClaudeCodeProvider(context("claude-code", runner=runner), which=found("/bin/claude"))
        state = provider.status()
        self.assertFalse(state.available)
        self.assertIn("/login", state.detail)
        self.assertEqual(runner.calls[0][0], ["/bin/claude", "auth", "status"])
        runner = FakeRunner(CommandResult(0, "Logged in using ChatGPT\n", ""))
        state = CodexCliProvider(context("codex-cli", runner=runner), which=found("/bin/codex")).status()
        self.assertTrue(state.available)
        self.assertIn("Logged in using ChatGPT", state.detail)

    def test_claude_failure_shows_reason(self):
        payload = json.dumps({"is_error": True, "result": "Failed to authenticate: OAuth session expired"})
        provider = ClaudeCodeProvider(context("claude-code", runner=FakeRunner(CommandResult(1, payload, ""))), which=found("/bin/claude"))
        with self.assertRaises(ProviderFailed) as caught:
            provider.complete(PROMPT)
        self.assertEqual(caught.exception.code, 'auth_required')
        self.assertIn("다시 로그인", str(caught.exception))

    def test_missing_cli_is_unavailable(self):
        provider = CodexCliProvider(context("codex-cli", {"binary": "/definitely/missing"}), which=found(None))
        self.assertFalse(provider.status().available)


class HttpProviderTests(unittest.TestCase):
    def test_openai_compatible_lists_models_and_strips_thinking(self):
        http = FakeHttp(get={"data": [{"id": "qwen3:8b"}]},
                        post={"choices": [{"message": {"content": "<think>hmm</think>\n답변"}}]})
        provider = OllamaProvider(context("ollama", http=http))
        state = provider.status()
        self.assertTrue(state.available)
        self.assertEqual(state.models, ("qwen3:8b",))
        completion = provider.complete(PROMPT)
        self.assertEqual(completion.text, "답변")
        self.assertEqual(completion.model, "qwen3:8b")
        method, url, headers, body = http.calls[-1]
        self.assertEqual(url, "http://localhost:11434/v1/chat/completions")
        self.assertEqual(body["messages"][0], {"role": "system", "content": "SYSTEM"})

    def test_internal_vllm_server_uses_custom_url_and_optional_key(self):
        http = FakeHttp(get={"data": [{"id": "Qwen/Qwen3-32B"}]}, post={"choices": [{"message": {"content": "ok"}}]})
        provider = OpenAICompatibleServerProvider(context("openai-compatible", {"base_url": "http://10.0.0.5:8000/v1/"},
                                                          secrets={"openai-compatible.api_key": "k"}, http=http))
        provider.complete(PROMPT)
        self.assertTrue(all(call[1].startswith("http://10.0.0.5:8000/v1/") for call in http.calls))
        self.assertEqual(http.calls[-1][2], {"Authorization": "Bearer k"})

    def test_openai_responses_stream_and_env_key_override(self):
        events = [{"type": "response.output_text.delta", "delta": "안녕"}, {"type": "response.output_text.delta", "delta": "하세요"},
                  {"type": "response.completed"}]
        http = FakeHttp(events=events)
        provider = OpenAIApiProvider(context("openai-api", http=http, secrets={"openai-api.api_key": "stored"},
                                             environ={"OPENAI_API_KEY": "from-env"}))
        self.assertEqual(provider.complete(PROMPT).text, "안녕하세요")
        _, url, headers, body = http.calls[0]
        self.assertEqual(headers["Authorization"], "Bearer from-env")
        self.assertEqual((body["store"], body["stream"], body["instructions"]), (False, True, "SYSTEM"))

    def test_responses_stream_without_completion_fails(self):
        http = FakeHttp(events=[{"type": "response.output_text.delta", "delta": "half"}])
        provider = OpenAIApiProvider(context("openai-api", http=http, secrets={"openai-api.api_key": "k"}))
        with self.assertRaises(ProviderFailed):
            provider.complete(PROMPT)

    def test_anthropic_messages_request(self):
        http = FakeHttp(post={"content": [{"type": "text", "text": "요약"}], "stop_reason": "end_turn"})
        provider = AnthropicApiProvider(context("anthropic-api", http=http, secrets={"anthropic-api.api_key": "sk-ant"}))
        self.assertEqual(provider.complete(PROMPT).text, "요약")
        _, url, headers, body = http.calls[0]
        self.assertEqual(headers["x-api-key"], "sk-ant")
        self.assertEqual(body["system"], "SYSTEM")
        self.assertEqual(body["model"], "claude-haiku-5-5")


class RegistryTests(unittest.TestCase):
    def test_describe_never_exposes_secret_values(self):
        registry = default_registry()
        for provider_id in registry.ids():
            ctx = context(provider_id, secrets={f"{provider_id}.api_key": "SECRET", f"{provider_id}.access_token": "SECRET"},
                          http=FakeHttp(get={"data": []}))
            described = registry.create(provider_id, ctx).describe()
            self.assertNotIn("SECRET", json.dumps(described), provider_id)

