"""Pending directed tests: fictional loopback proves controls, never semantic quality."""
import json
import unittest
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
import test_chapter_writing as fixtures
from novel_writer.application.materials import Materials
from novel_writer.application.semantic_retrieval import SemanticRetrievalCoordinator
from novel_writer.application.retrieval import search
from novel_writer.application.task_protocol import AdapterRegistry
from novel_writer.application.tasks import TaskCoordinator
from novel_writer.domain.semantic_retrieval import validate_source,verify_output


class SemanticRetrievalTests(unittest.TestCase):
 action=fixtures.ChapterWritingTests.action
 connection=fixtures.ChapterWritingTests.connection

 def setUp(self):
  fixtures.ChapterWritingTests.setUp(self)
  self.materials=Materials(self.service)
  self.semantic=SemanticRetrievalCoordinator(self.engine,self.providers,enabled=True)
  self.corpus=json.loads((Path(__file__).parent/'fixtures'/'semantic-retrieval-v1.json').read_text(encoding='utf-8'))['cases']
  self.mid=self.material(self.corpus[0]['text'])

 def revision(self):return self.service.get(self.pid)['revision']
 def operation(self):return dict(operation_id=str(uuid4()),expected_revision=self.revision())
 def material(self,text,index=True):
  result=self.materials.create(self.pid,dict(self.operation(),title='虚构资料',format='txt',tags=[],text=text))
  identifier=result['material']['id']
  if index:self.materials.rebuild(self.pid,identifier,self.operation())
  return identifier
 def options(self,**changes):
  value=dict(chapter_id=self.cid,query='饥饿',material_ids=[self.mid],offset=0,candidate_limit=16,character_budget=16000);value.update(changes);return value
 def prepare(self,connection,options=None,**changes):
  options=options or self.options();preview=self.semantic.preview(self.pid,options)
  request=dict(request_id=str(uuid4()),source_options=options,source_sha256=preview['source_sha256'],model_options=dict(adapter_id='configured-http-v2',connection_id=connection['id'],model_id=connection['model_id'],temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=True,prompt_version='semantic-retrieval-json-1'),max_output_chars=20000,timeout_ms=2000,budget_max_calls=10,budget_max_output_tokens=8192)
  request.update(changes);return self.semantic.prepare(self.pid,request)
 def permit(self,prepared):return dict(confirm_external=True,request_sha256=prepared['task']['binding']['request_sha256'])
 def run_task(self,prepared):
  self.semantic.start(self.pid,prepared['task']['id'],self.permit(prepared));self.engine.wait_idle(5)
  result=self.semantic.describe(self.pid,prepared['task']['id']);self.assertNotEqual(result['status'],'running');return result
 def output(self,hits=None):return json.dumps(dict(overview='虚构供应商返回的待核实相关意见',hits=[] if hits is None else hits),ensure_ascii=False)
 def hit(self,text=None,**changes):
  text=text or self.corpus[0]['text'];value=dict(window_id='w000000',start=0,end=len(text),quote=text,reason='人工预置的相关性意见，不能验证真实语义质量');value.update(changes);return value
 def inspect(self,done):
  return self.semantic.inspect(self.pid,done['task']['id'],dict(result_id=done['results'][0]['id'],request_sha256=done['task']['binding']['request_sha256'],expected_revision=self.revision()))

 def test_01_zero_overlap_candidate_eligible_default_lexical_zero_calls(self):
  with fixtures.supplier(output=self.output([self.hit()])) as wire:
   before=deepcopy(self.service.get(self.pid));options=self.options();preview=self.semantic.preview(self.pid,options)
   self.assertFalse(set(options['query'])&set(preview['windows'][0]['text']))
   for mode in ('literal','hybrid'):
    result=search(before,dict(query=options['query'],chapter_id=self.cid,scopes=['materials'],material_ids=[self.mid],mode=mode));self.assertEqual(result['hits'],[])
   self.assertEqual(self.service.get(self.pid),before);self.assertEqual(wire['calls'],[])
   prepared=self.prepare(self.connection(wire));self.assertEqual(wire['calls'],[])
   done=self.run_task(prepared);self.assertEqual(done['status'],'succeeded');self.assertFalse(done['semantic_quality_verified']);self.assertEqual(len(wire['calls']),1)
   inspected=self.inspect(done);self.assertEqual(inspected['hits'][0]['snippet'],self.corpus[0]['text']);self.assertEqual(self.service.get(self.pid)['document'],before['document'])

 def test_02_empty_hits_preserve_raw_and_honest_scope(self):
  with fixtures.supplier(output=self.output()) as wire:
   done=self.run_task(self.prepare(self.connection(wire)));self.assertEqual(done['status'],'succeeded');self.assertEqual(done['results'][0]['output']['hits'],[])
   self.assertIn('choices',done['results'][0]['response']['raw_response']);result=self.inspect(done);self.assertEqual(result['hits'],[]);self.assertFalse(result['automatic_context_inclusion']);self.assertFalse(result['semantic_quality_verified']);self.assertEqual(len(wire['calls']),1)

 def test_03_invalid_ids_spans_quotes_and_json_preserve_raw_fail_closed(self):
  malformed=[self.output([self.hit(window_id='unknown')]),self.output([self.hit(start=True)]),self.output([self.hit(quote='虚构不同引文')]),self.output([self.hit(),self.hit()]),'{"overview":"x","hits":[],"extra":NaN}']
  for output in malformed:
   with self.subTest(output=output),fixtures.supplier(output=output) as wire:
    done=self.run_task(self.prepare(self.connection(wire)));self.assertEqual(done['status'],'failed');self.assertEqual(len(done['results']),1);self.assertIsNone(done['results'][0]['output']);self.assertEqual(done['results'][0]['response']['output_text'],output)
    with self.assertRaises(ValueError):self.inspect(done)
    self.assertEqual(len(wire['calls']),1)

 def test_04_explicit_page_coverage_and_budgets_never_claim_omitted_windows(self):
  identifier=self.material('没有查询字面重合的石桥。'*180)
  first=self.semantic.preview(self.pid,self.options(material_ids=[identifier],candidate_limit=1,character_budget=800));second=self.semantic.preview(self.pid,self.options(material_ids=[identifier],offset=1,candidate_limit=1,character_budget=800))
  self.assertGreater(first['coverage']['total_windows'],1);self.assertFalse(first['coverage']['complete']);self.assertFalse(first['coverage']['lexical_prefilter']);self.assertEqual(first['coverage']['included_characters'],800);self.assertEqual(second['windows'][0]['window_id'],'w000001');self.assertNotEqual(first['windows'][0]['start'],second['windows'][0]['start'])
  for changes in (dict(candidate_limit=33),dict(offset=True),dict(character_budget=799),dict(material_ids=[]),dict(offset=first['coverage']['total_windows']),dict(material_ids=[identifier],candidate_limit=32,character_budget=800)):
   with self.subTest(changes=changes),self.assertRaises(ValueError):self.semantic.preview(self.pid,self.options(**changes))
  payload={key:first[key] for key in ('project_id','chapter_id','source_options','windows','coverage')};payload['coverage']['lexical_prefilter']=0
  with self.assertRaises(ValueError):validate_source(payload)

 def test_05_three_protocols_use_frozen_wire_and_independent_confirmation(self):
  for protocol in ('openai-chat','anthropic-messages','gemini-content'):
   with self.subTest(protocol=protocol),fixtures.supplier(protocol,output=self.output([self.hit()])) as wire:
    prepared=self.prepare(self.connection(wire,protocol=protocol));task=prepared['task']
    with self.assertRaises(ValueError):self.semantic.start(self.pid,task['id'],dict(confirm_external=False,request_sha256=task['binding']['request_sha256']))
    self.assertEqual(wire['calls'],[]);done=self.run_task(prepared);self.assertEqual(done['status'],'succeeded');self.assertEqual(len(wire['calls']),1);self.assertEqual(wire['calls'][0]['body'],json.loads(task['binding']['request_body']))
    self.assertFalse(done['formal_modification_permission']);self.assertFalse(done['automatic_context_inclusion'])
    with self.assertRaises(ValueError):self.semantic.start(self.pid,task['id'],self.permit(prepared))
    self.assertEqual(len(wire['calls']),1)

 def test_06_pending_cancel_never_sends_or_changes_formal_document(self):
  with fixtures.supplier(output=self.output()) as wire:
   before=deepcopy(self.service.get(self.pid)['document']);prepared=self.prepare(self.connection(wire));self.assertTrue(self.semantic.cancel(self.pid,prepared['task']['id'])['accepted'])
   self.assertEqual(self.semantic.describe(self.pid,prepared['task']['id'])['status'],'cancelled')
   with self.assertRaises(ValueError):self.semantic.start(self.pid,prepared['task']['id'],self.permit(prepared))
   self.assertEqual(wire['calls'],[]);self.assertEqual(self.service.get(self.pid)['document'],before)

 def test_07_stale_archive_missing_index_and_cross_book_block(self):
  with fixtures.supplier(output=self.output([self.hit()])) as wire:
   connection=self.connection(wire);pending=self.prepare(connection);done=self.run_task(self.prepare(connection));self.inspect(done)
   self.materials.update(self.pid,self.mid,dict(self.operation(),title='改版资料',format='txt',tags=[],text='新版本只有桥梁。'))
   with self.assertRaises(ValueError):self.semantic.start(self.pid,pending['task']['id'],self.permit(pending))
   with self.assertRaises(ValueError):self.inspect(done)
   with self.assertRaises(ValueError):self.semantic.preview(self.pid,self.options())
   self.materials.rebuild(self.pid,self.mid,self.operation());archived=self.prepare(connection);self.materials.archive(self.pid,self.mid,self.operation())
   with self.assertRaises(ValueError):self.semantic.start(self.pid,archived['task']['id'],self.permit(archived))
   missing=self.material('没有建立索引',index=False)
   with self.assertRaises(ValueError):self.semantic.preview(self.pid,self.options(material_ids=[missing]))
   other=self.service.create(title='另一虚构书');other_id=other['document']['project']['id']
   with self.assertRaises((ValueError,KeyError)):self.semantic.preview(other_id,self.options())
   with self.assertRaises((ValueError,KeyError)):self.semantic.describe(other_id,pending['task']['id'])
   self.assertEqual(len(wire['calls']),1)

 def test_08_unknown_cost_disabled_offline_missing_adapter_and_reopen_no_send(self):
  with fixtures.supplier(output=self.output()) as wire:
   connection=self.connection(wire);prepared=self.prepare(connection);task_id=prepared['task']['id']
   for field in ('enabled','offline'):
    target=self.semantic.adapter if field=='enabled' else self.providers;old=getattr(target,field);setattr(target,field,False if field=='enabled' else True)
    try:
     with self.assertRaises(ValueError):self.semantic.start(self.pid,task_id,self.permit(prepared))
    finally:setattr(target,field,old)
   profile=deepcopy(prepared['task']['binding']);profile={k:profile[k] for k in ('adapter_id','connection_id','model_id','temperature','max_tokens','budget_limit','allow_unknown_cost','prompt_version')};profile['allow_unknown_cost']=False
   try:unknown=self.prepare(connection,model_options=profile)
   except ValueError:unknown=None
   if unknown:
    with self.assertRaises(ValueError):self.semantic.start(self.pid,unknown['task']['id'],self.permit(unknown))
   new_engine=TaskCoordinator(self.service,AdapterRegistry());self.addCleanup(new_engine.close);reopened=SemanticRetrievalCoordinator(new_engine,self.providers,enabled=True)
   self.assertEqual(reopened.describe(self.pid,task_id)['display_status'],'interrupted')
   with self.assertRaises(ValueError):reopened.start(self.pid,task_id,self.permit(prepared))
   self.engine.registry._adapters.pop(('semantic_retrieval','configured-http-v2'))
   done=self.run_task(prepared);self.assertEqual(done['status'],'failed');self.assertEqual(wire['calls'],[])

 def test_09_restore_and_double_copy_keep_raw_wire_map_typed_sources_and_revoke_owner(self):
  from novel_writer.application.backups import create_backup,restore_backup
  from novel_writer.application.migrations import migrate
  from novel_writer.application.skill_import import SkillLibrary
  from novel_writer.application.service import NovelService
  from novel_writer.storage.sqlite_repository import SQLiteRepository
  with fixtures.supplier(output=self.output([self.hit()])) as wire:
   connection=self.connection(wire);done=self.run_task(self.prepare(connection));pending=self.prepare(connection);original=self.service.get(self.pid);SkillLibrary(self.db);archive=self.root/'semantic.nwbak';create_backup(self.db,archive)
   restored=restore_backup(archive,self.root/'semantic-restored');self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid),original)
   for number in (1,2):
    target=self.root/('semantic-copy-'+str(number)+'.sqlite3');SQLiteRepository(target);SkillLibrary(target);copied=migrate(archive,target,operation_id=str(uuid4()));project=copied['projects'][0]['new_id'];service=NovelService(SQLiteRepository(target));state=service.get(project);engine=TaskCoordinator(service,AdapterRegistry());self.addCleanup(engine.close);coordinator=SemanticRetrievalCoordinator(engine,self.providers,enabled=True)
    finished=state['semantic_retrieval_tasks'][0];old=done['task'];self.assertEqual(finished['binding']['request_body'],old['binding']['request_body']);self.assertEqual(finished['wire_source'],old['wire_source']);self.assertEqual(state['semantic_retrieval_results'][0]['response'],done['results'][0]['response']);self.assertEqual(len(finished['copy_mappings']),number);self.assertNotEqual(finished['owner_id'],old['owner_id']);self.assertEqual(finished['source_options']['material_ids'],[state['materials'][0]['id']]);self.assertEqual(finished['windows'][0]['selection']['project_id'],project)
    result=coordinator.inspect(project,finished['id'],dict(result_id=state['semantic_retrieval_results'][0]['id'],request_sha256=finished['binding']['request_sha256'],expected_revision=state['revision']));self.assertEqual(result['hits'][0]['selection']['entity_id'],state['materials'][0]['id'])
    copied_pending=state['semantic_retrieval_tasks'][1]
    with self.assertRaises(ValueError):coordinator.start(project,copied_pending['id'],dict(confirm_external=True,request_sha256=copied_pending['binding']['request_sha256']))
    archive=self.root/('semantic-copy-'+str(number)+'.nwbak');create_backup(target,archive)
   self.assertEqual(len(wire['calls']),1)

 def test_10_unicode_corpus_and_source_instructions_only_validate_structure(self):
  case=self.corpus[-1];mid=self.material(case['text']);preview=self.semantic.preview(self.pid,self.options(query=case['query'],material_ids=[mid]));start=case['text'].index(case['expected_quote']);hit=self.hit(case['text'],start=start,end=start+len(case['expected_quote']),quote=case['expected_quote']);self.assertEqual(start,1)
  self.assertEqual(verify_output(self.output([hit]),preview['windows'])['hits'][0]['quote'],case['expected_quote'])
  instruction=self.corpus[-2];self.assertFalse(instruction['relevant']);pool=self.semantic.preview(self.pid,self.options(material_ids=[self.material(instruction['text'])]));self.assertIn(instruction['text'],pool['windows'][0]['text']);self.assertFalse(pool['model_request_sent'])


if __name__=='__main__':unittest.main()
