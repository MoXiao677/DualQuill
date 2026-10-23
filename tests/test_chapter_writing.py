"""Draft/continuation use the real shared pipeline and fictional wire only."""
import importlib,json,tempfile,unittest,threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from importlib import util
from pathlib import Path
from uuid import uuid4
from novel_writer.application.service import NovelService
from novel_writer.application.provider_connections import ProviderConnections
from novel_writer.application.task_protocol import AdapterRegistry
from novel_writer.application.tasks import TaskCoordinator
from novel_writer.application.custom_protocols import ConfiguredHttpAdapter
from novel_writer.storage.sqlite_repository import SQLiteRepository
from test_book_ai import supplier

@contextmanager
def unfinished_supplier(text,finish):
 calls=[]
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def do_POST(self):
   calls.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))));raw=json.dumps(dict(id='fiction-incomplete',model='fiction-writing',choices=[dict(message=dict(role='assistant',content=text),finish_reason=finish)])).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
 try:yield dict(url='http://127.0.0.1:'+str(server.server_port)+'/v1',calls=calls)
 finally:server.shutdown();server.server_close();thread.join(2)

class ChapterWritingTests(unittest.TestCase):
 def setUp(self):
  self.assertIsNotNone(util.find_spec('novel_writer.application.chapter_writing'),'first draft / append-only continuation workflow is missing')
  self.temp=tempfile.TemporaryDirectory(prefix='novel-chapter-writing-');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.db=self.root/'fiction.sqlite3';self.service=NovelService(SQLiteRepository(self.db));state=self.service.create(title='保存 / English chapter fiction');self.pid=state['document']['project']['id'];state=self.service.execute(self.pid,'add_chapter',dict(title='初稿 / emoji'),expected_revision=state['revision']);self.cid=state['document']['chapters'][0]['id'];self.providers=ProviderConnections(self.root/'fiction.dpapi');self.adapter=ConfiguredHttpAdapter(self.providers,enabled=True);registry=AdapterRegistry()
  for capability in ('rewrite_chapter','audit_chapter','draft_chapter','continue_chapter'):registry.register(capability,self.adapter)
  self.engine=TaskCoordinator(self.service,registry);self.addCleanup(self.engine.close);self.writing=importlib.import_module('novel_writer.application.chapter_writing').ChapterWriting(self.engine,self.providers)
 def action(self,action,fields):return self.service.execute(self.pid,action,fields,expected_revision=self.service.get(self.pid)['revision'])
 def connection(self,wire,model='fiction-writing',protocol='openai-chat'):return self.providers.save_custom(id=str(uuid4()),name='虚构正文模型',base_url=wire['url'],protocol=protocol,model_id=model,api_key='fiction-writing-key',allow_local=True)
 def options(self,mode='draft',**changes):
  value=dict(chapter_id=self.cid,mode=mode,context_options=dict(chapter_id=self.cid,budget_chars=20000),instruction='只写作者这一章',target_chars=300,required_literals=['门'],forbidden_literals=['禁止样句']);value.update(changes);return value
 def prepare(self,connection,mode='draft',options=None,timeout=2000):
  options=options or self.options(mode);preview=self.writing.preview(self.pid,options);profile=dict(adapter_id='configured-http-v2',connection_id=connection['id'],model_id=connection['model_id'],temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=True,prompt_version='rewrite-1') if connection else None
  return self.writing.prepare(self.pid,dict(request_id=str(uuid4()),source_options=options,source_sha256=preview['source_sha256'],model_options=profile,max_output_chars=2000,timeout_ms=timeout,retry_of=None))
 def run_task(self,prepared):
  task=prepared['task'];self.engine.start(self.pid,task['id'],dict(confirm_external=True,request_sha256=task['frozen']['parameters']['binding']['request_sha256']));self.engine.wait_idle(5);return self.engine.describe(self.pid,task['id'])
 def adoption(self,done,correction_id=None,authorize=False):
  task=done['task'];review=self.writing.review(self.pid,task['id'],dict(candidate_id=task['candidate_id'],correction_id=correction_id));return dict(candidate_id=task['candidate_id'],adoption_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision'],authorize_confirmed=authorize,correction_id=correction_id,review_id=review['review_id'],confirmed_review=True)
 def test_empty_chapter_draft_uses_saved_idea_plan_and_rules_then_explicit_first_body_version(self):
  self.action('save_idea',dict(chapter_id=self.cid,content='送信人守在门外。'));self.action('save_chapter_outline',dict(chapter_id=self.cid,core_idea='开门前的迟疑',objective='建立悬念',story_time='第1天'));self.action('save_writing_rules',dict(content='只写限知视角，保留门外的声音。'));original=self.service.get(self.pid)['document']
  with supplier(output='门外传来一声轻响。') as wire:
   prepared=self.prepare(self.connection(wire));task=prepared['task'];self.assertEqual(task['task_type'],'draft_chapter');self.assertEqual(wire['calls'],[]);self.assertEqual(self.service.get(self.pid)['document'],original);body=task['frozen']['parameters']['binding']['request_body']
   for text in ['送信人守在门外','开门前的迟疑','建立悬念','只写限知视角','禁止样句']:self.assertIn(text,body)
   from hashlib import sha256
   self.assertEqual(json.loads(json.loads(body)['messages'][-1]['content'])['preserve_original']['sha256'],sha256(b'').hexdigest())
   done=self.run_task(prepared);self.assertEqual(done['task']['status'],'succeeded',done['task'].get('error_code'));self.assertEqual(len(wire['calls']),1);self.assertEqual(self.service.get(self.pid)['document'],original);request=self.adoption(done);receipt=self.engine.adopt(self.pid,task['id'],request);state=self.service.get(self.pid);self.assertEqual(state['document']['chapters'][0]['content'],'门外传来一声轻响。');self.assertEqual(len(state['document']['versions']),len(original['versions'])+1);self.assertEqual(self.engine.adopt(self.pid,task['id'],request),receipt);self.assertEqual(self.service.get(self.pid),state)
 def test_continuation_keeps_unicode_prefix_and_retains_original_response_and_manual_correction(self):
  original='原稿😀é\r\n门外尚有脚步。';self.action('save_chapter',dict(chapter_id=self.cid,content=original));before=self.service.get(self.pid)['document']
  with supplier(output='门慢慢开了。') as wire:
   connection=self.connection(wire)
   with self.assertRaises(ValueError):self.prepare(connection,'draft')
   prepared=self.prepare(connection,'continue');done=self.run_task(prepared);self.assertEqual(self.service.get(self.pid)['document'],before);self.assertEqual(done['candidates'][0]['output_text'],'门慢慢开了。');correction=self.writing.correct(self.pid,done['task']['id'],dict(operation_id=str(uuid4()),candidate_id=done['task']['candidate_id'],text='门缓缓开了。🚪'));request=self.adoption(done,correction['id']);self.engine.adopt(self.pid,done['task']['id'],request);text=self.service.get(self.pid)['document']['chapters'][0]['content'];self.assertEqual(text,original+'门缓缓开了。🚪');self.assertTrue(text.encode('utf-8').startswith(original.encode('utf-8')));self.assertEqual(self.engine.describe(self.pid,done['task']['id'])['candidates'][0]['output_text'],'门慢慢开了。')
 def test_task_events_do_not_stale_source_but_idea_and_configuration_changes_reject_old_execution(self):
  with supplier(output='门前的影子移动。') as wire:
   connection=self.connection(wire);first=self.prepare(connection);second=self.prepare(connection);done=self.run_task(first);self.assertEqual(done['task']['status'],'succeeded');self.action('save_idea',dict(chapter_id=self.cid,content='作者改过的真正来源'))
   with self.assertRaises(ValueError):self.engine.start(self.pid,second['task']['id'],dict(confirm_external=True,request_sha256=second['task']['frozen']['parameters']['binding']['request_sha256']))
   with self.assertRaises(ValueError):self.adoption(done)
   self.assertEqual(len(wire['calls']),1)
 def test_three_declared_protocols_receive_new_text_goal_rules_and_preservation_range(self):
  for protocol in ('openai-chat','anthropic-messages','gemini-content'):
   with self.subTest(protocol=protocol),supplier(protocol,output='门外的人点头。') as wire:
    prepared=self.prepare(self.connection(wire,protocol=protocol));done=self.run_task(prepared);self.assertEqual(done['task']['status'],'succeeded');self.assertEqual(len(wire['calls']),1);body=wire['calls'][0]['body'];encoded=json.dumps(body,ensure_ascii=False);self.assertIn('target_new_unicode_chars',encoded);self.assertIn('禁止样句',encoded);self.assertIn('preserve_original',encoded);self.assertNotIn('tools',body);self.assertEqual(self.service.get(self.pid)['document']['chapters'][0]['content'],'');self.assertEqual(done['writing']['metrics']['actual_new_chars'],len('门外的人点头。'));self.assertEqual(done['writing']['metrics']['deviation'],len('门外的人点头。')-300)
 def test_draft_preset_style_and_language_enter_actual_request_and_explicit_override_is_honored(self):
  from novel_writer.application.styles import StyleCoordinator
  from novel_writer.application.creation_presets import CreationPresets
  from test_styles import FEATURES
  styles=StyleCoordinator(self.engine,self.providers,enabled=True);card=styles.save_card(self.pid,dict(operation_id=str(uuid4()),style_id=None,name='作者的文风',prompt='只写具体动作，保持英文短句。',card=FEATURES,analysis_id=None,confirmed=True));styles.choose(self.pid,dict(operation_id=str(uuid4()),chapter_id=None,version_id=card['id'],confirmed=True))
  with supplier(output='A knock at the door. 门') as wire:
   connection=self.connection(wire);presets=CreationPresets(self.service);state=self.service.get(self.pid);made=presets.save(self.pid,dict(operation_id=str(uuid4()),preset_id=None,name='正文用途预设',settings=dict(steps=[dict(step='draft',adapter_id='configured-http-v2',connection_id=connection['id'],model_id=connection['model_id'],temperature=.4,max_tokens=768,budget_limit=1.0,allow_unknown_cost=True)],style_id=card['id'],style_prompt='Author preference KEEP ORIGINAL',manuscript_language='en',budget=dict(max_external_calls=2,max_reserved_output_tokens=2048,risk_budget=2.0,allow_unknown_cost=True)),expected_revision=state['revision']));presets.choose(self.pid,dict(operation_id=str(uuid4()),version_id=made['version_id'],confirmed=True,expected_revision=self.service.get(self.pid)['revision']));prepared=self.prepare(None);binding=prepared['task']['frozen']['parameters']['binding'];self.assertEqual(binding['temperature'],.4);self.assertEqual(binding['max_tokens'],768);self.assertEqual(binding['connection_id'],connection['id']);self.assertIn('只写具体动作',binding['request_body']);self.assertIn('Author preference KEEP ORIGINAL',binding['request_body']);self.assertIn('"manuscript_language":"en"',json.loads(binding['request_body'])['messages'][-1]['content']);done=self.run_task(prepared);self.assertEqual(done['task']['status'],'succeeded')
   override=self.prepare(connection);self.assertEqual(override['task']['frozen']['parameters']['binding']['temperature'],.3);self.assertEqual(len(wire['calls']),1)
 def test_confirmed_prefix_requires_authorization_and_changed_configuration_blocks_old_candidate(self):
  original='Confirmed 😀 prefix. 门';self.action('save_chapter',dict(chapter_id=self.cid,content=original,status='confirmed'))
  with supplier(output='New continuation 门') as wire:
   connection=self.connection(wire);done=self.run_task(self.prepare(connection,'continue'));request=self.adoption(done)
   with self.assertRaises(ValueError):self.engine.adopt(self.pid,done['task']['id'],request)
   self.assertEqual(self.service.get(self.pid)['document']['chapters'][0]['content'],original);request=self.adoption(done,authorize=True);self.engine.adopt(self.pid,done['task']['id'],request);self.assertEqual(self.service.get(self.pid)['document']['chapters'][0]['content'],original+'New continuation 门')
   fresh=self.run_task(self.prepare(connection,'continue'));self.providers.save_custom(id=connection['id'],name=connection['name'],base_url=wire['url'],protocol='openai-chat',model_id=connection['model_id'],api_key='',allow_local=True)
   with self.assertRaises(ValueError):self.adoption(fresh,authorize=True)
 def test_actual_response_arriving_at_cancellation_is_retained_without_candidate_or_body_write(self):
  with supplier(output='门外的迟到完整响应。') as wire:
   prepared=self.prepare(self.connection(wire));task=prepared['task'];before=self.service.get(self.pid)['document'];self.adapter.transport.capture_response=lambda _:self.engine.cancel(self.pid,task['id']);done=self.run_task(prepared);self.assertEqual(done['task']['status'],'cancelled');state=self.service.get(self.pid);self.assertEqual(state['document'],before);self.assertEqual(done['candidates'],[]);self.assertEqual(len(state['writing_late_results']),1);self.assertTrue(state['writing_late_results'][0]['response']['complete']);self.assertIn('门外的迟到完整响应',state['writing_late_results'][0]['response']['raw_response'])
 def test_complete_restore_and_copy_preserve_writing_corrections_decisions_and_old_v15_records(self):
  from contextlib import closing
  import sqlite3
  from novel_writer.application.backups import create_backup,restore_backup
  from novel_writer.application.migrations import migrate
  from novel_writer.application.skill_import import SkillLibrary
  from novel_writer.application.styles import StyleCoordinator
  from novel_writer.application.style_trials import TrialCoordinator
  styles=StyleCoordinator(self.engine,self.providers,enabled=True);trials=TrialCoordinator(self.engine,self.providers,styles,enabled=True)
  with supplier(output='门内传来回声。') as wire:
   connection=self.connection(wire);seed=dict(scope='custom',chapter_id=None,plan_version_id=None,fields=[],author_text='既有V15自有设定',instruction='保留旧试写准备',rubric='',target_chars=300,include_rules=False,include_preset_prompt=False,chapter_start=0,chapter_end=None);preview=trials.preview(self.pid,seed);profile=dict(adapter_id='configured-http-v2',connection_id=connection['id'],model_id=connection['model_id'],temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=True,prompt_version='rewrite-1');trials.prepare(self.pid,dict(operation_id=str(uuid4()),seed_options=seed,seed_sha256=preview['seed']['seed_sha256'],style_mode='baseline',style_version_id=None,model_options=profile,max_calls=1,max_output_tokens=512,timeout_ms=2000,retry_of=None))
   old=self.service.get(self.pid);self.assertEqual(old['workspace_version'],15);done=self.run_task(self.prepare(connection));edit=self.writing.correct(self.pid,done['task']['id'],dict(operation_id=str(uuid4()),candidate_id=done['task']['candidate_id'],text='门里的回声仍在。'));request=self.adoption(done,edit['id']);self.engine.adopt(self.pid,done['task']['id'],request);state=self.service.get(self.pid);self.assertEqual(state['workspace_version'],16);self.assertEqual(state['style_trial_tasks'],old['style_trial_tasks']);SkillLibrary(self.db);package=self.root/'writing.nwbak';self.assertEqual(create_backup(self.db,package)['backup_format_version'],51);restored=restore_backup(package,self.root/'writing-restored');self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid),state);target=self.root/'writing-copy.sqlite3';SQLiteRepository(target);SkillLibrary(target);copied=migrate(package,target,operation_id=str(uuid4()));clone=NovelService(SQLiteRepository(target)).get(copied['projects'][0]['new_id']);self.assertEqual(clone['document']['chapters'][0]['content'],'门里的回声仍在。');self.assertEqual(len(clone['writing_corrections']),1);self.assertEqual(len(clone['writing_decisions']),1);self.assertEqual(len(clone['style_trial_tasks']),1)
 def test_resaving_the_same_empty_content_changes_actual_source_version_and_blocks_old_request(self):
  with supplier(output='门前有人。') as wire:
   prepared=self.prepare(self.connection(wire));task=prepared['task'];self.action('save_chapter',dict(chapter_id=self.cid,content=''))
   with self.assertRaises(ValueError):self.engine.start(self.pid,task['id'],dict(confirm_external=True,request_sha256=task['frozen']['parameters']['binding']['request_sha256']))
   self.assertEqual(wire['calls'],[])
 def test_copied_style_candidate_can_be_freshly_reviewed_but_old_pending_permission_is_not_replayed(self):
  from novel_writer.application.styles import StyleCoordinator
  from novel_writer.application.backups import create_backup
  from novel_writer.application.migrations import migrate
  from novel_writer.application.skill_import import SkillLibrary
  from test_styles import FEATURES
  styles=StyleCoordinator(self.engine,self.providers,enabled=True);card=styles.save_card(self.pid,dict(operation_id=str(uuid4()),style_id=None,name='复制的文风',prompt='门前场景只写动作。',card=FEATURES,analysis_id=None,confirmed=True));styles.choose(self.pid,dict(operation_id=str(uuid4()),chapter_id=None,version_id=card['id'],confirmed=True))
  with supplier(output='门边有一道影子。') as wire:
   connection=self.connection(wire);done=self.run_task(self.prepare(connection));self.prepare(connection);SkillLibrary(self.db);package=self.root/'candidate-copy.nwbak';create_backup(self.db,package);target=self.root/'candidate-copy.sqlite3';SQLiteRepository(target);SkillLibrary(target);copied=migrate(package,target,operation_id=str(uuid4()));service=NovelService(SQLiteRepository(target));pid=copied['projects'][0]['new_id'];registry=AdapterRegistry()
   for cap in ('draft_chapter','continue_chapter'):registry.register(cap,self.adapter)
   engine=TaskCoordinator(service,registry);self.addCleanup(engine.close);writing=importlib.import_module('novel_writer.application.chapter_writing').ChapterWriting(engine,self.providers);state=service.get(pid);finished=next(v for v in state['generation_tasks'] if v['status']=='succeeded');pending=next(v for v in state['generation_tasks'] if v['status']=='pending');review=writing.review(pid,finished['id'],dict(candidate_id=finished['candidate_id'],correction_id=None));self.assertEqual(review['after'],'门边有一道影子。');self.assertEqual(engine.describe(pid,pending['id'])['display_status'],'interrupted')
   with self.assertRaises(ValueError):engine.start(pid,pending['id'],dict(confirm_external=True,request_sha256=pending['frozen']['parameters']['binding']['request_sha256']))
   self.assertEqual(len(wire['calls']),1)
 def test_explicit_model_override_uses_same_saved_connection_without_rewriting_its_default(self):
  for protocol in ('openai-chat','anthropic-messages','gemini-content'):
   with self.subTest(protocol=protocol),supplier(protocol,output='门外的新模型候选。') as wire:
    connection=self.connection(wire,model='fiction-default',protocol=protocol);prepared=self.prepare(dict(connection,model_id='fiction-author-override'));done=self.run_task(prepared);self.assertEqual(done['task']['status'],'succeeded');self.assertEqual(self.providers.status()[connection['id']]['model_id'],'fiction-default');self.assertEqual(len(wire['calls']),1);actual=wire['calls'][0]
    self.assertIn('fiction-author-override',actual['path'] if protocol=='gemini-content' else actual['body']['model'])
 def test_real_empty_partial_and_timeout_outputs_remain_failures_without_automatic_retry(self):
  before=self.service.get(self.pid)['document']
  for output,finish in [('', 'stop'),('门外的部分文字','length')]:
   with self.subTest(finish=finish),unfinished_supplier(output,finish) as wire:
    done=self.run_task(self.prepare(self.connection(wire)));self.assertEqual(done['task']['status'],'failed');self.assertEqual(done['candidates'],[]);self.assertEqual(len(wire['calls']),1);self.assertEqual(self.service.get(self.pid)['document'],before);self.assertFalse(done['model_results'][0]['response']['complete']);self.assertIn(finish,done['model_results'][0]['response']['raw_response'])
  with supplier(slow=True,output='不应成为候选的超时正文') as wire:
   prepared=self.prepare(self.connection(wire),timeout=100);done=self.run_task(prepared);wire['release'].set();self.assertEqual(done['task']['status'],'failed');self.assertEqual(done['task']['error_code'],'timeout');self.assertEqual(done['candidates'],[]);self.assertEqual(self.service.get(self.pid)['document'],before);self.assertLessEqual(len(wire['calls']),1)
 def test_new_planning_lock_blocks_old_candidate_and_restored_running_request_is_interrupted(self):
  from novel_writer.application.book_creation import BookCreation
  from novel_writer.application.backups import create_backup,restore_backup
  from novel_writer.application.skill_import import SkillLibrary
  planning=BookCreation(self.service);planning.start(self.pid,dict(operation_id=str(uuid4()),name='锁定方案',expected_revision=self.service.get(self.pid)['revision']));version=planning.describe(self.pid)['selected']
  with supplier(output='门前的完成候选。') as wire:
   done=self.run_task(self.prepare(self.connection(wire)));planning.set_lock(self.pid,dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision'],version_id=version['id'],field='ending',locked=True,current_lock_id=None,confirmed=True))
   with self.assertRaises(ValueError):self.adoption(done)
  with supplier(slow=True,output='恢复后不应自动重发。') as wire:
   prepared=self.prepare(self.connection(wire));task=prepared['task'];self.engine.start(self.pid,task['id'],dict(confirm_external=True,request_sha256=task['frozen']['parameters']['binding']['request_sha256']));self.assertTrue(wire['seen'].wait(2));SkillLibrary(self.db);package=self.root/'running.nwbak';create_backup(self.db,package);restored=restore_backup(package,self.root/'running-restored');service=NovelService(SQLiteRepository(restored['database_path']));registry=AdapterRegistry()
   for cap in ('draft_chapter','continue_chapter'):registry.register(cap,self.adapter)
   engine=TaskCoordinator(service,registry);self.addCleanup(engine.close);importlib.import_module('novel_writer.application.chapter_writing').ChapterWriting(engine,self.providers);self.assertEqual(engine.describe(self.pid,task['id'])['display_status'],'interrupted')
   with self.assertRaises(ValueError):engine.start(self.pid,task['id'],dict(confirm_external=True,request_sha256=task['frozen']['parameters']['binding']['request_sha256']))
   self.assertEqual(len(wire['calls']),1);result=engine.recover(self.pid);self.assertTrue(any(v['id']==task['id'] for v in result['interrupted']));self.engine.cancel(self.pid,task['id']);wire['release'].set();self.engine.wait_idle(3);self.assertEqual(service.get(self.pid)['document']['chapters'][0]['content'],'')
 def test_registry_rejects_a_writing_input_mislabelled_as_rewrite_or_other_mode_before_wire(self):
  import time
  from novel_writer.application.task_protocol import AdapterCall,CancellationToken
  from novel_writer.domain.model_contract import ExecutionPermit
  from novel_writer.domain.tasks import FrozenInput
  with supplier(output='不能以错误能力发送的正文。') as wire:
   prepared=self.prepare(self.connection(wire));task=prepared['task'];frozen=FrozenInput.from_dict(task['frozen']);attempt=str(uuid4());permit=ExecutionPermit(task_id=task['id'],attempt_id=attempt,request_sha256=frozen.parameters.binding.request_sha256,confirmed=True)
   for capability in ('rewrite_chapter','continue_chapter'):
    with self.assertRaises(ValueError):self.engine.registry.execute(AdapterCall(task_id=task['id'],attempt_id=attempt,capability=capability,input=frozen,permission=permit),CancellationToken(threading.Event(),time.monotonic()+2))
   self.assertEqual(wire['calls'],[])
 def test_preset_prompt_only_style_keeps_its_preset_reference_after_complete_copy(self):
  from novel_writer.application.creation_presets import CreationPresets
  from novel_writer.application.backups import create_backup
  from novel_writer.application.migrations import migrate
  from novel_writer.application.skill_import import SkillLibrary
  with supplier(output='门后的新稿。') as wire:
   connection=self.connection(wire);presets=CreationPresets(self.service);step=dict(step='draft',adapter_id='configured-http-v2',connection_id=connection['id'],model_id=connection['model_id'],temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=True);made=presets.save(self.pid,dict(operation_id=str(uuid4()),preset_id=None,name='只含作者提示的预设',settings=dict(steps=[step],style_id=None,style_prompt='Author English prompt only',manuscript_language='en',budget=dict(max_external_calls=1,max_reserved_output_tokens=512,risk_budget=1.0,allow_unknown_cost=True)),expected_revision=self.service.get(self.pid)['revision']));presets.choose(self.pid,dict(operation_id=str(uuid4()),version_id=made['version_id'],confirmed=True,expected_revision=self.service.get(self.pid)['revision']));done=self.run_task(self.prepare(None));SkillLibrary(self.db);package=self.root/'preset-source.nwbak';create_backup(self.db,package);target=self.root/'preset-copy.sqlite3';SQLiteRepository(target);SkillLibrary(target);copied=migrate(package,target,operation_id=str(uuid4()));service=NovelService(SQLiteRepository(target));pid=copied['projects'][0]['new_id'];state=service.get(pid);task=state['generation_tasks'][0];self.assertEqual(task['frozen']['parameters']['writing']['style_version_id'],state['creation_presets'][0]['id']);registry=AdapterRegistry();registry.register('draft_chapter',self.adapter);engine=TaskCoordinator(service,registry);self.addCleanup(engine.close);writing=importlib.import_module('novel_writer.application.chapter_writing').ChapterWriting(engine,self.providers);review=writing.review(pid,task['id'],dict(candidate_id=task['candidate_id'],correction_id=None));self.assertEqual(review['after'],'门后的新稿。');self.assertEqual(len(wire['calls']),1)

if __name__=='__main__':unittest.main()
