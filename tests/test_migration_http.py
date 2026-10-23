"""S2-C真实本机HTTP；只用虚构库和随机端口。"""
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src')); sys.path.insert(0,str(ROOT/'tests/fixtures'))
from s2_a_samples import create_fixture_database
from s2_b_samples import build_runtime_dataset
from novel_writer.ui.server import create_server, Handler
from novel_writer.storage.sqlite_repository import SQLiteRepository


class MigrationHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='novel-s2-c-http-'); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.database = self.root/'fictional.sqlite3'
        create_fixture_database(self.database,build_runtime_dataset())
        self.server = create_server(self.database,port=0,offline=True)
        self.thread = threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True)
        self.thread.start(); self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown(); self.thread.join(3); self.server.server_close()

    def request(self,method,path,body=None,*,token=True,headers=None,kind='application/json'):
        conn = http.client.HTTPConnection('127.0.0.1',self.server.server_address[1],timeout=30)
        actual = {'Content-Type':kind}
        if token: actual['X-Novel-Token']=self.server.token
        actual.update(headers or {})
        try:
            conn.request(method,path,body=body,headers=actual)
            res=conn.getresponse(); data=res.read()
            return res.status,json.loads(data)
        finally: conn.close()

    def copy(self,identity=None):
        return self.request('POST','/api/migrations/copy',json.dumps({'operation_id':identity or str(uuid4()),'project_id':'s2-a-project-one'}))

    def test_capabilities_are_read_only_and_separate_from_new_directory_restore(self):
        code,value=self.request('GET','/api/migrations/capabilities')
        self.assertEqual(code,200); self.assertTrue(value['new_projects']); self.assertTrue(value['legacy_json'])
        self.assertIn('backup_v22',value['formats']);self.assertLess(value['formats'].index('backup_v21'),value['formats'].index('backup_v22'))
        self.assertIsNone(self.server._backups)
        self.assertFalse(self.request('GET','/api/backups/capabilities')[1]['merge_restore'])

    def test_copy_creates_one_new_project_and_reuses_global_skills(self):
        identity=str(uuid4()); code,result=self.copy(identity)
        self.assertEqual(code,201,result); self.assertTrue(result['verified'])
        self.assertEqual(len(self.server.service.list_projects()),3)
        self.assertTrue(all(s['action']=='reused' for s in result['skills']))
        self.assertEqual(self.copy(identity)[1]['state'],'already_present')
        self.assertEqual(len(self.server.service.list_projects()),3)
        code,status=self.request('GET','/api/migrations/operations/'+identity)
        self.assertEqual(code,200,status); self.assertEqual(status['state'],'already_present')

    def test_legacy_upload_reports_missing_scopes_and_is_idempotent(self):
        identity=str(uuid4()); headers={'X-Novel-Migration-Operation':identity}
        text=json.dumps({'schema_version':1,'project':{'title':'HTTP虚构小说'}}).encode()
        code,result=self.request('POST','/api/migrations/import',text,kind='application/octet-stream',headers=headers)
        self.assertEqual(code,201,result); self.assertIn('skills',result['missing_scopes'])
        self.assertEqual(self.request('POST','/api/migrations/import',text,kind='application/octet-stream',headers=headers)[1]['state'],'already_present')
        changed=b'{"schema_version":1,"project":{"title":"changed"}}'
        self.assertEqual(self.request('POST','/api/migrations/import',changed,kind='application/octet-stream',headers=headers)[0],422)

    def test_token_origin_status_and_upload_protection(self):
        self.assertEqual(self.request('POST','/api/migrations/copy',b'{}',token=False)[0],403)
        self.assertEqual(self.request('POST','/api/migrations/import',b'fake',token=False,kind='application/octet-stream')[0],403)
        self.assertEqual(self.request('GET','/api/migrations/operations/'+str(uuid4()),token=False)[0],403)
        self.assertEqual(self.request('POST','/api/migrations/copy',b'{}',headers={'Origin':'https://outside.invalid'})[0],403)

    def test_origin_refusal_delayed_two_byte_body_preserves_403(self):
        written = threading.Event(); consumed = threading.Event(); closed = threading.Event()
        events = []; event_lock = threading.Lock(); readers = []
        def record(name, **details):
            with event_lock:
                events.append(dict(sequence=len(events)+1,event=name,thread=threading.get_ident(),**details))
        class ObservedReader:
            def __init__(self, original): self.original=original; self.body=bytearray()
            def read1(self, size):
                chunk=self.original.read1(size)
                self.body.extend(chunk)
                if len(self.body)==2:
                    record('body_consumed',body=bytes(self.body).decode('ascii'),bytes=len(self.body))
                    consumed.set()
                return chunk
            def __getattr__(self,name): return getattr(self.original,name)
        original_setup = Handler.setup
        original_send = Handler.send_body
        original_close = self.server.shutdown_request
        def setup(handler):
            original_setup(handler)
            handler.rfile=ObservedReader(handler.rfile); readers.append(handler.rfile)
        def send(handler, status, *args, **kwargs):
            result = original_send(handler, status, *args, **kwargs)
            record('response_written',status=status)
            written.set()
            return result
        def close(request):
            original_close(request)
            record('socket_closed'); closed.set()
        before = self.database.read_bytes()
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_address[1], timeout=2)
        try:
            with patch.object(Handler, 'setup', setup), patch.object(Handler, 'send_body', send), \
                    patch.object(self.server, 'shutdown_request', close):
                conn.putrequest('POST', '/api/migrations/copy')
                for name,value in {'Content-Type':'application/json','Content-Length':'2',
                    'Origin':'https://outside.invalid','X-Novel-Token':self.server.token}.items():
                    conn.putheader(name,value)
                started=time.monotonic(); conn.endheaders()
                self.assertTrue(written.wait(1))
                time.sleep(.03)  # 真实网络分段：正文在拒绝响应写出后到达。
                record('client_body_begin'); conn.send(b'{}')
                response = conn.getresponse()
                self.assertEqual(response.status,403)
                self.assertIn('拒绝',json.loads(response.read())['error'])
                self.assertTrue(consumed.wait(1))
                self.assertTrue(closed.wait(1))
                self.assertLess(time.monotonic()-started,1)
        finally:
            conn.close()
            print('origin-refusal-events '+json.dumps(events),flush=True)
        self.assertEqual([event['event'] for event in events],
                         ['response_written','client_body_begin','body_consumed','socket_closed'])
        self.assertEqual([event['sequence'] for event in events],[1,2,3,4])
        self.assertEqual(len({event['thread'] for event in events if event['event']!='client_body_begin'}),1)
        self.assertEqual([bytes(reader.body) for reader in readers],[b'{}'])
        self.assertIsNone(self.server._backups)
        self.assertEqual(self.database.read_bytes(),before)
        self.assertEqual(self.request('GET','/api/projects')[0],200)

    def test_rejected_body_drain_has_time_and_byte_bounds(self):
        # 记录实际读取字节；不替换403、权限判断或业务入口。
        class CountedReader:
            def __init__(self, original): self.original=original; self.bytes=0
            def read1(self, size):
                chunk=self.original.read1(size); self.bytes+=len(chunk); return chunk
            def __getattr__(self,name): return getattr(self.original,name)
        original_setup=Handler.setup
        for path,status,mode in [(path,status,mode) for path,status in
                (('/api/migrations/copy',403),('/api/migrations/import',422)) for mode in ('silent','drip','large')]:
            with self.subTest(mode=mode,path=path):
                readers=[];closed=threading.Event();original_close=self.server.shutdown_request
                def setup(handler):
                    original_setup(handler);handler.rfile=CountedReader(handler.rfile);readers.append(handler.rfile)
                def close(request): original_close(request);closed.set()
                before=self.database.read_bytes()
                conn=http.client.HTTPConnection('127.0.0.1',self.server.server_address[1],timeout=2)
                try:
                    with patch.object(Handler,'setup',setup),patch.object(self.server,'shutdown_request',close):
                        conn.putrequest('POST',path)
                        conn.putheader('Content-Type','application/json' if status==403 else 'application/octet-stream')
                        conn.putheader('Content-Length','1000000000' if mode=='large' else '4096')
                        if status==403:conn.putheader('Origin','https://outside.invalid')
                        else:conn.putheader('X-Novel-Token',self.server.token)
                        conn.endheaders();started=time.monotonic()
                        # HTTPResponse直接读取，保留客户端socket供后续真实正文发送；
                        # HTTPConnection.getresponse会因HTTP/1.0提前释放其socket。
                        response=http.client.HTTPResponse(conn.sock);response.begin()
                        self.assertEqual(response.status,status);response.read();response.close()
                        if mode=='drip':
                            for _ in range(2):
                                conn.send(b'x');time.sleep(.03)
                        elif mode=='large':conn.send(b'x'*4096)
                        self.assertTrue(closed.wait(1),'拒绝请求不能等待完整恶意正文')
                        self.assertLess(time.monotonic()-started,1)
                finally:conn.close()
                self.assertTrue(readers)
                self.assertLessEqual(sum(reader.bytes for reader in readers),4096)
                if status==403:self.assertIsNone(self.server._backups)
                else:
                    self.assertFalse(self.server._backups.active_migrations)
                    self.assertFalse(self.server._backups.active_restores)
                self.assertEqual(self.database.read_bytes(),before)
        self.assertEqual(self.request('GET','/api/projects')[0],200)

    def test_early_error_paths_preserve_response_with_late_private_body(self):
        body=b'secret-fictional-text'
        cases=[
            ('migration-missing-id','/api/migrations/import','application/octet-stream',{},True,422),
            ('backup-invalid-id','/api/backups/restore','application/octet-stream',{'X-Novel-Backup-Operation':'invalid'},True,422),
            ('backup-type','/api/backups/restore','text/plain',{},True,422),
            ('missing-route','/api/migrations/unknown','application/json',{},True,404),
            ('origin','/api/migrations/copy','application/json',{'Origin':'https://outside.invalid'},True,403),
            ('host','/api/migrations/copy','application/json',{'Host':'outside.invalid'},True,403),
            ('token','/api/migrations/copy','application/json',{},False,403)]
        for label,path,kind,headers,token,status in cases:
            with self.subTest(case=label):
                written=threading.Event();closed=threading.Event();events=[];lock=threading.Lock();bodies=[]
                def record(name,**details):
                    with lock:events.append(dict(sequence=len(events)+1,event=name,**details))
                class Reader:
                    def __init__(self,original):self.original=original;self.body=bytearray()
                    def read1(self,size):
                        chunk=self.original.read1(size);self.body.extend(chunk)
                        if len(self.body)==len(body):record('body_consumed',bytes=len(self.body))
                        return chunk
                    def __getattr__(self,name):return getattr(self.original,name)
                original_setup=Handler.setup;original_send=Handler.send_body;original_close=self.server.shutdown_request
                def setup(handler):original_setup(handler);handler.rfile=Reader(handler.rfile);bodies.append(handler.rfile)
                def send(handler,code,*args,**kwargs):
                    result=original_send(handler,code,*args,**kwargs);record('response_written',status=code);written.set();return result
                def close(request):original_close(request);record('socket_closed');closed.set()
                before=self.database.read_bytes();conn=http.client.HTTPConnection('127.0.0.1',self.server.server_address[1],timeout=2)
                try:
                    with patch.object(Handler,'setup',setup),patch.object(Handler,'send_body',send),patch.object(self.server,'shutdown_request',close):
                        conn.putrequest('POST',path,skip_host=True)
                        actual={'Host':f'127.0.0.1:{self.server.server_address[1]}','Content-Type':kind,'Content-Length':str(len(body)),**headers}
                        if token:actual['X-Novel-Token']=self.server.token
                        for key,value in actual.items():conn.putheader(key,value)
                        started=time.monotonic();conn.endheaders();self.assertTrue(written.wait(1));time.sleep(.03)
                        record('client_body_begin');conn.send(body)
                        response=conn.getresponse();self.assertEqual(response.status,status)
                        payload=response.read();self.assertNotIn(body,payload);self.assertIn('error',json.loads(payload))
                        self.assertTrue(closed.wait(1));self.assertLess(time.monotonic()-started,1)
                finally:
                    conn.close();print('early-error-events '+json.dumps(dict(case=label,events=events)),flush=True)
                self.assertEqual([e['event'] for e in events],['response_written','client_body_begin','body_consumed','socket_closed'])
                self.assertEqual([bytes(reader.body) for reader in bodies],[body])
                self.assertEqual(self.database.read_bytes(),before)
                if self.server._backups is not None:
                    self.assertFalse(self.server._backups.active_migrations)
                    self.assertFalse(self.server._backups.active_restores)
        self.assertEqual(self.request('GET','/api/projects')[0],200)
        self.assertEqual(self.copy()[0],201)

    def test_fully_consumed_bodies_are_not_read_again_after_response(self):
        for label,path,body,headers,kind in (
            ('json','/api/projects',b'{',{},'application/json'),
            ('copy-json','/api/migrations/copy',b'{',{},'application/json'),
            ('backup-preflight','/api/backups/restore',b'secret-fictional-text',{'X-Novel-Backup-Operation':str(uuid4())},'application/octet-stream')):
            with self.subTest(case=label):
                response_written=threading.Event();closed=threading.Event();reads=[]
                class Reader:
                    def __init__(self,original):self.original=original
                    def read(self,size=-1):
                        after=response_written.is_set();chunk=self.original.read(size);reads.append((after,len(chunk)));return chunk
                    def read1(self,size=-1):
                        after=response_written.is_set();chunk=self.original.read1(size);reads.append((after,len(chunk)));return chunk
                    def __getattr__(self,name):return getattr(self.original,name)
                original_setup=Handler.setup;original_send=Handler.send_body;original_close=self.server.shutdown_request
                def setup(handler):original_setup(handler);handler.rfile=Reader(handler.rfile)
                def send(handler,code,*args,**kwargs):
                    result=original_send(handler,code,*args,**kwargs);response_written.set();return result
                def close(request):original_close(request);closed.set()
                before=self.database.read_bytes()
                with patch.object(Handler,'setup',setup),patch.object(Handler,'send_body',send),patch.object(self.server,'shutdown_request',close):
                    code,payload=self.request('POST',path,body,headers=headers,kind=kind)
                    self.assertEqual(code,422);self.assertNotIn('secret-fictional-text',json.dumps(payload))
                    self.assertTrue(closed.wait(1))
                self.assertEqual(sum(size for _,size in reads),len(body))
                self.assertTrue(reads);self.assertFalse(any(after for after,_ in reads),'已读完正文不得在响应后再读/等待')
                self.assertEqual(self.database.read_bytes(),before)

    def test_unknown_paths_missing_identity_bad_json_and_private_errors(self):
        before=len(self.server.service.list_projects())
        self.assertEqual(self.request('POST','/api/migrations/copy',b'{"operation_id":"x","project_id":"x","path":"data"}')[0],422)
        self.assertEqual(self.request('POST','/api/migrations/copy',b'{"operation_id":"x","operation_id":"y"}')[0],422)
        code,error=self.request('POST','/api/migrations/import',b'secret-fictional-text',kind='application/octet-stream')
        self.assertEqual(code,422); self.assertNotIn('secret-fictional-text',json.dumps(error))
        self.assertEqual(self.request('POST','/api/migrations/unknown',b'{}')[0],404)
        self.assertEqual(self.request('GET','/api/migrations/operations/'+str(uuid4()))[0],404)
        self.assertEqual(len(self.server.service.list_projects()),before)

    def test_uploaded_sqlite_uses_contents_and_keeps_existing_target(self):
        source=self.root/'source.bin'; create_fixture_database(source,build_runtime_dataset())
        before=source.read_bytes(); identity=str(uuid4())
        code,result=self.request('POST','/api/migrations/import',before,kind='application/octet-stream',headers={'X-Novel-Migration-Operation':identity})
        self.assertEqual(code,201,result); self.assertEqual(result['source_format'],'sqlite_v1')
        self.assertEqual(len(self.server.service.list_projects()),4)
        self.assertEqual(SQLiteRepository(self.database).get('s2-a-project-one')['revision'],3)
        self.assertEqual(source.read_bytes(),before)

    def test_cancel_unknown_and_completed_do_not_claim_rollback(self):
        identity=str(uuid4())
        self.assertEqual(self.request('POST','/api/migrations/operations/'+identity+'/cancel',b'{}')[0],404)
        self.assertEqual(self.copy(identity)[0],201)
        code,result=self.request('POST','/api/migrations/operations/'+identity+'/cancel',b'{}')
        self.assertEqual(code,200,result); self.assertEqual(result['state'],'already_present')
        self.assertFalse(result['cancel_requested'])


if __name__=='__main__': unittest.main()
