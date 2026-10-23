"""独立恢复操作的库外收据：先留存期望数据，再发布；断线/重启可核对。"""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
from uuid import UUID

from novel_writer.application.backups import (
    BackupError, Limits, _errors, _file_hash, _guard, _logical_hash, _publish,
    _unpack, _write_all, _restorable_drafts, _drafts_digest,
)
from novel_writer.storage.backup_validation import strict_loads, validate_database
from novel_writer.application.backup_staging import OwnedTemporaryDirectory


def operation_id(value):
    if type(value) is not str:
        raise BackupError('operation', 'identity', '恢复操作编号必须为规范UUID')
    try:
        if str(UUID(value)) != value:
            raise ValueError()
    except ValueError:
        raise BackupError('operation', 'identity', '恢复操作编号必须为规范UUID') from None
    return value


def _plain(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 1024:
        raise BackupError('operation', 'link', '操作收据及目标不接受链接或重解析点')


def _root(database, *, create=False):
    root = Path(database).resolve().parent / '.novel-backup-operations'
    if create:
        root.mkdir(exist_ok=True)
    if not root.exists():
        raise KeyError('operation')
    _plain(root)
    if not root.is_dir():
        raise BackupError('operation', 'receipt', '操作收据位置不可用')
    return root


def _load(database, identity):
    path = _root(database) / (operation_id(identity)+'.json')
    if not path.exists():
        raise KeyError('operation')
    _plain(path)
    if not path.is_file() or path.stat().st_size > 262144:
        raise BackupError('operation', 'receipt', '操作收据损坏，禁止生成替代目标')
    with open(path, 'rb') as stream:
        receipt = strict_loads(stream.read(262145))
    fields = {'version','operation_id','package_sha256','backup_id','logical_sha256'}
    allowed=fields|{'drafts_sha256','drafts_restored','drafts_dropped','sensitive_fields_required'}
    if type(receipt) is not dict or set(receipt) not in (fields,allowed) or type(receipt['version']) is not int or receipt['version'] != 1 or receipt['operation_id'] != identity:
        raise BackupError('operation','receipt','操作收据损坏，禁止生成替代目标')
    operation_id(receipt['backup_id'])
    if not fields<=set(receipt) or (set(receipt)-fields)-allowed:
        raise BackupError('operation','receipt','操作收据损坏，禁止生成替代目标')
    for name in ('package_sha256','logical_sha256')+ (('drafts_sha256',) if 'drafts_sha256' in receipt else ()):
        value = receipt[name]
        if type(value) is not str or len(value) != 64 or any(char not in '0123456789abcdef' for char in value):
            raise BackupError('operation','receipt','操作收据校验信息损坏')
    return receipt


def _write_receipt(database, receipt):
    root = _root(database, create=True)
    # 只保存本操作的非秘密身份，不修改既有收据；容量满时显式停止。
    if sum(1 for _ in root.iterdir()) >= 1024:
        raise BackupError('operation','quota','恢复操作收据已达1024项，请先人工归档')
    destination = root / (receipt['operation_id']+'.json')
    with OwnedTemporaryDirectory(kind='receipt', prefix='.receipt-', dir=root) as temporary:
        staged = Path(temporary)/'receipt.json'
        with open(staged, 'xb') as stream:
            _write_all(stream, (json.dumps(receipt,ensure_ascii=False)+'\n').encode('utf8'))
            stream.flush();os.fsync(stream.fileno())
        _publish(staged,destination)


def target_for(database, identity):
    return Path(database).resolve().parent / ('restored-backup-'+UUID(operation_id(identity)).hex)


def prepare_operation(database, identity, package, *, limits=Limits(), cancel=None):
    """收据必须落盘成功才可调用恢复；同identity永远对应同包和同目标。"""
    with _errors('operation'):
        identity=operation_id(identity);check=_guard(limits,cancel)
        digest=_file_hash(package,check)
        try:
            receipt=_load(database,identity)
        except KeyError:
            receipt=None
        if receipt is not None:
            if receipt['package_sha256'] != digest:
                raise BackupError('operation','conflict','同一恢复操作编号对应不同备份包，拒绝重试')
            return operation_status(database,identity,limits=limits,cancel=cancel)
        if os.path.lexists(target_for(database,identity)):
            raise BackupError('operation','unknown_target','目标已有内容且缺少操作收据；禁止覆盖或猜测')
        with OwnedTemporaryDirectory(kind='receipt_preflight', prefix='novel-backup-receipt-') as temporary:
            manifest,snapshot,_,draft_records=_unpack(Path(package),Path(temporary),limits,check)
            with closing(sqlite3.connect(snapshot.as_uri()+'?mode=ro',uri=True)) as connection:
                connection.execute('PRAGMA query_only=ON')
                expected=_logical_hash(connection,check)
            restorable,drafts_dropped=_restorable_drafts(snapshot,draft_records)
            from novel_writer.application.drafts import filter_sensitive_fields as _redact
            drafts_digest=_drafts_digest([_redact(item) for item in restorable])
        receipt={'version':1,'operation_id':identity,'package_sha256':digest,
                 'backup_id':manifest['backup_id'],'logical_sha256':expected,'drafts_sha256':drafts_digest,
                 'drafts_restored':[item['document_key'] for item in restorable],
                 'drafts_dropped':drafts_dropped,
                 'sensitive_fields_required':any(item.get('sensitive_fields_required') for item in restorable)}
        _write_receipt(database,receipt)
        return {'operation_id':identity,'state':'target_absent','verified':False}


def operation_status(database, identity, *, limits=Limits(), cancel=None):
    """状态来自真实目标全部SQL单元格，不凭收据/路径存在冒称完成。"""
    with _errors('operation',allow_missing=True):
        receipt=_load(database,operation_id(identity));target=target_for(database,identity)
        if not os.path.lexists(target):
            return {'operation_id':identity,'state':'target_absent','verified':False}
        _plain(target)
        names={item.name for item in target.iterdir()}
        if not target.is_dir() or names not in ({'novels.sqlite3'},{'novels.sqlite3','drafts'}):
            raise BackupError('operation','changed_target','恢复目标已变化，禁止复用或覆盖')
        if 'drafts_sha256' not in receipt and 'drafts' in names:
            raise BackupError('operation','changed_target','旧恢复目标包含未登记的草稿文件')
        actual_drafts=[]
        if 'drafts' in names:
            from novel_writer.application.drafts import DiskDrafts,filter_sensitive_fields
            drafts_dir=target/'drafts';_plain(drafts_dir)
            listing=DiskDrafts(drafts_dir,create=False).list_all()
            if listing.get('corrupt') or listing.get('unreadable') or any(item.is_dir() for item in drafts_dir.iterdir()):
                raise BackupError('operation','changed_target','恢复草稿数据已变化，禁止复用或覆盖')
            actual_drafts=[filter_sensitive_fields(item) for item in listing['drafts']]
        if 'drafts_sha256' in receipt and _drafts_digest(actual_drafts)!=receipt['drafts_sha256']:
            raise BackupError('operation','changed_target','恢复草稿数据已变化，禁止复用或覆盖')
        actual=target/'novels.sqlite3';_plain(actual);check=_guard(limits,cancel)
        report=validate_database(actual,check=check)
        with closing(sqlite3.connect(actual.as_uri()+'?mode=ro',uri=True)) as connection:
            connection.execute('PRAGMA query_only=ON')
            connection.execute('BEGIN')
            if _logical_hash(connection,check) != receipt['logical_sha256']:
                raise BackupError('operation','changed_target','恢复目标已编辑，禁止复用或覆盖')
        return {'operation_id':identity,'state':'completed','database_path':str(actual),
                'counts':report['counts'],'verified':True,'credentials_restored':False,
                'drafts_restored':receipt.get('drafts_restored',[]),'drafts_dropped':receipt.get('drafts_dropped',[]),
                'sensitive_fields_required':receipt.get('sensitive_fields_required',False)}
