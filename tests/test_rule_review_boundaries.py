"""Semantic review cancellation, streaming, immutable history and copy boundaries."""
from contextlib import contextmanager
from copy import deepcopy
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json,threading,time,unittest
from unittest.mock import patch
from uuid import uuid4
import test_chapter_writing as fixtures
import test_rule_semantic_reviews as semantic
opinion=semantic.opinion
from test_sse_protocols import event,chat
from novel_writer.application.rule_reviews import RuleReviewCoordinator,emit
from novel_writer.domain.rule_reviews import RuleReviewTask,rule_messages,source_digest
from novel_writer.domain.tasks import parse,encode

@contextmanager
def stream(protocol,text,truncated=False):
 calls=[];ready=threading.Event();release=threading.Event()
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def do_POST(self):
   calls.append(dict(body=json.loads(self.rfile.read(int(self.headers['Content-Length']))),path=self.path,accept=self.headers.get('Accept')))
   if protocol=='openai-chat':head=event(chat(text));tail=event(chat('','stop'))+b'data: [DONE]\r\n\r\n'
   elif protocol=='anthropic-messages':
    head=event(dict(type='message_start',message=dict(id='fiction',role='assistant',content=[])),'message_start')+event(dict(type='content_block_start',index=0,content_block=dict(type='text',text='')),'content_block_start')+event(dict(type='content_block_delta',index=0,delta=dict(type='text_delta',text=text)),'content_block_delta')
    tail=event(dict(type='content_block_stop',index=0),'content_block_stop')+event(dict(type='message_delta',delta=dict(stop_reason='end_turn')),'message_delta')+event(dict(type='message_stop'),'message_stop')
   else:head=event(dict(candidates=[dict(index=0,content=dict(role='model',parts=[dict(text=text)]))]));tail=event(dict(candidates=[dict(index=0,finishReason='STOP')]))
   if truncated:tail=b''
   self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(head)+len(tail)));self.end_headers()
   try:
    for byte in head:self.wfile.write(bytes([byte]));self.wfile.flush()
    ready.set();release.wait(4);self.wfile.write(tail);self.wfile.flush()
   except OSError:pass
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True;thread=threading.Thread(target=server.serve_forever,kwargs=dict(poll_interval=.01),daemon=True);thread.start()
 try:yield dict(url='http://127.0.0.1:'+str(server.server_port)+'/v1',calls=calls,ready=ready,release=release,text=text)
 finally:release.set();server.shutdown();server.server_close();thread.join(2)

