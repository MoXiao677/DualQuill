"""Bounded fictional V48 failure probes; no real credentials or provider traffic."""
from contextlib import closing, contextmanager
from copy import deepcopy
import ctypes
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_model_planning as planning_fixture
import test_rule_semantic_reviews as rule_fixture
from novel_writer.application.drafts import DiskDrafts, DraftError
from novel_writer.application.service import NovelService
from novel_writer.domain.author_scope import active_locks, digest
from novel_writer.storage.sqlite_repository import SQLiteRepository, ConflictError

ROOT = Path(__file__).resolve().parents[1]


def history(path):
    with closing(sqlite3.connect(path)) as db:
        return [(row[0], sha256(row[1].encode('utf-8')).hexdigest(), row[2]) for row in
                db.execute('SELECT revision,payload,saved_at FROM project_snapshots ORDER BY project_id,revision')]


def lock_body(f):
    state = f.service.get(f.pid)
    chapter = next(c for c in state['document']['chapters'] if c['id'] == f.c1)
    body = chapter['content']; start = body.index('星灯')
    f.service.execute(f.pid, 'lock_body_range', dict(operation_id=str(uuid4()), confirmed=True,
        chapter_id=f.c1, version_id=chapter['current_version_id'], body_sha256=digest(body),
        start=start, end=start+2, text_sha256=digest(body[start:start+2])), expected_revision=state['revision'])


