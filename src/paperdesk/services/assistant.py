from __future__ import annotations

import hashlib
import json
from typing import Callable

from ..domain.errors import InvalidInput, ProviderFailed, ProviderUnavailable
from ..domain.models import AssistRequest, AssistTask, Completion
from ..ports.ai import AIProvider
from ..ports.repositories import CompletionCache
from .prompts import PROMPT_VERSION, PromptBuilder
from ..i18n import _

MAX_TEXT = 80_000
MAX_IMAGES = 2
MAX_IMAGE_BYTES = 6 * 1024 * 1024


class AssistantService:
    """Runs reading tasks on whichever provider is active, caching identical requests locally."""

    def __init__(self, *, active_provider: Callable[[], AIProvider | None], prompts: PromptBuilder, cache: CompletionCache) -> None:
        self._active_provider = active_provider
        self._prompts = prompts
        self._cache = cache

    @staticmethod
    def _validate(request: AssistRequest) -> None:
        if not request.text.strip() and not request.images:
            raise InvalidInput(_("내용이 비어 있어요."))
        if len(request.text) + len(request.context) > MAX_TEXT:
            raise InvalidInput(_("한 번에 보내기에는 글이 너무 길어요. 범위를 줄여 주세요."))
        if len(request.images) > MAX_IMAGES or any(len(i.data) > MAX_IMAGE_BYTES for i in request.images):
            raise InvalidInput(_("이미지가 너무 커요."))

    @staticmethod
    def _key(provider: AIProvider, prompt) -> str:
        images = [hashlib.sha256(i.data).hexdigest() for i in prompt.images]
        return hashlib.sha256(json.dumps(
            [PROMPT_VERSION, provider.id, provider.model, prompt.system, prompt.user, images], ensure_ascii=False
        ).encode()).hexdigest()

    def run(self, request: AssistRequest, *, cache_only: bool = False, refresh: bool = False,
            provider: AIProvider | None = None) -> Completion | None:
        """cache_only=True returns a saved answer or None without calling the model (used to restore panels)."""
        self._validate(request)
        provider = provider or self._active_provider()
        if provider is None:
            if cache_only:
                return None
            raise ProviderUnavailable(_("AI가 연결되지 않았어요. 설정에서 사용할 AI를 고르세요."))
        prompt = self._prompts.build(request, images_supported=provider.supports_images)
        key = self._key(provider, prompt)
        # Structured translations have their own validated, per-block storage. Never reuse raw responses.
        # A folder choice is acted on once; caching it would also repeat an unusable reply on every retry.
        use_cache = request.task not in (AssistTask.TRANSLATE_BLOCKS, AssistTask.CLASSIFY)
        cached = self._cache.get(key) if use_cache else None
        if cached is not None and not refresh:
            return Completion(cached, provider.id, provider.model, cached=True)
        if cache_only:
            return None
        state = provider.status()
        if not state.available:
            raise ProviderUnavailable(state.detail)
        try:
            completion = provider.complete(prompt)
        except ProviderFailed:
            if not prompt.images:
                raise
            # Text-only local models (e.g. an Ollama model without vision) reject images: retry with text alone.
            prompt = self._prompts.build(request, images_supported=False)
            completion = provider.complete(prompt)
        if use_cache:
            self._cache.put(key, completion.text)
        return completion

