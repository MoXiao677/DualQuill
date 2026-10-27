"""Real isolated desktop bootstrap; no formal data, credentials or external requests."""
import http.client
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import unittest
from uuid import uuid4
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

class DesktopBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='novel-s7-bootstrap-')
        self.profile = Path(self.temp.name) / 'profile'
        self.token, self.nonce = secrets.token_hex(32), secrets.token_hex(32)
        env = dict(os.environ, PYTHONPATH=str(ROOT/'src'), NOVEL_WRITER_PROVIDER_CONFIG=str(self.profile/'providers.dpapi'))
        bootstrap="import runpy,sys;sys.path.insert(0,"+repr(str(ROOT/'src'))+");runpy.run_module('novel_writer.ui.desktop',run_name='__main__')"
        self.child = subprocess.Popen([sys.executable,'-B','-X','utf8','-u','-c',bootstrap,
            '--profile',str(self.profile)],cwd=ROOT,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.child.stdin.write(json.dumps(dict(token=self.token,nonce=self.nonce))+'\n'); self.child.stdin.flush()
        lines=[]
        reader=threading.Thread(target=lambda:lines.append(self.child.stdout.readline()),daemon=True);reader.start();reader.join(12)
        self.assertTrue(lines and lines[0].startswith('{'), 'desktop bootstrap must send a bounded trusted ready handshake')
        self.ready=json.loads(lines[0]);self.assertEqual(self.ready['nonce'],self.nonce);self.assertEqual(self.ready['pid'],self.child.pid)
        self.assertNotIn(self.token,lines[0]);self.assertEqual(self.ready['type'],'ready')
    def tearDown(self):
        if getattr(self,'child',None):
            if not self.child.stdin.closed:self.child.stdin.close()
            try:self.child.wait(timeout=8)
            except subprocess.TimeoutExpired:self.child.kill();self.child.wait(timeout=5)
            self.child.stdout.close();self.child.stderr.close()
        self.temp.cleanup()
    def request(self,method,path,payload=None,*,token=True,origin=None,host=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.ready['port'],timeout=8)
        headers={'Content-Type':'application/json'}
        if token:headers['X-Novel-Token']=self.token
        if origin:headers['Origin']=origin
        if host:headers['Host']=host
        body=json.dumps(payload) if payload is not None else None
        try:
            connection.request(method,path,body=body,headers=headers);response=connection.getresponse()
            return response.status,json.loads(response.read())
        finally:connection.close()
    def test_all_desktop_reads_require_private_token_and_keep_origin_host_guards(self):
        for path in ['/api/session','/api/projects','/api/settings','/app.js']:
            self.assertEqual(self.request('GET',path,token=False)[0],403)
        self.assertEqual(self.request('GET','/api/projects'),(200,[]))
        self.assertEqual(self.request('GET','/api/projects',origin='novel://app')[0],403)
        self.assertEqual(self.request('GET','/api/projects',host='evil.test')[0],403)
        self.assertEqual(self.request('GET','/api/session')[0],404)
    def test_configured_desktop_default_and_explicit_session_disable_enable(self):
        self.assertTrue(self.request('GET','/api/tasks/capabilities')[1]['real_model_enabled'])
        self.assertEqual(self.request('POST','/api/desktop/mode',dict(mode='manual',confirmed=True))[0],200)
        self.assertFalse(self.request('GET','/api/tasks/capabilities')[1]['real_model_enabled'])
        self.assertEqual(self.request('POST','/api/desktop/mode',dict(mode='models',confirmed=False))[0],422)
        self.assertEqual(self.request('POST','/api/desktop/mode',dict(mode='models',confirmed=True,command='x'))[0],422)
        self.assertEqual(self.request('POST','/api/desktop/mode',dict(mode='models',confirmed=True))[0],200)
        self.assertTrue(self.request('GET','/api/tasks/capabilities')[1]['real_model_enabled'])
        self.assertEqual(self.request('POST','/api/desktop/mode',dict(mode='manual',confirmed=True))[0],200)
        self.assertFalse(self.request('GET','/api/tasks/capabilities')[1]['real_model_enabled'])
        self.assertFalse((self.profile/'providers.dpapi').exists())
    def test_stdin_parent_lifeline_stops_only_owned_backend(self):
        port=self.ready['port'];self.child.stdin.close();self.assertEqual(self.child.wait(timeout=8),0)
        connection=http.client.HTTPConnection('127.0.0.1',port,timeout=.5)
        with self.assertRaises(OSError):connection.request('GET','/api/projects')
        connection.close()
    def test_manual_configuration_saves_without_enabling_requests_or_loading_keys_on_status(self):
        self.assertEqual(self.request('POST','/api/desktop/mode',dict(mode='manual',confirmed=True))[0],200)
        identifier=str(uuid4())
        payload=dict(id=identifier,name='作者配置 保存/取消',base_url='http://127.0.0.1:19991/v1',protocol='openai-chat',model_id='fiction-manual-model',api_key='fiction-manual-secret',allow_local=True)
        status,result=self.request('POST','/api/providers/custom',payload)
        self.assertEqual(status,201,result)
        settings=self.request('GET','/api/settings')[1]
        self.assertTrue(settings['offline_mode']);self.assertTrue(settings['configuration_writes_enabled'])
        self.assertEqual(settings['connections'][identifier]['name'],payload['name'])
        self.assertNotIn(payload['api_key'],json.dumps(settings))
        self.assertNotIn(payload['api_key'],(self.profile/'providers.metadata.json').read_text(encoding='utf-8'))
        self.assertNotIn(payload['api_key'].encode(),(self.profile/'providers.dpapi').read_bytes())
        self.assertFalse(self.request('GET','/api/tasks/capabilities')[1]['real_model_enabled'])
        self.assertEqual(self.request('POST','/api/providers/test',dict(id=identifier))[0],422)
        from novel_writer.application.provider_connections import ProviderConnections
        reopened=ProviderConnections(self.profile/'providers.dpapi',offline=True,allow_manual_configuration=True)
        with patch('novel_writer.application.provider_connections._crypt',side_effect=AssertionError('status must not decrypt credentials')):
            self.assertEqual(reopened.status()[identifier]['model_id'],payload['model_id'])

if __name__=='__main__':unittest.main()
