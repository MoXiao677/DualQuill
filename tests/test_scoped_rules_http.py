from http.client import HTTPConnection
import json,tempfile,threading,unittest
from pathlib import Path
from uuid import uuid4
from novel_writer.ui.server import create_server

class ScopedRuleHttpTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='rules-http-');self.addCleanup(self.temp.cleanup);root=Path(self.temp.name)
  self.server=create_server(root/'fiction.sqlite3',port=0,provider_path=root/'fiction.dpapi');self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start();self.addCleanup(self.stop)
  code,state,_=self.request('POST','/api/projects',dict(title='规则HTTP'));self.pid=state['document']['project']['id'];self.base='/api/projects/'+self.pid
  code,state,_=self.request('POST',self.base+'/actions',dict(action='add_chapter',fields=dict(title='第一章'),expected_revision=state['revision']));self.cid=state['document']['chapters'][0]['id']
 def stop(self):self.server.shutdown();self.server.server_close();self.thread.join(2)
 def request(self,method,path,payload=None,*,token=True):
  c=HTTPConnection('127.0.0.1',self.server.server_port,timeout=10);headers={'Content-Type':'application/json'}
  if token:headers['X-Novel-Token']=self.server.token
  try:c.request(method,path,json.dumps(payload) if payload is not None else None,headers);r=c.getresponse();return r.status,json.loads(r.read()),dict(r.getheaders())
  finally:c.close()
 def save(self,scope,kind,scope_id):
  return self.request('POST',self.base+'/rules/save',dict(operation_id=str(uuid4()),rule_id=None,scope=scope,scope_id=scope_id,kind=kind,text='同一文本',enabled=True))
 def test_rule_crud_resolution_and_conflict(self):
  code,a,_=self.save('book','required',self.pid);self.assertEqual(code,200);code,b,_=self.save('chapter','forbidden',self.cid);self.assertEqual(code,200)
  code,resolved,_=self.request('GET',self.base+'/rules/resolve/'+self.cid);self.assertEqual(code,200);self.assertEqual(len(resolved['conflicts']),1)
  code,listing,_=self.request('GET',self.base+'/rules');self.assertEqual(code,200);self.assertEqual(len(listing['rules']),2)
  self.assertEqual(self.request('POST',self.base+'/rules/enabled',dict(rule_id=b['id'],enabled=False))[0],200);code,resolved,_=self.request('GET',self.base+'/rules/resolve/'+self.cid);self.assertEqual(resolved['conflicts'],[])
  self.assertEqual(self.request('POST',self.base+'/rules/archive',dict(rule_id=a['id'],archived=True))[0],200);self.assertEqual(self.request('POST',self.base+'/rules/save',dict(operation_id=str(uuid4()),rule_id=None,scope='unknown',scope_id='x',kind='guidance',text='x',enabled=True))[0],422)
  self.assertEqual(self.request('POST',self.base+'/rules/save',dict(operation_id=str(uuid4()),rule_id=None,scope='book',scope_id=self.pid,kind='guidance',text='x',enabled=True),token=False)[0],403)
 def test_import_preview_confirm_history_and_idempotency(self):
  rows=[dict(scope='global',scope_id=None,kind='guidance',text='导入全局',enabled=True),dict(scope='chapter',scope_id=self.cid,kind='required',text='导入章级',enabled=True)]
  content=json.dumps(rows,ensure_ascii=False);code,preview,_=self.request('POST',self.base+'/rules/import-preview',dict(format='json',content=content));self.assertEqual(code,200);self.assertTrue(preview['can_confirm']);self.assertEqual(preview['count'],2)
  operation_id=str(uuid4());request=dict(operation_id=operation_id,format='json',content=content,preview_sha256=preview['preview_sha256']);code,created,_=self.request('POST',self.base+'/rules/import',request);self.assertEqual(code,200);self.assertEqual(created['created'],2)
  code,listing,_=self.request('GET',self.base+'/rules');self.assertEqual(code,200);self.assertEqual(len(listing['rules']),2)
  code,history,_=self.request('GET',self.base+'/rules/history');self.assertEqual(code,200);self.assertEqual([v['operation'] for v in history['history']],['import','import'])
  code,single,_=self.request('GET',self.base+'/rules/history/'+created['rules'][0]['id']);self.assertEqual(code,200);self.assertEqual(len(single['history']),1)
  code,replay,_=self.request('POST',self.base+'/rules/import',request);self.assertEqual(code,200);self.assertTrue(replay['idempotent']);self.assertEqual(replay['created'],0)
  code,bad,_=self.request('POST',self.base+'/rules/import-preview',dict(format='json',content=json.dumps([dict(scope='global',scope_id=None,kind='bad',text='x',enabled=True)])));self.assertEqual(code,200);self.assertFalse(bad['can_confirm'])
  conflict=json.dumps([dict(scope='book',scope_id=self.pid,kind='required',text='冲突文本',enabled=True),dict(scope='chapter',scope_id=self.cid,kind='forbidden',text='冲突文本',enabled=True)],ensure_ascii=False);code,preview,_=self.request('POST',self.base+'/rules/import-preview',dict(format='json',content=conflict));self.assertFalse(preview['can_confirm']);code,error,_=self.request('POST',self.base+'/rules/import',dict(operation_id=str(uuid4()),format='json',content=conflict,preview_sha256=preview['preview_sha256']));self.assertEqual(code,422)
if __name__=='__main__':unittest.main()
