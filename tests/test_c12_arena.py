"""C12 real coordinators and disk persistence; fictional loopback only."""
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
import json,sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
import test_s6a_comparison as fixture
import test_chapter_planning as planning_fixture
from novel_writer.application.comparisons import ComparisonCoordinator,public_workspace
from novel_writer.domain.tasks import digest
from novel_writer.domain.experiments import common_instruction
from novel_writer.storage.sqlite_repository import SQLiteRepository
from novel_writer.application.service import NovelService
from novel_writer.application.backups import create_backup,restore_backup
from novel_writer.application.migrations import migrate
from novel_writer.application.skill_import import SkillLibrary

class ArenaTests(unittest.TestCase):
    def test_style_trial_result_projection_retains_persisted_identity(self):
        from novel_writer.domain.experiments import arena_records
        identity,task_id=str(uuid4()),str(uuid4())
        state=dict(style_trial_results=[dict(id=identity,task_id=task_id,usage=dict(prompt_tokens=1,completion_tokens=2,total_tokens=3),reported_model='fiction-trial')])
        _,_,results=arena_records(state)
        self.assertEqual(results,[dict(id=identity,task_id=task_id,response=dict(usage=state['style_trial_results'][0]['usage'],reported_model='fiction-trial'))])
    def setUp(self):
        self.f=fixture.ComparisonTests('test_blind_scores_reveal_reopen_winner_only_opens_candidate_and_preset');self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.engine=self.f.engine;self.service=self.f.service;self.pid=self.f.pid
    def request(self,kind='rewrite_chapter',count=3):
        _,r=self.f.create(return_request=True);r.update(task_kind=kind,planning_options=None,budget=dict(max_calls=count,max_output_tokens=count*512))
        r['profiles']=[dict(r['profiles'][0],temperature=.1+i*.1,prompt_version='review-json-1' if kind=='audit_chapter' else 'rewrite-1') for i in range(count)]
        return r
    def run_all(self,identifier):return self.f.execute(identifier)
    def scores(self,identifier):
        for c in self.engine.blind(self.pid,identifier)['candidates']:self.f.score(identifier,c['side'],4 if c['status']=='succeeded' else None)
    def clone(self,root,db,service,pid):
        SkillLibrary(db);path=root/'arena.nwbak';manifest=create_backup(db,path);self.assertEqual(manifest['backup_format_version'],51)
        restored=restore_backup(path,root/'restored');self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(pid),service.get(pid))
        target=root/'copy.sqlite3';SQLiteRepository(target);SkillLibrary(target);copied=migrate(path,target,operation_id=str(uuid4()));copy_service=NovelService(SQLiteRepository(target));return copy_service,copied['projects'][0]['new_id']
    def test_three_configs_same_frozen_source_blind_idempotency_reopen_and_no_body_write(self):
        request=self.request();before=self.service.get(self.pid)['document'];created=self.engine.create(self.pid,request);identifier=created['experiment_id']
        self.assertEqual(self.engine.create(self.pid,request),created);tasks=self.service.get(self.pid)['generation_tasks'];self.assertEqual(len(tasks),3)
        for key in ('target','dependencies','context_text','source_revision'):self.assertTrue(all(t['frozen'][key]==tasks[0]['frozen'][key] for t in tasks))
        blind=self.run_all(identifier);self.assertEqual({c['side'] for c in blind['candidates']},set('ABC'));raw=json.dumps(blind)
        for t in tasks:self.assertNotIn(t['id'],raw);self.assertNotIn(t['frozen']['parameters']['binding']['model_id'],raw)
        self.assertEqual(public_workspace(self.service.get(self.pid))['generation_tasks'],[])
        self.f.score(identifier,'A');self.f.score(identifier,'B')
        with self.assertRaises(ValueError):self.f.reveal(identifier)
        score=dict(operation_id=str(uuid4()),side='C',rating=5,outcome='scored',notes='当前样本',expected_revision=self.service.get(self.pid)['revision'])
        first=self.engine.score(self.pid,identifier,score);self.assertEqual(self.engine.score(self.pid,identifier,score),first)
        self.f.reveal(identifier);revision=self.service.get(self.pid)['revision'];self.f.reveal(identifier);self.assertEqual(self.service.get(self.pid)['revision'],revision)
        choice=dict(operation_id=str(uuid4()),side='C',action='open_candidate',name='',expected_revision=revision);result=self.engine.choose(self.pid,identifier,choice);self.assertEqual(self.engine.choose(self.pid,identifier,choice),result)
        self.assertEqual(self.service.get(self.pid)['document'],before);reopen=ComparisonCoordinator(NovelService(SQLiteRepository(self.f.f.db)),self.f.f.engine);self.assertTrue(reopen.blind(self.pid,identifier)['revealed'])
        copied,pid=self.clone(self.f.f.root,self.f.f.db,self.service,self.pid);self.assertEqual(len(copied.get(pid)['comparison_scores']),3);self.assertEqual(len(self.f.f.calls),3)
    def test_actual_usage_unknown_cost_per_request_confirmation_and_budget_rejection(self):
        request=self.request();bad=deepcopy(request);bad['budget']['max_calls']=2
        with self.assertRaises(ValueError):self.engine.create(self.pid,bad)
        bad=deepcopy(request);bad['budget']['max_output_tokens']=1535
        with self.assertRaises(ValueError):self.engine.create(self.pid,bad)
        created=self.engine.create(self.pid,request);identifier=created['experiment_id'];setup=self.engine.setup(self.pid,identifier);c=setup['configurations'][0]
        self.assertIsNone(c['metrics']['input_tokens']);self.assertIsNone(c['metrics']['actual_cost']);self.assertEqual(c['metrics']['output_token_limit'],512)
        for confirmation in ({},{'confirm_external':False,'request_sha256':c['request_sha256']},{'confirm_external':True,'request_sha256':'0'*64}):
            with self.assertRaises(ValueError):self.engine.execute(self.pid,identifier,c['configuration_id'],confirmation)
        self.assertEqual(self.f.f.calls,[]);blind=self.run_all(identifier)
        for c in blind['candidates']:self.assertEqual(c['usage'],dict(prompt_tokens=17,completion_tokens=9,total_tokens=26));self.assertIsNone(c['cost']);self.assertEqual(c['usage_source'],'provider_reported')
    def test_failure_cancel_and_missing_usage_are_never_zero_scores(self):
        made=self.engine.create(self.pid,self.request());identifier=made['experiment_id'];setup=self.engine.setup(self.pid,identifier)
        self.engine.cancel(self.pid,identifier,setup['configurations'][0]['configuration_id']);self.f.f.mode='429'
        for c in setup['configurations'][1:]:
            self.engine.execute(self.pid,identifier,c['configuration_id'],dict(confirm_external=True,request_sha256=c['request_sha256']));self.f.f.engine.wait_idle(5);self.f.f.mode='unknown_usage'
        blind=self.engine.blind(self.pid,identifier);self.assertEqual({c['status'] for c in blind['candidates']},{'failed','cancelled','succeeded'})
        for c in blind['candidates']:
            if c['status']!='succeeded':
                with self.assertRaises(ValueError):self.f.score(identifier,c['side'],0)
        self.scores(identifier);self.f.reveal(identifier)
        self.assertEqual([c['cost'] for c in blind['candidates']],[None]*3);self.assertTrue(all(c['usage']['total_tokens'] is None for c in blind['candidates']))
    def test_audit_three_configs_strict_evidence_report_scores_choice_and_copy(self):
        self.f.f.mode='analysis';made=self.engine.create(self.pid,self.request('audit_chapter'));identifier=made['experiment_id'];before=self.service.get(self.pid)['document'];blind=self.run_all(identifier)
        self.assertTrue(all(c['status']=='succeeded' for c in blind['candidates']),blind);self.assertTrue(all('model_opinion' in c['text'] for c in blind['candidates']))
        self.assertEqual(public_workspace(self.service.get(self.pid))['model_reports'],[]);self.scores(identifier);self.f.reveal(identifier)
        self.engine.choose(self.pid,identifier,dict(operation_id=str(uuid4()),side='B',action='open_candidate',name='',expected_revision=self.service.get(self.pid)['revision']))
        self.assertEqual(self.service.get(self.pid)['document'],before);copied,pid=self.clone(self.f.f.root,self.f.f.db,self.service,self.pid);self.assertEqual(len(copied.get(pid)['comparison_scores']),3)
    def test_changed_source_blocks_send_and_reopen_never_sends(self):
        made=self.engine.create(self.pid,self.request());identifier=made['experiment_id'];setup=self.engine.setup(self.pid,identifier);self.f.f.save('save_chapter',chapter_id=self.f.f.cid,content='作者更改虚构正文')
        c=setup['configurations'][0]
        with self.assertRaises(ValueError):self.engine.execute(self.pid,identifier,c['configuration_id'],dict(confirm_external=True,request_sha256=c['request_sha256']))
        self.assertTrue(ComparisonCoordinator(self.service,self.f.f.engine).blind(self.pid,identifier)['source_changed']);self.assertEqual(self.f.f.calls,[])
    def test_eight_config_boundary_incompatible_prompt_and_atomic_rollback(self):
        r=self.request(count=8);made=self.engine.create(self.pid,r);self.assertEqual(len(self.engine.setup(self.pid,made['experiment_id'])['configurations']),8)
        for count in (1,9):
            bad=self.request(count=count)
            with self.assertRaises(ValueError):self.engine.create(self.pid,bad)
        bad=self.request('audit_chapter');bad['profiles'][-1]['prompt_version']='rewrite-1';before=self.service.get(self.pid)
        with self.assertRaises(ValueError):self.engine.create(self.pid,bad)
        self.assertEqual(self.service.get(self.pid),before);self.assertEqual(self.f.f.calls,[])
    def test_manual_prices_are_sourced_estimates_revealed_only_after_scores_never_actual_bills(self):
        r=self.request();quote=dict(input_per_million=1.0,output_per_million=2.0,currency='USD',source='虚构测试手工价格，非真实报价');r['price_quotes']=[quote,None,None]
        made=self.engine.create(self.pid,r);identifier=made['experiment_id'];self.assertEqual(self.engine.setup(self.pid,identifier)['configurations'][0]['metrics']['price_quote'],quote)
        blind=self.run_all(identifier);self.assertNotIn('cost_estimate',json.dumps(blind));self.assertNotIn(quote['source'],json.dumps(blind));self.scores(identifier);revealed=self.f.reveal(identifier)
        estimates=[c['cost_estimate'] for c in revealed['candidates']];known=next(e for e in estimates if e['status']=='manual_usage_estimate');self.assertAlmostEqual(known['amount'],35/1_000_000);self.assertFalse(known['verified']);self.assertTrue(all(c['cost'] is None for c in revealed['candidates']))
        for value in (-1,float('inf'),float('nan')):
            bad=self.request();bad['price_quotes']=[dict(quote,input_per_million=value),None,None]
            with self.assertRaises(ValueError):self.engine.create(self.pid,bad)
    def test_pending_restore_copy_requires_fresh_confirmation_and_grants_no_adoption(self):
        made=self.engine.create(self.pid,self.request());copied,pid=self.clone(self.f.f.root,self.f.f.db,self.service,self.pid)
        from novel_writer.application.tasks import TaskCoordinator
        from novel_writer.application.task_protocol import AdapterRegistry
        shared=TaskCoordinator(copied,self.f.f.engine.registry);self.addCleanup(shared.close);engine=ComparisonCoordinator(copied,shared);e=copied.get(pid)['comparison_experiments'][0]
        self.assertEqual(copied.get(pid)['comparison_choices'],[]);self.assertEqual(copied.get(pid)['adoption_receipts'],[]);engine.blind(pid,e['id']);setup=engine.setup(pid,e['id']);self.assertEqual(len(setup['configurations']),3)
        with self.assertRaises(ValueError):engine.execute(pid,e['id'],setup['configurations'][0]['configuration_id'],{})
        with self.assertRaises(ValueError):engine.choose(pid,e['id'],dict(operation_id=str(uuid4()),side='A',action='open_candidate',name='',expected_revision=copied.get(pid)['revision']))
        self.assertEqual(self.f.f.calls,[])
    def test_audit_bad_quotes_fail_all_three_without_text_or_numeric_scores(self):
        self.f.f.mode='bad_quote';identifier=self.engine.create(self.pid,self.request('audit_chapter'))['experiment_id'];blind=self.run_all(identifier)
        self.assertTrue(all(c['status']=='failed' and c['text'] is None for c in blind['candidates']),blind)
        for c in blind['candidates']:
            with self.assertRaises(ValueError):self.f.score(identifier,c['side'],4)
        self.scores(identifier);self.f.reveal(identifier);self.assertTrue(all(s['rating'] is None and s['outcome']=='unscorable' for s in self.service.get(self.pid)['comparison_scores']))

