from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from enum import Enum


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Folder:
    """A topic folder. parent_id=None means top level; folders nest to any depth."""

    id: str
    name: str
    parent_id: str | None
    created_at: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    filename: str
    sha256: str
    size_bytes: int
    created_at: str
    folder_id: str | None = None  # None = unfiled
    last_opened_at: str | None = None
    page_count: int = 0
    text_pages: int = 0
    # Paper details from arXiv or OpenAlex (empty until looked up; info_checked_at marks a finished lookup).
    authors: str = ""
    year: str = ""
    venue: str = ""
    doi: str = ""
    arxiv_id: str = ""
    field: str = ""  # the index's research area, e.g. "cs.CL" or "Computer Science / Artificial Intelligence"
    info_checked_at: str | None = None

    def renamed(self, title: str) -> "Document":
        return replace(self, title=title)

    def moved(self, folder_id: str | None) -> "Document":
        return replace(self, folder_id=folder_id)

    def opened(self, at: str) -> "Document":
        return replace(self, last_opened_at=at)

    def with_text(self, page_count: int) -> "Document":
        return replace(self, page_count=page_count, text_pages=page_count)

    def with_info(self, info: "PaperMetadata | None", at: str) -> "Document":
        if info is None:
            return replace(self, info_checked_at=at)
        return replace(self, authors=info.authors, year=info.year, venue=info.venue, doi=info.doi, arxiv_id=info.arxiv_id,
                       field=info.field, info_checked_at=at)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ReadingItem:
    """A paper the user wants to read later, usually saved from a citation. document_id is set once its PDF is in the library."""

    id: str
    title: str
    citation: str
    created_at: str
    authors: str = ""
    year: str = ""
    arxiv_id: str = ""
    doi: str = ""
    url: str = ""
    source_doc_id: str | None = None
    document_id: str | None = None
    note: str = ""

    @property
    def in_library(self) -> bool:
        return self.document_id is not None

    def to_dict(self) -> dict:
        return {**asdict(self), "in_library": self.in_library}


class AssistTask(str, Enum):
    TRANSLATE = "translate"
    EXPLAIN = "explain"
    ASK = "ask"
    SUMMARIZE = "summarize"
    DEFINE = "define"            # word / phrase meaning in context
    TLDR = "tldr"                # three-line summary
    KEYWORDS = "keywords"        # key-term glossary (JSON)
    FIGURE = "figure"            # figure / table / algorithm explanation (image + caption + mentions)
    EQUATION = "equation"        # equation explanation (image + extracted text + surrounding text)
    REGION = "region"            # free rectangle the user drew
    REFERENCE = "reference"      # cited paper summary grounded on fetched metadata
    TRANSLATE_BLOCKS = "translate_blocks"  # body translation, sentence aligned (JSON)
    CLASSIFY = "classify"        # library folder for a new paper (JSON)


@dataclass(frozen=True)
class ImageInput:
    media_type: str  # image/png | image/jpeg
    data: bytes

    @property
    def data_url(self) -> str:
        import base64

        return f"data:{self.media_type};base64,{base64.b64encode(self.data).decode()}"


@dataclass(frozen=True)
class AssistRequest:
    task: AssistTask
    text: str
    question: str = ""
    context: str = ""
    target_language: str = "English"
    title: str = ""
    images: tuple[ImageInput, ...] = ()


@dataclass(frozen=True)
class Prompt:
    system: str
    user: str
    images: tuple[ImageInput, ...] = ()
    response_schema: dict | None = None

    def as_single_text(self) -> str:
        """For backends that accept only one message, such as codex exec."""
        return f"{self.system}\n\n---\n\n{self.user}"


@dataclass(frozen=True)
class Annotation:
    """Highlight or note on a page. rects are page-relative fractions [left, top, right, bottom]."""

    id: str
    doc_id: str
    page: int
    kind: str  # highlight | note
    color: str
    text: str
    rects: tuple[tuple[float, float, float, float], ...]
    created_at: str
    note: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["rects"] = [list(r) for r in self.rects]
        return data


@dataclass(frozen=True)
class BlockTranslation:
    doc_id: str
    block_key: str
    language: str
    source_hash: str
    text: str
    sentences: tuple[str, ...] | None
    provider_id: str
    model: str
    created_at: str

    def to_dict(self) -> dict:
        return {"key": self.block_key, "text": self.text, "sentences": list(self.sentences) if self.sentences is not None else None,
                "provider_id": self.provider_id, "model": self.model}


@dataclass(frozen=True)
class PaperMetadata:
    title: str
    abstract: str
    authors: str = ""
    year: str = ""
    venue: str = ""
    url: str = ""
    source: str = ""  # arxiv | openalex
    arxiv_id: str = ""
    doi: str = ""
    field: str = ""  # research area: arXiv primary category, or OpenAlex "field / subfield"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Completion:
    text: str
    provider_id: str
    model: str = ""
    cached: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ProviderStatus:
    available: bool
    detail: str = ""
    models: tuple[str, ...] = ()

