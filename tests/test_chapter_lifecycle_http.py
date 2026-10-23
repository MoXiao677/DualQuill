from http.client import HTTPConnection
import base64,json,tempfile,threading,unittest
from pathlib import Path
from novel_writer.ui.server import create_server

class LifecycleHttpTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='lifecycle-http-');self.addCleanup(self.temp.cleanup);root=Path(self.temp.name)
  self.server=create_server(root/'fiction.sqlite3',port=0,provider_path=root/'fiction.dpapi');self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start();self.addCleanup(self.stop)
  code,state,_=self.request('POST','/api/projects',dict(title='生命周期HTTP'));self.pid=state['document']['project']['id'];code,state,_=self.request('POST','/api/projects/'+self.pid+'/actions',dict(action='add_chapter',fields=dict(title='第一章'),expected_revision=state['revision']));self.cid=state['document']['chapters'][0]['id'];self.base='/api/projects/'+self.pid
 def stop(self):self.server.shutdown();self.server.server_close();self.thread.join(2)
 def request(self,method,path,payload=None,*,token=True,raw=False):
  c=HTTPConnection('127.0.0.1',self.server.server_port,timeout=10);headers={'Content-Type':'application/json'}
  if token:headers['X-Novel-Token']=self.server.token
  try:c.request(method,path,json.dumps(payload) if payload is not None else None,headers);r=c.getresponse();data=r.read()
  finally:c.close()
  return r.status,(data if raw else json.loads(data)),dict(r.getheaders())
 def test_import_preview_commit_and_export_roundtrip(self):
  text='第1章 开端\r\n第一段😀\r\n第2节 转折\nSecond body\n';encoded=base64.b64encode(text.encode()).decode();body=dict(filename='小说.txt',content_base64=encoded,encoding='utf-8')
  self.assertEqual(self.request('POST',self.base+'/import/preview',body,token=False)[0],403);code,preview,_=self.request('POST',self.base+'/import/preview',body);self.assertEqual(code,200);self.assertEqual([v['title'] for v in preview['items']],['开端','转折'])
  state=self.server.service.get(self.pid);commit=dict(expected_revision=state['revision'],filename='小说.txt',content_base64=encoded,encoding='utf-8',items=preview['items'],preview_sha256=preview['preview_sha256'],confirmed=True);code,state,_=self.request('POST',self.base+'/import/commit',commit);self.assertEqual(code,200);self.assertEqual([v['content'] for v in state['document']['chapters'][1:]],['第一段😀\r\n','Second body\n'])
  code,exported,headers=self.request('GET',self.base+'/export?scope=book&format=md',raw=True);self.assertEqual(code,200);self.assertIn('## 第1章',exported.decode());self.assertIn('attachment',headers.get('Content-Disposition',''));self.assertIn('text/markdown',headers.get('Content-Type',''))
 def test_reorder_archive_restore_and_invalid_import(self):
  _,state,_=self.request('POST','/api/projects/'+self.pid+'/actions',dict(action='add_chapter',fields=dict(title='第二章'),expected_revision=self.server.service.get(self.pid)['revision']));second=state['document']['chapters'][1]['id'];rev=state['revision']
  code,state,_=self.request('POST','/api/projects/'+self.pid+'/actions',dict(action='move_chapter',fields=dict(chapter_id=second,direction='up',confirmed=True),expected_revision=rev));self.assertEqual(code,200);self.assertEqual([v['id'] for v in sorted(state['document']['chapters'],key=lambda c:c['number'])],[second,self.cid])
  code,state,headers=self.request('POST','/api/projects/'+self.pid+'/actions',dict(action='archive_chapter',fields=dict(chapter_id=self.cid,confirmed=True),expected_revision=state['revision']));self.assertEqual(code,200);self.assertTrue(any(v['chapter_id']==self.cid for v in state['chapter_lifecycle_events']))
  self.assertEqual(self.request('POST',self.base+'/import/preview',dict(filename='bad.pdf',content_base64=base64.b64encode(b'abc').decode(),encoding='utf-8'))[0],422)

if __name__=='__main__':unittest.main()
