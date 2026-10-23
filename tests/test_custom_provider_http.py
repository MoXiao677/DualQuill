from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
import unittest
from uuid import uuid4
from novel_writer.ui.server import create_server

class CustomProviderHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='novel-custom-http-');self.addCleanup(self.temp.cleanup);root=Path(self.temp.name)
        self.server=create_server(root/'fiction.sqlite3',port=0,provider_path=root/'fiction.dpapi')
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start();self.addCleanup(self.stop)
    def stop(self):self.server.shutdown();self.server.server_close();self.thread.join(2)
    def request(self,method,path,payload=None,token=True):
        client=HTTPConnection('127.0.0.1',self.server.server_port,timeout=5);headers={'Content-Type':'application/json'}
        if token:headers['X-Novel-Token']=self.server.token
        try:client.request(method,path,json.dumps(payload) if payload is not None else None,headers);response=client.getresponse();return response.status,json.loads(response.read())
        finally:client.close()
    def test_custom_configuration_has_strict_http_entry_and_secret_free_status(self):
        fields=dict(id=str(uuid4()),name='虚构HTTP配置',base_url='https://provider.example/v1',protocol='openai-chat',model_id='fiction-model',api_key='fiction-http-key',allow_local=False)
        code,saved=self.request('POST','/api/providers/custom',fields);self.assertEqual(code,201,saved)
        self.assertTrue(saved['custom']);self.assertNotIn(fields['api_key'],json.dumps(saved));status=self.request('GET','/api/settings')[1];self.assertIn(fields['id'],status['connections']);self.assertNotIn(fields['api_key'],json.dumps(status))
        self.assertEqual(self.request('POST','/api/providers/custom',dict(fields,unknown='x'))[0],422)
        self.assertEqual(self.request('POST','/api/providers/custom',fields,token=False)[0],403)
    def test_configured_adapter_is_explicitly_registered_but_default_generation_is_disabled(self):
        code,caps=self.request('GET','/api/tasks/capabilities');self.assertEqual(code,200);self.assertFalse(caps['real_model_enabled'])
        self.assertTrue(any(adapter['adapter_id']=='configured-http-v2' for adapter in caps['model_adapters']))

if __name__=='__main__':unittest.main()
