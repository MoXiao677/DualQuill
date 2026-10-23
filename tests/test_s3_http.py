"""S3只读预览HTTP与既有事务入口，虚构库/随机端口。"""
import http.client,json,sys,tempfile,threading,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'tests/fixtures'))
from s3_planning import create_planning_database
from novel_writer.ui.server import create_server

class S3HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='novel-s3-http-');self.addCleanup(self.temp.cleanup)
        self.db=Path(self.temp.name)/'fictional.sqlite3';create_planning_database(self.db)
        self.server=create_server(self.db,port=0,offline=True)
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start();self.addCleanup(self.stop)
    def stop(self):self.server.shutdown();self.thread.join(3);self.server.server_close()
    def request(self,data,token=True):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_address[1],timeout=10)
        headers={'Content-Type':'application/json'}
        if token:headers['X-Novel-Token']=self.server.token
        try:
            conn.request('POST','/api/projects/p1/context-preview',json.dumps(data),headers)
            response=conn.getresponse();return response.status,json.loads(response.read())
        finally:conn.close()
    def test_saved_preview_no_database_or_model_side_effect(self):
        before=self.db.read_bytes();code,result=self.request({'chapter_id':'p1-c5'})
        self.assertEqual(code,200,result);self.assertEqual(result['revision'],1)
        self.assertFalse(result['model_request_sent']);self.assertEqual(self.db.read_bytes(),before)
        self.assertNotIn('FUTURE_',json.dumps(result));self.assertIsNone(self.server._backups)
    def test_preview_requires_token_and_rejects_cross_book_or_draft_payload(self):
        self.assertEqual(self.request({'chapter_id':'p1-c5'},token=False)[0],403)
        for data in ({'chapter_id':'p2-c1'},{'chapter_id':'p1-c5','draft':'PRIVATE_UNSAVED'}):
            code,result=self.request(data);self.assertEqual(code,422,result);self.assertNotIn('PRIVATE_UNSAVED',json.dumps(result))

if __name__=='__main__':unittest.main()
