"""Paper details (authors, year, venue, DOI, arXiv number, research field) for library papers, from arXiv and OpenAlex."""
from __future__ import annotations

import re
import unicodedata
import xml.etree.ElementTree as ET

from ..domain.errors import ReaderError
from ..domain.models import Document, PaperMetadata
from ..ports.scholarly import ScholarlyIndex
from .library import LibraryService

ARXIV_ID = re.compile(r"arXiv:\s*(\d{4}\.\d{4,5})(?:v\d+)?", re.I)
DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)")


def _words(text: str) -> set[str]:
    plain = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", text)).encode("ascii", "ignore").decode()
    return {w for w in re.findall(r"[a-z0-9]+", plain.casefold()) if len(w) > 2}


class PaperInfoService:
    """Looks a paper up by the arXiv number or DOI printed on its first page, else by its title. Each index is asked in
    order; for every detail the first index that has it wins. An arXiv listing is not a venue, and OpenAlex's DOI for a
    record without a venue is skipped: for a preprint it often belongs to a re-upload elsewhere."""

    def __init__(self, library: LibraryService, indexes: list[ScholarlyIndex]) -> None:
        self._library = library
        self._indexes = indexes

    def refresh(self, doc_id: str, *, force: bool = False) -> Document:
        document = self._library.get(doc_id)
        if document.info_checked_at and not force:
            return document
        pages = self._library.read_text(doc_id, 1, 1)
        text = pages[0][1] if pages else ""
        arxiv, doi = ARXIV_ID.search(text), DOI.search(text)
        arxiv_id, doi = (arxiv.group(1) if arxiv else ""), (doi.group(1).rstrip(".,;)]") if doi else "")
        title, found, failed = document.title, [], False
        for index in self._indexes:
            try:
                item = index.lookup(title=title, arxiv_id=arxiv_id, doi=doi)
            except (ReaderError, ET.ParseError, ValueError):
                failed = True
                continue
            if item and self._on_page(item, text):
                found.append(item)
                title, doi = item.title, doi or item.doi
        if not found and failed:
            return document  # offline or rate limited: not marked as checked, so the next import or launch tries again
        return self._library.set_info(doc_id, self._merge(found) if found else None)

    @staticmethod
    def _on_page(item: PaperMetadata, text: str) -> bool:
        """An identifier on the first page can belong to a cited paper, and a title can belong to another work: keep a
        match only if most of its title and its first author's surname are there."""
        words = _words(item.title)
        if not text.strip() or not words:
            return True  # nothing to compare: a title lookup has already matched the title closely
        page = _words(text)
        first = item.authors.split(",")[0].split()
        surname = _words(first[-1]) if first else set()
        return sum(word in page for word in words) >= 0.8 * len(words) and surname <= page

    @staticmethod
    def _merge(found: list[PaperMetadata]) -> PaperMetadata:
        merged: dict[str, str] = {}
        for item in found:
            published = bool(item.venue) and "arxiv" not in item.venue.casefold()
            for key, value in item.to_dict().items():
                if (key == "venue" or key == "doi" and item.source == "openalex") and not published:
                    continue
                if value and not merged.get(key):
                    merged[key] = value
        return PaperMetadata(**{"title": "", "abstract": "", **merged})
