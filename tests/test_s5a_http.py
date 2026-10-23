import http.client,json,sys,tempfile,threading,time,unittest
from pathlib import Path
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
from novel_writer.ui.server import create_server
from novel_writer.domain.tasks import digest
from test_s5a_rules import FROZEN,request_rules

class ReviewHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='novel-s5a-http-');self.addCleanup(self.temp.cleanup)
        self.db=Path(self.temp.name)/'fictional.sqlite3';self.db.write_bytes(bytes.fromhex(FROZEN['v3']['database_hex']))
        self.server=create_server(self.db,port=0,offline=True);self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start();self.addCleanup(self.stop)
    def stop(self):self.server.shutdown();self.thread.join(3);self.server.server_close()
    def request(self,method,path,payload=None,token=True):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_address[1],timeout=30);headers={'Content-Type':'application/json'}
        if token:headers['X-Novel-Token']=self.server.token
        try:c.request(method,path,json.dumps(payload) if payload is not None else None,headers);r=c.getresponse();return r.status,json.loads(r.read())
        finally:c.close()
    def test_default_product_can_run_real_offline_audit_without_rewrite_fixture_mode(self):
        code,caps=self.request('GET','/api/tasks/capabilities');self.assertEqual(code,200);self.assertTrue(caps['offline_audit_enabled']);self.assertFalse(caps['local_protocol_demo'])
        options=dict(chapter_id='p1-c5',budget_chars=4000);preview=self.server.service.preview_context('p1',options);state=self.server.service.get('p1')
        request=dict(request_id=str(uuid4()),chapter_id='p1-c5',task_type='audit_chapter',context_options=options,context_sha256=digest(preview['context_text']),parameters=request_rules(),expected_revision=state['revision'])
        code,prepared=self.request('POST','/api/projects/p1/tasks/prepare',request);self.assertEqual(code,201,prepared);identifier=prepared['task']['id']
        code,_=self.request('POST',f'/api/projects/p1/tasks/{identifier}/execute',{});self.assertEqual(code,202);self.server.task_coordinator.wait_idle(5)
        code,listing=self.request('GET','/api/projects/p1/reviews');self.assertEqual(code,200,listing);self.assertEqual(len(listing['reports']),1)
        report=listing['reports'][0];code,view=self.request('GET','/api/projects/p1/reviews/'+report['id']);self.assertEqual(code,200,view);self.assertTrue(view['proposals'])
        proposal=view['proposals'][0];receipt=dict(decision_id=str(uuid4()),proposal_id=proposal['id'],decision='accepted',expected_revision=view['revision'],confirmed=True,preserve_conflicts=True)
        code,saved=self.request('POST',f"/api/projects/p1/reviews/{report['id']}/proposal",receipt);self.assertEqual(code,200,saved);self.assertIsNotNone(saved['memory_id'])
    def test_review_routes_protect_token_unknown_and_crossbook_scope(self):
        self.assertEqual(self.request('POST','/api/projects/p1/reviews/unknown/proposal',{},token=False)[0],403)
        before=self.db.read_bytes();self.assertEqual(self.request('POST','/api/projects/p1/reviews/unknown/proposal',dict(fixture_output='fake'))[0],422);self.assertEqual(self.db.read_bytes(),before)

if __name__=='__main__':unittest.main()
