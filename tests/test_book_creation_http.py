from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile,threading,unittest
from uuid import uuid4
from novel_writer.ui.server import create_server
class BookCreationHttpTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='novel-f1-http-');self.addCleanup(self.temp.cleanup);root=Path(self.temp.name);self.server=create_server(root/'book.sqlite3',port=0,provider_path=root/'providers.dpapi',offline=True);self.worker=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.worker.start();self.addCleanup(self.stop);self.pid=self.server.service.create(title='虚构HTTP空书')['document']['project']['id'];self.base='/api/projects/'+self.pid+'/book-creation'
 def stop(self):self.server.shutdown();self.server.server_close();self.worker.join(2)
 def request(self,method,path,payload=None,token=True):
  c=HTTPConnection('127.0.0.1',self.server.server_port,timeout=5);headers={'Content-Type':'application/json'}
  if token:headers['X-Novel-Token']=self.server.token
  try:c.request(method,path,json.dumps(payload) if payload is not None else None,headers);r=c.getresponse();return r.status,json.loads(r.read())
  finally:c.close()
 def test_http_starts_saved_proposal_and_requires_token_without_formal_entities(self):
  state=self.server.service.get(self.pid);request=dict(operation_id=str(uuid4()),expected_revision=state['revision'],name='HTTP方案');self.assertEqual(self.request('POST',self.base+'/start',request,token=False)[0],403);code,result=self.request('POST',self.base+'/start',request);self.assertEqual(code,201,result);self.assertEqual(self.request('GET',self.base)[1]['selected']['id'],result['version_id']);self.assertEqual(self.server.service.get(self.pid)['document']['chapters'],[])
 def test_unknown_step_data_cannot_smuggle_body_or_execution(self):
  request=dict(operation_id=str(uuid4()),expected_revision=self.server.service.get(self.pid)['revision'],name='HTTP方案');code,start=self.request('POST',self.base+'/start',request);self.assertEqual(code,201,start);before=self.server.service.get(self.pid);payload=dict(operation_id=str(uuid4()),expected_revision=before['revision'],base_version_id=start['version_id'],step='idea',fields=dict(content='不准写正文'),mark='save',next_step='idea');self.assertEqual(self.request('POST',self.base+'/save-step',payload)[0],422);self.assertEqual(self.server.service.get(self.pid),before)
if __name__=='__main__':unittest.main()
