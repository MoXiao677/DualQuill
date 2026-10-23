"""C13 source identity replacement regression; fictional random loopback only."""
from copy import deepcopy
from hashlib import sha256
import json,unittest
from uuid import uuid4,uuid5,NAMESPACE_URL
import test_rule_semantic_reviews as semantic
import test_chapter_writing as fixtures
from novel_writer.application.rule_reviews import RuleReviewCoordinator,source,fresh
from novel_writer.application.scoped_rules import RuleCoordinator
from novel_writer.domain.rule_reviews import source_digest,RuleReviewTask
from novel_writer.domain.tasks import parse

class RuleReviewSourceIdentityTests(unittest.TestCase):
 setUp=semantic.RuleSemanticReviewTests.setUp
 action=semantic.RuleSemanticReviewTests.action
 connection=semantic.RuleSemanticReviewTests.connection
 prepare_review=semantic.RuleSemanticReviewTests.prepare_review
 run_review=semantic.RuleSemanticReviewTests.run_review
 def setup_identity(self):
  self.rules=RuleCoordinator(self.service);self.review=RuleReviewCoordinator(self.engine,self.providers,enabled=True)
  operations=[str(uuid5(NAMESPACE_URL,'c13-source-identity/'+str(i))) for i in range(20)]
  operations.sort(key=lambda op:str(uuid5(NAMESPACE_URL,op+'/rule')))
  self.old_operation,self.new_operation,self.other_operation=operations[0],operations[1],operations[-1]
  self.first=self.save_rule(self.old_operation,'身份不变的虚构guidance原文🙂')
  self.other=self.save_rule(self.other_operation,'第二条虚构guidance规则')
  return self.review.preview(self.pid,dict(chapter_id=self.cid,target_task_id=None))
 def save_rule(self,operation,text):
  return self.rules.save(self.pid,dict(operation_id=operation,rule_id=None,scope='book',scope_id=self.pid,kind='guidance',text=text,enabled=True))
 def replace_first(self):
  archived=self.rules.archive(self.pid,dict(rule_id=self.first['id'],archived=True));self.assertEqual(archived['version'],2)
  replacement=self.save_rule(self.new_operation,self.first['text']);self.assertEqual(replacement['version'],1);self.assertNotEqual(replacement['id'],self.first['id']);return replacement
 def test_prepared_request_rejects_archived_same_text_new_identity_before_wire(self):
  preview=self.setup_identity()
  with fixtures.supplier(output=semantic.opinion(preview['rules'])) as wire:
   view,_=self.prepare_review(self.connection(wire));task=parse(RuleReviewTask,view['task']);replacement=self.replace_first();current=source(self.service.get(self.pid),self.cid,None)
   self.assertEqual([r['id'] for r in current['rules']],[replacement['id'],self.other['id']]);before=self.service.get(self.pid)
   try:
    with self.assertRaisesRegex(ValueError,'source_changed'):self.review.start(self.pid,task.id,dict(confirm_external=True,request_sha256=task.binding.request_sha256))
   finally:self.engine.wait_idle(5)
   self.assertEqual(wire['calls'],[]);self.assertFalse(fresh(before,task));self.assertNotEqual(current['source_sha256'],task.source_sha256);self.assertEqual(self.service.get(self.pid),before)
   print(json.dumps(dict(probe='prepared_archive_and_same_text_new_v1_rule',old_ids=[r['id'] for r in task.rules],new_ids=[r['id'] for r in current['rules']],old_sha256=task.source_sha256,new_sha256=current['source_sha256'],actual_fresh=fresh(before,task),loopback_calls=len(wire['calls'])),ensure_ascii=False))
 def test_successful_opinion_rejects_same_text_replacement_on_inspect(self):
  preview=self.setup_identity()
  with fixtures.supplier(output=semantic.opinion(preview['rules'])) as wire:
   prepared,_=self.prepare_review(self.connection(wire));done=self.run_review(prepared);self.assertEqual(done['status'],'succeeded');result=done['results'][0];self.replace_first();before=self.service.get(self.pid)
   with self.assertRaisesRegex(ValueError,'stale_or_failed_opinion'):self.review.inspect(self.pid,done['task']['id'],dict(result_id=result['id'],request_sha256=done['task']['binding']['request_sha256'],expected_revision=before['revision']))
   self.assertEqual(self.service.get(self.pid),before);self.assertFalse(self.review.describe(self.pid,done['task']['id'])['can_inspect']);self.assertEqual(len(wire['calls']),1)
 def test_exact_restore_disk_reopen_and_double_copy_keep_original_wire_sha_and_citations(self):
  from novel_writer.application.backups import create_backup,restore_backup
  from novel_writer.application.migrations import migrate
  from novel_writer.application.skill_import import SkillLibrary
  from novel_writer.application.service import NovelService
  from novel_writer.storage.sqlite_repository import SQLiteRepository
  from novel_writer.application.tasks import TaskCoordinator
  from novel_writer.application.task_protocol import AdapterRegistry
  preview=self.setup_identity()
  with fixtures.supplier(output=semantic.opinion(preview['rules'])) as wire:
   connection=self.connection(wire);prepared,_=self.prepare_review(connection);done=self.run_review(prepared);self.assertEqual(done['status'],'succeeded');self.prepare_review(connection);original=self.service.get(self.pid);original_task=done['task'];original_result=done['results'][0]
   reopened=NovelService(SQLiteRepository(self.db));engine=TaskCoordinator(reopened,AdapterRegistry());self.addCleanup(engine.close);coordinator=RuleReviewCoordinator(engine,self.providers,enabled=True);self.assertEqual(reopened.get(self.pid),original);self.assertEqual(coordinator.describe(self.pid)['tasks'][1]['display_status'],'interrupted')
   SkillLibrary(self.db);package=self.root/'identity.nwbak';create_backup(self.db,package);restored=restore_backup(package,self.root/'exact-restore');self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid),original)
   for index in range(2):
    database=self.root/('identity-copy-'+str(index)+'.sqlite3');SQLiteRepository(database);SkillLibrary(database);copied=migrate(package,database,operation_id=str(uuid4()));project=copied['projects'][0]['new_id'];service=NovelService(SQLiteRepository(database));engine=TaskCoordinator(service,AdapterRegistry());self.addCleanup(engine.close);review=RuleReviewCoordinator(engine,self.providers,enabled=True);succeeded,pending=review.describe(project)['tasks'];task=succeeded['task'];result=succeeded['results'][0]
    self.assertTrue(succeeded['source_fresh']);self.assertEqual(task['wire_source'],original_task['wire_source']);self.assertEqual(task['binding']['request_body'],original_task['binding']['request_body']);self.assertEqual(task['binding']['request_sha256'],original_task['binding']['request_sha256']);self.assertEqual(result['response'],original_result['response']);self.assertEqual(result['output'],original_result['output']);self.assertEqual(len(task['copy_mappings']),index+1);self.assertEqual(task['copy_mappings'][-1]['after'],{k:task[k] for k in ('project_id','chapter_id','target_task_id','rules')});self.assertNotEqual(task['source_sha256'],original_task['source_sha256']);self.assertEqual(task['source_sha256'],source_digest(project,task['chapter_id'],task['target_task_id'],task['rules']));self.assertEqual(pending['display_status'],'interrupted')
    before=service.get(project);inspection=review.inspect(project,task['id'],dict(result_id=result['id'],request_sha256=task['binding']['request_sha256'],expected_revision=before['revision']));self.assertEqual(inspection['status'],'needs_verification');self.assertFalse(inspection['formal_modification_permission']);self.assertEqual(service.get(project),before)
    with self.assertRaisesRegex(ValueError,'fresh_preparation_required'):review.start(project,pending['task']['id'],dict(confirm_external=True,request_sha256=pending['task']['binding']['request_sha256']))
    if index==0:package=self.root/'identity-copy-0.nwbak';create_backup(database,package)
    else:
     rules=RuleCoordinator(service);old=next(r for r in task['rules'] if r['text']==self.first['text']);rules.archive(project,dict(rule_id=old['id'],archived=True));rules.save(project,dict(operation_id=str(uuid4()),rule_id=None,scope='book',scope_id=project,kind=old['kind'],text=old['text'],enabled=True));before=service.get(project)
     with self.assertRaisesRegex(ValueError,'stale_or_failed_opinion'):review.inspect(project,task['id'],dict(result_id=result['id'],request_sha256=task['binding']['request_sha256'],expected_revision=before['revision']))
     self.assertEqual(service.get(project),before)
   self.assertEqual(len(wire['calls']),1)
 def test_digest_binds_exact_rule_identity_version_source_and_order_is_stable(self):
  preview=self.setup_identity();rules=preview['rules'];payload=dict(project_id=self.pid,chapter_id=self.cid,target_task_id=None,rules=sorted(rules,key=lambda r:r['id']));expected=sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')).hexdigest()
  self.assertEqual(source_digest(self.pid,self.cid,None,rules),expected);self.assertEqual(source_digest(self.pid,self.cid,None,list(reversed(rules))),expected)
  for key,value in (('id',str(uuid5(NAMESPACE_URL,'other-id'))),('version',2),('source','import'),('created_at','2000-01-01T00:00:00+00:00'),('updated_at','2000-01-01T00:00:00+00:00')):
   changed=deepcopy(rules);changed[0][key]=value
   with self.subTest(field=key):self.assertNotEqual(source_digest(self.pid,self.cid,None,changed),expected)

if __name__=='__main__':unittest.main()
