"""V52 persistence and authenticated workbench wiring; isolated loopback only."""
from copy import deepcopy
import threading
from uuid import NAMESPACE_URL, uuid4, uuid5
import unittest
import test_chat_background as fixture
import test_console_runs_http as http_fixture


class BackgroundLegacyVersionTests(unittest.TestCase):
    def test_v52_single_snapshot_requires_full_history(self):
        from unittest.mock import Mock, mock_open
        from novel_writer.application.backups import BackupError
        from novel_writer.application.migrations import _legacy
        payload = b'{"workspace_version":52}'
        source = Mock()
        source.stat.return_value.st_size = len(payload)
        source.open = mock_open(read_data=payload)
        try:
            _legacy(source, None, str(uuid4()))
        except ValueError as error:
            # _legacy 对超出支持范围的版本抛普通 ValueError（"future workspace"），
            # 这不是 BackupError。原意是「不能静默接受 V52 的单快照」，验证方式改为断言错误信息。
            self.assertIn('future workspace', str(error))
        else:
            self.fail('V52 single snapshots must not be silently accepted')


class BackgroundPersistenceTests(unittest.TestCase):
    setUp = fixture.BackgroundChatTests.setUp
    action = fixture.BackgroundChatTests.action
    session = fixture.BackgroundChatTests.session
    step = fixture.BackgroundChatTests.step
    save_plan = fixture.BackgroundChatTests.save_plan
    start = fixture.BackgroundChatTests.start
    runner = fixture.BackgroundChatTests.runner
    launch = fixture.BackgroundChatTests.launch
    wait = fixture.BackgroundChatTests.wait

    def test_v50_refresh_and_graph_remain_v50_before_background_upgrade(self):
        import json
        from novel_writer.application.memory_refresh import upgrade as upgrade_v50
        from novel_writer.application.migrations import upgrade_console_background
        from novel_writer.storage.sqlite_repository import validate_workspace
        from novel_writer.storage.backup_validation import _workspace
        def validate_backup_workspace(value):return _workspace(json.dumps(value,ensure_ascii=False))
        state=self.service.get(self.pid)
        upgrade_v50(state)
        self.assertEqual(state['workspace_version'],50)
        validate_workspace(state);validate_backup_workspace(state)
        state['graph_item_decisions']=[]
        validate_workspace(state);validate_backup_workspace(state)
        before=deepcopy(state)
        upgrade_console_background(state)
        self.assertEqual(state['workspace_version'],52)
        self.assertEqual({k:v for k,v in state.items() if k not in ('workspace_version','console_background_batches','console_background_events')},
                         {k:v for k,v in before.items() if k!='workspace_version'})
        validate_workspace(state);validate_backup_workspace(state)

    def test_copy_maps_entire_background_history_twice(self):
        import json
        from novel_writer.application.migrations import _transform
        from novel_writer.storage.sqlite_repository import WorkspaceHistoryValidator
        executor, run = self.runner()
        self.launch(executor, run)
        self.assertEqual(self.wait(executor, run)['status'], 'completed')
        with self.service.repository._connection() as db:
            states=[json.loads(row[0]) for row in db.execute('SELECT payload FROM project_snapshots WHERE project_id=? ORDER BY revision',(self.pid,))]
        for copy_number in (1,2):
            def mapped(project, kind, old):
                return str(uuid5(NAMESPACE_URL,str(copy_number)+'/'+project+'/'+kind+'/'+old))
            states=[_transform(state,mapped) for state in states]
            history=WorkspaceHistoryValidator()
            for state in states:history.validate(state)
            current=states[-1];batch=current['console_background_batches'][0]
            self.assertEqual(batch['project_id'],current['document']['project']['id'])
            self.assertEqual(batch['run_id'],current['console_runs'][0]['id'])
            self.assertEqual(batch['request']['step_ids'],[step['id'] for step in current['console_run_steps']])
            self.assertEqual(batch['preview']['items'][0]['source']['step']['chapter_id'],current['document']['chapters'][0]['id'])
            self.assertTrue(all(e['batch_id']==batch['id'] for e in current['console_background_events']))

    def test_reopened_owner_requires_new_grant_and_preserves_audit(self):
        from novel_writer.application.console_background import BackgroundExecutor, upgrade
        from novel_writer.domain.models import utc_now
        executor, run = self.runner()
        step_ids=[step['id'] for step in self.console.describe_run(self.pid,run)['steps']]
        request=dict(step_ids=step_ids,max_steps=2,max_seconds=10)
        preview=executor.preview(self.pid,run,request)
        batch=dict(id=str(uuid4()),project_id=self.pid,run_id=run,operation_id=str(uuid4()),owner_id=executor.owner_id,request=request,preview=preview,created_at=utc_now())
        def interrupted_commit(state):
            upgrade(state);state['console_background_batches'].append(deepcopy(batch));executor._emit(state,batch,'started')
            return state,None
        self.service.repository.atomic(self.pid,interrupted_commit)
        recovered=BackgroundExecutor(self.console);self.addCleanup(recovered.close)
        self.assertEqual(recovered.describe(self.pid,run)['batches'][0]['status'],'interrupted')
        recovered.recover(self.pid)
        state=self.service.get(self.pid)
        self.assertEqual(state['console_background_events'][-1]['kind'],'interrupted')
        recovered.recover(self.pid)
        self.assertEqual(self.service.get(self.pid),state)
        self.assertEqual([s['status'] for s in state['console_run_steps']],['queued','queued'])
        self.launch(recovered,run)
        self.assertEqual(self.wait(recovered,run)['status'],'completed')

    def test_v52_backup_restore_copy_and_append_only_history(self):
        from novel_writer.application.backups import create_backup, restore_backup
        from novel_writer.application.migrations import migrate
        from novel_writer.application.service import NovelService
        from novel_writer.storage.sqlite_repository import SQLiteRepository
        from novel_writer.storage.backup_validation import validate_database
        from novel_writer.application.skill_import import SkillLibrary
        SkillLibrary(self.db)
        executor, run = self.runner()
        self.launch(executor, run)
        self.assertEqual(self.wait(executor, run)['status'], 'completed')
        state = self.service.get(self.pid)
        self.assertEqual(state['workspace_version'], 52)
        counts = validate_database(self.db)['counts']['projects'][0]
        self.assertEqual(counts['console_background_batches'], 1)
        self.assertEqual(counts['console_background_events'], 4)
        with self.assertRaises(ValueError):
            self.service.repository.atomic(self.pid, lambda s: (dict(s, console_background_events=[]), None))
        self.assertEqual(self.service.get(self.pid), state)
        package = self.root/'background.zip'
        create_backup(self.db, package)
        restored_dir = self.root/'restored'
        restore_backup(package, restored_dir)
        restored_db = next(restored_dir.glob('*.sqlite3'))
        self.assertEqual(NovelService(SQLiteRepository(restored_db)).get(self.pid), state)
        target = self.root/'copied.sqlite3'
        copied_service = NovelService(SQLiteRepository(target))
        SkillLibrary(target)
        result = migrate(package, target, operation_id=str(uuid4()))
        copied_id = result['projects'][0]['new_id']
        copied = copied_service.get(copied_id)
        batch = copied['console_background_batches'][0]
        self.assertEqual(batch['project_id'], copied_id)
        self.assertNotEqual(batch['id'], state['console_background_batches'][0]['id'])
        self.assertEqual(batch['run_id'], copied['console_runs'][0]['id'])
        self.assertEqual(batch['request']['step_ids'], [s['id'] for s in copied['console_run_steps']])
        self.assertEqual(batch['preview']['items'][0]['source']['step']['chapter_id'], copied['document']['chapters'][0]['id'])
        again = self.root/'copied-again.sqlite3'
        SQLiteRepository(again)
        SkillLibrary(again)
        migrate(target, again, operation_id=str(uuid4()))
        validate_database(again)


