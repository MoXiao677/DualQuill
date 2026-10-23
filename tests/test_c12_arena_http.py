"""HTTP boundary tests use ephemeral loopback servers and fictional keys."""
import http.client,json,threading,unittest
from uuid import uuid4
from copy import deepcopy
import test_s6a_http as http_fixture
import test_chapter_planning as planning_fixture
from novel_writer.ui.server import create_server
from novel_writer.domain.experiments import common_instruction

class ArenaHTTPTests(unittest.TestCase):
    def setUp(self):
        self.h=http_fixture.ComparisonHTTPTests('test_actual_comparison_routes_freeze_confirm_blind_score_reveal_and_token');self.h.setUp();self.addCleanup(self.h.doCleanups)
    def test_three_audit_http_routes_hide_every_report_and_require_all_scores(self):
        h=self.h;_,request=h.unit.create(return_request=True);request.update(task_kind='audit_chapter',planning_options=None,budget=dict(max_calls=3,max_output_tokens=1536));request['profiles']=[dict(request['profiles'][0],prompt_version='review-json-1',temperature=.1+i*.1) for i in range(3)];h.unit.f.mode='analysis'
        code,made=h.request('POST',h.base+'/comparisons',request);self.assertEqual(code,201,made);base=h.base+'/comparisons/'+made['experiment_id'];setup=h.request('GET',base+'/setup')[1]
        self.assertNotIn('"side"',json.dumps(setup));self.assertNotIn('"task_id"',json.dumps(setup))
        self.assertEqual(h.request('POST',base+'/execute',dict(configuration_id=setup['configurations'][0]['configuration_id'],confirm_external=True,request_sha256='bad'))[0],422)
        for c in setup['configurations']:
            self.assertEqual(h.request('POST',base+'/execute',dict(configuration_id=c['configuration_id'],confirm_external=True,request_sha256=c['request_sha256']))[0],202);h.server.task_coordinator.wait_idle(5)
        full=h.unit.service.get(h.unit.pid);public=h.request('GET',h.base)[1];raw=json.dumps(public);self.assertEqual(public['model_reports'],[])
        for task in full['generation_tasks']:
            self.assertNotIn(task['id'],raw);self.assertIn(h.request('GET',h.base+'/tasks/'+task['id'])[0],(404,422))
        for report in full['model_reports']:self.assertIn(h.request('GET',h.base+'/model-reviews/'+report['id'])[0],(404,422))
        self.assertEqual(h.request('GET',h.base+'/tasks')[1]['tasks'],[]);blind=h.request('GET',base)[1];self.assertNotIn('identities',blind);self.assertEqual(len(blind['candidates']),3)
        for c in blind['candidates']:
            self.assertEqual(h.request('POST',base+'/score',dict(operation_id=str(uuid4()),side=c['side'],rating=4,outcome='scored',notes='虚构HTTP评价',expected_revision=h.unit.service.get(h.unit.pid)['revision']))[0],200)
        code,revealed=h.request('POST',base+'/reveal',dict(operation_id=str(uuid4()),expected_revision=h.unit.service.get(h.unit.pid)['revision']));self.assertEqual(code,200,revealed);self.assertEqual(len(revealed['identities']),3)
        before=h.unit.service.get(h.unit.pid)['document'];code,choice=h.request('POST',base+'/choose',dict(operation_id=str(uuid4()),side='C',action='open_candidate',name='',expected_revision=h.unit.service.get(h.unit.pid)['revision']));self.assertEqual(code,200,choice);self.assertEqual(h.unit.service.get(h.unit.pid)['document'],before);self.assertEqual(len(h.unit.f.calls),3)

class OutlineHTTPTests(unittest.TestCase):
    def setUp(self):
        self.f=planning_fixture.ChapterPlanningTests('test_real_book_context_flows_idea_then_ordered_outline_without_body_or_entities');self.f.setUp();self.addCleanup(self.f.doCleanups)
    def test_planning_lists_details_mutations_and_workspace_never_leak_blind_identity(self):
        f=self.f;server=create_server(f.db,port=0,provider_path=f.root/'fiction.dpapi',enable_model_generation=True);thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
        def stop():server.shutdown();thread.join(3);server.server_close()
        self.addCleanup(stop);base='/api/projects/'+f.pid
        def request(method,path,body=None):
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=20)
            try:
                connection.request(method,path,None if body is None else json.dumps(body),{'Content-Type':'application/json','X-Novel-Token':server.token});response=connection.getresponse();return response.status,json.loads(response.read())
            finally:connection.close()
        outline=dict(core_idea='虚构信封',objective='辨认封蜡',character_ids=[f.chid],scenes=[dict(order=1,summary='打开信封',character_ids=[f.chid],location='塔门',story_time='清晨')],story_time='第1天')
        with planning_fixture.supplier(output=json.dumps(outline,ensure_ascii=False)) as wire:
            connection=f.connection(wire);instruction='只用本书资料';rubric='人物与场景';source=f.source('outline',instruction=common_instruction(instruction,rubric));preview=server.chapter_planning.preview(f.pid,source)
            body=dict(experiment_id=str(uuid4()),title='HTTP细纲竞技场',chapter_id=f.cid,context_options=dict(chapter_id=f.cid,budget_chars=4000,include_writing_rules=True),context_sha256=preview['context_sha256'],instruction=instruction,rubric=rubric,parameters=dict(max_output_chars=12000,timeout_ms=3000),profiles=[dict(f.options(connection),temperature=.1+i*.1) for i in range(3)],expected_revision=f.service.get(f.pid)['revision'],task_kind='outline_chapter',planning_options=source,budget=dict(max_calls=3,max_output_tokens=2304))
            code,made=request('POST',base+'/comparisons',body);self.assertEqual(code,201,made);identifier=made['experiment_id'];setup=request('GET',base+'/comparisons/'+identifier+'/setup')[1];tasks=f.service.get(f.pid)['chapter_planning_tasks']
            for task in tasks:
                self.assertIn(request('GET',base+'/chapter-planning/'+task['id'])[0],(404,422))
                self.assertEqual(request('POST',base+'/chapter-planning/'+task['id']+'/execute',dict(confirm_external=True,request_sha256=task['binding']['request_sha256']))[0],422)
                self.assertEqual(request('POST',base+'/chapter-planning/correct',dict(operation_id=str(uuid4()),task_id=task['id'],candidate_id=str(uuid4()),text='{}'))[0],422)
            self.assertEqual(request('GET',base+'/chapter-planning')[1]['tasks'],[]);self.assertEqual(request('GET',base)[1]['chapter_planning_tasks'],[]);self.assertEqual(wire['calls'],[])
            for c in setup['configurations']:
                self.assertEqual(request('POST',base+'/comparisons/'+identifier+'/execute',dict(configuration_id=c['configuration_id'],confirm_external=True,request_sha256=c['request_sha256']))[0],202);server.task_coordinator.wait_idle(5)
            blind=request('GET',base+'/comparisons/'+identifier)[1];self.assertTrue(blind['ready']);self.assertTrue(all(c['status']=='succeeded' for c in blind['candidates']));self.assertNotIn('identities',blind)
            raw=json.dumps(request('GET',base)[1]);self.assertNotIn(connection['id'],raw);self.assertNotIn('fiction-selected',raw)

if __name__=='__main__':unittest.main()
