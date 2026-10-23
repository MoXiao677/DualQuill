"""本地资料 HTTP 入口、会话令牌、冲突与静态页面边界。"""
from http.client import HTTPConnection
import json,sys,tempfile,threading,unittest
from pathlib import Path
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from novel_writer.ui.server import create_server


class MaterialsHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='materials-http-');self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);self.server=create_server(root/'fiction.sqlite3',port=0,provider_path=root/'fake.dpapi',offline=True)
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start();self.addCleanup(self.stop)
        state=self.server.service.create(title='HTTP资料虚构测试');self.pid=state['document']['project']['id']
        state=self.server.service.execute(self.pid,'add_chapter',dict(title='第一章'),expected_revision=state['revision'])
        self.chapter=state['document']['chapters'][0]['id'];self.base=f'/api/projects/{self.pid}/materials'
    def stop(self):self.server.shutdown();self.server.server_close();self.thread.join(2)
    def request(self,method,path,payload=None,token=True,parse=True):
        connection=HTTPConnection('127.0.0.1',self.server.server_port,timeout=10);headers={'Content-Type':'application/json'}
        if token:headers['X-Novel-Token']=self.server.token
        try:
            connection.request(method,path,json.dumps(payload) if payload is not None else None,headers)
            response=connection.getresponse();body=response.read()
            return response.status,(json.loads(body) if parse and body else body)
        finally:connection.close()
    def revision(self):return self.server.service.get(self.pid)['revision']
    def create(self,text='资料 KEYWORD',**values):
        payload=dict(operation_id=str(uuid4()),expected_revision=self.revision(),title='资料',format='txt',tags=[],text=text);payload.update(values)
        return self.request('POST',self.base,payload)
    def rebuild(self,material_id,revision):
        return self.request('POST',f'{self.base}/{material_id}/rebuild',dict(operation_id=str(uuid4()),expected_revision=revision))

    def test_create_read_update_archive_restore_and_conflicts(self):
        self.assertEqual(self.request('GET',self.base)[0],200)
        self.assertEqual(self.request('POST',self.base,dict(operation_id=str(uuid4()),expected_revision=self.revision(),title='x',format='txt',tags=[],text='x'),token=False)[0],403)
        code,created=self.create('第一版 KEYWORD',title=' HTTP资料 ',tags=['a'])
        self.assertEqual(code,201);material=created['material'];self.assertEqual(material['title'],'HTTP资料');self.assertEqual(material['index_status'],'missing')
        material_id=material['id'];self.assertEqual(self.request('GET',self.base)[0],200);self.assertEqual(self.request('GET',f'{self.base}/{material_id}')[0],200)
        version_id=material['current_version_id'];code,version=self.request('GET',f'{self.base}/{material_id}/versions/{version_id}');self.assertEqual(code,200);self.assertEqual(version['version_number'],1)
        code,rebuilt=self.rebuild(material_id,created['revision']);self.assertEqual(code,200);self.assertEqual(rebuilt['material']['index_status'],'current')
        update=dict(operation_id=str(uuid4()),expected_revision=rebuilt['revision'],title='HTTP资料',format='md',tags=['a','b'],note='第二版',text='第二版 KEYWORD')
        code,updated=self.request('POST',f'{self.base}/{material_id}/update',update);self.assertEqual(code,200);self.assertEqual(updated['material']['version_count'],2);self.assertEqual(updated['material']['index_status'],'stale')
        self.assertEqual(self.request('POST',f'{self.base}/{material_id}/archive',dict(operation_id=str(uuid4()),expected_revision=created['revision']))[0],409)
        code,archived=self.request('POST',f'{self.base}/{material_id}/archive',dict(operation_id=str(uuid4()),expected_revision=updated['revision']));self.assertEqual(code,200);self.assertTrue(archived['material']['archived'])
        self.assertEqual(self.request('POST',f'{self.base}/{material_id}/update',dict(update,operation_id=str(uuid4()),expected_revision=archived['revision']))[0],422)
        self.assertEqual(self.request('POST',f'{self.base}/{material_id}/rebuild',dict(operation_id=str(uuid4()),expected_revision=archived['revision']))[0],422)
        code,restored=self.request('POST',f'{self.base}/{material_id}/restore',dict(operation_id=str(uuid4()),expected_revision=archived['revision']));self.assertEqual(code,200);self.assertFalse(restored['material']['archived'])
        code,allr=self.request('POST',f'{self.base}/rebuild-all',dict(operation_id=str(uuid4()),expected_revision=restored['revision']));self.assertEqual(code,200);self.assertEqual(allr['rebuilt_material_ids'],[material_id])
        listing=self.request('GET',self.base)[1];self.assertEqual([value['archived'] for value in listing['materials']],[False])
        self.assertEqual(self.request('GET',f'{self.base}/{uuid4()}')[0],404)

    def test_search_requires_explicit_ids_and_rejects_archived(self):
        code,created=self.create('检索 KEYWORD');self.assertEqual(code,201);material=created['material'];self.rebuild(material['id'],created['revision'])
        payload=dict(query='KEYWORD',chapter_id=self.chapter,scopes=['materials'],material_ids=[material['id']])
        code,result=self.request('POST',f'/api/projects/{self.pid}/search',payload);self.assertEqual(code,200);self.assertEqual(len(result['hits']),1)
        self.assertEqual(result['hits'][0]['material_id'],material['id']);self.assertEqual(result['hits'][0]['start'],3);self.assertEqual(result['hits'][0]['end'],10)
        self.assertEqual(self.request('POST',f'/api/projects/{self.pid}/search',dict(payload,material_ids=[]))[0],422)
        archived=self.request('POST',f'{self.base}/{material["id"]}/archive',dict(operation_id=str(uuid4()),expected_revision=self.revision()))[1]
        self.assertEqual(self.request('POST',f'/api/projects/{self.pid}/search',payload)[0],422)
        self.assertTrue(archived['material']['archived'])

    def test_invalid_payloads_unknown_material_and_bad_revision(self):
        self.assertEqual(self.create(text='x',unknown=True)[0],422)
        self.assertEqual(self.request('POST',self.base,dict(operation_id=str(uuid4()),expected_revision=self.revision(),title='x',format='txt',tags=[],data_base64='***'))[0],422)
        self.assertEqual(self.request('POST',self.base,dict(operation_id='not-a-uuid',expected_revision=self.revision(),title='x',format='txt',tags=[],text='x'))[0],422)
        self.assertEqual(self.request('POST',self.base,dict(operation_id=str(uuid4()),expected_revision=0,title='x',format='txt',tags=[],text='x'))[0],422)
        code,created=self.create('幂等 KEYWORD');payload=dict(operation_id=str(uuid4()),expected_revision=self.revision(),title='幂等',format='txt',tags=[],text='原样')
        self.assertEqual(self.request('POST',self.base,payload)[0],201)
        self.assertEqual(self.request('POST',self.base,dict(payload,text='改动'))[0],422)
        self.assertEqual(self.request('POST',f'{self.base}/{uuid4()}/update',dict(payload,operation_id=str(uuid4())))[0],404)

    def test_capabilities_static_assets_and_explicit_retrieval_ui(self):
        backups=self.request('GET','/api/backups/capabilities')[1];self.assertIn(26,backups['workspace_versions']);self.assertIn(27,backups['workspace_versions']);self.assertIn(26,backups['backup_format_versions']);self.assertIn(27,backups['backup_format_versions'])
        migrations=self.request('GET','/api/migrations/capabilities')[1];self.assertIn('backup_v26',migrations['formats'])
        code,materials= self.request('GET','/materials.js',parse=False);self.assertEqual(code,200);text=materials.decode('utf8')
        self.assertIn('renderMaterials',text);self.assertIn('bindMaterials',text);self.assertIn('不是语义检索',text)
        app=self.request('GET','/app.js',parse=False)[1].decode('utf8');self.assertIn("from './materials.js'",app);self.assertIn("['materials','本地资料']",app)
        views=self.request('GET','/views.js',parse=False)[1].decode('utf8');self.assertIn('name="material_ids"',views);self.assertIn('不是语义检索',views)
        security=(ROOT/'desktop/security.cjs').read_text(encoding='utf8');self.assertIn("'/materials.js':'materials.js'",security)


if __name__=='__main__':unittest.main()
