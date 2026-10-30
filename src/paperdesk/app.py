"""Composition root: the only place that chooses concrete implementations."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import sqlite3
import uuid

from .config import AppPaths
from .infrastructure.blobs import FileBlobStore
from .infrastructure.downloads import UrllibDownloader
from .infrastructure.scholarly import ArxivIndex, CompositeIndex, OpenAlexIndex
from .infrastructure.settings_store import JsonSettingsStore
from .infrastructure.jobs import SqliteTranslationJobs
from .infrastructure.archives import LibraryArchives, apply_pending_restore, validate_database
from .domain.errors import InvalidInput
from .infrastructure.sqlite import (Database, SqliteCompletionCache, SqliteConversationRepository, SqliteDocumentRepository,
                                    SqliteFolderRepository, SqliteAnnotationRepository, SqlitePageTextRepository,
                                    SqlitePreferenceRepository, SqliteReadingListRepository, SqliteTranslationRepository)
from .platforms import Platform, current_platform
from .ports.ai import CommandRunner, HttpClient
from .ports.downloads import FileDownloader
from .ports.scholarly import ScholarlyIndex
from .ports.secrets import SecretStore
from .ports.settings import Settings, SettingsStore
from .providers.registry import ProviderRegistry, default_registry
from .providers.transport import SubprocessRunner, UrllibHttpClient
from .services.app_state import ConversationService, PreferenceService
from .services.assistant import AssistantService
from .services.library import FolderService, LibraryService
from .services.prompts import PromptBuilder
from .services.annotations import AnnotationService
from .services.reading_list import ReadingListService
from .services.reference_notes import ReferenceNoteService
from .services.translation import TranslationService
from .services.settings import SettingsService
from .services.updates import UpdateService
from .services.jobs import TranslationJobs
from .services.layout import LayoutAnalysis
from .services.organizer import OrganizerService
from .services.paper_info import PaperInfoService


@dataclass
class Application:
    paths: AppPaths
    platform: Platform
    library: LibraryService
    folders: FolderService
    assistant: AssistantService
    settings: SettingsService
    reading: ReadingListService
    annotations: AnnotationService
    translations: TranslationService
    reference_notes: ReferenceNoteService
    conversations: ConversationService
    preferences: PreferenceService
    updates: UpdateService
    jobs: TranslationJobs
    archives: LibraryArchives
    analysis: LayoutAnalysis
    paper_info: PaperInfoService
    organizer: OrganizerService
    restore_failed: bool = False

    @classmethod
    def build(cls, paths: AppPaths | None = None, *, secrets: SecretStore | None = None,
              settings_store: SettingsStore | None = None, registry: ProviderRegistry | None = None,
              runner: CommandRunner | None = None, http: HttpClient | None = None,
              platform: Platform | None = None, downloader: FileDownloader | None = None,
              scholarly: ScholarlyIndex | None = None, restore: bool = False) -> "Application":
        platform = platform or current_platform()
        paths = paths or AppPaths.default()
        restore_failed = False
        if restore:
            try:
                apply_pending_restore(paths)
            except (InvalidInput, ValueError, KeyError, TypeError, OSError, sqlite3.Error):
                # Only fall back after rollback has completed and the original database is usable.
                root = paths.root.resolve()
                pending = root/'pending-restore.json'
                if root.with_name('.'+root.name+'-restore.json').exists() or not pending.exists():
                    raise
                validate_database(paths.database.resolve())
                os.replace(pending, root/('failed-restore-'+uuid.uuid4().hex+'.json'))
                restore_failed = True
                logging.warning('Restore failed; opened the existing library. Failed request retained in the data directory.')
        paths = paths.ensure()
        database = Database(paths.database)
        documents = SqliteDocumentRepository(database)
        folders = FolderService(SqliteFolderRepository(database), documents)
        library = LibraryService(documents, FileBlobStore(paths.blobs), SqlitePageTextRepository(database), folders)
        runner = runner or SubprocessRunner()
        settings = SettingsService(
            store=settings_store or JsonSettingsStore(paths.settings_file, Settings(target_language=platform.preferred_language())),
            secrets=secrets or platform.secret_store(paths.root),
            registry=registry or default_registry(),
            runner=runner,
            http=http or UrllibHttpClient(),
        )
        cache = SqliteCompletionCache(database)
        assistant = AssistantService(active_provider=settings.active_provider, prompts=PromptBuilder(), cache=cache)
        downloader = downloader or UrllibDownloader()
        indexes = [scholarly] if scholarly else [ArxivIndex(downloader), OpenAlexIndex(downloader)]
        scholarly = scholarly or CompositeIndex(indexes)
        reading = ReadingListService(SqliteReadingListRepository(database), library, downloader, index=scholarly)
        annotations = AnnotationService(SqliteAnnotationRepository(database), library)
        translation_repository = SqliteTranslationRepository(database)
        translations = TranslationService(translation_repository, assistant, library,
                                          language=lambda: settings.load().target_language)
        notes = ReferenceNoteService(scholarly, assistant, cache)
        conversations = ConversationService(SqliteConversationRepository(database), library)
        preferences = PreferenceService(SqlitePreferenceRepository(database))
        def translate_job(doc_id, payload, blocks):
            options = dict(payload['options'])
            if payload['model']:
                options['model'] = payload['model']
            provider = settings.provider(payload['provider_id'], values=options)
            worker_assistant = AssistantService(active_provider=lambda: provider, prompts=PromptBuilder(), cache=cache)
            worker = TranslationService(translation_repository, worker_assistant, library,
                                        language=lambda: payload['language'])
            return worker.translate(doc_id, blocks, title=payload['title'], section=payload['section'],
                                    terms=payload['terms'], force=payload['force'])
        jobs = TranslationJobs(SqliteTranslationJobs(database), settings, library, translate_job, runner.close)
        return cls(paths, platform, library, folders, assistant, settings, reading, annotations, translations, notes,
                   conversations, preferences, UpdateService(), jobs, LibraryArchives(paths), LayoutAnalysis(paths, library),
                   PaperInfoService(library, indexes), OrganizerService(library, folders, assistant), restore_failed)
