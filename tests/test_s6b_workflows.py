from pathlib import Path
from importlib import util,import_module
from uuid import uuid4
from copy import deepcopy
import sys,json,unittest,time,threading
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
import test_s5c_models as fixture
from test_s5a_review import rows

TASK=dict(context_budget=4000,max_output_chars=10000,timeout_ms=2000)
def node(identifier,kind,parents=(),source=None,role=None,params=None,when=None):return dict(id=identifier,kind=kind,parents=list(parents),source=source,role=role,parameters=params or {},when=when)
def template(nodes,name='虚构白名单工作流'):
    permissions={'read_saved_source'}
    for n in nodes:
        permissions|={'search_local'} if n['kind']=='search' else {'offline_analysis'} if n['kind']=='offline_audit' else {'prepare_model_request'} if n['kind'].startswith('model_') else {'propose_changes'} if n['kind'] in ('plan_proposal','memory_proposal') else {'human_approval'} if n['kind']=='human' else {'apply_approved_change'} if n['kind']=='apply' else set()
    return dict(workflow_format=1,interface_version=1,name=name,permissions=sorted(permissions),nodes=nodes)
def rewrite_nodes():return [node('read','reference',params=dict(max_chars=20000)),node('rewrite','model_rewrite',['read'],'read','writer',TASK),node('approve','human',['rewrite'],'rewrite',params=dict(action='body')),node('apply','apply',['approve'],'approve',params=dict(action='body'))]

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(util.find_spec('novel_writer.application.workflows'),'缺少持久白名单图/审批与预算工作流')
        self.api=import_module('novel_writer.application.workflows');self.f=fixture.ModelTests('test_real_wire_completion_usage_and_atomic_candidate_adoption_once');self.f.setUp();self.addCleanup(self.f.doCleanups);self.service=self.f.service;self.pid=self.f.pid;self.engine=self.api.WorkflowCoordinator(self.service,self.f.engine);self.addCleanup(self.engine.close)
    def register(self,nodes):
        state=self.service.get(self.pid);return self.engine.import_template(self.pid,dict(operation_id=str(uuid4()),template_id=None,template=template(nodes),expected_revision=state['revision']))
    def create(self,nodes=None,**changes):
        version=self.register(nodes or rewrite_nodes());state=self.service.get(self.pid);profile=dict(role='writer',adapter_id='chat-completions-http-v1',connection_id='gg',model_id='author-selected-model',temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=True,prompt_version='rewrite-1');request=dict(operation_id=str(uuid4()),template_version_id=version['version_id'],chapter_id=self.f.cid,inputs=dict(instruction='根据保存原稿写候选',query='灯塔',plan_text='作者明确提出的新结局'),roles=[profile],limits=dict(max_external_calls=2,max_reserved_output_tokens=1024,max_node_attempts=64,max_retries=1,max_iterations=3,concurrency=1),execution_mode='step',network_mode='confirm_each',expected_revision=state['revision']);request.update(changes);return self.engine.create(self.pid,request)
    def view(self,run):return self.engine.describe(self.pid,run['run_id'])
    def start(self,run):return self.engine.control(self.pid,run['run_id'],'start')
    def step(self,run):return self.engine.step(self.pid,run['run_id'])
    def waiting(self,run,kind):return next(a for a in reversed(self.view(run)['attempts']) if a['node_kind']==kind and a['status'] in ('waiting_request','waiting_human'))
    def confirm(self,run,attempt,**changes):
        request=dict(operation_id=str(uuid4()),decision='accepted',request_sha256=attempt.get('request_sha256'),diff_sha256=attempt.get('diff_sha256'),authorize_confirmed=False,confirm_inference=True,preserve_conflicts=True,expected_revision=self.service.get(self.pid)['revision']);request.update(changes);return self.engine.confirm(self.pid,run['run_id'],attempt['id'],request)
    def model_completed(self,run):
        self.start(run);self.step(run);self.step(run);a=self.waiting(run,'model_rewrite');self.confirm(run,a);self.f.engine.wait_idle(5);self.step(run);return a
    def test_real_model_waits_single_confirmation_and_body_waits_bound_human_then_atomic_once(self):
        self.f.save('save_chapter',chapter_id=self.f.cid,status='confirmed');run=self.create();before=self.service.get(self.pid)['document'];self.start(run);self.step(run);self.step(run);a=self.waiting(run,'model_rewrite');self.assertEqual(self.f.calls,[]);self.assertEqual(self.service.get(self.pid)['document'],before)
        with self.assertRaises(ValueError):self.confirm(run,a,request_sha256='0'*64)
        self.confirm(run,a);self.f.engine.wait_idle(5);self.step(run);self.step(run);human=self.waiting(run,'human');self.assertEqual(len(self.f.calls),1);self.assertEqual(self.service.get(self.pid)['document'],before)
        with self.assertRaises(ValueError):self.confirm(run,human,diff_sha256='0'*64)
        self.confirm(run,human,authorize_confirmed=True);self.step(run);after=self.service.get(self.pid);self.assertEqual(len(after['document']['versions']),len(before['versions'])+1);self.assertEqual(next(c for c in after['document']['chapters'] if c['id']==self.f.cid)['content'],'模型返回的完整候选。');self.step(run);self.assertEqual(self.view(run)['status'],'completed');self.assertEqual(len(after['adoption_receipts']),1)
    def test_pause_after_result_prevents_successor_and_resume_requires_fresh_write_approval(self):
        run=self.create();self.model_completed(run);self.step(run);human=self.waiting(run,'human');self.confirm(run,human);before=self.service.get(self.pid)['document'];self.engine.control(self.pid,run['run_id'],'pause')
        with self.assertRaises(ValueError):self.step(run)
        self.engine.control(self.pid,run['run_id'],'resume');self.step(run);renewed=self.waiting(run,'human');self.assertNotEqual(renewed['id'],human['id']);self.assertEqual(self.service.get(self.pid)['document'],before);self.assertEqual(len(self.f.calls),1);self.confirm(run,renewed);self.step(run);self.assertEqual(len(self.service.get(self.pid)['adoption_receipts']),1)
    def test_cancellation_and_stale_source_do_not_write_or_auto_reconfirm(self):
        run=self.create();self.model_completed(run);self.step(run);human=self.waiting(run,'human');self.confirm(run,human);self.engine.control(self.pid,run['run_id'],'cancel');before=rows(self.f.db)
        with self.assertRaises(ValueError):self.step(run)
        self.assertEqual(rows(self.f.db),before);self.assertEqual(len(self.service.get(self.pid)['adoption_receipts']),0)
    def test_attempt_budget_not_refunded_after_failure_explicit_retry_uses_new_task(self):
        limits=dict(max_external_calls=1,max_reserved_output_tokens=512,max_node_attempts=64,max_retries=1,max_iterations=3,concurrency=1);run=self.create(limits=limits);self.f.mode='429';self.start(run);self.step(run);self.step(run);first=self.waiting(run,'model_rewrite');self.confirm(run,first);self.f.engine.wait_idle(5);self.step(run);self.assertEqual(self.view(run)['external_calls'],1);self.assertEqual(self.view(run)['reserved_output_tokens'],512)
        self.f.mode='success';self.engine.retry(self.pid,run['run_id'],'rewrite');self.step(run);second=self.waiting(run,'model_rewrite');self.assertNotEqual(first['task_id'],second['task_id'])
        with self.assertRaises(ValueError):self.confirm(run,second)
        self.assertEqual(len(self.f.calls),1);self.assertEqual(self.view(run)['external_calls'],1)
    def test_model_owned_task_cannot_bypass_workflow_confirmation_via_base_task_api(self):
        run=self.create();self.start(run);self.step(run);self.step(run);a=self.waiting(run,'model_rewrite')
        with self.assertRaises(ValueError):self.f.engine.start(self.pid,a['task_id'],confirmation=dict(confirm_external=True,request_sha256=a['request_sha256']))
        self.assertEqual(self.f.calls,[]);self.engine.control(self.pid,run['run_id'],'manual');
        with self.assertRaises(ValueError):self.confirm(run,a)
        self.assertEqual(self.f.calls,[])
    def test_branch_skip_join_bounded_loop_and_template_code_rejection(self):
        nodes=[node('read','reference',params=dict(max_chars=1000)),node('branch','branch',['read'],'read',params=dict(expected='has_findings')),node('skipped','reference',['branch','read'],'read',params=dict(max_chars=1000),when=dict(source='branch',equals=True)),node('join','join',['read','skipped']),node('repeat','loop',['join'],params=dict(iterations=2,nodes=[node('inside','reference',params=dict(max_chars=1000))]))];run=self.create(nodes=nodes);self.start(run)
        for _ in range(12):
            if self.view(run)['status']=='completed':break
            self.step(run)
        view=self.view(run);self.assertEqual(view['status'],'completed');self.assertTrue(any(a['node_id']=='skipped' and a['status']=='skipped' for a in view['attempts']));self.assertEqual(sum('inside' in a['node_id'] for a in view['attempts']),2);self.assertTrue(next(a for a in view['attempts'] if a['node_kind']=='join')['input_attempt_ids']);self.assertEqual(self.f.calls,[])
        bad=template([node('x','reference',['x'],params=dict(max_chars=1000))])
        with self.assertRaises(ValueError):self.engine.preflight(bad)
        bad=template([node('x','manual',params=dict(slot='instruction'))]);bad['script']='arbitrary code'
        with self.assertRaises(ValueError):self.engine.preflight(bad)
        bad=template([node('repeat','loop',params=dict(iterations=999,nodes=[node('x','reference',params=dict(max_chars=1000))]))])
        with self.assertRaises(ValueError):self.engine.preflight(bad)
    def test_restart_read_is_pure_and_old_unconsumed_write_permission_never_executes(self):
        run=self.create();self.model_completed(run);self.step(run);human=self.waiting(run,'human');self.confirm(run,human);before=rows(self.f.db);new=self.api.WorkflowCoordinator(self.service,self.f.engine);self.addCleanup(new.close);view=new.describe(self.pid,run['run_id']);self.assertTrue(view['requires_recovery']);self.assertEqual(rows(self.f.db),before)
        with self.assertRaises(ValueError):new.step(self.pid,run['run_id'])
        new.control(self.pid,run['run_id'],'recover');new.step(self.pid,run['run_id']);pending=next(a for a in reversed(new.describe(self.pid,run['run_id'])['attempts']) if a['status']=='waiting_human');self.assertNotEqual(pending['id'],human['id']);self.assertEqual(self.service.get(self.pid)['adoption_receipts'],[]);self.assertEqual(len(self.f.calls),1)
    def test_plan_lock_and_offline_memory_nodes_require_explicit_human_changes(self):
        nodes=[node('plan','plan_proposal',params=dict(target_kind='book_outline',field='ending')),node('approve','human',['plan'],'plan',params=dict(action='plan')),node('apply','apply',['approve'],'approve',params=dict(action='plan'))];run=self.create(nodes=nodes);before=self.service.get(self.pid)['document'];self.start(run);self.step(run);self.step(run);human=self.waiting(run,'human');self.assertEqual(self.service.get(self.pid)['document'],before);self.confirm(run,human);self.step(run);self.assertEqual(self.service.get(self.pid)['document']['book_outline']['ending'],'作者明确提出的新结局');self.assertEqual(self.f.calls,[])
    def test_v8_backup_copy_retains_results_but_never_inherits_unconsumed_approvals(self):
        from novel_writer.application.backups import create_backup,restore_backup
        from novel_writer.application.migrations import migrate
        from novel_writer.storage.sqlite_repository import SQLiteRepository
        from novel_writer.application.skill_import import SkillLibrary
        from novel_writer.application.service import NovelService
        from novel_writer.application.tasks import TaskCoordinator
        from novel_writer.application.task_protocol import AdapterRegistry
        run=self.create();self.model_completed(run);self.step(run);human=self.waiting(run,'human');self.confirm(run,human);package=self.f.root/'workflow.nwbak';manifest=create_backup(self.f.db,package);self.assertEqual(manifest['backup_format_version'],51);restored=Path(restore_backup(package,self.f.root/'restored-v8')['database_path']);self.assertEqual(rows(restored),rows(self.f.db));target=self.f.root/'copied.sqlite3';SQLiteRepository(target);SkillLibrary(target);result=migrate(package,target,operation_id=str(uuid4()));pid=result['projects'][0]['new_id'];service=NovelService(SQLiteRepository(target));tasks=TaskCoordinator(service,AdapterRegistry());self.addCleanup(tasks.close);copy=self.api.WorkflowCoordinator(service,tasks);self.addCleanup(copy.close);state=service.get(pid);identifier=state['workflow_runs'][0]['id'];self.assertTrue(copy.describe(pid,identifier)['requires_recovery']);before=rows(target)
        with self.assertRaises(ValueError):copy.step(pid,identifier)
        self.assertEqual(rows(target),before);self.assertFalse(state['adoption_receipts']);self.assertEqual(len(self.f.calls),1);copy.control(pid,identifier,'recover');copy.step(pid,identifier);view=copy.describe(pid,identifier);human=next(a for a in reversed(view['attempts']) if a['status']=='waiting_human');copy.confirm(pid,identifier,human['id'],dict(operation_id=str(uuid4()),decision='accepted',request_sha256=None,diff_sha256=human['diff_sha256'],authorize_confirmed=False,confirm_inference=True,preserve_conflicts=True,expected_revision=view['revision']));copy.step(pid,identifier);self.assertEqual(len(service.get(pid)['adoption_receipts']),1);self.assertEqual(len(self.f.calls),1)
        frozen=json.loads((ROOT/'tests/fixtures/s6b_legacy.json').read_text(encoding='utf8'))['v7'];old=self.f.root/'old-v7.sqlite3';old.write_bytes(bytes.fromhex(frozen['database_hex']));data=old.read_bytes();NovelService(SQLiteRepository(old)).get(frozen['project_id']);self.assertEqual(old.read_bytes(),data);oldpack=self.f.root/'old-v7.nwbak';oldpack.write_bytes(bytes.fromhex(frozen['package_hex']));oldrestored=Path(restore_backup(oldpack,self.f.root/'restored-v7')['database_path']);self.assertEqual(rows(oldrestored),frozen['rows'])
    def test_downstream_audits_and_rewrites_declared_candidate_not_saved_original(self):
        nodes=[node('read','reference',params=dict(max_chars=20000)),node('first','model_rewrite',['read'],'read','writer',TASK),node('audit','offline_audit',['first'],'first',params=dict(**TASK,forbidden_literals=['完整候选'])),node('second','model_rewrite',['audit'],'audit','writer',TASK),node('human','human',['second'],'second',params=dict(action='body')),node('apply','apply',['human'],'human',params=dict(action='body'))];run=self.create(nodes=nodes);original=self.service.get(self.pid)['document']['chapters'][0];self.start(run);self.step(run);self.step(run);first=self.waiting(run,'model_rewrite');self.confirm(run,first);self.f.engine.wait_idle(5);self.step(run);self.step(run);audit=next(a for a in self.view(run)['attempts'] if a['node_id']=='audit');self.assertEqual(audit['status'],'succeeded');self.assertTrue(audit['audit']['findings'],'只有候选含禁用字面串，读保存原稿会错过');e=audit['audit']['findings'][0]['evidence'][0];self.assertEqual(e['source_kind'],'candidate');self.assertEqual(e['task_id'],first['task_id']);self.assertIsNone(e['version_id']);self.assertNotIn('完整候选',original['content']);self.step(run);second=self.waiting(run,'model_rewrite');self.confirm(run,second);self.f.engine.wait_idle(5);self.step(run)
        sent=json.loads(self.f.calls[1]['body']['messages'][1]['content']);self.assertEqual(sent['original'],'模型返回的完整候选。');self.assertNotEqual(sent['original'],original['content']);self.assertIn('完整候选',sent['context']);state=self.service.get(self.pid);second_task=next(t for t in state['generation_tasks'] if t['id']==second['task_id']);self.assertEqual(second_task['frozen']['target']['text'],original['content']);self.assertEqual(second_task['frozen']['target']['version_id'],original['current_version_id']);self.assertFalse(state['memories']);self.assertFalse(state['adoption_receipts'])
    def test_candidate_cannot_be_promoted_to_saved_fact_and_rejection_is_persistent(self):
        nodes=[node('read','reference',params=dict(max_chars=20000)),node('rewrite','model_rewrite',['read'],'read','writer',TASK),node('memory','memory_proposal',['rewrite'],'rewrite',params=dict(index=0))];run=self.create(nodes=nodes);self.model_completed(run)
        with self.assertRaises(ValueError):self.step(run)
        view=self.view(run);self.assertEqual(view['status'],'failed');self.assertTrue(any(a['node_id']=='memory' and a['status']=='failed' for a in view['attempts']));self.assertEqual(self.service.get(self.pid)['memories'],[])
    def test_candidate_rule_review_keeps_candidate_for_bound_human_adoption(self):
        nodes=[node('read','reference',params=dict(max_chars=20000)),node('rewrite','model_rewrite',['read'],'read','writer',TASK),node('audit','offline_audit',['rewrite'],'rewrite',params=dict(**TASK,forbidden_literals=['完整候选'])),node('human','human',['audit'],'audit',params=dict(action='body')),node('apply','apply',['human'],'human',params=dict(action='body'))];run=self.create(nodes=nodes);self.model_completed(run);self.step(run);audit=next(a for a in self.view(run)['attempts'] if a['node_id']=='audit');self.assertTrue(any(r['kind']=='candidate' for r in audit['output_refs']),'审核不得丢失其实际候选引用');self.step(run);human=self.waiting(run,'human');self.assertEqual(human['review']['after'],'模型返回的完整候选。');self.confirm(run,human);self.step(run);self.assertEqual(len(self.service.get(self.pid)['adoption_receipts']),1);self.assertEqual(len(self.f.calls),1)
    def test_saved_offline_memory_flow_and_local_queue_write_only_after_human(self):
        nodes=[node('read','reference',params=dict(max_chars=20000)),node('audit','offline_audit',['read'],'read',params=dict(**TASK,forbidden_literals=[])),node('memory','memory_proposal',['audit'],'audit',params=dict(index=0)),node('human','human',['memory'],'memory',params=dict(action='memory')),node('apply','apply',['human'],'human',params=dict(action='memory'))];run=self.create(nodes=nodes);self.start(run)
        for _ in range(4):self.step(run)
        human=self.waiting(run,'human');self.assertFalse(self.service.get(self.pid)['memories']);self.confirm(run,human);self.step(run);self.assertEqual(self.service.get(self.pid)['memories'][0]['text'],self.service.get(self.pid)['document']['chapters'][0]['content']);self.assertEqual(self.f.calls,[])
        local=[node('read','reference',params=dict(max_chars=1000)),node('manual','manual',['read'],params=dict(slot='instruction')),node('join','join',['read','manual'])];queued=self.create(nodes=local);self.engine.control(self.pid,queued['run_id'],'queue');deadline=time.monotonic()+15
        while time.monotonic()<deadline and self.view(queued)['status']!='completed':time.sleep(.02)
        self.assertEqual(self.view(queued)['status'],'completed');self.assertEqual(self.f.calls,[])
    def test_cancel_wins_at_existing_body_transaction_guard_not_only_before_step(self):
        run=self.create();self.model_completed(run);self.step(run);human=self.waiting(run,'human');self.confirm(run,human);reached=threading.Event();release=threading.Event();failures=[];original=self.f.engine.adopt
        def blocked(*args,**kwargs):reached.set();self.assertTrue(release.wait(3));return original(*args,**kwargs)
        def apply():
            try:self.step(run)
            except ValueError as e:failures.append(str(e))
        before=self.service.get(self.pid)['document']
        with patch.object(self.f.engine,'adopt',side_effect=blocked):
            worker=threading.Thread(target=apply);worker.start();self.assertTrue(reached.wait(2));self.engine.control(self.pid,run['run_id'],'cancel');release.set();worker.join(3)
        self.assertFalse(worker.is_alive());self.assertTrue(failures);self.assertEqual(self.service.get(self.pid)['document'],before);self.assertFalse(self.service.get(self.pid)['adoption_receipts'])
    def test_queue_confirmation_wakeup_not_lost_while_previous_worker_returns_waiting(self):
        run=self.create();reached=threading.Event();release=threading.Event();original=self.engine.step;blocked=[False]
        def held(*args,**kwargs):
            view=original(*args,**kwargs)
            if not blocked[0] and any(a['status']=='waiting_request' for a in view['attempts']):blocked[0]=True;reached.set();self.assertTrue(release.wait(8))
            return view
        with patch.object(self.engine,'step',side_effect=held):
            self.engine.control(self.pid,run['run_id'],'queue');self.assertTrue(reached.wait(8));a=self.waiting(run,'model_rewrite');self.confirm(run,a);release.set();deadline=time.monotonic()+12
            while time.monotonic()<deadline:
                view=self.view(run)
                if any(a['status']=='waiting_human' for a in view['attempts']):break
                time.sleep(.05)
        self.assertTrue(any(a['status']=='waiting_human' for a in self.view(run)['attempts']),'确认发生在旧worker退出前，后继仍必须消费已完成候选');self.assertEqual(len(self.f.calls),1);self.assertFalse(self.service.get(self.pid)['adoption_receipts'])
    def test_search_node_feedback_consumed_and_target_edit_rejects_old_human_diff(self):
        nodes=[node('search','search',params=dict(max_results=5)),node('rewrite','model_rewrite',['search'],'search','writer',TASK),node('human','human',['rewrite'],'rewrite',params=dict(action='body')),node('apply','apply',['human'],'human',params=dict(action='body'))];run=self.create(nodes=nodes);self.start(run);self.step(run);self.step(run);a=self.waiting(run,'model_rewrite');self.confirm(run,a);self.f.engine.wait_idle(5);self.step(run);self.step(run);human=self.waiting(run,'human');sent=json.loads(self.f.calls[0]['body']['messages'][1]['content']);self.assertIn('灯塔',sent['context']);self.assertIn('灯塔照亮港口潮水',sent['context']);self.f.save('save_chapter',chapter_id=self.f.cid,content='作者在候选后明确修改的正文');before=rows(self.f.db)
        with self.assertRaises(ValueError):self.confirm(run,human)
        self.assertEqual(rows(self.f.db),before);self.assertFalse(self.service.get(self.pid)['adoption_receipts'])
    def test_saved_model_audit_memory_proposal_uses_shared_model_confirmation(self):
        profile=dict(role='auditor',adapter_id='chat-completions-http-v1',connection_id='gg',model_id='author-selected-model',temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=True,prompt_version='review-json-1');nodes=[node('read','reference',params=dict(max_chars=20000)),node('audit','model_audit',['read'],'read','auditor',TASK),node('memory','memory_proposal',['audit'],'audit',params=dict(index=0)),node('human','human',['memory'],'memory',params=dict(action='memory')),node('apply','apply',['human'],'human',params=dict(action='memory'))];run=self.create(nodes=nodes,roles=[profile]);self.f.mode='analysis';self.start(run);self.step(run);self.step(run);a=self.waiting(run,'model_audit');self.confirm(run,a);self.f.engine.wait_idle(5);self.step(run);self.step(run);self.step(run);human=self.waiting(run,'human');self.assertFalse(self.service.get(self.pid)['memories']);self.confirm(run,human);self.step(run);self.assertEqual(len(self.service.get(self.pid)['model_proposal_receipts']),1);self.assertEqual(len(self.service.get(self.pid)['memories']),1);self.assertEqual(len(self.f.calls),1)
    def test_retry_downstream_consumes_selected_new_attempt_and_preserves_failed_result(self):
        nodes=[node('read','reference',params=dict(max_chars=20000)),node('rewrite','model_rewrite',['read'],'read','writer',TASK),node('audit','offline_audit',['rewrite'],'rewrite',params=dict(**TASK,forbidden_literals=['完整候选']))];run=self.create(nodes=nodes);self.f.mode='429';self.model_completed(run);old=self.view(run)['attempts'][-1];self.assertEqual(old['status'],'failed');self.f.mode='success';self.engine.retry(self.pid,run['run_id'],'rewrite');new=self.waiting(run,'model_rewrite');self.confirm(run,new);self.f.engine.wait_idle(5);self.step(run);self.step(run);view=self.view(run);audit=next(a for a in view['attempts'] if a['node_id']=='audit');self.assertIn(new['id'],audit['input_attempt_ids']);self.assertNotIn(old['id'],audit['input_attempt_ids']);self.assertEqual(audit['audit']['findings'][0]['evidence'][0]['task_id'],new['task_id']);self.assertNotEqual(new['task_id'],old['task_id']);self.assertEqual(view['external_calls'],2);self.assertEqual(len(self.f.calls),2);self.assertTrue(any(a['id']==old['id'] and a['status']=='failed' for a in view['attempts']))
    def test_timeout_preserves_external_attempt_and_token_reservation(self):
        nodes=rewrite_nodes();nodes[1]['parameters']=dict(TASK,timeout_ms=120);run=self.create(nodes=nodes);self.f.mode='slow';self.start(run);self.step(run);self.step(run);a=self.waiting(run,'model_rewrite');self.confirm(run,a);self.f.engine.wait_idle(3);self.step(run);view=self.view(run);self.assertEqual(view['status'],'failed');self.assertEqual(view['external_calls'],1);self.assertEqual(view['reserved_output_tokens'],512);self.assertFalse(self.service.get(self.pid)['adoption_receipts'])

if __name__=='__main__':unittest.main()
