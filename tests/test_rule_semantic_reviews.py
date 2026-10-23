"""Rule-only model semantic review, real fictional wire and immutable opinion provenance."""
from copy import deepcopy
import json
import unittest
from uuid import uuid4
import test_chapter_writing as fixtures
from novel_writer.application.rule_reviews import RuleReviewCoordinator
from novel_writer.application.scoped_rules import RuleCoordinator
from novel_writer.domain.connections import canonical_messages


def opinion(rules,change=None):
 sides=[dict(rule_id=r['id'],version=r['version'],start=0,end=len(r['text']),quote=r['text']) for r in rules[:2]]
 value=dict(overview='以下均为待核实模型意见',findings=[dict(assessment='model_opinion',category='possible_conflict',statement='叙事视角可能存在不同要求，需作者核实。',evidence=sides)])
 if change:change(value)
 return json.dumps(value,ensure_ascii=False)

class RuleSemanticReviewTests(unittest.TestCase):
 setUp=fixtures.ChapterWritingTests.setUp
 action=fixtures.ChapterWritingTests.action
 connection=fixtures.ChapterWritingTests.connection
 def setup_review(self):
  self.rules=RuleCoordinator(self.service)
  for kind,text in [('required','主角采用第一人称🙂'),('guidance','采用全知视角描述远处事件')]:self.rules.save(self.pid,dict(operation_id=str(uuid4()),rule_id=None,scope='book',scope_id=self.pid,kind=kind,text=text,enabled=True))
  self.review=RuleReviewCoordinator(self.engine,self.providers,enabled=True)
  return self.review.preview(self.pid,dict(chapter_id=self.cid,target_task_id=None))
 def prepare_review(self,connection,preview=None,**changes):
  preview=preview or self.review.preview(self.pid,dict(chapter_id=self.cid,target_task_id=None))
  req=dict(request_id=str(uuid4()),chapter_id=self.cid,target_task_id=preview['target_task_id'],source_sha256=preview['source_sha256'],model_options=dict(adapter_id='configured-http-v2',connection_id=connection['id'],model_id=connection['model_id'],temperature=.3,max_tokens=1024,budget_limit=1.,allow_unknown_cost=True,prompt_version='rewrite-1'),max_output_chars=10000,timeout_ms=2000,budget_max_calls=10,budget_max_output_tokens=81920);req.update(changes)
  return self.review.prepare(self.pid,req),req
 def run_review(self,view):
  task=view['task'];self.review.start(self.pid,task['id'],dict(confirm_external=True,request_sha256=task['binding']['request_sha256']));self.engine.wait_idle(5);return self.review.describe(self.pid,task['id'])
 def test_three_protocol_json_only_rule_sources_are_frozen_and_persistent(self):
  preview=self.setup_review();formal=self.service.get(self.pid)['document']
  for protocol in ('openai-chat','anthropic-messages','gemini-content'):
   with self.subTest(protocol=protocol),fixtures.supplier(protocol,output=opinion(preview['rules'])) as wire:
    view,req=self.prepare_review(self.connection(wire,protocol=protocol));self.assertEqual(wire['calls'],[]);self.assertEqual(view['status'],'pending');self.assertFalse(view['semantic_quality_verified']);self.assertNotIn('content',json.loads(canonical_messages(json.loads(view['task']['binding']['request_body']),protocol)[1]['content']))
    done=self.run_review(view);self.assertEqual(done['status'],'succeeded',done);self.assertEqual(len(wire['calls']),1);self.assertEqual(wire['calls'][0]['body'],json.loads(view['task']['binding']['request_body']));self.assertFalse(done['formal_modification_permission']);self.assertEqual(done['results'][0]['output']['findings'][0]['assessment'],'model_opinion');self.assertEqual(self.service.get(self.pid)['document'],formal)
    result=done['results'][0];inspected=self.review.inspect(self.pid,done['task']['id'],dict(result_id=result['id'],request_sha256=done['task']['binding']['request_sha256'],expected_revision=done['revision']));self.assertEqual(inspected['status'],'needs_verification');self.assertFalse(inspected['formal_modification_permission'])
 def test_bad_pair_quote_version_fact_or_unknown_output_fails_with_preserved_response(self):
  preview=self.setup_review()
  changes=[lambda v:v['findings'][0]['evidence'][0].update(quote='伪造'),lambda v:v['findings'][0]['evidence'][1].update(rule_id=v['findings'][0]['evidence'][0]['rule_id']),lambda v:v['findings'][0]['evidence'][0].update(version=999),lambda v:v['findings'][0].update(assessment='confirmed_fact'),lambda v:v.update(apply=True)]
  for change in changes:
   with self.subTest(change=change),fixtures.supplier(output=opinion(preview['rules'],change)) as wire:
    view,_=self.prepare_review(self.connection(wire));done=self.run_review(view);self.assertEqual(done['status'],'failed');self.assertEqual(len(done['results']),1);self.assertIsNone(done['results'][0]['output']);self.assertEqual(done['events'][-1]['error_code'],'invalid_rule_opinion_or_evidence')
 def test_new_rule_stales_send_and_successful_result_use_but_other_task_does_not(self):
  preview=self.setup_review()
  with fixtures.supplier(output=opinion(preview['rules'])) as wire:
   view,_=self.prepare_review(self.connection(wire));self.rules.save(self.pid,dict(operation_id=str(uuid4()),rule_id=None,scope='book',scope_id=self.pid,kind='guidance',text='新增本书规则',enabled=True));before=self.service.get(self.pid)
   with self.assertRaises(ValueError):self.run_review(view)
   self.assertEqual(wire['calls'],[]);self.assertEqual(self.service.get(self.pid),before)
  preview=self.review.preview(self.pid,dict(chapter_id=self.cid,target_task_id=None))
  with fixtures.supplier(output=opinion(preview['rules'])) as wire:
   view,_=self.prepare_review(self.connection(wire));done=self.run_review(view);self.assertEqual(done['status'],'succeeded');result=done['results'][0];self.rules.set_enabled(self.pid,dict(rule_id=preview['rules'][0]['id'],enabled=False));before=self.service.get(self.pid)
   with self.assertRaises(ValueError):self.review.inspect(self.pid,view['task']['id'],dict(result_id=result['id'],request_sha256=view['task']['binding']['request_sha256'],expected_revision=before['revision']))
   self.assertEqual(self.service.get(self.pid),before);self.assertEqual(self.review.describe(self.pid,view['task']['id'])['results'][0],result)

if __name__=='__main__':unittest.main()
