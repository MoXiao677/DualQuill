import http.client,json,sys,tempfile,threading,time,unittest
from pathlib import Path
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from novel_writer.ui.server import create_server
from novel_writer.domain.tasks import digest
FROZEN=json.loads((ROOT/'tests/fixtures/s4a_legacy.json').read_text(encoding='utf8'))

class TaskHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='novel-s4a-http-');self.addCleanup(self.temp.cleanup)
        self.db=Path(self.temp.name)/'fictional.sqlite3';self.db.write_bytes(bytes.fromhex(FROZEN['v2']['database_hex']))
        self.server=create_server(self.db,port=0,offline=True)
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start();self.addCleanup(self.stop)
    def stop(self):self.server.shutdown();self.thread.join(3);self.server.server_close()
    def request(self,method,path,data=None,token=True):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_address[1],timeout=20);headers={'Content-Type':'application/json'}
        if token:headers['X-Novel-Token']=self.server.token
        try:c.request(method,path,json.dumps(data) if data is not None else None,headers);r=c.getresponse();return r.status,json.loads(r.read())
        finally:c.close()
    def test_normal_product_prepares_saved_task_but_cannot_execute_model_or_fixture(self):
        code,caps=self.request('GET','/api/tasks/capabilities');self.assertEqual(code,200);self.assertFalse(caps['local_protocol_demo']);self.assertFalse(caps['real_model_enabled'])
        options={'chapter_id':'p1-c5','budget_chars':1000};code,preview=self.request('POST','/api/projects/p1/context-preview',options);self.assertEqual(code,200)
        revision=self.server.service.get('p1')['revision'];payload=dict(request_id=str(uuid4()),chapter_id='p1-c5',task_type='rewrite_chapter',context_options=options,context_sha256=digest(preview['context_text']),parameters=dict(instruction='测试',max_output_chars=10000,timeout_ms=3000),expected_revision=revision)
        code,prepared=self.request('POST','/api/projects/p1/tasks/prepare',payload);self.assertEqual(code,201,prepared);task=prepared['task']['id']
        before=self.db.read_bytes();self.assertEqual(self.request('POST',f'/api/projects/p1/tasks/{task}/execute',{})[0],422);self.assertEqual(self.db.read_bytes(),before)
        self.assertEqual(self.request('GET',f'/api/projects/p1/tasks/{task}')[1]['task']['status'],'pending')
    def test_protected_task_routes_reject_unknown_or_crossbook_parameters(self):
        self.assertEqual(self.request('POST','/api/projects/p1/tasks/prepare',{},token=False)[0],403)
        code,result=self.request('POST','/api/projects/p1/tasks/prepare',dict(fixture_output='fake'));self.assertEqual(code,422,result)
        self.assertEqual(self.request('POST','/api/projects/p1/tasks/not-owned/execute',{})[0],422)

if __name__=='__main__':unittest.main()
