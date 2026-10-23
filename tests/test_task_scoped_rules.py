"""C13 task isolation, immutable freezing and proposal trust boundaries; no provider calls."""
from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository
from novel_writer.application.scoped_rules import RuleCoordinator,require_fresh_rules
from novel_writer.application.tasks import TaskCoordinator,get_task
from novel_writer.application.task_protocol import AdapterRegistry,LocalProtocolAdapter
from novel_writer.domain.tasks import digest,encode


class TaskScopedRuleTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='c13-task-');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.db=self.root/'fiction.sqlite3'
  self.service=NovelService(SQLiteRepository(self.db));self.pid=self.service.create(title='虚构任务规则')['document']['project']['id']
  for title in ('甲章','乙章'):self.action('add_chapter',dict(title=title))
  self.cid,self.other=[v['id'] for v in self.state()['document']['chapters']]
  self.action('save_book_outline',dict(theme='',premise='',main_plot='',ending='',volumes=[dict(number=1,title='虚构卷',summary='',chapter_ids=[self.cid,self.other])]))
  self.rules=RuleCoordinator(self.service);registry=AdapterRegistry();registry.register('rewrite_chapter',LocalProtocolAdapter(delay_seconds=0));self.tasks=TaskCoordinator(self.service,registry);self.addCleanup(self.tasks.close)
 def state(self):return self.service.get(self.pid)
 def action(self,name,fields):return self.service.execute(self.pid,name,fields,expected_revision=self.state()['revision'])
 def bind(self,chapter=None,kind='rewrite_chapter',identifier=None):
  identifier=identifier or str(uuid4());self.rules.bind_task(self.pid,dict(request_id=identifier,chapter_id=chapter or self.cid,task_type=kind));return identifier
 def save(self,scope,kind,text,target=None):
  target=target if target is not None else {'book':self.pid,'chapter':self.cid,'volume':'1'}.get(scope)
  return self.rules.save(self.pid,dict(operation_id=str(uuid4()),rule_id=None,scope=scope,scope_id=target,kind=kind,text=text,enabled=True))
 def request(self,binding=None):
  options=dict(chapter_id=self.cid,budget_chars=20000)
  if binding is not None:options['rule_task_id']=binding
  report=self.service.preview_context(self.pid,options)
  return dict(request_id=binding or str(uuid4()),chapter_id=self.cid,task_type='rewrite_chapter',context_options=options,context_sha256=digest(report['context_text']),parameters=dict(instruction='虚构改写',max_output_chars=10000,timeout_ms=1000),expected_revision=self.state()['revision'])
 def prepare(self,binding=None):return self.tasks.prepare(self.pid,self.request(binding))['task']
 def test_task_priority_required_forbidden_guidance_and_no_leak(self):
  a=self.bind();b=self.bind();self.save('global','guidance','全局');self.save('book','guidance','书');self.save('volume','guidance','卷');self.save('chapter','guidance','章')
  for kind,text in [('required','任务必写'),('forbidden','任务禁写'),('guidance','任务指引')]:self.save('task',kind,text,a)
  self.save('task','guidance','别的任务',b)
  resolved=self.rules.resolve(self.pid,self.cid,a);self.assertEqual([v['scope'] for v in resolved['rules']],['task']*3+['chapter','volume','book','global'])
  self.assertEqual([v['kind'] for v in resolved['rules'][:3]],['required','forbidden','guidance'])
  self.assertFalse(any(v['scope']=='task' for v in self.rules.resolve(self.pid,self.cid)['rules']))
  self.assertNotIn('任务必写',self.service.preview_context(self.pid,dict(chapter_id=self.cid))['context_text'])
  task=self.prepare(a);self.assertIn('任务必写',task['frozen']['context_text']);self.assertNotIn('别的任务',task['frozen']['context_text'])
 def test_task_cannot_override_hard_conflict_or_dedup_lower_required(self):
  target=self.bind();self.save('book','required','同一硬约束');self.save('task','required','同一硬约束',target)
  self.assertEqual(len(self.rules.resolve(self.pid,self.cid,target)['rules']),1)
  self.save('task','forbidden','同一硬约束',target)
  with self.assertRaises(ValueError):self.prepare(target)
  self.assertEqual(len(self.rules.resolve(self.pid,self.cid)['rules']),1)
 def test_bound_identity_cannot_omit_rules_and_unrelated_task_conflict_does_not_block_import(self):
  a=self.bind();b=self.bind();self.save('task','required','冲突',a);self.save('task','forbidden','冲突',a)
  req=self.request();req['request_id']=b;before=self.state()
  with self.assertRaises(ValueError):self.tasks.prepare(self.pid,req)
  self.assertEqual(self.state(),before)
  content=json.dumps([dict(scope='task',scope_id=b,kind='guidance',text='另一任务独立导入',enabled=True)]);p=self.rules.preview_import(self.pid,dict(format='json',content=content));self.assertTrue(p['can_confirm'])
  self.rules.import_rules(self.pid,dict(operation_id=str(uuid4()),format='json',content=content,preview_sha256=p['preview_sha256']));self.prepare(b)
 def test_unknown_crossbook_crosschapter_cross_task_rejected_atomically(self):
  target=self.bind();request=self.request(target);request['request_id']=str(uuid4());before=self.state()
  with self.assertRaises(ValueError):self.tasks.prepare(self.pid,request)
  with self.assertRaises(ValueError):self.rules.resolve(self.pid,self.other,target)
  with self.assertRaises(ValueError):self.save('task','guidance','未知',str(uuid4()))
  other=self.service.create(title='另一虚构书')['document']['project']['id']
  with self.assertRaises(ValueError):self.rules.save(other,dict(operation_id=str(uuid4()),rule_id=None,scope='task',scope_id=target,kind='guidance',text='越界',enabled=True))
  self.assertEqual(self.state(),before)
 def test_binding_identity_type_and_existing_frozen_task_rejected(self):
  target=self.bind();before=self.state();self.bind(identifier=target);self.assertEqual(self.state(),before)
  with self.assertRaises(ValueError):self.bind(self.other,identifier=target)
  wrong=self.bind(kind='audit_chapter')
  with self.assertRaises(ValueError):self.prepare(wrong)
  task=self.prepare()
  with self.assertRaises(ValueError):self.bind(identifier=task['request_id'])
 def test_audit_acceptance_freshness_rechecks_added_task_rules(self):
  from test_s5a_rules import request_rules
  from novel_writer.application.reviews import assert_fresh
  self.action('save_chapter',dict(chapter_id=self.cid,content='虚构灯塔正文'))
  target=self.bind(kind='audit_chapter');self.save('task','guidance','审核关注叙事视角',target);req=self.request(target);req['task_type']='audit_chapter';req['parameters']=request_rules();req['parameters']['selected_chapter_ids']=[self.cid]
  task=self.tasks.prepare(self.pid,req)['task'];assert_fresh(self.tasks,self.state(),get_task(self.state(),task['id']))
  self.save('task','guidance','新增审核要求',target)
  with self.assertRaises(ValueError):assert_fresh(self.tasks,self.state(),get_task(self.state(),task['id']))
 def test_frozen_rules_immutable_and_edits_block_send_without_event(self):
  target=self.bind();rule=self.save('task','required','冻结必写',target);task=self.prepare(target);frozen=deepcopy(task['frozen'])
  self.rules.set_enabled(self.pid,dict(rule_id=rule['id'],enabled=False));before=self.state()
  with self.assertRaises(ValueError):self.tasks.start(self.pid,task['id'])
  self.assertEqual(self.state(),before);self.assertEqual(get_task(before,task['id']).frozen.context_text,frozen['context_text'])
 def test_new_rule_after_freeze_blocks_send_and_other_task_change_does_not(self):
  a=self.bind();b=self.bind();task=self.prepare(a);self.save('task','required','别任务新规则',b)
  require_fresh_rules(self.state(),get_task(self.state(),task['id']))
  self.save('task','guidance','本任务新规则',a)
  with self.assertRaises(ValueError):self.tasks.start(self.pid,task['id'])
 def test_new_rule_after_success_blocks_manual_adoption(self):
  target=self.bind();task=self.prepare(target);self.tasks.start(self.pid,task['id']);self.tasks.wait_idle(2);state=self.state();candidate=get_task(state,task['id']).candidate_id;self.assertIsNotNone(candidate)
  self.save('task','required','迟到的必写',target);before=self.state()
  with self.assertRaises(ValueError):self.tasks.adopt(self.pid,task['id'],dict(candidate_id=candidate,adoption_id=str(uuid4()),expected_revision=before['revision'],authorize_confirmed=False))
  self.assertEqual(self.state(),before)
 def test_import_conflict_isolation_atomic_and_replay_after_delete(self):
  a=self.bind();b=self.bind();self.save('task','required','同文',a)
  rows=[dict(scope='task',scope_id=b,kind='forbidden',text='同文',enabled=True)];content=json.dumps(rows);preview=self.rules.preview_import(self.pid,dict(format='json',content=content));self.assertTrue(preview['can_confirm'])
  req=dict(operation_id=str(uuid4()),format='json',content=content,preview_sha256=preview['preview_sha256']);created=self.rules.import_rules(self.pid,req);before=self.state();self.assertTrue(self.rules.import_rules(self.pid,req)['idempotent']);self.assertEqual(self.state(),before)
  self.rules.delete(self.pid,dict(rule_id=created['rules'][0]['id']));before=self.state()
  with self.assertRaises(ValueError):self.rules.import_rules(self.pid,req)
  self.assertEqual(self.state(),before)
  rows[0]['scope_id']=a;content=json.dumps(rows);preview=self.rules.preview_import(self.pid,dict(format='json',content=content));self.assertFalse(preview['can_confirm']);self.assertTrue(preview['conflicts'])
 def test_csv_and_json_unknown_target_and_history_failure_roll_back(self):
  target=self.bind();csv='scope,scope_id,kind,text,enabled\ntask,'+target+',guidance,虚构规则,true\n';p=self.rules.preview_import(self.pid,dict(format='csv',content=csv));self.assertTrue(p['can_confirm'])
  rows=[dict(scope='task',scope_id=target,kind='guidance',text='一',enabled=True),dict(scope='task',scope_id=target,kind='guidance',text='二',enabled=True)];content=json.dumps(rows);p=self.rules.preview_import(self.pid,dict(format='json',content=content));before=self.state()
  import novel_writer.application.scoped_rules as module
  original=module._history;calls=[]
  def fail(*args,**kwargs):
   calls.append(1)
   if len(calls)==2:raise RuntimeError('虚构事务故障')
   return original(*args,**kwargs)
  with patch.object(module,'_history',fail):
   with self.assertRaises(RuntimeError):self.rules.import_rules(self.pid,dict(operation_id=str(uuid4()),format='json',content=content,preview_sha256=p['preview_sha256']))
  self.assertEqual(self.state(),before)
  rows[1]['scope_id']=str(uuid4());p=self.rules.preview_import(self.pid,dict(format='json',content=json.dumps(rows)));self.assertFalse(p['can_confirm'])
 def test_semantic_unknown_remains_unverified_and_never_changes_rules(self):
  target=self.bind();a=self.save('task','required','主角始终第一人称',target);b=self.save('book','required','叙述者保持全知视角');before=self.state()
  req=dict(chapter_id=self.cid,task_id=target,observations=[dict(rule_ids=[a['id'],b['id']],quotes=['第一人称','全知视角'],reason='可能存在叙述视角冲突，尚待核实')]);result=self.rules.semantic_preview(self.pid,req)
  self.assertEqual(result['proposals'][0]['status'],'needs_verification');self.assertFalse(result['proposals'][0]['can_apply']);self.assertFalse(result['semantic_quality_verified']);self.assertFalse(result['model_request_sent']);self.assertEqual(result['exact_conflicts'],[]);self.assertEqual(self.state(),before)
  req['observations'][0]['quotes'][0]='捏造引文'
  with self.assertRaises(ValueError):self.rules.semantic_preview(self.pid,req)
  self.assertEqual(self.state(),before)
 def test_history_append_only_delete_auditable_reopen_and_copy(self):
  from novel_writer.application.backups import create_backup,restore_backup
  from novel_writer.application.migrations import migrate
  from novel_writer.application.skill_import import SkillLibrary
  target=self.bind();rule=self.save('task','guidance','保留旧任务规则',target);task=self.prepare(target);self.rules.delete(self.pid,dict(rule_id=rule['id']));before=self.state()
  self.assertEqual(len(self.rules.history(self.pid,rule['id'])['history']),2)
  def corrupt(state):state['scoped_rule_history'][0]['after']['text']='篡改';return state,True
  with self.assertRaises(ValueError):self.service.repository.atomic(self.pid,corrupt)
  self.assertEqual(NovelService(SQLiteRepository(self.db)).get(self.pid),before)
  SkillLibrary(self.db);package=self.root/'task-rules.nwbak';self.assertEqual(create_backup(self.db,package)['backup_format_version'],51)
  restored=restore_backup(package,self.root/'restored');self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid),before)
  clone_db=self.root/'clone.sqlite3';SQLiteRepository(clone_db);SkillLibrary(clone_db);copied=migrate(package,clone_db,operation_id=str(uuid4()));clone=NovelService(SQLiteRepository(clone_db)).get(copied['projects'][0]['new_id'])
  binding=clone['rule_task_bindings'][0];self.assertNotEqual(binding['id'],target);self.assertNotEqual(binding['chapter_id'],self.cid);self.assertEqual(clone['scoped_rule_history'][0]['after']['scope_id'],binding['id']);self.assertEqual(clone['generation_tasks'][0]['frozen']['context_options']['rule_task_id'],binding['id']);self.assertEqual(clone['generation_tasks'][0]['request_id'],binding['id']);self.assertEqual(clone['generation_tasks'][0]['status'],'pending');self.assertIsNone(clone['generation_tasks'][0]['attempt_id'])
 def test_old_options_omit_new_key_and_downgrade_rejected(self):
  task=self.prepare();self.assertNotIn('rule_task_id',task['frozen']['context_options']);self.bind();before=self.state()
  def downgrade(state):state['workspace_version']=35;state.pop('rule_task_bindings');return state,True
  with self.assertRaises(ValueError):self.service.repository.atomic(self.pid,downgrade)
  self.assertEqual(self.state(),before)
 def test_manual_create_identity_cannot_change_content_or_resurrect_deleted_rule(self):
  target=self.bind();req=dict(operation_id=str(uuid4()),rule_id=None,scope='task',scope_id=target,kind='guidance',text='审计规则',enabled=True);rule=self.rules.save(self.pid,req);before=self.state();self.assertEqual(self.rules.save(self.pid,req),rule);self.assertEqual(self.state(),before)
  for bad in (dict(req,text='另一个内容'),dict(req,enabled=1)):
   with self.assertRaises(ValueError):self.rules.save(self.pid,bad)
   self.assertEqual(self.state(),before)
  self.rules.delete(self.pid,dict(rule_id=rule['id']));before=self.state()
  with self.assertRaises(ValueError):self.rules.save(self.pid,req)
  self.assertEqual(self.state(),before);self.assertEqual(len(self.rules.history(self.pid,rule['id'])['history']),2)


if __name__=='__main__':unittest.main()