class JointTransactionDurabilityTests(unittest.TestCase):
    def setUp(self):
        self.f = planning_fixture.ModelPlanningTests('runTest'); self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        lock_body(self.f)
        self.repo = self.f.service.repository
        self.assertEqual(self.repo.get(self.f.pid)['workspace_version'], 48)

    def unchanged(self, before, old_history):
        self.assertEqual(self.repo.get(self.f.pid), before)
        self.assertEqual(SQLiteRepository(self.f.db).get(self.f.pid), before)
        self.assertEqual(history(self.f.db), old_history)
        with closing(sqlite3.connect(self.f.db)) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(), ('ok',))

    def test_real_sqlite_full_rolls_back_body_lock_blob_history_and_cache(self):
        f=self.f
        f.service.change_memory_automation(f.pid, dict(action='policy',operation_id=str(uuid4()),
            expected_revision=f.revision(),policy=dict(track_updates=True,auto_select=False)))
        before = self.repo.get(self.f.pid); old_history = history(self.f.db)
        original = self.repo._connection
        @contextmanager
        def limited():
            with original() as db:
                pages = db.execute('PRAGMA page_count').fetchone()[0]
                self.assertEqual(db.execute('PRAGMA max_page_count='+str(pages)).fetchone()[0], pages)
                yield db
        def operation(state):
            from novel_writer.application import chapters
            from novel_writer.storage.json_codec import document_from_dict,document_to_dict
            document=document_from_dict(state['document'])
            body=next(c for c in state['document']['chapters'] if c['id']==f.c1)['content']
            chapters.save(document,dict(chapter_id=f.c1,content=body+'虚构不能部分提交'))
            state['document']=document_to_dict(document)
            state['writing_rules'] = '虚构事务中未提交规则'
            return state, True
        with patch.object(self.repo, '_connection', limited):
            with self.assertRaises(sqlite3.OperationalError) as caught:
                self.repo.atomic(self.f.pid, operation, blobs=(b'fiction-only-full-' * 131072,))
        self.assertEqual(caught.exception.sqlite_errorcode, sqlite3.SQLITE_FULL)
        self.unchanged(before, old_history)
        with closing(sqlite3.connect(self.f.db)) as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='content_blobs'").fetchone()
            if exists:self.assertEqual(db.execute('SELECT count(*) FROM content_blobs').fetchone()[0], 0)

    def test_sqlite_readonly_rejects_save_preserving_lock_and_history(self):
        before = self.repo.get(self.f.pid); old_history = history(self.f.db)
        @contextmanager
        def readonly():
            with closing(sqlite3.connect(self.f.db.as_uri()+'?mode=ro', uri=True)) as db:
                db.row_factory=sqlite3.Row
                with db:yield db
        changed=deepcopy(before); changed['writing_rules']='虚构只读拒绝'
        with patch.object(self.repo, '_connection', readonly):
            with self.assertRaises(sqlite3.OperationalError) as caught:
                self.repo.save(changed, expected_revision=before['revision'])
        self.assertEqual(caught.exception.sqlite_errorcode, sqlite3.SQLITE_READONLY)
        self.unchanged(before, old_history)

    def test_late_snapshot_failure_rolls_back_lock_rebase_and_incremental_queue(self):
        f=self.f
        f.service.change_memory_automation(f.pid, dict(action='policy', operation_id=str(uuid4()),
            expected_revision=f.revision(), policy=dict(track_updates=True, auto_select=False)))
        before=self.repo.get(f.pid); old_history=history(f.db)
        with closing(sqlite3.connect(f.db)) as db, db:
            db.execute("CREATE TRIGGER fictional_v48_fail AFTER INSERT ON project_snapshots BEGIN SELECT RAISE(ABORT,'fictional V48 late failure'); END")
        body=next(c for c in before['document']['chapters'] if c['id']==f.c1)['content']
        with self.assertRaisesRegex(sqlite3.IntegrityError,'fictional V48 late failure'):
            f.save(content=body+'锁外新内容')
        self.unchanged(before, old_history)
        with closing(sqlite3.connect(f.db)) as db, db:db.execute('DROP TRIGGER fictional_v48_fail')
        f.save(content=body+'锁外重试')
        after=self.repo.get(f.pid)
        self.assertTrue(f.service.memory_automation(f.pid)['queue'])
        self.assertNotEqual(next(iter(active_locks(before).values()))['version_id'],
                            next(iter(active_locks(after).values()))['version_id'])
        self.assertEqual(history(f.db)[:-1],old_history)

    def test_real_writer_contention_then_stale_revision_never_overwrites(self):
        f=self.f;before=self.repo.get(f.pid);old_history=history(f.db);original=self.repo._connection
        @contextmanager
        def bounded():
            with original() as db:
                db.execute('PRAGMA busy_timeout=50');yield db
        with closing(sqlite3.connect(f.db)) as other:
            other.execute('BEGIN IMMEDIATE')
            with patch.object(self.repo,'_connection',bounded):
                with self.assertRaises(sqlite3.OperationalError) as caught:
                    self.repo.save(before,expected_revision=before['revision'])
            self.assertEqual(caught.exception.sqlite_errorcode,sqlite3.SQLITE_BUSY)
            other.rollback()
        self.unchanged(before,old_history)
        second=NovelService(SQLiteRepository(f.db));body=next(c for c in before['document']['chapters'] if c['id']==f.c1)['content']
        second.execute(f.pid,'save_chapter',dict(chapter_id=f.c1,content=body+'另一实例提交'),expected_revision=before['revision'])
        committed=second.get(f.pid)
        with self.assertRaises(ConflictError):self.repo.save(before,expected_revision=before['revision'])
        self.assertEqual(self.repo.get(f.pid),committed)
        self.assertEqual(history(f.db)[:-1],old_history)

    def test_failed_transfer_does_not_consume_claim_or_write_partial_proposal(self):
        f=self.f
        with planning_fixture.model_wire(json.dumps(f.payload(),ensure_ascii=False)) as wire:
            self.assertNotIn(':8765/', wire['url'])
            done=f.run_task(f.prepare(f.connection(wire))); candidate=done['candidates'][0]
            selection=dict(candidate_id=candidate['id'],candidate_sha256=candidate['data_sha256'],suggestion_index=0)
            preview=f.ai.preview_transfer(f.pid,selection)
            request=f.request(**selection,transfer_token=preview['transfer_token'],confirmed=True)
            before=self.repo.get(f.pid); old_history=history(f.db)
            with closing(sqlite3.connect(f.db)) as db, db:
                db.execute("CREATE TRIGGER fictional_transfer_fail AFTER INSERT ON project_snapshots BEGIN SELECT RAISE(ABORT,'fictional transfer failure'); END")
            with self.assertRaisesRegex(sqlite3.IntegrityError,'fictional transfer failure'):f.ai.propose(f.pid,request)
            self.unchanged(before,old_history)
            with closing(sqlite3.connect(f.db)) as db, db:db.execute('DROP TRIGGER fictional_transfer_fail')
            link=f.ai.propose(f.pid,request)
            self.assertEqual(link,f.ai.propose(f.pid,request))
            saved=self.repo.get(f.pid)
            self.assertEqual(len(saved['model_planning_links']),1)
            self.assertEqual(len(saved['body_planning_proposals']),1)
            self.assertEqual(saved['document'],before['document'])
            self.assertEqual(saved['key_events'],before['key_events'])
            self.assertEqual(saved['model_planning_results'],before['model_planning_results'])
            self.assertEqual(len(wire['calls']),1)

    def test_model_terminal_disk_failure_is_visible_without_partial_candidate_or_resend(self):
        f=self.f; crashes=[]
        with planning_fixture.model_wire(json.dumps(f.payload(),ensure_ascii=False)) as wire:
            prepared=f.prepare(f.connection(wire)); before=self.repo.get(f.pid)
            with closing(sqlite3.connect(f.db)) as db, db:
                db.execute("CREATE TRIGGER fictional_terminal_fail AFTER INSERT ON project_snapshots WHEN json_array_length(json_extract(NEW.payload,'$.model_planning_results'))>0 BEGIN SELECT RAISE(ABORT,'fictional terminal failure'); END")
            with patch.object(threading,'excepthook',lambda args:crashes.append(args.exc_value)):
                f.start(prepared);f.shared.wait_idle(5)
            self.assertEqual(len(crashes),1)
            self.assertIsInstance(crashes[0],sqlite3.IntegrityError)
            self.assertEqual(f.shared.active,{})
            self.assertTrue(f.shared.slot.acquire(blocking=False));f.shared.slot.release()
            after=self.repo.get(f.pid)
            self.assertEqual(after['model_planning_results'],[])
            self.assertEqual(after['model_planning_candidates'],[])
            self.assertEqual(after['document'],before['document'])
            self.assertEqual(after['author_scope_events'],before['author_scope_events'])
            self.assertEqual(after['revision'],before['revision']+1)
            view=f.ai.describe(f.pid,prepared['task']['id'])
            self.assertEqual(view['display_status'],'interrupted')
            self.assertEqual(view['status'],'running')
            with self.assertRaises(ValueError):f.start(prepared)
            with closing(sqlite3.connect(f.db)) as db, db:db.execute('DROP TRIGGER fictional_terminal_fail')
            self.assertEqual(f.ai.cancel(f.pid,prepared['task']['id'],{}),dict(accepted=True))
            self.assertEqual(f.ai.describe(f.pid,prepared['task']['id'])['display_status'],'cancelled')
            self.assertEqual(len(wire['calls']),1)
            self.assertEqual(SQLiteRepository(f.db).get(f.pid),self.repo.get(f.pid))

    def test_joint_v48_restore_double_copy_keep_raw_identity_claims_and_manual_gates(self):
        from novel_writer.application.backups import create_backup,restore_backup
        from novel_writer.application.migrations import migrate
        from novel_writer.application.skill_import import SkillLibrary
        from novel_writer.application.scoped_rules import RuleCoordinator
        from novel_writer.application.rule_reviews import RuleReviewCoordinator
        from novel_writer.application.model_planning import ModelPlanningCoordinator
        from novel_writer.application.tasks import TaskCoordinator
        from novel_writer.application.task_protocol import AdapterRegistry
        f=self.f
        f.service.change_memory_automation(f.pid,dict(action='policy',operation_id=str(uuid4()),
            expected_revision=f.revision(),policy=dict(track_updates=True,auto_select=True)))
        state=f.service.get(f.pid);body=next(c for c in state['document']['chapters'] if c['id']==f.c1)['content']
        f.save(content=body+'虚构锁外已保存尾部')
        rules=RuleCoordinator(f.service)
        for kind,text in [('required','虚构第一人称叙事'),('guidance','虚构全知叙事提示')]:
            rules.save(f.pid,dict(operation_id=str(uuid4()),rule_id=None,scope='book',scope_id=f.pid,kind=kind,text=text,enabled=True))
        review=RuleReviewCoordinator(f.shared,f.providers,enabled=True)
        preview=review.preview(f.pid,dict(chapter_id=f.c1,target_task_id=None))
        with planning_fixture.model_wire(rule_fixture.opinion(preview['rules'])) as wire:
            connection=f.connection(wire)
            request=dict(request_id=str(uuid4()),chapter_id=f.c1,target_task_id=None,source_sha256=preview['source_sha256'],
                model_options=dict(adapter_id='configured-http-v2',connection_id=connection['id'],model_id='fiction-selected',
                    temperature=.3,max_tokens=1024,budget_limit=1.,allow_unknown_cost=True,prompt_version='rewrite-1'),
                max_output_chars=10000,timeout_ms=2000,budget_max_calls=10,budget_max_output_tokens=81920)
            prepared=review.prepare(f.pid,request);task=prepared['task']
            review.start(f.pid,task['id'],dict(confirm_external=True,request_sha256=task['binding']['request_sha256']))
            f.shared.wait_idle(5);self.assertEqual(review.describe(f.pid,task['id'])['status'],'succeeded')
            pending_rule=review.prepare(f.pid,dict(request,request_id=str(uuid4())))
            self.assertEqual(len(wire['calls']),1)
        with planning_fixture.model_wire(json.dumps(f.payload(),ensure_ascii=False)) as wire:
            connection=f.connection(wire);done=f.run_task(f.prepare(connection));f.transfer(done)
            pending_model=f.prepare(connection)
            self.assertEqual(len(wire['calls']),1)
        original=f.service.get(f.pid);old_history=history(f.db);SkillLibrary(f.db)
        archive=f.root/'joint-v48.nwbak';manifest=create_backup(f.db,archive)
        self.assertEqual(manifest['backup_format_version'],51)
        restored=restore_backup(archive,f.root/'joint-restored')
        self.assertEqual(SQLiteRepository(restored['database_path']).get(f.pid),original)
        self.assertEqual(history(restored['database_path']),old_history)
        old_wire=original['model_planning_tasks'][0]['binding']
        old_rule=original['rule_review_tasks'][0]
        for index in range(2):
            target=f.root/('joint-copy-'+str(index)+'.sqlite3');SQLiteRepository(target);SkillLibrary(target)
            result=migrate(archive,target,operation_id=str(uuid4()));pid=result['projects'][0]['new_id']
            service=NovelService(SQLiteRepository(target));parent=TaskCoordinator(service,AdapterRegistry());self.addCleanup(parent.close)
            ai=ModelPlanningCoordinator(parent,f.providers,enabled=True);copied_rules=RuleReviewCoordinator(parent,f.providers,enabled=True)
            copied=service.get(pid);model=copied['model_planning_tasks'][0];rule=copied['rule_review_tasks'][0]
            self.assertEqual(copied['workspace_version'],48)
            self.assertEqual(model['binding'],old_wire)
            self.assertEqual(model['original_source_json'],original['model_planning_tasks'][0]['original_source_json'])
            self.assertEqual(copied['model_planning_results'][0]['response'],original['model_planning_results'][0]['response'])
            self.assertEqual(rule['wire_source'],old_rule['wire_source'])
            self.assertEqual(rule['binding'],old_rule['binding'])
            self.assertEqual(copied['rule_review_results'][0]['response'],original['rule_review_results'][0]['response'])
            self.assertEqual(next(iter(active_locks(copied).values()))['text_sha256'],next(iter(active_locks(original).values()))['text_sha256'])
            self.assertFalse(service.memory_automation(pid)['policy']['track_updates'])
            self.assertEqual(copied['model_planning_links'][0]['proposal_id'],copied['body_planning_proposals'][0]['id'])
            pending=ai.describe(pid)['tasks'][-1]
            self.assertEqual(pending['display_status'],'interrupted')
            with self.assertRaises(ValueError):ai.start(pid,pending['task']['id'],dict(confirm_external=True,
                request_sha256=pending['task']['binding']['request_sha256'],budget_sha256=pending['task']['budget_sha256'],expected_revision=copied['revision']))
            rpending=copied_rules.describe(pid)['tasks'][-1];self.assertEqual(rpending['display_status'],'interrupted')
            with self.assertRaises(ValueError):copied_rules.start(pid,rpending['task']['id'],dict(confirm_external=True,request_sha256=rpending['task']['binding']['request_sha256']))
            # A copied pending proposal has no inherited preview/acceptance permission.
            from novel_writer.application.body_planning import BodyPlanning
            proposal=copied['body_planning_proposals'][0]
            with self.assertRaises(ValueError):BodyPlanning(service).decide(pid,dict(operation_id=str(uuid4()),expected_revision=copied['revision'],
                proposal_id=proposal['id'],decision='accepted',preview_sha256='0'*64))
            locked=next(iter(active_locks(copied).values()))
            with self.assertRaises(ValueError):service.execute(pid,'save_chapter',dict(chapter_id=locked['chapter_id'],content='不能继承解锁'),expected_revision=copied['revision'])
            self.assertEqual(service.get(pid),copied)
            archive=f.root/('joint-copy-'+str(index)+'.nwbak');create_backup(target,archive)
        self.assertEqual(f.service.get(f.pid),original);self.assertEqual(history(f.db),old_history)


