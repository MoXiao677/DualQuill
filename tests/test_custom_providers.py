"""Public protocol support is exercised only against fictional loopback providers."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from importlib import import_module,util
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from uuid import uuid4
from unittest.mock import patch

from novel_writer.application.provider_connections import ProviderConnections,PROVIDERS
from novel_writer.application.task_protocol import CancellationToken

@contextmanager
def wire(protocol,*,status=200,location=None):
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append(dict(path=self.path,body=body,headers=dict(self.headers)))
            if protocol=='openai-chat':payload=dict(id='fiction-chat',model='fiction-model',choices=[dict(message=dict(role='assistant',content='虚构协议候选'),finish_reason='stop')],usage=dict(prompt_tokens=11,completion_tokens=7,total_tokens=18))
            elif protocol=='anthropic-messages':payload=dict(id='fiction-native',type='message',role='assistant',model='fiction-model',content=[dict(type='text',text='虚构协议候选')],stop_reason='end_turn',usage=dict(input_tokens=11,output_tokens=7))
            else:payload=dict(responseId='fiction-google',candidates=[dict(content=dict(role='model',parts=[dict(text='虚构协议候选')]),finishReason='STOP')],usageMetadata=dict(promptTokenCount=11,candidatesTokenCount=7,totalTokenCount=18))
            data=json.dumps(payload,ensure_ascii=False).encode('utf-8');self.send_response(status)
            if location:self.send_header('Location',location)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    try:yield 'http://127.0.0.1:'+str(server.server_port)+'/v1',calls
    finally:server.shutdown();server.server_close();worker.join(2)

class CustomProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='novel-custom-provider-');self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'fiction.dpapi';self.providers=ProviderConnections(self.path)
    def save(self,endpoint='https://provider.example/v1',protocol='openai-chat',identifier=None,**changes):
        self.assertTrue(callable(getattr(self.providers,'save_custom',None)),'custom provider configuration is missing')
        request=dict(id=identifier or str(uuid4()),name='虚构自建供应商',base_url=endpoint,protocol=protocol,model_id='fiction-model',api_key='fictional-test-key',allow_local=False)
        request.update(changes);return self.providers.save_custom(**request)
    def test_custom_identity_does_not_overwrite_old_connections_or_expose_secret(self):
        self.providers.save(id='gg',base_url=PROVIDERS['gg']['base_url'],model_id='legacy-model',api_key='legacy-fiction-key')
        old=self.providers.generation_connection('gg','legacy-model',enabled=True,confirmed=True)
        added=self.save();self.assertNotIn(added['id'],PROVIDERS);self.assertEqual(added['protocol'],'openai-chat')
        self.assertEqual(self.providers.generation_connection('gg','legacy-model',enabled=True,confirmed=True),old)
        self.assertNotIn('fictional-test-key',json.dumps(self.providers.status()))
        self.assertNotIn(b'fictional-test-key',self.path.read_bytes())
        offline=ProviderConnections(self.path,offline=True)
        with self.assertRaises(ValueError):offline.save_custom(id=str(uuid4()),name='offline',base_url='https://provider.example/v1',protocol='openai-chat',model_id='x',api_key='x',allow_local=False)
    def test_protocol_url_and_local_scope_are_explicit_and_saving_makes_no_request(self):
        for endpoint in ['file:///tmp/secret','http://public.example/v1','https://u:p@public.example/v1','https://public.example/v1?key=secret','https://public.example/v1#fragment','http://127.0.0.1:9/v1','https://169.254.169.254/v1','https://10.0.0.1/v1']:
            with self.subTest(endpoint=endpoint),self.assertRaises(ValueError):self.save(endpoint)
        with self.assertRaises(ValueError):self.save(protocol='unknown-protocol')
        with wire('openai-chat') as (endpoint,calls):
            self.save(endpoint,allow_local=True);self.assertEqual(calls,[])
    def test_changed_destination_or_config_revision_cannot_reuse_frozen_permission(self):
        with wire('openai-chat') as (first,old_calls),wire('openai-chat') as (second,new_calls):
            configured=self.save(first,allow_local=True);snapshot=self.providers.destination(configured['id'],'fiction-model')
            self.assertNotIn('fictional-test-key',json.dumps(snapshot))
            self.save(second,identifier=configured['id'],allow_local=True)
            with self.assertRaises(ValueError):self.providers.generation_connection(configured['id'],'fiction-model',enabled=True,confirmed=True,destination=snapshot)
            self.assertEqual(old_calls,[]);self.assertEqual(new_calls,[])
    def test_three_actual_wire_protocols_use_declared_paths_headers_and_usage(self):
        self.assertIsNotNone(util.find_spec('novel_writer.application.custom_protocols'),'native protocol transport is missing')
        api=import_module('novel_writer.application.custom_protocols')
        messages=[dict(role='system',content='只生成虚构文本'),dict(role='user',content='作者自己的设定')]
        for protocol in ['openai-chat','anthropic-messages','gemini-content']:
            with self.subTest(protocol=protocol),wire(protocol) as (endpoint,calls):
                configured=self.save(endpoint,protocol,allow_local=True);destination=self.providers.destination(configured['id'],'fiction-model')
                saved=self.providers.generation_connection(configured['id'],'fiction-model',enabled=True,confirmed=True,destination=destination)
                body=api.request_payload(protocol,messages,dict(model_id='fiction-model',temperature=.3,max_tokens=512))
                binding=SimpleNamespace(request_body=json.dumps(body,ensure_ascii=False))
                response=api.ConfiguredHttpTransport().send(binding,saved,CancellationToken(threading.Event(),time.monotonic()+3),1000)
                self.assertTrue(response.complete,response.error_code);self.assertEqual(response.output_text,'虚构协议候选');self.assertEqual(response.usage.total_tokens,18);self.assertEqual(len(calls),1)
                request=calls[0];self.assertNotIn('fictional-test-key',request['path'])
                if protocol=='openai-chat':self.assertEqual(request['path'],'/v1/chat/completions');self.assertEqual(request['body']['messages'],messages);self.assertEqual(request['headers'].get('Authorization'),'Bearer fictional-test-key')
                elif protocol=='anthropic-messages':self.assertEqual(request['path'],'/v1/messages');self.assertEqual(request['body']['system'],'只生成虚构文本');self.assertEqual(request['headers'].get('x-api-key'),'fictional-test-key');self.assertEqual(request['headers'].get('anthropic-version'),'2023-06-01')
                else:self.assertEqual(request['path'],'/v1/models/fiction-model:generateContent');self.assertEqual(request['body']['systemInstruction']['parts'][0]['text'],'只生成虚构文本');self.assertEqual(request['headers'].get('x-goog-api-key'),'fictional-test-key')
    def test_redirect_never_forwards_text_or_key_to_another_endpoint(self):
        api=import_module('novel_writer.application.custom_protocols')
        with wire('openai-chat') as (second,new_calls),wire('openai-chat',status=302,location=second+'/chat/completions') as (first,old_calls):
            configured=self.save(first,allow_local=True);saved=self.providers.generation_connection(configured['id'],'fiction-model',enabled=True,confirmed=True,destination=self.providers.destination(configured['id'],'fiction-model'))
            response=api.ConfiguredHttpTransport().send(SimpleNamespace(request_body='{}'),saved,CancellationToken(threading.Event(),time.monotonic()+2),1000)
            self.assertFalse(response.complete);self.assertEqual(len(old_calls),1);self.assertEqual(new_calls,[])
    def test_public_dns_resolving_private_is_rejected_before_connect(self):
        api=import_module('novel_writer.application.custom_protocols');configured=self.save()
        saved=self.providers.generation_connection(configured['id'],'fiction-model',enabled=True,confirmed=True,destination=self.providers.destination(configured['id'],'fiction-model'))
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]),patch('socket.create_connection') as connect,patch('socket.socket') as create_socket:
            response=api.ConfiguredHttpTransport().send(SimpleNamespace(request_body='{}'),saved,CancellationToken(threading.Event(),time.monotonic()+2),1000)
            self.assertFalse(response.complete);connect.assert_not_called();create_socket.assert_not_called()
    def test_explicit_local_model_can_omit_key_without_triggering_empty_secret_redaction(self):
        api=import_module('novel_writer.application.custom_protocols')
        with wire('openai-chat') as (endpoint,calls):
            configured=self.save(endpoint,allow_local=True,api_key='');saved=self.providers.generation_connection(configured['id'],'fiction-model',enabled=True,confirmed=True,destination=self.providers.destination(configured['id'],'fiction-model'))
            response=api.ConfiguredHttpTransport().send(SimpleNamespace(request_body='{}'),saved,CancellationToken(threading.Event(),time.monotonic()+2),1000)
            self.assertTrue(response.complete,response.error_code);self.assertNotIn('Authorization',calls[0]['headers'])
    def test_native_unknown_usage_remains_unknown_and_malformed_candidate_is_rejected(self):
        api=import_module('novel_writer.application.custom_protocols')
        with self.subTest(case='unknown usage'):
            value=api.normalized(dict(role='assistant',content=[dict(type='text',text='虚构')],stop_reason='end_turn',usage=None),'anthropic-messages');self.assertIsNone(value['usage']['total_tokens'])
        with self.subTest(case='malformed candidate'),self.assertRaises(ValueError):api.normalized(dict(candidates=[dict(content=None,finishReason='STOP')]),'gemini-content')

if __name__=='__main__':unittest.main()
