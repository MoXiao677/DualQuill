from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from importlib import util,import_module
import json
from pathlib import Path
import tempfile,threading,time,unittest
from uuid import uuid4
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository
from novel_writer.application.book_creation import BookCreation
from novel_writer.application.tasks import TaskCoordinator
from novel_writer.application.task_protocol import AdapterRegistry
from novel_writer.application.provider_connections import ProviderConnections
from novel_writer.application.creation_presets import CreationPresets

@contextmanager
def supplier(protocol='openai-chat',output=None,slow=False):
 calls=[];seen=threading.Event();release=threading.Event()
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def do_POST(self):
   body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append(dict(path=self.path,body=body));seen.set()
   if slow:release.wait(3)
   value=output if output is not None else json.dumps(dict(title='AI虚构书名',creative_idea='AI只提出灯塔构思'),ensure_ascii=False)
   if protocol=='anthropic-messages':payload=dict(id='fiction-book',role='assistant',content=[dict(type='text',text=value)],stop_reason='end_turn',usage=dict(input_tokens=20,output_tokens=9))
   elif protocol=='gemini-content':payload=dict(candidates=[dict(content=dict(role='model',parts=[dict(text=value)]),finishReason='STOP')],usageMetadata=dict(promptTokenCount=20,candidatesTokenCount=9,totalTokenCount=29))
   else:payload=dict(id='fiction-book',model='fiction-selected',choices=[dict(message=dict(role='assistant',content=value),finish_reason='stop')],usage=dict(prompt_tokens=20,completion_tokens=9,total_tokens=29))
   data=json.dumps(payload,ensure_ascii=False).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers()
   try:self.wfile.write(data)
   except OSError:pass
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True;worker=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);worker.start()
 try:yield dict(url='http://127.0.0.1:'+str(server.server_port)+'/v1',calls=calls,seen=seen,release=release)
 finally:release.set();server.shutdown();server.server_close();worker.join(2)