class RuleTerminalDurabilityTests(unittest.TestCase):
    def test_rule_terminal_disk_failure_is_visible_and_explicitly_recoverable(self):
        f=rule_fixture.RuleSemanticReviewTests('runTest');f.setUp();self.addCleanup(f.doCleanups)
        preview=f.setup_review();crashes=[]
        from test_chapter_writing import supplier
        with supplier(output=rule_fixture.opinion(preview['rules'])) as wire:
            prepared,_=f.prepare_review(f.connection(wire));task=prepared['task'];before=f.service.get(f.pid)
            with closing(sqlite3.connect(f.db)) as db,db:
                db.execute("CREATE TRIGGER fictional_rule_terminal AFTER INSERT ON project_snapshots WHEN json_array_length(json_extract(NEW.payload,'$.rule_review_results'))>0 BEGIN SELECT RAISE(ABORT,'fictional rule terminal failure'); END")
            with patch.object(threading,'excepthook',lambda args:crashes.append(args.exc_value)):
                f.review.start(f.pid,task['id'],dict(confirm_external=True,request_sha256=task['binding']['request_sha256']))
                f.engine.wait_idle(5)
            self.assertEqual(len(crashes),1);self.assertIsInstance(crashes[0],sqlite3.IntegrityError)
            after=f.service.get(f.pid);self.assertEqual(after['rule_review_results'],[])
            self.assertEqual(after['document'],before['document'])
            self.assertEqual(f.review.describe(f.pid,task['id'])['display_status'],'interrupted')
            with closing(sqlite3.connect(f.db)) as db,db:db.execute('DROP TRIGGER fictional_rule_terminal')
            self.assertEqual(f.review.recover(f.pid)['interrupted'],[task['id']])
            self.assertEqual(f.review.describe(f.pid,task['id'])['status'],'interrupted')
            self.assertEqual(len(wire['calls']),1)


class DraftFileDurabilityTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt','Windows sharing denial requires Win32')
    def test_real_windows_sharing_denial_keeps_previous_draft_and_allows_retry(self):
        with tempfile.TemporaryDirectory(prefix='v48-draft-sharing-') as directory:
            store=DiskDrafts(Path(directory)/'drafts');key=json.dumps(['fiction','writing','chapter','body'])
            store.save('fiction',key,1,dict(content='虚构原草稿😀'))
            target=next(store.directory.glob('*.json'));old=target.read_bytes()
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p]
            kernel.CreateFileW.restype=ctypes.c_void_p
            kernel.CloseHandle.argtypes=[ctypes.c_void_p]
            handle=kernel.CreateFileW(str(target),0x80000000,1,None,3,0,None)
            self.assertNotEqual(handle,ctypes.c_void_p(-1).value)
            try:
                with self.assertRaisesRegex(DraftError,'保留输入'):store.save('fiction',key,2,dict(content='虚构待重试'))
                self.assertEqual(target.read_bytes(),old)
                self.assertEqual(list(store.directory.glob('.draft-*.tmp')),[])
            finally:kernel.CloseHandle(handle)
            store.save('fiction',key,2,dict(content='虚构待重试'))
            self.assertEqual(DiskDrafts(store.directory).list('fiction')['drafts'][0]['values']['content'],'虚构待重试')


