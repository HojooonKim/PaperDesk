from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Callable

from ..domain.errors import InvalidInput, NotFound
from ..domain.models import Document, Folder, PaperMetadata, utcnow
from ..ports.repositories import DocumentRepository, FolderRepository, PageTextRepository
from ..ports.storage import BlobStore
from ..i18n import _

MAX_PDF_BYTES = 200 * 1024 * 1024
MAX_NAME = 120
MAX_PAPER_TITLE = 300


def _new_id() -> str:
    return uuid.uuid4().hex


def _clean_name(value: str, empty: str, too_long: str, *, limit: int = MAX_NAME) -> str:
    name = " ".join(str(value or "").split())
    if not name:
        raise InvalidInput(empty)
    if len(name) > limit:
        raise InvalidInput(too_long)
    return name


def _folder_name(value: str) -> str:
    return _clean_name(value, _("폴더 이름을 입력하세요."), _("폴더 이름은 {n}자 이하로 해 주세요.", n=MAX_NAME))


def _file_title(filename: str) -> str:
    """A new paper's title until a better one is found: the file name without extension."""
    return (Path(filename).stem.replace("_", " ").strip() or "Untitled")[:MAX_NAME]


def _paper_title(value: str) -> str:
    return _clean_name(value, _("논문 제목을 입력하세요."), _("논문 제목은 {n}자 이하로 해 주세요.", n=MAX_PAPER_TITLE), limit=MAX_PAPER_TITLE)


class FolderService:
    """Topic folders with unlimited nesting. Deleting a folder never deletes papers."""

    def __init__(self, folders: FolderRepository, documents: DocumentRepository, *,
                 new_id: Callable[[], str] = _new_id, clock: Callable[[], str] = utcnow) -> None:
        self._folders = folders
        self._documents = documents
        self._new_id = new_id
        self._clock = clock

    def list(self) -> list[Folder]:
        return self._folders.list()

    def get(self, folder_id: str) -> Folder:
        folder = self._folders.get(folder_id)
        if folder is None:
            raise NotFound(_("폴더를 찾지 못했어요."))
        return folder

    def require_optional(self, folder_id: str | None) -> str | None:
        if folder_id in (None, ""):
            return None
        return self.get(folder_id).id

    def create(self, name: str, parent_id: str | None = None) -> Folder:
        parent = self.require_optional(parent_id)
        clean = _folder_name(name)
        self._ensure_unique(clean, parent, ignore=None)
        folder = Folder(self._new_id(), clean, parent, self._clock())
        self._folders.add(folder)
        return folder

    def rename(self, folder_id: str, name: str) -> Folder:
        folder = self.get(folder_id)
        clean = _folder_name(name)
        self._ensure_unique(clean, folder.parent_id, ignore=folder.id)
        updated = Folder(folder.id, clean, folder.parent_id, folder.created_at)
        self._folders.update(updated)
        return updated

    def move(self, folder_id: str, parent_id: str | None) -> Folder:
        folder = self.get(folder_id)
        parent = self.require_optional(parent_id)
        if parent is not None and (parent == folder.id or parent in self.descendants(folder.id)):
            raise InvalidInput(_("폴더를 자기 자신이나 하위 폴더 안으로 옮길 수 없어요."))
        self._ensure_unique(folder.name, parent, ignore=folder.id)
        updated = Folder(folder.id, folder.name, parent, folder.created_at)
        self._folders.update(updated)
        return updated

    def delete(self, folder_id: str) -> None:
        """Move the folder's papers and subfolders up one level, then remove the folder."""
        folder = self.get(folder_id)
        for child in self._children(folder.id):
            unique = self._unique_name(child.name, folder.parent_id, ignore=child.id)
            self._folders.update(Folder(child.id, unique, folder.parent_id, child.created_at))
        self._documents.move_all(folder.id, folder.parent_id)
        self._folders.delete(folder.id)

    def descendants(self, folder_id: str) -> set[str]:
        by_parent: dict[str | None, list[str]] = {}
        for item in self._folders.list():
            by_parent.setdefault(item.parent_id, []).append(item.id)
        found: set[str] = set()
        stack = [folder_id]
        while stack:
            for child in by_parent.get(stack.pop(), []):
                if child not in found:
                    found.add(child)
                    stack.append(child)
        return found

    def _children(self, folder_id: str) -> list[Folder]:
        return [item for item in self._folders.list() if item.parent_id == folder_id]

    def _ensure_unique(self, name: str, parent_id: str | None, *, ignore: str | None) -> None:
        if self._taken(name, parent_id, ignore):
            raise InvalidInput(_("같은 위치에 '{name}' 폴더가 이미 있어요.", name=name))

    def _taken(self, name: str, parent_id: str | None, ignore: str | None) -> bool:
        return any(item.parent_id == parent_id and item.id != ignore and item.name.casefold() == name.casefold()
                   for item in self._folders.list())

    def _unique_name(self, name: str, parent_id: str | None, *, ignore: str) -> str:
        candidate, number = name, 2
        while self._taken(candidate, parent_id, ignore):
            candidate, number = f"{name} ({number})", number + 1
        return candidate


