from http.client import HTTPConnection
import json,tempfile,threading,unittest
from pathlib import Path
from uuid import uuid4
from novel_writer.ui.server import create_server
from test_book_ai import supplier

class ChapterPlanningHttpTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='novel-planning-http-');self.addCleanup(self.temp.cleanup);root=Path(self.temp.name)
  self.server=create_server(root/'fiction.sqlite3',port=0,provider_path=root/'fiction.dpapi',enable_model_generation=True)
  self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start();self.addCleanup(self.stop)
  code,state=self.request('POST','/api/projects',dict(title='章节构思HTTP'));self.assertEqual(code,201);self.pid=state['document']['project']['id']
  code,state=self.request('POST','/api/projects/'+self.pid+'/actions',dict(action='add_character',fields=dict(name='林舟'),expected_revision=state['revision']));self.chid=state['document']['characters'][0]['id']
  code,state=self.request('POST','/api/projects/'+self.pid+'/actions',dict(action='add_chapter',fields=dict(title='第一封信'),expected_revision=state['revision']));self.cid=state['document']['chapters'][0]['id'];self.revision=state['revision'];self.base='/api/projects/'+self.pid+'/chapter-planning'
 def stop(self):self.server.shutdown();self.server.server_close();self.thread.join(2)
 def request(self,method,path,payload=None,*,token=True):
  client=HTTPConnection('127.0.0.1',self.server.server_port,timeout=10);headers={'Content-Type':'application/json'}
  if token:headers['X-Novel-Token']=self.server.token
  try:client.request(method,path,json.dumps(payload) if payload is not None else None,headers);response=client.getresponse();return response.status,json.loads(response.read())
  finally:client.close()
 def source(self,mode='brainstorm'):return dict(chapter_id=self.cid,mode=mode,instruction='HTTP只读本书',character_ids=[self.chid],include_worldbuilding=False,include_writing_rules=False,include_facts=False,include_locations=False,context_budget_chars=8000)
 def profile(self,connection):return dict(adapter_id='configured-http-v2',connection_id=connection['id'],model_id=connection['model_id'],temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=True,prompt_version='rewrite-1')
 def test_preview_is_read_only_strict_and_token_bound(self):
  before=self.request('GET','/api/projects/'+self.pid)[1];options=self.source()
  self.assertEqual(self.request('POST',self.base+'/preview',options,token=False)[0],403)
  code,preview=self.request('POST',self.base+'/preview',options);self.assertEqual(code,200,preview);self.assertFalse(preview['model_request_sent']);self.assertIn(self.chid,preview['context_text']);self.assertEqual(self.request('GET','/api/projects/'+self.pid)[1],before)
  self.assertEqual(self.request('POST',self.base+'/preview',dict(options,character_ids=[str(uuid4())]))[0],422)
  self.assertEqual(self.request('POST',self.base+'/preview',dict(options,endpoint='http://private.invalid'))[0],422)
 def test_prepare_execute_correct_review_accept_are_distinct_and_idempotent(self):
  with supplier(output='{"note":"坏格式"}') as wire:
   connection=self.server.providers.save_custom(id=str(uuid4()),name='HTTP章节构思',base_url=wire['url'],protocol='openai-chat',model_id='fixture',api_key='fiction-http-planning-key',allow_local=True)
   options=self.source();code,source=self.request('POST',self.base+'/preview',options);request=dict(operation_id=str(uuid4()),source_options=options,source_sha256=source['source_sha256'],model_options=self.profile(connection),max_output_chars=8000,timeout_ms=2000)
   code,prepared=self.request('POST',self.base+'/prepare',request);self.assertEqual(code,201,prepared);self.assertEqual(wire['calls'],[]);task=prepared['task'];url=self.base+'/'+task['id']
   self.assertEqual(self.request('POST',url+'/execute',dict(confirm_external=True,request_sha256='0'*64))[0],422);self.assertEqual(wire['calls'],[])
   self.assertEqual(self.request('POST',url+'/execute',dict(confirm_external=True,request_sha256=task['binding']['request_sha256']))[0],200);self.server.task_coordinator.wait_idle(6)
   view=self.request('GET',url)[1];self.assertEqual(view['status'],'failed');candidate=view['latest_candidate'];self.assertIn('missing:idea',candidate['errors'])
   code,fixed=self.request('POST',self.base+'/correct',dict(operation_id=str(uuid4()),task_id=task['id'],candidate_id=candidate['id'],text=json.dumps(dict(idea='HTTP人工修正的IDEA'),ensure_ascii=False)));self.assertEqual(code,201,fixed);candidate=fixed['latest_candidate']
   code,review=self.request('POST',self.base+'/review',dict(operation_id=str(uuid4()),task_id=task['id'],candidate_id=candidate['id'],candidate_sha256=candidate['data_sha256']));self.assertEqual(code,201,review);self.assertEqual(review['after']['idea'],'HTTP人工修正的IDEA')
   accept=dict(operation_id=str(uuid4()),task_id=task['id'],candidate_id=candidate['id'],candidate_sha256=candidate['data_sha256'],review_id=review['id'],review_sha256=review['review_sha256'],expected_revision=self.server.service.get(self.pid)['revision'],confirm_chapter=True)
   self.assertEqual(self.request('POST',self.base+'/accept',dict(accept,confirm_chapter=False))[0],422)
   code,receipt=self.request('POST',self.base+'/accept',accept);self.assertEqual(code,200,receipt);state=self.server.service.get(self.pid);self.assertEqual(state['ideas'][self.cid],'HTTP人工修正的IDEA');self.assertEqual(state['document']['chapters'][0]['content'],'')
   self.assertEqual(self.request('POST',self.base+'/accept',accept),(200,receipt));self.assertEqual(self.server.service.get(self.pid),state);self.assertEqual(len(wire['calls']),1)

if __name__=='__main__':unittest.main()
