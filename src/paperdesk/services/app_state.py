"""Per-user app state that used to live in the web view's localStorage.

Keeping it in the app's own database means it survives a port change, a reinstall of the web view
storage, or opening the same library from another shell (native window, browser during development).
"""

from __future__ import annotations

import json
from typing import Any, Callable

from ..domain.errors import InvalidInput
from ..domain.models import utcnow
from ..i18n import _
from ..ports.repositories import ConversationRepository, PreferenceRepository
from .library import LibraryService

MAX_TURNS = 80
MAX_CONVERSATION_BYTES = 4 * 1024 * 1024


def _one_of(*choices: str) -> Callable[[Any], bool]:
    return lambda value: value in choices


def _pixels(low: int, high: int) -> Callable[[Any], bool]:
    return lambda value: isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _id_list(value: Any) -> bool:
    return isinstance(value, list) and len(value) <= 2000 and all(isinstance(v, str) and len(v) <= 64 for v in value)


# key -> (default, validator). Unknown keys are rejected so the table cannot grow without bound.
PREFERENCES: dict[str, tuple[Any, Callable[[Any], bool]]] = {
    "theme": ("system", _one_of("system", "dark", "light")),
    "sidebar": ("shown", _one_of("shown", "hidden")),
    "assistant": ("open", _one_of("open", "collapsed")),
    "sidebar_width": (252, _pixels(200, 420)),
    "assistant_width": (380, _pixels(300, 640)),
    "translation_mode": ("side", _one_of("side", "over", "off", "compare", "translated")),
    "translation_font": ("sans", _one_of("sans", "gulim", "serif")),
    "navigator": ("closed", _one_of("open", "closed")),
    "navigator_tab": ("sections", _one_of("sections", "pages")),
    "highlight_color": ("yellow", _one_of("yellow", "green", "blue", "pink")),
    "expanded_folders": ([], _id_list),
}


class PreferenceService:
    def __init__(self, repository: PreferenceRepository) -> None:
        self._repository = repository
        self._watchers: list[Callable[[dict], None]] = []

    def watch(self, watcher: Callable[[dict], None]) -> None:
        """Called with the saved values after every change (the native window follows the theme this way)."""
        self._watchers.append(watcher)

    def all(self) -> dict:
        stored = self._repository.all()
        return {key: stored.get(key, default) for key, (default, _check) in PREFERENCES.items()}

    def update(self, values: dict, *, only_missing: bool = False) -> dict:
        if not isinstance(values, dict):
            raise InvalidInput(_("요청 형식이 올바르지 않아요."))
        for key, value in values.items():
            spec = PREFERENCES.get(key)
            if spec is None or not spec[1](value):
                raise InvalidInput(_("화면 설정 값이 올바르지 않아요: {key}", key=str(key)[:40]))
        if values:
            self._repository.put_many(values, only_missing=only_missing)
            for watcher in self._watchers:
                watcher(values)
        return self.all()


class ConversationService:
    """AI chat history per paper. Deleted together with the paper (foreign key cascade)."""

    def __init__(self, repository: ConversationRepository, library: LibraryService, *,
                 clock: Callable[[], str] = utcnow) -> None:
        self._repository = repository
        self._library = library
        self._clock = clock

    def get(self, doc_id: str) -> list[dict]:
        self._library.get(doc_id)
        return self._repository.get(doc_id)

    def save(self, doc_id: str, turns: Any, *, only_missing: bool = False) -> list[dict]:
        self._library.get(doc_id)
        if not isinstance(turns, list) or not all(isinstance(turn, dict) for turn in turns):
            raise InvalidInput(_("대화 기록 형식이 올바르지 않아요."))
        turns = turns[-MAX_TURNS:]
        if len(json.dumps(turns, ensure_ascii=False).encode("utf-8")) > MAX_CONVERSATION_BYTES:
            raise InvalidInput(_("대화 기록이 너무 커요."))
        self._repository.put(doc_id, turns, self._clock(), only_missing=only_missing)
        return turns
