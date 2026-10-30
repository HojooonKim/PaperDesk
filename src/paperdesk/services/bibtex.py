"""BibTeX entries for library papers, built from their stored details."""
from __future__ import annotations

import re
import unicodedata

from ..domain.models import Document

CONFERENCE = re.compile(r"conference|proceedings|symposium|workshop|meeting|neural information processing systems", re.I)
ARXIV_CATEGORY = re.compile(r"[a-z-]+(\.[A-Za-z-]+)?")  # cs.CL, stat.ML, hep-th; OpenAlex fields have spaces
SKIP_WORDS = {"a", "an", "the", "on", "of", "for", "to", "in", "and", "with", "towards", "toward"}


def _escape(value: str) -> str:
    return re.sub(r"([&%$#_])", r"\\\1", value.replace("{", "").replace("}", ""))


def _key(document: Document) -> str:
    """Google Scholar style: first author's last name, year, first title word (vaswani2017attention)."""
    names = document.authors.split(",")[0].split()
    word = next((w for w in re.findall(r"[^\W\d_]+", document.title) if w.casefold() not in SKIP_WORDS), "")
    key = unicodedata.normalize("NFKD", (names[-1] if names else "") + document.year + word).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", key.lower()) or "paper"


def bibtex(documents: list[Document]) -> str:
    entries, used = [], {}
    for document in documents:
        key = _key(document)
        used[key] = used.get(key, 0) + 1
        if used[key] > 1:
            key += chr(ord("a") + used[key] - 1)  # vaswani2017attention, vaswani2017attentionb, …
        fields = [("title", document.title),
                  ("author", " and ".join(name.strip() for name in document.authors.split(",") if name.strip())),
                  ("year", document.year)]
        kind = "misc"
        if document.venue:
            kind = "inproceedings" if CONFERENCE.search(document.venue) else "article"
            fields.append(("booktitle" if kind == "inproceedings" else "journal", document.venue))
        fields.append(("doi", document.doi))
        if document.arxiv_id:
            fields += [("eprint", document.arxiv_id), ("archivePrefix", "arXiv")]
            if ARXIV_CATEGORY.fullmatch(document.field):
                fields.append(("primaryClass", document.field))
        body = ",\n".join(f"  {name} = {{{_escape(value)}}}" for name, value in fields if value)
        entries.append(f"@{kind}{{{key},\n{body}\n}}")
    return "\n\n".join(entries) + ("\n" if entries else "")
