"""Real delayed loopback responses; no provider account or production database."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json, threading, time, unittest
from copy import deepcopy
from uuid import uuid4
import test_creative_dialogue as dialogue_fixture
import test_chapter_writing as writing_fixture
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository, validate_workspace

@contextmanager
def delayed(output, delay=31):
    calls=[]; seen=threading.Event(); release=threading.Event(); finished=threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            calls.append(json.loads(self.rfile.read(int(self.headers['Content-Length'])))); seen.set()
            release.wait(delay)
            raw=json.dumps(dict(id='fiction-delayed',model='fiction-selected',choices=[dict(message=dict(role='assistant',content=output),finish_reason='stop')])).encode()
            try:
                self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
            except OSError: pass
            finally: finished.set()
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler); worker=threading.Thread(target=server.serve_forever,daemon=True); worker.start()
    try: yield dict(url='http://127.0.0.1:'+str(server.server_port)+'/v1',calls=calls,seen=seen,release=release,finished=finished)
    finally: release.set(); server.shutdown(); server.server_close(); worker.join(2)

class LongDialogueTests(unittest.TestCase):
    setUp=dialogue_fixture.CreativeDialogueTests.setUp
    dialogue=dialogue_fixture.CreativeDialogueTests.dialogue
    plan_text=dialogue_fixture.CreativeDialogueTests.plan_text
    request=dialogue_fixture.CreativeDialogueTests.request
    connection=dialogue_fixture.CreativeDialogueTests.connection
    options=dialogue_fixture.CreativeDialogueTests.options
    def test_31_second_dialogue_and_v30_exact_backup_restore_copy(self):
        from novel_writer.application.backups import create_backup,restore_backup
        from novel_writer.application.migrations import migrate
        from novel_writer.application.skill_import import SkillLibrary
        dialogue,session=self.dialogue(); original=self.service.get(self.pid)['document']
        with delayed(self.plan_text()) as wire:
            task=dialogue.prepare(self.pid,self.request(session,self.connection(wire),'虚构长请求',timeout_ms=120000))['task']
            self.assertEqual(task['timeout_ms'],120000); start=time.monotonic()
            self.ai.start(self.pid,task['id'],dict(confirm_external=True,request_sha256=task['binding']['request_sha256'])); self.shared.wait_idle(40)
            done=self.ai.describe(self.pid,task['id']); self.assertEqual(done['status'],'succeeded',done); self.assertGreaterEqual(time.monotonic()-start,30.8)
            state=self.service.get(self.pid); self.assertEqual(state['workspace_version'],30); self.assertEqual(state['document'],original)
            frozen=deepcopy(task); self.assertEqual(done['task'],frozen)
            old=deepcopy(state); old['workspace_version']=29
            with self.assertRaises(ValueError): validate_workspace(old)
            SkillLibrary(self.db); package=self.root/'long.nwbak'; self.assertEqual(create_backup(self.db,package)['backup_format_version'],51)
            restored=restore_backup(package,self.root/'long-restore'); self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid),state)
            target=self.root/'long-copy.sqlite3'; SQLiteRepository(target); SkillLibrary(target); result=migrate(package,target,operation_id=str(uuid4()))
            clone=NovelService(SQLiteRepository(target)).get(result['projects'][0]['new_id']); self.assertEqual(clone['book_ai_tasks'][0]['timeout_ms'],120000); self.assertEqual(clone['book_ai_tasks'][0]['binding'],frozen['binding'])
            self.assertEqual(NovelService(SQLiteRepository(self.db)).get(self.pid),state); self.assertEqual(len(wire['calls']),1)
    def test_short_timeout_and_cancel_have_no_late_candidate_or_resend(self):
        dialogue,session=self.dialogue()
        for cancel in (False,True):
            with self.subTest(cancel=cancel),delayed(self.plan_text()) as wire:
                task=dialogue.prepare(self.pid,self.request(session,self.connection(wire),'超时或取消',timeout_ms=120000 if cancel else 150))['task']
                self.ai.start(self.pid,task['id'],dict(confirm_external=True,request_sha256=task['binding']['request_sha256'])); self.assertTrue(wire['seen'].wait(2)); start=time.monotonic()
                if cancel:self.ai.cancel(self.pid,task['id'])
                self.shared.wait_idle(3); self.assertLess(time.monotonic()-start,2)
                wire['release'].set(); self.assertTrue(wire['finished'].wait(2)); view=self.ai.describe(self.pid,task['id'])
                self.assertEqual(view['status'],'cancelled' if cancel else 'failed'); self.assertIsNone(view['latest_candidate'])
                if not cancel:self.assertEqual(view['responses'][-1]['response']['error_code'],'timeout')
                state=self.service.get(self.pid); self.assertEqual(NovelService(SQLiteRepository(self.db)).get(self.pid),state); self.assertEqual(len(wire['calls']),1)

class LongManuscriptTests(unittest.TestCase):
    setUp=writing_fixture.ChapterWritingTests.setUp
    action=writing_fixture.ChapterWritingTests.action
    options=writing_fixture.ChapterWritingTests.options
    prepare=writing_fixture.ChapterWritingTests.prepare
    connection=writing_fixture.ChapterWritingTests.connection
    def test_31_second_manuscript_keeps_body_and_frozen_limits(self):
        with delayed('门外的风吹过。') as wire:
            task=self.prepare(self.connection(wire),timeout=60000)['task']; before=self.service.get(self.pid)['document']; start=time.monotonic()
            self.engine.start(self.pid,task['id'],dict(confirm_external=True,request_sha256=task['frozen']['parameters']['binding']['request_sha256'])); self.engine.wait_idle(40)
            view=self.engine.describe(self.pid,task['id']); self.assertEqual(view['task']['status'],'succeeded',view); self.assertGreaterEqual(time.monotonic()-start,30.8)
            self.assertEqual(view['task']['frozen'],task['frozen']); self.assertEqual(task['frozen']['parameters']['timeout_ms'],60000); self.assertEqual(task['frozen']['parameters']['max_output_chars'],2000)
            state=self.service.get(self.pid); self.assertEqual(state['document'],before); self.assertEqual(state['workspace_version'],30); self.assertEqual(NovelService(SQLiteRepository(self.db)).get(self.pid),state); self.assertEqual(len(wire['calls']),1)
    def test_timeout_bounds_reject_without_preparing_task(self):
        with delayed('门') as wire:
            c=self.connection(wire)
            for value in (99,300001,True,120000.0):
                with self.subTest(value=value),self.assertRaises(ValueError):self.prepare(c,timeout=value)
            self.assertEqual(self.service.get(self.pid).get('generation_tasks',[]),[]); self.assertEqual(wire['calls'],[])
