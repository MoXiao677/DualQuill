import importlib,json,tempfile,unittest
from pathlib import Path
from uuid import uuid4

from novel_writer.application.chapter_planning import ChapterPlanningCoordinator
from novel_writer.application.chapter_writing import ChapterWriting
from novel_writer.application.console import ConsoleCoordinator
from novel_writer.application.creation_presets import CreationPresets
from novel_writer.application.provider_connections import ProviderConnections
from novel_writer.application.scene_expansion import SceneExpansionCoordinator
from novel_writer.application.service import NovelService
from novel_writer.application.task_protocol import AdapterRegistry
from novel_writer.application.tasks import TaskCoordinator
from novel_writer.storage.sqlite_repository import SQLiteRepository
from test_book_ai import supplier


class ConsoleRunTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='novel-console-runs-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=self.root/'fiction.sqlite3';self.service=NovelService(SQLiteRepository(self.db))
        self.pid=self.service.create(title='持久运行控制台')['document']['project']['id']
        self.action('add_character',dict(name='林舟'));self.chid=self.service.get(self.pid)['document']['characters'][0]['id']
        self.action('add_chapter',dict(title='第一章'));self.cid=self.service.get(self.pid)['document']['chapters'][0]['id']
        self.action('save_worldbuilding',dict(content='港城有雾。'));self.action('save_writing_rules',dict(content='限知视角。'))
        self.providers=ProviderConnections(self.root/'providers.dpapi')
        self.shared=TaskCoordinator(self.service,AdapterRegistry());self.addCleanup(self.shared.close)
        self.writing=ChapterWriting(self.shared,self.providers)
        self.planning=ChapterPlanningCoordinator(self.shared,self.providers,enabled=True)
        self.expansion=SceneExpansionCoordinator(self.shared,self.providers,enabled=True)
        self.console=ConsoleCoordinator(self.service,self.writing,self.planning,self.expansion)

    def action(self,name,fields):
        return self.service.execute(self.pid,name,fields,expected_revision=self.service.get(self.pid)['revision'])

    def session(self,title='运行会话'):
        return self.console.create(self.pid,dict(operation_id=str(uuid4()),title=title))

    def step(self,type_='idea',instruction='生成候选'):
        return dict(id=str(uuid4()),type=type_,chapter_id=self.cid,instruction=instruction,status='planned',scene_order=None,selection_start=None,selection_end=None)

    def save_plan(self,sid,steps):
        return self.console.save_plan(self.pid,dict(session_id=sid,steps=steps))

    def configure(self,wire,steps=('brainstorm','draft')):
        connection=self.providers.save_custom(id=str(uuid4()),name='虚构运行模型',base_url=wire['url'],protocol='openai-chat',model_id='fixture',api_key='console-run-private-key',allow_local=True)
        profiles=[dict(step=step,adapter_id='configured-http-v2',connection_id=connection['id'],model_id='fixture',temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=True) for step in steps]
        presets=CreationPresets(self.service)
        saved=presets.save(self.pid,dict(operation_id=str(uuid4()),preset_id=None,name='运行预设',settings=dict(steps=profiles,style_id=None,style_prompt='',manuscript_language='zh-CN',budget=dict(max_external_calls=8,max_reserved_output_tokens=4096,risk_budget=2.0,allow_unknown_cost=True)),expected_revision=self.service.get(self.pid)['revision']))
        presets.choose(self.pid,dict(operation_id=str(uuid4()),version_id=saved['version_id'],confirmed=True,expected_revision=self.service.get(self.pid)['revision']))

    def start(self,sid,operation=None):
        return self.console.start(self.pid,dict(operation_id=operation or str(uuid4()),session_id=sid,expected_revision=self.service.get(self.pid)['revision']))

    def advance(self,run_id,operation=None,revision=None):
        return self.console.advance(self.pid,dict(operation_id=operation or str(uuid4()),expected_revision=self.service.get(self.pid)['revision'] if revision is None else revision),run_id)

    def test_start_freezes_plan_and_advance_prepares_only_one_pending_task(self):
        with supplier(output=json.dumps(dict(idea='不应发送'),ensure_ascii=False)) as wire:
            self.configure(wire)
            sid=self.session()['id'];one=self.step('idea');two=self.step('draft');self.save_plan(sid,[one,two])
            started=self.start(sid);run_id=started['run']['id']
            self.assertEqual(self.service.get(self.pid)['workspace_version'],24)
            self.assertEqual(started['run']['status'],'running');self.assertEqual([v['status'] for v in started['steps']],['queued','queued'])
            self.assertEqual(len(self.service.get(self.pid).get('chapter_planning_tasks',[])),0)
            self.assertEqual(len(self.service.get(self.pid).get('generation_tasks',[])),0)
            advanced=self.advance(run_id)
            self.assertEqual(advanced['steps'][0]['status'],'awaiting_confirmation');self.assertEqual(advanced['steps'][1]['status'],'queued')
            self.assertEqual(advanced['run']['current_step_id'],advanced['steps'][0]['id'])
            self.assertTrue(advanced['steps'][0]['task_id'])
            self.assertEqual(len(self.service.get(self.pid)['chapter_planning_tasks']),1)
            before=self.service.get(self.pid)['revision']
            with self.assertRaises(ValueError):self.advance(run_id)
            after=self.service.get(self.pid)
            self.assertEqual(after['revision'],before);self.assertEqual(len(after['chapter_planning_tasks']),1)
            self.assertEqual(after['generation_tasks'],[]);self.assertEqual(wire['calls'],[])

    def test_operation_id_is_idempotent_and_stale_revision_is_rejected(self):
        with supplier() as wire:
            self.configure(wire,('brainstorm',))
            sid=self.session()['id'];self.save_plan(sid,[self.step('idea')]);started=self.start(sid);run_id=started['run']['id']
            operation=str(uuid4());revision=self.service.get(self.pid)['revision'];first=self.advance(run_id,operation,revision);second=self.advance(run_id,operation,revision)
            self.assertEqual(first['steps'][0]['task_id'],second['steps'][0]['task_id'])
            state=self.service.get(self.pid);self.assertEqual(len(state['chapter_planning_tasks']),1);self.assertEqual(len(state['console_run_actions']),2)
            with self.assertRaises(ValueError):self.advance(run_id,str(uuid4()),revision)
            self.assertEqual(len(self.service.get(self.pid)['chapter_planning_tasks']),1);self.assertEqual(wire['calls'],[])

    def test_skip_is_explicit_advances_past_unadopted_step_and_no_auto_skip(self):
        with supplier() as wire:
            self.configure(wire,('brainstorm',))
            sid=self.session()['id'];step=self.step('idea');self.save_plan(sid,[step]);started=self.start(sid);run_id=started['run']['id'];advanced=self.advance(run_id)
            current=advanced['steps'][0]
            skipped=self.console.skip(self.pid,dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision'],step_id=current['id']),run_id)
            self.assertEqual(skipped['steps'][0]['status'],'skipped');self.assertEqual(skipped['run']['status'],'completed');self.assertIsNone(skipped['run']['current_step_id'])
            self.assertEqual(len(self.service.get(self.pid)['chapter_planning_tasks']),1)
            self.assertEqual(self.service.get(self.pid)['chapter_planning_adoptions'],[]);self.assertEqual(wire['calls'],[])
            with self.assertRaises(ValueError):self.console.skip(self.pid,dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision']),run_id)

    def test_plan_revision_change_blocks_advance_but_cancel_is_explicit(self):
        sid=self.session()['id'];step=self.step('idea');self.save_plan(sid,[step]);started=self.start(sid);run_id=started['run']['id']
        self.save_plan(sid,[dict(step,instruction='修改后的指令')])
        with self.assertRaises(ValueError):self.advance(run_id)
        self.assertEqual(self.service.get(self.pid)['chapter_planning_tasks'],[])
        blocked=self.console.describe_run(self.pid,run_id);self.assertTrue(blocked['run']['blocked_reason']);self.assertFalse(blocked['run']['can_advance'])
        cancelled=self.console.cancel(self.pid,dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision']),run_id)
        self.assertEqual(cancelled['run']['status'],'cancelled');self.assertEqual(cancelled['steps'][0]['status'],'cancelled')

    def test_archived_session_missing_preset_and_invalid_revision_are_rejected(self):
        sid=self.session()['id'];self.console.archive(self.pid,dict(session_id=sid,archived=True))
        with self.assertRaises(ValueError):self.start(sid)
        sid=self.session('未配置')['id'];self.save_plan(sid,[self.step('idea')]);started=self.start(sid);run_id=started['run']['id']
        with self.assertRaises(ValueError):self.advance(run_id)
        state=self.service.get(self.pid);self.assertEqual(state['console_run_steps'][0]['status'],'queued');self.assertEqual(state['chapter_planning_tasks'],[])
        with self.assertRaises(ValueError):self.advance(run_id,revision=state['revision']-1)

    def test_pause_resume_then_advance_still_never_starts_or_adopts(self):
        with supplier() as wire:
            self.configure(wire,('brainstorm',))
            sid=self.session()['id'];self.save_plan(sid,[self.step('idea')]);started=self.start(sid);run_id=started['run']['id']
            paused=self.console.pause(self.pid,dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision']),run_id)
            self.assertEqual(paused['run']['status'],'paused')
            with self.assertRaises(ValueError):self.advance(run_id)
            resumed=self.console.resume(self.pid,dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision']),run_id)
            self.assertEqual(resumed['run']['status'],'running')
            self.advance(run_id);state=self.service.get(self.pid)
            self.assertEqual(state['chapter_planning_adoptions'],[]);self.assertEqual(state['console_run_actions'][0]['action'],'start')
            self.assertEqual(state['console_run_actions'][-1]['action'],'advance');self.assertEqual(wire['calls'],[])

    def test_task_success_then_adoption_is_observed_before_completion(self):
        class Engine:
            def __init__(self):self.value=None
            def describe(self,project,task):return self.value
        with supplier() as wire:
            self.configure(wire,('brainstorm',))
            sid=self.session()['id'];self.save_plan(sid,[self.step('idea')]);started=self.start(sid);run_id=started['run']['id'];self.advance(run_id)
            engine=Engine();self.console.engines['chapter_planning']=engine
            engine.value=dict(status='succeeded',display_status='succeeded',latest_candidate=dict(id='candidate-1'),adoptions=[])
            waiting=self.console.describe_run(self.pid,run_id);self.assertEqual(waiting['steps'][0]['status'],'awaiting_adoption')
            engine.value=dict(status='succeeded',display_status='adopted',latest_candidate=dict(id='candidate-1'),adoptions=[dict(id='receipt-1')])
            completed=self.console.describe_run(self.pid,run_id);self.assertEqual(completed['steps'][0]['status'],'completed')
            final=self.advance(run_id);self.assertEqual(final['run']['status'],'completed');self.assertEqual(final['steps'][0]['status'],'completed');self.assertEqual(wire['calls'],[])

    def test_v24_backup_restore_copy_maps_run_ids_and_does_not_copy_permission(self):
        from novel_writer.application.backups import create_backup,restore_backup
        from novel_writer.application.migrations import migrate
        from novel_writer.application.skill_import import SkillLibrary
        with supplier() as wire:
            self.configure(wire,('brainstorm',))
            sid=self.session()['id'];self.save_plan(sid,[self.step('idea')]);started=self.start(sid);run_id=started['run']['id'];self.advance(run_id)
            state=self.service.get(self.pid);self.assertEqual(state['workspace_version'],24);self.assertNotIn('console-run-private-key',json.dumps(state))
            SkillLibrary(self.db);package=self.root/'run.nwbak';manifest=create_backup(self.db,package);self.assertEqual(manifest['backup_format_version'],51)
            restored=restore_backup(package,self.root/'restored');self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid),state)
            target=self.root/'copy'/'copy.sqlite3';target.parent.mkdir();SQLiteRepository(target);SkillLibrary(target)
            copied=migrate(package,target,operation_id=str(uuid4()));clone=NovelService(SQLiteRepository(target)).get(copied['projects'][0]['new_id'])
            self.assertEqual(len(clone['console_runs']),1);self.assertEqual(len(clone['console_run_steps']),1);self.assertEqual(len(clone['console_run_actions']),2)
            old=state['console_runs'][0];new=clone['console_runs'][0];self.assertNotEqual(old['id'],new['id']);self.assertNotEqual(old['session_id'],new['session_id'])
            old_step=state['console_run_steps'][0];new_step=clone['console_run_steps'][0];self.assertNotEqual(old_step['id'],new_step['id']);self.assertNotEqual(old_step['dispatch_id'],new_step['dispatch_id']);self.assertNotEqual(old_step['task_id'],new_step['task_id'])
            self.assertEqual(new_step['run_id'],new['id']);self.assertEqual(new_step['dispatch_id'],clone['console_dispatches'][0]['id']);self.assertEqual(new_step['task_id'],clone['chapter_planning_tasks'][0]['id'])
            self.assertNotIn('console-run-private-key',json.dumps(clone))
            newpid=copied['projects'][0]['new_id'];newservice=NovelService(SQLiteRepository(target));shared=TaskCoordinator(newservice,AdapterRegistry());self.addCleanup(shared.close)
            planning=ChapterPlanningCoordinator(shared,self.providers,enabled=True)
            with self.assertRaises(ValueError):planning.start(newpid,new_step['task_id'],dict(confirm_external=True,request_sha256=clone['chapter_planning_tasks'][0]['binding']['request_sha256']))
            self.assertEqual(wire['calls'],[])


class ConsoleRunAssetTests(unittest.TestCase):
    def test_console_assets_expose_run_controls_and_filter_runs_client_side(self):
        base=Path(__file__).resolve().parents[1]/'src'/'novel_writer'/'ui'/'static'
        console=(base/'console.js').read_text(encoding='utf-8')
        for token in ('console-run-start','console-run-list','console-run-detail','console-run-advance','console-run-pause','console-run-resume','console-run-cancel','console-run-skip','console-run-blocked','expected_revision:runDetail.revision','payload.step_id=current.current_step_id','awaiting_confirmation'):
            self.assertIn(token,console)
        app=(base/'app.js').read_text(encoding='utf-8')
        self.assertIn("api(base+'/runs')",app)
        self.assertNotIn('/runs?session_id=',app)


if __name__=='__main__':unittest.main()
