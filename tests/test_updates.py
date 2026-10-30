import importlib.util
import json
import sqlite3
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path
from unittest import mock

from paperdesk.domain.errors import InvalidInput, ProviderUnavailable
from paperdesk.infrastructure.sqlite import Database, MIGRATIONS
from paperdesk.ports.updates import UpdateBackend, UpdateState
from paperdesk.services.updates import UpdateService
from paperdesk.web.server import create_server
from .helpers import DOWNGRADE_TO_V3, build_app, make_pdf

ROOT = Path(__file__).resolve().parents[1]


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecordingUpdates(UpdateBackend):
    def __init__(self):
        self.auto = False
        self.busy = False
        self.ready = False
        self.checks = 0

    def state(self):
        return UpdateState(True, not self.busy, self.auto, ready=self.ready)

    def check(self):
        self.checks += 1

    def set_automatic_checks(self, enabled):
        self.auto = enabled


class UpdateTests(unittest.TestCase):
    def test_unconfigured_build_does_not_claim_to_be_current_or_connect(self):
        service = UpdateService()
        state = service.view('en')
        self.assertFalse(state['available'])
        self.assertIn("can't update itself", state['message'])
        self.assertNotIn('up to date', state['message'])
        with self.assertRaises(ProviderUnavailable):
            service.check()

    def test_native_backend_receives_manual_check_and_opt_in(self):
        backend = RecordingUpdates()
        service = UpdateService(backend)
        self.assertFalse(service.view()['automatic_checks'])
        service.configure(True)
        self.assertTrue(backend.auto)
        self.assertEqual(service.check(), {'opened': True})
        self.assertEqual(backend.checks, 1)
        backend.busy = True
        with self.assertRaises(InvalidInput):
            service.check()
        for bad in ['yes', 1, None]:
            with self.assertRaises(InvalidInput):
                service.configure(bad)

    def test_restart_needs_a_downloaded_update_and_a_window_that_can_restart(self):
        backend = RecordingUpdates()
        service = UpdateService(backend)
        backend.ready = True
        self.assertFalse(service.view()['restart_ready'])  # the browser shell cannot restart itself
        with self.assertRaises(InvalidInput):
            service.restart()
        restarted = []
        service.allow_restart(lambda: restarted.append(True))
        backend.ready = False
        self.assertFalse(service.view()['restart_ready'])
        with self.assertRaises(InvalidInput):
            service.restart()
        backend.ready = True
        self.assertTrue(service.view()['restart_ready'])
        self.assertEqual(service.restart(), {'restarting': True})
        self.assertEqual(restarted, [True])

    def test_restart_closes_the_window_and_open_starts_again(self):
        from paperdesk import cli as commands
        backend = RecordingUpdates()
        backend.ready = True
        service = UpdateService(backend)
        window = mock.Mock()
        restart = commands._restartable(service, window)
        service.restart()
        self.assertTrue(restart.is_set())
        for _ in range(50):
            if window.close.called:
                break
            threading.Event().wait(0.05)
        window.close.assert_called_once_with()
        browser = UpdateService(backend)
        self.assertFalse(commands._restartable(browser, object()).is_set())
        with self.assertRaises(InvalidInput):
            browser.restart()

    def test_api_opens_native_ui_and_persists_user_choice_without_ai(self):
        app, tmp = build_app()
        backend = RecordingUpdates()
        app.updates.attach(backend)
        server = create_server(app, '127.0.0.1', 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        def call(path, method='GET', data=None):
            req = urllib.request.Request(server.url + path, method=method,
                data=json.dumps(data).encode() if data is not None else None,
                headers={'X-Paperdesk':'1','Content-Type':'application/json'})
            with urllib.request.urlopen(req) as response:
                return json.load(response)
        try:
            self.assertFalse(call('api/updates')['automatic_checks'])
            self.assertTrue(call('api/updates/preferences', 'PUT', {'automatic_checks':True})['automatic_checks'])
            self.assertEqual(call('api/updates/check','POST',{}), {'opened':True})
            self.assertEqual(backend.checks, 1)
        finally:
            server.shutdown()
            server.server_close()
            tmp.cleanup()

    def test_database_migration_backs_up_committed_library(self):
        app, tmp = build_app()
        try:
            doc, _ = app.library.import_pdf('old.pdf', make_pdf(['Data before an update']))
            # A real older installed schema, with existing user documents in WAL mode.
            with closing(sqlite3.connect(app.paths.database)) as connection, connection:
                connection.executescript(DOWNGRADE_TO_V3)
            Database(app.paths.database)
            backups = list((app.paths.root / 'backups/migrations').glob('*.sqlite3'))
            self.assertEqual(len(backups), 1)
            with closing(sqlite3.connect(backups[0])) as backup:
                self.assertEqual(backup.execute('PRAGMA user_version').fetchone()[0], 3)
                self.assertEqual(backup.execute('SELECT title FROM documents WHERE id=?',(doc.id,)).fetchone()[0], doc.title)
            Database(app.paths.database)
            self.assertEqual(len(list((app.paths.root / 'backups/migrations').glob('*.sqlite3'))), 1)
        finally:
            tmp.cleanup()

    def test_failed_migration_rolls_back_and_future_schema_is_refused(self):
        app, tmp = build_app()
        try:
            # Exercise a future migration that fails part-way through.
            with mock.patch('paperdesk.infrastructure.sqlite.MIGRATIONS', MIGRATIONS +
                            ('CREATE TABLE should_rollback(x); INVALID SQL;',)):
                with self.assertRaises(sqlite3.Error):
                    Database(app.paths.database)
            with closing(sqlite3.connect(app.paths.database)) as connection, connection:
                self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], len(MIGRATIONS))
                self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='should_rollback'").fetchone())
                connection.execute('PRAGMA user_version=99')
            with self.assertRaises(InvalidInput):
                Database(app.paths.database)
        finally:
            tmp.cleanup()
