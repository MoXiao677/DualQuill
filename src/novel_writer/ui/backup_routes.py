"""会话保护的受控文件传输；浏览器不能指定任意磁盘路径。"""
import json
from pathlib import Path
import re
import select
import tempfile
import threading
import time
from uuid import uuid4
from dataclasses import replace

from novel_writer.application.backups import BackupError, Limits, _write_all, create_backup, restore_backup
from novel_writer.application.backup_identity import operation_id, operation_status, prepare_operation, target_for
from novel_writer.application.backup_staging import OwnedTemporaryDirectory


UPLOAD_TOTAL_SECONDS = 300.0
UPLOAD_IDLE_SECONDS = 20.0
UPLOAD_POLL_SECONDS = .1
UPLOAD_CHUNK_BYTES = 1024 * 1024


def _receive_upload(handler, writer, length, deadline, cancel):
    """非阻塞读取已有缓冲与单次 socket 数据；等待期间也能超时和取消。"""
    connection = handler.connection
    original_timeout = connection.gettimeout()
    idle_deadline = time.monotonic() + UPLOAD_IDLE_SECONDS

    def check():
        now = time.monotonic()
        if cancel():
            raise BackupError('transfer', 'cancelled', '上传已取消，未发布恢复目标')
        if now >= deadline:
            raise BackupError('transfer', 'timeout', '上传总时限已到，未发布恢复目标')
        if now >= idle_deadline:
            raise BackupError('transfer', 'idle_timeout', '上传等待数据超时，未发布恢复目标')
        return now

    def available(size):
        try:
            # read1最多尝试一次底层读取。非阻塞socket不会等待凑满size。
            return handler.rfile.read1(size)
        except (BlockingIOError, InterruptedError):
            return None

    try:
        connection.setblocking(False)
        remaining = length
        while remaining:
            now = check()
            size = min(UPLOAD_CHUNK_BYTES, remaining)
            # 请求头可能已预读正文；先取缓冲，不能只等待socket可读。
            data = available(size)
            if not data:
                wait = min(UPLOAD_POLL_SECONDS, deadline-now, idle_deadline-now)
                try:
                    readable, _, _ = select.select([connection], [], [], max(0, wait))
                except InterruptedError:
                    continue
                check()
                if not readable:
                    continue
                data = available(size)
                if data is None:
                    continue
                # 首次空读也可能只是EAGAIN；可读之后再空读才表示EOF。
                if not data:
                    raise BackupError('transfer', 'truncated', '上传文件被截断')
            check()
            _write_all(writer, data)
            remaining -= len(data)
            idle_deadline = time.monotonic() + UPLOAD_IDLE_SECONDS
    except BaseException:
        # 禁止残余正文被作为同一连接上的下一条HTTP请求解析。
        handler.close_connection = True
        raise
    finally:
        try:
            connection.settimeout(original_timeout)
        except OSError:
            # 对端断开不能阻止外层finally释放暂存、操作状态和恢复槽。
            pass


