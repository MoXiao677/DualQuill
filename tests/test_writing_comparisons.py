"""C04 multi-candidate integration; fictional loopback, no real provider calls."""
import json,unittest
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
from novel_writer.application.comparisons import ComparisonCoordinator,public_workspace
from novel_writer.domain.experiments import arena_records
from novel_writer.storage.sqlite_repository import SQLiteRepository
from novel_writer.application.service import NovelService
from test_scene_expansion import SceneExpansionTests
from test_book_ai import supplier

class WritingComparisonTests(unittest.TestCase):
    def setUp(self):
        self.f=SceneExpansionTests('test_selection_replaces_exact_code_point_range_and_keeps_prefix_suffix_bytes');self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.arena=ComparisonCoordinator(self.f.service,self.f.shared);self.pid=self.f.pid
    def group(self,prepared,kind='scene_expansion'):
        request=dict(experiment_id=str(uuid4()),title='虚构逐段多候选',task_kind=kind,task_ids=[v['task']['id'] for v in prepared],expected_revision=self.f.service.get(self.pid)['revision'])
        made=self.arena.create(self.pid,request);return made['experiment_id'],request
    def execute_all(self,identifier):
        for c in self.arena.setup(self.pid,identifier)['configurations']:
            self.arena.execute(self.pid,identifier,c['configuration_id'],dict(confirm_external=True,request_sha256=c['request_sha256']));self.f.shared.wait_idle(6)
        return self.arena.blind(self.pid,identifier)
    def score_all(self,identifier):
        for c in self.arena.blind(self.pid,identifier)['candidates']:
            self.arena.score(self.pid,identifier,dict(operation_id=str(uuid4()),side=c['side'],rating=4 if c['status']=='succeeded' else None,outcome='scored' if c['status']=='succeeded' else 'unscorable',notes='虚构人工比较，非真实质量验证',expected_revision=self.f.service.get(self.pid)['revision']))
        return self.arena.reveal(self.pid,identifier,dict(operation_id=str(uuid4()),expected_revision=self.f.service.get(self.pid)['revision']))
    def choose(self,identifier,side):
        return self.arena.choose(self.pid,identifier,dict(operation_id=str(uuid4()),side=side,action='open_candidate',name='',expected_revision=self.f.service.get(self.pid)['revision']))
    def test_three_identical_inputs_distinct_tasks_scores_choice_correction_exact_adoption(self):
        f=self.f;start=f.original.index('门外');end=start+len('门外有雾。');source=f.source('selection',scene_order=None,selection_start=start,selection_end=end)
        with supplier(output='门外的潮声近了。') as wire:
            connection=f.connection(wire);prepared=[f.prepare(connection,source) for _ in range(3)];before=f.service.get(self.pid)['document'];identifier,request=self.group(prepared)
            self.assertEqual(len({v['task']['id'] for v in prepared}),3);self.assertEqual(len({v['task']['source_sha256'] for v in prepared}),1);self.assertEqual(wire['calls'],[])
            self.assertEqual(self.arena.create(self.pid,request)['experiment_id'],identifier);self.assertEqual(f.service.get(self.pid)['workspace_version']>=37,True)  # V50 记忆刷新排队会推高版本
            blind=self.execute_all(identifier);self.assertTrue(blind['ready']);self.assertEqual({v['side'] for v in blind['candidates']},{'A','B','C'});self.assertNotIn('identities',blind)
            public=json.dumps(public_workspace(f.service.get(self.pid)));self.assertTrue(all(v['task']['id'] not in public for v in prepared))
            revealed=self.score_all(identifier);choice=self.choose(identifier,'C');self.assertEqual(f.service.get(self.pid)['document'],before)
            detail=f.engine.describe(self.pid,choice['task_id']);original=deepcopy(detail['latest_candidate']);corrected=f.engine.correct(self.pid,dict(operation_id=str(uuid4()),task_id=choice['task_id'],candidate_id=original['id'],text='门外只剩潮声，脚步已经远去。'))
            self.assertEqual(self.arena.blind(self.pid,identifier)['candidates'],blind['candidates']);self.assertEqual(f.service.get(self.pid)['document'],before)
            review=f.review(corrected);self.assertEqual(review['selected_before'],f.original[start:end]);f.accept(corrected,review)
            after=f.service.get(self.pid)['document']['chapters'][0]['content'];self.assertEqual(after,f.original[:start]+corrected['latest_candidate']['text']+f.original[end:]);self.assertEqual(len(wire['calls']),3)
            self.assertEqual(next(v for v in f.service.get(self.pid)['scene_expansion_candidates'] if v['id']==original['id']),original)
    def test_failure_is_unscorable_and_never_selectable(self):
        f=self.f
        with supplier(output='') as wire:
            conn=f.connection(wire);identifier,_=self.group([f.prepare(conn),f.prepare(conn)]);blind=self.execute_all(identifier)
            self.assertTrue(blind['ready']);self.assertEqual({v['status'] for v in blind['candidates']},{'failed'})
            with self.assertRaises(ValueError):self.arena.score(self.pid,identifier,dict(operation_id=str(uuid4()),side='A',rating=1,outcome='scored',notes='',expected_revision=f.service.get(self.pid)['revision']))
            self.score_all(identifier)
            with self.assertRaises(ValueError):self.choose(identifier,'A')
            self.assertFalse(f.service.get(self.pid)['scene_expansion_candidates']);self.assertEqual(len(wire['calls']),2)
    def test_cancelled_late_response_never_enters_blind_candidates(self):
        f=self.f
        with supplier(output='迟到虚构文本') as wire:
            conn=f.connection(wire);identifier,_=self.group([f.prepare(conn),f.prepare(conn)]);setup=self.arena.setup(self.pid,identifier);first=setup['configurations'][0]
            f.engine.adapter.transport.capture_response=lambda _:self.arena.cancel(self.pid,identifier,first['configuration_id'])
            self.arena.execute(self.pid,identifier,first['configuration_id'],dict(confirm_external=True,request_sha256=first['request_sha256']));f.shared.wait_idle(6)
            self.arena.cancel(self.pid,identifier,setup['configurations'][1]['configuration_id']);blind=self.arena.blind(self.pid,identifier)
            self.assertEqual({v['status'] for v in blind['candidates']},{'cancelled'});self.assertTrue(all(v['text'] is None for v in blind['candidates']));self.assertEqual(len(f.service.get(self.pid)['scene_expansion_late_results']),1)
            self.assertFalse(f.service.get(self.pid)['scene_expansion_candidates']);self.assertEqual(len(wire['calls']),1)
    def test_different_range_and_changed_body_are_rejected(self):
        f=self.f
        with supplier(output='虚构') as wire:
            conn=f.connection(wire);a=f.prepare(conn,f.source('selection',scene_order=None,selection_start=0,selection_end=1));b=f.prepare(conn,f.source('selection',scene_order=None,selection_start=1,selection_end=2))
            with self.assertRaises(ValueError):self.group([a,b])
            identifier,_=self.group([a,f.prepare(conn,a['task']['source_options'])]);f.action('save_chapter',dict(chapter_id=f.cid,content=f.original+'作者修改'))
            with self.assertRaises(ValueError):self.execute_all(identifier)
            self.assertEqual(wire['calls'],[])
    def test_every_request_needs_its_own_confirmation_and_no_automatic_resend(self):
        f=self.f
        with supplier(output='虚构') as wire:
            conn=f.connection(wire);identifier,request=self.group([f.prepare(conn),f.prepare(conn)]);setup=self.arena.setup(self.pid,identifier);a,b=setup['configurations']
            with self.assertRaises(ValueError):self.arena.execute(self.pid,identifier,a['configuration_id'],dict(confirm_external=False,request_sha256=a['request_sha256']))
            self.assertEqual(wire['calls'],[]);self.arena.execute(self.pid,identifier,a['configuration_id'],dict(confirm_external=True,request_sha256=a['request_sha256']));f.shared.wait_idle(6)
            self.assertEqual(len(wire['calls']),1);self.assertFalse(self.arena.blind(self.pid,identifier)['ready'])
            self.assertEqual(self.arena.create(self.pid,request)['experiment_id'],identifier)
            self.assertEqual(len(wire['calls']),1)
            with self.assertRaises(ValueError):self.arena.execute(self.pid,identifier,a['configuration_id'],dict(confirm_external=True,request_sha256=a['request_sha256']))
            self.assertFalse(self.arena.setup(self.pid,identifier)['configurations'][1]['submitted'])
    def test_backup_restore_double_copy_preserves_groups_scores_choices_and_revokes_permissions(self):
        from novel_writer.application.backups import create_backup,restore_backup
        from novel_writer.application.migrations import migrate
        from novel_writer.application.skill_import import SkillLibrary
        from novel_writer.application.tasks import TaskCoordinator
        from novel_writer.application.task_protocol import AdapterRegistry
        from novel_writer.application.scene_expansion import SceneExpansionCoordinator
        f=self.f
        with supplier(output='虚构备份候选') as wire:
            conn=f.connection(wire);identifier,_=self.group([f.prepare(conn),f.prepare(conn)]);self.execute_all(identifier);self.score_all(identifier);choice=self.choose(identifier,'A')
            detail=f.engine.describe(self.pid,choice['task_id']);detail=f.engine.correct(self.pid,dict(operation_id=str(uuid4()),task_id=choice['task_id'],candidate_id=detail['latest_candidate']['id'],text='作者修正后的虚构备份候选'));f.accept(detail)
            pending,_=self.group([f.prepare(conn),f.prepare(conn)])
            state=f.service.get(self.pid);SkillLibrary(f.db);package=f.root/'c04.nwbak';self.assertGreaterEqual(create_backup(f.db,package)['backup_format_version'],51)
            restored=restore_backup(package,f.root/'restored');self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid),state)
            for index in range(2):
                target=f.root/('copy'+str(index)+'.sqlite3');SQLiteRepository(target);SkillLibrary(target);result=migrate(package,target,operation_id=str(uuid4()));pid=result['projects'][0]['new_id'];service=NovelService(SQLiteRepository(target));clone=service.get(pid)
                self.assertEqual(len(clone['comparison_experiments']),2);self.assertEqual(len(clone['comparison_scores']),2);self.assertEqual(len(clone['comparison_choices']),1)
                self.assertEqual(len(clone['scene_expansion_candidates']),3);self.assertEqual(len(clone['scene_expansion_reviews']),1);self.assertEqual(len(clone['scene_expansion_adoptions']),1);self.assertEqual(clone['document']['chapters'][0]['content'],state['document']['chapters'][0]['content'])
                parent=TaskCoordinator(service,AdapterRegistry());self.addCleanup(parent.close);SceneExpansionCoordinator(parent,f.providers,enabled=True);arena=ComparisonCoordinator(service,parent)
                e=clone['comparison_experiments'][1];setup=arena.setup(pid,e['id']);self.assertTrue(all(c['status']=='interrupted' for c in setup['configurations']))
                c=setup['configurations'][0]
                with self.assertRaises(ValueError):arena.execute(pid,e['id'],c['configuration_id'],dict(confirm_external=True,request_sha256=c['request_sha256']))
                package=f.root/('copy'+str(index)+'.nwbak');create_backup(target,package)
            self.assertEqual(len(wire['calls']),2)
    def test_six_cancelled_sides_require_all_evaluations_and_cannot_be_winners(self):
        f=self.f
        with supplier(output='不会发送') as wire:
            conn=f.connection(wire);identifier,_=self.group([f.prepare(conn) for _ in range(6)])
            for c in self.arena.setup(self.pid,identifier)['configurations']:self.arena.cancel(self.pid,identifier,c['configuration_id'])
            blind=self.arena.blind(self.pid,identifier);self.assertEqual({v['side'] for v in blind['candidates']},set('ABCDEF'));self.assertTrue(blind['ready'])
            with self.assertRaises(ValueError):self.arena.reveal(self.pid,identifier,dict(operation_id=str(uuid4()),expected_revision=f.service.get(self.pid)['revision']))
            self.assertEqual(len(self.score_all(identifier)['identities']),6)
            with self.assertRaises(ValueError):self.choose(identifier,'F')
            self.assertEqual(wire['calls'],[])
    def test_grouped_review_refuses_resaved_same_body_version(self):
        f=self.f
        with supplier(output='旧版本候选') as wire:
            conn=f.connection(wire);identifier,_=self.group([f.prepare(conn),f.prepare(conn)]);self.execute_all(identifier);self.score_all(identifier);choice=self.choose(identifier,'B');detail=f.engine.describe(self.pid,choice['task_id']);review=f.review(detail)
            f.action('save_chapter',dict(chapter_id=f.cid,content=f.original));before=f.service.get(self.pid)
            with self.assertRaises(ValueError):f.accept(detail,review)
            self.assertEqual(f.service.get(self.pid),before);self.assertEqual(len(wire['calls']),2)
    def test_group_reuse_and_identity_conflicts_leave_state_unchanged(self):
        f=self.f
        with supplier(output='不会发送') as wire:
            conn=f.connection(wire);prepared=[f.prepare(conn),f.prepare(conn)];identifier,request=self.group(prepared);before=f.service.get(self.pid)
            for invalid in (dict(request,title='不同名称'),dict(request,task_ids=list(reversed(request['task_ids']))),dict(request,experiment_id=str(uuid4())),dict(request,experiment_id=str(uuid4()),task_ids=[prepared[0]['task']['id']]*2)):
                with self.assertRaises(ValueError):self.arena.create(self.pid,invalid)
                self.assertEqual(f.service.get(self.pid),before)
            self.assertEqual(wire['calls'],[])
    def test_different_sampling_same_input_preserves_original_per_request_budget(self):
        from novel_writer.application.creation_presets import CreationPresets
        f=self.f
        with supplier(output='只允许第一条虚构请求') as wire:
            conn=f.connection(wire);presets=CreationPresets(f.service);profile=dict(step='draft',**{k:v for k,v in f.options(conn).items() if k!='prompt_version'})
            saved=presets.save(self.pid,dict(operation_id=str(uuid4()),preset_id=None,name='仅一次请求预算',settings=dict(steps=[profile],style_id=None,style_prompt='',manuscript_language='zh-CN',budget=dict(max_external_calls=1,max_reserved_output_tokens=768,risk_budget=1.0,allow_unknown_cost=True)),expected_revision=f.service.get(self.pid)['revision']))
            presets.choose(self.pid,dict(operation_id=str(uuid4()),version_id=saved['version_id'],confirmed=True,expected_revision=f.service.get(self.pid)['revision']))
            prepared=[f.prepare(conn),f.prepare(conn,model_options=dict(f.options(conn),temperature=.8))];identifier,_=self.group(prepared);a,b=self.arena.setup(self.pid,identifier)['configurations'];self.assertNotEqual(a['request_sha256'],b['request_sha256'])
            self.arena.execute(self.pid,identifier,a['configuration_id'],dict(confirm_external=True,request_sha256=a['request_sha256']));f.shared.wait_idle(6)
            for sha in (a['request_sha256'],b['request_sha256']):
                with self.assertRaises(ValueError):self.arena.execute(self.pid,identifier,b['configuration_id'],dict(confirm_external=True,request_sha256=sha))
            self.assertEqual(len(wire['calls']),1);self.assertFalse(self.arena.setup(self.pid,identifier)['configurations'][1]['submitted'])

if __name__=='__main__':unittest.main()
