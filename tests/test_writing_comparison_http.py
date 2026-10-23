"""Actual HTTP boundary, privacy, token and exact-range adoption tests."""
import http.client,json,threading,unittest
from uuid import uuid4
from novel_writer.ui.server import create_server
from test_scene_expansion import SceneExpansionTests as Fixture
from test_book_ai import supplier

class WritingComparisonHTTPTests(unittest.TestCase):
    def setUp(self):
        self.f=Fixture();self.f.setUp();self.addCleanup(self.f.doCleanups);f=self.f
        self.server=create_server(f.db,port=0,provider_path=f.providers.path,enable_model_generation=True,drafts_path=f.root/'drafts')
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start();self.addCleanup(self.stop)
        self.base='/api/projects/'+f.pid;f.engine=self.server.scene_expansion;f.shared=self.server.task_coordinator
    def stop(self):self.server.shutdown();self.thread.join(3);self.server.server_close()
    def request(self,method,path,payload=None,token=True):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=20);headers={'Content-Type':'application/json'}
        if token:headers['X-Novel-Token']=self.server.token
        try:
            c.request(method,path,None if payload is None else json.dumps(payload,ensure_ascii=False).encode(),headers);r=c.getresponse();return r.status,json.loads(r.read())
        finally:c.close()
    def prepare(self,connection,count=3):
        f=self.f;source=f.source('selection',scene_order=None,selection_start=f.original.index('门外'),selection_end=f.original.index('门外')+len('门外有雾。'))
        tasks=[]
        for _ in range(count):
            code,preview=self.request('POST',self.base+'/scene-expansion/preview',source);self.assertEqual(code,200,preview)
            code,value=self.request('POST',self.base+'/scene-expansion/prepare',dict(operation_id=str(uuid4()),source_options=source,source_sha256=preview['source_sha256'],model_options=f.options(connection),max_output_chars=8000,timeout_ms=3000));self.assertEqual(code,201,value);tasks.append(value['task'])
        request=dict(experiment_id=str(uuid4()),title='HTTP虚构多候选',task_kind='scene_expansion',task_ids=[v['id'] for v in tasks],expected_revision=self.server.service.get(f.pid)['revision'])
        self.assertEqual(self.request('POST',self.base+'/comparisons',request,token=False)[0],403)
        code,value=self.request('POST',self.base+'/comparisons',request);self.assertEqual(code,201,value);return value['experiment_id'],tasks
    def test_http_confirm_privacy_all_scores_choose_correct_review_accept(self):
        f=self.f
        with supplier(output='门外仍是虚构潮声。') as wire:
            identifier,tasks=self.prepare(f.connection(wire));path=self.base+'/comparisons/'+identifier;before=self.server.service.get(f.pid)['document']
            code,setup=self.request('GET',path+'/setup');self.assertEqual(code,200,setup);self.assertNotIn('"side"',json.dumps(setup));self.assertNotIn('"task_id"',json.dumps(setup))
            for task in tasks:
                self.assertIn(self.request('GET',self.base+'/scene-expansion/'+task['id'])[0],(404,422))
                self.assertEqual(self.request('POST',self.base+'/scene-expansion/'+task['id']+'/execute',dict(confirm_external=True,request_sha256=task['binding']['request_sha256']))[0],422)
            self.assertEqual(self.request('GET',self.base+'/scene-expansion')[1]['tasks'],[])
            for c in setup['configurations']:
                code,value=self.request('POST',path+'/execute',dict(configuration_id=c['configuration_id'],confirm_external=True,request_sha256=c['request_sha256']));self.assertEqual(code,202,value);f.shared.wait_idle(6)
            blind=self.request('GET',path)[1];self.assertTrue(blind['ready']);self.assertNotIn('identities',blind)
            for c in blind['candidates']:
                code,value=self.request('POST',path+'/score',dict(operation_id=str(uuid4()),side=c['side'],rating=3,outcome='scored',notes='HTTP虚构比较',expected_revision=self.server.service.get(f.pid)['revision']));self.assertEqual(code,200,value)
            code,revealed=self.request('POST',path+'/reveal',dict(operation_id=str(uuid4()),expected_revision=self.server.service.get(f.pid)['revision']));self.assertEqual(code,200,revealed)
            code,choice=self.request('POST',path+'/choose',dict(operation_id=str(uuid4()),side='C',action='open_candidate',name='',expected_revision=self.server.service.get(f.pid)['revision']));self.assertEqual(code,200,choice);self.assertEqual(self.server.service.get(f.pid)['document'],before)
            detail=self.request('GET',self.base+'/scene-expansion/'+choice['task_id'])[1];candidate=detail['latest_candidate']
            code,corrected=self.request('POST',self.base+'/scene-expansion/correct',dict(operation_id=str(uuid4()),task_id=choice['task_id'],candidate_id=candidate['id'],text='门外是作者修正后的潮声。'));self.assertEqual(code,201,corrected);candidate=corrected['latest_candidate']
            code,review=self.request('POST',self.base+'/scene-expansion/review',dict(operation_id=str(uuid4()),task_id=choice['task_id'],candidate_id=candidate['id'],candidate_sha256=candidate['data_sha256']));self.assertEqual(code,201,review);self.assertEqual(review['selected_before'],'门外有雾。')
            request=dict(operation_id=str(uuid4()),task_id=choice['task_id'],candidate_id=candidate['id'],candidate_sha256=candidate['data_sha256'],review_id=review['id'],review_sha256=review['review_sha256'],expected_revision=self.server.service.get(f.pid)['revision'],confirm_chapter=True,authorize_confirmed=False)
            code,receipt=self.request('POST',self.base+'/scene-expansion/accept',request);self.assertEqual(code,200,receipt);start=f.original.index('门外');end=start+len('门外有雾。');self.assertEqual(self.server.service.get(f.pid)['document']['chapters'][0]['content'],f.original[:start]+candidate['text']+f.original[end:]);self.assertEqual(len(wire['calls']),3)
            code,again=self.request('POST',self.base+'/scene-expansion/accept',request);self.assertEqual(code,200,again);self.assertEqual(again,receipt)
    def test_invalid_group_cross_book_and_exact_hash_refuse_without_wire(self):
        f=self.f
        with supplier(output='不会发送') as wire:
            identifier,tasks=self.prepare(f.connection(wire),2);path=self.base+'/comparisons/'+identifier;setup=self.request('GET',path+'/setup')[1];c=setup['configurations'][0]
            code,_=self.request('POST',path+'/execute',dict(configuration_id=c['configuration_id'],confirm_external=True,request_sha256='0'*64));self.assertEqual(code,422);self.assertEqual(wire['calls'],[])
            other=self.server.service.create(title='另一本虚构书')['document']['project']['id']
            self.assertIn(self.request('GET','/api/projects/'+other+'/comparisons/'+identifier)[0],(404,422))
            self.assertEqual(wire['calls'],[])

if __name__=='__main__':unittest.main()
