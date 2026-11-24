import json
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from paperdesk.domain.errors import ProviderFailed
from paperdesk.domain.models import Completion, ProviderStatus
from paperdesk.ports.ai import AIProvider, OptionField
from paperdesk.providers.registry import ProviderRegistry
from paperdesk.web.server import create_server
from .helpers import build_app


class QuestionModelProvider(AIProvider):
    id = 'question-model-test'
    label = 'Local model fixture'
    kind = 'offline'
    options = (OptionField('model','Model',default='small'),)
    calls = []

    def status(self):
        return ProviderStatus(True,models=('small','large'))

    def complete(self,prompt):
        self.calls.append(self.model)
        return Completion('Selected model: '+self.model,self.id,self.model)


class QuestionModelTests(unittest.TestCase):
    def setUp(self):
        QuestionModelProvider.calls=[]
        self.app,self.tmp=build_app(registry=ProviderRegistry([QuestionModelProvider]))
        self.app.settings.update_general(provider=QuestionModelProvider.id)
        self.server=create_server(self.app,'127.0.0.1',0)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def call(self,path,body=None):
        request=urllib.request.Request(self.server.url+path,method='POST' if body is not None else 'GET',
            data=json.dumps(body).encode() if body is not None else None,
            headers={'X-Paperdesk':'1','Content-Type':'application/json'})
        with urllib.request.urlopen(request) as response:return json.load(response)

    def test_question_model_is_scoped_to_request_and_has_its_own_cache(self):
        payload={'task':'ask','text':'A paper about models.','question':'Why?'}
        large=self.call('api/assist',{**payload,'model':'large'})
        small=self.call('api/assist',payload)
        cached=self.call('api/assist',{**payload,'model':'large'})
        self.assertEqual((large['model'],small['model']),('large','small'))
        self.assertTrue(cached['cached'])
        self.assertEqual(QuestionModelProvider.calls,['large','small'])
        self.assertEqual(self.app.settings.active_provider().model,'small')
        self.assertEqual(self.app.settings.load().options_for(QuestionModelProvider.id),{})

    def test_chat_flushes_first_delta_before_provider_can_finish(self):
        release = threading.Event()
        def stream(provider, prompt, on_delta):
            on_delta('첫 ')
            if not release.wait(5):
                self.fail('client did not receive first delta during generation')
            on_delta('답변')
            return Completion('첫 답변', provider.id, provider.model)

        payload = {'task': 'ask', 'text': 'Streaming paper', 'question': 'Why?', 'model': 'large'}
        request = urllib.request.Request(self.server.url + 'api/assist', data=json.dumps(payload).encode(),
            headers={'X-Paperdesk': '1', 'Accept': 'application/x-ndjson', 'Content-Type': 'application/json'})
        with patch.object(QuestionModelProvider, 'complete_stream', stream):
            try:
                with urllib.request.urlopen(request, timeout=6) as response:
                    self.assertEqual(response.headers.get_content_type(), 'application/x-ndjson')
                    self.assertEqual(response.headers['Transfer-Encoding'], 'chunked')
                    self.assertEqual(json.loads(response.readline()), {'delta': '첫 '})
                    release.set()
                    self.assertEqual(json.loads(response.readline()), {'delta': '답변'})
                    answer = json.loads(response.readline())['result']
                    self.assertEqual((answer['text'], answer['model']), ('첫 답변', 'large'))
            finally:
                release.set()
        self.assertTrue(self.call('api/assist', payload)['cached'])

    def test_interrupted_stream_never_enters_the_completion_cache(self):
        def interrupted(provider, prompt, on_delta):
            on_delta('partial')
            raise ProviderFailed('Interrupted')

        payload = {'task': 'ask', 'text': 'Separate paper', 'question': 'Why?'}
        request = urllib.request.Request(self.server.url + 'api/assist', data=json.dumps(payload).encode(),
            headers={'X-Paperdesk': '1', 'Accept': 'application/x-ndjson'})
        with patch.object(QuestionModelProvider, 'complete_stream', interrupted):
            with urllib.request.urlopen(request, timeout=5) as response:
                events = [json.loads(line) for line in response]
        self.assertEqual(events[0], {'delta': 'partial'})
        self.assertEqual(events[1]['error']['code'], 'provider_failed')
        self.assertIsNone(self.call('api/assist', {**payload, 'cache_only': True}))

    def test_model_catalog_and_invalid_override(self):
        models=self.call('api/providers/'+QuestionModelProvider.id+'/models')
        self.assertEqual(models['models'],['small','large'])
        for value in (42,{},'x'*201):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.call('api/assist',{'task':'ask','text':'A paper.','question':'Why?','model':value})
            self.assertEqual(error.exception.code,400)
            error.exception.close()
        self.assertEqual(QuestionModelProvider.calls,[])
