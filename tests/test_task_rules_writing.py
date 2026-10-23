"""Real three-protocol loopback wire with task-scoped draft constraints; never paid."""
import json
import unittest
from uuid import uuid4
import test_chapter_writing as fixtures
from novel_writer.application.scoped_rules import RuleCoordinator
from novel_writer.application.tasks import TaskCoordinator
from novel_writer.application.task_protocol import AdapterRegistry
from novel_writer.application.chapter_writing import ChapterWriting
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository


class TaskRulesWritingTests(unittest.TestCase):
 setUp=fixtures.ChapterWritingTests.setUp
 action=fixtures.ChapterWritingTests.action
 connection=fixtures.ChapterWritingTests.connection
 options=fixtures.ChapterWritingTests.options
 run_task=fixtures.ChapterWritingTests.run_task
 adoption=fixtures.ChapterWritingTests.adoption
 def bound(self):
  rules=RuleCoordinator(self.service);target=str(uuid4());rules.bind_task(self.pid,dict(request_id=target,chapter_id=self.cid,task_type='draft_chapter'));return rules,target
 def rule(self,rules,target,kind,text):return rules.save(self.pid,dict(operation_id=str(uuid4()),rule_id=None,scope='task',scope_id=target,kind=kind,text=text,enabled=True))
 def prepare(self,connection,target):
  options=self.options(context_options=dict(chapter_id=self.cid,budget_chars=20000,rule_task_id=target));preview=self.writing.preview(self.pid,options)
  profile=dict(adapter_id='configured-http-v2',connection_id=connection['id'],model_id=connection['model_id'],temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=True,prompt_version='rewrite-1')
  return self.writing.prepare(self.pid,dict(request_id=target,source_options=options,source_sha256=preview['source_sha256'],model_options=profile,max_output_chars=2000,timeout_ms=2000,retry_of=None))
 def test_three_protocols_task_constraints_and_metrics_are_real_frozen_inputs(self):
  for protocol in ('openai-chat','anthropic-messages','gemini-content'):
   with self.subTest(protocol=protocol),fixtures.supplier(protocol,output='门前的灯塔亮起。') as wire:
    rules,target=self.bound();self.rule(rules,target,'required','灯塔');self.rule(rules,target,'forbidden','任务禁词');self.rule(rules,target,'guidance','本次采用限知视角')
    _,other=self.bound();self.rule(rules,other,'guidance','不该泄入的另一个任务')
    prepared=self.prepare(self.connection(wire,protocol=protocol),target);spec=prepared['task']['frozen']['parameters']['writing'];self.assertIn('灯塔',spec['required_literals']);self.assertIn('任务禁词',spec['forbidden_literals']);self.assertNotIn('本次采用限知视角',spec['required_literals']);self.assertNotIn('不该泄入的另一个任务',prepared['task']['frozen']['context_text']);self.assertEqual(wire['calls'],[])
    self.rule(rules,other,'guidance','冻结后另一任务变化也不影响本次')
    done=self.run_task(prepared);self.assertEqual(done['task']['status'],'succeeded');self.assertEqual(len(wire['calls']),1);actual=json.dumps(wire['calls'][0]['body'],ensure_ascii=False);self.assertIn('灯塔',actual);self.assertIn('任务禁词',actual);self.assertIn('本次采用限知视角',actual);self.assertNotIn('不该泄入的另一个任务',actual);self.assertNotIn('冻结后另一任务变化',actual);self.assertEqual(done['writing']['metrics']['missing_required'],[]);self.assertEqual(done['writing']['metrics']['forbidden_found'],[]);self.assertEqual(self.service.get(self.pid)['document']['chapters'][0]['content'],'')
 def test_rule_disable_reenable_blocks_actual_wire_and_new_rule_blocks_adoption(self):
  with fixtures.supplier(output='门前的灯塔亮起。') as wire:
   rules,target=self.bound();rule=self.rule(rules,target,'required','灯塔');prepared=self.prepare(self.connection(wire),target);rules.set_enabled(self.pid,dict(rule_id=rule['id'],enabled=False));rules.set_enabled(self.pid,dict(rule_id=rule['id'],enabled=True))
   with self.assertRaises(ValueError):self.run_task(prepared)
   self.assertEqual(wire['calls'],[])
   rules,new=self.bound();self.rule(rules,new,'required','灯塔');done=self.run_task(self.prepare(self.connection(wire),new));self.assertEqual(done['task']['status'],'succeeded');request=self.adoption(done);self.rule(rules,new,'guidance','采用前新增规则');request['expected_revision']=self.service.get(self.pid)['revision'];before=self.service.get(self.pid)
   with self.assertRaises(ValueError):self.engine.adopt(self.pid,done['task']['id'],request)
   self.assertEqual(self.service.get(self.pid),before);self.assertEqual(len(wire['calls']),1)
 def test_v36_model_pending_copy_maps_binding_but_never_inherits_send_permission(self):
  from novel_writer.application.backups import create_backup,restore_backup
  from novel_writer.application.migrations import migrate
  from novel_writer.application.skill_import import SkillLibrary
  with fixtures.supplier(output='门前灯塔。') as wire:
   rules,target=self.bound();rule=self.rule(rules,target,'required','灯塔');prepared=self.prepare(self.connection(wire),target);SkillLibrary(self.db);package=self.root/'pending.nwbak';create_backup(self.db,package);restored=restore_backup(package,self.root/'restored');self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid),self.service.get(self.pid))
   clone_db=self.root/'copied.sqlite3';SQLiteRepository(clone_db);SkillLibrary(clone_db);copied=migrate(package,clone_db,operation_id=str(uuid4()));service=NovelService(SQLiteRepository(clone_db));project=copied['projects'][0]['new_id'];state=service.get(project);task=state['generation_tasks'][0];self.assertEqual(state['scoped_rules'][0]['scope_id'],state['rule_task_bindings'][0]['id']);self.assertNotEqual(task['request_id'],target)
   registry=AdapterRegistry();registry.register('draft_chapter',self.adapter);engine=TaskCoordinator(service,registry);self.addCleanup(engine.close);ChapterWriting(engine,self.providers)
   with self.assertRaises(ValueError):engine.start(project,task['id'],dict(confirm_external=True,request_sha256=task['frozen']['parameters']['binding']['request_sha256']))
   self.assertEqual(wire['calls'],[]);self.assertNotEqual(task['frozen']['parameters']['writing']['prepared_owner'],engine.owner_id)


if __name__=='__main__':unittest.main()