class BackupTransfers:
    def __init__(self, database, drafts_path=None):
        self.database = Path(database)
        self.drafts_path = Path(drafts_path) if drafts_path is not None else self.database.parent/'drafts'
        self.temporary = OwnedTemporaryDirectory(kind='transfers', prefix='novel-backup-transfers-')
        self.directory = Path(self.temporary.name)
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(2)
        self.closed = threading.Event()
        self.downloads = {}
        self.active_restores = {}
        self.active_migrations = {}
        self.cleanup_lock = threading.Lock()

    def _acquire(self):
        if self.closed.is_set() or not self.slots.acquire(blocking=False):
            raise BackupError('transfer','busy','已有备份操作或服务正在关闭，请稍后重试')
        if self.closed.is_set():
            self.slots.release()
            raise BackupError('transfer','closed','服务正在关闭')

    def _release(self):
        self.slots.release()
        if self.closed.is_set():
            self._cleanup_if_idle()

    def _cleanup_if_idle(self):
        with self.cleanup_lock:
            acquired=0
            for _ in range(2):
                if self.slots.acquire(blocking=False):
                    acquired+=1
            try:
                if acquired==2:
                    self.temporary.cleanup()
            finally:
                for _ in range(acquired):
                    self.slots.release()

    def close(self):
        self.closed.set()
        self._cleanup_if_idle()

    def _expire(self):
        for ticket, (path, expires, active) in list(self.downloads.items()):
            if path is not None and not active and expires < time.monotonic():
                path.unlink(missing_ok=True)
                del self.downloads[ticket]

    def export(self):
        self._acquire()
        ticket = uuid4().hex
        path = self.directory / (ticket+'.nwbak')
        try:
            with self.lock:
                self._expire()
                if len(self.downloads) >= 4:
                    raise BackupError('transfer','quota','请先下载已准备的备份，或等待5分钟过期')
                self.downloads[ticket] = (None, time.monotonic()+300, False)
            manifest = create_backup(self.database, path, cancel=self.closed.is_set, drafts_path=self.drafts_path)
            with self.lock:
                self.downloads[ticket] = (path, time.monotonic()+300, False)
            return {'download_url':'/api/backups/download/'+ticket, 'counts':manifest['counts'],
                    'verified':True, 'expires_in_seconds':300,
                    'cleanup_warnings':getattr(manifest,'cleanup_warnings',[]),
                    'drafts_dropped':getattr(manifest,'drafts_dropped',[])}
        except BaseException:
            with self.lock:
                self.downloads.pop(ticket, None)
            path.unlink(missing_ok=True)
            raise
        finally:
            self._release()

    def download(self, handler, ticket):
        if not re.fullmatch('[0-9a-f]{32}', ticket):
            raise KeyError('download')
        self._acquire()
        try:
            with self.lock:
                self._expire()
                entry = self.downloads.get(ticket)
                if entry is None or entry[0] is None or entry[2]:
                    raise KeyError('download')
                self.downloads[ticket] = (entry[0],entry[1],True)
        except BaseException:
            self._release()
            raise
        path = entry[0];deadline=time.monotonic()+300
        try:
            with open(path, 'rb') as reader:
                handler.connection.settimeout(20)
                handler.send_response(200)
                handler.send_header('Content-Type','application/zip')
                handler.send_header('Content-Length',str(path.stat().st_size))
                handler.send_header('Content-Disposition','attachment; filename="novel-library.nwbak"')
                handler.send_header('Cache-Control','no-store')
                handler.send_header('X-Content-Type-Options','nosniff')
                handler.end_headers()
                while data := reader.read(1024*1024):
                    if self.closed.is_set() or time.monotonic() >= deadline:
                        break
                    handler.wfile.write(data)
        except (BrokenPipeError, ConnectionError, OSError):
            # 客户端中断时不在已发送的二进制响应后追加JSON。
            pass
        finally:
            try:
                path.unlink(missing_ok=True)
                with self.lock:
                    self.downloads.pop(ticket,None)
            finally:
                self._release()

    def status(self, identity):
        identity=operation_id(identity)
        with self.lock:
            if identity in self.active_restores:
                return {'operation_id':identity,'state':'running','verified':False}
        self._acquire()
        try:
            result=operation_status(self.database,identity,cancel=self.closed.is_set)
            if result.get('state')=='completed':
                from novel_writer.application.extension_policy import backup_dependencies
                result.update(extension_dependencies=backup_dependencies(result['database_path']),extension_authorizations_restored=False)
            return result
        finally:
            self._release()

    def cancel(self, identity):
        identity=operation_id(identity)
        with self.lock:
            event=self.active_restores.get(identity)
            if event is not None:
                event.set()
                # 这是取消请求，最终发布若先完成则最终结果仍为completed。
                return {'operation_id':identity,'state':'running','cancel_requested':True}
        result=self.status(identity)
        return dict(result,cancel_requested=False)

    def restore_upload(self, handler):
        if handler.headers.get('Content-Type','').split(';')[0] != 'application/octet-stream':
            raise BackupError('transfer','type','恢复仅接受.nwbak二进制文件')
        if handler.headers.get('Transfer-Encoding'):
            raise BackupError('transfer','length','请提交具有明确大小的备份文件')
        try:
            length = int(handler.headers.get('Content-Length','0'))
        except ValueError:
            raise BackupError('transfer','length','文件大小无效') from None
        if not 0 < length <= Limits().package_bytes:
            raise BackupError('transfer','size','上传文件为空或超过资源上限')
        identity=operation_id(handler.headers.get('X-Novel-Backup-Operation',str(uuid4())))
        self._acquire()
        with self.lock:
            if identity in self.active_restores:
                self._release()
                raise BackupError('operation','busy','同一恢复操作正在运行，请查询状态')
            event=threading.Event();self.active_restores[identity]=event
        result=None;temporary=None
        try:
            handler.connection.settimeout(20)
            deadline = time.monotonic()+UPLOAD_TOTAL_SECONDS
            cancel=lambda:self.closed.is_set() or event.is_set()
            temporary=tempfile.TemporaryDirectory(prefix='upload-',dir=self.directory)
            uploaded=Path(temporary.name)/'input.nwbak'
            with open(uploaded,'xb') as writer:
                _receive_upload(handler, writer, length, deadline, cancel)
            remaining_limits=lambda:replace(Limits(),seconds=max(0,deadline-time.monotonic()))
            known=prepare_operation(self.database,identity,uploaded,limits=remaining_limits(),cancel=cancel)
            if known['state']=='completed':
                result=known
            else:
                restored=restore_backup(uploaded,target_for(self.database,identity),limits=remaining_limits(),cancel=cancel)
                result={key:restored[key] for key in ('database_path','counts','verified','credentials_restored','extension_dependencies','extension_authorizations_restored')}
                result.update(drafts_restored=restored.get('drafts_restored',[]),drafts_dropped=restored.get('drafts_dropped',[]),sensitive_fields_required=restored.get('sensitive_fields_required',False))
                result.update(operation_id=identity,state='completed',cleanup_warnings=restored.get('cleanup_warnings',[]))
            if 'extension_dependencies' not in result:
                from novel_writer.application.extension_policy import backup_dependencies
                result.update(extension_dependencies=backup_dependencies(result['database_path']),extension_authorizations_restored=False)
            return result
        finally:
            try:
                if temporary is not None:
                    try:
                        temporary.cleanup()
                    except OSError:
                        if result is None:
                            raise
                        result.setdefault('cleanup_warnings',[]).append('恢复已完成，上传暂存清理失败；请按操作归属检查暂存目录')
            finally:
                with self.lock:
                    self.active_restores.pop(identity,None)
                self._release()
