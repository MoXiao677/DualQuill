"""Real loopback transport, frozen tasks and transient progress integration."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json,threading,time,unittest
from copy import deepcopy
from uuid import uuid4
import test_configured_tasks as fixtures
from test_sse_protocols import event,chat

@contextmanager
def stream_wire(protocol='openai-chat',bad=None):
    calls=[];ready=threading.Event();release=threading.Event()
    text='虚构流式候选🙂'
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append(dict(path=self.path,body=body,accept=self.headers.get('Accept')))
            if protocol=='openai-chat':head=event(chat(text));tail=event(chat('', 'stop'))+b'data: [DONE]\r\n\r\n'
            elif protocol=='anthropic-messages':
                head=event(dict(type='message_start',message=dict(id='fake',role='assistant',content=[])),'message_start')+event(dict(type='content_block_start',index=0,content_block=dict(type='text',text='')),'content_block_start')+event(dict(type='content_block_delta',index=0,delta=dict(type='text_delta',text=text)),'content_block_delta')
                tail=event(dict(type='content_block_stop',index=0),'content_block_stop')+event(dict(type='message_delta',delta=dict(stop_reason='end_turn')),'message_delta')+event(dict(type='message_stop'),'message_stop')
            else:
                head=event(dict(candidates=[dict(index=0,content=dict(role='model',parts=[dict(text=text)]))]))
                tail=event(dict(candidates=[dict(index=0,finishReason='STOP')]))
            if bad=='secret':head=event(chat('safe fiction-configured-'))+event(chat('key'));tail=b''
            if bad=='truncated':tail=b''
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(head)+len(tail)));self.end_headers()
            try:
                for byte in head:self.wfile.write(bytes([byte]));self.wfile.flush()
                ready.set();release.wait(4)
                self.wfile.write(tail);self.wfile.flush()
            except OSError:pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True;worker=threading.Thread(target=server.serve_forever,kwargs=dict(poll_interval=.01),daemon=True);worker.start()
    try:yield dict(url='http://127.0.0.1:'+str(server.server_port)+'/v1',calls=calls,ready=ready,release=release,text=text)
    finally:release.set();server.shutdown();server.server_close();worker.join(2)

class SSETaskTests(unittest.TestCase):
    setUp=fixtures.ConfiguredTaskTests.setUp
    save=fixtures.ConfiguredTaskTests.save
    prepare=fixtures.ConfiguredTaskTests.prepare
    def setup_stream(self,wire,protocol='openai-chat'):
        c=self.save(wire['url'],protocol);self.providers.manage(id=c['id'],action='stream_profile',confirmed=True,stream_mode='sse');return c
    def start(self,task):
        b=task['frozen']['parameters']['binding'];return self.engine.start(self.pid,task['id'],dict(confirm_external=True,request_sha256=b['request_sha256']))
    def test_three_protocols_preview_before_completion_exact_wire_and_no_persistence(self):
        for protocol in ('openai-chat','anthropic-messages','gemini-content'):
            with self.subTest(protocol=protocol),stream_wire(protocol) as wire:
                task=self.prepare(self.setup_stream(wire,protocol))['task'];binding=task['frozen']['parameters']['binding'];self.assertEqual(binding['destination']['stream_mode'],'sse');self.assertEqual(self.service.get(self.pid)['workspace_version'],33)
                self.start(task);self.assertTrue(wire['ready'].wait(2));deadline=time.monotonic()+2
                while time.monotonic()<deadline:
                    view=self.engine.describe(self.pid,task['id'])
                    if view.get('stream_preview',{}).get('text')==wire['text']:break
                    time.sleep(.01)
                self.assertEqual(view['stream_preview'],dict(text=wire['text'],chars=len(wire['text']),temporary=True));self.assertEqual(view['candidates'],[])
                state=self.service.get(self.pid);self.assertNotIn('stream_preview',json.dumps(state));self.assertEqual(state['document']['chapters'][0]['content'],'作者保存的虚构原稿。')
                wire['release'].set();self.engine.wait_idle(5);done=self.engine.describe(self.pid,task['id']);self.assertEqual(done['task']['status'],'succeeded',done);self.assertEqual(done['candidates'][0]['output_text'],wire['text']);self.assertNotIn('stream_preview',done);self.assertEqual(done['task']['frozen'],task['frozen'])
                self.assertEqual(wire['calls'][0]['body'],json.loads(binding['request_body']));self.assertEqual(wire['calls'][0]['accept'],'text/event-stream');self.assertEqual(len(wire['calls']),1)
                if protocol=='gemini-content':self.assertEqual(wire['calls'][0]['path'],'/v1/models/fiction-model:streamGenerateContent?alt=sse')
                else:self.assertIs(wire['calls'][0]['body']['stream'],True)
    def test_truncated_and_secret_streams_fail_without_candidate_or_secret(self):
        for bad in ('truncated','secret'):
            with self.subTest(bad=bad),stream_wire(bad=bad) as wire:
                task=self.prepare(self.setup_stream(wire))['task'];self.start(task);self.assertTrue(wire['ready'].wait(2));wire['release'].set();self.engine.wait_idle(5);view=self.engine.describe(self.pid,task['id']);self.assertEqual(view['task']['status'],'failed');self.assertEqual(view['candidates'],[]);self.assertNotIn('stream_preview',view);self.assertNotIn('fiction-configured-key',json.dumps(self.service.get(self.pid)));self.assertEqual(len(wire['calls']),1)
    def test_cancel_clears_preview_and_no_replay(self):
        with stream_wire() as wire:
            task=self.prepare(self.setup_stream(wire))['task'];self.start(task);self.assertTrue(wire['ready'].wait(2));self.engine.cancel(self.pid,task['id']);wire['release'].set();self.engine.wait_idle(5);view=self.engine.describe(self.pid,task['id']);self.assertEqual(view['task']['status'],'cancelled');self.assertNotIn('stream_preview',view);self.assertEqual(view['candidates'],[])
            with self.assertRaises(ValueError):self.start(task)
            self.assertEqual(len(wire['calls']),1)
    def test_mode_change_invalidates_permission_and_json_omits_new_field(self):
        with stream_wire() as wire:
            c=self.save(wire['url']);old=self.prepare(c)['task'];self.assertNotIn('stream_mode',old['frozen']['parameters']['binding']['destination']);self.providers.manage(id=c['id'],action='stream_profile',confirmed=True,stream_mode='sse')
            with self.assertRaises(ValueError):self.start(old)
            streamed=self.prepare(c)['task'];self.providers.manage(id=c['id'],action='stream_profile',confirmed=True,stream_mode='json')
            with self.assertRaises(ValueError):self.start(streamed)
            restored=self.prepare(c)['task'];self.assertNotIn('stream_mode',restored['frozen']['parameters']['binding']['destination']);self.assertEqual(wire['calls'],[])
    def test_v33_backup_restore_copy_downgrade_and_zero_write_reads(self):
        from novel_writer.application.backups import create_backup,restore_backup
        from novel_writer.application.migrations import migrate
        from novel_writer.application.skill_import import SkillLibrary
        from novel_writer.application.service import NovelService
        from novel_writer.storage.sqlite_repository import SQLiteRepository,validate_workspace
        with stream_wire() as wire:
            task=self.prepare(self.setup_stream(wire))['task'];state=self.service.get(self.pid);old=deepcopy(state);old['workspace_version']=32
            with self.assertRaises(ValueError):validate_workspace(old)
            db=self.root/'fiction.sqlite3';SkillLibrary(db);package=self.root/'stream.nwbak';self.assertEqual(create_backup(db,package)['backup_format_version'],51)
            restored=restore_backup(package,self.root/'restored-stream');self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid),state)
            target=self.root/'copy-stream.sqlite3';SQLiteRepository(target);SkillLibrary(target);copy=migrate(package,target,operation_id=str(uuid4()));clone=NovelService(SQLiteRepository(target)).get(copy['projects'][0]['new_id']);self.assertEqual(clone['generation_tasks'][0]['frozen']['parameters']['binding'],task['frozen']['parameters']['binding']);self.assertEqual(wire['calls'],[])
