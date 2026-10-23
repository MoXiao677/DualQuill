import base64,json,sqlite3,threading,unittest
from contextlib import closing
from pathlib import Path
from importlib import import_module,util
from uuid import uuid4
from test_book_ai import BookAITests,supplier

FEATURES=dict(viewpoint='限知视角',syntax_vocabulary='短句与具体动词',rhythm='关键处放慢',dialogue='留白的短对话',description='感官细节',rhetoric_emotion='克制表达')
def output(start,end):return json.dumps(dict(prompt='采用限知视角，以具体动作推进，克制抒情。',card=FEATURES,evidence=[dict(start=start,end=end,feature='viewpoint')]),ensure_ascii=False)

class StyleTests(BookAITests):
 # Reuse only fixture helpers; inherited book-AI tests are deliberately excluded below.
 def setUp(self):
  super().setUp();self.assertIsNotNone(util.find_spec('novel_writer.application.styles'),'style import/extraction service is missing');self.styles=import_module('novel_writer.application.styles').StyleCoordinator(self.shared,self.providers,enabled=True)
 def source(self,text='虚构长文。'*700,kind='book',**changes):
  raw=text.encode('utf-8-sig');request=dict(operation_id=str(uuid4()),kind=kind,name='fiction.md',encoding='auto',origin='用户自有虚构资料',data_base64=base64.b64encode(raw).decode());request.update(changes);return self.styles.import_source(self.pid,request)
 def analysis(self,source,connection,**changes):
  request=dict(operation_id=str(uuid4()),source_id=source['id'],start=0,end=source['char_count'],chunk_chars=2000,model_options=self.options(connection),max_calls=4,max_output_tokens=4096);request.update(changes);return self.styles.create_analysis(self.pid,request)
 def run_chunk(self,analysis):
  prepared=self.styles.prepare_next(self.pid,dict(operation_id=str(uuid4()),analysis_id=analysis['id']));request=prepared['request'];self.styles.start(self.pid,request['id'],dict(confirm_external=True,request_sha256=request['request_sha256']));self.shared.wait_idle(5);return self.styles.describe(self.pid,analysis['id'])
 def test_source_bytes_encoding_hash_ranges_and_dedup_are_independent_of_snapshots(self):
  source=self.source();detail=self.styles.source(self.pid,source['id']);self.assertEqual(detail['text'],'虚构长文。'*700);self.assertEqual(base64.b64decode(detail['data_base64']),('虚构长文。'*700).encode('utf-8-sig'));self.assertEqual(detail['encoding'],'utf-8-sig');self.assertEqual(self.service.get(self.pid)['document']['chapters'],[])
  for _ in range(3):self.styles.save_card(self.pid,dict(operation_id=str(uuid4()),style_id=None,name='人工文风',prompt='具体动词',card=FEATURES,analysis_id=None,confirmed=True))
  with closing(sqlite3.connect(self.db)) as db:
   self.assertEqual(db.execute('SELECT count(*) FROM content_blobs').fetchone()[0],1);self.assertNotIn(detail['data_base64'],db.execute('SELECT payload FROM projects WHERE id=?',(self.pid,)).fetchone()[0])
  with self.assertRaises(ValueError):self.source(name='../unsafe.txt')
  with self.assertRaises(ValueError):self.source(data_base64=base64.b64encode(b'\xff\x00binary').decode())
 def test_manual_card_versions_book_and_chapter_choices_feed_actual_task_snapshot_without_body_write(self):
  from novel_writer.application.context_preview import preview
  state=self.service.get(self.pid);self.service.execute(self.pid,'add_chapter',dict(title='虚构章'),expected_revision=state['revision']);chapter=self.service.get(self.pid)['document']['chapters'][0]['id'];before=self.service.get(self.pid)['document'];card=self.styles.save_card(self.pid,dict(operation_id=str(uuid4()),style_id=None,name='作者自己的卡',prompt='每个场景只跟随一个人物。',card=FEATURES,analysis_id=None,confirmed=True));self.styles.choose(self.pid,dict(operation_id=str(uuid4()),chapter_id=None,version_id=card['id'],confirmed=True));options=dict(chapter_id=chapter,scope='previous');context=preview(self.service.get(self.pid),options);self.assertIn('每个场景只跟随一个人物。',context['context_text']);self.assertEqual(context['style_snapshot']['id'],card['id']);self.assertEqual(self.service.get(self.pid)['document'],before)
 def test_chunk_progress_explicit_confirmation_and_partial_coverage_need_no_automatic_calls(self):
  source=self.source('虚构资料。'*900)
  with supplier(output=output(0,2000)) as wire:
   analysis=self.analysis(source,self.connection(wire));prepared=self.styles.prepare_next(self.pid,dict(operation_id=str(uuid4()),analysis_id=analysis['id']));self.assertEqual(len(wire['calls']),0)
   with self.assertRaises(ValueError):self.styles.start(self.pid,prepared['request']['id'],dict(confirm_external=True,request_sha256='0'*64))
   self.styles.start(self.pid,prepared['request']['id'],dict(confirm_external=True,request_sha256=prepared['request']['request_sha256']));self.shared.wait_idle(5);view=self.styles.describe(self.pid,analysis['id']);self.assertEqual(view['covered_chars'],2000);self.assertEqual(view['source_chars'],len('虚构资料。'*900));self.assertFalse(view['full_source']);self.assertEqual(len(wire['calls']),1);draft=self.styles.compile(self.pid,analysis['id']);self.assertEqual(draft['coverage'][0]['end'],2000);self.assertEqual(self.service.get(self.pid)['document']['chapters'],[])
 def test_cancelled_chunk_and_restart_do_not_repeat_completed_blocks(self):
  source=self.source('虚构取消。'*600)
  with supplier(slow=True,output=output(0,2000)) as wire:
   analysis=self.analysis(source,self.connection(wire));prepared=self.styles.prepare_next(self.pid,dict(operation_id=str(uuid4()),analysis_id=analysis['id']));request=prepared['request'];self.styles.start(self.pid,request['id'],dict(confirm_external=True,request_sha256=request['request_sha256']));self.assertTrue(wire['seen'].wait(2));self.styles.cancel(self.pid,request['id']);wire['release'].set();self.shared.wait_idle(4);view=self.styles.describe(self.pid,analysis['id']);self.assertEqual(view['covered_chars'],0);self.assertEqual(view['requests'][0]['status'],'cancelled');self.assertEqual(len(wire['calls']),1)
 def test_invalid_model_card_is_correctable_and_original_response_survives(self):
  source=self.source('虚构文章。'*100,kind='article')
  with supplier(output='{"prompt":"缺少证据和风格维度"}') as wire:
   analysis=self.analysis(source,self.connection(wire));view=self.run_chunk(analysis);candidate=view['requests'][0]['latest_candidate'];self.assertTrue(candidate['errors']);corrected=self.styles.correct(self.pid,dict(operation_id=str(uuid4()),request_id=view['requests'][0]['request']['id'],candidate_id=candidate['id'],text=output(0,source['char_count'])));self.assertEqual(corrected['covered_chars'],source['char_count']);self.assertEqual(len(wire['calls']),1);self.assertIn('缺少证据',corrected['requests'][0]['response']['raw_response']);draft=self.styles.compile(self.pid,analysis['id']);card=self.styles.save_card(self.pid,dict(operation_id=str(uuid4()),style_id=None,name='作者复核提炼',prompt=draft['prompt'],card=draft['card'],analysis_id=analysis['id'],coverage_sha256=draft['coverage_sha256'],confirmed=True));self.assertEqual(card['coverage'][0]['end'],source['char_count'])
 def test_complete_backup_restore_copy_keeps_raw_assets_and_all_style_history(self):
  from novel_writer.application.backups import create_backup,restore_backup
  from novel_writer.application.migrations import migrate
  from novel_writer.application.skill_import import SkillLibrary
  source=self.source();card=self.styles.save_card(self.pid,dict(operation_id=str(uuid4()),style_id=None,name='手动导入',prompt='短句。',card=FEATURES,analysis_id=None,confirmed=True));self.styles.choose(self.pid,dict(operation_id=str(uuid4()),chapter_id=None,version_id=card['id'],confirmed=True));SkillLibrary(self.db);package=self.root/'styles.nwbak';self.assertEqual(create_backup(self.db,package)['backup_format_version'],51);restored=restore_backup(package,self.root/'restored');self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid),self.service.get(self.pid));target=self.root/'copy-style.sqlite3';SQLiteRepository(target);SkillLibrary(target);copied=migrate(package,target,operation_id=str(uuid4()));clone=NovelService(SQLiteRepository(target)).get(copied['projects'][0]['new_id']);self.assertEqual(clone['style_sources'][0]['blob_sha256'],source['blob_sha256']);self.assertEqual(clone['style_choices'][0]['version_id'],clone['style_cards'][0]['id'])
 def test_explicit_budget_extension_completes_all_chunks_without_repeating_success(self):
  source=self.source('虚构资料。'*900)
  with supplier(output=output(0,2000)) as wire:
   analysis=self.analysis(source,self.connection(wire),max_calls=1,max_output_tokens=512);view=self.run_chunk(analysis);self.assertEqual(view['covered_chars'],2000)
   with self.assertRaises(ValueError):self.styles.prepare_next(self.pid,dict(operation_id=str(uuid4()),analysis_id=analysis['id']))
   self.styles.extend_budget(self.pid,dict(operation_id=str(uuid4()),analysis_id=analysis['id'],additional_calls=2,additional_output_tokens=1024,confirmed=True))
   for start,end in [(2000,4000),(4000,source['char_count'])]:
    view=self.run_chunk(analysis);candidate=view['requests'][-1]['latest_candidate'];view=self.styles.correct(self.pid,dict(operation_id=str(uuid4()),request_id=view['requests'][-1]['request']['id'],candidate_id=candidate['id'],text=output(start,end)))
   self.assertEqual(view['covered_chars'],source['char_count']);self.assertTrue(view['full_source']);self.assertEqual([json.loads(c['body']['messages'][-1]['content'])['range']['start'] for c in wire['calls']],[0,2000,4000]);self.assertEqual(len(self.styles.compile(self.pid,analysis['id'])['coverage']),3)
 def test_original_prompt_and_json_card_import_are_immediately_manual_and_versioned(self):
  raw=json.dumps(dict(prompt='我自己的声音：写得直接。',card=FEATURES),ensure_ascii=False).encode('utf-8-sig');request=dict(operation_id=str(uuid4()),name='作者自有卡',filename='my-style.json',encoding='auto',data_base64=base64.b64encode(raw).decode(),confirmed=True);card=self.styles.import_card(self.pid,request);self.assertEqual(card['prompt'],'我自己的声音：写得直接。');material=self.styles.source(self.pid,card['source_id']);self.assertEqual(base64.b64decode(material['data_base64']),raw);self.assertEqual(self.styles.listing(self.pid)['analyses'],[])
  edited=self.styles.save_card(self.pid,dict(operation_id=str(uuid4()),style_id=card['style_id'],name='作者自有卡二版',prompt='直接、具体。',card=FEATURES,analysis_id=None,confirmed=True));self.assertEqual(edited['previous_version_id'],card['id']);self.assertEqual(edited['source_id'],card['source_id'])
 def test_actual_model_request_consumes_chapter_style_and_respects_context_budget(self):
  from novel_writer.application.custom_protocols import ConfiguredHttpAdapter
  from novel_writer.domain.tasks import digest
  state=self.service.get(self.pid);state=self.service.execute(self.pid,'add_chapter',dict(title='原稿'),expected_revision=state['revision']);chapter=state['document']['chapters'][0]['id'];self.service.execute(self.pid,'save_chapter',dict(chapter_id=chapter,content='作者正文不能因选择风格被覆盖。'),expected_revision=state['revision']);card=self.styles.save_card(self.pid,dict(operation_id=str(uuid4()),style_id=None,name='章节卡',prompt='每段只跟随单一人物的感知。',card=FEATURES,analysis_id=None,confirmed=True));self.styles.choose(self.pid,dict(operation_id=str(uuid4()),chapter_id=chapter,version_id=card['id'],confirmed=True))
  with self.assertRaisesRegex(ValueError,'styles.context_budget'):self.service.preview_context(self.pid,dict(chapter_id=chapter,budget_chars=128))
  with supplier(output='虚构模型候选，仍待作者采用。') as wire:
   connection=self.connection(wire);adapter=ConfiguredHttpAdapter(self.providers,enabled=True);self.shared.registry.register('rewrite_chapter',adapter);options=dict(chapter_id=chapter,budget_chars=4000);context=self.service.preview_context(self.pid,options);task=self.shared.prepare(self.pid,dict(request_id=str(uuid4()),chapter_id=chapter,task_type='rewrite_chapter',context_options=options,context_sha256=digest(context['context_text']),parameters=dict(instruction='按所选风格改写',max_output_chars=2000,timeout_ms=3000),expected_revision=self.service.get(self.pid)['revision'],model_options=self.options(connection,model='fiction-default')))['task'];binding=task['frozen']['parameters']['binding'];self.assertIn(card['prompt'],binding['request_body']);self.shared.start(self.pid,task['id'],dict(confirm_external=True,request_sha256=binding['request_sha256']));self.shared.wait_idle(5);self.assertEqual(len(wire['calls']),1);self.assertIn(card['prompt'],wire['calls'][0]['body']['messages'][-1]['content']);self.assertEqual(self.service.get(self.pid)['document']['chapters'][0]['content'],'作者正文不能因选择风格被覆盖。')
 def test_extraction_results_corrections_budget_and_readonly_bytes_survive_complete_copy(self):
  from novel_writer.application.backups import create_backup,restore_backup
  from novel_writer.application.migrations import migrate
  from novel_writer.application.skill_import import SkillLibrary
  source=self.source('虚构测试文章。'*50)
  with supplier(output='bad structure') as wire:
   analysis=self.analysis(source,self.connection(wire));view=self.run_chunk(analysis);request=view['requests'][0];view=self.styles.correct(self.pid,dict(operation_id=str(uuid4()),request_id=request['request']['id'],candidate_id=request['latest_candidate']['id'],text=output(0,source['char_count'])));draft=self.styles.compile(self.pid,analysis['id']);card=self.styles.save_card(self.pid,dict(operation_id=str(uuid4()),style_id=None,name='已复核提炼卡',prompt=draft['prompt'],card=draft['card'],analysis_id=analysis['id'],coverage_sha256=draft['coverage_sha256'],confirmed=True));self.styles.extend_budget(self.pid,dict(operation_id=str(uuid4()),analysis_id=analysis['id'],additional_calls=1,additional_output_tokens=512,confirmed=True));self.styles.choose(self.pid,dict(operation_id=str(uuid4()),chapter_id=None,version_id=card['id'],confirmed=True));SkillLibrary(self.db);package=self.root/'all-style.nwbak';create_backup(self.db,package);restored=restore_backup(package,self.root/'all-restored');self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid),self.service.get(self.pid));target=self.root/'all-copy.sqlite3';SQLiteRepository(target);SkillLibrary(target);copied=migrate(package,target,operation_id=str(uuid4()));clone=NovelService(SQLiteRepository(target)).get(copied['projects'][0]['new_id']);self.assertEqual(clone['style_cards'][0]['coverage'][0]['candidate_id'],clone['style_candidates'][-1]['id']);self.assertEqual(len(clone['style_budgets']),1);self.assertEqual([v['response_sha256'] for v in clone['style_results']],[v['response_sha256'] for v in self.service.get(self.pid)['style_results']]);self.assertEqual(len(wire['calls']),1)
 def test_style_analysis_preset_and_native_protocols_are_consumed_without_copying_permissions(self):
  from novel_writer.application.creation_presets import CreationPresets
  for protocol in ('anthropic-messages','gemini-content'):
   with self.subTest(protocol=protocol),supplier(protocol,output=output(0,5)) as wire:
    source=self.source('虚构文章。');connection=self.connection(wire,protocol);presets=CreationPresets(self.service);profile=dict(step='style_analysis',**{k:v for k,v in self.options(connection).items() if k!='prompt_version'});settings=dict(steps=[profile],style_id=None,style_prompt='',manuscript_language='zh-CN',budget=dict(max_external_calls=2,max_reserved_output_tokens=1024,risk_budget=2.0,allow_unknown_cost=True));saved=presets.save(self.pid,dict(operation_id=str(uuid4()),preset_id=None,name='分析步骤原生协议',settings=settings,expected_revision=self.service.get(self.pid)['revision']));presets.choose(self.pid,dict(operation_id=str(uuid4()),version_id=saved['version_id'],confirmed=True,expected_revision=self.service.get(self.pid)['revision']));analysis=self.analysis(source,connection,model_options=None,max_calls=2,max_output_tokens=1024);view=self.run_chunk(analysis);self.assertEqual(view['covered_chars'],5);self.assertEqual(analysis['preset_version_id'],saved['version_id']);self.assertEqual(len(wire['calls']),1)
 def test_v12_raw_history_is_unchanged_when_styles_first_extend_the_library(self):
  with supplier() as wire:self.prepare(self.connection(wire))
  self.assertEqual(self.service.get(self.pid)['workspace_version'],12);before=self.db.read_bytes();reopened=NovelService(SQLiteRepository(self.db));reopened.get(self.pid);self.assertEqual(self.db.read_bytes(),before)
  with closing(sqlite3.connect(self.db)) as db:rows=db.execute('SELECT project_id,revision,payload,saved_at FROM project_snapshots ORDER BY project_id,revision').fetchall()
  self.source()
  with closing(sqlite3.connect(self.db)) as db:self.assertEqual(db.execute('SELECT project_id,revision,payload,saved_at FROM project_snapshots ORDER BY project_id,revision').fetchall()[:len(rows)],rows)
 def test_cross_book_preset_missing_style_is_explicit_and_local_style_binding_is_usable(self):
  from novel_writer.application.creation_presets import CreationPresets
  from novel_writer.domain.styles import selected_style
  card=self.styles.save_card(self.pid,dict(operation_id=str(uuid4()),style_id=None,name='本书卡',prompt='本书声音。',card=FEATURES,analysis_id=None,confirmed=True));preset=CreationPresets(self.service);settings=dict(steps=[dict(step='rewrite',adapter_id='configured-http-v2',connection_id=None,model_id='',temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=False)],style_id=card['id'],style_prompt='',manuscript_language='zh-CN',budget=dict(max_external_calls=1,max_reserved_output_tokens=512,risk_budget=1.0,allow_unknown_cost=False));saved=preset.save(self.pid,dict(operation_id=str(uuid4()),preset_id=None,name='带卡预设',settings=settings,expected_revision=self.service.get(self.pid)['revision']));preset.choose(self.pid,dict(operation_id=str(uuid4()),version_id=saved['version_id'],confirmed=True,expected_revision=self.service.get(self.pid)['revision']));self.assertEqual(selected_style(self.service.get(self.pid))['id'],card['id']);self.assertFalse(preset.preflight(self.pid,saved['version_id'],connections={})['missing_style']);other=self.service.create(title='虚构跨书目标')['document']['project']['id'];reused=preset.reuse(other,dict(operation_id=str(uuid4()),source_project_id=self.pid,version_id=saved['version_id'],expected_revision=self.service.get(other)['revision']));self.assertTrue(preset.preflight(other,reused['version_id'],connections={})['missing_style'])
 def test_card_confirmation_binds_the_actual_reviewed_candidate_coverage(self):
  source=self.source('虚构文章。')
  with supplier(output=output(0,5)) as wire:
   analysis=self.analysis(source,self.connection(wire));view=self.run_chunk(analysis);draft=self.styles.compile(self.pid,analysis['id']);request=view['requests'][0];self.styles.correct(self.pid,dict(operation_id=str(uuid4()),request_id=request['request']['id'],candidate_id=request['latest_candidate']['id'],text=output(0,5)))
   with self.assertRaisesRegex(ValueError,'styles.coverage_changed'):self.styles.save_card(self.pid,dict(operation_id=str(uuid4()),style_id=None,name='过期审阅',prompt=draft['prompt'],card=draft['card'],analysis_id=analysis['id'],coverage_sha256=draft.get('coverage_sha256'),confirmed=True))
 def test_large_aggregate_remains_editable_without_truncating_or_losing_coverage(self):
  source=self.source('虚构材料。'*600)
  with supplier(output=output(0,2000)) as wire:
   analysis=self.analysis(source,self.connection(wire))
   for index,(start,end) in enumerate([(0,2000),(2000,source['char_count'])]):
    view=self.run_chunk(analysis);request=view['requests'][-1];raw=json.loads(output(start,end));raw['prompt']=('甲' if index==0 else '乙')*5000;self.styles.correct(self.pid,dict(operation_id=str(uuid4()),request_id=request['request']['id'],candidate_id=request['latest_candidate']['id'],text=json.dumps(raw,ensure_ascii=False)))
   draft=self.styles.compile(self.pid,analysis['id']);self.assertTrue(draft['needs_condensation']);self.assertEqual(len(draft['prompt']),10001);self.assertEqual(len(draft['coverage']),2);card=self.styles.save_card(self.pid,dict(operation_id=str(uuid4()),style_id=None,name='人工浓缩后保留整书覆盖',prompt='作者审阅后浓缩的统一声音。',card=FEATURES,analysis_id=analysis['id'],coverage_sha256=draft['coverage_sha256'],confirmed=True));self.assertEqual(len(card['coverage']),2);self.assertEqual(len(wire['calls']),2)

from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository
for _name in list(BookAITests.__dict__):
 if _name.startswith('test_') and _name not in StyleTests.__dict__:setattr(StyleTests,_name,None)
if __name__=='__main__':unittest.main()
