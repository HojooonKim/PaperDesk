from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, ClassVar, ContextManager, Iterator, Mapping

from ..domain.models import Completion, Prompt, ProviderStatus
from .secrets import SecretStore


@dataclass(frozen=True)
class OptionField:
    """One user setting a provider needs. The settings page renders these without provider-specific code.

    kind: "text" | "url" | "path" | "secret". Secret values go to the SecretStore, never to settings.json.
    env:  optional environment variable that overrides a secret (for example OPENAI_API_KEY).
    """

    key: str
    label: str
    kind: str = "text"
    default: str = ""
    placeholder: str = ""
    help: str = ""
    env: str = ""

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("key", "label", "kind", "default", "placeholder", "help", "env")}


class CommandRunner(ABC):
    @abstractmethod
    def run(self, argv: list[str], *, input_text: str, cwd: Path, timeout: float) -> "CommandResult": ...

    def codex_session(self, argv: list[str], cwd: Path, timeout: float) -> ContextManager:
        """Open the CLI's app-server JSON-RPC transport for an ephemeral chat."""
        raise NotImplementedError

    def codex_models(self, executable: str) -> list[str]:
        return []

    def close(self) -> None:
        pass


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class HttpClient(ABC):
    @abstractmethod
    def get_json(self, url: str, *, headers: Mapping[str, str], timeout: float) -> Any: ...

    @abstractmethod
    def post_json(self, url: str, *, headers: Mapping[str, str], body: dict, timeout: float) -> Any: ...

    @abstractmethod
    def stream_sse(self, url: str, *, headers: Mapping[str, str], body: dict, timeout: float) -> Iterator[dict]:
        """POST and yield each server-sent event's JSON payload."""


@dataclass(frozen=True)
class ProviderContext:
    """Everything a provider may use. Built by SettingsService; tests pass fakes."""

    provider_id: str
    values: Mapping[str, str]
    secrets: SecretStore
    runner: CommandRunner
    http: HttpClient
    environ: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))

    def secret_name(self, key: str) -> str:
        return f"{self.provider_id}.{key}"

    def value(self, option: OptionField) -> str:
        if option.kind == "secret":
            if option.env and self.environ.get(option.env, "").strip():
                return self.environ[option.env].strip()
            return (self.secrets.get(self.secret_name(option.key)) or "").strip()
        return (self.values.get(option.key) or option.default or "").strip()


class AIProvider(ABC):
    """One way of reaching a language model: an HTTP API, a local CLI login, a local model server, or an offline stub.

    Subclasses declare metadata and options as class attributes, then implement status() and complete().
    """

    id: ClassVar[str]
    label: ClassVar[str]
    kind: ClassVar[str]  # "offline" | "local-cli" | "api" | "account" | "local-server"
    description: ClassVar[str] = ""
    docs_url: ClassVar[str] = ""
    options: ClassVar[tuple[OptionField, ...]] = ()
    supports_images: ClassVar[bool] = False  # True when complete() forwards Prompt.images to the model

    def __init__(self, context: ProviderContext) -> None:
        self.context = context

    def option(self, key: str) -> str:
        for item in self.options:
            if item.key == key:
                return self.context.value(item)
        raise KeyError(key)

    @property
    def model(self) -> str:
        return self.option("model") if any(o.key == "model" for o in self.options) else ""

    def available_models(self) -> list[str]:
        return list(self.status().models)

    def resolve_model(self) -> str:
        """Resolve an implicit model before persisting a request."""
        return self.model

    @abstractmethod
    def status(self) -> ProviderStatus:
        """Check readiness without spending tokens. Local probes must use short timeouts."""

    @abstractmethod
    def complete(self, prompt: Prompt) -> Completion:
        """Run one prompt and return the model's text."""

    def complete_stream(self, prompt: Prompt, on_delta: Callable[[str], None]) -> Completion:
        return self.complete(prompt)

    def describe(self) -> dict:
        state = self.status()
        fields = []
        for item in self.options:
            entry = item.to_dict()
            if item.kind == "secret":
                entry["has_value"] = bool(self.context.value(item))
                entry["from_env"] = bool(item.env and self.context.environ.get(item.env, "").strip())
            else:
                entry["value"] = self.context.values.get(item.key, "")
            fields.append(entry)
        return {
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "description": self.description,
            "docs_url": self.docs_url,
            "model": self.model,
            "available": state.available,
            "detail": state.detail,
            "models": list(state.models),
            "supports_images": self.supports_images,
            "options": fields,
        }

