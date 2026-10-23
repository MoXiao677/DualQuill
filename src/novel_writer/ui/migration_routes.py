"""复用备份传输槽/关闭信号，迁移只写当前服务明确的数据库。"""
from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import time

from novel_writer.application.backup_identity import operation_id
from novel_writer.application.backups import BackupError, Limits
from novel_writer.application.migrations import migrate, migration_status
from novel_writer.storage.backup_validation import strict_loads
from novel_writer.ui.backup_routes import _receive_upload, UPLOAD_TOTAL_SECONDS


class MigrationOperations:
    def __init__(self, transfers):
        self.transfers = transfers

    def _begin(self, identity):
        manager = self.transfers
        manager._acquire()
        with manager.lock:
            if identity in manager.active_migrations:
                manager._release()
                raise BackupError('migration','busy','同一迁移操作正在运行，请核对结果')
            event = threading.Event()
            manager.active_migrations[identity] = event
        return event

    def _end(self, identity):
        manager = self.transfers
        with manager.lock: manager.active_migrations.pop(identity,None)
        manager._release()

    def status(self, identity):
        identity = operation_id(identity)
        manager = self.transfers
        with manager.lock:
            if identity in manager.active_migrations:
                return {'operation_id':identity,'state':'running','verified':False}
        manager._acquire()
        try: return migration_status(manager.database,identity,cancel=manager.closed.is_set)
        finally: manager._release()

    def cancel(self, identity):
        identity = operation_id(identity)
        with self.transfers.lock:
            event = self.transfers.active_migrations.get(identity)
            if event is not None:
                event.set()
                return {'operation_id':identity,'state':'running','cancel_requested':True,'verified':False}
        return dict(self.status(identity),cancel_requested=False)

    def copy(self, payload):
        if (type(payload) is not dict or not {'operation_id','project_id'}<=set(payload)
                or set(payload)-{'operation_id','project_id','preview'} or type(payload['project_id']) is not str):
            raise BackupError('migration','fields','复制只接受操作编号及已保存小说编号')
        identity = operation_id(payload['operation_id'])
        event = self._begin(identity)
        try:
            return migrate(self.transfers.database,self.transfers.database,operation_id=identity,
                project_ids=[payload['project_id']],preview=payload.get('preview',False),drafts_path=self.transfers.drafts_path,
                target_drafts_path=self.transfers.drafts_path,
                cancel=lambda:self.transfers.closed.is_set() or event.is_set())
        finally: self._end(identity)

    def upload(self, handler):
        if handler.headers.get('Content-Type','').split(';')[0]!='application/octet-stream':
            raise BackupError('migration','type','请选择V1备份包、兼容SQLite或旧JSON文件')
        if handler.headers.get('Transfer-Encoding'):
            raise BackupError('migration','length','迁移文件必须具有明确大小')
        identity = operation_id(handler.headers.get('X-Novel-Migration-Operation'))
        preview_header = handler.headers.get('X-Novel-Migration-Preview','0')
        if preview_header not in ('0','1'): raise ValueError('preview header')
        try: length = int(handler.headers.get('Content-Length','0'))
        except ValueError: raise BackupError('migration','length','文件大小无效') from None
        if not 0 < length <= Limits().package_bytes:
            raise BackupError('migration','size','迁移文件为空或超过资源上限')
        event = self._begin(identity)
        manager = self.transfers
        temporary, result = None, None
        try:
            deadline = time.monotonic()+UPLOAD_TOTAL_SECONDS
            cancel = lambda:manager.closed.is_set() or event.is_set()
            temporary = tempfile.TemporaryDirectory(prefix='migration-upload-',dir=manager.directory)
            uploaded = Path(temporary.name)/'input'
            with uploaded.open('xb') as writer:
                _receive_upload(handler,writer,length,deadline,cancel)
            result = migrate(uploaded,manager.database,operation_id=identity,cancel=cancel,preview=preview_header=='1',
                target_drafts_path=manager.drafts_path,
                limits=replace(Limits(),seconds=max(0,deadline-time.monotonic())))
            return result
        finally:
            try:
                if temporary is not None:
                    try: temporary.cleanup()
                    except OSError:
                        if result is None: raise
                        result.setdefault('cleanup_warnings',[]).append('迁移已提交；本次上传暂存清理未完成，请保留报告。')
            finally: self._end(identity)


def read_parameters(handler):
    if handler.headers.get('Content-Type','').split(';')[0]!='application/json' or handler.headers.get('Transfer-Encoding'):
        raise BackupError('migration','type','复制或取消只接受JSON参数')
    try: length = int(handler.headers.get('Content-Length','0'))
    except ValueError: raise BackupError('migration','length','参数大小无效') from None
    if not 0 < length <= 4096: raise BackupError('migration','size','迁移参数为空或超限')
    handler.connection.settimeout(20)
    return strict_loads(handler.rfile.read(length))