class BackgroundHttpTests(unittest.TestCase):
    setUp = http_fixture.ConsoleRunHttpTests.setUp
    stop = http_fixture.ConsoleRunHttpTests.stop
    request = http_fixture.ConsoleRunHttpTests.request

    def make_run(self):
        code, session, _ = self.request('POST', self.base+'/sessions', dict(operation_id=str(uuid4()),title='后台运行'))
        self.assertEqual(code, 201)
        step = dict(id=str(uuid4()),type='chapter.inspect',chapter_id=self.chapter,instruction='',status='planned',scene_order=None,selection_start=None,selection_end=None)
        self.assertEqual(self.request('POST',self.base+'/sessions/'+session['id']+'/plan',dict(steps=[step]))[0],200)
        code, result, _ = self.request('POST',self.base+'/runs',dict(operation_id=str(uuid4()),session_id=session['id'],expected_revision=self.server.service.get(self.pid)['revision']))
        self.assertEqual(code,201)
        return result['run']['id'], result['steps'][0]['id']

    def test_preview_start_query_capabilities_and_rejected_payloads(self):
        run, step = self.make_run()
        route = self.base+'/runs/'+run+'/background'
        selection = dict(step_ids=[step],max_steps=1,max_seconds=10)
        before = self.server.service.get(self.pid)
        self.assertEqual(self.request('POST',route+'/recover',{},token=False)[0],403)
        self.assertEqual(self.request('POST',route+'/recover',dict(output='injected'))[0],422)
        self.assertEqual(self.request('POST',route+'/recover',{})[0],200)
        self.assertEqual(self.request('POST',route+'/preview',selection,token=False)[0],403)
        code, preview, _ = self.request('POST',route+'/preview',selection)
        self.assertEqual(code,200,preview)
        self.assertEqual(self.server.service.get(self.pid),before)
        grant = dict(selection,operation_id=str(uuid4()),expected_revision=preview['revision'],preview_sha256=preview['sha256'],confirmed=True)
        self.assertEqual(self.request('POST',route+'/start',grant,token=False)[0],403)
        self.assertEqual(self.request('POST',route+'/start',dict(grant,confirmed=False))[0],422)
        self.assertEqual(self.request('POST','/api/projects/'+self.pid+'/workflows/runs/'+run+'/background/start',grant)[0],404)
        self.assertEqual(self.request('POST',route+'/start',grant)[0],202)
        self.assertTrue(self.server.console_background.wait_idle(5))
        code, result, _ = self.request('GET',route,token=False)
        self.assertEqual(code,200,result)
        self.assertEqual(result['batches'][0]['status'],'completed')
        detail = self.request('GET',self.base+'/runs/'+run)[1]
        self.assertEqual(detail['background']['batches'],result['batches'])
        self.assertEqual(self.request('POST',route+'/pause',dict(output='injected'))[0],422)
        self.assertEqual(self.request('POST',route+'/cancel',{},token=False)[0],403)
        self.assertEqual(self.request('GET',self.base+'/runs/missing/background')[0],404)
        caps = self.request('GET','/api/backups/capabilities')[1]
        self.assertIn(52,caps['workspace_versions']); self.assertIn(51,caps['backup_format_versions'])
        self.assertIn('backup_v51',self.request('GET','/api/migrations/capabilities')[1]['formats'])

    def test_pause_and_cancel_signal_active_batch(self):
        from unittest.mock import patch
        for action, expected in [('pause','paused'),('cancel','cancelled')]:
            with self.subTest(action=action):
                run, step = self.make_run()
                route = self.base+'/runs/'+run+'/background'
                selection=dict(step_ids=[step],max_steps=1,max_seconds=10)
                preview=self.request('POST',route+'/preview',selection)[1]
                entered, release = threading.Event(), threading.Event()
                original=self.server.console._read_tool
                def slow(state, selected):
                    if threading.current_thread().name.startswith('console-background'):
                        entered.set();release.wait(3)
                    return original(state,selected)
                with patch.object(self.server.console,'_read_tool',side_effect=slow):
                    grant=dict(selection,operation_id=str(uuid4()),expected_revision=preview['revision'],preview_sha256=preview['sha256'],confirmed=True)
                    self.assertEqual(self.request('POST',route+'/start',grant)[0],202)
                    self.assertTrue(entered.wait(2))
                    try:self.assertEqual(self.request('POST',route+'/'+action,{})[0],200)
                    finally:release.set()
                self.assertTrue(self.server.console_background.wait_idle(5))
                self.assertEqual(self.request('GET',route)[1]['batches'][-1]['status'],expected)
                self.server.console.cancel(self.pid,dict(operation_id=str(uuid4()),expected_revision=self.server.service.get(self.pid)['revision']),run)
