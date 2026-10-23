"""Explicit single-task rules for IDEA/outline and scene/selection engines."""
from copy import deepcopy
import json,unittest
from uuid import uuid4
import test_chapter_planning as planning
import test_scene_expansion as expansion
from test_book_ai import supplier
from novel_writer.application.scoped_rules import RuleCoordinator

def reserve(case,capability):
 rules=RuleCoordinator(case.service);identity=str(uuid4());rules.bind_task(case.pid,dict(request_id=identity,chapter_id=case.cid,task_type=capability));return rules,identity
def add(case,rules,target,text='仅此任务采用近距离视角🙂',scope='task'):
 return rules.save(case.pid,dict(operation_id=str(uuid4()),rule_id=None,scope=scope,scope_id=target,kind='guidance',text=text,enabled=True))

class PlanningTaskRuleTests(unittest.TestCase):
 setUp=planning.ChapterPlanningTests.setUp
 action=planning.ChapterPlanningTests.action
 connection=planning.ChapterPlanningTests.connection
 options=planning.ChapterPlanningTests.options
 source=planning.ChapterPlanningTests.source
 prepare=planning.ChapterPlanningTests.prepare
 execute=planning.ChapterPlanningTests.execute
 review=planning.ChapterPlanningTests.review
 accept=planning.ChapterPlanningTests.accept
 def test_idea_outline_rule_identity_context_and_isolation(self):
  for mode,capability in (('brainstorm','brainstorm_chapter'),('outline','outline_chapter')):
   with self.subTest(mode=mode):
    rules,target=reserve(self,capability);add(self,rules,target);source=self.source(mode,rule_task_id=target);preview=self.planning.preview(self.pid,source);self.assertIn('仅此任务',preview['context_text']);self.assertNotIn('仅此任务',self.planning.preview(self.pid,self.source(mode))['context_text'])
    plan=self.service.get(self.pid)['document']['chapter_outlines'][0];output={'idea':'只写本章的观察。'} if mode=='brainstorm' else {k:deepcopy(plan[k]) for k in ('core_idea','objective','character_ids','scenes','story_time')}
    with supplier(output=json.dumps(output,ensure_ascii=False)) as wire:
     c=self.connection(wire);before=self.service.get(self.pid)
     with self.assertRaises(ValueError):self.prepare(c,mode,source,operation_id=str(uuid4()))
     self.assertEqual(self.service.get(self.pid),before)
     with self.assertRaises(ValueError):self.prepare(c,mode,self.source(mode),operation_id=target)
     task=self.prepare(c,mode,source,operation_id=target);self.assertEqual(task['task']['request_id'],target);self.assertIn('rule_sources',task['task']['source_guard']);done=self.execute(task);self.assertEqual(done['status'],'succeeded',done);self.assertEqual(len(wire['calls']),1)
 def test_rule_addition_stales_send_and_rule_disable_stales_adoption(self):
  rules,target=reserve(self,'brainstorm_chapter');rule=add(self,rules,target);source=self.source(rule_task_id=target)
  with supplier(output=json.dumps({'idea':'待人工采纳的构思'})) as wire:
   c=self.connection(wire);task=self.prepare(c,source=source,operation_id=target);add(self,rules,self.pid,'新增本书约束',scope='book')
   with self.assertRaises(ValueError):self.execute(task)
   self.assertEqual(wire['calls'],[]);rules,target=reserve(self,'brainstorm_chapter');add(self,rules,target);source=self.source(rule_task_id=target);done=self.execute(self.prepare(c,source=source,operation_id=target));review=self.review(done);rules.set_enabled(self.pid,dict(rule_id=rule['id'],enabled=False))
   # The first binding is unrelated; modifying it does not stale this task.
   self.assertTrue(self.planning.describe(self.pid,done['task']['id'])['source_fresh']);add(self,rules,target,'新增本次规则');before=self.service.get(self.pid)
   with self.assertRaises(ValueError):self.accept(done,review)
   self.assertEqual(self.service.get(self.pid),before)
 def test_wrong_capability_old_encoding_and_copy_binding(self):
  from novel_writer.application.backups import create_backup
  from novel_writer.application.migrations import migrate
  from novel_writer.application.skill_import import SkillLibrary
  from novel_writer.application.service import NovelService
  from novel_writer.storage.sqlite_repository import SQLiteRepository
  rules,wrong=reserve(self,'expand_scene_selection')
  with self.assertRaises(ValueError):self.planning.preview(self.pid,self.source(rule_task_id=wrong))
  self.assertNotIn('rule_sources',self.planning.preview(self.pid,self.source())['guard']);rules,target=reserve(self,'brainstorm_chapter');add(self,rules,target)
  with supplier() as wire:
   task=self.prepare(self.connection(wire),source=self.source(rule_task_id=target),operation_id=target);SkillLibrary(self.db);package=self.root/'bound.nwbak';create_backup(self.db,package);db=self.root/'copy.sqlite3';SQLiteRepository(db);SkillLibrary(db);copied=migrate(package,db,operation_id=str(uuid4()));clone=NovelService(SQLiteRepository(db)).get(copied['projects'][0]['new_id']);bound=next(b for b in clone['rule_task_bindings'] if b['task_type']=='brainstorm_chapter');mapped=clone['chapter_planning_tasks'][0];self.assertEqual(mapped['request_id'],bound['id']);self.assertEqual(mapped['source_options']['rule_task_id'],bound['id']);self.assertEqual(mapped['source_guard']['rule_sources'][0]['scope_id'],bound['id']);self.assertEqual(wire['calls'],[])

