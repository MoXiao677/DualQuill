from pathlib import Path
import sys,json,http.client,threading,unittest
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
import test_s6a_comparison as comparison
from novel_writer.ui.server import create_server

class ComparisonHTTPTests(unittest.TestCase):
    def setUp(self):
        self.unit=comparison.ComparisonTests('test_blind_scores_reveal_reopen_winner_only_opens_candidate_and_preset');self.unit.setUp();self.addCleanup(self.unit.doCleanups);f=self.unit.f;self.server=create_server(f.db,port=0,provider_path=f.path,enable_model_generation=True,model_adapter=f.adapter);self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start();self.addCleanup(self.stop);self.base='/api/projects/'+self.unit.pid
    def stop(self):self.server.shutdown();self.thread.join(3);self.server.server_close()
    def request(self,method,path,body=None,token=True):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_address[1],timeout=20);headers={'Content-Type':'application/json'}
        if token:headers['X-Novel-Token']=self.server.token
        try:c.request(method,path,None if body is None else json.dumps(body),headers);r=c.getresponse();return r.status,json.loads(r.read())
        finally:c.close()
    def test_normal_project_task_and_report_responses_hide_unrevealed_children_not_only_cards(self):
        made,_=self.unit.create();self.unit.execute(made['experiment_id']);full=self.unit.service.get(self.unit.pid);before=self.unit.f.db.read_bytes();code,public=self.request('GET',self.base);self.assertEqual(code,200);self.assertTrue(public.get('read_only_projection'),'普通工作区响应直接泄露完整实验绑定');raw=json.dumps(public)
        for task in full['generation_tasks']:
            self.assertNotIn(task['id'],raw);self.assertNotIn(task['frozen']['parameters']['binding']['model_id'],raw);self.assertNotIn('supplier-reported-alias',raw)
            self.assertIn(self.request('GET',self.base+'/tasks/'+task['id'])[0],(404,422))
        self.assertEqual(self.request('GET',self.base+'/tasks')[1]['tasks'],[]);self.assertEqual(self.unit.f.db.read_bytes(),before);self.assertEqual(len(full['comparison_experiments'][0]['configurations']),2);self.assertEqual(len(full['model_results']),2)
        code,saved=self.request('POST',self.base+'/actions',dict(action='save_worldbuilding',fields=dict(content='作者修改无关设定'),expected_revision=full['revision']));self.assertEqual(code,200,saved);self.assertTrue(saved.get('read_only_projection'));self.assertNotIn('author-selected-model',json.dumps(saved));self.assertEqual(len(self.unit.service.get(self.unit.pid)['generation_tasks']),2)
        self.unit.score(made['experiment_id'],'A');self.unit.score(made['experiment_id'],'B');self.unit.reveal(made['experiment_id']);code,visible=self.request('GET',self.base);self.assertFalse(visible.get('read_only_projection',False));self.assertEqual(len(visible['generation_tasks']),2)
    def test_actual_comparison_routes_freeze_confirm_blind_score_reveal_and_token(self):
        _,request=self.unit.create(return_request=True);self.assertEqual(self.request('POST',self.base+'/comparisons',request,token=False)[0],403);code,created=self.request('POST',self.base+'/comparisons',request);self.assertEqual(code,201,created);identifier=created['experiment_id'];code,setup=self.request('GET',self.base+'/comparisons/'+identifier+'/setup');self.assertEqual(code,200,setup);self.assertNotIn('"side"',json.dumps(setup));self.assertNotIn('"task_id"',json.dumps(setup))
        for cfg in setup['configurations']:
            code,result=self.request('POST',self.base+'/comparisons/'+identifier+'/execute',dict(configuration_id=cfg['configuration_id'],confirm_external=True,request_sha256=cfg['request_sha256']));self.assertEqual(code,202,result);self.server.task_coordinator.wait_idle(5)
        code,blind=self.request('GET',self.base+'/comparisons/'+identifier);self.assertEqual(code,200);self.assertTrue(blind['ready']);self.assertNotIn('identities',blind)
        for side in ('A','B'):
            code,result=self.request('POST',self.base+'/comparisons/'+identifier+'/score',dict(operation_id=str(uuid4()),side=side,rating=3,outcome='scored',notes='HTTP虚构盲评分',expected_revision=self.unit.service.get(self.unit.pid)['revision']));self.assertEqual(code,200,result)
        code,result=self.request('POST',self.base+'/comparisons/'+identifier+'/reveal',dict(operation_id=str(uuid4()),expected_revision=self.unit.service.get(self.unit.pid)['revision']));self.assertEqual(code,200,result);self.assertEqual(len(result['identities']),2);self.assertEqual(len(self.unit.f.calls),2)
    def test_recovery_response_hides_identity_while_persisting_interruption(self):
        from novel_writer.application.tasks import get_task,event
        self.unit.create();state=self.unit.service.get(self.unit.pid);task_id=state['comparison_experiments'][0]['configurations'][0]['task_id']
        def simulate_prior_owner(state):
            event(state,get_task(state,task_id),'started',attempt_id=str(uuid4()),owner_id=str(uuid4()));return state,None
        self.unit.service.repository.atomic(self.unit.pid,simulate_prior_owner);code,value=self.request('POST',self.base+'/tasks/recover',{});self.assertEqual(code,200,value);self.assertNotIn(task_id,json.dumps(value));self.assertNotIn('author-selected-model',json.dumps(value));saved=self.unit.service.get(self.unit.pid);self.assertEqual(next(t for t in saved['generation_tasks'] if t['id']==task_id)['status'],'interrupted');self.assertEqual(self.unit.f.calls,[])

if __name__=='__main__':unittest.main()
