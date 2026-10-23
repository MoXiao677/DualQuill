"""C04-B1 chapter IDEA brainstorm and outline/scene planning, fictional wire only."""
import importlib,json,tempfile,unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from importlib import util
from pathlib import Path
import threading
from uuid import uuid4
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository
from novel_writer.application.provider_connections import ProviderConnections
from novel_writer.application.tasks import TaskCoordinator
from novel_writer.application.task_protocol import AdapterRegistry
from test_book_ai import supplier

@contextmanager
def slow_supplier(output):
 calls=[];seen=threading.Event();release=threading.Event()
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def do_POST(self):
   body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append(body);seen.set();release.wait(5)
   raw=json.dumps(dict(id='fiction-planning',model='fiction-planning',choices=[dict(message=dict(role='assistant',content=output),finish_reason='stop')]),ensure_ascii=False).encode()
   self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers()
   try:self.wfile.write(raw)
   except OSError:pass
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
 worker=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);worker.start()
 try:yield dict(url='http://127.0.0.1:'+str(server.server_port)+'/v1',calls=calls,seen=seen,release=release)
 finally:release.set();server.shutdown();server.server_close();worker.join(2)

class ChapterPlanningTests(unittest.TestCase):
 def setUp(self):
  self.assertIsNotNone(util.find_spec('novel_writer.application.chapter_planning'),'chapter IDEA/outline planning coordinator is missing')
  self.temp=tempfile.TemporaryDirectory(prefix='novel-chapter-planning-');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.db=self.root/'fiction.sqlite3'
  self.service=NovelService(SQLiteRepository(self.db));self.pid=self.service.create(title='灯塔旧信')['document']['project']['id']
  self.action('add_character',dict(name='林舟',role='送信人',personality='谨慎',background='从港城来',goals=['送达旧信']))
  self.action('add_chapter',dict(title='第一封信'))
  state=self.service.get(self.pid);self.cid=state['document']['chapters'][0]['id'];self.chid=state['document']['characters'][0]['id']
  self.action('save_book_outline',dict(theme='信任',premise='旧信抵达',main_plot='循信找塔',ending='灯塔归还',volumes=[dict(number=1,title='旧信卷',summary='启程',chapter_ids=[self.cid])]))
  self.action('save_idea',dict(chapter_id=self.cid,content='林舟在门外听见潮声。'))
  self.action('save_chapter_outline',dict(chapter_id=self.cid,core_idea='迟疑',objective='建立悬念',story_time='第1天',character_ids=[self.chid],scenes=[dict(order=1,summary='门外等待',character_ids=[self.chid],location='旧灯塔',story_time='清晨')]))
  self.action('save_worldbuilding',dict(content='港城终年有雾，灯塔在礁石上。'))
  self.action('save_writing_rules',dict(content='限知视角，只写可观察动作。'))
  from novel_writer.application.styles import StyleCoordinator
  from test_styles import FEATURES
  style_engine=TaskCoordinator(self.service,AdapterRegistry());self.addCleanup(style_engine.close);styles=StyleCoordinator(style_engine,ProviderConnections(self.root/'style.dpapi'),enabled=False)
  card=styles.save_card(self.pid,dict(operation_id=str(uuid4()),style_id=None,name='作者的冷雾文风',prompt='冷雾短句，只写动作。',card=FEATURES,analysis_id=None,confirmed=True));styles.choose(self.pid,dict(operation_id=str(uuid4()),chapter_id=None,version_id=card['id'],confirmed=True))
  self.action('save_memory',dict(kind='event',title='旧信抵达',text='信在清晨送到门外。',position_chapter_id=self.cid,confirmed=True,source=dict(kind='idea',entity_id=self.cid)))
  self.providers=ProviderConnections(self.root/'fiction.dpapi');self.shared=TaskCoordinator(self.service,AdapterRegistry());self.addCleanup(self.shared.close)
  self.api=importlib.import_module('novel_writer.application.chapter_planning');self.planning=self.api.ChapterPlanningCoordinator(self.shared,self.providers,enabled=True)
 def action(self,action,fields):return self.service.execute(self.pid,action,fields,expected_revision=self.service.get(self.pid)['revision'])
 def connection(self,wire,model='fiction-planning',protocol='openai-chat',identifier=None):return self.providers.save_custom(id=identifier or str(uuid4()),name='虚构章节构思模型',base_url=wire['url'],protocol=protocol,model_id=model,api_key='fiction-planning-key',allow_local=True)
 def options(self,connection,model='fiction-selected'):return dict(adapter_id='configured-http-v2',connection_id=connection['id'],model_id=model,temperature=.3,max_tokens=768,budget_limit=1.0,allow_unknown_cost=True,prompt_version='rewrite-1')
 def source(self,mode='brainstorm',**changes):
  value=dict(chapter_id=self.cid,mode=mode,instruction='只依据本书资料',character_ids=[self.chid],include_worldbuilding=True,include_writing_rules=True,include_facts=True,include_locations=True,context_budget_chars=20000);value.update(changes);return value
 def prepare(self,connection=None,mode='brainstorm',source=None,**changes):
  source=source or self.source(mode);preview=self.planning.preview(self.pid,source)
  request=dict(operation_id=str(uuid4()),source_options=source,source_sha256=preview['source_sha256'],model_options=self.options(connection) if connection else None,max_output_chars=12000,timeout_ms=3000);request.update(changes)
  return self.planning.prepare(self.pid,request)
 def execute(self,prepared):
  task=prepared['task'];self.planning.start(self.pid,task['id'],dict(confirm_external=True,request_sha256=task['binding']['request_sha256']));self.shared.wait_idle(6);return self.planning.describe(self.pid,task['id'])
 def review(self,view):
  candidate=view['latest_candidate'];return self.planning.review(self.pid,dict(operation_id=str(uuid4()),task_id=view['task']['id'],candidate_id=candidate['id'],candidate_sha256=candidate['data_sha256']))
 def accept(self,view,review=None):
  candidate=view['latest_candidate'];review=review or self.review(view)
  return self.planning.accept(self.pid,dict(operation_id=str(uuid4()),task_id=view['task']['id'],candidate_id=candidate['id'],candidate_sha256=candidate['data_sha256'],review_id=review['id'],review_sha256=review['review_sha256'],expected_revision=self.service.get(self.pid)['revision'],confirm_chapter=True))
 def test_real_book_context_flows_idea_then_ordered_outline_without_body_or_entities(self):
  before=self.service.get(self.pid);document=before['document']
  with supplier(output=json.dumps(dict(idea='林舟在潮声里认出旧信的封蜡。'),ensure_ascii=False)) as wire:
   connection=self.connection(wire);source=self.source();preview=self.planning.preview(self.pid,source)
   for text in ['林舟','港城终年有雾','限知视角','旧灯塔','信在清晨送到门外','灯塔旧信','旧信卷','第一封信','冷雾短句，只写动作。']:self.assertIn(text,preview['context_text'])
   self.assertEqual(wire['calls'],[]);self.assertFalse(preview['model_request_sent'])
   prepared=self.prepare(connection,source=source);self.assertEqual(wire['calls'],[]);self.assertNotIn('fiction-planning-key',json.dumps(prepared));done=self.execute(prepared)
   self.assertEqual(done['display_status'],'candidate_ready');self.assertEqual(len(wire['calls']),1);self.assertEqual(self.service.get(self.pid)['document'],document)
   self.assertIn('idea',json.dumps(wire['calls'][0],ensure_ascii=False));self.assertIn('林舟',json.dumps(wire['calls'][0],ensure_ascii=False))
   adopted=self.accept(done);self.assertEqual(adopted['mode'],'brainstorm');state=self.service.get(self.pid);self.assertEqual(state['ideas'][self.cid],'林舟在潮声里认出旧信的封蜡。');self.assertEqual(state['document'],document)
  outline=dict(core_idea='封蜡揭示来信人',objective='作出是否开门的决定',character_ids=[self.chid],scenes=[dict(order=1,summary='辨认封蜡',character_ids=[self.chid],location='旧灯塔门口',story_time='清晨'),dict(order=2,summary='听见第二封信落地的声音',character_ids=[self.chid],location='旧灯塔楼梯',story_time='清晨稍后')],story_time='第1天清晨')
  with supplier(output=json.dumps(outline,ensure_ascii=False)) as wire:
   connection=self.connection(wire);prepared=self.prepare(connection,'outline');self.assertIn('林舟在潮声里认出旧信的封蜡',prepared['task']['binding']['request_body']);done=self.execute(prepared);self.assertEqual(done['display_status'],'candidate_ready',done.get('task',{}).get('error_code'))
   review=self.review(done);self.assertEqual(review['before']['core_idea'],'迟疑');self.assertEqual([v['order'] for v in review['after']['scenes']],[1,2]);self.assertIn('scenes',[v['field'] for v in self.changes(review)])
   adopted=self.accept(done,review);self.assertIsNotNone(adopted['outline_id']);self.assertIsNotNone(adopted['outline_version_id']);state=self.service.get(self.pid)
   saved=state['document']['chapter_outlines'][0];self.assertEqual(saved['core_idea'],'封蜡揭示来信人');self.assertEqual([v['order'] for v in saved['scenes']],[1,2]);self.assertEqual(saved['character_ids'],[self.chid])
   self.assertEqual(len(state['document']['characters']),len(document['characters']));self.assertEqual(len(state['document']['chapters']),1);self.assertTrue(all(v['content']=='' for v in state['document']['chapters']))
   self.assertEqual(len(state['document']['versions']),len(document['versions'])+1)
   from novel_writer.application.chapter_writing import ChapterWriting
   from novel_writer.application.custom_protocols import ConfiguredHttpAdapter
   adapter=ConfiguredHttpAdapter(self.providers,enabled=True);registry=AdapterRegistry();registry.register('draft_chapter',adapter);registry.register('continue_chapter',adapter)
   writing_engine=TaskCoordinator(self.service,registry);self.addCleanup(writing_engine.close);writing=ChapterWriting(writing_engine,self.providers)
   chapter_source=dict(chapter_id=self.cid,mode='draft',context_options=dict(chapter_id=self.cid,budget_chars=20000,include_current_plan=True,include_writing_rules=True),instruction='准备初稿',target_chars=300,required_literals=[],forbidden_literals=[])
   draft_preview=writing.preview(self.pid,chapter_source);self.assertIn('封蜡揭示来信人',draft_preview['context']['context_text']);self.assertIn('林舟在潮声里认出旧信的封蜡',draft_preview['context']['context_text']);self.assertIn('旧灯塔楼梯',draft_preview['context']['context_text'])
   frozen=writing.prepare(self.pid,dict(request_id=str(uuid4()),source_options=chapter_source,source_sha256=draft_preview['source_sha256'],model_options=self.options(connection),max_output_chars=4000,timeout_ms=3000,retry_of=None));self.assertIn('封蜡揭示来信人',frozen['task']['frozen']['parameters']['binding']['request_body']);self.assertEqual(self.service.get(self.pid)['document']['chapters'][0]['content'],'')
 def changes(self,review):
  result=[]
  for field in ('idea','core_idea','objective','character_ids','scenes','story_time'):
   if field in review['before'] or field in review['after']:
    if review['before'].get(field)!=review['after'].get(field):result.append(dict(field=field))
  return result
 def test_invalid_json_missing_fields_manual_correction_and_review_are_one_request_path(self):
  with supplier(output='{"note":"缺少结构化包装"}') as wire:
   done=self.execute(self.prepare(self.connection(wire)));self.assertEqual(done['status'],'failed');self.assertIn('missing:idea',done['latest_candidate']['errors']);raw=done['responses'][0]['response']['raw_response']
   fixed=self.planning.correct(self.pid,dict(operation_id=str(uuid4()),task_id=done['task']['id'],candidate_id=done['latest_candidate']['id'],text=json.dumps(dict(idea='人工修正：旧信封蜡破损。'),ensure_ascii=False)))
   self.assertEqual(len(fixed['candidates']),2);self.assertEqual(fixed['responses'][0]['response']['raw_response'],raw);self.assertEqual(len(wire['calls']),1)
   review=self.review(fixed);self.assertEqual(review['before']['idea'],'林舟在门外听见潮声。');self.assertEqual(review['after']['idea'],'人工修正：旧信封蜡破损。');self.accept(fixed,review);self.assertEqual(self.service.get(self.pid)['ideas'][self.cid],'人工修正：旧信封蜡破损。')
 def test_outline_rejects_unknown_characters_and_unordered_scenes_without_creating_entities(self):
  before=self.service.get(self.pid);unknown=dict(core_idea='新人物',objective='拒绝',character_ids=[str(uuid4())],scenes=[dict(order=1,summary='新场景',character_ids=[],location='新地点',story_time='')],story_time='')
  with supplier(output=json.dumps(unknown,ensure_ascii=False)) as wire:
   done=self.execute(self.prepare(self.connection(wire),'outline'));self.assertEqual(done['status'],'failed');self.assertIn('chapter_planning.unknown_character',done['latest_candidate']['errors'])
   unordered=dict(unknown,character_ids=[self.chid],scenes=[dict(order=2,summary='倒序',character_ids=[self.chid],location='旧灯塔',story_time='')])
   fixed=self.planning.correct(self.pid,dict(operation_id=str(uuid4()),task_id=done['task']['id'],candidate_id=done['latest_candidate']['id'],text=json.dumps(unordered,ensure_ascii=False)));self.assertIn('chapter_planning.scene_order',fixed['latest_candidate']['errors'])
   self.assertEqual(self.service.get(self.pid)['document'],before['document']);self.assertEqual(len(self.service.get(self.pid)['document']['characters']),1);self.assertEqual(len(wire['calls']),1)
 def test_syntax_broken_json_is_rejected_and_only_manual_correction_can_proceed(self):
  with supplier(output='not JSON at all') as wire:
   done=self.execute(self.prepare(self.connection(wire)));self.assertEqual(done['status'],'failed');self.assertIn('chapter_planning.invalid_json',done['latest_candidate']['errors']);self.assertEqual(self.service.get(self.pid)['ideas'][self.cid],'林舟在门外听见潮声。')
   fixed=self.planning.correct(self.pid,dict(operation_id=str(uuid4()),task_id=done['task']['id'],candidate_id=done['latest_candidate']['id'],text=json.dumps(dict(idea='人工修正后的合法IDEA'),ensure_ascii=False)));self.assertEqual(fixed['latest_candidate']['errors'],[]);self.assertEqual(len(wire['calls']),1)
 def test_preset_step_and_explicit_override_select_real_protocols(self):
  from novel_writer.application.creation_presets import CreationPresets
  with supplier(output=json.dumps(dict(idea='预设构思'),ensure_ascii=False)) as first,supplier('anthropic-messages') as second:
   left=self.connection(first);right=self.connection(second,'anthropic-messages');presets=CreationPresets(self.service)
   profiles=[dict(step='brainstorm',**{k:v for k,v in self.options(left).items() if k!='prompt_version'})]
   saved=presets.save(self.pid,dict(operation_id=str(uuid4()),preset_id=None,name='构思用途',settings=dict(steps=profiles,style_id=None,style_prompt='',manuscript_language='zh-CN',budget=dict(max_external_calls=3,max_reserved_output_tokens=8000,risk_budget=2.0,allow_unknown_cost=True)),expected_revision=self.service.get(self.pid)['revision']))
   presets.choose(self.pid,dict(operation_id=str(uuid4()),version_id=saved['version_id'],confirmed=True,expected_revision=self.service.get(self.pid)['revision']))
   preset_prepared=self.prepare(None);self.assertEqual(preset_prepared['task']['selection_source'],'preset');done=self.execute(preset_prepared);self.assertEqual(done['status'],'succeeded');self.assertEqual(len(first['calls']),1)
   with supplier(output=json.dumps(dict(idea='临时覆盖'),ensure_ascii=False)) as override_wire:
    overridden=self.connection(override_wire);prepared=self.prepare(overridden);self.assertEqual(prepared['task']['selection_source'],'override');done=self.execute(prepared);self.assertEqual(done['status'],'succeeded');self.assertEqual(len(override_wire['calls']),1);self.assertEqual(len(first['calls']),1)
 def test_source_lock_and_config_changes_reject_old_execution_and_candidate(self):
  with supplier(output=json.dumps(dict(idea='旧来源候选'),ensure_ascii=False)) as first,supplier() as second:
   connection=self.connection(first);prepared=self.prepare(connection);self.action('save_idea',dict(chapter_id=self.cid,content='作者更新的来源'))
   with self.assertRaises(ValueError):self.execute(prepared)
   self.assertEqual(first['calls'],[]);done=self.execute(self.prepare(connection));review=self.review(done)
   self.action('save_worldbuilding',dict(content='作者更新的新世界，仍无第二地点。'))
   with self.assertRaises(ValueError):self.accept(done,review)
   self.assertEqual(len(first['calls']),1);pending=self.prepare(connection);self.connection(second,identifier=connection['id'])
   with self.assertRaises(ValueError):self.execute(pending)
   self.assertEqual(second['calls'],[])
 def test_new_planning_lock_blocks_old_execution_and_candidate_adoption(self):
  from novel_writer.application.book_creation import BookCreation
  planning=BookCreation(self.service);planning.start(self.pid,dict(operation_id=str(uuid4()),name='锁定方案',expected_revision=self.service.get(self.pid)['revision']));version=planning.describe(self.pid)['selected']
  with supplier(output=json.dumps(dict(idea='锁定前的候选'),ensure_ascii=False)) as wire:
   prepared=self.prepare(self.connection(wire));planning.set_lock(self.pid,dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision'],version_id=version['id'],field='ending',locked=True,current_lock_id=None,confirmed=True))
   with self.assertRaises(ValueError):self.execute(prepared)
   self.assertEqual(wire['calls'],[])
   done=self.execute(self.prepare(self.connection(wire)));review=self.review(done);active=planning.describe(self.pid)['locks']['ending'];planning.set_lock(self.pid,dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision'],version_id=version['id'],field='ending',locked=False,current_lock_id=active['id'],confirmed=True))
   with self.assertRaises(ValueError):self.accept(done,review)
   self.assertEqual(len(wire['calls']),1)
 def test_preset_call_budget_counts_completed_requests_and_blocks_a_second_send(self):
  from novel_writer.application.creation_presets import CreationPresets
  with supplier(output=json.dumps(dict(idea='预算内候选'),ensure_ascii=False)) as wire:
   connection=self.connection(wire);presets=CreationPresets(self.service);profile=dict(step='brainstorm',**{k:v for k,v in self.options(connection).items() if k!='prompt_version'})
   saved=presets.save(self.pid,dict(operation_id=str(uuid4()),preset_id=None,name='一次构思预算',settings=dict(steps=[profile],style_id=None,style_prompt='',manuscript_language='zh-CN',budget=dict(max_external_calls=1,max_reserved_output_tokens=2048,risk_budget=2.0,allow_unknown_cost=True)),expected_revision=self.service.get(self.pid)['revision']));presets.choose(self.pid,dict(operation_id=str(uuid4()),version_id=saved['version_id'],confirmed=True,expected_revision=self.service.get(self.pid)['revision']))
   done=self.execute(self.prepare(None));self.assertEqual(done['status'],'succeeded');second=self.prepare(None)
   with self.assertRaisesRegex(ValueError,'chapter_planning.budget_exceeded'):self.execute(second)
   self.assertEqual(len(wire['calls']),1)
 def test_cancel_retains_late_response_without_new_candidate_or_resend(self):
  with supplier(output=json.dumps(dict(idea='迟到的构思响应'),ensure_ascii=False)) as wire:
   prepared=self.prepare(self.connection(wire));task=prepared['task'];before=self.service.get(self.pid)['ideas'][self.cid]
   self.planning.adapter.transport.capture_response=lambda _:self.planning.cancel(self.pid,task['id'])
   self.execute(prepared);view=self.planning.describe(self.pid,task['id'])
   self.assertEqual(view['status'],'cancelled');self.assertEqual(view['candidates'],[]);self.assertEqual(view['adoptions'],[]);self.assertEqual(self.service.get(self.pid)['ideas'][self.cid],before)
   self.assertEqual(len(view['late_results']),1);late=view['late_results'][0];expected=json.dumps(dict(idea='迟到的构思响应'),ensure_ascii=False);self.assertEqual(late['response']['http_status'],200);self.assertTrue(late['response']['complete']);self.assertEqual(late['response']['output_text'],expected);self.assertIn('迟到的构思响应',late['response']['raw_response']);self.assertEqual(view['responses'][0]['response']['output_text'],expected);self.assertEqual(len(wire['calls']),1)
   with self.assertRaises(ValueError):self.planning.start(self.pid,task['id'],dict(confirm_external=True,request_sha256=task['binding']['request_sha256']))
 def test_complete_v17_backup_restore_copy_and_pending_permission_is_not_inherited(self):
  from novel_writer.application.backups import create_backup,restore_backup
  from novel_writer.application.migrations import migrate
  from novel_writer.application.skill_import import SkillLibrary
  with supplier(output=json.dumps(dict(idea='备份中的构思'),ensure_ascii=False)) as wire:
   connection=self.connection(wire);done=self.execute(self.prepare(connection));self.accept(done);pending=self.prepare(connection)
   state=self.service.get(self.pid);self.assertEqual(state['workspace_version'],17);SkillLibrary(self.db);package=self.root/'planning.nwbak'
   self.assertEqual(create_backup(self.db,package)['backup_format_version'],51);restored=restore_backup(package,self.root/'planning-restored');self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid),state)
   target=self.root/'planning-copy.sqlite3';SQLiteRepository(target);SkillLibrary(target);copied=migrate(package,target,operation_id=str(uuid4()));pid=copied['projects'][0]['new_id'];service=NovelService(SQLiteRepository(target));clone=service.get(pid)
   self.assertEqual(len(clone['chapter_planning_tasks']),2);self.assertEqual(len(clone['chapter_planning_candidates']),1);self.assertEqual(len(clone['chapter_planning_reviews']),1);self.assertEqual(clone['chapter_planning_adoptions'][0]['review_id'],clone['chapter_planning_reviews'][0]['id']);self.assertEqual(clone['ideas'][clone['document']['chapters'][0]['id']],'备份中的构思');self.assertNotIn('fiction-planning-key',json.dumps(clone))
   registry=AdapterRegistry();engine=TaskCoordinator(service,registry);self.addCleanup(engine.close);new=self.api.ChapterPlanningCoordinator(engine,self.providers,enabled=True)
   pending_ids={e['task_id'] for e in clone['chapter_planning_events'] if e['kind']=='prepared'}|{e['task_id'] for e in clone['chapter_planning_events'] if e['kind']!='prepared'}
   old=next(v for v in clone['chapter_planning_tasks'] if next(e['status'] for e in reversed(clone['chapter_planning_events']) if e['task_id']==v['id'])=='pending')
   self.assertEqual(new.describe(pid,old['id'])['display_status'],'interrupted')
   with self.assertRaises(ValueError):new.start(pid,old['id'],dict(confirm_external=True,request_sha256=old['binding']['request_sha256']))
   self.assertEqual(len(wire['calls']),1)
if __name__=='__main__':unittest.main()
