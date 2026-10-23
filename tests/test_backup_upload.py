"""P2 上传回归：真实本地 HTTP/socket，仅独立虚构库，不启动接收辅助线程。"""
from contextlib import closing
import hashlib
import http.client
import json
import os
from pathlib import Path
import select
import socket
import sqlite3
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests/fixtures')]
from s2_b_samples import build_runtime_dataset
from s2_a_samples import create_fixture_database
from novel_writer.application.backups import create_backup
from novel_writer.ui import backup_routes
from novel_writer.ui.server import create_server


class BackupUploadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='novel-p2-upload-')
        self.root = Path(self.temporary.name)
        self.database = self.root / 'fictional.sqlite3'
        create_fixture_database(self.database, build_runtime_dataset())
        package = self.root / 'fixture.nwbak'
        create_backup(self.database, package)
        self.archive = package.read_bytes()
        self.server = create_server(self.database, port=0, offline=True)
        # 既有 repository 初始化会写库头；只比较服务启动之后上传前后的源库。
        self.source_hash = hashlib.sha256(self.database.read_bytes()).hexdigest()
        self.clients = []
        self.workers = []
        self.worker_errors = []
        self.worker_lock = threading.Lock()
        original = self.server.process_request_thread
        original_error = self.server.handle_error

        def tracked_error(request, address):
            self.worker_errors.append(type(sys.exc_info()[1]).__name__)
            original_error(request, address)

        def tracked(request, address):
            with self.worker_lock:
                self.workers.append(threading.current_thread())
            try:
                original(request, address)
            except BaseException as error:
                self.worker_errors.append(type(error).__name__)
                raise

        self.server.process_request_thread = tracked
        self.server.handle_error = tracked_error
        def serve():
            try:
                self.server.serve_forever(poll_interval=.01)
            except BaseException as error:
                self.worker_errors.append(type(error).__name__)
                raise

        self.thread = threading.Thread(target=serve, daemon=True)
        self.thread.start()
        self.observations = []
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for client in self.clients:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            client.close()
        self.server.shutdown()
        self.thread.join(2)
        self.server.server_close()
        for worker in self.workers:
            worker.join(2)
        report = {'test': self.id(), 'fictional_database': str(self.database),
                  'port': self.server.server_address[1], 'observations': self.observations,
                  'worker_errors': self.worker_errors,
                  'live_request_workers': sum(worker.is_alive() for worker in self.workers),
                  'server_thread_stopped': not self.thread.is_alive(),
                  'source_hash_unchanged': hashlib.sha256(self.database.read_bytes()).hexdigest() == self.source_hash,
                  'transfer_directory_removed': self.server._backups is None or not self.server._backups.directory.exists()}
        self.temporary.cleanup()
        report['test_directory_removed'] = not self.root.exists()
        artifacts = os.environ.get('NOVEL_WRITER_ARTIFACTS')
        if artifacts:
            with (Path(artifacts) / 'upload-http-probes.jsonl').open('a', encoding='utf8') as stream:
                stream.write(json.dumps(report, ensure_ascii=False) + '\n')
        self.assertTrue(report['source_hash_unchanged'])
        self.assertTrue(report['server_thread_stopped'])
        self.assertTrue(report['transfer_directory_removed'])
        self.assertEqual(report['live_request_workers'], 0)
        self.assertEqual(self.worker_errors, [])

    def request(self, method, endpoint, body=b'{}', **headers):
        with closing(http.client.HTTPConnection('127.0.0.1', self.server.server_address[1], timeout=5)) as client:
            client.request(method, endpoint, body=body,
                           headers={'X-Novel-Token': self.server.token, 'Content-Type': 'application/json', **headers})
            response = client.getresponse()
            return response.status, json.loads(response.read())

    def upload(self, length=4096, body=b'x', identity=None):
        identity = identity or str(uuid4())
        client = socket.create_connection(self.server.server_address, timeout=2)
        self.clients.append(client)
        headers = (f'POST /api/backups/restore HTTP/1.1\r\n'
                   f'Host: 127.0.0.1:{self.server.server_address[1]}\r\n'
                   f'X-Novel-Token: {self.server.token}\r\n'
                   f'X-Novel-Backup-Operation: {identity}\r\n'
                   f'Content-Length: {length}\r\nContent-Type: application/octet-stream\r\n'
                   'Connection: close\r\n\r\n').encode()
        client.sendall(headers + body)
        return client, identity

    def wait_running(self, identity):
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            with self.server.backups.lock:
                if identity in self.server.backups.active_restores:
                    return
            time.sleep(.005)
        self.fail('请求必须进入真实上传读取阶段')

    def response(self, client, *, drip=False, seconds=1.5):
        start = time.monotonic()
        received = bytearray()
        last_send = start
        while time.monotonic() - start < seconds:
            readable, _, _ = select.select([client], [], [], .01)
            if readable:
                chunk = client.recv(65536)
                if not chunk:
                    break
                received.extend(chunk)
                if b'\r\n\r\n' in received:
                    headers, body = bytes(received).split(b'\r\n\r\n', 1)
                    size = int(next(line.split(b':', 1)[1] for line in headers.split(b'\r\n')
                                    if line.lower().startswith(b'content-length:')))
                    if len(body) >= size:
                        elapsed = time.monotonic() - start
                        status = int(headers.split(b' ', 2)[1])
                        result = json.loads(body[:size])
                        self.observations.append({'response_seconds': elapsed, 'status': status,
                                                  'code': result.get('code'), 'drip': drip})
                        return status, result, elapsed
            if drip and time.monotonic() - last_send >= .03:
                client.sendall(b'x')
                last_send = time.monotonic()
        self.fail('客户端仍保持连接并滴流/等待时，服务未在有界时间内终止上传')

    def assert_released(self, active=0):
        transfers = self.server.backups
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            with transfers.lock:
                count = len(transfers.active_restores)
            if count == active:
                break
            time.sleep(.005)
        self.assertEqual(count, active)
        acquired = 0
        try:
            for _ in range(2):
                acquired += int(transfers.slots.acquire(blocking=False))
            self.assertEqual(acquired, 2 - active)
        finally:
            for _ in range(acquired):
                transfers.slots.release()
        leftovers = list(transfers.directory.glob('upload-*')) if transfers.directory.exists() else []
        self.assertEqual(len(leftovers), active)
        self.observations.append({'active_restores': count, 'occupied_slots': 2-acquired,
                                  'upload_directories': len(leftovers)})

    def assert_retry(self):
        status, result = self.request('POST', '/api/backups/restore', self.archive,
                                      **{'Content-Type': 'application/octet-stream'})
        self.assertEqual(status, 201, result)
        self.assertTrue(result['verified'])
        with closing(sqlite3.connect(self.database)) as source, closing(sqlite3.connect(result['database_path'])) as target:
            for table in ('projects', 'project_snapshots', 'skills'):
                sql = f'SELECT * FROM {table} ORDER BY 1,2'
                self.assertEqual(source.execute(sql).fetchall(), target.execute(sql).fetchall())
        self.assert_released()
        self.observations.append({'subsequent_restore': '201, verified, all SQL cells equal'})

    def test_continuous_drip_stops_at_total_deadline(self):
        with patch.object(backup_routes, 'UPLOAD_TOTAL_SECONDS', .35):
            client, identity = self.upload()
            self.wait_running(identity)
            status, result, elapsed = self.response(client, drip=True)
        self.assertEqual((status, result['code']), (422, 'timeout'))
        self.assertLess(elapsed, .85)
        self.assertEqual(list(self.root.glob('restored-backup-*')), [])
        self.assert_released()
        self.assert_retry()

    def test_cancel_interrupts_continuous_drip(self):
        client, identity = self.upload()
        self.wait_running(identity)
        status, result = self.request('POST', '/api/backups/operations/' + identity + '/cancel')
        self.assertEqual(status, 200)
        self.assertTrue(result['cancel_requested'])
        status, result, elapsed = self.response(client, drip=True)
        self.assertEqual((status, result['code']), (422, 'cancelled'))
        self.assertLess(elapsed, .8)
        self.assert_released()
        self.assert_retry()

    def test_cancel_interrupts_silent_client(self):
        client, identity = self.upload(body=b'')
        self.wait_running(identity)
        self.request('POST', '/api/backups/operations/' + identity + '/cancel')
        status, result, elapsed = self.response(client)
        self.assertEqual((status, result['code']), (422, 'cancelled'))
        self.assertLess(elapsed, .8)
        self.assert_released()
        self.assert_retry()

    def test_idle_deadline_releases_silent_client(self):
        with patch.object(backup_routes, 'UPLOAD_IDLE_SECONDS', .25):
            client, identity = self.upload(body=b'')
            self.wait_running(identity)
            status, result, elapsed = self.response(client)
        self.assertEqual((status, result['code']), (422, 'idle_timeout'))
        self.assertLess(elapsed, .8)
        self.assert_released()
        self.assert_retry()

    def test_half_closed_client_is_truncated_and_slot_reusable(self):
        client, identity = self.upload()
        self.wait_running(identity)
        client.shutdown(socket.SHUT_WR)
        status, result, _ = self.response(client)
        self.assertEqual((status, result['code']), (422, 'truncated'))
        self.assert_released()
        self.assert_retry()

    def test_reset_client_leaves_no_handler_error_or_slot(self):
        client, identity = self.upload()
        self.wait_running(identity)
        client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                          struct.pack('hh' if sys.platform == 'win32' else 'ii', 1, 0))
        client.close()
        self.assert_released()
        self.assert_retry()

    def test_normal_upload_with_body_buffered_after_headers(self):
        client, _ = self.upload(len(self.archive), self.archive)
        status, result, _ = self.response(client, seconds=5)
        self.assertEqual(status, 201, result)
        self.assertTrue(result['verified'])
        self.assert_released()

    def test_fragmented_valid_upload_and_same_operation_retry(self):
        client, identity = self.upload(len(self.archive), b'')
        for offset in range(0, len(self.archive), 256):
            client.sendall(self.archive[offset:offset+256])
            time.sleep(.002)
        status, result, _ = self.response(client, seconds=5)
        self.assertEqual(status, 201, result)
        status, retry = self.request('POST', '/api/backups/restore', self.archive,
                                     **{'Content-Type': 'application/octet-stream',
                                        'X-Novel-Backup-Operation': identity})
        self.assertEqual(status, 201)
        self.assertEqual(result['database_path'], retry['database_path'])
        self.assertEqual(len(list(self.root.glob('restored-backup-*'))), 1)
        self.assert_released()

    def test_two_slots_cancel_one_preserves_other_restore(self):
        first, one = self.upload()
        second, two = self.upload(len(self.archive), b'')
        self.wait_running(one)
        self.wait_running(two)
        self.assertEqual(self.request('POST', '/api/backups/export')[0], 422)
        self.request('POST', '/api/backups/operations/' + one + '/cancel')
        self.assertEqual(self.response(first)[1]['code'], 'cancelled')
        self.assert_released(active=1)
        second.sendall(self.archive)
        status, restored, _ = self.response(second, seconds=5)
        self.assertEqual(status, 201, restored)
        self.assertTrue(restored['verified'])
        self.assertEqual(len(list(self.root.glob('restored-backup-*'))), 1)
        self.assert_released()

    def test_server_close_interrupts_upload_without_helper_threads(self):
        client, identity = self.upload(body=b'')
        self.wait_running(identity)
        # 停止接收循环后关闭监听；正在上传的请求线程此时仍保持连接。
        self.server.shutdown()
        self.thread.join(2)
        self.server.server_close()
        status, result, elapsed = self.response(client)
        self.assertEqual((status, result['code']), (422, 'cancelled'))
        self.assertLess(elapsed, .8)
        self.assert_released()
        self.assertFalse(self.server.backups.directory.exists())

    def test_upload_disk_exception_releases_resources(self):
        with patch.object(backup_routes, '_write_all', side_effect=OSError('fictional write failure')):
            client, _ = self.upload(len(self.archive), self.archive)
            self.assertEqual(self.response(client)[0], 422)
        self.assert_released()
        self.assert_retry()

    def request_after_close(self, method, endpoint, body=b''):
        accepted = threading.Event()
        original = self.server.process_request_thread

        def tracked(request, address):
            accepted.set()
            original(request, address)

        self.server.process_request_thread = tracked
        client = socket.create_connection(self.server.server_address, timeout=2)
        self.clients.append(client)
        headers = (f'{method} {endpoint} HTTP/1.1\r\n'
                   f'Host: 127.0.0.1:{self.server.server_address[1]}\r\n'
                   f'X-Novel-Token: {self.server.token}\r\n'
                   f'Content-Length: {len(body)}\r\nContent-Type: application/octet-stream\r\n'
                   'Connection: close\r\n').encode()
        client.sendall(headers)
        self.assertTrue(accepted.wait(1), '必须先由真实HTTP请求线程接受连接')
        self.assertIsNone(self.server._backups)
        self.server.shutdown()
        self.thread.join(2)
        self.server.server_close()
        self.assertIsNone(self.server._backups)
        client.sendall(b'\r\n' + body)
        return self.response(client)

    def test_first_restore_headers_completed_after_close_cannot_publish(self):
        status, result, elapsed = self.request_after_close('POST', '/api/backups/restore', self.archive)
        self.assertEqual((status, result.get('code')), (422, 'closed'))
        self.assertLess(elapsed, .8)
        self.assertIsNone(self.server._backups, '关闭后不能惰性创建备份管理器')
        self.assertEqual(list(self.root.glob('restored-backup-*')), [])

    def test_first_download_headers_completed_after_close_is_controlled(self):
        status, result, elapsed = self.request_after_close('GET', '/api/backups/download/' + 'a' * 32)
        self.assertEqual((status, result.get('code')), (422, 'closed'))
        self.assertLess(elapsed, .8)
        self.assertIsNone(self.server._backups, '关闭后不能创建传输临时目录')

    def test_duplicate_operation_does_not_release_original_slot(self):
        client, identity = self.upload(len(self.archive), b'')
        self.wait_running(identity)
        status, result = self.request('POST', '/api/backups/restore', b'x',
                                      **{'Content-Type': 'application/octet-stream',
                                         'X-Novel-Backup-Operation': identity})
        self.assertEqual((status, result['code']), (422, 'busy'))
        self.assert_released(active=1)
        client.sendall(self.archive)
        self.assertEqual(self.response(client, seconds=5)[0], 201)
        self.assert_released()


if __name__ == '__main__':
    unittest.main()
