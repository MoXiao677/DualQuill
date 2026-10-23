"""本地coordinator真实仓储闭环、竞争、幂等与原始V1/V2兼容。"""
from contextlib import closing
from copy import deepcopy
from importlib import util,import_module
import json,sqlite3,sys,tempfile,threading,time,unittest
from contextlib import contextmanager
from unittest.mock import patch
from pathlib import Path
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src')]
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository,ConflictError
from novel_writer.application.task_protocol import AdapterRegistry,LocalProtocolAdapter,AdapterResult
from novel_writer.domain.tasks import digest
FROZEN=json.loads((ROOT/'tests/fixtures/s4a_legacy.json').read_text(encoding='utf8'))

def rows(path):
    with closing(sqlite3.connect(path)) as db:return {t:[list(r) for r in db.execute('SELECT * FROM '+t+' ORDER BY 1,2')] for t in ('projects','project_snapshots','skills')}

class TaskTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(util.find_spec('novel_writer.application.tasks'),'缺少真实共享持久coordinator')
        self.mod=import_module('novel_writer.application.tasks');self.temp=tempfile.TemporaryDirectory(prefix='novel-s4a-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=self.root/'fictional.sqlite3';self.db.write_bytes(bytes.fromhex(FROZEN['v2']['database_hex']))
        self.service=NovelService(SQLiteRepository(self.db));self.engines=[];self.engine=self.coordinator(LocalProtocolAdapter(delay_seconds=0))
        self.addCleanup(self.close)
    def close(self):
        for engine in self.engines:engine.close()
    def coordinator(self,adapter=None):
        registry=AdapterRegistry()
        if adapter is not None:registry.register('rewrite_chapter',adapter)
        engine=self.mod.TaskCoordinator(self.service,registry);self.engines.append(engine);return engine
    def prepare(self,engine=None,**changes):
        state=self.service.get('p1');options=dict(chapter_id='p1-c5',budget_chars=2000,include_current_plan=True)
        preview=self.service.preview_context('p1',options)
        request=dict(request_id=str(uuid4()),chapter_id='p1-c5',task_type='rewrite_chapter',context_options=options,
            context_sha256=digest(preview['context_text']),parameters=dict(instruction='整章重写',max_output_chars=10000,timeout_ms=1000),expected_revision=state['revision'])
        request.update(changes);return (engine or self.engine).prepare('p1',request),request
    def wait(self,engine,task_id):
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            view=engine.describe('p1',task_id)
            if view['task']['status'] not in ('pending','running'):return view
            time.sleep(.01)
        self.fail('任务未在独立上限内结束')
    def succeed(self):
        prepared,_=self.prepare();identifier=prepared['task']['id'];self.engine.start('p1',identifier)
        view=self.wait(self.engine,identifier);self.assertEqual(view['task']['status'],'succeeded');return view
    def adopt(self,view,identity=None,**changes):
        request=dict(candidate_id=view['candidates'][0]['id'],adoption_id=identity or str(uuid4()),
            expected_revision=self.service.get('p1')['revision'],authorize_confirmed=False)
        request.update(changes);return self.engine.adopt('p1',view['task']['id'],request),request
    def save(self,action,**values):
        state=self.service.get('p1');return self.service.execute('p1',action,values,expected_revision=state['revision'])
    def test_prepare_freezes_exact_saved_material_and_replay_identity(self):
        before=self.service.get('p1');prepared,request=self.prepare();task=prepared['task']
        self.assertEqual(task['frozen']['target']['text'],before['document']['chapters'][4]['content'])
        self.assertEqual(task['frozen']['source_revision'],before['revision']);self.assertEqual(task['status'],'pending')
        snapshot=rows(self.db);again=self.engine.prepare('p1',request)
        self.assertEqual(again['task']['id'],task['id']);self.assertEqual(rows(self.db),snapshot)
        changed=deepcopy(request);changed['parameters']['instruction']='换输入'
        with self.assertRaises(ValueError):self.engine.prepare('p1',changed)
        self.save('save_chapter',chapter_id='p1-c5',content='运行时新正文')
        self.engine.start('p1',task['id']);result=self.wait(self.engine,task['id'])
        self.assertIn(before['document']['chapters'][4]['content'],result['candidates'][0]['output_text'])
        self.assertNotIn('运行时新正文',result['candidates'][0]['output_text'])
    def test_default_disabled_unknown_parameters_and_crossbook_never_execute(self):
        engine=self.coordinator();prepared,_=self.prepare(engine)
        before=rows(self.db)
        with self.assertRaises(ValueError):engine.start('p1',prepared['task']['id'])
        with self.assertRaises(ValueError):engine.start('p2',prepared['task']['id'])
        self.assertEqual(rows(self.db),before)
        with self.assertRaises(ValueError):self.prepare(parameters=dict(instruction='x',max_output_chars=500,timeout_ms=100,fixture_output='fake'))
        with self.assertRaises(ValueError):self.prepare(task_type='arbitrary_url')
    def test_accept_is_atomic_idempotent_after_lost_response_restart_and_unrelated_save(self):
        view=self.succeed();self.save('save_chapter',chapter_id='p1-c20',content='无关后续章更新')
        before=self.service.get('p1');identity=str(uuid4());receipt,request=self.adopt(view,identity)
        after=self.service.get('p1');self.assertEqual(len(after['document']['versions']),len(before['document']['versions'])+1)
        self.assertEqual(after['document']['chapters'][4]['content'],view['candidates'][0]['output_text'])
        self.assertEqual(after['document']['versions'][:-1],before['document']['versions'])
        new_engine=self.coordinator();replayed=new_engine.adopt('p1',view['task']['id'],request)
        self.assertEqual(replayed,receipt);self.assertEqual(self.service.get('p1'),after)
        self.save('save_worldbuilding',content='采纳后无关保存')
        self.assertEqual(new_engine.adopt('p1',view['task']['id'],request),receipt)
        with self.assertRaises(ValueError):new_engine.adopt('p1',view['task']['id'],dict(request,candidate_id='another-candidate'))
    def test_related_plan_or_target_change_rejects_stale_candidate_without_receipt(self):
        for action,fields in [('save_chapter_outline',dict(chapter_id='p1-c5',objective='相关计划更新')),
                              ('save_chapter',dict(chapter_id='p1-c5',content='目标已变'))]:
            view=self.succeed();self.save(action,**fields);before=rows(self.db)
            with self.subTest(action=action),self.assertRaises(ValueError):self.adopt(view)
            self.assertEqual(rows(self.db),before)
    def test_confirmed_chapter_requires_authorization_and_memory_is_not_reconfirmed(self):
        self.save('save_chapter',chapter_id='p1-c5',status='confirmed')
        memory=self.service.get('p1')['memories'][0]
        self.save('review_memory',memory_id=memory['id'],confirmed=True)
        view=self.succeed();before=rows(self.db)
        with self.assertRaises(ValueError):self.adopt(view)
        self.assertEqual(rows(self.db),before)
        self.adopt(view,authorize_confirmed=True)
        record=self.service.memory_records('p1')[0];self.assertTrue(record['confirmed']);self.assertTrue(record['outdated'])
    def test_failed_snapshot_insert_rolls_back_body_event_receipt_then_retries_once(self):
        view=self.succeed();before=rows(self.db);state=self.service.get('p1');identity=str(uuid4())
        with closing(sqlite3.connect(self.db)) as db,db:
            db.execute("CREATE TRIGGER reject_adoption BEFORE INSERT ON project_snapshots WHEN NEW.project_id='p1' AND NEW.revision="+str(state['revision']+1)+" BEGIN SELECT RAISE(ABORT,'fictional disk full'); END")
        with self.assertRaises((ValueError,sqlite3.Error)):self.adopt(view,identity)
        self.assertEqual(rows(self.db),before)
        with closing(sqlite3.connect(self.db)) as db,db:db.execute('DROP TRIGGER reject_adoption')
        self.adopt(view,identity);self.assertEqual(len(self.service.get('p1')['adoption_receipts']),1)
    def test_cancel_wins_over_ignored_token_late_result_and_does_not_make_candidate(self):
        entered=threading.Event();release=threading.Event()
        class Paused:
            adapter_id='local-protocol-demo-v1'
            def run(this,call,token):
                entered.set();release.wait(2)
                return AdapterResult(task_id=call.task_id,attempt_id=call.attempt_id,capability=call.capability,output_text='迟到正文',complete=True)
        engine=self.coordinator(Paused());prepared,_=self.prepare(engine);identifier=prepared['task']['id'];engine.start('p1',identifier)
        try:
            self.assertTrue(entered.wait(1));cancelled=engine.cancel('p1',identifier);self.assertTrue(cancelled['accepted'])
        finally:release.set()
        engine.wait_idle(2);view=engine.describe('p1',identifier)
        self.assertEqual(view['task']['status'],'cancelled');self.assertEqual(view['candidates'],[])
    def test_timeout_wrong_result_and_adapter_exception_are_failed_not_candidates(self):
        class Raises:
            adapter_id='local-protocol-demo-v1'
            def run(this,call,token):raise RuntimeError('SHOULD_NOT_LEAK')
        for adapter,timeout in ((Raises(),1000),(LocalProtocolAdapter(delay_seconds=.3),100)):
            engine=self.coordinator(adapter);prepared,_=self.prepare(engine,parameters=dict(instruction='x',max_output_chars=1000,timeout_ms=timeout));identifier=prepared['task']['id']
            engine.start('p1',identifier);view=self.wait(engine,identifier)
            self.assertEqual(view['task']['status'],'failed');self.assertEqual(view['candidates'],[]);self.assertNotIn('SHOULD_NOT_LEAK',json.dumps(view))
    def test_restart_read_is_pure_and_only_explicit_recovery_interrupts(self):
        entered=threading.Event();release=threading.Event()
        class Paused:
            adapter_id='local-protocol-demo-v1'
            def run(this,call,token):entered.set();release.wait(2);return AdapterResult(task_id=call.task_id,attempt_id=call.attempt_id,capability=call.capability,output_text='旧会话迟到',complete=True)
        old=self.coordinator(Paused());prepared,_=self.prepare(old);identifier=prepared['task']['id'];old.start('p1',identifier)
        self.assertTrue(entered.wait(1));new=self.coordinator();before=self.db.read_bytes()
        shown=new.describe('p1',identifier);self.assertEqual(shown['display_status'],'interrupted');self.assertEqual(self.db.read_bytes(),before)
        try:new.recover('p1')
        finally:release.set()
        old.wait_idle(2);view=new.describe('p1',identifier);self.assertEqual(view['task']['status'],'interrupted');self.assertEqual(view['candidates'],[])
    def test_v3_backup_restore_and_copy_map_all_ids_preserve_text_and_do_not_run(self):
        from novel_writer.application.backups import create_backup,restore_backup
        from novel_writer.application.migrations import migrate
        view=self.succeed();receipt,_=self.adopt(view)
        package=self.root/'tasks.nwbak';manifest=create_backup(self.db,package);self.assertGreaterEqual(manifest['backup_format_version'],51)
        restored=Path(restore_backup(package,self.root/'restored')['database_path']);self.assertEqual(rows(restored),rows(self.db))
        target=self.root/'target.sqlite3';target.write_bytes(bytes.fromhex(FROZEN['v1']['database_hex']))
        result=migrate(package,target,operation_id=str(uuid4()));project=next(p['new_id'] for p in result['projects'] if p['old_id']=='p1')
        copied=NovelService(SQLiteRepository(target)).get(project);task=copied['generation_tasks'][0]
        self.assertNotEqual(task['id'],view['task']['id']);self.assertEqual(task['frozen']['context_text'],view['task']['frozen']['context_text'])
        self.assertEqual(copied['generation_candidates'][0]['output_text'],view['candidates'][0]['output_text'])
        self.assertEqual(copied['adoption_receipts'][0]['applied_revision'],receipt['applied_revision'])
        mapping={(i['kind'],i['old_id']):i['new_id'] for i in result['id_map'] if i['old_project_id']=='p1'}
        self.assertEqual(copied['adoption_receipts'][0]['version_after'],mapping['version',receipt['version_after']])
    def test_old_v1_v2_open_backup_restore_and_json_unchanged_or_honestly_rejected(self):
        from novel_writer.application.backups import create_backup,restore_backup
        from novel_writer.application.migrations import migrate
        for version in ('v1','v2'):
            frozen=FROZEN[version];source=self.root/(version+'.sqlite3');source.write_bytes(bytes.fromhex(frozen['database_hex']));original=source.read_bytes()
            state=NovelService(SQLiteRepository(source)).get('p1');self.assertEqual(source.read_bytes(),original);self.assertEqual(rows(source),frozen['rows'])
            package=self.root/(version+'.nwbak');package.write_bytes(bytes.fromhex(frozen['package_hex']))
            restored=Path(restore_backup(package,self.root/(version+'-restored'))['database_path']);self.assertEqual(rows(restored),frozen['rows'])
            again=create_backup(source,self.root/(version+'-again.nwbak'));self.assertEqual(again['backup_format_version'],51)
            self.assertNotIn('generation_tasks',state)

    def test_pending_memory_and_global_skill_dependencies_copy_without_execution_or_text_rewrite(self):
        from novel_writer.storage.skills_repository import SkillsRepository
        from novel_writer.application.backups import create_backup,restore_backup
        from novel_writer.application.migrations import migrate
        skill=dict(id='global-s4-skill',name='明确选中资料',description='本地夹具',imported_at='2020-01-01T00:00:00+00:00',primary_path='SKILL.md',
            files=[dict(path='SKILL.md',content='资料原文包含旧ID p1-c5，不能替换。')])
        SkillsRepository(self.db).add(skill)
        search=self.service.search_local('p1',dict(query='资料原文',chapter_id='p1-c5',scopes=['skills'],skill_ids=[skill['id']]))
        options=dict(chapter_id='p1-c5',include_memories=True,include_search_results=True,search_selections=[search['hits'][0]['selection']],budget_chars=4000)
        preview=self.service.preview_context('p1',options)
        prepared,_=self.prepare(context_options=options,context_sha256=digest(preview['context_text']))
        frozen=prepared['task']['frozen'];self.assertEqual({d['kind'] for d in frozen['dependencies']} & {'memory','skill'},{'memory','skill'})
        package=self.root/'mixed.nwbak';create_backup(self.db,package)
        restored=Path(restore_backup(package,self.root/'mixed-restored')['database_path'])
        self.assertEqual(rows(restored),rows(self.db));self.assertEqual(NovelService(SQLiteRepository(restored)).get('p1')['generation_tasks'][0]['status'],'pending')
        target=self.root/'mixed-target.sqlite3';target.write_bytes(bytes.fromhex(FROZEN['v1']['database_hex']))
        conflict=deepcopy(skill);conflict['files'][0]['content']='已有目标的不同资料';SkillsRepository(target).add(conflict)
        result=migrate(package,target,operation_id=str(uuid4()));new=next(p['new_id'] for p in result['projects'] if p['old_id']=='p1')
        copied=NovelService(SQLiteRepository(target)).get(new);task=copied['generation_tasks'][0]
        self.assertEqual(task['status'],'pending');self.assertEqual(copied['generation_candidates'],[])
        self.assertEqual(task['frozen']['context_text'],frozen['context_text']);self.assertIn('p1-c5',task['frozen']['context_text'])
        mapped_skill=next(s['new_id'] for s in result['skills'] if s['old_id']==skill['id']);self.assertNotEqual(mapped_skill,skill['id'])
        self.assertEqual(next(d['entity_id'] for d in task['frozen']['dependencies'] if d['kind']=='skill'),mapped_skill)
        self.assertEqual(task['frozen']['skill_snapshots'][0]['id'],mapped_skill)
        self.assertEqual(next(d['entity_id'] for d in task['frozen']['dependencies'] if d['kind']=='memory'),copied['memories'][0]['id'])

    def test_wait_idle_includes_started_timeout_callback_sqlite_connection(self):
        timer_open=threading.Event();release_timer=threading.Event();timer_closed=threading.Event();wait_entered=threading.Event();wait_done=threading.Event()
        engine=self.coordinator(LocalProtocolAdapter(delay_seconds=.3));original=self.service.repository._connection;timers=[]
        @contextmanager
        def observed_connection():
            is_timer=isinstance(threading.current_thread(),threading.Timer)
            try:
                with original() as connection:
                    if is_timer:
                        timers.append(threading.current_thread());timer_open.set();release_timer.wait(3)
                    yield connection
            finally:
                if is_timer:timer_closed.set()
        prepared,_=self.prepare(engine,parameters=dict(instruction='超时生命周期',max_output_chars=1000,timeout_ms=100));identifier=prepared['task']['id']
        observer=None
        with patch.object(self.service.repository,'_connection',side_effect=observed_connection):
            engine.start('p1',identifier)
            try:
                self.assertTrue(timer_open.wait(1),'真实Timer未进入SQLite连接')
                self.wait(engine,identifier)
                def observe_wait():wait_entered.set();engine.wait_idle(1);wait_done.set()
                observer=threading.Thread(target=observe_wait);observer.start();self.assertTrue(wait_entered.wait(1))
                self.assertFalse(wait_done.wait(.05),'worker结束不能早于仍持有SQLite连接的超时回调')
            finally:
                release_timer.set()
                if observer:observer.join(2)
                for timer in timers:timer.join(2)
                engine.wait_idle(2)
        self.assertTrue(timer_closed.is_set());self.assertTrue(wait_done.is_set())

if __name__=='__main__':unittest.main()