class ExpansionTaskRuleTests(unittest.TestCase):
 setUp=expansion.SceneExpansionTests.setUp
 action=expansion.SceneExpansionTests.action
 connection=expansion.SceneExpansionTests.connection
 options=expansion.SceneExpansionTests.options
 source=expansion.SceneExpansionTests.source
 prepare=expansion.SceneExpansionTests.prepare
 execute=expansion.SceneExpansionTests.execute
 review=expansion.SceneExpansionTests.review
 accept=expansion.SceneExpansionTests.accept
 def test_scene_and_selection_freeze_only_the_reserved_task(self):
  for kind in ('scene','selection'):
   with self.subTest(kind=kind),supplier(output='本次扩写仍需作者确认。') as wire:
    rules,target=reserve(self,'expand_scene_selection');add(self,rules,target);source=self.source(kind,rule_task_id=target,**(dict(selection_start=0,selection_end=2) if kind=='selection' else {}));preview=self.engine.preview(self.pid,source);self.assertIn('仅此任务',preview['context_text']);self.assertNotIn('仅此任务',self.engine.preview(self.pid,self.source())['context_text']);c=self.connection(wire)
    with self.assertRaises(ValueError):self.prepare(c,source=source)
    with self.assertRaises(ValueError):self.prepare(c,operation_id=target)
    task=self.prepare(c,source,operation_id=target);done=self.execute(task);self.assertEqual(done['status'],'succeeded',done);self.assertEqual(len(wire['calls']),1);self.assertEqual(self.service.get(self.pid)['document']['chapters'][0]['content'],self.original)
 def test_added_task_rules_block_send_and_use(self):
  rules,target=reserve(self,'expand_scene_selection');rule=add(self,rules,target)
  with supplier(output='有效但未采纳的扩写。') as wire:
   c=self.connection(wire);task=self.prepare(c,self.source(rule_task_id=target),operation_id=target);add(self,rules,self.pid,'新增本书要求',scope='book')
   with self.assertRaises(ValueError):self.execute(task)
   self.assertEqual(wire['calls'],[]);rules,target=reserve(self,'expand_scene_selection');rule=add(self,rules,target);done=self.execute(self.prepare(c,self.source(rule_task_id=target),operation_id=target));review=self.review(done);rules.set_enabled(self.pid,dict(rule_id=rule['id'],enabled=False));before=self.service.get(self.pid)
   with self.assertRaises(ValueError):self.accept(done,review)
   self.assertEqual(self.service.get(self.pid),before)
 def test_wrong_capability_exact_conflict_and_old_encoding(self):
  rules,target=reserve(self,'outline_chapter')
  with self.assertRaises(ValueError):self.engine.preview(self.pid,self.source(rule_task_id=target))
  self.assertNotIn('rule_sources',self.engine.preview(self.pid,self.source())['guard']);rules,target=reserve(self,'expand_scene_selection')
  for kind in ('required','forbidden'):rules.save(self.pid,dict(operation_id=str(uuid4()),rule_id=None,scope='task',scope_id=target,kind=kind,text='同一精确文本',enabled=True))
  with self.assertRaises(ValueError):self.engine.preview(self.pid,self.source(rule_task_id=target))

if __name__=='__main__':unittest.main()
