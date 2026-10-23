import json,base64,unittest,threading,time
from importlib import util,import_module
from uuid import uuid4
from test_styles import StyleTests,FEATURES
from test_book_ai import BookAITests,supplier
from novel_writer.application.comparisons import ComparisonCoordinator

class TrialTests(StyleTests):
 def setUp(self):
  super().setUp();self.assertIsNotNone(util.find_spec('novel_writer.application.style_trials'),'typed short style-trial workflow is missing');self.api=import_module('novel_writer.application.style_trials');self.trials=self.api.TrialCoordinator(self.shared,self.providers,self.styles,enabled=True);self.arena=ComparisonCoordinator(self.service,self.shared)
 def seed_options(self,**changes):
  value=dict(scope='custom',chapter_id=None,plan_version_id=None,fields=[],author_text='作者自有设定：送信人停在虚构雾港。',instruction='试写送信人犹豫的一瞬。',rubric='比较视角一致、节奏与具体描写；不推断通用排名。',target_chars=300,include_rules=False,include_preset_prompt=False,chapter_start=0,chapter_end=None);value.update(changes);return value
 def card(self,name,prompt):return self.styles.save_card(self.pid,dict(operation_id=str(uuid4()),style_id=None,name=name,prompt=prompt,card=FEATURES,analysis_id=None,confirmed=True))
 def prepare_trial(self,connection,style=None,options=None,**changes):
  options=options or self.seed_options();preview=self.trials.preview(self.pid,options);request=dict(operation_id=str(uuid4()),seed_options=options,seed_sha256=preview['seed']['seed_sha256'],style_mode='card' if style else 'baseline',style_version_id=style['id'] if style else None,model_options=self.options(connection),max_calls=2,max_output_tokens=2048,timeout_ms=2000,retry_of=None);request.update(changes);return self.trials.prepare(self.pid,request)
 def run_trial(self,prepared):
  task=prepared['task'];self.trials.start(self.pid,task['id'],dict(confirm_external=True,request_sha256=task['request_sha256']));self.shared.wait_idle(5);return self.trials.describe(self.pid,task['id'])
 def compare(self,connection,left,right=None):
  options=self.seed_options();preview=self.trials.preview(self.pid,options);profiles=[dict(style_mode='card' if card else 'baseline',style_version_id=card['id'] if card else None,model_options=self.options(connection,model='fiction-side-'+str(i))) for i,card in enumerate((left,right))];return self.trials.create_comparison(self.pid,dict(experiment_id=str(uuid4()),title='自有种子文风试写A/B',seed_options=options,seed_sha256=preview['seed']['seed_sha256'],profiles=profiles,max_calls=2,max_output_tokens=2048,timeout_ms=2000))
 def test_empty_book_trial_freezes_own_seed_and_style_without_raw_material_or_fake_chapter(self):
  original=self.source('不能自动外发的原始提炼样本XYZ。'*30);style=self.card('动作风格','重视具体动作，少作评价。');before=self.service.get(self.pid)['document']
  with supplier(output='送信人的手停在门环旁。') as wire:
   prepared=self.prepare_trial(self.connection(wire),style);self.assertEqual(wire['calls'],[]);self.assertEqual(prepared['task']['task_type'],'style_trial');self.assertIsNone(prepared['task']['seed']['options']['chapter_id']);self.assertIn('重视具体动作',prepared['request_body']);self.assertNotIn('原始提炼样本XYZ',prepared['request_body']);done=self.run_trial(prepared);self.assertEqual(done['status'],'succeeded');self.assertEqual(len(wire['calls']),1);self.assertEqual(self.service.get(self.pid)['document'],before);self.assertEqual(done['candidate']['output_text'],'送信人的手停在门环旁。')
 def test_explicit_baseline_does_not_inherit_active_card_rules_or_preset_prompt(self):
  style=self.card('正在应用的卡','不应出现在基线的卡提示。');self.styles.choose(self.pid,dict(operation_id=str(uuid4()),chapter_id=None,version_id=style['id'],confirmed=True));state=self.service.get(self.pid);self.service.execute(self.pid,'save_writing_rules',dict(content='不应隐式继承的旧规则。'),expected_revision=state['revision'])
  with supplier(output='基线短段。') as wire:
   baseline=self.prepare_trial(self.connection(wire));self.assertNotIn(style['prompt'],baseline['request_body']);self.assertNotIn('不应隐式继承',baseline['request_body']);self.assertIn('baseline',baseline['request_body']);self.assertEqual(len(wire['calls']),0)
 def test_arena_reuses_blind_scores_reveal_and_two_styles_share_the_same_actual_seed(self):
  left=self.card('克制','克制的动作与短句。');right=self.card('舒缓','舒缓的描写与长句。');before=self.service.get(self.pid)['document']
  with supplier(output='虚构试写短段。') as wire:
   created=self.compare(self.connection(wire),left,right);identifier=created['experiment_id'];setup=self.arena.setup(self.pid,identifier);self.assertEqual(len(setup['configurations']),2);bodies=[json.loads(v['request_body']) for v in setup['configurations']];inputs=[json.loads(v['messages'][-1]['content']) for v in bodies];self.assertEqual(inputs[0]['seed'],inputs[1]['seed']);self.assertNotEqual(inputs[0]['style'],inputs[1]['style']);self.assertEqual(wire['calls'],[])
   for configuration in setup['configurations']:self.arena.execute(self.pid,identifier,configuration['configuration_id'],dict(confirm_external=True,request_sha256=configuration['request_sha256']));self.shared.wait_idle(5)
   blind=self.arena.blind(self.pid,identifier);self.assertTrue(blind['ready']);self.assertNotIn(left['id'],json.dumps(blind));self.assertNotIn(right['id'],json.dumps(blind));self.assertFalse(blind['quality_ranking_verified'])
   for side in ('A','B'):self.arena.score(self.pid,identifier,dict(operation_id=str(uuid4()),side=side,rating=4,outcome='scored',notes='仅本段作者判断',expected_revision=self.service.get(self.pid)['revision']))
   revealed=self.arena.reveal(self.pid,identifier,dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision']));task=revealed['identities'][0]['task_id'];self.trials.choose(self.pid,dict(operation_id=str(uuid4()),task_id=task,action='apply_style',chapter_id=None,confirmed=True));self.assertEqual(self.service.get(self.pid)['document'],before);self.assertEqual(len(wire['calls']),2)
 def test_cancelled_trial_is_unscorable_and_late_response_never_applies_style(self):
  style=self.card('取消卡','取消时不要应用。')
  with supplier(slow=True,output='迟到短段。') as wire:
   prepared=self.prepare_trial(self.connection(wire),style);task=prepared['task'];self.trials.start(self.pid,task['id'],dict(confirm_external=True,request_sha256=task['request_sha256']));self.assertTrue(wire['seen'].wait(2));self.trials.cancel(self.pid,task['id']);wire['release'].set();self.shared.wait_idle(4);done=self.trials.describe(self.pid,task['id']);self.assertEqual(done['status'],'cancelled');self.assertEqual(self.service.get(self.pid)['style_choices'],[])
   with self.assertRaises(ValueError):self.trials.choose(self.pid,dict(operation_id=str(uuid4()),task_id=task['id'],action='apply_style',chapter_id=None,confirmed=True))
 def test_source_revision_or_lock_changes_block_old_approval_and_style_choice(self):
  style=self.card('守卫卡','只读候选。');state=self.service.get(self.pid);self.service.execute(self.pid,'save_worldbuilding',dict(content='原始作者世界。'),expected_revision=state['revision']);options=self.seed_options(scope='book',fields=['worldbuilding'])
  with supplier(output='新的短段。') as wire:
   connection=self.connection(wire);prepared=self.prepare_trial(connection,style,options);state=self.service.get(self.pid);self.service.execute(self.pid,'save_worldbuilding',dict(content='作者更新世界。'),expected_revision=state['revision'])
   with self.assertRaises(ValueError):self.run_trial(prepared)
   self.assertEqual(wire['calls'],[]);done=self.run_trial(self.prepare_trial(connection,style,options));state=self.service.get(self.pid);self.service.execute(self.pid,'save_worldbuilding',dict(content='作者再次更新世界。'),expected_revision=state['revision'])
   with self.assertRaises(ValueError):self.trials.choose(self.pid,dict(operation_id=str(uuid4()),task_id=done['task']['id'],action='apply_style',chapter_id=None,confirmed=True))
 def test_trial_arena_complete_copy_keeps_styles_scores_choices_and_prior_v14_rows(self):
  from contextlib import closing
  import sqlite3
  from novel_writer.application.backups import create_backup,restore_backup
  from novel_writer.application.migrations import migrate
  from novel_writer.application.skill_import import SkillLibrary
  from novel_writer.application.service import NovelService
  from novel_writer.storage.sqlite_repository import SQLiteRepository
  from novel_writer.application.public_search import SearchCoordinator
  with supplier(output='完整保存的短段。') as wire:
   connection=self.connection(wire);self.source('V13/V14虚构原资料。');search=SearchCoordinator(self.shared,self.providers,self.styles,enabled=True);native=self.connection(wire,'gemini-content');search.prepare(self.pid,dict(operation_id=str(uuid4()),title='虚构旧V14记录',platform='虚构平台',author='',model_options=self.options(native),max_calls=1,max_output_tokens=512));self.assertEqual(self.service.get(self.pid)['workspace_version'],14)
   left=self.card('保留卡','保留这份风格。');created=self.compare(connection,left);identifier=created['experiment_id']
   for config in self.arena.setup(self.pid,identifier)['configurations']:self.arena.execute(self.pid,identifier,config['configuration_id'],dict(confirm_external=True,request_sha256=config['request_sha256']));self.shared.wait_idle(4)
   for side in ('A','B'):self.arena.score(self.pid,identifier,dict(operation_id=str(uuid4()),side=side,rating=3,outcome='scored',notes='历史评价',expected_revision=self.service.get(self.pid)['revision']))
   revealed=self.arena.reveal(self.pid,identifier,dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision']));self.trials.choose(self.pid,dict(operation_id=str(uuid4()),task_id=revealed['identities'][0]['task_id'],action='apply_style',chapter_id=None,confirmed=True));SkillLibrary(self.db);package=self.root/'trials.nwbak';self.assertEqual(create_backup(self.db,package)['backup_format_version'],51);restored=restore_backup(package,self.root/'trial-restored');self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid),self.service.get(self.pid));target=self.root/'trial-copy.sqlite3';SQLiteRepository(target);SkillLibrary(target);copied=migrate(package,target,operation_id=str(uuid4()));clone=NovelService(SQLiteRepository(target)).get(copied['projects'][0]['new_id']);self.assertEqual(len(clone['style_trial_candidates']),2);self.assertEqual(len(clone['comparison_scores']),2);self.assertEqual(clone['style_trial_choices'][0]['style_choice_id'],clone['style_choices'][-1]['id']);self.assertEqual(clone['document']['chapters'],[]);self.assertEqual(len(wire['calls']),2)
 def test_experiment_replay_binds_style_profiles_and_limits_not_only_title_and_seed(self):
  with supplier(output='只准备不发送。') as wire:
   connection=self.connection(wire);style=self.card('绑定卡','样式甲');options=self.seed_options();preview=self.trials.preview(self.pid,options);profile=dict(style_mode='card',style_version_id=style['id'],model_options=self.options(connection));request=dict(experiment_id=str(uuid4()),title='幂等实验',seed_options=options,seed_sha256=preview['seed']['seed_sha256'],profiles=[profile,dict(profile,style_mode='baseline',style_version_id=None)],max_calls=2,max_output_tokens=2048,timeout_ms=2000);first=self.trials.create_comparison(self.pid,request);self.assertEqual(self.trials.create_comparison(self.pid,request),first)
   with self.assertRaises(ValueError):self.trials.create_comparison(self.pid,dict(request,max_output_tokens=4096))
 def test_failed_side_requires_unscorable_and_cannot_win_or_apply_style(self):
  style=self.card('成功侧卡','具体而克制。');options=self.seed_options();preview=self.trials.preview(self.pid,options)
  with supplier(output='') as bad,supplier(output='成功的短段。') as good:
   left=self.connection(bad);right=self.connection(good);profiles=[dict(style_mode='baseline',style_version_id=None,model_options=self.options(left)),dict(style_mode='card',style_version_id=style['id'],model_options=self.options(right))];created=self.trials.create_comparison(self.pid,dict(experiment_id=str(uuid4()),title='失败侧独立',seed_options=options,seed_sha256=preview['seed']['seed_sha256'],profiles=profiles,max_calls=2,max_output_tokens=1024,timeout_ms=2000));identifier=created['experiment_id']
   for config in self.arena.setup(self.pid,identifier)['configurations']:self.arena.execute(self.pid,identifier,config['configuration_id'],dict(confirm_external=True,request_sha256=config['request_sha256']));self.shared.wait_idle(4)
   blind=self.arena.blind(self.pid,identifier);failed=next(v for v in blind['candidates'] if v['status']=='failed')
   with self.assertRaises(ValueError):self.arena.score(self.pid,identifier,dict(operation_id=str(uuid4()),side=failed['side'],rating=0,outcome='scored',notes='',expected_revision=self.service.get(self.pid)['revision']))
   for result in blind['candidates']:self.arena.score(self.pid,identifier,dict(operation_id=str(uuid4()),side=result['side'],rating=4 if result['status']=='succeeded' else None,outcome='scored' if result['status']=='succeeded' else 'unscorable',notes='失败单列',expected_revision=self.service.get(self.pid)['revision']))
   self.arena.reveal(self.pid,identifier,dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision']))
   with self.assertRaises(ValueError):self.arena.choose(self.pid,identifier,dict(operation_id=str(uuid4()),side=failed['side'],action='open_candidate',name='',expected_revision=self.service.get(self.pid)['revision']))
 def test_trial_preset_chapter_range_explicit_rules_and_lock_guards_are_real_inputs(self):
  from novel_writer.application.creation_presets import CreationPresets
  state=self.service.get(self.pid);state=self.service.execute(self.pid,'add_chapter',dict(title='自己的章节'),expected_revision=state['revision']);chapter=state['document']['chapters'][0]['id'];self.service.execute(self.pid,'save_chapter',dict(chapter_id=chapter,content='甲乙丙丁戊己庚辛壬癸。'),expected_revision=state['revision']);state=self.service.get(self.pid);self.service.execute(self.pid,'save_writing_rules',dict(content='显式旧规则标记。'),expected_revision=state['revision'])
  with supplier(output='章节范围短段。') as wire:
   connection=self.connection(wire);preset=CreationPresets(self.service);step=dict(step='style_trial',**{k:v for k,v in self.options(connection).items() if k!='prompt_version'});saved=preset.save(self.pid,dict(operation_id=str(uuid4()),preset_id=None,name='试写步骤',settings=dict(steps=[step],style_id=None,style_prompt='显式预设标记。',manuscript_language='zh-CN',budget=dict(max_external_calls=2,max_reserved_output_tokens=2048,risk_budget=1.0,allow_unknown_cost=True)),expected_revision=self.service.get(self.pid)['revision']));preset.choose(self.pid,dict(operation_id=str(uuid4()),version_id=saved['version_id'],confirmed=True,expected_revision=self.service.get(self.pid)['revision']));options=self.seed_options(scope='chapter',chapter_id=chapter,fields=['chapter_body'],chapter_start=2,chapter_end=6,include_rules=True,include_preset_prompt=True);prepared=self.prepare_trial(connection,None,options,model_options=None);payload=json.loads(json.loads(prepared['request_body'])['messages'][-1]['content']);self.assertEqual(payload['seed']['selected_saved_material']['chapter_body']['text'],'丙丁戊己');self.assertEqual(payload['explicit_legacy_rules'],'显式旧规则标记。');self.assertEqual(payload['explicit_preset_prompt'],'显式预设标记。');self.assertEqual(payload['style']['mode'],'baseline');self.assertEqual(prepared['task']['preset_version_id'],saved['version_id']);self.manual.set_lock(self.pid,dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision'],version_id=self.manual.describe(self.pid)['selected']['id'],field='ending',locked=True,current_lock_id=None,confirmed=True))
   with self.assertRaises(ValueError):self.run_trial(prepared)
   self.assertEqual(wire['calls'],[])
 def test_restart_invalidates_old_permission_and_explicit_retry_keeps_prior_task(self):
  from novel_writer.application.tasks import TaskCoordinator
  from novel_writer.application.task_protocol import AdapterRegistry
  from novel_writer.application.styles import StyleCoordinator
  with supplier(output='重准备后的短段。') as wire:
   connection=self.connection(wire);prepared=self.prepare_trial(connection);old=prepared['task'];parent=TaskCoordinator(self.service,AdapterRegistry());self.addCleanup(parent.close);styles=StyleCoordinator(parent,self.providers,enabled=True);trials=self.api.TrialCoordinator(parent,self.providers,styles,enabled=True);self.assertEqual(trials.describe(self.pid,old['id'])['display_status'],'interrupted')
   with self.assertRaises(ValueError):trials.start(self.pid,old['id'],dict(confirm_external=True,request_sha256=old['request_sha256']))
   self.assertEqual(wire['calls'],[]);request=dict(operation_id=str(uuid4()),seed_options=self.seed_options(),seed_sha256=trials.preview(self.pid,self.seed_options())['seed']['seed_sha256'],style_mode='baseline',style_version_id=None,model_options=self.options(connection),max_calls=1,max_output_tokens=512,timeout_ms=2000,retry_of=old['id']);retry=trials.prepare(self.pid,request);self.assertEqual(retry['task']['retry_of'],old['id']);self.assertEqual(wire['calls'],[]);trials.start(self.pid,retry['task']['id'],dict(confirm_external=True,request_sha256=retry['task']['request_sha256']));parent.wait_idle(4);self.assertEqual(trials.describe(self.pid,retry['task']['id'])['status'],'succeeded');self.assertEqual(len(self.service.get(self.pid)['style_trial_tasks']),2);self.assertEqual(len(wire['calls']),1)
 def test_three_protocols_send_short_trial_semantics_and_never_enable_search_tools(self):
  for protocol in ('openai-chat','anthropic-messages','gemini-content'):
   with self.subTest(protocol=protocol),supplier(protocol,output='三协议短段。') as wire:
    prepared=self.prepare_trial(self.connection(wire,protocol));done=self.run_trial(prepared);self.assertEqual(done['status'],'succeeded');self.assertEqual(len(wire['calls']),1);self.assertNotIn('tools',wire['calls'][0]['body']);self.assertIn('short style trial',prepared['request_body']);self.assertEqual(self.service.get(self.pid)['document']['chapters'],[])

for parent in (StyleTests,BookAITests):
 for name in parent.__dict__:
  if name.startswith('test_') and name not in TrialTests.__dict__:setattr(TrialTests,name,None)
if __name__=='__main__':unittest.main()
