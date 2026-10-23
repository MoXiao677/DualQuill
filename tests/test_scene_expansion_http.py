from http.client import HTTPConnection
import json,tempfile,threading,unittest
from pathlib import Path
from uuid import uuid4
from novel_writer.ui.server import create_server
from test_book_ai import supplier

class SceneExpansionHttpTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='scene-expansion-http-');self.addCleanup(self.temp.cleanup);root=Path(self.temp.name)
  self.server=create_server(root/'fiction.sqlite3',port=0,provider_path=root/'fiction.dpapi',enable_model_generation=True)
  self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start();self.addCleanup(self.stop)
  code,state=self.request('POST','/api/projects',dict(title='扩写HTTP'));self.assertEqual(code,201);self.pid=state['document']['project']['id']
  code,state=self.request('POST','/api/projects/'+self.pid+'/actions',dict(action='add_character',fields=dict(name='林舟'),expected_revision=state['revision']));self.chid=state['document']['characters'][0]['id']
  code,state=self.request('POST','/api/projects/'+self.pid+'/actions',dict(action='add_chapter',fields=dict(title='第一封信'),expected_revision=state['revision']));self.cid=state['document']['chapters'][0]['id']
  code,state=self.request('POST','/api/projects/'+self.pid+'/actions',dict(action='save_chapter',fields=dict(chapter_id=self.cid,content='前缀😀门外有雾。\n尾声。'),expected_revision=state['revision']));self.original=state['document']['chapters'][0]['content']
  self.request('POST','/api/projects/'+self.pid+'/actions',dict(action='save_chapter_outline',fields=dict(chapter_id=self.cid,core_idea='门外',objective='开门',story_time='第1天',character_ids=[self.chid],scenes=[dict(order=1,summary='封蜡揭示',character_ids=[self.chid],location='门外',story_time='清晨')]),expected_revision=state['revision']))
  self.base='/api/projects/'+self.pid+'/scene-expansion'
 def stop(self):self.server.shutdown();self.server.server_close();self.thread.join(2)
 def request(self,method,path,payload=None,*,token=True):
  c=HTTPConnection('127.0.0.1',self.server.server_port,timeout=10);headers={'Content-Type':'application/json'}
  if token:headers['X-Novel-Token']=self.server.token
  try:c.request(method,path,json.dumps(payload) if payload is not None else None,headers);r=c.getresponse();return r.status,json.loads(r.read())
  finally:c.close()
 def source(self):return dict(chapter_id=self.cid,target_kind='selection',scene_order=None,selection_start=3,selection_end=8,instruction='只扩写选区',target_chars=300,character_ids=[self.chid],include_worldbuilding=False,include_writing_rules=False,include_facts=False,context_budget_chars=8000)
 def profile(self,connection):return dict(adapter_id='configured-http-v2',connection_id=connection['id'],model_id=connection['model_id'],temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=True,prompt_version='rewrite-1')
 def test_preview_is_read_only_strict_and_token_bound(self):
  before=self.request('GET','/api/projects/'+self.pid)[1];source=self.source()
  self.assertEqual(self.request('POST',self.base+'/preview',source,token=False)[0],403)
  code,preview=self.request('POST',self.base+'/preview',source);self.assertEqual(code,200,preview);self.assertFalse(preview['model_request_sent']);self.assertEqual(preview['source_options']['selection_start'],3);self.assertIn('门外有雾',preview['context_text']);self.assertEqual(self.request('GET','/api/projects/'+self.pid)[1],before)
  for bad in (dict(source,selection_end=0),dict(source,selection_end=999),dict(source,scene_order=1),dict(source,target_kind='scene',scene_order=99,selection_start=None,selection_end=None),dict(source,endpoint='http://private.invalid')):
   self.assertEqual(self.request('POST',self.base+'/preview',bad)[0],422)
 def test_prepare_execute_correct_review_accept_and_idempotency(self):
  with supplier(output='门外传来潮声。') as wire:
   connection=self.server.providers.save_custom(id=str(uuid4()),name='HTTP扩写',base_url=wire['url'],protocol='openai-chat',model_id='fixture',api_key='fiction-http-expansion-key',allow_local=True)
   source=self.source();code,preview=self.request('POST',self.base+'/preview',source);request=dict(operation_id=str(uuid4()),source_options=source,source_sha256=preview['source_sha256'],model_options=self.profile(connection),max_output_chars=4000,timeout_ms=2000)
   code,prepared=self.request('POST',self.base+'/prepare',request);self.assertEqual(code,201,prepared);task=prepared['task'];url=self.base+'/'+task['id'];self.assertEqual(wire['calls'],[])
   self.assertEqual(self.request('POST',url+'/execute',dict(confirm_external=True,request_sha256='0'*64))[0],422);self.assertEqual(wire['calls'],[])
   self.assertEqual(self.request('POST',url+'/execute',dict(confirm_external=True,request_sha256=task['binding']['request_sha256']))[0],200);self.server.task_coordinator.wait_idle(6)
   view=self.request('GET',url)[1];candidate=view['latest_candidate'];self.assertEqual(candidate['text'],'门外传来潮声。')
   code,fixed=self.request('POST',self.base+'/correct',dict(operation_id=str(uuid4()),task_id=task['id'],candidate_id=candidate['id'],text='门外只有潮声和雾。'));self.assertEqual(code,201,fixed);candidate=fixed['latest_candidate']
   code,review=self.request('POST',self.base+'/review',dict(operation_id=str(uuid4()),task_id=task['id'],candidate_id=candidate['id'],candidate_sha256=candidate['data_sha256']));self.assertEqual(code,201,review);self.assertEqual(review['selected_before'],'门外有雾。');self.assertEqual(review['selected_after'],'门外只有潮声和雾。')
   accept=dict(operation_id=str(uuid4()),task_id=task['id'],candidate_id=candidate['id'],candidate_sha256=candidate['data_sha256'],review_id=review['id'],review_sha256=review['review_sha256'],expected_revision=self.server.service.get(self.pid)['revision'],confirm_chapter=True,authorize_confirmed=False)
   code,receipt=self.request('POST',self.base+'/accept',accept);self.assertEqual(code,200,receipt);state=self.server.service.get(self.pid);expected=self.original[:3]+'门外只有潮声和雾。'+self.original[8:];self.assertEqual(state['document']['chapters'][0]['content'],expected);self.assertEqual(self.request('POST',self.base+'/accept',accept),(200,receipt));self.assertEqual(self.server.service.get(self.pid),state);self.assertEqual(len(wire['calls']),1)

if __name__=='__main__':unittest.main()
