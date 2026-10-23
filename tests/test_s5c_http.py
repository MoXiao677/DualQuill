import sys,json,http.client,threading,unittest,inspect
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src'),str(Path(__file__).resolve().parent)]
import test_s5c_models as model_fixture
from novel_writer.ui.server import create_server
from novel_writer.domain.tasks import digest
from test_s5a_rules import request_rules

class ModelHTTPTests(unittest.TestCase):
    def setUp(self):
        self.assertIn('enable_model_generation',inspect.signature(create_server).parameters,'服务器缺少显式真实模型启用门槛')
        self.fixture=model_fixture.ModelTests('test_real_wire_completion_usage_and_atomic_candidate_adoption_once');self.fixture.setUp();self.addCleanup(self.fixture.doCleanups);self.servers=[];self.addCleanup(self.stop)
    def stop(self):
        for server,thread in self.servers:server.shutdown();thread.join(3);server.server_close()
    def server(self,enabled=False,offline=False):
        f=self.fixture;s=create_server(f.db,port=0,provider_path=f.path,offline=offline,enable_model_generation=enabled,model_adapter=f.adapter);t=threading.Thread(target=s.serve_forever,kwargs={'poll_interval':.01},daemon=True);t.start();self.servers.append((s,t));return s
    def request(self,s,method,path,body=None,token=True):
        c=http.client.HTTPConnection('127.0.0.1',s.server_address[1],timeout=15);headers={'Content-Type':'application/json'}
        if token:headers['X-Novel-Token']=s.token
        try:c.request(method,path,None if body is None else json.dumps(body),headers);r=c.getresponse();return r.status,json.loads(r.read())
        finally:c.close()
    def prepare(self,s,analysis=False):
        f=self.fixture;state=s.service.get(f.pid);options=dict(chapter_id=f.cid,budget_chars=4000);preview=s.service.preview_context(f.pid,options);parameters=request_rules() if analysis else dict(instruction='HTTP候选',max_output_chars=10000,timeout_ms=2000)
        if analysis:parameters['selected_chapter_ids']=[f.cid]
        body=dict(request_id=str(uuid4()),chapter_id=f.cid,task_type='audit_chapter' if analysis else 'rewrite_chapter',context_options=options,context_sha256=digest(preview['context_text']),parameters=parameters,expected_revision=state['revision'],model_options=dict(adapter_id='chat-completions-http-v1',connection_id='gg',model_id='author-selected-model',temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=True,prompt_version='review-json-1' if analysis else 'rewrite-1'))
        code,p=self.request(s,'POST','/api/projects/'+f.pid+'/tasks/prepare',body);self.assertEqual(code,201,p);return p
    def test_default_disabled_and_offline_prepare_never_read_credentials_or_send(self):
        s=self.server();f=self.fixture
        with patch.object(f.providers,'_load',side_effect=AssertionError('未确认不能读凭据')):
            p=self.prepare(s);code,caps=self.request(s,'GET','/api/tasks/capabilities');self.assertEqual(code,200);self.assertFalse(caps['real_model_enabled']);code,failed=self.request(s,'POST','/api/projects/'+f.pid+'/tasks/'+p['task']['id']+'/execute',dict(confirm_external=True,request_sha256=p['task']['frozen']['parameters']['binding']['request_sha256']));self.assertEqual(code,422,failed)
        self.assertEqual(f.calls,[]);self.assertEqual(self.request(s,'POST','/api/projects/'+f.pid+'/tasks/'+p['task']['id']+'/execute',{},token=False)[0],403)
        offline=self.server(enabled=True,offline=True)
        with patch.object(f.providers,'_load',side_effect=AssertionError('离线不可读取生成凭据')):
            p=self.prepare(offline);code,caps=self.request(offline,'GET','/api/tasks/capabilities');self.assertFalse(caps['real_model_enabled']);code,result=self.request(offline,'POST','/api/projects/'+f.pid+'/tasks/'+p['task']['id']+'/execute',dict(confirm_external=True,request_sha256=p['task']['frozen']['parameters']['binding']['request_sha256']));self.assertEqual(code,422,result)
        self.assertEqual(f.calls,[])
    def test_enabled_model_http_analysis_report_and_explicit_summary_accept(self):
        s=self.server(enabled=True);f=self.fixture;f.mode='analysis';p=self.prepare(s,True);task=p['task'];confirm=dict(confirm_external=True,request_sha256=task['frozen']['parameters']['binding']['request_sha256']);code,r=self.request(s,'POST','/api/projects/'+f.pid+'/tasks/'+task['id']+'/execute',confirm);self.assertEqual(code,202,r);s.task_coordinator.wait_idle(4);code,view=self.request(s,'GET','/api/projects/'+f.pid+'/tasks/'+task['id']);self.assertEqual(code,200);self.assertEqual(view['task']['status'],'succeeded',view);report_id=view['model_reports'][0]['id'];code,report=self.request(s,'GET','/api/projects/'+f.pid+'/model-reviews/'+report_id);self.assertEqual(code,200,report);before=s.service.get(f.pid)
        code,receipt=self.request(s,'POST','/api/projects/'+f.pid+'/model-reviews/'+report_id+'/proposal',dict(decision_id=str(uuid4()),proposal_id=report['proposals'][0]['id'],decision='accepted',expected_revision=before['revision'],confirm_inference=True,preserve_conflicts=True));self.assertEqual(code,200,receipt);self.assertEqual(len(s.service.get(f.pid)['memories']),1);self.assertEqual(s.service.get(f.pid)['document'],before['document']);self.assertEqual(len(f.calls),1)

if __name__=='__main__':unittest.main()