class LibraryService:
    def __init__(self, documents: DocumentRepository, blobs: BlobStore, texts: PageTextRepository, folders: FolderService, *,
                 new_id: Callable[[], str] = _new_id, clock: Callable[[], str] = utcnow) -> None:
        self._documents = documents
        self._blobs = blobs
        self._texts = texts
        self._folders = folders
        self._new_id = new_id
        self._clock = clock

    @staticmethod
    def blob_key(doc_id: str) -> str:
        return f"documents/{doc_id}.pdf"

    def list(self, folder_id: str | None = None, *, scope: str = "all") -> list[Document]:
        """scope: 'all' | 'unfiled' | 'folder' (folder_id plus its subfolders)."""
        documents = self._documents.list()
        if scope == "unfiled":
            return [doc for doc in documents if doc.folder_id is None]
        if scope == "folder":
            folder = self._folders.get(folder_id or "")
            wanted = {folder.id, *self._folders.descendants(folder.id)}
            return [doc for doc in documents if doc.folder_id in wanted]
        return documents

    def get(self, doc_id: str) -> Document:
        document = self._documents.get(doc_id)
        if document is None:
            raise NotFound(_("논문을 찾지 못했어요."))
        return document

    def import_pdf(self, filename: str, data: bytes, folder_id: str | None = None) -> tuple[Document, bool]:
        """Return (document, created). Re-importing the same file returns the existing entry."""
        if not data.startswith(b"%PDF-"):
            raise InvalidInput(_("PDF 파일만 올릴 수 있어요."))
        if len(data) > MAX_PDF_BYTES:
            raise InvalidInput(_("PDF가 너무 커요 (최대 200MB)."))
        folder = self._folders.require_optional(folder_id)
        digest = hashlib.sha256(data).hexdigest()
        existing = self._documents.find_by_sha256(digest)
        if existing is not None:
            return existing, False
        name = Path(filename or "paper.pdf").name[:200] or "paper.pdf"
        document = Document(self._new_id(), _file_title(name), name, digest, len(data), self._clock(), folder_id=folder)
        self._blobs.put(self.blob_key(document.id), data)
        stored = self._documents.add(document)
        if stored.id != document.id:
            self._blobs.delete(self.blob_key(document.id))
        return stored, stored.id == document.id

    def pdf_path(self, doc_id: str) -> Path:
        self.get(doc_id)
        return self._blobs.path(self.blob_key(doc_id))

    def mark_opened(self, doc_id: str) -> Document:
        document = self.get(doc_id).opened(self._clock())
        self._documents.update(document)
        return document

    def rename(self, doc_id: str, title: str) -> Document:
        document = self.get(doc_id).renamed(_paper_title(title))
        self._documents.update(document)
        return document

    def move(self, doc_id: str, folder_id: str | None) -> Document:
        document = self.get(doc_id).moved(self._folders.require_optional(folder_id))
        self._documents.update(document)
        return document

    def delete(self, doc_id: str) -> None:
        self.get(doc_id)
        self._documents.delete(doc_id)
        self._blobs.delete(self.blob_key(doc_id))

    def save_text(self, doc_id: str, pages: list[str]) -> Document:
        if len(pages) > 5000 or any(not isinstance(page, str) for page in pages):
            raise InvalidInput(_("쪽 텍스트 형식이 올바르지 않아요."))
        document = self.get(doc_id)
        self._texts.replace(doc_id, [page[:200_000] for page in pages])
        updated = document.with_text(len(pages))
        self._documents.update(updated)
        return updated

    def set_info(self, doc_id: str, info: PaperMetadata | None) -> Document:
        """Store looked-up details (None: the lookup found nothing). Re-reads the paper, which may have moved meanwhile.
        A paper still named after its file (no title found in the PDF, never renamed) takes the found title."""
        document = self.get(doc_id).with_info(info, self._clock())
        if info is not None and info.title.strip() and document.title == _file_title(document.filename):
            document = document.renamed(" ".join(info.title.split())[:MAX_PAPER_TITLE])
        self._documents.update(document)
        return document

    def read_text(self, doc_id: str, first: int = 1, last: int | None = None) -> list[tuple[int, str]]:
        document = self.get(doc_id)
        end = document.text_pages if last is None else min(last, document.text_pages)
        return self._texts.read(doc_id, max(1, first), end)

    def search(self, query: str, limit: int = 20) -> list[dict]:
        titles = {doc.id: doc.title for doc in self._documents.list()}
        return [{"doc_id": doc_id, "title": titles.get(doc_id, ""), "page": page, "snippet": snippet}
                for doc_id, page, snippet in self._texts.search(query, limit)]
