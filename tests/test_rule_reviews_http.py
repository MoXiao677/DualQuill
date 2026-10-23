"""Actual authenticated HTTP semantic review workflow, fictional random loopback only."""
import unittest
from uuid import uuid4
import test_scoped_rules_http as fixtures
from test_book_ai import supplier
from test_rule_semantic_reviews import opinion

class RuleReviewHttpTests(unittest.TestCase):
 setUp=fixtures.ScopedRuleHttpTests.setUp
 stop=fixtures.ScopedRuleHttpTests.stop
 request=fixtures.ScopedRuleHttpTests.request
 def setup_source(self):
  for kind,text in (('required','近距离第一人称🙂'),('guidance','全知叙述远处事件')):
   code,_,_=self.request('POST',self.base+'/rules/save',dict(operation_id=str(uuid4()),rule_id=None,scope='book',scope_id=self.pid,kind=kind,text=text,enabled=True));self.assertEqual(code,200)
  code,preview,_=self.request('POST',self.base+'/rule-reviews/preview',dict(chapter_id=self.cid,target_task_id=None));self.assertEqual(code,200);return preview
 def preparation(self,wire,preview):
  c=self.server.providers.save_custom(id=str(uuid4()),name='虚构规则审阅',base_url=wire['url'],protocol='openai-chat',model_id='fiction-rules',api_key='fiction-http-rules-key',allow_local=True)
  return dict(request_id=str(uuid4()),chapter_id=self.cid,target_task_id=None,source_sha256=preview['source_sha256'],model_options=dict(adapter_id='configured-http-v2',connection_id=c['id'],model_id=c['model_id'],temperature=.3,max_tokens=1024,budget_limit=1.,allow_unknown_cost=True,prompt_version='rule-conflicts-json-1'),max_output_chars=10000,timeout_ms=2000,budget_max_calls=2,budget_max_output_tokens=2048)
 def state(self):return self.server.service.get(self.pid)
 def test_complete_http_preview_freeze_confirm_and_readonly_opinion(self):
  preview=self.setup_source()
  with supplier(output=opinion(preview['rules'])) as wire:
   request=self.preparation(wire,preview);code,view,_=self.request('POST',self.base+'/rule-reviews/prepare',request);self.assertEqual(code,200,view);self.assertEqual(wire['calls'],[]);url=self.base+'/rule-reviews/'+view['task']['id'];confirm=dict(confirm_external=True,request_sha256=view['task']['binding']['request_sha256']);before=self.state()
   self.assertEqual(self.request('POST',url+'/execute',confirm)[0],422);self.assertEqual(self.state(),before)
   self.server.rule_reviews.adapter.enabled=True;self.server.model_generation_enabled=True
   self.assertEqual(self.request('POST',url+'/execute',dict(confirm,force=True))[0],422);self.assertEqual(self.request('POST',url+'/execute',confirm,token=False)[0],403);self.assertEqual(self.state(),before)
   code,_,_=self.request('POST',url+'/execute',confirm);self.assertEqual(code,200);self.server.task_coordinator.wait_idle(5);code,done,_=self.request('GET',url);self.assertEqual(code,200);self.assertEqual(done['status'],'succeeded',done);result=done['results'][0];before=self.state();code,inspection,_=self.request('POST',url+'/inspect',dict(result_id=result['id'],request_sha256=confirm['request_sha256'],expected_revision=before['revision']));self.assertEqual(code,200,inspection);self.assertEqual(inspection['status'],'needs_verification');self.assertFalse(inspection['formal_modification_permission']);self.assertEqual(self.state(),before);self.assertEqual(len(wire['calls']),1)
   self.assertEqual(self.request('POST',url+'/execute',confirm)[0],422);self.assertEqual(self.request('POST',url+'/accept',{})[0],404);self.assertEqual(self.state(),before)
 def test_unknown_fields_crossbook_stale_revision_cancel_and_recovery(self):
  preview=self.setup_source();before=self.state()
  for body in ({},dict(chapter_id=self.cid,target_task_id=None,apply=True),dict(chapter_id=self.cid,target_task_id=str(uuid4()))):
   self.assertEqual(self.request('POST',self.base+'/rule-reviews/preview',body)[0],422);self.assertEqual(self.state(),before)
  with supplier(output=opinion(preview['rules'])) as wire:
   req=self.preparation(wire,preview);self.assertEqual(self.request('POST',self.base+'/rule-reviews/prepare',dict(req,automatic=True))[0],422);self.assertEqual(self.state(),before);code,view,_=self.request('POST',self.base+'/rule-reviews/prepare',req);self.assertEqual(code,200);url=self.base+'/rule-reviews/'+view['task']['id'];before=self.state();self.assertEqual(self.request('POST',url+'/cancel',dict(force=True))[0],422);self.assertEqual(self.request('POST',self.base+'/rule-reviews/recover',dict(resend=True))[0],422);self.assertEqual(self.state(),before)
   other=self.request('POST','/api/projects',dict(title='另一虚构书'))[1]['document']['project']['id'];code,_,_=self.request('GET','/api/projects/'+other+'/rule-reviews/'+view['task']['id']);self.assertEqual(code,404);self.assertEqual(self.request('POST',url+'/cancel',{})[0],200);self.assertEqual(self.request('POST',self.base+'/rule-reviews/recover',{})[1]['interrupted'],[]);self.assertEqual(wire['calls'],[])
 def test_preparation_requires_task_identity_separation_and_does_not_expose_key(self):
  preview=self.setup_source();identity=str(uuid4());self.request('POST',self.base+'/rules/bind-task',dict(request_id=identity,chapter_id=self.cid,task_type='draft_chapter'))
  with supplier() as wire:
   req=self.preparation(wire,preview);req['request_id']=identity;before=self.state();self.assertEqual(self.request('POST',self.base+'/rule-reviews/prepare',req)[0],422);self.assertEqual(self.state(),before);self.assertNotIn('fiction-http-rules-key',str(self.request('GET',self.base+'/rule-reviews')));self.assertEqual(wire['calls'],[])

if __name__=='__main__':unittest.main()
