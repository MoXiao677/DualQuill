"""受控HTTP文件交接，所有数据库与恢复目录都属于虚构临时目录。"""
import http.client
import json
from pathlib import Path
from uuid import uuid4
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import sqlite3
from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(ROOT/'tests/fixtures'))
from s2_a_samples import build_dataset, create_fixture_database
from novel_writer.ui.server import create_server


class BackupHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='novel-s2-b-http-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root/'fictional.sqlite3'
        create_fixture_database(self.database, build_dataset())
        self.server = create_server(self.database, port=0, offline=True)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.thread.join(3)
        self.server.server_close()

    def request(self, method, endpoint, body=None, *, token=True, content_type='application/json', headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_address[1], timeout=30)
        actual = {'Content-Type': content_type}
        if token:
            actual['X-Novel-Token'] = self.server.token
        actual.update(headers or {})
        try:
            connection.request(method, endpoint, body=body, headers=actual)
            response = connection.getresponse()
            mime = response.getheader('Content-Type')
            data = response.read()
            return response.status, json.loads(data) if 'application/json' in mime else data
        finally:
            connection.close()

    def test_complete_download_and_independent_upload_restore(self):
        status, result = self.request('POST', '/api/backups/export', b'{}')
        self.assertEqual(status, 201)
        status, archive = self.request('GET', result['download_url'])
        self.assertEqual(status, 200)
        self.assertTrue(archive.startswith(b'PK'))
        status, restored = self.request('POST', '/api/backups/restore', archive, content_type='application/octet-stream')
        self.assertEqual(status, 201)
        self.assertTrue(restored['verified'])
        path = Path(restored['database_path'])
        self.assertTrue(path.is_file())
        self.assertNotEqual(path.resolve(), self.database.resolve())
        self.assertEqual(self.server.database_path, self.database)
        self.assertEqual(self.request('GET', '/api/projects/s2-a-project-one')[1]['revision'], 3)
        self.assertEqual(self.request('GET', result['download_url'])[0], 404)

    def test_backup_requires_token_and_same_origin(self):
        self.assertEqual(self.request('POST','/api/backups/export', b'{}', token=False)[0], 403)
        self.assertEqual(self.request('POST','/api/backups/export', b'{}', headers={'Origin':'https://outside.invalid'})[0], 403)
        self.assertEqual(self.request('POST','/api/backups/restore', b'fake', token=False, content_type='application/octet-stream')[0], 403)

    def test_capability_read_does_not_initialize_transfer_files(self):
        self.assertIsNone(self.server._backups)
        status,result=self.request('GET','/api/backups/capabilities')
        self.assertEqual(status,200);self.assertEqual(result['backup_format_version'],51)
        self.assertIn(51,result['backup_format_versions']);self.assertIn(22,result['workspace_versions'])
        self.assertTrue(result['independent_restore']);self.assertFalse(result['merge_restore'])
        self.assertIsNone(self.server._backups)

    def test_no_arbitrary_path_parameters(self):
        self.assertEqual(self.request('POST','/api/backups/export', b'{"path":"elsewhere"}')[0], 422)
        self.assertEqual(self.request('POST','/api/backups/restore', b'{}')[0], 422)
        self.assertEqual(self.request('GET','/api/backups/download/../../data/novels.sqlite3')[0], 404)

    def test_bad_upload_leaves_no_restored_database(self):
        self.assertEqual(self.request('POST','/api/backups/restore', b'notzip', content_type='application/octet-stream')[0], 422)
        self.assertEqual(list(self.root.glob('restored-backup-*/novels.sqlite3')), [])

    def test_upload_retry_has_recoverable_identity_and_does_not_create_second_target(self):
        status,result=self.request('POST','/api/backups/export',b'{}')
        self.assertEqual(status,201)
        archive=self.request('GET',result['download_url'])[1]
        operation=str(uuid4());headers={'X-Novel-Backup-Operation':operation}
        status,first=self.request('POST','/api/backups/restore',archive,content_type='application/octet-stream',headers=headers)
        self.assertEqual(status,201)
        status,retry=self.request('POST','/api/backups/restore',archive,content_type='application/octet-stream',headers=headers)
        self.assertEqual(status,201)
        self.assertEqual(first['database_path'],retry['database_path'])
        self.assertEqual(len(list(self.root.glob('restored-backup-*/novels.sqlite3'))),1)
        status,known=self.request('GET','/api/backups/operations/'+operation)
        self.assertEqual(status,200);self.assertEqual(known['database_path'],first['database_path'])

    def archive(self):
        result=self.request('POST','/api/backups/export',b'{}')[1]
        return self.request('GET',result['download_url'])[1]

    def test_operation_identity_survives_restart_and_rejects_changed_package(self):
        archive=self.archive(); operation=str(uuid4());headers={'X-Novel-Backup-Operation':operation}
        first=self.request('POST','/api/backups/restore',archive,content_type='application/octet-stream',headers=headers)[1]
        self.stop()
        self.server=create_server(self.database,port=0,offline=True)
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True)
        self.thread.start()
        status,known=self.request('GET','/api/backups/operations/'+operation)
        self.assertEqual(status,200);self.assertEqual(known['database_path'],first['database_path'])
        self.assertEqual(known['state'],'completed')
        different=self.archive()
        self.assertNotEqual(different,archive)
        self.assertEqual(self.request('POST','/api/backups/restore',different,content_type='application/octet-stream',headers=headers)[0],422)
        self.assertEqual(len(list(self.root.glob('restored-backup-*/novels.sqlite3'))),1)

    def test_operation_receipt_failure_does_not_publish_target(self):
        archive=self.archive()
        with patch('novel_writer.application.backup_identity._write_receipt',side_effect=OSError('fictional receipt failure')):
            self.assertEqual(self.request('POST','/api/backups/restore',archive,content_type='application/octet-stream')[0],422)
        self.assertEqual(list(self.root.glob('restored-backup-*/novels.sqlite3')),[])

    def test_restore_receipt_reports_drafts_dropped_for_unknown_project(self):
        from novel_writer.application import backup_identity
        package=self.root/'receipt-probe.nwbak';package.write_bytes(b'fictional package')
        draft={'project_id':'missing-project','document_key':'["missing-project","writing","missing-chapter","body"]',
               'base_revision':4,'values':{'content':'unmapped'},'position':{},'updated_at':'2026-10-22T00:00:00+00:00'}
        manifest={'backup_id':str(uuid4())}
        class Temporary:
            def __init__(self,*args,**kwargs):self.path=self.root/'receipt-stage'
            def __enter__(self):self.path.mkdir();return str(self.path)
            def __exit__(self,*args):return False
        Temporary.root=self.root
        with patch.object(backup_identity,'OwnedTemporaryDirectory',Temporary), \
             patch.object(backup_identity,'_unpack',return_value=(manifest,self.database,{},[draft])), \
             patch.object(backup_identity,'_write_receipt') as write_receipt:
            result=backup_identity.prepare_operation(self.database,str(uuid4()),package)
        self.assertEqual(result,{'operation_id':write_receipt.call_args.args[1]['operation_id'],'state':'target_absent','verified':False})
        self.assertEqual(write_receipt.call_args.args[1]['drafts_restored'],[])
        self.assertEqual(write_receipt.call_args.args[1]['drafts_dropped'],[
            {'document_key':draft['document_key'],'reason':'missing_mapping'}])

    def test_status_requires_token_and_edited_target_is_never_reused(self):
        archive=self.archive();operation=str(uuid4());headers={'X-Novel-Backup-Operation':operation}
        first=self.request('POST','/api/backups/restore',archive,content_type='application/octet-stream',headers=headers)[1]
        self.assertEqual(self.request('GET','/api/backups/operations/'+operation,token=False)[0],403)
        with closing(sqlite3.connect(first['database_path'])) as connection:
            connection.execute("UPDATE skills SET description='独立目标已编辑'");connection.commit()
        self.assertEqual(self.request('POST','/api/backups/restore',archive,content_type='application/octet-stream',headers=headers)[0],422)
        with closing(sqlite3.connect(first['database_path'])) as connection:
            self.assertEqual(connection.execute('SELECT description FROM skills LIMIT 1').fetchone()[0],'独立目标已编辑')

    def test_cancel_during_transaction_has_no_target_and_completed_cancel_reports_completion(self):
        from novel_writer.application import backups
        archive=self.archive();operation=str(uuid4());headers={'X-Novel-Backup-Operation':operation}
        entered=threading.Event();release=threading.Event();result=[]
        original=backups._insert_row
        def wait(connection,table,row):
            entered.set();release.wait(10);original(connection,table,row)
        with patch.object(backups,'_insert_row',side_effect=wait):
            worker=threading.Thread(target=lambda:result.append(self.request('POST','/api/backups/restore',archive,content_type='application/octet-stream',headers=headers)))
            worker.start()
            try:
                self.assertTrue(entered.wait(10))
                status,response=self.request('POST','/api/backups/operations/'+operation+'/cancel',b'{}')
                self.assertEqual(status,200);self.assertTrue(response['cancel_requested'])
            finally:
                release.set();worker.join(15)
        self.assertEqual(result[0][0],422);self.assertEqual(result[0][1]['code'],'cancelled')
        self.assertEqual(list(self.root.glob('restored-backup-*/novels.sqlite3')),[])
        first=self.request('POST','/api/backups/restore',archive,content_type='application/octet-stream',headers=headers)[1]
        status,response=self.request('POST','/api/backups/operations/'+operation+'/cancel',b'{}')
        self.assertEqual(status,200);self.assertFalse(response['cancel_requested'])
        self.assertEqual(response['state'],'completed');self.assertEqual(response['database_path'],first['database_path'])

    def test_response_loss_can_query_completed_target_without_second_restore(self):
        from novel_writer.ui.server import Handler
        archive=self.archive();operation=str(uuid4());headers={'X-Novel-Backup-Operation':operation}
        original=Handler.send_json
        def lost(handler,status,value,**kwargs):
            if handler.path=='/api/backups/restore':
                raise BrokenPipeError('fictional response loss')
            return original(handler,status,value,**kwargs)
        with patch.object(Handler,'send_json',new=lost):
            with self.assertRaises(http.client.RemoteDisconnected):
                self.request('POST','/api/backups/restore',archive,content_type='application/octet-stream',headers=headers)
        status,result=self.request('GET','/api/backups/operations/'+operation)
        self.assertEqual(status,200);self.assertEqual(result['state'],'completed')
        self.assertTrue(Path(result['database_path']).is_file())
        retry=self.request('POST','/api/backups/restore',archive,content_type='application/octet-stream',headers=headers)[1]
        self.assertEqual(retry['database_path'],result['database_path'])

    def test_slow_active_download_still_counts_against_four_file_quota(self):
        from types import SimpleNamespace
        from novel_writer.application.backups import BackupError
        transfers=self.server.backups
        tickets=[transfers.export()['download_url'].split('/')[-1] for _ in range(4)]
        entered=threading.Event();release=threading.Event()
        class Writer:
            def write(self,data):
                entered.set();release.wait(10);return len(data)
        handler=SimpleNamespace(connection=SimpleNamespace(settimeout=lambda _:None),
            send_response=lambda _:None,send_header=lambda *args:None,end_headers=lambda:None,wfile=Writer())
        worker=threading.Thread(target=lambda:transfers.download(handler,tickets[0]))
        worker.start()
        try:
            self.assertTrue(entered.wait(10))
            with self.assertRaises(BackupError):
                transfers.export()
            self.assertEqual(len(list(transfers.directory.glob('*.nwbak'))),4)
            transfers.close()
            self.assertTrue(transfers.directory.exists(),'活动下载结束前不得删除传输目录')
        finally:
            release.set();worker.join(15)
        self.assertFalse(transfers.directory.exists(),'服务关闭后最后一个下载须释放暂存目录')

    def test_unknown_operation_is_reported_missing_and_bad_compression_has_json_error(self):
        import io,struct,zipfile
        self.assertEqual(self.request('GET','/api/backups/operations/'+str(uuid4()))[0],404)
        archive=self.archive()
        with zipfile.ZipFile(io.BytesIO(archive)) as package:
            header=package.getinfo('snapshot.sqlite3').header_offset
        damaged=bytearray(archive)
        name,extra=struct.unpack_from('<HH',damaged,header+26)
        offset=header+30+name+extra;damaged[offset]=(damaged[offset]&0xf8)|7
        status,result=self.request('POST','/api/backups/restore',bytes(damaged),content_type='application/octet-stream')
        self.assertEqual(status,422);self.assertIn('error',result)
        self.assertEqual(list(self.root.glob('restored-backup-*/novels.sqlite3')),[])


if __name__ == '__main__':
    unittest.main()
