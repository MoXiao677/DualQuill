"""C08 real random-loopback HTTP routes, not a real model provider."""
import time
import unittest
from uuid import uuid4
import test_materials_http as fixture


class HybridHTTPTests(unittest.TestCase):
    setUp=fixture.MaterialsHTTPTests.setUp
    stop=fixture.MaterialsHTTPTests.stop
    request=fixture.MaterialsHTTPTests.request
    revision=fixture.MaterialsHTTPTests.revision
    create=fixture.MaterialsHTTPTests.create
    rebuild=fixture.MaterialsHTTPTests.rebuild

    def test_hybrid_and_tag_routes_preserve_auth_and_exact_evidence(self):
        code,created=self.create('# 古城龙舟\n古城龙舟\n古城龙舟');self.assertEqual(code,201)
        mid=created['material']['id'];path=self.base+'/'+mid+'/suggest-tags';before=self.server.database_path.read_bytes()
        self.assertEqual(self.request('POST',path,{},token=False)[0],403)
        code,result=self.request('POST',path,{});self.assertEqual(code,200);self.assertEqual(result['suggestions'][0]['evidence'],'古城龙舟')
        self.assertEqual(self.server.database_path.read_bytes(),before);self.assertEqual(self.request('POST',path,{'auto_accept':True})[0],422)
        self.rebuild(mid,self.revision());payload=dict(query='古城 龙舟',chapter_id=self.chapter,mode='hybrid',scopes=['materials'],material_ids=[mid])
        code,result=self.request('POST',f'/api/projects/{self.pid}/search',payload);self.assertEqual(code,200)
        self.assertTrue(result['hits']);self.assertFalse(result['model_request_sent']);self.assertIn('excerpt',result['hits'][0]['selection'])
        self.assertEqual(self.request('POST',f'/api/projects/{self.pid}/search',dict(payload,remote_embeddings=True))[0],422)

    def test_async_index_poll_idempotence_and_crossbook_cancel(self):
        code,created=self.create('古城龙舟'*300);self.assertEqual(code,201);mid=created['material']['id']
        path=self.base+'/'+mid+'/index-jobs';request=dict(operation_id=str(uuid4()),expected_revision=self.revision())
        self.assertEqual(self.request('POST',path,request,token=False)[0],403)
        code,job=self.request('POST',path,request);self.assertEqual(code,202)
        self.assertEqual(self.request('POST',path,request)[1]['id'],job['id'])
        poll=self.base+'/index-jobs/'+job['id']
        deadline=time.monotonic()+4
        while job['status'] in ('running','cancelling') and time.monotonic()<deadline:
            time.sleep(.01);code,job=self.request('GET',poll);self.assertEqual(code,200)
        self.assertEqual(job['status'],'succeeded');self.assertGreater(job['result']['index_update']['rebuilt_chunks'],0)
        self.assertEqual(self.request('POST',poll+'/cancel',{})[1]['status'],'succeeded')
        self.assertEqual(self.request('POST',poll+'/cancel',{'status':'cancelled'})[0],422)
        other=self.server.service.create(title='其他虚构书')['document']['project']['id']
        self.assertEqual(self.request('GET',poll.replace(self.pid,other))[0],404)
        self.assertEqual(self.request('POST',poll.replace(self.pid,other)+'/cancel',{})[0],404)

    def test_new_ui_assets_and_capabilities_are_served(self):
        views=self.request('GET','/views.js',parse=False)[1].decode('utf-8');self.assertIn('name="mode"',views);self.assertIn('value="hybrid"',views)
        materials=self.request('GET','/materials.js',parse=False)[1].decode('utf-8');self.assertIn('material-index-cancel',materials);self.assertIn('suggest-tags',materials)
        caps=self.request('GET','/api/backups/capabilities')[1];self.assertIn(44,caps['workspace_versions'])
        caps=self.request('GET','/api/migrations/capabilities')[1];self.assertIn('backup_v44',caps['formats'])

if __name__=='__main__':unittest.main()