class RuleReviewBoundaryTests(unittest.TestCase):
 setUp=semantic.RuleSemanticReviewTests.setUp
 action=semantic.RuleSemanticReviewTests.action
 connection=semantic.RuleSemanticReviewTests.connection
 setup_review=semantic.RuleSemanticReviewTests.setup_review
 prepare_review=semantic.RuleSemanticReviewTests.prepare_review
 run_review=semantic.RuleSemanticReviewTests.run_review
 def start(self,view):return self.review.start(self.pid,view['task']['id'],dict(confirm_external=True,request_sha256=view['task']['binding']['request_sha256']))
 def test_v36_describe_preview_are_byte_preserving_and_do_not_upgrade(self):
  from hashlib import sha256
  self.setup_review();self.rules.bind_task(self.pid,dict(request_id=str(uuid4()),chapter_id=self.cid,task_type='draft_chapter'));before=self.service.get(self.pid);self.assertEqual(before['workspace_version'],36);digest=sha256(self.db.read_bytes()).hexdigest();self.assertEqual(self.review.describe(self.pid)['tasks'],[]);self.review.preview(self.pid,dict(chapter_id=self.cid,target_task_id=None));self.assertEqual(self.service.get(self.pid),before);self.assertEqual(sha256(self.db.read_bytes()).hexdigest(),digest)
 def test_strict_unicode_duplicate_keys_two_sides_and_unknown_conflict(self):
  from novel_writer.domain.rule_reviews import verify_output
  preview=self.setup_review();text=opinion(preview['rules']);value=json.loads(text)
  for alter in (lambda v:v['findings'][0]['evidence'][0].update(start=True),lambda v:v['findings'][0]['evidence'][0].update(end=len(preview['rules'][0]['text'])+1),lambda v:v['findings'][0]['evidence'][0].update(quote=''),lambda v:v['findings'][0]['evidence'].append(deepcopy(v['findings'][0]['evidence'][0])),lambda v:v['findings'][0].update(category='confirmed_conflict')):
   bad=deepcopy(value);alter(bad)
   with self.assertRaises(ValueError):verify_output(json.dumps(bad),preview['rules'])
  with self.assertRaises(ValueError):verify_output(text.replace('"overview":','"overview":"duplicate", "overview":',1),preview['rules'])
  self.assertEqual(verify_output('{"overview":"未提供意见，不代表没有冲突","findings":[]}',preview['rules'])['findings'],[])
 def test_three_protocol_sse_preview_is_temporary_then_exact_valid_opinion(self):
  preview=self.setup_review()
  for protocol in ('openai-chat','anthropic-messages','gemini-content'):
   with self.subTest(protocol=protocol),stream(protocol,opinion(preview['rules'])) as wire:
    c=self.connection(wire,protocol=protocol);self.providers.manage(id=c['id'],action='stream_profile',confirmed=True,stream_mode='sse');view,_=self.prepare_review(c);self.assertEqual(wire['calls'],[]);self.start(view);self.assertTrue(wire['ready'].wait(2))
    deadline=time.monotonic()+2
    while time.monotonic()<deadline:
     live=self.review.describe(self.pid,view['task']['id'])
     if live.get('stream_preview',{}).get('text')==wire['text']:break
     time.sleep(.01)
    self.assertEqual(live['stream_preview']['text'],wire['text']);state=self.service.get(self.pid);self.assertEqual(state['rule_review_results'],[] if protocol=='openai-chat' else state['rule_review_results']);self.assertFalse(any(r['task_id']==view['task']['id'] for r in state['rule_review_results']));self.assertNotIn('stream_preview',json.dumps(state));wire['release'].set();self.engine.wait_idle(5);done=self.review.describe(self.pid,view['task']['id']);self.assertEqual(done['status'],'succeeded',done);self.assertNotIn('stream_preview',done);self.assertEqual(wire['calls'][0]['body'],json.loads(view['task']['binding']['request_body']));self.assertEqual(wire['calls'][0]['accept'],'text/event-stream');self.assertEqual(len(wire['calls']),1)
 def test_cancel_timeout_and_truncation_never_create_opinion_or_resend(self):
  preview=self.setup_review()
  for kind in ('cancel','timeout','truncated'):
   with self.subTest(kind=kind),stream('openai-chat',opinion(preview['rules']),kind=='truncated') as wire:
    c=self.connection(wire);self.providers.manage(id=c['id'],action='stream_profile',confirmed=True,stream_mode='sse');view,_=self.prepare_review(c,timeout_ms=150 if kind=='timeout' else 2000);self.start(view);self.assertTrue(wire['ready'].wait(2))
    if kind=='cancel':self.review.cancel(self.pid,view['task']['id'])
    if kind=='timeout':time.sleep(.22)
    wire['release'].set();self.engine.wait_idle(5);done=self.review.describe(self.pid,view['task']['id']);self.assertEqual(done['status'],'cancelled' if kind=='cancel' else 'failed',done);self.assertFalse(any(r['output'] for r in done['results']));self.assertNotIn('stream_preview',done)
    with self.assertRaises(ValueError):self.start(view)
    self.assertEqual(len(wire['calls']),1)
 def test_confirmation_config_budget_and_duplicate_content_additions(self):
  preview=self.setup_review()
  with fixtures.supplier(output=opinion(preview['rules'])) as wire:
   c=self.connection(wire);view,request=self.prepare_review(c,budget_max_calls=1,budget_max_output_tokens=1024);before=self.service.get(self.pid)
   for confirm in ({},dict(confirm_external=False,request_sha256=view['task']['binding']['request_sha256']),dict(confirm_external=True,request_sha256='0'*64),dict(confirm_external=True,request_sha256=view['task']['binding']['request_sha256'],force=True)):
    with self.assertRaises(ValueError):self.review.start(self.pid,view['task']['id'],confirm)
    self.assertEqual(self.service.get(self.pid),before)
   self.assertEqual(self.review.prepare(self.pid,request)['task'],view['task']);self.assertEqual(self.service.get(self.pid),before)
   with self.assertRaises(ValueError):self.review.prepare(self.pid,dict(request,timeout_ms=1000))
   self.assertTrue(self.engine.slot.acquire(blocking=False))
   try:
    with self.assertRaises(ValueError):self.start(view)
   finally:self.engine.slot.release()
   self.assertEqual(self.service.get(self.pid),before);self.assertEqual(wire['calls'],[])
   self.assertEqual(self.run_review(view)['status'],'succeeded');second,_=self.prepare_review(c,budget_max_calls=1,budget_max_output_tokens=1024)
   with self.assertRaises(ValueError):self.start(second)
   third,_=self.prepare_review(c);self.providers.manage(id=c['id'],action='stream_profile',confirmed=True,stream_mode='sse')
   with self.assertRaises(ValueError):self.start(third)
   self.assertEqual(len(wire['calls']),1)
  with fixtures.supplier() as wire:
   view,_=self.prepare_review(self.connection(wire));r=preview['rules'][0];self.rules.save(self.pid,dict(operation_id=str(uuid4()),rule_id=None,scope='chapter',scope_id=self.cid,kind=r['kind'],text=r['text'],enabled=True))
   with self.assertRaises(ValueError):self.start(view)
   self.assertEqual(wire['calls'],[])
 def test_worker_rechecks_rules_and_atomic_prepare_failure_keeps_state(self):
  preview=self.setup_review()
  with fixtures.supplier(output=opinion(preview['rules'])) as wire:
   c=self.connection(wire);before=self.service.get(self.pid)
   with patch('novel_writer.application.rule_reviews.emit',side_effect=RuntimeError('fiction atomic failure')):
    with self.assertRaises(RuntimeError):self.prepare_review(c)
   self.assertEqual(self.service.get(self.pid),before);view,_=self.prepare_review(c)
   def worker(task,attempt,token):
    self.rules.set_enabled(self.pid,dict(rule_id=preview['rules'][0]['id'],enabled=False));return original(task,attempt,token)
   original=self.review._worker
   with patch.object(self.review,'_worker',worker):self.start(view);self.engine.wait_idle(5)
   done=self.review.describe(self.pid,view['task']['id']);self.assertEqual(done['status'],'failed');self.assertEqual(wire['calls'],[])
 def test_exact_backup_double_copy_preserves_wire_citations_and_revokes_pending_permission(self):
  from novel_writer.application.backups import create_backup,restore_backup
  from novel_writer.application.migrations import migrate
  from novel_writer.application.skill_import import SkillLibrary
  from novel_writer.application.service import NovelService
  from novel_writer.storage.sqlite_repository import SQLiteRepository
  from novel_writer.application.tasks import TaskCoordinator
  from novel_writer.application.task_protocol import AdapterRegistry
  preview=self.setup_review();self.action('save_writing_rules',dict(content='旧本书规则原文'))
  preview=self.review.preview(self.pid,dict(chapter_id=self.cid,target_task_id=None))
  with fixtures.supplier(output=opinion(preview['rules'])) as wire:
   c=self.connection(wire);view,_=self.prepare_review(c);done=self.run_review(view);pending,_=self.prepare_review(c);state=self.service.get(self.pid);SkillLibrary(self.db);package=self.root/'review.nwbak';self.assertEqual(create_backup(self.db,package)['backup_format_version'],51);restored=restore_backup(package,self.root/'restore');self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid),state)
   for index in range(2):
    target=self.root/('copy'+str(index)+'.sqlite3');SQLiteRepository(target);SkillLibrary(target);copied=migrate(package,target,operation_id=str(uuid4()));pid=copied['projects'][0]['new_id'];service=NovelService(SQLiteRepository(target));engine=TaskCoordinator(service,AdapterRegistry());self.addCleanup(engine.close);coordinator=RuleReviewCoordinator(engine,self.providers,enabled=True);listing=coordinator.describe(pid);success,pending_copy=listing['tasks'];self.assertTrue(success['source_fresh']);self.assertEqual(success['task']['binding']['request_body'],done['task']['binding']['request_body']);self.assertEqual(success['results'][0]['output'],done['results'][0]['output']);self.assertEqual(len(success['task']['copy_mappings']),index+1);self.assertEqual(pending_copy['display_status'],'interrupted')
    with self.assertRaises(ValueError):coordinator.start(pid,pending_copy['task']['id'],dict(confirm_external=True,request_sha256=pending_copy['task']['binding']['request_sha256']))
    package=self.root/('copy'+str(index)+'.nwbak');create_backup(target,package)
   self.assertEqual(len(wire['calls']),1)
 def test_history_rejects_coherent_missing_rule_freeze_and_output_tampering(self):
  from novel_writer.domain.connections import request_payload
  from novel_writer.domain.model_contract import request_digest
  preview=self.setup_review()
  with fixtures.supplier(output=opinion(preview['rules'])) as wire:
   view,_=self.prepare_review(self.connection(wire));before=self.service.get(self.pid)
   def corrupt(state):
    task=deepcopy(view['task']);task['id']=str(uuid4());task['request_id']=str(uuid4());task['source_revision']=state['revision'];task['rules']=task['rules'][:1];task['wire_source']['rules']=task['rules'];task['source_sha256']=source_digest(self.pid,self.cid,None,task['rules']);body=json.dumps(request_payload('openai-chat',rule_messages(self.pid,self.cid,None,task['rules']),task['binding']),ensure_ascii=False,sort_keys=True,separators=(',',':'));task['binding']['request_body']=body;task['binding']['request_sha256']=request_digest(body,parse(RuleReviewTask,view['task']).binding.destination);state['rule_review_tasks'].append(task);emit(state,parse(RuleReviewTask,task),'prepared','pending');return state,True
   with self.assertRaises(ValueError):self.service.repository.atomic(self.pid,corrupt)
   self.assertEqual(self.service.get(self.pid),before);done=self.run_review(view);before=self.service.get(self.pid)
   def forged(state):state['rule_review_results'][0]['output']['findings'][0]['evidence'][0]['quote']='伪造';return state,True
   with self.assertRaises(ValueError):self.service.repository.atomic(self.pid,forged)
   self.assertEqual(self.service.get(self.pid),before)
 def test_reopen_has_no_permission_and_explicit_recovery_never_sends(self):
  from novel_writer.application.tasks import TaskCoordinator
  from novel_writer.application.task_protocol import AdapterRegistry
  preview=self.setup_review()
  with fixtures.supplier() as wire:
   view,_=self.prepare_review(self.connection(wire))
   def running(state):emit(state,parse(RuleReviewTask,view['task']),'started','running',str(uuid4()));return state,True
   self.service.repository.atomic(self.pid,running);engine=TaskCoordinator(self.service,AdapterRegistry());self.addCleanup(engine.close);other=RuleReviewCoordinator(engine,self.providers,enabled=True);self.assertEqual(other.describe(self.pid,view['task']['id'])['display_status'],'interrupted')
   with self.assertRaises(ValueError):other.start(self.pid,view['task']['id'],dict(confirm_external=True,request_sha256=view['task']['binding']['request_sha256']))
   self.assertEqual(other.recover(self.pid)['interrupted'],[view['task']['id']]);self.assertEqual(other.describe(self.pid,view['task']['id'])['status'],'interrupted');self.assertEqual(wire['calls'],[])

if __name__=='__main__':unittest.main()