class BookAITests(unittest.TestCase):
 def setUp(self):
  self.assertIsNotNone(util.find_spec('novel_writer.application.book_ai'),'typed book-level AI coordinator is missing')
  self.api=import_module('novel_writer.application.book_ai');self.temp=tempfile.TemporaryDirectory(prefix='novel-book-ai-');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.db=self.root/'book.sqlite3';self.service=NovelService(SQLiteRepository(self.db));self.pid=self.service.create(title='空书AI虚构测试')['document']['project']['id'];self.manual=BookCreation(self.service);self.manual.start(self.pid,dict(operation_id=str(uuid4()),name='初始方案',expected_revision=self.service.get(self.pid)['revision']));self.shared=TaskCoordinator(self.service,AdapterRegistry());self.addCleanup(self.shared.close);self.providers=ProviderConnections(self.root/'fake.dpapi');self.ai=self.api.BookAICoordinator(self.shared,self.providers,self.manual,enabled=True)
 def selected(self):return self.manual.describe(self.pid)['selected']
 def connection(self,wire,protocol='openai-chat',identifier=None):return self.providers.save_custom(id=identifier or str(uuid4()),name='虚构书级供应商',base_url=wire['url'],protocol=protocol,model_id='fiction-default',api_key='fiction-book-private-key',allow_local=True)
 def options(self,connection,model='fiction-selected'):return dict(adapter_id='configured-http-v2',connection_id=connection['id'],model_id=model,temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=True,prompt_version='rewrite-1')
 def prepare(self,connection=None,step='idea',role='brainstorm',**changes):
  request=dict(operation_id=str(uuid4()),version_id=self.selected()['id'],step=step,preset_step=role,instruction='只生成本步骤虚构提案',model_options=self.options(connection) if connection else None,max_output_chars=10000,timeout_ms=2000);request.update(changes);return self.ai.prepare(self.pid,request)
 def run_task(self,prepared):
  task=prepared['task'];self.ai.start(self.pid,task['id'],dict(confirm_external=True,request_sha256=task['binding']['request_sha256']));self.shared.wait_idle(5);return self.ai.describe(self.pid,task['id'])
 def review(self,view):
  candidate=view['latest_candidate'];return self.ai.review(self.pid,dict(operation_id=str(uuid4()),task_id=view['task']['id'],candidate_id=candidate['id'],candidate_sha256=candidate['data_sha256']))
 def accept(self,view,review=None):
  candidate=view['latest_candidate'];review=review or self.review(view);return self.ai.accept(self.pid,dict(operation_id=str(uuid4()),task_id=view['task']['id'],candidate_id=candidate['id'],candidate_sha256=candidate['data_sha256'],review_id=review['id'],review_sha256=review['review_sha256'],confirmed=True))
 def test_empty_book_real_wire_is_candidate_only_and_task_events_do_not_stale_source(self):
  with supplier() as wire:
   connection=self.connection(wire);formal=self.service.get(self.pid)['document'];prepared=self.prepare(connection);self.assertEqual(wire['calls'],[]);self.assertEqual(self.service.get(self.pid)['document']['chapters'],[]);self.assertNotIn('fiction-book-private-key',json.dumps(prepared));self.assertEqual(prepared['task']['source_version_id'],self.selected()['id'])
   with self.assertRaises(ValueError):self.ai.start(self.pid,prepared['task']['id'],dict(confirm_external=True,request_sha256='0'*64))
   done=self.run_task(prepared);self.assertEqual(done['status'],'succeeded');self.assertEqual(len(wire['calls']),1);self.assertEqual(done['responses'][0]['response']['usage']['total_tokens'],29);self.assertEqual(self.service.get(self.pid)['document'],formal);self.assertTrue(done['source_fresh']);accepted=self.accept(done);self.assertEqual(self.selected()['id'],accepted['version_id']);self.assertEqual(self.selected()['data']['creative_idea'],'AI只提出灯塔构思');self.assertEqual(self.service.get(self.pid)['document'],formal)
   with self.assertRaises(ValueError):self.ai.start(self.pid,prepared['task']['id'],dict(confirm_external=True,request_sha256=prepared['task']['binding']['request_sha256']))
 def test_bad_json_missing_fields_and_manual_correction_keep_raw_and_no_retry(self):
  with supplier(output='{"creative_idea":"缺少书名"}') as wire:
   prepared=self.prepare(self.connection(wire));done=self.run_task(prepared);self.assertEqual(done['status'],'failed');self.assertIn('missing:title',done['latest_candidate']['errors']);original=done['responses'][0]['response']['raw_response'];candidate=done['latest_candidate'];corrected=self.ai.correct(self.pid,dict(operation_id=str(uuid4()),task_id=done['task']['id'],candidate_id=candidate['id'],text=json.dumps(dict(title='人工修正书名',creative_idea='人工修正创意'),ensure_ascii=False)));self.assertEqual(len(corrected['candidates']),2);self.assertEqual(corrected['responses'][0]['response']['raw_response'],original);self.assertEqual(len(wire['calls']),1);self.accept(corrected);self.assertEqual(self.selected()['data']['title'],'人工修正书名');self.assertEqual(self.service.get(self.pid)['document']['chapters'],[])
 def test_presets_and_explicit_per_step_override_use_different_real_protocols(self):
  with supplier() as first,supplier('anthropic-messages',output=json.dumps(dict(main_plot='虚构主线',subplots=['虚构支线'],ending='虚构结局'),ensure_ascii=False)) as second:
   left=self.connection(first);right=self.connection(second,'anthropic-messages');profiles=[]
   for step,connection in [('brainstorm',left),('outline',right)]:profiles.append(dict(step=step,**{k:v for k,v in self.options(connection).items() if k!='prompt_version'}))
   presets=CreationPresets(self.service);saved=presets.save(self.pid,dict(operation_id=str(uuid4()),preset_id=None,name='分步骤AI虚构预设',settings=dict(steps=profiles,style_id=None,style_prompt='',manuscript_language='zh-CN',budget=dict(max_external_calls=4,max_reserved_output_tokens=4096,risk_budget=2.0,allow_unknown_cost=True)),expected_revision=self.service.get(self.pid)['revision']));presets.choose(self.pid,dict(operation_id=str(uuid4()),version_id=saved['version_id'],confirmed=True,expected_revision=self.service.get(self.pid)['revision']));self.accept(self.run_task(self.prepare()));version=self.selected();self.manual.save_step(self.pid,dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision'],base_version_id=version['id'],step='idea',fields={},mark='save',next_step='plot'));done=self.run_task(self.prepare(step='plot',role='outline'));self.assertEqual(done['task']['binding']['destination']['protocol'],'anthropic-messages');self.assertEqual(second['calls'][0]['path'],'/v1/messages');self.assertEqual(len(first['calls']),1);self.assertEqual(len(second['calls']),1)
 def test_source_lock_or_connection_changes_reject_old_permission_and_candidate(self):
  with supplier() as first,supplier() as second:
   connection=self.connection(first);prepared=self.prepare(connection);self.connection(second,identifier=connection['id'])
   with self.assertRaises(ValueError):self.run_task(prepared)
   self.assertEqual(first['calls']+second['calls'],[]);done=self.run_task(self.prepare(connection));review=self.review(done);version=self.selected();self.manual.save_step(self.pid,dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision'],base_version_id=version['id'],step='idea',fields=dict(creative_idea='作者更新来源'),mark='save',next_step='idea'))
   with self.assertRaises(ValueError):self.accept(done,review)
   prepared=self.prepare(connection);self.manual.set_lock(self.pid,dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision'],version_id=self.selected()['id'],field='ending',locked=True,current_lock_id=None,confirmed=True))
   with self.assertRaises(ValueError):self.run_task(prepared)
 def test_cancel_and_late_response_never_advance_plan_or_repeat(self):
  with supplier(slow=True) as wire:
   prepared=self.prepare(self.connection(wire));before=self.selected();task=prepared['task'];self.ai.start(self.pid,task['id'],dict(confirm_external=True,request_sha256=task['binding']['request_sha256']));self.assertTrue(wire['seen'].wait(2));self.ai.cancel(self.pid,task['id']);wire['release'].set();self.shared.wait_idle(4);view=self.ai.describe(self.pid,task['id']);self.assertEqual(view['status'],'cancelled');self.assertEqual(self.selected(),before);self.assertEqual(view['adoptions'],[]);self.assertEqual(len(wire['calls']),1)
 def test_all_records_backup_copy_and_frozen_v11_are_preserved_without_permissions(self):
  from novel_writer.application.backups import create_backup,restore_backup
  from novel_writer.application.migrations import migrate
  from novel_writer.application.skill_import import SkillLibrary
  with supplier(output='not JSON') as wire:
   done=self.run_task(self.prepare(self.connection(wire)));self.ai.correct(self.pid,dict(operation_id=str(uuid4()),task_id=done['task']['id'],candidate_id=done['latest_candidate']['id'],text='{"title":"修正","creative_idea":"完整保留"}'));SkillLibrary(self.db);package=self.root/'ai.nwbak';self.assertEqual(create_backup(self.db,package)['backup_format_version'],51);restored=restore_backup(package,self.root/'restored');self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid),self.service.get(self.pid));target=self.root/'copy.sqlite3';SQLiteRepository(target);SkillLibrary(target);copied=migrate(package,target,operation_id=str(uuid4()));clone=NovelService(SQLiteRepository(target)).get(copied['projects'][0]['new_id']);self.assertEqual(len(clone['book_ai_candidates']),2);self.assertEqual(clone['book_ai_results'][0]['response']['raw_response'],self.service.get(self.pid)['book_ai_results'][0]['response']['raw_response']);self.assertNotIn('fiction-book-private-key',json.dumps(clone));self.assertEqual(len(wire['calls']),1)
  frozen=json.loads((Path(__file__).parent/'fixtures/f1ai_legacy_v11.json').read_text(encoding='utf-8'));old=self.root/'old11.sqlite3';old.write_bytes(bytes.fromhex(frozen['database_hex']));before=old.read_bytes();service=NovelService(SQLiteRepository(old));manual=BookCreation(service)
  for project in service.list_projects():manual.describe(project['id'])
  self.assertEqual(old.read_bytes(),before)
 def test_shared_slot_and_request_identity_do_not_silently_retry(self):
  with supplier() as wire:
   connection=self.connection(wire);state=self.service.get(self.pid);options=self.options(connection);request=dict(operation_id=str(uuid4()),version_id=self.selected()['id'],step='idea',preset_step='brainstorm',instruction='稳定准备身份',model_options=options,max_output_chars=10000,timeout_ms=2000);prepared=self.ai.prepare(self.pid,request);self.assertEqual(self.ai.prepare(self.pid,request)['task'],prepared['task'])
   with self.assertRaises(ValueError):self.ai.prepare(self.pid,dict(request,instruction='不可复用旧身份'))
   self.shared.slot.acquire()
   try:
    with self.assertRaises(ValueError):self.ai.start(self.pid,prepared['task']['id'],dict(confirm_external=True,request_sha256=prepared['task']['binding']['request_sha256']))
   finally:self.shared.slot.release()
   self.assertEqual(wire['calls'],[]);done=self.run_task(prepared);self.assertEqual(done['status'],'succeeded')
 def test_cancelled_call_still_consumes_call_and_reserved_token_budgets(self):
  with supplier(slow=True) as wire:
   connection=self.connection(wire);presets=CreationPresets(self.service)
   def select_budget(calls,tokens):
    profile=dict(step='brainstorm',**{k:v for k,v in self.options(connection).items() if k!='prompt_version'});saved=presets.save(self.pid,dict(operation_id=str(uuid4()),preset_id=None,name='取消不退回预算',settings=dict(steps=[profile],style_id=None,style_prompt='',manuscript_language='zh-CN',budget=dict(max_external_calls=calls,max_reserved_output_tokens=tokens,risk_budget=2.0,allow_unknown_cost=True)),expected_revision=self.service.get(self.pid)['revision']));presets.choose(self.pid,dict(operation_id=str(uuid4()),version_id=saved['version_id'],confirmed=True,expected_revision=self.service.get(self.pid)['revision']))
   select_budget(1,4096);prepared=self.prepare();task=prepared['task'];self.ai.start(self.pid,task['id'],dict(confirm_external=True,request_sha256=task['binding']['request_sha256']));self.assertTrue(wire['seen'].wait(2));self.ai.cancel(self.pid,task['id']);wire['release'].set();self.shared.wait_idle(4)
   with self.assertRaisesRegex(ValueError,'book_ai.budget_exceeded'):self.run_task(self.prepare())
   select_budget(10,512)
   with self.assertRaisesRegex(ValueError,'book_ai.budget_exceeded'):self.run_task(self.prepare())
   self.assertEqual(len(wire['calls']),1)
 def test_all_seven_typed_steps_flow_into_original_explicit_formal_confirmation(self):
  values={'idea':dict(title='AI七步虚构书',creative_idea='循信找塔'),'audience':dict(genre='悬疑',readership='成年读者'),'scope':dict(target_words=60000,manuscript_language='zh-CN'),'conflict':dict(theme='信任',core_conflict='旧信和新谎言'),'world':dict(worldbuilding='虚构港城',characters=[dict(name='林舟',role='送信人')]),'plot':dict(main_plot='循信寻找灯塔',subplots=['重建友谊'],ending='灯塔归还港城'),'structure':dict(volumes=[dict(title='旧信',summary='追寻',chapters=[dict(title='第一封信',core_idea='遇见委托')]),dict(title='灯塔',summary='揭示',chapters=[dict(title='归港',objective='做出选择')])])};steps=list(values);formal=self.service.get(self.pid)['document']
  for index,(step,fields) in enumerate(values.items()):
   with self.subTest(step=step),supplier(output=json.dumps(fields,ensure_ascii=False)) as wire:
    connection=self.connection(wire);done=self.run_task(self.prepare(connection,step=step,role='outline' if step in ('scope','plot','structure') else 'brainstorm'));self.assertEqual(done['display_status'],'candidate_ready');self.accept(done);self.assertEqual(self.service.get(self.pid)['document'],formal);self.assertEqual(len(wire['calls']),1)
   self.manual.save_step(self.pid,dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision'],base_version_id=self.selected()['id'],step=step,fields={},mark='complete',next_step=steps[min(index+1,len(steps)-1)]))
  planned=[chapter['id'] for volume in self.selected()['data']['volumes'] for chapter in volume['chapters']];preview=self.manual.preview(self.pid,dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision'],version_id=self.selected()['id']));self.assertEqual(len(preview['preview']['impact']['chapter_creates']),2);self.assertEqual(self.service.get(self.pid)['document'],formal);request=dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision'],preview_id=preview['preview']['id'],decision='accepted',confirmed=True,create_entities=True,authorize_confirmed_metadata=False);receipt=self.manual.decide(self.pid,request);self.assertEqual(self.manual.decide(self.pid,request),receipt);state=self.service.get(self.pid);self.assertEqual([v['id'] for v in state['document']['chapters']],planned);self.assertTrue(all(v['content']=='' for v in state['document']['chapters']));self.assertEqual(len(state['document']['characters']),1);self.assertEqual(state['memories'],[])
 def test_gemini_book_path_and_legacy_configuration_version_are_real_contracts(self):
  from novel_writer.application.provider_connections import PROVIDERS
  with supplier('gemini-content') as wire:
   done=self.run_task(self.prepare(self.connection(wire,'gemini-content')));self.assertEqual(done['status'],'succeeded');self.assertEqual(wire['calls'][0]['path'],'/v1/models/fiction-selected:generateContent');self.assertEqual(self.service.get(self.pid)['document']['chapters'],[])
  self.providers.save(id='gg',base_url=PROVIDERS['gg']['base_url'],model_id='fiction-default',api_key='fiction-legacy-key');prepared=self.prepare(dict(id='gg'),model_options=dict(self.options(dict(id='gg')),adapter_id='chat-completions-http-v1'));self.assertEqual(prepared['task']['binding']['destination']['connection_id'],'gg');self.assertEqual(prepared['task']['binding']['destination']['base_url'],PROVIDERS['gg']['base_url'])
 def test_valid_candidate_review_and_adoption_history_survive_copy(self):
  from novel_writer.application.backups import create_backup
  from novel_writer.application.migrations import migrate
  from novel_writer.application.skill_import import SkillLibrary
  with supplier() as wire:
   done=self.run_task(self.prepare(self.connection(wire)));review=self.review(done);self.accept(done,review);SkillLibrary(self.db);package=self.root/'adopted.nwbak';create_backup(self.db,package);target=self.root/'adopted-copy.sqlite3';SQLiteRepository(target);SkillLibrary(target);mapped=migrate(package,target,operation_id=str(uuid4()));state=NovelService(SQLiteRepository(target)).get(mapped['projects'][0]['new_id']);self.assertEqual(len(state['book_ai_reviews']),1);self.assertEqual(len(state['book_ai_adoptions']),1);self.assertEqual(state['book_ai_adoptions'][0]['review_id'],state['book_ai_reviews'][0]['id']);self.assertEqual(state['book_creation_versions'][-1]['data']['title'],'AI虚构书名');self.assertEqual(len(wire['calls']),1)
 def test_running_copy_is_interrupted_and_cannot_inherit_external_permission(self):
  from novel_writer.application.backups import create_backup,restore_backup
  from novel_writer.application.skill_import import SkillLibrary
  with supplier(slow=True) as wire:
   prepared=self.prepare(self.connection(wire));task=prepared['task'];self.ai.start(self.pid,task['id'],dict(confirm_external=True,request_sha256=task['binding']['request_sha256']));self.assertTrue(wire['seen'].wait(2));SkillLibrary(self.db);package=self.root/'running.nwbak';create_backup(self.db,package);restored=restore_backup(package,self.root/'running-restored');service=NovelService(SQLiteRepository(restored['database_path']));shared=TaskCoordinator(service,AdapterRegistry());self.addCleanup(shared.close);new=self.api.BookAICoordinator(shared,self.providers,BookCreation(service),enabled=True);view=new.describe(self.pid,task['id']);self.assertEqual(view['display_status'],'interrupted')
   with self.assertRaises(ValueError):new.start(self.pid,task['id'],dict(confirm_external=True,request_sha256=task['binding']['request_sha256']))
   self.assertEqual(len(wire['calls']),1);self.ai.cancel(self.pid,task['id']);wire['release'].set();self.shared.wait_idle(4)
if __name__=='__main__':unittest.main()
