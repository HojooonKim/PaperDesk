"""Public metadata lookups for cited papers: arXiv API first (exact id or title), then OpenAlex (abstract by title/DOI)."""

from __future__ import annotations

import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher

from ..domain.errors import ReaderError
from ..domain.models import PaperMetadata
from ..ports.downloads import FileDownloader
from ..ports.scholarly import ScholarlyIndex

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"
MAX_BYTES = 2 * 1024 * 1024


def _norm(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", " ", text.casefold()).strip()


def title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


class ArxivIndex(ScholarlyIndex):
    endpoint = "https://export.arxiv.org/api/query"

    def __init__(self, downloader: FileDownloader) -> None:
        self._downloader = downloader

    def _query(self, params: dict) -> list[PaperMetadata]:
        raw = self._downloader.download(self.endpoint + "?" + urllib.parse.urlencode(params), max_bytes=MAX_BYTES, timeout=20)
        root = ET.fromstring(raw)
        found = []
        for entry in root.findall(f"{ATOM}entry"):
            ident = (entry.findtext(f"{ATOM}id") or "").rsplit("/", 1)[-1]
            arxiv_id = re.sub(r"v\d+$", "", ident)
            if not re.fullmatch(r"\d{4}\.\d{4,5}", arxiv_id):
                continue
            authors = ", ".join(a.findtext(f"{ATOM}name") or "" for a in entry.findall(f"{ATOM}author"))
            category = entry.find(f"{ARXIV}primary_category")
            found.append(PaperMetadata(
                title=" ".join((entry.findtext(f"{ATOM}title") or "").split()),
                abstract=" ".join((entry.findtext(f"{ATOM}summary") or "").split()),
                authors=authors, year=(entry.findtext(f"{ATOM}published") or "")[:4],
                url=f"https://arxiv.org/abs/{arxiv_id}", source="arxiv", arxiv_id=arxiv_id,
                doi=(entry.findtext(f"{ARXIV}doi") or "").strip(),
                field=category.get("term", "") if category is not None else ""))
        return found

    def lookup(self, *, title: str, arxiv_id: str = "", doi: str = "", year: str = "") -> PaperMetadata | None:
        if arxiv_id:
            items = self._query({"id_list": arxiv_id})
            return items[0] if items else None
        words = [w for w in _norm(title).split() if len(w) > 2][:12]
        if len(words) < 2:
            return None
        phrase = re.sub(r'["\\]', " ", title).strip()
        items = self._query({"search_query": f'ti:"{phrase}"', "max_results": "5"})
        if not any(title_similarity(m.title, title) >= 0.9 for m in items):
            items += self._query({"search_query": " AND ".join(f"ti:{w}" for w in words), "max_results": "5"})
        best = max(items, key=lambda m: title_similarity(m.title, title), default=None)
        return best if best and title_similarity(best.title, title) >= 0.9 else None


class OpenAlexIndex(ScholarlyIndex):
    endpoint = "https://api.openalex.org/works"

    def __init__(self, downloader: FileDownloader, mailto: str = "") -> None:
        self._downloader = downloader
        self._mailto = mailto

    @staticmethod
    def _abstract(inverted: dict | None) -> str:
        if not inverted:
            return ""
        slots: dict[int, str] = {}
        for word, places in inverted.items():
            for place in places:
                slots[place] = word
        return " ".join(slots[i] for i in sorted(slots))

    def _work(self, work: dict) -> PaperMetadata:
        authors = ", ".join(((a.get("author") or {}).get("display_name") or "") for a in work.get("authorships", [])[:12])
        venue = (((work.get("primary_location") or {}).get("source") or {}).get("display_name")) or ""
        arxiv_id = ""
        for location in work.get("locations") or []:
            found = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", str(location.get("landing_page_url") or location.get("pdf_url") or ""))
            if found:
                arxiv_id = found.group(1)
                break
        topic = work.get("primary_topic") or {}
        field = " / ".join(name for name in ((topic.get("field") or {}).get("display_name"), (topic.get("subfield") or {}).get("display_name")) if name)
        return PaperMetadata(title=work.get("display_name") or work.get("title") or "", abstract=self._abstract(work.get("abstract_inverted_index")),
                             authors=authors, year=str(work.get("publication_year") or ""), venue=venue,
                             url=work.get("doi") or work.get("id") or "", source="openalex", arxiv_id=arxiv_id,
                             doi=re.sub(r"^https?://(dx\.)?doi\.org/", "", work.get("doi") or ""), field=field)

    def _get(self, url: str):
        if self._mailto:
            url += ("&" if "?" in url else "?") + "mailto=" + urllib.parse.quote(self._mailto)
        return json.loads(self._downloader.download(url, max_bytes=MAX_BYTES, timeout=20))

    def lookup(self, *, title: str, arxiv_id: str = "", doi: str = "", year: str = "") -> PaperMetadata | None:
        if doi:
            try:
                return self._work(self._get(f"{self.endpoint}/doi:{urllib.parse.quote(doi)}"))
            except ReaderError:
                pass
        if len(_norm(title).split()) < 2:
            return None
        data = self._get(f"{self.endpoint}?search={urllib.parse.quote(title)}&per-page=5")
        # Popular titles have look-alikes (re-uploads, talks with the same name): of the close matches, the most cited.
        works = [(self._work(w), w.get("cited_by_count") or 0) for w in data.get("results", [])]
        close = [(work, cited) for work, cited in works if title_similarity(work.title, title) >= 0.9]
        return max(close, key=lambda pair: (pair[1], title_similarity(pair[0].title, title)))[0] if close else None


class CompositeIndex(ScholarlyIndex):
    """Tries each index in order; prefers a result that has an abstract. Network failures fall through to the next."""

    def __init__(self, indexes: list[ScholarlyIndex]) -> None:
        self._indexes = indexes

    def lookup(self, *, title: str, arxiv_id: str = "", doi: str = "", year: str = "") -> PaperMetadata | None:
        fallback = None
        for index in self._indexes:
            try:
                found = index.lookup(title=title, arxiv_id=arxiv_id, doi=doi, year=year)
            except (ReaderError, ET.ParseError, ValueError):
                continue
            if found and found.abstract:
                if fallback and fallback.arxiv_id and not found.arxiv_id:
                    return PaperMetadata(**{**found.to_dict(), "arxiv_id": fallback.arxiv_id})
                return found
            fallback = fallback or found
        return fallback

