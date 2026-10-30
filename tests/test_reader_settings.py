import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from paperdesk.infrastructure.settings_store import JsonSettingsStore
from paperdesk.ports.settings import Settings
from paperdesk.web.server import create_server
from .helpers import build_app


class ReaderSettingsTests(unittest.TestCase):
    def test_automatic_translation_persists_without_changing_existing_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'settings.json'
            path.write_text(json.dumps({'provider':'demo', 'target_language':'Korean', 'ui_language':'ko'}))
            store = JsonSettingsStore(path, Settings())
            app, temporary = build_app(settings_store=store)
            self.addCleanup(temporary.cleanup)
            self.assertTrue(app.settings.view()['auto_translate'])
            app.settings.update_general(auto_translate=False)
            reopened = JsonSettingsStore(path, Settings()).load()
            self.assertFalse(reopened.auto_translate)
            self.assertEqual((reopened.provider,reopened.target_language,reopened.ui_language),('demo','Korean','ko'))
            app.settings.update_general(target_language='Japanese')
            self.assertFalse(store.load().auto_translate)
            app.settings.update_general(auto_translate=True)
            self.assertTrue(JsonSettingsStore(path, Settings()).load().auto_translate)

    def test_paper_details_and_organizing_switches_default_on_and_persist(self):
        from paperdesk.domain.errors import InvalidInput
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'settings.json'
            path.write_text(json.dumps({'provider':'demo'}))  # saved by a version without these switches
            app, temporary = build_app(settings_store=JsonSettingsStore(path, Settings()))
            self.addCleanup(temporary.cleanup)
            self.assertEqual((app.settings.view()['auto_info'], app.settings.view()['auto_organize']), (True, True))
            app.settings.update_general(auto_organize=False)
            reopened = JsonSettingsStore(path, Settings()).load()
            self.assertEqual((reopened.auto_info, reopened.auto_organize, reopened.provider), (True, False, 'demo'))
            with self.assertRaises(InvalidInput):
                app.settings.update_general(auto_info='no')

    def test_setting_api_accepts_only_booleans_and_returns_the_saved_choice(self):
        app, temporary = build_app()
        self.addCleanup(temporary.cleanup)
        server = create_server(app,'127.0.0.1',0)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        for value in (False,True):
            req=urllib.request.Request(server.url+'api/settings',method='PUT',data=json.dumps({'auto_translate':value}).encode(),
                headers={'X-Paperdesk':'1','Content-Type':'application/json'})
            with urllib.request.urlopen(req) as response:
                self.assertIs(json.load(response)['auto_translate'],value)
        for value in ('false',0,[],{}):
            req=urllib.request.Request(server.url+'api/settings',method='PUT',data=json.dumps({'auto_translate':value}).encode(),
                headers={'X-Paperdesk':'1','Content-Type':'application/json'})
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(req)
            self.assertEqual(error.exception.code,400)
            error.exception.close()
            self.assertTrue(app.settings.load().auto_translate)
