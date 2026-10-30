import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from contextlib import closing
from unittest import mock

from paperdesk.app import Application
from paperdesk.config import AppPaths
from paperdesk.domain.errors import InvalidInput, ProviderFailed, ProviderLimitReached
from paperdesk.domain.models import utcnow
from paperdesk.infrastructure.archives import apply_pending_restore, digest
from paperdesk.infrastructure.instance import library_lock
from paperdesk.infrastructure.sqlite import Database, MIGRATIONS
from paperdesk.platforms import MacPlatform
from paperdesk.ports.ai import CommandResult
from paperdesk.providers.codex_cli import CodexCliProvider
from paperdesk.providers.claude_code import ClaudeCodeProvider
from paperdesk.services.diagnostics import diagnostic_report
from .helpers import build_app, make_pdf
from .test_providers import context, FakeRunner, found


def wait_for(test, timeout=4):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        if test():
            return
        time.sleep(.02)
    raise AssertionError('Timed out waiting for the worker')


class JobTests(unittest.TestCase):
    def setUp(self):
        self.app, self.tmp = build_app()
        self.doc, _ = self.app.library.import_pdf('test.pdf', make_pdf(['One sentence.']))
        self.app.settings.update_general(provider='demo')
        self.app.jobs.retry_delays = (0, 0)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.app.jobs.close)

    def test_job_completes_and_stores_translations(self):
        job = self.app.jobs.create(self.doc.id, {'blocks':[{'key':'1:abcd','sentences':['One.','Two.']}]})
        wait_for(lambda:self.app.jobs.repository.get(job['id'])['state']=='completed')
        saved=self.app.translations.list(self.doc.id)['blocks']['1:abcd']
        self.assertEqual(len(saved['sentences']),2)
        self.assertEqual(self.app.jobs.list(self.doc.id)[0]['completed'],1)

    def test_job_status_exposes_only_remaining_keys_for_pending_cards(self):
        from paperdesk.services.jobs import TranslationJobs
        job={'id':'job','doc_id':self.doc.id,'state':'running','completed':1,'total':2,
             'error':'','created_at':'now','updated_at':'now','payload':{
                 'provider_id':'demo','model':'test','language':'Korean',
                 'blocks':[{'key':'first','sentences':['Private source.']},
                           {'key':'second','sentences':['Another source.']}]}}
        view=TranslationJobs.view(job)
        self.assertEqual(view['pending_keys'],['second'])
        self.assertNotIn('Private source',json.dumps(view))
        for state in ('paused','failed','cancelled','completed'):
            job['state']=state
            self.assertEqual(TranslationJobs.view(job)['pending_keys'],[])

    def test_duplicate_running_request_is_not_sent_twice_and_cancel_stops_remaining_batches(self):
        entered, release = threading.Event(), threading.Event()
        calls=[]
        def translate(doc_id,payload,blocks):
            calls.append((payload['language'],payload['provider_id']))
            entered.set()
            release.wait(3)
            return {'missing':[]}
        self.app.jobs.translate=translate
        data={'blocks':[{'key':f'1:abcd{i}', 'sentences':['Sentence.']} for i in range(12)]}
        first=self.app.jobs.create(self.doc.id,data)
        self.assertTrue(entered.wait(2))
        status=self.app.jobs.list(self.doc.id)[0]
        self.assertEqual(status['active_keys'],[b['key'] for b in data['blocks'][:10]])
        self.assertEqual(status['pending_keys'],[b['key'] for b in data['blocks']])
        second=self.app.jobs.create(self.doc.id,data)
        self.assertEqual(first['id'],second['id'])
        self.app.settings.update_general(target_language='Japanese')
        self.app.jobs.action(first['id'],'cancel')
        release.set()
        wait_for(lambda:not self.app.jobs.list(self.doc.id)[0]['request_in_flight'])
        self.assertEqual(self.app.jobs.repository.get(first['id'])['state'],'cancelled')
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0],('Korean','demo'))

    def test_paragraphs_already_waiting_in_a_job_are_not_queued_again(self):
        # The reader and the background translation after an import can both ask for the same paper.
        entered, release = threading.Event(), threading.Event()
        def translate(doc_id,payload,blocks):
            entered.set(); release.wait(3)
            return {'missing':[]}
        self.app.jobs.translate=translate
        self.addCleanup(release.set)
        block=lambda i:{'key':f'1:abcd{i}','sentences':['Sentence.']}
        first=self.app.jobs.create(self.doc.id,{'blocks':[block(i) for i in range(12)],'title':'From the reader'})
        self.assertTrue(entered.wait(2))
        second=self.app.jobs.create(self.doc.id,{'blocks':[block(i) for i in range(5,15)],'title':'In the background'})
        self.assertNotEqual(first['id'],second['id'])
        self.assertEqual(self.app.jobs.list(self.doc.id)[1]['pending_keys'],[f'1:abcd{i}' for i in (12,13,14)])
        self.assertEqual(self.app.jobs.create(self.doc.id,{'blocks':[block(3)]})['id'],first['id'])  # nothing new
        forced=self.app.jobs.create(self.doc.id,{'blocks':[block(3)],'force':True})  # "translate again" still works
        self.assertEqual(self.app.jobs.list(self.doc.id)[-1]['pending_keys'],['1:abcd3'])
        self.assertNotIn(forced['id'],(first['id'],second['id']))

    def test_incomplete_batch_reports_missing_keys_and_explicit_resume_uses_single_blocks(self):
        calls=[]
        def translate(doc_id,payload,blocks):
            calls.append([b.key for b in blocks])
            return {'missing':['1:abcd2'] if len(calls)<=3 and '1:abcd2' in calls[-1] else []}
        self.app.jobs.translate=translate
        job=self.app.jobs.create(self.doc.id,{'blocks':[{'key':f'1:abcd{i}','sentences':['Sentence.']} for i in range(3)]})
        wait_for(lambda:self.app.jobs.repository.get(job['id'])['state']=='failed')
        self.assertEqual(self.app.jobs.list(self.doc.id)[0]['missing_keys'],['1:abcd2'])
        self.assertEqual(calls,[['1:abcd0','1:abcd1','1:abcd2'],['1:abcd2'],['1:abcd2']])
        self.app.jobs.action(job['id'],'resume')
        wait_for(lambda:self.app.jobs.repository.get(job['id'])['state']=='completed')
        self.assertEqual([len(batch) for batch in calls],[3,1,1,1,1,1])
        self.assertEqual(self.app.jobs.list(self.doc.id)[0]['missing_keys'],[])

    def test_paragraphs_left_out_of_a_reply_are_retried_one_by_one(self):
        calls=[]
        def translate(doc_id,payload,blocks):
            calls.append([b.key for b in blocks])
            return {'missing':['1:abcd0','1:abcd2'] if len(calls)==1 else []}
        self.app.jobs.translate=translate
        job=self.app.jobs.create(self.doc.id,{'blocks':[{'key':f'1:abcd{i}','sentences':['Sentence.']} for i in range(3)]})
        wait_for(lambda:self.app.jobs.repository.get(job['id'])['state']=='completed')
        self.assertEqual(calls,[['1:abcd0','1:abcd1','1:abcd2'],['1:abcd0'],['1:abcd2']])
        self.assertEqual(self.app.jobs.list(self.doc.id)[0]['missing_keys'],[])

    def test_transient_failure_is_resent_but_quota_errors_stop_at_once(self):
        calls=[]
        def flaky(doc_id,payload,blocks):
            calls.append(1)
            if len(calls)==1: raise ProviderFailed('connection dropped')
            return {'missing':[]}
        self.app.jobs.translate=flaky
        job=self.app.jobs.create(self.doc.id,{'blocks':[{'key':'1:abcd','sentences':['One.']}]})
        wait_for(lambda:self.app.jobs.repository.get(job['id'])['state']=='completed')
        self.assertEqual(len(calls),2)
        limited=[]
        def quota(*args): limited.append(1); raise ProviderLimitReached('limit')
        self.app.jobs.translate=quota
        job=self.app.jobs.create(self.doc.id,{'blocks':[{'key':'1:abce','sentences':['Two.']}]})
        wait_for(lambda:self.app.jobs.repository.get(job['id'])['state']=='failed')
        self.assertEqual((len(limited),self.app.jobs.repository.get(job['id'])['error']),(1,'rate_limited'))

    def test_cancel_during_a_retry_pause_sends_nothing_more(self):
        self.app.jobs.retry_delays=(.5,)
        failed=threading.Event();calls=[]
        def fail(*args): calls.append(1); failed.set(); raise ProviderFailed('timeout')
        self.app.jobs.translate=fail
        job=self.app.jobs.create(self.doc.id,{'blocks':[{'key':'1:abcd','sentences':['One.']}]})
        self.assertTrue(failed.wait(2))
        self.app.jobs.action(job['id'],'cancel')
        wait_for(lambda:self.app.jobs._inflight is None)
        self.assertEqual((len(calls),self.app.jobs.repository.get(job['id'])['state']),(1,'cancelled'))

    def test_restart_pauses_unsent_and_inflight_jobs_until_explicit_resume(self):
        stamp=utcnow()
        payload={'provider_id':'demo','model':'','options':{},'language':'Korean','title':'','section':'','terms':'','force':False,
                 'blocks':[{'key':'1:abcd','sentences':['One.']}]}
        self.app.jobs.repository.add({'id':'interrupted','doc_id':self.doc.id,'fingerprint':'test','payload':payload,
                                     'state':'running','total':1,'created_at':stamp,'updated_at':stamp})
        self.app.jobs.start()
        self.assertEqual(self.app.jobs.list(self.doc.id)[0]['state'],'paused')
        time.sleep(.05)
        self.assertEqual(self.app.translations.list(self.doc.id)['blocks'],{})
        self.app.jobs.action('interrupted','resume')
        wait_for(lambda:self.app.jobs.repository.get('interrupted')['state']=='completed')

    def test_failure_saves_only_a_code_and_resume_is_explicit(self):
        def fail(*args): raise ProviderFailed('SECRET source text must not persist in job errors')
        self.app.jobs.translate=fail
        job=self.app.jobs.create(self.doc.id,{'blocks':[{'key':'1:abcd','sentences':['One.']}]})
        wait_for(lambda:self.app.jobs.repository.get(job['id'])['state']=='failed')
        saved=self.app.jobs.list(self.doc.id)[0]
        self.assertEqual(saved['error'],'provider_failed')
        self.assertNotIn('SECRET',json.dumps(saved))


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.app,self.tmp=build_app()
        self.addCleanup(self.tmp.cleanup)
        self.doc,_=self.app.library.import_pdf('private-title.pdf',make_pdf(['PRIVATE CONTENT']))
        self.app.settings.update_general(provider='demo',target_language='Korean')
        self.app.conversations.save(self.doc.id,[{'answer':'private chat','status':'done'}])
        self.app.preferences.update({'theme':'dark'})

    def test_round_trip_preserves_entire_library_excludes_secrets_and_keeps_previous_library(self):
        (self.app.paths.root/'secrets.json').write_text('{"key":"TOPSECRET"}')
        (self.app.paths.root/'webview').mkdir()
        (self.app.paths.root/'webview'/'cookie').write_text('COOKIESECRET')
        archive=self.app.archives.export()
        with zipfile.ZipFile(archive) as z:
            self.assertNotIn('secrets.json',z.namelist())
            self.assertFalse(any('webview' in p for p in z.namelist()))
        checked=self.app.archives.prepare(archive)
        self.assertEqual(checked['documents'],1)
        self.app.library.rename(self.doc.id,'changed after backup')
        self.app.archives.schedule(checked['token'])
        self.assertEqual(self.app.library.get(self.doc.id).title,'changed after backup')
        apply_pending_restore(self.app.paths)
        restored=Application.build(paths=self.app.paths)
        self.assertEqual(restored.library.get(self.doc.id).title,'private-title')
        self.assertEqual(restored.conversations.get(self.doc.id)[0]['answer'],'private chat')
        self.assertEqual(restored.preferences.all()['theme'],'dark')
        self.assertTrue(restored.library.pdf_path(self.doc.id).is_file())
        self.assertFalse((self.app.paths.root/'secrets.json').exists())
        old=self.app.paths.root.with_name(self.app.paths.root.name+'.before-restore-'+checked['token'])
        self.addCleanup(lambda:__import__('shutil').rmtree(old,ignore_errors=True))
        with closing(sqlite3.connect(old/'library.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT title FROM documents').fetchone()[0],'changed after backup')

    def test_checksum_corruption_and_path_traversal_do_not_modify_live_library(self):
        archive=self.app.archives.export()
        bad=self.app.paths.root/'bad.zip'
        with zipfile.ZipFile(archive) as source,zipfile.ZipFile(bad,'w') as target:
            for item in source.infolist():
                target.writestr(item.filename,b'bad data' if item.filename.endswith('.pdf') else source.read(item.filename))
        with self.assertRaises(InvalidInput):self.app.archives.prepare(bad)
        with zipfile.ZipFile(bad,'w') as target:target.writestr('../escape','evil')
        with self.assertRaises(InvalidInput):self.app.archives.prepare(bad)
        self.assertEqual(self.app.library.get(self.doc.id).title,'private-title')
        self.assertFalse((self.app.paths.root/'escape').exists())

    def test_tampered_staging_and_future_schema_are_rejected(self):
        archive=self.app.archives.export()
        checked=self.app.archives.prepare(archive)
        stage=self.app.paths.root/'restore-staging'/checked['token']
        (stage/'files/documents'/f'{self.doc.id}.pdf').write_bytes(b'bad')
        self.app.archives.schedule(checked['token'])
        with self.assertRaises(InvalidInput):apply_pending_restore(self.app.paths)
        self.assertTrue(self.app.library.pdf_path(self.doc.id).is_file())
        with tempfile.TemporaryDirectory() as folder:
            with zipfile.ZipFile(archive) as z:z.extractall(folder)
            dbpath=Path(folder)/'library.sqlite3'
            with closing(sqlite3.connect(dbpath)) as db, db:db.execute('PRAGMA user_version=999')
            manifest=json.loads((Path(folder)/'manifest.json').read_text())
            manifest['sha256']['library.sqlite3']=digest(dbpath)
            (Path(folder)/'manifest.json').write_text(json.dumps(manifest))
            bad=Path(folder)/'future.zip'
            with zipfile.ZipFile(bad,'w') as z:
                for p in Path(folder).rglob('*'):
                    if p.is_file() and p!=bad:z.write(p,p.relative_to(folder))
            with self.assertRaises(InvalidInput):self.app.archives.prepare(bad)

    def test_failed_swap_restores_original_and_keeps_validated_snapshot(self):
        checked=self.app.archives.prepare(self.app.archives.export())
        self.app.archives.schedule(checked['token'])
        original=os.replace
        def replace(source,target):
            if Path(source).name==self.app.paths.root.name+'.restore-'+checked['token'] and Path(target).resolve()==self.app.paths.root.resolve():
                raise OSError('simulated disk error')
            return original(source,target)
        with mock.patch('paperdesk.infrastructure.archives.os.replace',side_effect=replace):
            with self.assertRaises(OSError):apply_pending_restore(self.app.paths)
        self.assertEqual(self.app.library.get(self.doc.id).title,'private-title')
        self.assertTrue((self.app.paths.root/'restore-staging'/checked['token']/'library.sqlite3').exists())

    def test_backup_settings_are_filtered_even_for_unknown_provider_fields(self):
        self.app.paths.settings_file.write_text(json.dumps({'provider_options':{'x':{'api_key':'SECRET','access_token':'SECRET','model':'m'}}}))
        archive=self.app.archives.export()
        with zipfile.ZipFile(archive) as z:self.assertNotIn('SECRET',z.read('settings.json').decode())

    def test_journal_write_failure_leaves_original_and_staging_in_place(self):
        checked=self.app.archives.prepare(self.app.archives.export())
        self.app.archives.schedule(checked['token'])
        original=Path.write_text
        def write(path,*args,**kwargs):
            if path.name=='.'+self.app.paths.root.name+'-restore.json.tmp':
                raise OSError('disk full')
            return original(path,*args,**kwargs)
        with mock.patch.object(Path,'write_text',write):
            with self.assertRaises(OSError):apply_pending_restore(self.app.paths)
        self.assertEqual(self.app.library.get(self.doc.id).title,'private-title')
        self.assertTrue((self.app.paths.root/'restore-staging'/checked['token']/'library.sqlite3').is_file())

    def test_recovery_after_interrupted_directory_swap(self):
        checked=self.app.archives.prepare(self.app.archives.export())
        self.app.archives.schedule(checked['token'])
        root=self.app.paths.root.resolve();token=checked['token']
        candidate=root.with_name(root.name+'.restore-'+token)
        old=root.with_name(root.name+'.before-restore-'+token)
        journal=root.with_name('.'+root.name+'-restore.json')
        journal.write_text(json.dumps({'old':old.name,'candidate':candidate.name,'token':token}))
        os.replace(root/'restore-staging'/token,candidate)
        os.replace(root,old)
        apply_pending_restore(self.app.paths)
        self.assertTrue((root/'library.sqlite3').is_file())
        self.assertFalse(journal.exists())
        self.addCleanup(lambda:__import__('shutil').rmtree(old,ignore_errors=True))


