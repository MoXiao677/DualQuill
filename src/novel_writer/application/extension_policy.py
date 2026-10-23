"""Local, append-only grants. Backups copy data, never extension authority."""
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from novel_writer.application.fields import check_fields
from novel_writer.domain.tasks import require, uuid_value


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


class ExtensionPolicy:
    def __init__(self, database):
        self.database = Path(database).resolve()
        self.path = self.database.with_name(self.database.name + '.extension-policy.sqlite3')

    def _connect(self, write=False):
        require(not self.path.is_symlink(), '扩展授权文件不能是符号链接')
        connection = sqlite3.connect(self.path if write else self.path.as_uri() + '?mode=ro',
                                     uri=not write, timeout=10)
        if write:
            connection.execute('CREATE TABLE IF NOT EXISTS events ('
                'sequence INTEGER PRIMARY KEY, database_binding TEXT NOT NULL, '
                'project_id TEXT NOT NULL, operation_id TEXT NOT NULL UNIQUE, '
                'request_hash TEXT NOT NULL, version_id TEXT NOT NULL, '
                'template_hash TEXT NOT NULL, enabled INTEGER NOT NULL, '
                'permissions TEXT NOT NULL)')
            for operation in ('UPDATE', 'DELETE'):
                connection.execute(f'CREATE TRIGGER IF NOT EXISTS events_no_{operation.lower()} '
                    f'BEFORE {operation} ON events BEGIN SELECT RAISE(ABORT, '
                    "'扩展授权历史不可改写'); END")
        return connection

    def status(self, project_id, record):
        result = dict(version_id=record['id'], enabled=False, policy_revision=0,
                      permissions=[], reason='requires_local_authorization')
        if not self.path.exists():
            return result
        with closing(self._connect()) as connection:
            result['policy_revision'] = connection.execute(
                'SELECT COALESCE(MAX(sequence),0) FROM events').fetchone()[0]
            row = connection.execute(
                'SELECT template_hash,enabled,permissions FROM events '
                'WHERE database_binding=? AND project_id=? AND version_id=? '
                'ORDER BY sequence DESC LIMIT 1',
                (str(self.database), project_id, record['id'])).fetchone()
        if row and row[0] == _digest(record['template']):
            result.update(enabled=bool(row[1]), permissions=json.loads(row[2]),
                          reason='enabled' if row[1] else 'disabled_by_author')
        return result

    def change(self, service, project_id, request):
        fields = {'operation_id', 'expected_revision', 'expected_policy_revision',
                  'version_id', 'enabled', 'permissions'}
        check_fields(request, fields)
        require(set(request) == fields, '扩展授权字段缺失')
        uuid_value(request['operation_id']); uuid_value(request['version_id'])
        require(type(request['enabled']) is bool, '启停状态须为布尔值')
        require(type(request['expected_revision']) is int and
                type(request['expected_policy_revision']) is int, '授权修订号非法')
        state = service.get(project_id)
        record = next((v for v in state.get('extension_templates', [])
                       if v['id'] == request['version_id']), None)
        require(record is not None, '模板版本不属于当前书')
        from novel_writer.application.extensions import preflight
        spec = preflight(record['template'])['template']
        require(type(request['permissions']) is list and
                request['permissions'] == (spec['permissions'] if request['enabled'] else []),
                '须逐项明确授权已注册权限，停用时撤销全部权限')
        require(next(v for v in reversed(state['extension_templates'])
                     if v['template_id'] == record['template_id'])['id'] == record['id'],
                '旧模板版本不能重新启用；请显式导入为新版本')
        request_hash = _digest(request)
        if not self.path.exists():
            require(state['revision'] == request['expected_revision'], '保存编号变化，请刷新')
            require(request['expected_policy_revision'] == 0, '扩展授权已变化，请刷新')
        with closing(self._connect(write=True)) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            old = connection.execute('SELECT request_hash FROM events WHERE operation_id=?',
                                     (request['operation_id'],)).fetchone()
            if old:
                require(old[0] == request_hash, '同一授权操作编号绑定不同请求')
            else:
                require(state['revision'] == request['expected_revision'], '保存编号变化，请刷新')
                revision = connection.execute('SELECT COALESCE(MAX(sequence),0) FROM events').fetchone()[0]
                require(revision == request['expected_policy_revision'], '扩展授权已变化，请刷新')
                connection.execute('INSERT INTO events(database_binding,project_id,operation_id,'
                    'request_hash,version_id,template_hash,enabled,permissions) VALUES(?,?,?,?,?,?,?,?)',
                    (str(self.database), project_id, request['operation_id'], request_hash,
                     record['id'], _digest(spec), int(request['enabled']),
                     json.dumps(request['permissions'])))
        return self.status(project_id, record)


def policy_for(service):
    return ExtensionPolicy(service.repository.path)


def dependencies(state, *, policy=None):
    """Read-only report; imported records are retained even without local grants."""
    latest = {}
    for record in state.get('extension_templates', []):
        latest[record['template_id']] = record
    result = []
    for record in latest.values():
        from novel_writer.application.extensions import preflight
        try:
            preflight(record['template'])
            compatible, reason = True, 'requires_local_authorization'
        except (ValueError, TypeError):
            compatible, reason = False, 'incompatible_extension_contract'
        status = policy.status(state['document']['project']['id'], record) if policy else {}
        result.append(dict(template_id=record['template_id'], version_id=record['id'],
                           capability=record['template']['capability'], compatible=compatible,
                           enabled=status.get('enabled', False),
                           reason=status.get('reason', reason) if compatible else reason,
                           data_preserved=True, code_loaded=False))
    return result


def backup_dependencies(database):
    """Read validated backup snapshots without opening/migrating their repository."""
    result = []
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)) as connection:
        connection.execute('PRAGMA query_only=ON')
        for project_id, payload in connection.execute('SELECT id,payload FROM projects ORDER BY id'):
            for item in dependencies(json.loads(payload)):
                result.append(dict(project_id=project_id, **item))
    return result
