from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from dataclasses import fields

import json

from ..domain.models import Annotation, BlockTranslation, Document, Folder, ReadingItem
from ..domain.errors import InvalidInput
from ..i18n import _
from ..ports.repositories import (AnnotationRepository, CompletionCache, ConversationRepository, DocumentRepository,
                                  FolderRepository, PageTextRepository, PreferenceRepository, ReadingListRepository,
                                  TranslationRepository)

# Append-only. Each entry upgrades the schema by one version (tracked in PRAGMA user_version).
MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE folders (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        parent_id TEXT REFERENCES folders(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL
    );
    CREATE TABLE documents (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        filename TEXT NOT NULL,
        sha256 TEXT NOT NULL UNIQUE,
        size_bytes INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        folder_id TEXT REFERENCES folders(id) ON DELETE SET NULL,
        last_opened_at TEXT,
        page_count INTEGER NOT NULL DEFAULT 0,
        text_pages INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX documents_folder ON documents(folder_id);
    CREATE TABLE page_texts (
        doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        page INTEGER NOT NULL,
        text TEXT NOT NULL,
        PRIMARY KEY (doc_id, page)
    );
    CREATE TABLE completions (
        key TEXT PRIMARY KEY,
        text TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE reading_items (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        citation TEXT NOT NULL,
        created_at TEXT NOT NULL,
        authors TEXT NOT NULL DEFAULT '',
        year TEXT NOT NULL DEFAULT '',
        arxiv_id TEXT NOT NULL DEFAULT '',
        doi TEXT NOT NULL DEFAULT '',
        url TEXT NOT NULL DEFAULT '',
        source_doc_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
        document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
        note TEXT NOT NULL DEFAULT ''
    );
    """,
    """
    CREATE TABLE annotations (
        id TEXT PRIMARY KEY,
        doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        page INTEGER NOT NULL,
        kind TEXT NOT NULL,
        color TEXT NOT NULL,
        text TEXT NOT NULL,
        rects TEXT NOT NULL,
        created_at TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX annotations_doc ON annotations(doc_id, page);
    CREATE TABLE block_translations (
        doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        block_key TEXT NOT NULL,
        language TEXT NOT NULL,
        source_hash TEXT NOT NULL,
        text TEXT NOT NULL,
        sentences TEXT,
        provider_id TEXT NOT NULL,
        model TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (doc_id, block_key, language)
    );
    """,
    """
    CREATE TABLE conversations (
        doc_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
        turns TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE preferences (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE translation_jobs (
        id TEXT PRIMARY KEY,
        doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        fingerprint TEXT NOT NULL,
        payload TEXT NOT NULL,
        state TEXT NOT NULL,
        completed INTEGER NOT NULL DEFAULT 0,
        total INTEGER NOT NULL,
        error TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE UNIQUE INDEX translation_jobs_active ON translation_jobs(doc_id, fingerprint)
        WHERE state IN ('queued', 'running', 'paused');
    """,
    """
    ALTER TABLE documents ADD COLUMN authors TEXT NOT NULL DEFAULT '';
    ALTER TABLE documents ADD COLUMN year TEXT NOT NULL DEFAULT '';
    ALTER TABLE documents ADD COLUMN venue TEXT NOT NULL DEFAULT '';
    ALTER TABLE documents ADD COLUMN doi TEXT NOT NULL DEFAULT '';
    ALTER TABLE documents ADD COLUMN arxiv_id TEXT NOT NULL DEFAULT '';
    ALTER TABLE documents ADD COLUMN field TEXT NOT NULL DEFAULT '';
    ALTER TABLE documents ADD COLUMN info_checked_at TEXT;
    """,
)


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._migrate()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _migrate(self) -> None:
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > len(MIGRATIONS):
                raise InvalidInput(_("이 서재는 더 최신 앱에서 저장되었어요. PaperDesk를 업데이트한 뒤 다시 열어 주세요."))
            db.execute("PRAGMA journal_mode = WAL")
            if 0 < version < len(MIGRATIONS):
                folder = self.path.parent / "backups" / "migrations"
                folder.mkdir(parents=True, exist_ok=True, mode=0o700)
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                backup = sqlite3.connect(folder / f"library-v{version}-{stamp}.sqlite3")
                try:
                    db.backup(backup)  # includes committed WAL data; a raw file copy would not
                finally:
                    backup.close()
            for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
                db.executescript(f"BEGIN IMMEDIATE;\n{script}\nPRAGMA user_version = {number};\nCOMMIT;")


_DOC_COLUMNS = ("id, title, filename, sha256, size_bytes, created_at, folder_id, last_opened_at, page_count, text_pages, "
                "authors, year, venue, doi, arxiv_id, field, info_checked_at")


def _document(row: sqlite3.Row) -> Document:
    return Document(**{key: row[key] for key in row.keys()})


class SqliteDocumentRepository(DocumentRepository):
    def __init__(self, database: Database) -> None:
        self._db = database

    def add(self, document: Document) -> Document:
        values = document.to_dict()
        with self._db.connect() as db:
            db.execute(f"INSERT INTO documents ({_DOC_COLUMNS}) VALUES ({', '.join(':' + c.strip() for c in _DOC_COLUMNS.split(','))}) ON CONFLICT(sha256) DO NOTHING", values)
            return _document(db.execute(f"SELECT {_DOC_COLUMNS} FROM documents WHERE sha256=?", (document.sha256,)).fetchone())

    def get(self, doc_id: str) -> Document | None:
        with self._db.connect() as db:
            row = db.execute(f"SELECT {_DOC_COLUMNS} FROM documents WHERE id = ?", (doc_id,)).fetchone()
        return _document(row) if row else None

    def find_by_sha256(self, digest: str) -> Document | None:
        with self._db.connect() as db:
            row = db.execute(f"SELECT {_DOC_COLUMNS} FROM documents WHERE sha256 = ?", (digest,)).fetchone()
        return _document(row) if row else None

    def list(self) -> list[Document]:
        with self._db.connect() as db:
            rows = db.execute(f"SELECT {_DOC_COLUMNS} FROM documents ORDER BY COALESCE(last_opened_at, created_at) DESC").fetchall()
        return [_document(row) for row in rows]

    def update(self, document: Document) -> None:
        values = document.to_dict()
        assignments = ", ".join(f"{c.strip()} = :{c.strip()}" for c in _DOC_COLUMNS.split(",")[1:])
        with self._db.connect() as db:
            db.execute(f"UPDATE documents SET {assignments} WHERE id = :id", values)

    def delete(self, doc_id: str) -> None:
        with self._db.connect() as db:
            db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))

    def move_all(self, from_folder: str, to_folder: str | None) -> None:
        with self._db.connect() as db:
            db.execute("UPDATE documents SET folder_id = ? WHERE folder_id = ?", (to_folder, from_folder))


class SqliteFolderRepository(FolderRepository):
    def __init__(self, database: Database) -> None:
        self._db = database

    def add(self, folder: Folder) -> None:
        with self._db.connect() as db:
            db.execute("INSERT INTO folders (id, name, parent_id, created_at) VALUES (:id, :name, :parent_id, :created_at)", folder.to_dict())

    def get(self, folder_id: str) -> Folder | None:
        with self._db.connect() as db:
            row = db.execute("SELECT id, name, parent_id, created_at FROM folders WHERE id = ?", (folder_id,)).fetchone()
        return Folder(**dict(row)) if row else None

    def list(self) -> list[Folder]:
        with self._db.connect() as db:
            rows = db.execute("SELECT id, name, parent_id, created_at FROM folders ORDER BY name COLLATE NOCASE").fetchall()
        return [Folder(**dict(row)) for row in rows]

    def update(self, folder: Folder) -> None:
        with self._db.connect() as db:
            db.execute("UPDATE folders SET name = :name, parent_id = :parent_id WHERE id = :id", folder.to_dict())

    def delete(self, folder_id: str) -> None:
        with self._db.connect() as db:
            db.execute("DELETE FROM folders WHERE id = ?", (folder_id,))


_READING_COLUMNS = [f.name for f in fields(ReadingItem)]


class SqliteReadingListRepository(ReadingListRepository):
    def __init__(self, database: Database) -> None:
        self._db = database

    @staticmethod
    def _item(row: sqlite3.Row) -> ReadingItem:
        return ReadingItem(**{key: row[key] for key in _READING_COLUMNS})

    def add(self, item: ReadingItem) -> None:
        values = {key: getattr(item, key) for key in _READING_COLUMNS}
        with self._db.connect() as db:
            db.execute(f"INSERT INTO reading_items ({', '.join(_READING_COLUMNS)}) VALUES ({', '.join(':' + c for c in _READING_COLUMNS)})", values)

    def get(self, item_id: str) -> ReadingItem | None:
        with self._db.connect() as db:
            row = db.execute(f"SELECT {', '.join(_READING_COLUMNS)} FROM reading_items WHERE id = ?", (item_id,)).fetchone()
        return self._item(row) if row else None

    def list(self) -> list[ReadingItem]:
        with self._db.connect() as db:
            rows = db.execute(f"SELECT {', '.join(_READING_COLUMNS)} FROM reading_items ORDER BY created_at DESC").fetchall()
        return [self._item(row) for row in rows]

    def update(self, item: ReadingItem) -> None:
        values = {key: getattr(item, key) for key in _READING_COLUMNS}
        assignments = ", ".join(f"{c} = :{c}" for c in _READING_COLUMNS if c != "id")
        with self._db.connect() as db:
            db.execute(f"UPDATE reading_items SET {assignments} WHERE id = :id", values)

    def delete(self, item_id: str) -> None:
        with self._db.connect() as db:
            db.execute("DELETE FROM reading_items WHERE id = ?", (item_id,))


class SqliteAnnotationRepository(AnnotationRepository):
    COLUMNS = ("id", "doc_id", "page", "kind", "color", "text", "rects", "created_at", "note")

    def __init__(self, database: Database) -> None:
        self._db = database

    def _row(self, row: sqlite3.Row) -> Annotation:
        data = {k: row[k] for k in self.COLUMNS}
        data["rects"] = tuple(tuple(r) for r in json.loads(data["rects"]))
        return Annotation(**data)

    def _values(self, a: Annotation) -> dict:
        return {**{k: getattr(a, k) for k in self.COLUMNS}, "rects": json.dumps([list(r) for r in a.rects])}

    def add(self, annotation: Annotation) -> None:
        with self._db.connect() as db:
            db.execute(f"INSERT INTO annotations ({', '.join(self.COLUMNS)}) VALUES ({', '.join(':' + c for c in self.COLUMNS)})", self._values(annotation))

    def get(self, annotation_id: str) -> Annotation | None:
        with self._db.connect() as db:
            row = db.execute(f"SELECT {', '.join(self.COLUMNS)} FROM annotations WHERE id = ?", (annotation_id,)).fetchone()
        return self._row(row) if row else None

    def list(self, doc_id: str) -> list[Annotation]:
        with self._db.connect() as db:
            rows = db.execute(f"SELECT {', '.join(self.COLUMNS)} FROM annotations WHERE doc_id = ? ORDER BY page, created_at", (doc_id,)).fetchall()
        return [self._row(r) for r in rows]

    def update(self, annotation: Annotation) -> None:
        with self._db.connect() as db:
            db.execute("UPDATE annotations SET kind = :kind, color = :color, note = :note WHERE id = :id", self._values(annotation))

    def delete(self, annotation_id: str) -> None:
        with self._db.connect() as db:
            db.execute("DELETE FROM annotations WHERE id = ?", (annotation_id,))


class SqliteTranslationRepository(TranslationRepository):
    def __init__(self, database: Database) -> None:
        self._db = database

    def list(self, doc_id: str, language: str) -> list[BlockTranslation]:
        with self._db.connect() as db:
            rows = db.execute("SELECT * FROM block_translations WHERE doc_id = ? AND language = ?", (doc_id, language)).fetchall()
        return [BlockTranslation(r["doc_id"], r["block_key"], r["language"], r["source_hash"], r["text"],
                                 tuple(json.loads(r["sentences"])) if r["sentences"] else None, r["provider_id"], r["model"],
                                 r["created_at"]) for r in rows]

    def put(self, t: BlockTranslation) -> None:
        with self._db.connect() as db:
            db.execute("INSERT OR REPLACE INTO block_translations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (t.doc_id, t.block_key, t.language, t.source_hash, t.text,
                        json.dumps(list(t.sentences), ensure_ascii=False) if t.sentences is not None else None,
                        t.provider_id, t.model, t.created_at))


class SqlitePageTextRepository(PageTextRepository):
    def __init__(self, database: Database) -> None:
        self._db = database

    def replace(self, doc_id: str, pages: list[str]) -> None:
        with self._db.connect() as db:
            db.execute("DELETE FROM page_texts WHERE doc_id = ?", (doc_id,))
            db.executemany("INSERT INTO page_texts (doc_id, page, text) VALUES (?, ?, ?)",
                           [(doc_id, number, text) for number, text in enumerate(pages, start=1)])

    def read(self, doc_id: str, first: int, last: int) -> list[tuple[int, str]]:
        with self._db.connect() as db:
            rows = db.execute("SELECT page, text FROM page_texts WHERE doc_id = ? AND page BETWEEN ? AND ? ORDER BY page",
                              (doc_id, first, last)).fetchall()
        return [(row["page"], row["text"]) for row in rows]

    def search(self, query: str, limit: int) -> list[tuple[str, int, str]]:
        needle = query.strip()
        if not needle:
            return []
        escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self._db.connect() as db:
            rows = db.execute("SELECT doc_id, page, text FROM page_texts WHERE text LIKE ? ESCAPE '\\' ORDER BY doc_id, page LIMIT ?",
                              (f"%{escaped}%", limit)).fetchall()
        results = []
        for row in rows:
            text = row["text"]
            at = text.lower().find(needle.lower())
            start = max(0, at - 80)
            snippet = ("…" if start else "") + " ".join(text[start:at + len(needle) + 120].split()) + "…"
            results.append((row["doc_id"], row["page"], snippet))
        return results


class SqliteCompletionCache(CompletionCache):
    def __init__(self, database: Database) -> None:
        self._db = database

    def get(self, key: str) -> str | None:
        with self._db.connect() as db:
            row = db.execute("SELECT text FROM completions WHERE key = ?", (key,)).fetchone()
        return row["text"] if row else None

    def put(self, key: str, text: str) -> None:
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._db.connect() as db:
            db.execute("INSERT OR REPLACE INTO completions (key, text, created_at) VALUES (?, ?, ?)", (key, text, stamp))


class SqliteConversationRepository(ConversationRepository):
    def __init__(self, database: Database) -> None:
        self._db = database

    def get(self, doc_id: str) -> list[dict]:
        with self._db.connect() as db:
            row = db.execute("SELECT turns FROM conversations WHERE doc_id = ?", (doc_id,)).fetchone()
        return json.loads(row["turns"]) if row else []

    def put(self, doc_id: str, turns: list[dict], updated_at: str, *, only_missing: bool = False) -> None:
        with self._db.connect() as db:
            # Retain an empty row after a user clears chat, so an old browser's legacy data cannot resurrect it.
            conflict = "IGNORE" if only_missing else "REPLACE"
            db.execute(f"INSERT OR {conflict} INTO conversations (doc_id, turns, updated_at) VALUES (?, ?, ?)",
                       (doc_id, json.dumps(turns, ensure_ascii=False), updated_at))

    def delete(self, doc_id: str) -> None:
        with self._db.connect() as db:
            db.execute("DELETE FROM conversations WHERE doc_id = ?", (doc_id,))


class SqlitePreferenceRepository(PreferenceRepository):
    def __init__(self, database: Database) -> None:
        self._db = database

    def all(self) -> dict:
        with self._db.connect() as db:
            rows = db.execute("SELECT key, value FROM preferences").fetchall()
        return {row["key"]: json.loads(row["value"]) for row in rows}

    def put_many(self, values: dict, *, only_missing: bool = False) -> None:
        with self._db.connect() as db:
            conflict = "IGNORE" if only_missing else "REPLACE"
            db.executemany(f"INSERT OR {conflict} INTO preferences (key, value) VALUES (?, ?)",
                           [(key, json.dumps(value, ensure_ascii=False)) for key, value in values.items()])
