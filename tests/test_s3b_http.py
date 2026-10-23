import http.client,json,sys,tempfile,threading,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src')]
from novel_writer.ui.server import create_server
FROZEN=json.loads((ROOT/'tests/fixtures/s3b_legacy_v1.json').read_text(encoding='utf8'))

class MemoryHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='novel-s3b-http-');self.addCleanup(self.temp.cleanup)
        self.db=Path(self.temp.name)/'fictional.sqlite3';self.db.write_bytes(bytes.fromhex(FROZEN['database_hex']))
        self.server=create_server(self.db,port=0,offline=True);self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True)
        self.thread.start();self.addCleanup(self.stop)
    def stop(self):self.server.shutdown();self.thread.join(3);self.server.server_close()
    def request(self,method,path,data=None,token=True):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_address[1],timeout=20)
        headers={'Content-Type':'application/json'}
        if token:headers['X-Novel-Token']=self.server.token
        try:
            conn.request(method,path,json.dumps(data) if data is not None else None,headers);r=conn.getresponse();return r.status,json.loads(r.read())
        finally:conn.close()
    def test_memory_list_and_historical_source_and_readonly_search_are_real_routes(self):
        code,records=self.request('GET','/api/projects/p1/memories');self.assertEqual(code,200);self.assertEqual(records,[])
        fields=dict(kind='event',title='事件',text='记忆检索关键词',position_chapter_id='p1-c5',confirmed=True,source={'kind':'chapter','entity_id':'p1-c5'})
        code,state=self.request('POST','/api/projects/p1/actions',dict(action='save_memory',fields=fields,expected_revision=1));self.assertEqual(code,200,state)
        identifier=state['memories'][0]['id'];code,source=self.request('GET',f'/api/projects/p1/memories/{identifier}/source')
        self.assertEqual(code,200,source);self.assertEqual(source['source']['workspace_revision'],1);self.assertIn('BODY_p1_5',json.dumps(source))
        before=self.db.read_bytes();code,found=self.request('POST','/api/projects/p1/search',dict(chapter_id='p1-c5',query='记忆检索关键词',scopes=['memories']))
        self.assertEqual(code,200,found);self.assertEqual(found['hits'][0]['locator']['memory_id'],identifier);self.assertEqual(self.db.read_bytes(),before)
    def test_cross_book_unknown_and_no_token_search_refused_without_changes(self):
        before=self.db.read_bytes()
        self.assertEqual(self.request('POST','/api/projects/p1/search',dict(chapter_id='p1-c5',query='x'),token=False)[0],403)
        self.assertEqual(self.request('POST','/api/projects/p1/search',dict(chapter_id='p2-c1',query='x'))[0],422)
        self.assertEqual(self.request('POST','/api/projects/p1/search',dict(chapter_id='p1-c5',query='x',draft='private'))[0],422)
        self.assertEqual(self.db.read_bytes(),before)

if __name__=='__main__':unittest.main()
