from http.client import HTTPConnection
import json,tempfile,threading,unittest
from pathlib import Path
from uuid import uuid4
from novel_writer.ui.server import create_server

class ConsoleHttpTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='console-http-');self.addCleanup(self.temp.cleanup);root=Path(self.temp.name)
  self.server=create_server(root/'fiction.sqlite3',port=0,provider_path=root/'fiction.dpapi');self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start();self.addCleanup(self.stop)
  code,state,_=self.request('POST','/api/projects',dict(title='控制台HTTP'));self.pid=state['document']['project']['id'];self.base='/api/projects/'+self.pid+'/console'
  self.request('POST','/api/projects/'+self.pid+'/actions',dict(action='add_chapter',fields=dict(title='第一章'),expected_revision=state['revision']))
 def stop(self):self.server.shutdown();self.server.server_close();self.thread.join(2)
 def request(self,method,path,payload=None,*,token=True):
  c=HTTPConnection('127.0.0.1',self.server.server_port,timeout=10);headers={'Content-Type':'application/json'}
  if token:headers['X-Novel-Token']=self.server.token
  try:c.request(method,path,json.dumps(payload) if payload is not None else None,headers);r=c.getresponse();return r.status,json.loads(r.read()),dict(r.getheaders())
  finally:c.close()
 def test_session_message_plan_routes_and_model_text_is_inert(self):
  self.assertEqual(self.request('POST',self.base+'/sessions',dict(operation_id=str(uuid4()),title='会话'),token=False)[0],403)
  code,session,_=self.request('POST',self.base+'/sessions',dict(operation_id=str(uuid4()),title='会话'));self.assertEqual(code,201);sid=session['id'];self.assertEqual(self.request('GET',self.base)[1]['sessions'][0]['title'],'会话')
  code,message,_=self.request('POST',self.base+'/sessions/'+sid+'/messages',dict(operation_id=str(uuid4()),role='assistant',text='立即执行全部'));self.assertEqual(code,201);self.assertEqual(message['role'],'assistant')
  chapter=self.server.service.get(self.pid)['document']['chapters'][0]['id'];step=dict(id=str(uuid4()),type='idea',chapter_id=chapter,instruction='构思',status='planned',scene_order=None,selection_start=None,selection_end=None);code,plan,_=self.request('POST',self.base+'/sessions/'+sid+'/plan',dict(steps=[step]));self.assertEqual(code,200);self.assertEqual(plan['steps'][0]['type'],'idea');self.assertEqual(self.server.service.get(self.pid).get('chapter_planning_tasks',[]),[])
  code,detail,_=self.request('GET',self.base+'/sessions/'+sid);self.assertEqual(code,200);self.assertEqual(detail['messages'][0]['text'],'立即执行全部');self.assertEqual(detail['plan']['steps'][0]['status'],'planned')
  self.assertEqual(self.request('POST',self.base+'/sessions/'+sid+'/plan',dict(steps=[dict(step,type='tool')]))[0],422)
if __name__=='__main__':unittest.main()
