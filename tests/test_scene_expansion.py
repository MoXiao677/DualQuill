"""C04-B2 scene/selection prose expansion, fictional loopback only."""
import importlib,json,tempfile,unittest
from importlib import util
from pathlib import Path
from uuid import uuid4
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository
from novel_writer.application.provider_connections import ProviderConnections
from novel_writer.application.tasks import TaskCoordinator
from novel_writer.application.task_protocol import AdapterRegistry
from test_book_ai import supplier

class SceneExpansionTests(unittest.TestCase):
 def setUp(self):
  self.assertIsNotNone(util.find_spec('novel_writer.application.scene_expansion'),'scene/selection expansion coordinator is missing')
  self.temp=tempfile.TemporaryDirectory(prefix='novel-scene-expansion-');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.db=self.root/'fiction.sqlite3'
  self.service=NovelService(SQLiteRepository(self.db));self.pid=self.service.create(title='扩写虚构小说')['document']['project']['id']
  self.action('add_character',dict(name='林舟',role='送信人'));state=self.service.get(self.pid);self.chid=state['document']['characters'][0]['id']
  self.action('add_chapter',dict(title='第一封信'));state=self.service.get(self.pid);self.cid=state['document']['chapters'][0]['id']
  self.original='前缀😀e\u0301\r\n门外有雾。\n尾声。';self.action('save_chapter',dict(chapter_id=self.cid,content=self.original))
  self.action('save_idea',dict(chapter_id=self.cid,content='林舟在门外辨认旧信。'))
  self.action('save_chapter_outline',dict(chapter_id=self.cid,core_idea='门外辨认',objective='决定是否开门',story_time='第1天',character_ids=[self.chid],scenes=[dict(order=1,summary='初听潮声',character_ids=[self.chid],location='旧灯塔',story_time='清晨'),dict(order=2,summary='封蜡揭示来信人',character_ids=[self.chid],location='旧灯塔门口',story_time='清晨稍后')]))
  self.action('save_worldbuilding',dict(content='港城终年有雾。'))
  self.action('save_writing_rules',dict(content='限知视角，只写可观察动作。'))
  self.action('save_memory',dict(kind='event',title='旧信抵达',text='信在清晨送到门外。',position_chapter_id=self.cid,confirmed=True,source=dict(kind='idea',entity_id=self.cid)))
  self.providers=ProviderConnections(self.root/'fiction.dpapi');self.shared=TaskCoordinator(self.service,AdapterRegistry());self.addCleanup(self.shared.close)
  self.api=importlib.import_module('novel_writer.application.scene_expansion');self.engine=self.api.SceneExpansionCoordinator(self.shared,self.providers,enabled=True)
 def action(self,action,fields):return self.service.execute(self.pid,action,fields,expected_revision=self.service.get(self.pid)['revision'])
 def connection(self,wire,protocol='openai-chat',identifier=None):return self.providers.save_custom(id=identifier or str(uuid4()),name='虚构扩写模型',base_url=wire['url'],protocol=protocol,model_id='fiction-expansion',api_key='fiction-expansion-key',allow_local=True)
 def options(self,connection,model='fiction-expansion'):return dict(adapter_id='configured-http-v2',connection_id=connection['id'],model_id=model,temperature=.3,max_tokens=768,budget_limit=1.0,allow_unknown_cost=True,prompt_version='rewrite-1')
 def source(self,target_kind='scene',**changes):
  value=dict(chapter_id=self.cid,target_kind=target_kind,scene_order=2 if target_kind=='scene' else None,selection_start=None,selection_end=None,instruction='扩写为可观察动作',target_chars=400,character_ids=[self.chid],include_worldbuilding=True,include_writing_rules=True,include_facts=True,context_budget_chars=20000);value.update(changes);return value
 def prepare(self,connection=None,source=None,**changes):
  source=source or self.source();preview=self.engine.preview(self.pid,source)
  request=dict(operation_id=str(uuid4()),source_options=source,source_sha256=preview['source_sha256'],model_options=self.options(connection) if connection else None,max_output_chars=8000,timeout_ms=3000);request.update(changes)
  return self.engine.prepare(self.pid,request)
 def execute(self,prepared):
  task=prepared['task'];self.engine.start(self.pid,task['id'],dict(confirm_external=True,request_sha256=task['binding']['request_sha256']));self.shared.wait_idle(6);return self.engine.describe(self.pid,task['id'])
 def review(self,view):
  candidate=view['latest_candidate'];return self.engine.review(self.pid,dict(operation_id=str(uuid4()),task_id=view['task']['id'],candidate_id=candidate['id'],candidate_sha256=candidate['data_sha256']))
 def accept(self,view,review=None,authorize=False):
  candidate=view['latest_candidate'];review=review or self.review(view)
  return self.engine.accept(self.pid,dict(operation_id=str(uuid4()),task_id=view['task']['id'],candidate_id=candidate['id'],candidate_sha256=candidate['data_sha256'],review_id=review['id'],review_sha256=review['review_sha256'],expected_revision=self.service.get(self.pid)['revision'],confirm_chapter=True,authorize_confirmed=authorize))
 def test_scene_target_appends_expansion_and_preserves_all_original_bytes(self):
  versions=len(self.service.get(self.pid)['document']['versions'])
  with supplier(output='门外的雾贴着台阶。🚪林舟没有立刻开门。') as wire:
   connection=self.connection(wire);source=self.source();preview=self.engine.preview(self.pid,source)
   for text in ['封蜡揭示来信人','旧灯塔门口','林舟','港城终年有雾','限知视角','信在清晨送到门外','前缀😀','尾声。']:self.assertIn(text,preview['context_text'])
   self.assertEqual(wire['calls'],[]);prepared=self.prepare(connection,source=source);self.assertEqual(wire['calls'],[]);done=self.execute(prepared);self.assertEqual(done['status'],'succeeded',done.get('task',{}).get('error_code'))
   self.assertEqual(self.service.get(self.pid)['document']['chapters'][0]['content'],self.original);self.assertEqual(len(wire['calls']),1)
   review=self.review(done);self.assertEqual(review['selected_before'],'');self.assertTrue(review['after_text'].startswith(self.original));self.assertEqual(review['after_text'],self.original+'门外的雾贴着台阶。🚪林舟没有立刻开门。')
   receipt=self.accept(done,review);state=self.service.get(self.pid);after=state['document']['chapters'][0]['content'];self.assertEqual(after,self.original+'门外的雾贴着台阶。🚪林舟没有立刻开门。');self.assertTrue(after.encode('utf-8').startswith(self.original.encode('utf-8')));self.assertTrue(receipt['version_after']);self.assertEqual(receipt['selected_start'],len(self.original));self.assertEqual(receipt['selected_end'],len(self.original))
   self.assertEqual(len(state['document']['characters']),1);self.assertEqual(len(state['document']['chapter_outlines'][0]['scenes']),2);self.assertEqual(len(state['document']['versions']),versions+1)
 def test_selection_replaces_exact_code_point_range_and_keeps_prefix_suffix_bytes(self):
  start=self.original.index('门外');end=start+len('门外有雾。')
  with supplier(output='门外只有潮声，没有脚步。') as wire:
   connection=self.connection(wire);source=self.source('selection',scene_order=None,selection_start=start,selection_end=end);prepared=self.prepare(connection,source=source);done=self.execute(prepared);review=self.review(done)
   self.assertEqual(review['selected_before'],'门外有雾。');self.assertEqual(review['selected_after'],'门外只有潮声，没有脚步。');self.assertEqual(review['after_text'],self.original[:start]+'门外只有潮声，没有脚步。'+self.original[end:])
   self.accept(done,review);after=self.service.get(self.pid)['document']['chapters'][0]['content'];self.assertEqual(after,self.original[:start]+'门外只有潮声，没有脚步。'+self.original[end:])
   self.assertEqual(after.encode('utf-8')[:len(self.original[:start].encode('utf-8'))],self.original[:start].encode('utf-8'));self.assertTrue(after.encode('utf-8').endswith(self.original[end:].encode('utf-8')))
 def test_invalid_selection_missing_scene_and_whole_document_are_rejected_before_wire(self):
  with supplier() as wire:
   connection=self.connection(wire)
   for source in (self.source('selection',scene_order=None,selection_start=0,selection_end=0),self.source('selection',scene_order=None,selection_start=0,selection_end=len(self.original)+1),dict(self.source(),scene_order=99),dict(self.source(),selection_start=0,selection_end=2)):
    with self.subTest(source=source),self.assertRaises(ValueError):self.prepare(connection,source)
   self.assertEqual(wire['calls'],[])
 def test_outline_body_lock_and_config_changes_block_old_execution_and_adoption(self):
  from novel_writer.application.book_creation import BookCreation
  with supplier(output='旧来源扩写。') as wire:
   connection=self.connection(wire);prepared=self.prepare(connection);self.action('save_chapter_outline',dict(chapter_id=self.cid,core_idea='作者更新细纲',objective='变化',story_time='第2天',character_ids=[self.chid],scenes=[dict(order=1,summary='改变',character_ids=[self.chid],location='门外',story_time=''),dict(order=2,summary='作者改过的第二场',character_ids=[self.chid],location='门外',story_time='')]))
   with self.assertRaises(ValueError):self.execute(prepared)
   self.assertEqual(wire['calls'],[])
   done=self.execute(self.prepare(connection));review=self.review(done);self.action('save_chapter',dict(chapter_id=self.cid,content=self.original+'作者追加'))
   with self.assertRaises(ValueError):self.accept(done,review)
   self.assertEqual(len(wire['calls']),1)
   planning=BookCreation(self.service);planning.start(self.pid,dict(operation_id=str(uuid4()),name='锁定方案',expected_revision=self.service.get(self.pid)['revision']));version=planning.describe(self.pid)['selected'];pending=self.prepare(connection);planning.set_lock(self.pid,dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision'],version_id=version['id'],field='ending',locked=True,current_lock_id=None,confirmed=True))
   with self.assertRaises(ValueError):self.execute(pending)
   self.assertEqual(len(wire['calls']),1)
 def test_confirm_chapter_requires_authorization_and_adoption_is_idempotent(self):
  self.action('save_chapter',dict(chapter_id=self.cid,content=self.original,status='confirmed'))
  with supplier(output='确认章的新扩写。') as wire:
   connection=self.connection(wire);done=self.execute(self.prepare(connection));review=self.review(done)
   base=dict(task_id=done['task']['id'],candidate_id=done['latest_candidate']['id'],candidate_sha256=done['latest_candidate']['data_sha256'],review_id=review['id'],review_sha256=review['review_sha256'],expected_revision=self.service.get(self.pid)['revision'],confirm_chapter=True)
   with self.assertRaises(ValueError):self.engine.accept(self.pid,dict(base,operation_id=str(uuid4()),authorize_confirmed=False))
   request=dict(base,operation_id=str(uuid4()),authorize_confirmed=True);receipt=self.engine.accept(self.pid,request);self.assertEqual(self.engine.accept(self.pid,request),receipt)
   with self.assertRaises(ValueError):self.engine.accept(self.pid,dict(request,authorize_confirmed=False))
   self.assertEqual(len(wire['calls']),1)
 def test_cancel_late_response_is_retained_without_candidate_or_resend(self):
  with supplier(output='迟到的场景扩写。') as wire:
   prepared=self.prepare(self.connection(wire));task=prepared['task'];before=self.service.get(self.pid)['document']
   self.engine.adapter.transport.capture_response=lambda _:self.engine.cancel(self.pid,task['id']);done=self.execute(prepared);view=self.engine.describe(self.pid,task['id'])
   self.assertEqual(view['status'],'cancelled');self.assertEqual(view['candidates'],[]);self.assertEqual(view['adoptions'],[]);self.assertEqual(self.service.get(self.pid)['document'],before);self.assertEqual(len(view['late_results']),1);self.assertTrue(view['late_results'][0]['response']['complete']);self.assertEqual(len(wire['calls']),1)
   with self.assertRaises(ValueError):self.engine.start(self.pid,task['id'],dict(confirm_external=True,request_sha256=task['binding']['request_sha256']))
 def test_v18_backup_restore_copy_and_pending_permission_not_inherited(self):
  from novel_writer.application.backups import create_backup,restore_backup
  from novel_writer.application.migrations import migrate
  from novel_writer.application.skill_import import SkillLibrary
  with supplier(output='备份中的扩写。') as wire:
   connection=self.connection(wire);done=self.execute(self.prepare(connection));self.accept(done);pending=self.prepare(connection);state=self.service.get(self.pid);self.assertGreaterEqual(state['workspace_version'],18)  # V50 记忆刷新排队会推高版本
   SkillLibrary(self.db);package=self.root/'expansion.nwbak';self.assertGreaterEqual(create_backup(self.db,package)['backup_format_version'],51);restored=restore_backup(package,self.root/'restored');self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid),state)
   target=self.root/'copy.sqlite3';SQLiteRepository(target);SkillLibrary(target);copied=migrate(package,target,operation_id=str(uuid4()));pid=copied['projects'][0]['new_id'];clone=NovelService(SQLiteRepository(target)).get(pid)
   self.assertEqual(len(clone['scene_expansion_candidates']),1);self.assertEqual(len(clone['scene_expansion_reviews']),1);self.assertEqual(clone['scene_expansion_adoptions'][0]['review_id'],clone['scene_expansion_reviews'][0]['id']);self.assertEqual(clone['document']['chapters'][0]['content'],self.original+'备份中的扩写。');self.assertNotIn('fiction-expansion-key',json.dumps(clone))
   engine=TaskCoordinator(NovelService(SQLiteRepository(target)),AdapterRegistry());self.addCleanup(engine.close);new=self.api.SceneExpansionCoordinator(engine,self.providers,enabled=True);old=next(v for v in clone['scene_expansion_tasks'] if next(e['status'] for e in reversed(clone['scene_expansion_events']) if e['task_id']==v['id'])=='pending')
   self.assertEqual(new.describe(pid,old['id'])['display_status'],'interrupted')
   with self.assertRaises(ValueError):new.start(pid,old['id'],dict(confirm_external=True,request_sha256=old['binding']['request_sha256']))
   self.assertEqual(len(wire['calls']),1)
 def test_empty_output_is_failure_without_candidate_or_body_write(self):
  with supplier(output='') as wire:
   done=self.execute(self.prepare(self.connection(wire)));self.assertEqual(done['status'],'failed');self.assertEqual(done['candidates'],[]);self.assertEqual(self.service.get(self.pid)['document']['chapters'][0]['content'],self.original);self.assertEqual(len(wire['calls']),1)
 def test_draft_creation_preset_is_used_when_no_override_is_supplied(self):
  from novel_writer.application.creation_presets import CreationPresets
  with supplier(output='预设扩写文本。') as wire:
   connection=self.connection(wire);presets=CreationPresets(self.service);profile=dict(step='draft',**{k:v for k,v in self.options(connection).items() if k!='prompt_version'})
   saved=presets.save(self.pid,dict(operation_id=str(uuid4()),preset_id=None,name='扩写正文预设',settings=dict(steps=[profile],style_id=None,style_prompt='',manuscript_language='zh-CN',budget=dict(max_external_calls=2,max_reserved_output_tokens=4096,risk_budget=2.0,allow_unknown_cost=True)),expected_revision=self.service.get(self.pid)['revision']));presets.choose(self.pid,dict(operation_id=str(uuid4()),version_id=saved['version_id'],confirmed=True,expected_revision=self.service.get(self.pid)['revision']))
   prepared=self.prepare(None);self.assertEqual(prepared['task']['selection_source'],'preset');done=self.execute(prepared);self.assertEqual(done['status'],'succeeded');self.assertEqual(len(wire['calls']),1)
if __name__=='__main__':unittest.main()