def pause_owned(root, point, nonce, artifact):
    root=Path(root).resolve(strict=True);artifact=Path(artifact).resolve(strict=True)
    if root not in artifact.parents:raise AssertionError('barrier escaped owned directory')
    with (root/'ready.json').open('x',encoding='utf-8') as output:
        json.dump(dict(pid=os.getpid(),nonce=nonce,point=point,artifact=str(artifact)),output)
        output.flush();os.fsync(output.fileno())
    time.sleep(25)
    raise AssertionError('owned parent did not terminate bounded worker')


def owned_worker(root, point, nonce):
    root=Path(root).resolve(strict=True)
    request=json.loads((root/'worker-input.json').read_text(encoding='utf-8'))
    if point.startswith('draft-'):
        import novel_writer.application.drafts as drafts
        original=drafts.os.replace
        def replace(source,target):
            if point=='draft-before':pause_owned(root,point,nonce,source)
            original(source,target)
            if point=='draft-after':pause_owned(root,point,nonce,target)
        drafts.os.replace=replace
        DiskDrafts(root/'drafts').save('fiction',request['key'],2,dict(content='虚构新恢复草稿😀'))
    else:
        repo=SQLiteRepository(root/'fiction.sqlite3');original=repo._connection
        if point=='sql-before-commit':
            @contextmanager
            def barrier_connection():
                with original() as db:
                    def trace(statement):
                        if statement.startswith('INSERT INTO project_snapshots'):
                            pause_owned(root,point,nonce,repo.path)
                    db.set_trace_callback(trace)
                    yield db
            repo._connection=barrier_connection
        else:
            def committed(*args,**kwargs):pause_owned(root,point,nonce,repo.path)
            repo._remember_commit=committed
        NovelService(repo).execute(request['project_id'],'save_chapter',
            dict(chapter_id=request['chapter_id'],content=request['body']+'虚构中断尾部'),
            expected_revision=request['revision'])


