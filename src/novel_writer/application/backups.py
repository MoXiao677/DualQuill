"""完整库V1包和新目录恢复。只读源库，不接触配置/凭据，不合并既有库。"""
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import struct
import subprocess
import tempfile
import time
from uuid import UUID, uuid4
import zipfile
import zlib

from novel_writer.storage.backup_validation import (
    BackupValidationError, TABLE_COLUMNS, create_schema, strict_loads, validate_database,
)
from novel_writer.application.backup_staging import OwnedTemporaryDirectory, StagingError

FORMAT = 'ai-novel-writer-backup'
EXCLUSIONS = ['provider_configuration_and_credentials', 'environment_variables', 'session_tokens',
              'browser_session_selection', 'unsent_requests', 'in_memory_activity',
              'program_files_and_executable_extensions']
LEGACY_EXCLUSIONS = EXCLUSIONS[:4] + ['in_memory_drafts'] + EXCLUSIONS[4:]
BACKUP_FORMAT_VERSION = 51
DRAFTS_MEMBER = 'drafts.json'
MAX_DRAFT_EXPORT_BYTES = 32 * 1024**2
CHUNK = 1024 * 1024


class BackupError(ValueError):
    def __init__(self, stage, code, message):
        self.stage, self.code = stage, code
        super().__init__(f'{stage}/{code}：{message}')


