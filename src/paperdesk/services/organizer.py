"""Sorts a paper that was added without a folder into a topic folder the connected AI picks or names."""
from __future__ import annotations

import threading

from ..domain.errors import ProviderFailed
from ..domain.models import AssistRequest, AssistTask, Folder
from ..i18n import _
from .assistant import AssistantService
from .library import FolderService, LibraryService
from .translation import _extract_json

MAX_PAGE_TEXT = 3000  # the first page (title, abstract, introduction) is enough to tell the topic
MAX_NEW_NAME = 60


class OrganizerService:
    def __init__(self, library: LibraryService, folders: FolderService, assistant: AssistantService) -> None:
        self._library = library
        self._folders = folders
        self._assistant = assistant
        self._lock = threading.Lock()  # two papers of a new topic must not create the same folder twice

    def organize(self, doc_id: str, language: str) -> dict:
        """language: for a new folder's name (the app's display language). A paper already in a folder stays there."""
        document = self._library.get(doc_id)
        if document.folder_id is not None:
            return {"document": document.to_dict(), "folder": None, "created": False}
        paths = self._paths(self._folders.list())
        pages = self._library.read_text(doc_id, 1, 1)
        details = [("Title", document.title), ("Authors", document.authors), ("Year", document.year),
                   ("Venue", document.venue), ("Research area (from arXiv or OpenAlex)", document.field)]
        paper = "\n".join(f"{name}: {value}" for name, value in details if value)
        if pages and pages[0][1].strip():
            paper += "\n\nFirst page:\n" + pages[0][1][:MAX_PAGE_TEXT]
        listing = "\n".join(f"{folder_id}: {path}" for folder_id, path in paths.items()) or "(no folders yet)"
        reply = self._assistant.run(AssistRequest(AssistTask.CLASSIFY, text=paper, context=listing, target_language=language))
        choice = _extract_json(reply.text) or {}
        folder_id = str(choice.get("folder_id") or "").strip()
        name = " ".join(str(choice.get("new_folder") or "").split())[:MAX_NEW_NAME]
        with self._lock:
            folders = self._folders.list()
            folder = next((f for f in folders if f.id == folder_id), None)
            if folder is None and name:
                folder = next((f for f in folders if f.name.casefold() == name.casefold()), None)
            created = folder is None and bool(name)
            if created:
                folder = self._folders.create(name)
            if folder is None:
                raise ProviderFailed(_("AI가 알맞은 폴더를 고르지 못했어요. 다시 시도해 주세요."))
            moved = self._library.move(doc_id, folder.id)
        return {"document": moved.to_dict(), "folder": folder.to_dict(), "created": created}

    @staticmethod
    def _paths(folders: list[Folder]) -> dict[str, str]:
        """id → "Parent / Child", so the AI sees where each folder sits."""
        by_id = {folder.id: folder for folder in folders}
        def path(folder: Folder) -> str:
            parent = by_id.get(folder.parent_id or "")
            return f"{path(parent)} / {folder.name}" if parent else folder.name
        return {folder.id: path(folder) for folder in folders}
