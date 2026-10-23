from pathlib import Path
import sys,json,http.client,threading,unittest
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
import test_s6b_workflows as base
from novel_writer.ui.server import create_server

class WorkflowHTTPTests(unittest.TestCase):
    def setUp(self):
        self.unit=base.WorkflowTests('test_real_model_waits_single_confirmation_and_body_waits_bound_human_then_atomic_once');self.unit.setUp();self.addCleanup(self.unit.doCleanups);f=self.unit.f;self.server=create_server(f.db,port=0,provider_path=f.path,enable_model_generation=True,model_adapter=f.adapter);self.addCleanup(self.server.server_close);self.assertIsNotNone(getattr(self.server,'workflows',None),'产品服务器没有工作流入口');self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start();self.addCleanup(self.stop);self.url='/api/projects/'+self.unit.pid+'/workflows'
    def stop(self):self.server.shutdown();self.thread.join(3)
    def request(self,method,path,body=None,token=True):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_address[1],timeout=20);headers={'Content-Type':'application/json'}
        if token:headers['X-Novel-Token']=self.server.token
        try:c.request(method,path,None if body is None else json.dumps(body),headers);r=c.getresponse();return r.status,json.loads(r.read())
        finally:c.close()
    def create(self):
        u=self.unit;s=u.service.get(u.pid);code,version=self.request('POST',self.url+'/templates',dict(operation_id=str(uuid4()),template_id=None,template=base.template(base.rewrite_nodes()),expected_revision=s['revision']));self.assertEqual(code,201,version);s=u.service.get(u.pid);profile=dict(role='writer',adapter_id='chat-completions-http-v1',connection_id='gg',model_id='author-selected-model',temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=True,prompt_version='rewrite-1');code,run=self.request('POST',self.url+'/runs',dict(operation_id=str(uuid4()),template_version_id=version['version_id'],chapter_id=u.f.cid,inputs=dict(instruction='HTTP虚构流程',query='灯塔',plan_text='作者规划'),roles=[profile],limits=dict(max_external_calls=2,max_reserved_output_tokens=1024,max_node_attempts=64,max_retries=1,max_iterations=3,concurrency=1),execution_mode='step',network_mode='confirm_each',expected_revision=s['revision']));self.assertEqual(code,201,run);return run
    def test_workflow_http_single_request_and_bound_diff_confirmation_not_start_permission(self):
        u=self.unit;run=self.create();root=self.url+'/runs/'+run['run_id'];before=u.service.get(u.pid)['document'];self.assertEqual(self.request('POST',root+'/control',dict(action='start'))[0],200)
        for _ in range(2):self.assertEqual(self.request('POST',root+'/step',{})[0],200)
        view=self.request('GET',root)[1];a=next(a for a in view['attempts'] if a['status']=='waiting_request');self.assertEqual(u.f.calls,[]);self.assertEqual(u.service.get(u.pid)['document'],before);request=dict(operation_id=str(uuid4()),decision='accepted',request_sha256=a['request_sha256'],diff_sha256=None,authorize_confirmed=False,confirm_inference=True,preserve_conflicts=True,expected_revision=view['revision']);self.assertEqual(self.request('POST',root+'/nodes/'+a['id']+'/confirm',request)[0],200);self.server.task_coordinator.wait_idle(5)
        for _ in range(2):self.assertEqual(self.request('POST',root+'/step',{})[0],200)
        view=self.request('GET',root)[1];human=next(a for a in view['attempts'] if a['status']=='waiting_human');request.update(operation_id=str(uuid4()),request_sha256=None,diff_sha256=human['diff_sha256'],expected_revision=view['revision']);self.assertEqual(self.request('POST',root+'/nodes/'+human['id']+'/confirm',request)[0],200);self.assertEqual(u.service.get(u.pid)['document'],before);self.assertEqual(self.request('POST',root+'/step',{})[0],200);self.assertEqual(len(u.service.get(u.pid)['adoption_receipts']),1);self.assertEqual(len(u.f.calls),1)
    def test_template_preflight_export_and_token_no_execution(self):
        u=self.unit;before=u.f.db.read_bytes();spec=base.template(base.rewrite_nodes());self.assertEqual(self.request('POST',self.url+'/preflight',spec,token=False)[0],403);bad=dict(spec,script='arbitrary execution');self.assertEqual(self.request('POST',self.url+'/preflight',bad)[0],422);self.assertEqual(u.f.db.read_bytes(),before);run=self.create();state=u.service.get(u.pid);version=state['workflow_templates'][0]['id'];code,public=self.request('GET',self.url+'/templates/'+version+'/export');self.assertEqual(code,200);self.assertNotIn(u.pid,json.dumps(public));self.assertNotIn('author-selected-model',json.dumps(public));self.assertEqual(u.f.calls,[])

if __name__=='__main__':unittest.main()