class BackupResult(dict):
    """保持manifest映射兼容，清理警告只用于业务报告，不写入包。"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cleanup_warnings = []
        self._published = False


@dataclass(frozen=True)
class Limits:
    snapshot_bytes: int = 8 * 1024**3
    manifest_bytes: int = 1024**2
    package_bytes: int = 8 * 1024**3 + 2 * 1024**2
    seconds: float = 300
    reserve_bytes: int = 64 * 1024**2


def _now():
    return datetime.now(timezone.utc).isoformat()


def _guard(limits, cancel=None, progress=None):
    deadline = time.monotonic() + limits.seconds
    def check():
        if cancel is not None and cancel():
            raise BackupError('operation', 'cancelled', '操作已取消，未发布新文件')
        if time.monotonic() >= deadline:
            raise BackupError('operation', 'timeout', '操作超时，未发布新文件')
    check()
    return check


@contextmanager
def _errors(stage, *, allow_missing=False):
    try:
        yield
    except BackupError:
        raise
    except BackupValidationError as error:
        raise BackupError(stage, 'invalid_data', str(error)) from None
    except KeyError:
        if allow_missing:
            raise
        raise BackupError(stage,'invalid_or_io','文件/数据库必需信息缺失；输入和已有目标保留') from None
    except (OSError, sqlite3.Error, zipfile.BadZipFile, zlib.error, RuntimeError, EOFError, ValueError,
            TypeError, KeyError, UnicodeError, OverflowError, RecursionError, struct.error):
        # 不回显私有路径、正文、SQL异常或包内攻击者控制的字符串。
        raise BackupError(stage, 'invalid_or_io', '文件/数据库校验或磁盘操作失败；输入和已有目标保留') from None


@contextmanager
def _publication_directory(parent, result, kind='backup'):
    """发布是完成边界；之后的暂存清理失败不能撤销已经核验的结果。"""
    try:
        owner = OwnedTemporaryDirectory(kind=kind, prefix='.novel-backup-', dir=parent)
        with owner as temporary:
            yield Path(temporary)
        if owner.cleanup_warnings:
            result.cleanup_warnings.append('操作已完成并校验通过；暂存归属元数据清理未完全完成，已发布结果保留。')
    except (OSError, StagingError):
        if not result._published:
            raise
        result.cleanup_warnings.append('操作已完成并校验通过；暂存清理未完全完成，已发布结果保留。')


def _destination(path):
    path = Path(path).absolute()
    if os.path.lexists(path):
        raise BackupError('destination', 'exists', '目标已存在，禁止覆盖')
    parent = path.parent.resolve(strict=True)
    if not parent.is_dir():
        raise BackupError('destination', 'parent', '请选择已有的父目录')
    return parent / path.name


def _space(parent, needed, limits):
    free = shutil.disk_usage(parent)[2]
    if free < needed + max(limits.reserve_bytes, int(needed * .05)):
        raise BackupError('disk', 'space', '可用磁盘空间不足，未发布新文件')


def _write_all(stream, data):
    written = stream.write(data)
    if written != len(data):
        raise OSError('short write')


def _fsync_file(path):
    with open(path, 'rb+') as stream:
        os.fsync(stream.fileno())


def _publish(stage, destination):
    # 暂存与目标同父目录/同卷。Windows rename本身拒绝已有目标，消除exists/replace竞争。
    if os.name == 'nt':
        os.rename(stage, destination)
    elif Path(stage).is_file():
        os.link(stage, destination)  # POSIX文件的原子无覆盖发布
        Path(stage).unlink()
    else:
        raise BackupError('publish', 'platform', '目录原子恢复目前只在Windows支持')


def _insert_row(connection, table, row):
    columns = TABLE_COLUMNS[table]
    connection.execute('INSERT INTO ' + table + ' (' + ','.join(columns) + ') VALUES (' +
                       ','.join('?' for _ in columns) + ')', tuple(row))


def _logical_hash(connection, check):
    digest = hashlib.sha256()
    for table in ('projects', 'project_snapshots', 'skills')+ (('content_blobs',) if connection.execute('PRAGMA user_version').fetchone()[0]==2 else ()):
        digest.update(table.encode())
        for row in connection.execute('SELECT ' + ','.join(TABLE_COLUMNS[table]) + ' FROM ' + table + ' ORDER BY 1,2'):
            check()
            digest.update(json.dumps(list(row), ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf8'))
            digest.update(b'\n')
    return digest.hexdigest()


def _file_hash(path, check):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        while data := stream.read(CHUNK):
            check()
            digest.update(data)
    return digest.hexdigest()


def _snapshot(source, destination, limits, check, progress):
    if not source.is_file():
        raise BackupError('capture', 'missing_source', '源数据库不存在；不会创建空库')
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=.2)) as reader, \
         closing(sqlite3.connect(destination, timeout=.2)) as writer:
        reader.execute('PRAGMA query_only=ON')
        page_size = reader.execute('PRAGMA page_size').fetchone()[0]
        estimated = reader.execute('PRAGMA page_count').fetchone()[0] * page_size
        if estimated > limits.snapshot_bytes:
            raise BackupError('capture','size','一致性快照超过资源上限')
        _space(destination.parent, estimated, limits)
        def step(status, remaining, total):
            check()
            if total * page_size > limits.snapshot_bytes:
                raise BackupError('capture', 'size', '一致性快照超过资源上限')
            if progress:
                progress('capture', total-remaining, total)
        reader.backup(writer, pages=64, progress=step, sleep=.05)
        # 只转换本次新建的冻结副本，保持源journal/WAL模式与提交状态不变。
        writer.execute('PRAGMA journal_mode=DELETE')
    if destination.stat().st_size > limits.snapshot_bytes:
        raise BackupError('capture', 'size', '一致性快照超过资源上限')
    check()


def _producer():
    root = Path(__file__).resolve().parents[3]
    revision, modified = None, True
    try:
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, stderr=subprocess.DEVNULL, text=True, timeout=2).strip()
        if not re.fullmatch('[0-9a-f]{40}', revision):
            revision = None
        modified = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=root, stderr=subprocess.DEVNULL, timeout=2))
    except (OSError, subprocess.SubprocessError):
        pass
    return {'application_version': '0.2.0', 'git_revision': revision, 'working_tree_modified': modified}


def create_backup(source, destination, *, limits=Limits(), cancel=None, progress=None, drafts_path=None):
    """从唯一明确源库在线备份，完整核验后无覆盖发布新.nwbak。"""
    with _errors('backup'):
        check = _guard(limits, cancel, progress)
        source, destination = Path(source).resolve(), _destination(destination)
        if not source.is_file():
            raise BackupError('capture', 'missing_source', '源数据库不存在；不会创建空库')
        estimate = source.stat().st_size
        _space(destination.parent, estimate * 2 + limits.manifest_bytes, limits)
        from novel_writer.application.drafts import DiskDrafts, filter_sensitive_fields
        draft_directory = Path(drafts_path) if drafts_path is not None else source.parent / 'drafts'
        draft_listing = DiskDrafts(draft_directory, create=False).list_all()
        local_drafts = draft_listing['drafts']
        draft_records = [filter_sensitive_fields(record) for record in local_drafts]
        drafts_dropped = ([{'file_name':name,'reason':'invalid_record'} for name in draft_listing.get('corrupt',[])] +
                          [{'file_name':name,'reason':'unreadable'} for name in draft_listing.get('unreadable_files',[])])
        draft_data = (json.dumps({'version': 1, 'drafts': draft_records}, ensure_ascii=False, sort_keys=True, separators=(',', ':'))+'\n').encode('utf-8')
        if len(draft_data) > MAX_DRAFT_EXPORT_BYTES:
            raise BackupError('drafts', 'size', 'draft recovery data exceeds the package limit')

        result = BackupResult()
        with _publication_directory(destination.parent, result) as temporary:
            snapshot = temporary / 'snapshot.sqlite3'
            drafts_file = temporary / DRAFTS_MEMBER
            drafts_file.write_bytes(draft_data)
            started = _now()
            _snapshot(source, snapshot, limits, check, progress)
            finished = _now()
            report = validate_database(snapshot, check=check)
            package_version = BACKUP_FORMAT_VERSION
            manifest = {
                'format': FORMAT, 'backup_format_version': package_version, 'backup_id': str(uuid4()),
                'created_at': _now(), 'capture': {'started_at': started, 'finished_at': finished},
                'producer': _producer(), 'scope': {'mode': 'full_library', 'project_ids': report['project_ids'],
                'skills': {'mode': 'all', 'ids': report['skill_ids']}, 'browser_preferences': 'excluded'},
                'database': report['database'], 'counts': report['counts'],
                'entries': [{'path': 'snapshot.sqlite3', 'bytes': snapshot.stat().st_size, 'sha256': _file_hash(snapshot, check)}],
                'exclusions': (EXCLUSIONS if package_version==BACKUP_FORMAT_VERSION else LEGACY_EXCLUSIONS).copy(),
            }
            if package_version==BACKUP_FORMAT_VERSION:
                manifest['entries'].append({'path': DRAFTS_MEMBER, 'bytes': len(draft_data), 'sha256': hashlib.sha256(draft_data).hexdigest()})
            encoded = (json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode('utf8')
            if len(encoded) > limits.manifest_bytes:
                raise BackupError('manifest', 'size', '清单超过资源上限')
            _space(destination.parent, snapshot.stat().st_size + len(draft_data) + limits.manifest_bytes, limits)
            staged = temporary / 'complete.nwbak'
            with zipfile.ZipFile(staged, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as package:
                with package.open('manifest.json', 'w') as entry:
                    _write_all(entry, encoded)
                with package.open('snapshot.sqlite3', 'w', force_zip64=True) as entry, open(snapshot, 'rb') as reader:
                    while data := reader.read(CHUNK):
                        check()
                        _write_all(entry, data)
                if package_version==BACKUP_FORMAT_VERSION:
                    with package.open(DRAFTS_MEMBER, 'w') as entry:
                        _write_all(entry, draft_data)
            _fsync_file(staged)
            if staged.stat().st_size > limits.package_bytes:
                raise BackupError('package', 'size', '包超过资源上限')
            # 使用同一个生产读取器复核最终包，写入成功不等于包可恢复。
            with tempfile.TemporaryDirectory(prefix='verify-', dir=temporary) as extracted:
                verified, _, _, verified_drafts = _unpack(staged, Path(extracted), limits, check)
                if verified != manifest or verified_drafts != (draft_records if package_version==BACKUP_FORMAT_VERSION else []):
                    raise BackupError('package', 'verify', '最终包校验失败')
            check()
            result.update(manifest)
            result.drafts_dropped = drafts_dropped
            _publish(staged, destination)
            result._published = True
            return result


def _keys(value, names, label):
    if type(value) is not dict or set(value) != set(names):
        raise BackupError('manifest', 'fields', label + '字段缺失或未知')


def _utc(value):
    if type(value) is not str:
        raise BackupError('manifest', 'time', '清单时间类型错误')
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() != timedelta(0):
        raise BackupError('manifest', 'time', '清单时间必须包含UTC时区')
    return parsed


def _unique_strings(value):
    if type(value) is not list or any(type(item) is not str or not item.strip() for item in value) or len(value) != len(set(value)):
        raise BackupError('manifest', 'list', '清单集合类型或唯一性错误')


def _same(value, expected):
    """值与类型一起核验，避免True等于1绕过数量/版本约束。"""
    if type(value) is not type(expected):
        return False
    if isinstance(expected, dict):
        return value.keys() == expected.keys() and all(_same(value[key], item) for key, item in expected.items())
    if isinstance(expected, list):
        return len(value) == len(expected) and all(_same(a,b) for a,b in zip(value, expected))
    return value == expected


def _manifest(data, limits):
    _keys(data, ['format','backup_format_version','backup_id','created_at','capture','producer','scope','database','counts','entries','exclusions'], 'manifest')
    if data['format'] != FORMAT or type(data['backup_format_version']) is not int or data['backup_format_version'] not in range(1, BACKUP_FORMAT_VERSION+1):
        raise BackupError('manifest', 'version', '未知或未来备份格式；仅支持V1-V51')
    if type(data.get('database')) is not dict:
        raise BackupError('manifest','profile','包格式与实际工作区profile不符')
    workspace_version=data['database'].get('workspace_version')
    if (type(workspace_version) is not int or workspace_version not in range(1,53) or
            (data['backup_format_version'] <= 50 and workspace_version != data['backup_format_version'])):
        raise BackupError('manifest','profile','包格式与实际工作区profile不符')
    if type(data['backup_id']) is not str or str(UUID(data['backup_id'])) != data['backup_id']:
        raise BackupError('manifest', 'identity', '包身份不是规范UUID')
    _keys(data['capture'], ['started_at','finished_at'], 'capture')
    if not _utc(data['capture']['started_at']) <= _utc(data['capture']['finished_at']) <= _utc(data['created_at']):
        raise BackupError('manifest', 'time', '捕获时间顺序错误')
    producer = data['producer']
    _keys(producer, ['application_version','git_revision','working_tree_modified'], 'producer')
    if type(producer['application_version']) is not str or not producer['application_version'].strip() or type(producer['working_tree_modified']) is not bool:
        raise BackupError('manifest', 'producer', '软件信息类型错误')
    if producer['git_revision'] is not None and (type(producer['git_revision']) is not str or not re.fullmatch('[0-9a-f]{40}', producer['git_revision'])):
        raise BackupError('manifest', 'producer', 'Git版本信息错误')
    scope = data['scope']
    _keys(scope, ['mode','project_ids','skills','browser_preferences'], 'scope')
    _keys(scope['skills'], ['mode','ids'], 'skills范围')
    if scope['mode'] != 'full_library' or scope['skills']['mode'] != 'all' or scope['browser_preferences'] != 'excluded':
        raise BackupError('manifest', 'unsupported_scope', 'B批只支持完整库与全部Skills；选择性迁移/偏好附件暂不支持')
    _unique_strings(scope['project_ids']); _unique_strings(scope['skills']['ids'])
    _unique_strings(data['exclusions'])
    expected_exclusions = LEGACY_EXCLUSIONS if data['backup_format_version'] <= 50 else EXCLUSIONS
    if set(data['exclusions']) != set(expected_exclusions):
        raise BackupError('manifest', 'exclusions', '排除范围不符合备份格式')
    expected_entry_count = 2 if data['backup_format_version'] == BACKUP_FORMAT_VERSION else 1
    if type(data['entries']) is not list or len(data['entries']) != expected_entry_count:
        raise BackupError('manifest', 'entries', '备份成员缺失或超出格式约定')
    paths=['snapshot.sqlite3'] + ([DRAFTS_MEMBER] if expected_entry_count==2 else [])
    for entry,path in zip(data['entries'],paths):
        _keys(entry, ['path','bytes','sha256'], 'entry')
        maximum = limits.snapshot_bytes if path=='snapshot.sqlite3' else MAX_DRAFT_EXPORT_BYTES
        if entry['path'] != path or type(entry['bytes']) is not int or not 0 < entry['bytes'] <= maximum:
            raise BackupError('manifest', 'size', '备份成员或大小不合法/超限')
        if type(entry['sha256']) is not str or not re.fullmatch('[0-9a-f]{64}', entry['sha256']):
            raise BackupError('manifest', 'hash', 'SHA256格式错误')
    return data


def _zip_header(stream):
    """在ZipFile分配中央目录对象之前限制条目数/目录字节，兼容ZIP64。"""
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(max(0, size-65557))
    tail = stream.read(65557)
    offset = tail.rfind(b'PK\x05\x06')
    if offset < 0 or len(tail)-offset < 22:
        raise BackupError('zip', 'directory', 'ZIP目录缺失或截断')
    _, disk, cd_disk, disk_count, total, central_size, central_offset, comment_size = struct.unpack('<4s4H2LH', tail[offset:offset+22])
    if len(tail)-offset != 22+comment_size or disk or cd_disk or disk_count != total:
        raise BackupError('zip', 'directory', 'ZIP目录或分卷格式不合法')
    eocd_offset = size-len(tail)+offset
    if total == 65535 or central_size == 0xffffffff or central_offset == 0xffffffff:
        stream.seek(eocd_offset-20)
        signature, locator_disk, location, disks = struct.unpack('<4sLQL', stream.read(20))
        if signature != b'PK\x06\x07' or locator_disk or disks != 1:
            raise BackupError('zip', 'zip64', 'ZIP64目录不合法')
        stream.seek(location)
        signature, record_size, _, _, zip_disk, zip_cd_disk, zip_disk_count, total, central_size, central_offset = struct.unpack('<4sQ2H2L4Q', stream.read(56))
        if signature != b'PK\x06\x06' or not 44 <= record_size <= 1024 or zip_disk or zip_cd_disk or zip_disk_count != total:
            raise BackupError('zip', 'zip64', 'ZIP64目录不合法')
    if not 1 <= total <= 3 or central_size > 16384 or central_offset+central_size > eocd_offset:
        raise BackupError('zip', 'resource', 'ZIP成员数量或目录体积超限')
    stream.seek(0)


def _unpack(path, extracted, limits, check):
    check()
    with open(path, 'rb') as stream:
        if os.fstat(stream.fileno()).st_size > limits.package_bytes:
            raise BackupError('zip', 'size', '包体积超限')
        _zip_header(stream)
        with zipfile.ZipFile(stream) as package:
            members = package.infolist()
            names = [item.filename for item in members]
            if len(names) != len(set(names)) or set(names) not in ({'manifest.json','snapshot.sqlite3'}, {'manifest.json','snapshot.sqlite3',DRAFTS_MEMBER}):
                raise BackupError('zip', 'members', '成员缺失/重复/未知路径；偏好附件暂不支持')
            for item in members:
                mode = item.external_attr >> 16
                if item.flag_bits & 1 or item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED) or stat.S_ISLNK(mode) or item.is_dir():
                    raise BackupError('zip', 'member_type', '拒绝加密、链接或未知压缩格式')
                maximum = limits.manifest_bytes if item.filename == 'manifest.json' else MAX_DRAFT_EXPORT_BYTES if item.filename == DRAFTS_MEMBER else limits.snapshot_bytes
                if item.file_size > maximum or item.file_size < 0:
                    raise BackupError('zip', 'size', '成员展开体积超限')
            with package.open('manifest.json') as entry:
                text = entry.read(limits.manifest_bytes+1)
                if len(text) > limits.manifest_bytes:
                    raise BackupError('manifest', 'size', '清单展开体积超限')
            manifest = _manifest(strict_loads(text), limits)
            expected_names={'manifest.json','snapshot.sqlite3'} | ({DRAFTS_MEMBER} if manifest['backup_format_version']==BACKUP_FORMAT_VERSION else set())
            if set(names)!=expected_names:
                raise BackupError('zip','members','成员集合与备份版本不匹配')
            declared = manifest['entries'][0]
            info = package.getinfo('snapshot.sqlite3')
            if info.file_size != declared['bytes']:
                raise BackupError('zip', 'size', 'ZIP与manifest快照大小不一致')
            _space(extracted, declared['bytes'] * 2, limits)
            snapshot = extracted / 'snapshot.sqlite3'
            digest, total = hashlib.sha256(), 0
            with package.open(info) as entry, open(snapshot, 'xb') as writer:
                while data := entry.read(CHUNK):
                    check()
                    total += len(data)
                    if total > declared['bytes'] or total > limits.snapshot_bytes:
                        raise BackupError('zip', 'size', '实际展开体积超限')
                    _write_all(writer, data)
                    digest.update(data)
                writer.flush(); os.fsync(writer.fileno())
            if total != declared['bytes'] or digest.hexdigest() != declared['sha256']:
                raise BackupError('integrity', 'checksum', '快照大小或SHA256不一致')
            draft_records=[]
            if manifest['backup_format_version']==BACKUP_FORMAT_VERSION:
                from novel_writer.application.drafts import filter_sensitive_fields, validate_draft_record
                draft_declaration=manifest['entries'][1]
                with package.open(DRAFTS_MEMBER) as entry:
                    draft_data=entry.read(MAX_DRAFT_EXPORT_BYTES+1)
                if len(draft_data)!=draft_declaration['bytes'] or hashlib.sha256(draft_data).hexdigest()!=draft_declaration['sha256']:
                    raise BackupError('integrity','draft_checksum','Draft collection size or SHA256 mismatch')
                payload=strict_loads(draft_data)
                if type(payload) is not dict or set(payload)!={'version','drafts'} or type(payload['version']) is not int or payload['version']!=1 or type(payload['drafts']) is not list or len(payload['drafts'])>10000:
                    raise BackupError('drafts','format','Draft collection format is invalid')
                seen=set()
                for item in payload['drafts']:
                    check();record=filter_sensitive_fields(validate_draft_record(item))
                    identity=(record['project_id'],record['document_key'])
                    if identity in seen:raise BackupError('drafts','duplicate','Draft collection contains duplicate documents')
                    seen.add(identity);draft_records.append(record)
    report = validate_database(snapshot, check=check)
    database = manifest['database']
    if type(database) is dict and type(database.get('tables')) is list:
        database = dict(database, tables=sorted(database['tables'], key=lambda item: item['name']))
    counts = manifest['counts']
    if type(counts) is dict and type(counts.get('projects')) is list:
        counts = dict(counts, projects=sorted(counts['projects'], key=lambda item: item['project_id']))
    if not _same(database, report['database']) or not _same(counts, report['counts']) or sorted(manifest['scope']['project_ids']) != report['project_ids'] or sorted(manifest['scope']['skills']['ids']) != report['skill_ids']:
        raise BackupError('manifest', 'mismatch', '清单/schema/数量/范围与实际数据不一致')
    return manifest, snapshot, report, draft_records



def _drafts_digest(records):
    normalized=sorted(records,key=lambda item:(item['project_id'],item['document_key']))
    return hashlib.sha256(json.dumps(normalized,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()


def _restorable_drafts(snapshot,draft_records):
    from novel_writer.application.drafts import draft_entity_references
    refs={}
    with closing(sqlite3.connect(snapshot.as_uri()+'?mode=ro',uri=True)) as source_db:
        for row in source_db.execute('SELECT id,payload FROM projects'):
            state=strict_loads(row[1]);doc=state['document']
            refs[row[0]]={'writing':{item['id'] for item in doc['chapters']},
                          'characters':{item['id'] for item in doc['characters']},
                          'memory':{item['id'] for item in state.get('memories',[])}}
    accepted=[];dropped=[]
    for item in draft_records:
        parsed=json.loads(item['document_key']);project,view,entity,pane=parsed
        valid=project in refs and ((view=='writing' and entity in refs[project]['writing']) or
              (view=='characters' and entity in refs[project]['characters']) or
              (view=='memory' and entity in refs[project]['memory']) or
              (view not in ('writing','characters','memory') and not entity and not pane))
        if valid:valid=all(reference in refs[project].get({'chapter':'writing','character':'characters','memory':'memory'}[kind],set()) for kind,reference in draft_entity_references(item))
        if valid:accepted.append(item)
        else:dropped.append({'document_key':item['document_key'],'reason':'missing_mapping'})
    return accepted,dropped


def preflight_backup(package, *, limits=Limits(), cancel=None):
    """完整只读预检，临时展开会清理，既有数据不写入。"""
    with _errors('preflight'):
        check = _guard(limits, cancel)
        with OwnedTemporaryDirectory(kind='preflight', prefix='.novel-backup-') as temporary:
            manifest, snapshot, report, _ = _unpack(Path(package), Path(temporary), limits, check)
            from novel_writer.application.extension_policy import backup_dependencies
            return {'manifest': manifest, 'counts': report['counts'], 'verified': True,
                    'extension_dependencies': backup_dependencies(snapshot),
                    'extension_authorizations_restored': False}


def restore_backup(package, target_directory, *, limits=Limits(), cancel=None, progress=None):
    """完整预检后在新库事务重建，重开逐单元格核验后发布不存在的新目录。"""
    with _errors('restore'):
        check = _guard(limits, cancel, progress)
        target = _destination(target_directory)
        result = BackupResult()
        result['cleanup_warnings'] = result.cleanup_warnings
        with _publication_directory(target.parent, result, kind='restore') as temporary:
            manifest, snapshot, report, draft_records = _unpack(Path(package), temporary, limits, check)
            restored = temporary / 'restored'
            restored.mkdir()
            database = restored / 'novels.sqlite3'
            with closing(sqlite3.connect(snapshot.as_uri()+'?mode=ro', uri=True)) as reader, \
                 closing(sqlite3.connect(database)) as writer:
                reader.execute('PRAGMA query_only=ON')
                writer.execute('PRAGMA foreign_keys=ON')
                writer.execute('PRAGMA synchronous=FULL')
                create_schema(writer,report['database']['sqlite_user_version'])
                writer.commit()
                with writer:
                    writer.execute('BEGIN IMMEDIATE')
                    for table in ('projects','project_snapshots','skills')+ (('content_blobs',) if report['database']['sqlite_user_version']==2 else ()):
                        for row in reader.execute('SELECT '+','.join(TABLE_COLUMNS[table])+' FROM '+table+' ORDER BY 1,2'):
                            check()
                            _insert_row(writer, table, row)
                    if writer.execute('PRAGMA foreign_key_check').fetchone() is not None:
                        raise BackupError('restore', 'foreign_key', '目标外键检查失败')
                expected_hash = _logical_hash(reader, check)
            actual = validate_database(database, check=check)
            with closing(sqlite3.connect(database.as_uri()+'?mode=ro', uri=True)) as reopened:
                if _logical_hash(reopened, check) != expected_hash or not _same(actual, report):
                    raise BackupError('restore', 'roundtrip', '目标落盘重开完整性校验失败')
            _fsync_file(database)
            check()
            from novel_writer.application.drafts import DiskDrafts
            draft_records,drafts_dropped=_restorable_drafts(snapshot,draft_records)
            draft_restored=[]
            if draft_records:
                destination_drafts=DiskDrafts(restored/'drafts')
                for item in draft_records:
                    destination_drafts.import_record(item,only_if_missing=True)
                    draft_restored.append(item['document_key'])
            result.update(database_path=str(target / 'novels.sqlite3'), manifest=manifest,
                          counts=report['counts'], verified=True, credentials_restored=False,
                          drafts_restored=draft_restored, drafts_dropped=drafts_dropped,
                          sensitive_fields_required=any(item.get('sensitive_fields_required') for item in draft_records))
            from novel_writer.application.extension_policy import backup_dependencies
            result.update(extension_dependencies=backup_dependencies(database),
                          extension_authorizations_restored=False)
            _publish(restored, target)
            result._published = True
            return result
