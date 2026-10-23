"""Strict authenticated HTTP routes for task bindings and untrusted semantic opinions."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch
from uuid import uuid4
import test_scoped_rules_http as fixtures
from novel_writer.domain.tasks import digest


class TaskScopedRuleHTTPTests(fixtures.ScopedRuleHttpTests):
 def bind(self):
  target=str(uuid4());code,result,_=self.request('POST',self.base+'/rules/bind-task',dict(request_id=target,chapter_id=self.cid,task_type='rewrite_chapter'));self.assertEqual(code,200,result);return target
 def state(self):return self.server.service.get(self.pid)
 def test_strict_fields_csrf_identity_and_zero_writes(self):
  valid=dict(request_id=str(uuid4()),chapter_id=self.cid,task_type='rewrite_chapter');before=self.state()
  for payload in ({},dict(valid,automatic=True),dict(valid,task_type='arbitrary'),dict(valid,request_id=True),dict(valid,chapter_id='foreign')):
   code,result,_=self.request('POST',self.base+'/rules/bind-task',payload);self.assertEqual(code,422,result);self.assertEqual(self.state(),before)
  self.assertEqual(self.request('POST',self.base+'/rules/bind-task',valid,token=False)[0],403);self.assertEqual(self.state(),before)
  code,first,_=self.request('POST',self.base+'/rules/bind-task',valid);self.assertEqual(code,200);before=self.state();self.assertEqual(self.request('POST',self.base+'/rules/bind-task',valid)[1],first);self.assertEqual(self.state(),before)
 def test_bound_context_prepare_identity_and_freeze_trace(self):
  target=self.bind();code,rule,_=self.save('task','required',target);self.assertEqual(code,200,rule)
  options=dict(chapter_id=self.cid,rule_task_id=target,budget_chars=20000);code,preview,_=self.request('POST',self.base+'/context-preview',options);self.assertEqual(code,200,preview);self.assertIn('同一文本',preview['context_text'])
  req=dict(request_id=target,chapter_id=self.cid,task_type='rewrite_chapter',context_options=options,context_sha256=digest(preview['context_text']),parameters=dict(instruction='虚构改写',max_output_chars=10000,timeout_ms=1000),expected_revision=self.state()['revision']);before=self.state();bad=deepcopy(req);bad['request_id']=str(uuid4())
  self.assertEqual(self.request('POST',self.base+'/tasks/prepare',bad)[0],422);self.assertEqual(self.state(),before)
  code,prepared,_=self.request('POST',self.base+'/tasks/prepare',req);self.assertEqual(code,201,prepared)
  code,detail,_=self.request('GET',self.base+'/tasks/'+prepared['task']['id']);self.assertEqual(code,200);self.assertTrue(detail['rules_fresh']);self.assertEqual(detail['rule_task_id'],target);self.assertEqual(detail['rule_trace'][0]['rule_id'],rule['id'])
  self.request('POST',self.base+'/rules/enabled',dict(rule_id=rule['id'],enabled=False));detail=self.request('GET',self.base+'/tasks/'+prepared['task']['id'])[1];self.assertFalse(detail['rules_fresh']);self.assertIn('同一文本',detail['task']['frozen']['context_text'])
 def test_import_conflicts_and_stale_preview_leave_entire_state_unchanged(self):
  target=self.bind();self.save('task','required',target);row=dict(scope='task',scope_id=target,kind='forbidden',text='同一文本',enabled=True);content=json.dumps([row]);code,preview,_=self.request('POST',self.base+'/rules/import-preview',dict(format='json',content=content));self.assertFalse(preview['can_confirm']);before=self.state()
  self.assertEqual(self.request('POST',self.base+'/rules/import',dict(operation_id=str(uuid4()),format='json',content=content,preview_sha256=preview['preview_sha256']))[0],422);self.assertEqual(self.state(),before)
  row['text']='另一个虚构词';content=json.dumps([row]);preview=self.request('POST',self.base+'/rules/import-preview',dict(format='json',content=content))[1];self.save('book','guidance',self.pid);before=self.state()
  self.assertEqual(self.request('POST',self.base+'/rules/import',dict(operation_id=str(uuid4()),format='json',content=content,preview_sha256=preview['preview_sha256']))[0],422);self.assertEqual(self.state(),before)
 def test_semantic_quotes_unknown_fields_no_permission_and_no_mutation(self):
  target=self.bind();a=self.save('task','required',target)[1];b=self.save('book','guidance',self.pid)[1];before=self.state()
  req=dict(chapter_id=self.cid,task_id=target,observations=[dict(rule_ids=[a['id'],b['id']],quotes=['同一','文本'],reason='可能冲突但不确定')]);code,report,_=self.request('POST',self.base+'/rules/semantic-preview',req);self.assertEqual(code,200,report);self.assertFalse(report['semantic_quality_verified']);self.assertFalse(report['proposals'][0]['can_apply']);self.assertEqual(self.state(),before)
  for bad in (dict(req,apply=True),dict(req,observations=[dict(req['observations'][0],confidence=1)]),dict(req,observations=[dict(req['observations'][0],quotes=['不存在的引文','文本'])])):
   self.assertEqual(self.request('POST',self.base+'/rules/semantic-preview',bad)[0],422);self.assertEqual(self.state(),before)
  self.assertEqual(self.request('POST',self.base+'/rules/semantic-preview',req,token=False)[0],403)
 def test_resolve_task_crossbook_and_strict_body(self):
  target=self.bind();self.save('task','required',target);before=self.state();req=dict(chapter_id=self.cid,task_id=target)
  self.assertEqual(self.request('POST',self.base+'/rules/resolve-task',req)[0],200)
  for bad in (dict(req,task_id=str(uuid4())),dict(req,chapter_id='foreign'),dict(req,force=True)):
   self.assertEqual(self.request('POST',self.base+'/rules/resolve-task',bad)[0],422);self.assertEqual(self.state(),before)
  code,other,_=self.request('POST','/api/projects',dict(title='另一虚构书'));other_id=other['document']['project']['id'];self.assertEqual(self.request('POST','/api/projects/'+other_id+'/rules/resolve-task',req)[0],422)
 def test_mid_import_failure_over_http_rolls_back_rule_history_and_revision(self):
  import novel_writer.application.scoped_rules as module
  target=self.bind();content=json.dumps([dict(scope='task',scope_id=target,kind='guidance',text=text,enabled=True) for text in ('甲','乙')]);preview=self.request('POST',self.base+'/rules/import-preview',dict(format='json',content=content))[1];before=self.state();calls=[];original=module._history
  def fail(*args,**kwargs):
   calls.append(1)
   if len(calls)==2:raise ValueError('虚构第二条历史失败')
   return original(*args,**kwargs)
  with patch.object(module,'_history',fail):
   code,result,_=self.request('POST',self.base+'/rules/import',dict(operation_id=str(uuid4()),format='json',content=content,preview_sha256=preview['preview_sha256']))
  self.assertEqual(code,422,result);self.assertEqual(len(calls),2);self.assertEqual(self.state(),before)


if __name__=='__main__':unittest.main()
