"""Explicit single-chapter summaries reuse model reports and manual memory gates."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json,threading,unittest
from uuid import uuid4
from copy import deepcopy
import test_configured_tasks as fixtures
from novel_writer.application import semantic_summaries
from novel_writer.domain.connections import canonical_messages

@contextmanager
def summary_wire(protocol='openai-chat',bad=None):
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));messages=canonical_messages(body,protocol);source=json.loads(messages[1]['content']);calls.append(dict(body=body,messages=messages,source=source));text=source['sources'][0]['text'];quote=dict(source_index=0,start=0,end=len(text),quote=text)
            proposal=dict(kind='chapter_summary',title='本章语义概括',text='作者保存了虚构原稿，模型摘要仍待核实。',assessment='model_summary',evidence=[quote]);value=dict(overview='摘要待核实',findings=[],proposals=[proposal],bridges=[])
            if bad=='cross':quote['source_index']=1
            elif bad=='wrong':quote['quote']='编造引用'
            elif bad=='inference':proposal['assessment']='model_inference'
            elif bad=='empty':proposal['evidence']=[]
            elif bad=='findings':value['findings']=[dict(category='quality',statement='不该有审核',assessment='model_opinion',evidence=[quote])]
            elif bad=='many':value['proposals'].append(deepcopy(proposal))
            content=json.dumps(value,ensure_ascii=False)
            if protocol=='anthropic-messages':payload=dict(role='assistant',content=[dict(type='text',text=content)],stop_reason='end_turn')
            elif protocol=='gemini-content':payload=dict(candidates=[dict(content=dict(role='model',parts=[dict(text=content)]),finishReason='STOP')])
            else:payload=dict(choices=[dict(message=dict(role='assistant',content=content),finish_reason='stop')])
            data=json.dumps(payload,ensure_ascii=False).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True;t=threading.Thread(target=server.serve_forever,kwargs=dict(poll_interval=.01),daemon=True);t.start()
    try:yield dict(url='http://127.0.0.1:'+str(server.server_port)+'/v1',calls=calls)
    finally:server.shutdown();server.server_close();t.join(2)

class SummaryTests(unittest.TestCase):
    setUp=fixtures.ConfiguredTaskTests.setUp
    save=fixtures.ConfiguredTaskTests.save
    def prepare(self,c,**overrides):
        request=dict(request_id=str(uuid4()),chapter_id=self.cid,expected_revision=self.service.get(self.pid)['revision'],instruction='只摘要已保存正文',max_output_chars=10000,timeout_ms=3000,model_options=dict(adapter_id='configured-http-v2',connection_id=c['id'],model_id='fiction-model',temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=True,prompt_version='chapter-summary-json-1'))
        request.update(overrides);return semantic_summaries.prepare(self.engine,self.pid,request)
    def execute(self,task):
        b=task['frozen']['parameters']['binding'];self.engine.start(self.pid,task['id'],dict(confirm_external=True,request_sha256=b['request_sha256']));self.engine.wait_idle(5);return self.engine.describe(self.pid,task['id'])
    def accept(self,view,identity=None):
        report=view['model_reports'][0];detail=self.engine.model_review(self.pid,report['id']);p=detail['proposals'][0]
        return self.engine.decide_model_proposal(self.pid,report['id'],dict(decision_id=identity or str(uuid4()),proposal_id=p['id'],decision='accepted',expected_revision=self.service.get(self.pid)['revision'],confirm_inference=True,preserve_conflicts=True))
    def test_three_protocols_summary_is_proposal_only_then_explicit_new_memory(self):
        for protocol in ('openai-chat','anthropic-messages','gemini-content'):
            with self.subTest(protocol=protocol),summary_wire(protocol) as wire:
                c=self.save(wire['url'],protocol);before=self.service.get(self.pid);task=self.prepare(c)['task'];self.assertEqual(wire['calls'],[]);self.assertEqual(task['task_type'],'audit_chapter');self.assertEqual(self.service.get(self.pid)['workspace_version'],34)
                self.assertEqual(task['frozen']['context_text'],'');self.assertEqual(len(task['frozen']['parameters']['sources']),1)
                view=self.execute(task);self.assertEqual(view['task']['status'],'succeeded',view);self.assertEqual(view['candidates'],[]);state=self.service.get(self.pid);self.assertEqual(state['memories'],before.get('memories',[]));self.assertEqual(state['document'],before['document']);self.assertEqual(len(wire['calls']),1);self.assertEqual(wire['calls'][0]['source']['sources'][0]['text'],'作者保存的虚构原稿。')
                identity=str(uuid4());receipt=self.accept(view,identity);self.assertEqual(self.accept(view,identity),receipt);state=self.service.get(self.pid);self.assertEqual(len(state['memories']),len(before.get('memories',[]))+1);self.assertEqual(state['memories'][-1]['kind'],'chapter_summary');self.assertEqual(state.get('memory_rollups',[]),before.get('memory_rollups',[]));self.assertEqual(state['document'],before['document'])
    def test_wrong_or_cross_quotes_inference_and_other_outputs_have_no_proposal(self):
        for bad in ('cross','wrong','inference','empty','findings','many'):
            with self.subTest(bad=bad),summary_wire(bad=bad) as wire:
                view=self.execute(self.prepare(self.save(wire['url']))['task']);self.assertEqual(view['task']['status'],'failed');self.assertEqual(view['model_reports'],[]);self.assertEqual(self.service.get(self.pid)['memories'],[])
    def memory(self):
        return self.service.execute(self.pid,'save_memory',dict(kind='event',title='新记忆',text='作者新记忆',position_chapter_id=self.cid,confirmed=True,active=True,source=dict(kind='chapter',entity_id=self.cid)),expected_revision=self.service.get(self.pid)['revision'])
    def test_memory_or_body_changes_block_actual_send_and_accept(self):
        with summary_wire() as wire:
            c=self.save(wire['url']);task=self.prepare(c)['task'];self.memory()
            with self.assertRaises(ValueError):self.execute(task)
            self.assertEqual(wire['calls'],[]);view=self.execute(self.prepare(c)['task']);self.memory()
            with self.assertRaises(ValueError):self.accept(view)
            self.assertEqual(self.service.get(self.pid)['model_proposal_receipts'],[])
            task=self.prepare(c)['task'];self.service.execute(self.pid,'save_chapter',dict(chapter_id=self.cid,content='作者修改正文🙂'),expected_revision=self.service.get(self.pid)['revision'])
            with self.assertRaises(ValueError):self.execute(task)
    def test_unknown_fields_and_blank_body_refused_without_write_or_call(self):
        with summary_wire() as wire:
            c=self.save(wire['url']);before=self.service.get(self.pid)
            with self.assertRaises(ValueError):self.prepare(c,source='伪造来源')
            self.assertEqual(self.service.get(self.pid),before);self.assertEqual(wire['calls'],[])
            self.service.execute(self.pid,'save_chapter',dict(chapter_id=self.cid,content=''),expected_revision=before['revision']);before=self.service.get(self.pid)
            with self.assertRaises(ValueError):self.prepare(c)
            self.assertEqual(self.service.get(self.pid),before)
    def test_prepare_idempotent_and_connection_change_refuses_old_proposal(self):
        with summary_wire() as wire:
            c=self.save(wire['url']);before=self.service.get(self.pid);request=dict(request_id=str(uuid4()),chapter_id=self.cid,expected_revision=before['revision'],instruction='只摘要正文',max_output_chars=10000,timeout_ms=3000,model_options=dict(adapter_id='configured-http-v2',connection_id=c['id'],model_id='fiction-model',temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=True,prompt_version='chapter-summary-json-1'))
            result=semantic_summaries.prepare(self.engine,self.pid,request);self.assertEqual(semantic_summaries.prepare(self.engine,self.pid,request)['task'],result['task']);view=self.execute(result['task']);self.providers.manage(id=c['id'],action='limits',confirmed=True,min_interval_ms=1,requests_per_minute=0)
            with self.assertRaises(ValueError):self.accept(view)
            self.assertTrue(self.engine.model_review(self.pid,view['model_reports'][0]['id'])['outdated']);self.assertEqual(self.service.get(self.pid)['model_proposal_receipts'],[])
    def test_v34_exact_restore_copy_legacy_omission_and_downgrade_rejection(self):
        from novel_writer.application.backups import create_backup,restore_backup
        from novel_writer.application.migrations import migrate
        from novel_writer.application.skill_import import SkillLibrary
        from novel_writer.application.service import NovelService
        from novel_writer.storage.sqlite_repository import SQLiteRepository,validate_workspace
        with summary_wire() as wire:
            c=self.save(wire['url']);task=self.prepare(c)['task'];view=self.execute(task);state=self.service.get(self.pid);old=deepcopy(state);old['workspace_version']=33
            with self.assertRaises(ValueError):validate_workspace(old)
            db=self.root/'fiction.sqlite3';SkillLibrary(db);package=self.root/'summary.nwbak';self.assertEqual(create_backup(db,package)['backup_format_version'],51)
            restored=restore_backup(package,self.root/'summary-restored');self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid),state)
            target=self.root/'summary-copy.sqlite3';SQLiteRepository(target);SkillLibrary(target);copied=migrate(package,target,operation_id=str(uuid4()));clone=NovelService(SQLiteRepository(target)).get(copied['projects'][0]['new_id']);self.assertEqual(clone['generation_tasks'][0]['frozen']['parameters']['binding'],task['frozen']['parameters']['binding']);self.assertEqual(clone['generation_tasks'][0]['frozen']['parameters']['summary_memory_sha256'],task['frozen']['parameters']['summary_memory_sha256']);self.assertEqual(len(clone['model_memory_proposals']),1)
            legacy=fixtures.ConfiguredTaskTests.prepare(self,c)['task'];self.assertNotIn('summary_memory_sha256',legacy['frozen']['parameters']);self.assertEqual(len(wire['calls']),1)