class OutlineArenaTests(unittest.TestCase):
    def setUp(self):
        self.f=planning_fixture.ChapterPlanningTests('test_real_book_context_flows_idea_then_ordered_outline_without_body_or_entities');self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.engine=ComparisonCoordinator(self.f.service,self.f.shared,self.f.planning)
    def test_three_outline_configs_real_planning_validation_blind_restore_copy_no_permissions(self):
        f=self.f;outline=dict(core_idea='虚构封蜡',objective='作出选择',character_ids=[f.chid],scenes=[dict(order=1,summary='辨认封蜡',character_ids=[f.chid],location='灯塔',story_time='清晨')],story_time='第1天')
        with planning_fixture.supplier(output=json.dumps(outline,ensure_ascii=False)) as wire:
            connection=f.connection(wire);instruction='按本书资料规划';rubric='场景顺序与人物一致';source=f.source('outline',instruction=common_instruction(instruction,rubric));preview=f.planning.preview(f.pid,source);options=dict(chapter_id=f.cid,budget_chars=4000,include_writing_rules=True)
            request=dict(experiment_id=str(uuid4()),title='虚构三配置细纲',chapter_id=f.cid,context_options=options,context_sha256=preview['context_sha256'],instruction=instruction,rubric=rubric,parameters=dict(max_output_chars=12000,timeout_ms=3000),profiles=[dict(f.options(connection),temperature=.1+i*.1) for i in range(3)],expected_revision=f.service.get(f.pid)['revision'],task_kind='outline_chapter',planning_options=source,budget=dict(max_calls=3,max_output_tokens=2304))
            made=self.engine.create(f.pid,request);identifier=made['experiment_id'];before=f.service.get(f.pid)['document'];setup=self.engine.setup(f.pid,identifier)
            tasks=f.service.get(f.pid)['chapter_planning_tasks'];self.assertEqual(len(tasks),3);self.assertTrue(all(t['source_guard']==tasks[0]['source_guard'] for t in tasks));self.assertEqual(wire['calls'],[])
            for c in setup['configurations']:self.engine.execute(f.pid,identifier,c['configuration_id'],dict(confirm_external=True,request_sha256=c['request_sha256']));f.shared.wait_idle(5)
            blind=self.engine.blind(f.pid,identifier);self.assertTrue(all(c['status']=='succeeded' for c in blind['candidates']),blind);self.assertEqual(public_workspace(f.service.get(f.pid))['chapter_planning_tasks'],[])
            for c in blind['candidates']:self.engine.score(f.pid,identifier,dict(operation_id=str(uuid4()),side=c['side'],rating=4,outcome='scored',notes='虚构作者评分',expected_revision=f.service.get(f.pid)['revision']))
            self.engine.reveal(f.pid,identifier,dict(operation_id=str(uuid4()),expected_revision=f.service.get(f.pid)['revision']));self.engine.choose(f.pid,identifier,dict(operation_id=str(uuid4()),side='C',action='open_candidate',name='',expected_revision=f.service.get(f.pid)['revision']))
            self.assertEqual(f.service.get(f.pid)['document'],before);copied,pid=ArenaTests.clone(self,f.root,f.db,f.service,f.pid);self.assertEqual(len(copied.get(pid)['comparison_scores']),3);self.assertEqual(len(wire['calls']),3)

if __name__=='__main__':unittest.main()
