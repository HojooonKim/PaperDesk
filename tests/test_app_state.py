import json
import sqlite3
import threading
import unittest
import urllib.request
from contextlib import closing
from pathlib import Path

from paperdesk.app import Application
from paperdesk.config import AppPaths
from paperdesk.domain.errors import InvalidInput, NotFound
from paperdesk.infrastructure.sqlite import Database
from paperdesk.web.server import create_server

from .helpers import DOWNGRADE_TO_V3, build_app, make_pdf


class AppStateTests(unittest.TestCase):
    """Chat history and UI preferences are stored in the app's database, not in the web view."""

    def setUp(self):
        self.app, self.tmp = build_app()
        self.doc, _ = self.app.library.import_pdf("a.pdf", make_pdf(["Hello paper"]))

    def tearDown(self):
        self.tmp.cleanup()

    def reopen(self) -> Application:
        app, unused = build_app(paths=AppPaths(Path(self.tmp.name)))
        unused.cleanup()
        return app

    def test_preferences_persist_and_reject_unknown_values(self):
        self.assertEqual(self.app.preferences.all()["theme"], "system")
        self.app.preferences.update({"theme": "dark", "expanded_folders": ["f1", "f2"]})
        reopened = self.reopen().preferences.all()
        self.assertEqual((reopened["theme"], reopened["expanded_folders"]), ("dark", ["f1", "f2"]))
        for bad in ({"theme": "neon"}, {"unknown": 1}, {"expanded_folders": "f1"}):
            with self.assertRaises(InvalidInput):
                self.app.preferences.update(bad)

    def test_pane_widths_persist_within_bounds(self):
        self.assertEqual((self.app.preferences.all()["sidebar_width"], self.app.preferences.all()["assistant_width"]), (252, 380))
        self.app.preferences.update({"sidebar_width": 320, "assistant_width": 520})
        reopened = self.reopen().preferences.all()
        self.assertEqual((reopened["sidebar_width"], reopened["assistant_width"]), (320, 520))
        for bad in ({"sidebar_width": 199}, {"sidebar_width": 421}, {"assistant_width": 641}, {"sidebar_width": True}, {"assistant_width": "400"}):
            with self.assertRaises(InvalidInput):
                self.app.preferences.update(bad)

    def test_conversation_is_kept_per_paper_and_deleted_with_it(self):
        turns = [{"task": "ask", "question": f"q{i}", "answer": "a"} for i in range(100)]
        self.app.conversations.save(self.doc.id, turns)
        saved = self.reopen().conversations.get(self.doc.id)
        self.assertEqual((len(saved), saved[0]["question"]), (80, "q20"))  # keeps the latest 80
        self.app.conversations.save(self.doc.id, [])
        self.assertEqual(self.app.conversations.get(self.doc.id), [])
        self.app.conversations.save(self.doc.id, turns[:2])
        self.app.library.delete(self.doc.id)
        with Database(self.app.paths.database).connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0], 0)
        with self.assertRaises(NotFound):
            self.app.conversations.get(self.doc.id)
        with self.assertRaises(InvalidInput):
            other, _ = self.app.library.import_pdf("b.pdf", make_pdf(["Other"]))
            self.app.conversations.save(other.id, "not a list")

    def test_legacy_import_preserves_new_values_and_cleared_chat(self):
        self.app.preferences.update({"theme": "dark"})
        self.app.preferences.update({"theme": "light", "translation_mode": "over"}, only_missing=True)
        self.assertEqual(self.app.preferences.all()["theme"], "dark")
        self.assertEqual(self.app.preferences.all()["translation_mode"], "over")
        old = [{"task": "ask", "question": "old", "status": "done"}]
        self.app.conversations.save(self.doc.id, old, only_missing=True)
        self.assertEqual(self.app.conversations.get(self.doc.id), old)
        self.app.conversations.save(self.doc.id, [])
        self.app.conversations.save(self.doc.id, old, only_missing=True)
        self.assertEqual(self.reopen().conversations.get(self.doc.id), [])

    def test_schema_upgrade_preserves_existing_library(self):
        # Reproduce an installed version-3 library before conversations/preferences were added.
        with closing(sqlite3.connect(self.app.paths.database)) as db, db:
            db.executescript(DOWNGRADE_TO_V3)
        reopened = self.reopen()
        self.assertEqual(reopened.library.get(self.doc.id).title, self.doc.title)
        reopened.preferences.update({"theme": "dark"})
        reopened.conversations.save(self.doc.id, [{"answer": "stored after upgrade"}])
        self.assertEqual(self.reopen().conversations.get(self.doc.id)[0]["answer"], "stored after upgrade")

    def test_boot_script_carries_saved_preferences(self):
        self.app.preferences.update({"theme": "light", "sidebar": "hidden"})
        server = create_server(self.app, "127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with urllib.request.urlopen(server.url + "boot.js", timeout=5) as response:
                body = response.read().decode()
            prefix = "window.paperdeskBoot = "
            data = json.loads(body.strip()[len(prefix):].rstrip(";").replace("preferences:", '"preferences":'))
            self.assertEqual((data["preferences"]["theme"], data["preferences"]["sidebar"]), ("light", "hidden"))
            request = urllib.request.Request(server.url + "api/documents/" + self.doc.id + "/conversation", method="PUT",
                                             data=json.dumps({"turns": [{"task": "ask"}]}).encode(),
                                             headers={"X-Paperdesk": "1", "Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=5) as response:
                self.assertEqual(json.loads(response.read())["saved"], 1)
        finally:
            server.shutdown()
            server.server_close()
