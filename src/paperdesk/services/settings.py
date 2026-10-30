from __future__ import annotations

import time
import re

from ..config import LANGUAGES
from ..domain.errors import InvalidInput
from ..domain.models import Prompt
from ..ports.ai import AIProvider, CommandRunner, HttpClient, ProviderContext
from ..ports.secrets import SecretStore
from ..ports.settings import Settings, SettingsStore
from ..providers.registry import ProviderRegistry
from ..i18n import SUPPORTED, _
from ..domain.errors import ReaderError


class SettingsService:
    """Owns user settings and builds provider instances from them."""

    def __init__(self, *, store: SettingsStore, secrets: SecretStore, registry: ProviderRegistry,
                 runner: CommandRunner, http: HttpClient) -> None:
        self._store = store
        self._secrets = secrets
        self._registry = registry
        self._runner = runner
        self._http = http

    def load(self) -> Settings:
        return self._store.load()

    def context_for(self, provider_id: str, settings: Settings | None = None) -> ProviderContext:
        current = settings or self._store.load()
        return ProviderContext(provider_id, current.options_for(provider_id), self._secrets, self._runner, self._http)

    def provider(self, provider_id: str, *, values: dict | None = None) -> AIProvider:
        from dataclasses import replace
        context = self.context_for(provider_id)
        if values is not None:
            context = replace(context, values=values)
        return self._registry.create(provider_id, context)

    def active_provider(self, settings: Settings | None = None) -> AIProvider | None:
        settings = settings or self._store.load()
        if not settings.provider or not self._registry.has(settings.provider):
            return None
        return self._registry.create(settings.provider, self.context_for(settings.provider, settings))

    def view(self) -> dict:
        settings = self._store.load()
        return {
            "provider": settings.provider if self._registry.has(settings.provider) else "",
            "target_language": settings.target_language,
            "ui_language": settings.ui_language,
            "auto_translate": settings.auto_translate,
            "auto_info": settings.auto_info,
            "auto_organize": settings.auto_organize,
            "languages": sorted(set(LANGUAGES.values())),
            "providers": [self._registry.create(pid, self.context_for(pid, settings)).describe() for pid in self._registry.ids()],
        }

    def available_models(self, provider_id: str) -> dict:
        return {"models": self.provider(provider_id).available_models()}

    def initialize_ai(self) -> dict:
        """Use existing CLI logins on first entry; never probe by sending an AI prompt."""
        current = self.load()
        candidates = [current.provider] if current.provider else [pid for pid in ('codex-cli', 'claude-code') if self._registry.has(pid)]
        for pid in candidates:
            if not self._registry.has(pid):
                continue
            provider = self.provider(pid)
            if provider.kind != 'local-cli' or not provider.status().available:
                continue
            if not provider.model:
                try:
                    models = provider.available_models()
                except (ReaderError, OSError):
                    models = []
                luna = [m for m in models if re.search(r'(?:^|-)luna(?:$|-)', m)]
                model = max(luna, key=lambda m: tuple(map(int, re.findall(r'\d+', m)))) if luna else (models[0] if models else '')
                if model:
                    self.update_provider(pid, {'model': model})
            if not current.provider:
                self.update_general(provider=pid)
            break
        return self.view()

    def discover_provider(self, provider_id: str) -> dict:
        provider = self.provider(provider_id)
        if not hasattr(provider, 'discover'):
            raise InvalidInput(_("이 연결은 CLI 설치 확인을 사용하지 않아요."))
        result = provider.discover()
        # Explicit user action; select the discovered executable, but never change models or providers silently.
        if result['selected']:
            self.update_provider(provider_id, {'binary': result['selected']})
        return result

    def update_general(self, *, provider: str | None = None, target_language: str | None = None,
                       ui_language: str | None = None, auto_translate: bool | None = None,
                       auto_info: bool | None = None, auto_organize: bool | None = None) -> Settings:
        settings = self._store.load()
        if auto_translate is not None:
            if not isinstance(auto_translate, bool):
                raise InvalidInput(_("자동 번역 설정을 확인해 주세요."))
            settings.auto_translate = auto_translate
        for name, value in (("auto_info", auto_info), ("auto_organize", auto_organize)):
            if value is not None:
                if not isinstance(value, bool):
                    raise InvalidInput(_("자동 정리 설정을 확인해 주세요."))
                setattr(settings, name, value)
        if provider is not None:
            if provider and not self._registry.has(provider):
                raise InvalidInput(_("알 수 없는 AI 연결: {id}", id=provider))
            settings.provider = provider
        if ui_language is not None:
            if ui_language != "system" and ui_language not in SUPPORTED:
                raise InvalidInput(_("지원하지 않는 화면 언어예요."))
            settings.ui_language = ui_language
        if target_language is not None:
            language = " ".join(str(target_language).split())
            if not language or len(language) > 40:
                raise InvalidInput(_("번역 언어를 확인해 주세요."))
            settings.target_language = language
        self._store.save(settings)
        return settings

    def update_provider(self, provider_id: str, values: dict) -> dict:
        """values: {option_key: str | None}. For secrets, '' or None deletes; omitted keys stay unchanged."""
        cls = self._registry.get_class(provider_id)
        fields = {item.key: item for item in cls.options}
        settings = self._store.load()
        stored = settings.options_for(provider_id)
        context = self.context_for(provider_id, settings)
        for key, raw in values.items():
            if key not in fields:
                raise InvalidInput(_("알 수 없는 설정 항목: {key}", key=key))
            value = "" if raw is None else str(raw).strip()
            if len(value) > 4000:
                raise InvalidInput(_("값이 너무 길어요."))
            if fields[key].kind == "secret":
                if value:
                    self._secrets.set(context.secret_name(key), value)
                else:
                    self._secrets.delete(context.secret_name(key))
            elif value:
                stored[key] = value
            else:
                stored.pop(key, None)
        settings.provider_options[provider_id] = stored
        self._store.save(settings)
        return self.provider(provider_id).describe()

    def test_provider(self, provider_id: str) -> dict:
        provider = self.provider(provider_id)
        state = provider.status()
        if not state.available:
            return {"ok": False, "message": state.detail}
        started = time.monotonic()
        try:
            completion = provider.complete(Prompt("Reply with text only. Do not use tools.", "Reply with exactly: OK"))
        except ReaderError as error:
            return {"ok": False, "code": error.code, "message": error.args[0]}
        return {"ok": True, "message": completion.text.strip()[:200], "model": completion.model,
                "seconds": round(time.monotonic() - started, 1)}
