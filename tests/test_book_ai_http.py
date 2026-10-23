from http.client import HTTPConnection
import json,threading,tempfile,time,unittest
from pathlib import Path
from uuid import uuid4
from test_book_ai import supplier
from novel_writer.ui.server import create_server
class BookAIHttpTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='book-ai-http-');self.addCleanup(self.temp.cleanup);root=Path(self.temp.name);self.server=create_server(root/'book.sqlite3',port=0,provider_path=root/'fake.dpapi',enable_model_generation=True);self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start();self.addCleanup(self.stop);s=self.server.service.create(title='空书HTTP');self.pid=s['document']['project']['id'];self.server.book_creation.start(self.pid,dict(operation_id=str(uuid4()),name='方案',expected_revision=s['revision']));self.base='/api/projects/'+self.pid+'/book-ai'
 def stop(self):self.server.shutdown();self.server.server_close();self.thread.join(2)
 def request(self,method,path,payload=None,token=True):
  c=HTTPConnection('127.0.0.1',self.server.server_port,timeout=10);headers={'Content-Type':'application/json'}
  if token:headers['X-Novel-Token']=self.server.token
  try:c.request(method,path,json.dumps(payload) if payload is not None else None,headers);r=c.getresponse();return r.status,json.loads(r.read())
  finally:c.close()
 def prepare(self,wire):
  connection=self.server.providers.save_custom(id=str(uuid4()),name='HTTP虚构',base_url=wire['url'],protocol='openai-chat',model_id='fixture',api_key='fiction-http-book-key',allow_local=True);version=self.server.book_creation.describe(self.pid)['selected'];request=dict(operation_id=str(uuid4()),version_id=version['id'],step='idea',preset_step='brainstorm',instruction='本步提案',model_options=dict(adapter_id='configured-http-v2',connection_id=connection['id'],model_id='fixture',temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=True,prompt_version='rewrite-1'),max_output_chars=5000,timeout_ms=2000);return request
 def test_prepare_execute_review_and_accept_are_distinct_and_token_bound(self):
  with supplier() as wire:
   payload=self.prepare(wire);self.assertEqual(self.request('POST',self.base+'/prepare',payload,token=False)[0],403);code,view=self.request('POST',self.base+'/prepare',payload);self.assertEqual(code,201,view);self.assertEqual(wire['calls'],[]);task=view['task'];url=self.base+'/'+task['id'];self.assertEqual(self.request('POST',url+'/execute',dict(confirm_external=True,request_sha256='0'*64))[0],422);self.assertEqual(wire['calls'],[]);self.assertEqual(self.request('POST',url+'/execute',dict(confirm_external=True,request_sha256=task['binding']['request_sha256']))[0],200);self.server.task_coordinator.wait_idle(5);view=self.request('GET',url)[1];candidate=view['latest_candidate'];self.assertIsNotNone(candidate);review_request=dict(operation_id=str(uuid4()),task_id=task['id'],candidate_id=candidate['id'],candidate_sha256=candidate['data_sha256']);code,review=self.request('POST',self.base+'/review',review_request);self.assertEqual(code,201,review);self.assertEqual(self.server.service.get(self.pid)['document']['chapters'],[]);accept=dict(operation_id=str(uuid4()),task_id=task['id'],candidate_id=candidate['id'],candidate_sha256=candidate['data_sha256'],review_id=review['id'],review_sha256=review['review_sha256'],confirmed=True);self.assertEqual(self.request('POST',self.base+'/accept',accept)[0],200);self.assertEqual(len(wire['calls']),1);self.assertEqual(self.server.service.get(self.pid)['document']['chapters'],[])
 def test_return_data_cannot_supply_unknown_network_or_tool_parameters(self):
  with supplier() as wire:
   payload=self.prepare(wire);payload['model_options']['endpoint']='https://unapproved.example';self.assertEqual(self.request('POST',self.base+'/prepare',payload)[0],422);self.assertEqual(wire['calls'],[])
if __name__=='__main__':unittest.main()