class ReleaseSafetyTests(unittest.TestCase):
    def test_branding_does_not_change_data_directory_or_keychain(self):
        with mock.patch('paperdesk.APP_NAME','New Brand'),mock.patch('paperdesk.APP_ID','new-brand'):
            self.assertEqual(MacPlatform().data_dir().name,'Paperdesk')
            self.assertEqual(MacPlatform().secret_store(Path('/tmp')).service,'paperdesk')

    def test_same_data_directory_cannot_have_two_owners(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'library'
            with library_lock(root):
                with self.assertRaises(InvalidInput):
                    with library_lock(root):pass
            with library_lock(root):pass

    def test_diagnostic_allowlist_excludes_user_data(self):
        app,tmp=build_app()
        self.addCleanup(tmp.cleanup)
        app.library.import_pdf('SECRET-TITLE.pdf',make_pdf(['SECRET BODY']))
        app.settings.update_provider('openai-api',{'api_key':'SECRET-KEY'})
        report=json.dumps(diagnostic_report(app.paths))
        self.assertNotIn('SECRET',report)
        self.assertNotIn(str(app.paths.root),report)

    def test_cli_errors_are_actionable_without_raw_output(self):
        samples=[('model_not_found SECRET','unsupported_model'),('You have hit your usage limit SECRET','rate_limited'),
                 ('OAuth session expired SECRET','auth_required'),('private stderr SECRET','provider_failed')]
        for text,code in samples:
            provider=CodexCliProvider(context('codex-cli',runner=FakeRunner(CommandResult(1,'',text))),which=found('/bin/codex'))
            with self.assertRaises(ProviderFailed) as caught:provider.complete(__import__('paperdesk.domain.models',fromlist=['Prompt']).Prompt('x','y'))
            self.assertEqual(caught.exception.code,code)
            self.assertNotIn('SECRET',str(caught.exception))


class DeploymentApiTests(unittest.TestCase):
    def setUp(self):
        import urllib.request
        from paperdesk.web.server import create_server
        self.app,self.tmp=build_app()
        self.app.settings.update_general(provider='demo')
        self.doc,_=self.app.library.import_pdf('api.pdf',make_pdf(['API sentence.']))
        self.server=create_server(self.app,'127.0.0.1',0)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def call(self,path,method='GET',data=None):
        import urllib.request
        body=data if isinstance(data,bytes) else json.dumps(data).encode() if data is not None else None
        request=urllib.request.Request(self.server.url+path,body,method=method,headers={'X-Paperdesk':'1','Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=5) as response:
            payload=response.read()
            return json.loads(payload) if response.headers['Content-Type'].startswith('application/json') else payload

    def test_job_routes_and_server_restart_preserve_results(self):
        path='api/documents/'+self.doc.id+'/translation-jobs'
        created=self.call(path,'POST',{'blocks':[{'key':'1:abcd','sentences':['One.']}]})['job']
        wait_for(lambda:self.call(path)['jobs'][0]['state']=='completed')
        self.assertEqual(self.call(path)['jobs'][0]['id'],created['id'])
        self.assertIn('1:abcd',self.call('api/documents/'+self.doc.id+'/translations')['blocks'])

    def test_restore_failure_notice_is_exposed_to_the_ui(self):
        self.app.restore_failed = True
        self.assertIn(b'"restoreFailed": true', self.call('boot.js'))

    def test_static_scripts_are_javascript_even_if_the_system_says_text_plain(self):
        # Windows can register .js as text/plain (HKEY_CLASSES_ROOT); with nosniff the web view would run no script.
        import urllib.request
        with mock.patch('paperdesk.web.server.mimetypes.guess_type',return_value=('text/plain',None)):
            for path,kind in (('app.js','text/javascript'),('app.css','text/css'),('','text/html')):
                with urllib.request.urlopen(self.server.url+path,timeout=5) as response:
                    self.assertEqual(response.headers['Content-Type'],kind+'; charset=utf-8')

    def test_export_inspect_and_restore_require_confirmed_token(self):
        download=self.call('api/backups/export','POST',{})['url'].lstrip('/')
        data=self.call(download)
        self.assertTrue(data.startswith(b'PK'))
        checked=self.call('api/backups/inspect','POST',data)
        self.assertEqual(checked['documents'],1)
        self.assertFalse((self.app.paths.root/'pending-restore.json').exists())
        result=self.call('api/backups/restore','POST',{'token':checked['token']})
        self.assertTrue(result['restart_required'])
        self.assertEqual(self.app.library.get(self.doc.id).title,'api')
        report=self.call('api/diagnostics')
        self.assertNotIn(str(self.app.paths.root),json.dumps(report))

    def test_library_activity_reports_progress_without_source_text(self):
        from paperdesk.domain.models import utcnow
        stamp=utcnow()
        payload={'provider_id':'demo','model':'','language':'Korean','blocks':[{'key':'1:abcd','sentences':['PRIVATE SOURCE TEXT']} ]}
        self.app.jobs.repository.add({'id':'activity','doc_id':self.doc.id,'fingerprint':'activity','payload':payload,
                                     'state':'paused','total':1,'created_at':stamp,'updated_at':stamp})
        data=self.call('api/activity')
        self.assertEqual(data['translations'][0]['state'],'paused')
        self.assertEqual(data['analysis'][0]['state'],'not_started')
        self.assertNotIn('PRIVATE SOURCE',json.dumps(data))

    def test_bad_job_payload_is_a_client_error(self):
        import urllib.error
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.call('api/documents/'+self.doc.id+'/translation-jobs','POST',{'blocks':['invalid']})
        self.assertEqual(caught.exception.code,400)


class DiscoveryAndGateTests(unittest.TestCase):
    def test_cli_discovery_prefers_newer_install_and_preserves_explicit_choice(self):
        class Versions(FakeRunner):
            def run(self,argv,**kwargs):
                return CommandResult(0,'codex-cli '+('0.165.0' if Path(argv[0]).parent.name=='new' else '0.147.0'),'')
            def codex_models(self,path):return ['gpt-6-luna','gpt-5.6-luna']
        name='codex.exe' if os.name=='nt' else 'codex'
        with tempfile.TemporaryDirectory() as folder:
            old=Path(folder)/'old'/name;new=Path(folder)/'new'/name
            old.parent.mkdir();new.parent.mkdir();old.touch();new.touch()
            os.chmod(old,0o700);os.chmod(new,0o700)
            runner=Versions(CommandResult(0,'',''))
            provider=CodexCliProvider(context('codex-cli',runner=runner),which=found(str(old)))
            provider.extra_dirs=(str(new.parent),)
            with mock.patch('paperdesk.providers.cli.COMMON_BIN_DIRS',()):
                result=provider.discover()
            self.assertEqual(result['selected'],str(new))
            self.assertIn('gpt-6-luna',result['models'])
            explicit=CodexCliProvider(context('codex-cli',{'binary':str(old)},runner=runner),which=found(str(old)))
            explicit.extra_dirs=(str(new.parent),)
            with mock.patch('paperdesk.providers.cli.COMMON_BIN_DIRS',()):self.assertEqual(explicit.discover()['selected'],str(old))



class ReviewRegressionTests(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.TemporaryDirectory()
        self.addCleanup(self.base.cleanup)
        self.paths = AppPaths(Path(self.base.name)/'library')
        self.app, temporary = build_app(paths=self.paths)
        temporary.cleanup()
        self.doc, _ = self.app.library.import_pdf('original.pdf', make_pdf(['Keep this paper.']))
        self.addCleanup(self.app.jobs.close)

    def schedule(self):
        checked = self.app.archives.prepare(self.app.archives.export())
        self.app.archives.schedule(checked['token'])
        return checked['token']

    def test_damaged_pending_restore_opens_original_and_does_not_block_next_launch(self):
        token = self.schedule()
        (self.paths.root/'restore-staging'/token/'files/documents'/f'{self.doc.id}.pdf').write_bytes(b'bad')
        first = Application.build(paths=self.paths, restore=True)
        self.assertTrue(first.restore_failed)
        self.assertEqual(first.library.get(self.doc.id).title, 'original')
        self.assertFalse((self.paths.root/'pending-restore.json').exists())
        self.assertEqual(len(list(self.paths.root.glob('failed-restore-*.json'))), 1)
        second = Application.build(paths=self.paths, restore=True)
        self.assertFalse(second.restore_failed)
        self.assertEqual(second.library.get(self.doc.id).title, 'original')

    def test_falsely_claimed_schema_is_rejected_before_scheduling(self):
        source = Path(self.base.name)/'fake.sqlite3'
        with closing(sqlite3.connect(source)) as db, db:
            db.execute('CREATE TABLE documents(id TEXT,sha256 TEXT)')
            db.execute(f'PRAGMA user_version={len(MIGRATIONS)}')
        archive = Path(self.base.name)/'invalid.paperdesk'
        manifest = {'format':1, 'storage_id':'paperdesk', 'sha256':{
            'library.sqlite3':digest(source), 'settings.json':hashlib.sha256(b'{}').hexdigest()}}
        with zipfile.ZipFile(archive, 'w') as output:
            output.write(source, 'library.sqlite3')
            output.writestr('settings.json', '{}')
            output.writestr('manifest.json', json.dumps(manifest))
        with self.assertRaises(InvalidInput):
            self.app.archives.prepare(archive)
        self.assertEqual(self.app.library.get(self.doc.id).title, 'original')

    def test_older_valid_backup_is_checked_and_migrated_on_restore(self):
        from paperdesk.infrastructure.archives import validate_database
        with closing(sqlite3.connect(self.paths.database)) as db, db:
            db.executescript('DROP TABLE translation_jobs; DROP TABLE conversations; DROP TABLE preferences; PRAGMA user_version=3;')
        version, documents = validate_database(self.paths.database)
        self.assertEqual(version, 3)
        self.assertEqual(documents[0][0], self.doc.id)
        with closing(sqlite3.connect(self.paths.database)) as db, db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 3)
        self.schedule()
        restored = Application.build(paths=self.paths, restore=True)
        self.assertEqual(restored.library.get(self.doc.id).title, 'original')
        self.assertEqual(restored.preferences.all()['theme'], 'system')

    def test_unexpected_root_creation_during_swap_rolls_back_original(self):
        token = self.schedule()
        root = self.paths.root.resolve()
        old = root.with_name(root.name+'.before-restore-'+token)
        replace = os.replace
        def concurrent(source, target):
            result = replace(source, target)
            if Path(source) == root and Path(target) == old:
                Application.build(paths=self.paths)
            return result
        with mock.patch('paperdesk.infrastructure.archives.os.replace', side_effect=concurrent):
            with self.assertRaises(OSError):
                apply_pending_restore(self.paths)
        self.assertEqual(Application.build(paths=self.paths).library.get(self.doc.id).title, 'original')
        self.assertTrue((root/'restore-staging'/token/'library.sqlite3').exists())
        self.assertEqual(len(list(root.parent.glob(root.name+'.restore-conflict-*'))), 1)
        self.assertFalse(root.with_name('.'+root.name+'-restore.json').exists())

    def test_failed_rollback_retains_journal_and_next_start_recovers(self):
        token = self.schedule()
        root = self.paths.root.resolve()
        old = root.with_name(root.name+'.before-restore-'+token)
        candidate = root.with_name(root.name+'.restore-'+token)
        replace = os.replace
        def fail(source, target):
            if Path(target) == root and Path(source) in (old, candidate):
                raise OSError('disk unavailable')
            return replace(source, target)
        with mock.patch('paperdesk.infrastructure.archives.os.replace', side_effect=fail):
            with self.assertRaises(OSError):
                apply_pending_restore(self.paths)
        self.assertTrue(root.with_name('.'+root.name+'-restore.json').exists())
        self.assertTrue((old/'library.sqlite3').exists())
        apply_pending_restore(self.paths)
        self.assertEqual(Application.build(paths=self.paths).library.get(self.doc.id).title, 'original')

    def test_interruption_after_install_keeps_restored_library(self):
        token = self.schedule()
        self.app.library.rename(self.doc.id, 'changed since backup')
        root = self.paths.root.resolve()
        journal = root.with_name('.'+root.name+'-restore.json')
        unlink = Path.unlink
        def interrupted(path, *args, **kwargs):
            if path == journal:
                raise OSError('interruption after install')
            return unlink(path, *args, **kwargs)
        with mock.patch.object(Path, 'unlink', interrupted):
            with self.assertRaises(OSError):
                apply_pending_restore(self.paths)
        self.assertTrue(journal.exists())
        apply_pending_restore(self.paths)
        self.assertEqual(Application.build(paths=self.paths).library.get(self.doc.id).title, 'original')
        old = self.paths.root.with_name(self.paths.root.name+'.before-restore-'+token)
        with closing(sqlite3.connect(old/'library.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT title FROM documents').fetchone()[0], 'changed since backup')

    def test_all_cli_entrypoints_refuse_access_during_restore(self):
        import io
        from paperdesk.cli import main
        from paperdesk.infrastructure.instance import library_access
        with mock.patch.dict(os.environ, {'PAPERDESK_HOME':str(self.paths.root)}), library_access(self.paths.root, exclusive=True):
            with mock.patch('paperdesk.cli.Application.build') as build, mock.patch('paperdesk.cli._running_instance', return_value=False):
                with mock.patch('sys.stderr', io.StringIO()):
                    for args in (['mcp'], ['doctor'], ['open'], ['serve'], ['backup','inspect','unused.paperdesk']):
                        self.assertEqual(main(args), 1, args)
                build.assert_not_called()

    def test_cli_restore_blocked_by_an_open_file_explains_and_keeps_the_library(self):
        import io
        from paperdesk.cli import main
        archive = str(self.app.archives.export())
        self.app.library.rename(self.doc.id, 'changed since backup')
        root = self.paths.root.resolve()
        replace = os.replace
        def held_open(source, target):
            if Path(source) == root:  # Windows: another program has a file inside the library folder open
                raise PermissionError(13, 'Access is denied', str(source))
            return replace(source, target)
        def title():
            with closing(sqlite3.connect(root/'library.sqlite3')) as db:
                return db.execute('SELECT title FROM documents').fetchone()[0]
        with mock.patch.dict(os.environ, {'PAPERDESK_HOME':str(self.paths.root)}):
            with mock.patch('paperdesk.infrastructure.archives.os.replace', side_effect=held_open), \
                 mock.patch('paperdesk.infrastructure.archives.time.sleep'), mock.patch('sys.stderr', io.StringIO()) as stderr:
                self.assertEqual(main(['backup','restore',archive,'--replace-library']), 1)
            self.assertIn('current library was not changed', stderr.getvalue())
            self.assertNotIn('Traceback', stderr.getvalue())
            self.assertEqual(title(), 'changed since backup')
            self.assertFalse((root/'pending-restore.json').exists())  # the next launch does not restore unasked
            with mock.patch('sys.stdout', io.StringIO()):
                self.assertEqual(main(['backup','restore',archive,'--replace-library']), 0)  # once the file is closed
        self.assertEqual(title(), 'original')

    def test_shared_app_and_mcp_access_coexist_but_restore_is_exclusive(self):
        from paperdesk.cli import _application
        from paperdesk.infrastructure.instance import library_access
        with mock.patch.dict(os.environ, {'PAPERDESK_HOME':str(self.paths.root)}):
            with _application(restore=True) as owner:
                with _application() as client:
                    self.assertEqual(client.library.get(self.doc.id).id, self.doc.id)

                with self.assertRaises(InvalidInput):
                    with library_access(self.paths.root, exclusive=True):
                        pass
                owner.archives.schedule(owner.archives.prepare(owner.archives.export())['token'])
            with _application(restore=True):
                # Exclusive startup has downgraded to shared access after the swap.
                with _application() as client:
                    self.assertEqual(client.library.get(self.doc.id).id, self.doc.id)

    def test_mcp_close_does_not_pause_the_app_workers_jobs(self):
        from paperdesk.cli import _application
        stamp = utcnow()
        payload = {'provider_id':'demo','model':'','language':'Korean'}
        self.app.jobs.repository.add({'id':'other-process','doc_id':self.doc.id,'fingerprint':'other-process',
                                     'payload':payload,'state':'running','total':1,'created_at':stamp,'updated_at':stamp})
        with mock.patch.dict(os.environ, {'PAPERDESK_HOME':str(self.paths.root)}):
            with _application():
                pass
        self.assertEqual(self.app.jobs.repository.get('other-process')['state'], 'running')

    def test_resume_requeries_after_invalid_response_and_keeps_successful_blocks(self):
        from .test_reader_services import scripted_app, ScriptedProvider
        # The first request and both automatic retries come back empty; only the explicit resume recovers.
        app, temporary = scripted_app('{"blocks":[]}', '{"blocks":[]}', '{"blocks":[]}', '{"blocks":[{"id":"0","sentences":["Recovered."]}]}')
        self.addCleanup(temporary.cleanup)
        self.addCleanup(app.jobs.close)
        doc, _ = app.library.import_pdf('retry.pdf', make_pdf(['A sentence.']))
        job = app.jobs.create(doc.id, {'blocks':[{'key':'1:abcd','sentences':['A sentence.']}]})
        wait_for(lambda:app.jobs.repository.get(job['id'])['state']=='failed' and not app.jobs.list(doc.id)[0]['request_in_flight'])
        # A previous version may already have persisted the invalid raw response.
        key = app.assistant._key(app.settings.active_provider(), ScriptedProvider.prompts[0])
        app.assistant._cache.put(key, '{"blocks":[]}')
        app.jobs.action(job['id'], 'resume')
        wait_for(lambda:app.jobs.repository.get(job['id'])['state']=='completed')
        self.assertEqual(len(ScriptedProvider.prompts), 4)
        self.assertEqual(app.translations.list(doc.id)['blocks']['1:abcd']['text'], 'Recovered.')
        app.translations.translate(doc.id, app.translations.parse_blocks([{'key':'1:abcd','sentences':['A sentence.']}]))
        self.assertEqual(len(ScriptedProvider.prompts), 4)

    def test_model_is_resolved_at_enqueue_and_used_after_server_changes(self):
        from .test_providers import FakeHttp
        from paperdesk.providers.openai_compatible import OllamaProvider
        from paperdesk.providers.registry import ProviderRegistry
        http = FakeHttp(get={'data':[{'id':'model-a'}]}, post={'choices':[{'message':{'content':'{"blocks":[{"id":"0","sentences":["Translated."]}]}'}}]})
        app, temporary = build_app(registry=ProviderRegistry([OllamaProvider]), http=http)
        self.addCleanup(temporary.cleanup)
        self.addCleanup(app.jobs.close)
        app.settings.update_general(provider='ollama')
        doc, _ = app.library.import_pdf('model.pdf', make_pdf(['A sentence.']))
        with mock.patch.object(app.jobs, 'start'), mock.patch.object(app.settings, 'load', wraps=app.settings.load) as load:
            job = app.jobs.create(doc.id, {'blocks':[{'key':'1:abcd','sentences':['A sentence.']}]})
            self.assertEqual(load.call_count, 1)
        payload = app.jobs.repository.get(job['id'])['payload']
        self.assertEqual(payload['model'], 'model-a')
        self.assertEqual(payload['options']['model'], 'model-a')
        http.get = {'data':[{'id':'model-b'}]}
        app.jobs.start()
        # Starting a new worker pauses persisted jobs, requiring explicit resume.
        app.jobs.action(job['id'], 'resume')
        wait_for(lambda:app.jobs.repository.get(job['id'])['state']=='completed')
        self.assertEqual([call[3]['model'] for call in http.calls if call[0]=='POST'], ['model-a'])
        self.assertEqual(app.translations.list(doc.id)['blocks']['1:abcd']['model'], 'model-a')