class OwnedProcessDurabilityTests(unittest.TestCase):
    setUp=JointTransactionDurabilityTests.setUp

    def crash(self,point,request):
        root=self.f.root;nonce=uuid4().hex
        (root/'worker-input.json').write_text(json.dumps(request,ensure_ascii=False),encoding='utf-8')
        environment={key:os.environ[key] for key in ('PATH','SystemRoot','WINDIR','COMSPEC','PATHEXT','TEMP','TMP') if key in os.environ}
        environment.update(PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=os.pathsep.join((str(ROOT/'src'),str(ROOT/'tests'))),
                           USERPROFILE=str(root),LOCALAPPDATA=str(root/'profile'),APPDATA=str(root/'profile'))
        child=None;started=time.monotonic()
        with (root/'worker.log').open('w',encoding='utf-8') as output:
            child=subprocess.Popen([sys.executable,'-B','-X','utf8',str(Path(__file__).resolve()),'--owned-worker',str(root),point,nonce],
                cwd=ROOT,env=environment,stdout=output,stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            try:
                marker=root/'ready.json';deadline=started+15;ready=None
                while time.monotonic()<deadline and child.poll() is None:
                    try:ready=json.loads(marker.read_text(encoding='utf-8'));break
                    except (FileNotFoundError,json.JSONDecodeError):time.sleep(.02)
                self.assertIsNotNone(ready,'worker did not reach barrier: '+(root/'worker.log').read_text(encoding='utf-8'))
                self.assertEqual((ready['pid'],ready['nonce'],ready['point']),(child.pid,nonce,point))
                self.assertIn(root,Path(ready['artifact']).resolve(strict=True).parents)
                self.assertIsNone(child.poll());child.kill();self.assertNotEqual(child.wait(timeout=5),0)
            finally:
                if child.poll() is None:child.kill();child.wait(timeout=5)
        record=dict(point=point,pid=child.pid,nonce=nonce,handshake_verified=True,exit_code=child.returncode,
                    seconds=round(time.monotonic()-started,6),physical_power_loss=False,process_exited=child.poll() is not None,
                    marker_sha256=sha256((root/'ready.json').read_bytes()).hexdigest(),
                    worker_log_sha256=sha256((root/'worker.log').read_bytes()).hexdigest())
        artifacts=os.environ.get('NOVEL_WRITER_ARTIFACTS')
        if artifacts:
            with (Path(artifacts)/'v48-owned-process-probes.jsonl').open('a',encoding='utf-8') as output:
                output.write(json.dumps(record)+'\n')
        print(json.dumps(record,ensure_ascii=False))

    def sql_crash(self,point):
        f=self.f;before=self.repo.get(f.pid);old_history=history(f.db)
        chapter=next(c for c in before['document']['chapters'] if c['id']==f.c1)
        self.crash(point,dict(project_id=f.pid,chapter_id=f.c1,body=chapter['content'],revision=before['revision']))
        reopened=SQLiteRepository(f.db).get(f.pid)
        with closing(sqlite3.connect(f.db)) as db:self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(),('ok',))
        if point=='sql-before-commit':
            self.assertEqual(reopened,before);self.assertEqual(self.repo.get(f.pid),before)
            self.assertEqual(history(f.db),old_history)
        else:
            self.assertEqual(reopened['revision'],before['revision']+1)
            self.assertEqual(next(c for c in reopened['document']['chapters'] if c['id']==f.c1)['content'],chapter['content']+'虚构中断尾部')
            self.assertEqual(history(f.db)[:-1],old_history)
            self.assertEqual(next(iter(active_locks(reopened).values()))['text_sha256'],next(iter(active_locks(before).values()))['text_sha256'])
            self.assertEqual(self.repo.get(f.pid),reopened)
        body=next(c for c in reopened['document']['chapters'] if c['id']==f.c1)['content']
        NovelService(SQLiteRepository(f.db)).execute(f.pid,'save_chapter',dict(chapter_id=f.c1,content=body+'重开续写'),expected_revision=reopened['revision'])

    def test_owned_kill_before_sql_commit_reopens_zero_partial_state(self):self.sql_crash('sql-before-commit')
    def test_owned_kill_after_sql_commit_reopens_complete_state(self):self.sql_crash('sql-after-commit')

    def draft_crash(self,point):
        store=DiskDrafts(self.f.root/'drafts');key=json.dumps(['fiction','writing','chapter','body'])
        store.save('fiction',key,1,dict(content='虚构旧恢复草稿😀'))
        before=self.repo.get(self.f.pid);old_history=history(self.f.db)
        self.crash(point,dict(key=key))
        recovered=DiskDrafts(store.directory).list('fiction')
        self.assertEqual(recovered['corrupt'],[]);self.assertEqual(len(recovered['drafts']),1)
        self.assertEqual(recovered['drafts'][0]['values']['content'],'虚构旧恢复草稿😀' if point=='draft-before' else '虚构新恢复草稿😀')
        self.assertEqual(self.repo.get(self.f.pid),before);self.assertEqual(history(self.f.db),old_history)
        self.assertLess(sum(p.stat().st_size for p in self.f.root.rglob('*') if p.is_file()),8*1024**2)
        store.save('fiction',key,3,dict(content='虚构重开后草稿'))
        self.assertEqual(store.list('fiction')['drafts'][0]['values']['content'],'虚构重开后草稿')

    def test_owned_kill_before_atomic_draft_replace_preserves_old_record(self):self.draft_crash('draft-before')
    def test_owned_kill_after_atomic_draft_replace_preserves_new_record(self):self.draft_crash('draft-after')


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--owned-worker':owned_worker(*sys.argv[2:])
    else:unittest.main()
