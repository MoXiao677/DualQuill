"""Dedicated chapter chain against a real local HTTP fixture; paid calls = 0."""
import json
import time
import unittest
from copy import deepcopy
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from uuid import uuid4
import test_s6b_workflows as legacy
from test_s6b_workflows import node, TASK


def chapter_chain():
    result=[node('read','reference',params={'max_chars':20000})]
    for identity,kind,parent,role in [('idea','model_idea','read','writer'),('outline','model_outline','idea','writer'),
                                      ('draft','model_draft','outline','writer'),('review','model_candidate_audit','draft','auditor'),
                                      ('rewrite','model_rewrite','review','writer')]:
        result.append(node(identity,kind,[parent],parent,role,TASK))
    result.extend([node('human','human',['rewrite'],'rewrite',params={'action':'body'}),
                   node('apply','apply',['human'],'human',params={'action':'body'})])
    return result


class DedicatedWorkflowTests(unittest.TestCase):
    setUp=legacy.WorkflowTests.setUp
    register=legacy.WorkflowTests.register
    create=legacy.WorkflowTests.create
    view=legacy.WorkflowTests.view
    start=legacy.WorkflowTests.start
    step=legacy.WorkflowTests.step
    waiting=legacy.WorkflowTests.waiting
    confirm=legacy.WorkflowTests.confirm

    def setup_supplier(self):
        owner=self
        self.wire=[]
        self.bad_idea=False
        class Supplier(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.wire.append(body)
                system=body['messages'][0]['content'];user=json.loads(body['messages'][1]['content'])
                if '构思本章IDEA' in system:
                    text=json.dumps({'idea':'虚构守塔人发现潮水中的信。'} if not owner.bad_idea else {'tool':'invalid'},ensure_ascii=False)
                elif '实际IDEA JSON' in system:
                    text=json.dumps({'core_idea':'守塔人读信','objective':'寻找虚构寄信者','character_ids':[],
                                     'scenes':[{'order':1,'summary':'虚构守塔人拾信','character_ids':[],'location':'虚构灯塔','story_time':'晨'}],
                                     'story_time':'晨'},ensure_ascii=False)
                elif '实际typed细纲' in system:text='虚构守塔人拾起一封被潮水打湿的信。'
                elif '只审核sources[0]' in system:
                    text=json.dumps({'overview':'待人工核实的意见','findings':[{'category':'quality','statement':'可补充触感',
                        'assessment':'model_opinion','evidence':[{'source_index':0,'start':0,'end':2,'quote':user['sources'][0]['text'][:2]}]}]},ensure_ascii=False)
                else:text='虚构守塔人拾起湿漉漉的信，纸角冰冷。'
                payload=json.dumps({'id':'c14-fictional','model':'fixture','choices':[{'message':{'role':'assistant','content':text},'finish_reason':'stop'}]},ensure_ascii=False).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        self.f.remote.RequestHandlerClass=Supplier

    def create_chain(self,**changes):
        self.setup_supplier()
        self.f.save('save_chapter',chapter_id=self.f.cid,content='')
        writer=dict(role='writer',adapter_id='chat-completions-http-v1',connection_id='gg',model_id='author-selected-model',temperature=.3,max_tokens=512,budget_limit=1.,allow_unknown_cost=True,prompt_version='rewrite-1')
        auditor=dict(writer,role='auditor',prompt_version='review-json-1')
        return self.create(nodes=chapter_chain(),roles=[writer,auditor],limits=dict(max_external_calls=7,max_reserved_output_tokens=3584,max_node_attempts=64,max_retries=1,max_iterations=3,concurrency=1),**changes)

    def complete_model(self,run,kind):
        self.step(run)
        attempt=self.waiting(run,kind)
        count=len(self.wire)
        self.assertEqual(self.view(run)['external_calls'],count)
        self.confirm(run,attempt)
        self.f.engine.wait_idle(5)
        self.step(run)
        return attempt

    def test_serial_dedicated_chain_consumes_real_typed_candidates_and_human_diff(self):
        run=self.create_chain();before=self.service.get(self.pid)['document']
        self.start(run);self.step(run)
        prior=None
        for kind in ('model_idea','model_outline','model_draft','model_candidate_audit','model_rewrite'):
            a=self.complete_model(run,kind)
            state=self.service.get(self.pid);task=next(t for t in state['generation_tasks'] if t['id']==a['task_id'])
            source=task['frozen']['parameters']['upstream']
            self.assertEqual(source['saved_target']['text'],'')
            self.assertEqual(task['frozen']['target'],source['saved_target'])
            self.assertEqual(self.service.get(self.pid)['document'],before)
            if prior:
                self.assertEqual(source['producer_task_id'],prior['task_id'])
                self.assertEqual(source['producer_node_attempt_id'],prior['id'])
                self.assertIn(source['via_node_attempt_id'],a['input_attempt_ids'])
            if kind!='model_candidate_audit':prior=a
        self.assertIn('typed_result',next(a for a in self.view(run)['attempts'] if a['node_id']=='outline'))
        idea=json.loads(self.wire[1]['messages'][1]['content'])
        self.assertEqual(json.loads(idea['source_text'])['idea'],'虚构守塔人发现潮水中的信。')
        self.assertIn('可补充触感',json.loads(self.wire[4]['messages'][1]['content'])['context'])
        self.step(run);human=self.waiting(run,'human')
        self.assertEqual(human['review']['before'],'')
        self.assertEqual(human['review']['after'],'虚构守塔人拾起湿漉漉的信，纸角冰冷。')
        self.confirm(run,human);self.step(run);self.step(run)
        saved=self.service.get(self.pid)
        self.assertEqual(self.view(run)['status'],'completed')
        self.assertEqual(saved['document']['chapters'][0]['content'],human['review']['after'])
        self.assertEqual(len(saved['adoption_receipts']),1)
        self.assertFalse(saved['ideas'].get(self.f.cid,''))
        self.assertEqual(saved['workspace_version'],40)

    def test_invalid_typed_plan_fails_and_retry_reserves_again_without_refund(self):
        run=self.create_chain();self.bad_idea=True;self.start(run);self.step(run)
        self.complete_model(run,'model_idea')
        old=next(a for a in self.view(run)['attempts'] if a['node_id']=='idea')
        self.assertEqual(old['status'],'failed');self.assertEqual(old['error_code'],'invalid_workflow_typed_plan')
        self.bad_idea=False;self.engine.retry(self.pid,run['run_id'],'idea')
        new=self.waiting(run,'model_idea');self.assertNotEqual(old['id'],new['id'])
        self.confirm(run,new);self.f.engine.wait_idle(5);self.step(run)
        self.complete_model(run,'model_outline')
        view=self.view(run)
        self.assertEqual(view['external_calls'],3);self.assertEqual(view['reserved_output_tokens'],1536)
        outline=next(a for a in view['attempts'] if a['node_id']=='outline')
        self.assertEqual(outline['input_attempt_ids'],[new['id']])
        self.assertEqual(next(a for a in view['attempts'] if a['id']==old['id'])['status'],'failed')

    def test_saved_text_cannot_stand_in_for_typed_outline(self):
        self.setup_supplier()
        self.f.save('save_chapter',chapter_id=self.f.cid,content='')
        run=self.create(nodes=[node('read','reference',params={'max_chars':20000}),node('draft','model_draft',['read'],'read','writer',TASK)])
        self.start(run);self.step(run)
        with self.assertRaisesRegex(ValueError,'typed'):self.step(run)
        self.assertFalse(self.wire)

    def test_nonempty_draft_target_rejected_before_any_request_or_run(self):
        self.setup_supplier()
        before=self.service.get(self.pid)['document']
        with self.assertRaisesRegex(ValueError,'只支持空正文'):
            self.create(nodes=[node('read','reference',params={'max_chars':20000}),node('draft','model_draft',['read'],'read','writer',TASK)])
        self.assertFalse(self.wire)
        state=self.service.get(self.pid);self.assertFalse(state.get('workflow_runs',[]));self.assertEqual(state['document'],before)

    def test_typed_plan_cannot_be_adopted_as_body_and_original_guard_cannot_be_reset(self):
        from novel_writer.storage.sqlite_repository import validate_workspace
        run=self.create_chain();self.start(run);self.step(run);idea=self.complete_model(run,'model_idea')
        state=self.service.get(self.pid);task=next(t for t in state['generation_tasks'] if t['id']==idea['task_id'])
        with self.assertRaisesRegex(ValueError,'IDEA'):
            self.f.engine.adopt(self.pid,task['id'],dict(candidate_id=task['candidate_id'],adoption_id=str(uuid4()),expected_revision=state['revision'],authorize_confirmed=False))
        corrupt=deepcopy(state);source=corrupt['generation_tasks'][0]['frozen']['parameters']['upstream'];source['text_sha256']='0'*64
        with self.assertRaises(ValueError):validate_workspace(corrupt)
        corrupt=deepcopy(state);corrupt['workspace_version']=39
        with self.assertRaisesRegex(ValueError,'V40'):validate_workspace(corrupt)
        self.f.save('save_chapter',chapter_id=self.f.cid,content='作者后来保存的新稿')
        with self.assertRaisesRegex(ValueError,'正式目标已变化'):self.step(run)
        self.assertEqual(len(self.wire),1)

    def test_v36_restore_copy_keep_typed_sources_but_invalidate_write_permission(self):
        from novel_writer.application.backups import create_backup,restore_backup
        from novel_writer.application.migrations import migrate
        from novel_writer.application.service import NovelService
        from novel_writer.application.workflows import WorkflowCoordinator
        from novel_writer.storage.sqlite_repository import SQLiteRepository
        from novel_writer.application.skill_import import SkillLibrary
        from novel_writer.application.tasks import TaskCoordinator
        from novel_writer.application.task_protocol import AdapterRegistry
        from test_s5a_review import rows
        run=self.create_chain();self.start(run);self.step(run)
        for kind in ('model_idea','model_outline','model_draft','model_candidate_audit','model_rewrite'):self.complete_model(run,kind)
        self.step(run);self.confirm(run,self.waiting(run,'human'))
        package=self.f.root/'c14.nwbak';manifest=create_backup(self.f.db,package)
        self.assertEqual(manifest['backup_format_version'],51)
        restored=Path(restore_backup(package,self.f.root/'restored')['database_path']);self.assertEqual(rows(restored),rows(self.f.db))
        original=self.service.get(self.pid)
        copy=self.f.root/'copied.sqlite3';SQLiteRepository(copy);SkillLibrary(copy)
        result=migrate(package,copy,operation_id=str(uuid4()));pid=result['projects'][0]['new_id']
        service=NovelService(SQLiteRepository(copy));tasks=TaskCoordinator(service,AdapterRegistry());flow=WorkflowCoordinator(service,tasks)
        self.addCleanup(tasks.close);self.addCleanup(flow.close)
        state=service.get(pid);rid=state['workflow_runs'][0]['id'];view=flow.describe(pid,rid)
        self.assertTrue(view['requires_recovery'])
        self.assertEqual(state['generation_candidates'][0]['output_text'],original['generation_candidates'][0]['output_text'])
        for old,new in zip(original['generation_tasks'],state['generation_tasks']):
            self.assertEqual(old['frozen']['parameters']['binding']['request_body'],new['frozen']['parameters']['binding']['request_body'])
            self.assertNotEqual(old['id'],new['id'])
        with self.assertRaises(ValueError):flow.step(pid,rid)
        flow.control(pid,rid,'recover');flow.step(pid,rid)
        self.assertEqual(flow.describe(pid,rid)['attempts'][-1]['status'],'waiting_human')
        self.assertFalse(service.get(pid)['adoption_receipts'])
        self.assertEqual(len(self.wire),5)

    def test_bounded_parallel_independent_candidates_confirm_each_and_join(self):
        import threading
        self.setup_supplier()
        reached=threading.Event();release=threading.Event();count=[0];lock=threading.Lock()
        handler=self.f.remote.RequestHandlerClass
        class Slow(handler):
            def do_POST(inner):
                with lock:
                    count[0]+=1
                    if count[0]==2:reached.set()
                release.wait(4)
                super().do_POST()
        self.f.remote.RequestHandlerClass=Slow
        self.addCleanup(release.set)
        nodes=[node('read','reference',params={'max_chars':20000}),
               node('left','model_rewrite',['read'],'read','writer',TASK),
               node('right','model_rewrite',['read'],'read','writer',TASK),
               node('third','model_rewrite',['read'],'read','writer',TASK),
               node('join','join',['left','right','third'],'right')]
        run=self.create(nodes=nodes,limits=dict(max_external_calls=3,max_reserved_output_tokens=1536,max_node_attempts=64,max_retries=1,max_iterations=3,concurrency=2))
        self.start(run);self.step(run);self.step(run)
        view=self.view(run);waiting=[a for a in view['attempts'] if a['status']=='waiting_request']
        self.assertEqual([a['node_id'] for a in waiting],['left','right'])
        self.assertFalse(self.wire);self.confirm(run,waiting[0]);self.confirm(run,waiting[1])
        self.assertTrue(reached.wait(3),'both independent requests must actually run concurrently')
        self.assertEqual(self.view(run)['external_calls'],2)
        self.assertEqual(len(self.f.engine.execution_claims),2)
        self.step(run);self.assertNotIn('third',[a['node_id'] for a in self.view(run)['attempts']])
        release.set();self.f.engine.wait_idle(5)
        for _ in range(4):self.step(run)
        third=self.waiting(run,'model_rewrite');self.assertEqual(third['node_id'],'third')
        self.confirm(run,third);self.f.engine.wait_idle(5)
        for _ in range(4):
            if self.view(run)['status']=='completed':break
            self.step(run)
        view=self.view(run);self.assertEqual(view['status'],'completed')
        state=self.service.get(self.pid);join=next(a for a in view['attempts'] if a['node_id']=='join')
        snapshot=next(e['snapshot'] for e in reversed(state['workflow_node_events']) if e['attempt_id']==join['id'])
        self.assertEqual(snapshot['producer_node_attempt_id'],waiting[1]['id'])
        self.assertFalse(state['adoption_receipts']);self.assertEqual(view['reserved_output_tokens'],1536)

    def test_parallel_formal_target_conflict_rejected_before_run_is_saved(self):
        nodes=[node('read','reference',params={'max_chars':20000}),node('write','model_rewrite',['read'],'read','writer',TASK),
               node('h1','human',['write'],'write',params={'action':'body'}),node('h2','human',['write'],'write',params={'action':'body'}),
               node('a1','apply',['h1'],'h1',params={'action':'body'}),node('a2','apply',['h2'],'h2',params={'action':'body'})]
        before=len(self.service.get(self.pid).get('workflow_runs',[]))
        with self.assertRaisesRegex(ValueError,'目标冲突'):
            self.create(nodes=nodes,limits=dict(max_external_calls=2,max_reserved_output_tokens=1024,max_node_attempts=64,max_retries=1,max_iterations=3,concurrency=2))
        self.assertEqual(len(self.service.get(self.pid).get('workflow_runs',[])),before)
        self.assertFalse(self.f.calls)

    def test_dedicated_branch_skips_before_preparing_invalid_typed_source(self):
        self.f.save('save_chapter',chapter_id=self.f.cid,content='')
        self.setup_supplier()
        nodes=[node('search','search',params={'max_results':2}),
               node('branch','branch',['search'],'search',params={'expected':'no_findings'}),
               node('draft','model_draft',['branch','search'],'search','writer',TASK,when={'source':'branch','equals':True}),
               node('join','join',['draft','search'],'search')]
        # The fictional fixture has a saved lighthouse hit, so no_findings=False.
        run=self.create(nodes=nodes);self.start(run)
        for _ in range(5):self.step(run)
        view=self.view(run);self.assertEqual(view['status'],'completed')
        draft=next(a for a in view['attempts'] if a['node_id']=='draft')
        self.assertEqual(draft['status'],'skipped');self.assertIsNone(draft['task_id']);self.assertFalse(self.wire)

    def test_explicit_failure_branch_finishes_without_faking_a_typed_result(self):
        self.setup_supplier();self.bad_idea=True
        nodes=[node('read','reference',params={'max_chars':20000}),node('idea','model_idea',['read'],'read','writer',TASK),
               node('failed','branch',['idea'],'idea',params={'expected':'failed'}),
               node('fallback','manual',['failed'],params={'slot':'instruction'},when={'source':'failed','equals':True}),
               node('join','join',['fallback'])]
        run=self.create(nodes=nodes);self.start(run);self.step(run);self.complete_model(run,'model_idea')
        for _ in range(4):self.step(run)
        view=self.view(run);self.assertEqual(view['status'],'completed')
        self.assertEqual(next(a for a in view['attempts'] if a['node_id']=='idea')['status'],'failed')
        self.assertEqual(next(a for a in view['attempts'] if a['node_id']=='fallback')['status'],'succeeded')
        self.assertFalse(self.service.get(self.pid)['generation_candidates'])

    def test_v1_through_v35_saved_manuscript_reads_are_byte_preserving(self):
        from importlib import import_module
        from hashlib import sha256
        from novel_writer.storage.sqlite_repository import SQLiteRepository
        base={k:deepcopy(v) for k,v in self.service.get(self.pid).items() if k in
              ('workspace_version','revision','document','ideas','worldbuilding','writing_rules')}
        groups=[(2,None,('memories','memory_history')),(3,'tasks','COLLECTIONS'),(4,'review','REVIEW_COLLECTIONS'),
                (5,'knowledge','KNOWLEDGE_COLLECTIONS'),(6,'model_contract','MODEL_COLLECTIONS'),(7,'experiments','EXPERIMENT_COLLECTIONS'),
                (8,'workflows','WORKFLOW_COLLECTIONS'),(10,'creation_presets','CREATION_COLLECTIONS'),(11,'book_creation','COLLECTIONS'),
                (12,'book_ai','COLLECTIONS'),(13,'styles','COLLECTIONS'),(14,'public_search','COLLECTIONS'),(15,'style_trials','COLLECTIONS'),
                (16,'chapter_writing','COLLECTIONS'),(17,'chapter_planning','COLLECTIONS'),(18,'scene_expansion','COLLECTIONS'),
                (19,'chapter_lifecycle','COLLECTIONS'),(20,'console','COLLECTIONS'),(21,None,('scoped_rules',)),
                (22,None,('scoped_rule_history',)),(23,'memory_rollups','COLLECTIONS'),(24,'console','RUN_COLLECTIONS'),
                (25,'materials','COLLECTIONS'),(26,'full_book_planning','COLLECTIONS'),(27,'chapter_trash','COLLECTIONS')]
        for version in range(1,36):
            with self.subTest(version=version):
                state=deepcopy(base);state['workspace_version']=version
                for start,module,collection in groups:
                    if version>=start:
                        names=getattr(import_module('novel_writer.domain.'+module),collection) if module else collection
                        for name in names:state[name]=[]
                path=self.f.root/f'legacy-v{version}.sqlite3';repo=SQLiteRepository(path);saved=repo.create(state)
                before=sha256(path.read_bytes()).hexdigest()
                self.assertEqual(repo.get(self.pid),saved);repo.list_projects()
                self.assertEqual(SQLiteRepository(path).get(self.pid),saved)
                self.assertEqual(sha256(path.read_bytes()).hexdigest(),before)


if __name__=='__main__':unittest.main()
