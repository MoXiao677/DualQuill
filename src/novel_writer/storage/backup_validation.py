"""关闭后的 S2-B SQLite 快照严格只读预检；不修复或升级输入。"""
from __future__ import annotations

from contextlib import closing
from copy import deepcopy
from dataclasses import fields, is_dataclass
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sqlite3
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

from novel_writer.domain.models import (
    BookOutline, Chapter, ChapterOutline, Character, DataValidationError, NovelDocument,
    NovelProject, VersionRecord, _timestamp,
)
from novel_writer.storage.json_codec import MAX_JSON_BYTES, strict_json_loads,normalize_persistent_document
from novel_writer.storage.sqlite_repository import WorkspaceHistoryValidator, validate_workspace


TABLE_COLUMNS = {
    "projects": ["id", "title", "revision", "payload", "updated_at"],
    "project_snapshots": ["project_id", "revision", "payload", "saved_at"],
    "skills": ["id", "name", "description", "imported_at", "primary_path", "files_json"],
    "content_blobs": ["sha256", "data_base64"],
}
MODEL_TYPES = {"project": NovelProject, "book_outline": BookOutline, "chapter_outline": ChapterOutline,
               "character": Character, "chapter": Chapter}
SCHEMA_PROFILE = "novel-writer/sqlite-1"
# 工程资源边界，超限明确拒绝；不裁剪正文、元信息或历史。
MAX_SQL_VALUE_BYTES = 64 * 1024 * 1024
MAX_SQL_ROW_BYTES = MAX_SQL_VALUE_BYTES + 1024 * 1024
MAX_DATABASE_ROWS = 1_000_000
MAX_TABLE_ROWS = {"projects": 1_000, "project_snapshots": 1_000_000, "skills": 10_000, "content_blobs":100_000}
MAX_MANIFEST_ID_BYTES = 512 * 1024
MAX_REPORT_BYTES = 768 * 1024


class BackupValidationError(ValueError):
    """备份结构或数据校验失败；错误不包含正文、资料或原始 SQL。"""


def strict_loads(text: str | bytes) -> Any:
    try:
        return strict_json_loads(text)
    except DataValidationError as error:
        raise BackupValidationError(str(error)) from None


def _require(condition, message):
    if not condition:
        raise BackupValidationError(message)


@lru_cache(maxsize=2)
def _trusted_profile(version=1):
    # 此资源随应用发布；绝不从备份包读取 DDL。
    return json.loads(Path(__file__).with_name('schema_v'+str(version)+'.json').read_text(encoding="utf-8"))


def create_schema(connection: sqlite3.Connection,version=1) -> None:
    """只在新库执行应用冻结 DDL；不读取输入包 SQL，也不隐式提交事务。"""
    profile = _trusted_profile(version)
    connection.execute("PRAGMA foreign_keys=ON")
    for table in profile['tables']:
        connection.execute(profile["tables"][table]["ddl"])
    for ddl in profile["triggers"].values():
        connection.execute(ddl)
    connection.execute('PRAGMA user_version='+str(version))


def _sql_space(sql):
    return " ".join(sql.split())


def _schema(connection, check):
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    _require(version in (1,2),'schema.user_version：未知数据库版本')
    expected = _trusted_profile(version)
    objects = [dict(type=row[0], name=row[1]) for row in connection.execute(
        "SELECT type,name FROM sqlite_master ORDER BY type,name")]
    _require(objects == expected["objects"], "schema.objects：存在未知或缺失的表、索引、视图或触发器")
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    for name, table in expected["tables"].items():
        check()
        actual = connection.execute("SELECT sql,tbl_name FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
        _require(actual[1] == name and _sql_space(actual[0]) == _sql_space(table["ddl"]), f"schema.{name}.ddl：与可信定义不一致")
        columns = [list(row) for row in connection.execute(f'PRAGMA table_xinfo("{name}")')]
        foreign_keys = [list(row) for row in connection.execute(f'PRAGMA foreign_key_list("{name}")')]
        indexes = []
        for row in connection.execute(f'PRAGMA index_list("{name}")'):
            index_name = row[1]
            _require(index_name in {item["definition"][1] for item in table["indexes"]}, f"schema.{name}.indexes：未知索引")
            indexes.append({"definition": list(row), "columns": [list(item) for item in connection.execute(f'PRAGMA index_xinfo("{index_name}")')]})
        _require(columns == table["columns"], f"schema.{name}.columns：列定义不一致")
        _require(foreign_keys == table["foreign_keys"], f"schema.{name}.foreign_keys：外键不一致")
        _require(indexes == table["indexes"], f"schema.{name}.indexes：索引不一致")
    for name, ddl in expected["triggers"].items():
        row = connection.execute("SELECT sql,tbl_name FROM sqlite_master WHERE type='trigger' AND name=?", (name,)).fetchone()
        _require(row[1] == ('content_blobs' if name.startswith('blobs_') else 'project_snapshots') and _sql_space(row[0]) == _sql_space(ddl), f"schema.{name}：历史保护触发器不一致")
    canonical = deepcopy(expected)
    for table in canonical["tables"].values():
        del table["ddl"]
    canonical["triggers"] = {name: _sql_space(ddl) for name, ddl in canonical["triggers"].items()}
    digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {
        "schema_profile": 'novel-writer/sqlite-'+str(version), "sqlite_user_version": version, "workspace_version": 1,
        "document_schema_version": 1, "schema_sha256": digest,
        "tables": [{"name": name, "columns": TABLE_COLUMNS[name], "rows": 0} for name in sorted(expected['tables'])],
        "indexes": [item["name"] for item in objects if item["type"] == "index"],
        "triggers": sorted(expected["triggers"]),
        "foreign_keys": [{"table": name, "definition": key} for name in sorted(expected["tables"])
                         for key in expected["tables"][name]["foreign_keys"]],
    }


@lru_cache(maxsize=None)
def _model_fields(model):
    return {item.name for item in fields(model)}, get_type_hints(model)


def _exact(value, annotation, path, *, snapshot=False):
    """在构造器补默认值之前检查每一层完整字段及精确 Python 类型。"""
    if annotation is Any:
        return
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (UnionType, Union):
        for option in args:
            try:
                _exact(value, option, path, snapshot=snapshot)
                return
            except BackupValidationError:
                pass
        raise BackupValidationError(f"{path}：类型或完整字段不匹配")
    if origin is Literal:
        _require(any(type(value) is type(item) and value == item for item in args), f"{path}：未知枚举值")
    elif origin is list:
        _require(type(value) is list, f"{path}：必须为列表")
        for index, item in enumerate(value):
            _exact(item, args[0], f"{path}[{index}]", snapshot=snapshot)
    elif origin is dict:
        _require(type(value) is dict, f"{path}：必须为对象")
        for index, (key, item) in enumerate(value.items()):
            _exact(key, args[0], f"{path}.key[{index}]", snapshot=snapshot)
            _exact(item, args[1], f"{path}.value[{index}]", snapshot=snapshot)
    elif is_dataclass(annotation):
        names, hints = _model_fields(annotation)
        if snapshot and annotation is Chapter:
            names = names - {"current_version_id"}
        _require(type(value) is dict and set(value) == names, f"{path}：持久字段缺失或含未知字段")
        for name in names:
            _exact(value[name], hints[name], f"{path}.{name}", snapshot=snapshot)
    else:
        _require(type(value) is annotation, f"{path}：字段类型错误")


def _workspace(payload):
    state = strict_loads(payload)
    expected = {"workspace_version", "revision", "document", "ideas", "worldbuilding", "writing_rules"}
    if type(state) is dict and type(state.get('workspace_version')) is int and state['workspace_version'] in (2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52):
        expected |= {'memories','memory_history'}
        if state['workspace_version']>=3:
            from novel_writer.domain.tasks import COLLECTIONS
            expected |= set(COLLECTIONS)
        if state['workspace_version']>=4:
            from novel_writer.domain.review import REVIEW_COLLECTIONS
            expected |= set(REVIEW_COLLECTIONS)
        if state['workspace_version']>=5:
            from novel_writer.domain.knowledge import KNOWLEDGE_COLLECTIONS
            expected |= set(KNOWLEDGE_COLLECTIONS)
        if state['workspace_version']>=6:
            from novel_writer.domain.model_contract import MODEL_COLLECTIONS
            expected |= set(MODEL_COLLECTIONS)
        if state['workspace_version']>=7:
            from novel_writer.domain.experiments import EXPERIMENT_COLLECTIONS
            expected |= set(EXPERIMENT_COLLECTIONS)
        if state['workspace_version']>=8:
            from novel_writer.domain.workflows import WORKFLOW_COLLECTIONS
            expected |= set(WORKFLOW_COLLECTIONS)
        if state['workspace_version']>=10:
            from novel_writer.domain.creation_presets import CREATION_COLLECTIONS
            expected |= set(CREATION_COLLECTIONS)
        if state['workspace_version']>=11:
            from novel_writer.domain.book_creation import COLLECTIONS as BOOK_CREATION_COLLECTIONS
            expected |= set(BOOK_CREATION_COLLECTIONS)
        if state['workspace_version']>=12:
            from novel_writer.domain.book_ai import COLLECTIONS as BOOK_AI_COLLECTIONS
            expected |= set(BOOK_AI_COLLECTIONS)
        if state['workspace_version']>=13:
            from novel_writer.domain.styles import COLLECTIONS as STYLE_COLLECTIONS
            expected |= set(STYLE_COLLECTIONS)
        if state['workspace_version']>=14:
            from novel_writer.domain.public_search import COLLECTIONS as WEB_COLLECTIONS
            expected |= set(WEB_COLLECTIONS)
        if state['workspace_version']>=15:
            from novel_writer.domain.style_trials import COLLECTIONS as TRIAL_COLLECTIONS
            expected |= set(TRIAL_COLLECTIONS)
        if state['workspace_version']>=16:
            from novel_writer.domain.chapter_writing import COLLECTIONS as WRITING_COLLECTIONS
            expected |= set(WRITING_COLLECTIONS)
        if state['workspace_version']>=17:
            from novel_writer.domain.chapter_planning import COLLECTIONS as PLANNING_COLLECTIONS
            expected |= set(PLANNING_COLLECTIONS)
        if state['workspace_version']>=18:
            from novel_writer.domain.scene_expansion import COLLECTIONS as EXPANSION_COLLECTIONS
            expected |= set(EXPANSION_COLLECTIONS)
        if state['workspace_version']>=19:
            from novel_writer.domain.chapter_lifecycle import COLLECTIONS as LIFECYCLE_COLLECTIONS
            expected |= set(LIFECYCLE_COLLECTIONS)
        if state['workspace_version']>=20:
            from novel_writer.domain.console import COLLECTIONS as CONSOLE_COLLECTIONS
            expected |= set(CONSOLE_COLLECTIONS)
        if state['workspace_version']>=21:
            expected |= {'scoped_rules'}
        if state['workspace_version']>=46:
            from novel_writer.domain.rule_reviews import COLLECTIONS as RULE_REVIEW_COLLECTIONS
            expected |= set(RULE_REVIEW_COLLECTIONS)
        if state['workspace_version']>=36:
            expected |= {'rule_task_bindings'}
        if state['workspace_version']>=22:
            expected |= {'scoped_rule_history'}
        if state['workspace_version']>=23:
            from novel_writer.domain.memory_rollups import COLLECTIONS as ROLLUP_COLLECTIONS
            expected |= set(ROLLUP_COLLECTIONS)
        if state['workspace_version']>=24:
            from novel_writer.domain.console import RUN_COLLECTIONS
            expected |= set(RUN_COLLECTIONS)
        if state['workspace_version']>=25:
            from novel_writer.domain.materials import COLLECTIONS as MATERIAL_COLLECTIONS
            expected |= set(MATERIAL_COLLECTIONS)
        if state['workspace_version']>=26:
            from novel_writer.domain.full_book_planning import COLLECTIONS as PLANNING_V26_COLLECTIONS
            expected |= set(PLANNING_V26_COLLECTIONS)
        if state['workspace_version']>=27:
            from novel_writer.domain.chapter_trash import COLLECTIONS as TRASH_COLLECTIONS
            expected |= set(TRASH_COLLECTIONS)
        if state['workspace_version']>=41:expected.add('deep_review_actions')
        if state['workspace_version']>=42:expected.add('memory_automation_events')
        if state['workspace_version']>=43:
            from novel_writer.domain.body_planning import COLLECTIONS as BODY_PLANNING_COLLECTIONS
            expected |= set(BODY_PLANNING_COLLECTIONS)
        if state['workspace_version']>=45:
            from novel_writer.domain.graph_extraction import COLLECTIONS as GRAPH_COLLECTIONS
            expected |= set(GRAPH_COLLECTIONS)
        if state['workspace_version']>=47:
            from novel_writer.domain.model_planning import COLLECTIONS as MODEL_PLANNING_COLLECTIONS
            expected |= set(MODEL_PLANNING_COLLECTIONS)
        if state['workspace_version']>=48:expected.add('author_scope_events')
        if state['workspace_version']>=49:
            from novel_writer.domain.semantic_retrieval import COLLECTIONS as SEMANTIC_COLLECTIONS
            expected |= set(SEMANTIC_COLLECTIONS)
        if state['workspace_version']>=50:expected.add('memory_refresh_events')
        if state['workspace_version']>=50 and (state['workspace_version']>=51 or 'graph_item_decisions' in state):expected.add('graph_item_decisions')
        if state['workspace_version']>=52:
            from novel_writer.domain.console_background import COLLECTIONS as BACKGROUND_COLLECTIONS
            expected.update(BACKGROUND_COLLECTIONS)
        if any(name in state for name in ('canon_maintenance_settings','canon_maintenance_facts','canon_maintenance_events','canon_maintenance_checkpoints')):
            from novel_writer.domain.canon_maintenance import COLLECTIONS as CANON_COLLECTIONS
            expected.update(CANON_COLLECTIONS)
    _require(type(state) is dict and set(state) == expected, "workspace：字段缺失或含未知字段")
    _require(type(state["workspace_version"]) is int and state["workspace_version"] in (1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52), "workspace.workspace_version：仅支持版本 1–52")
    _require(type(state["revision"]) is int and state["revision"] >= 1, "workspace.revision：必须为正整数")
    from novel_writer.domain.sampling import contains as contains_sampling
    _require(state['workspace_version']>=28 or not contains_sampling(state), 'sampling 需要 workspace_version 28')
    from novel_writer.domain.sampling import contains_native
    _require(state['workspace_version']>=29 or not contains_native(state), '原生请求配置需要 workspace_version 29')
    from novel_writer.domain.execution_limits import contains_long_timeout
    _require(state['workspace_version']>=30 or not contains_long_timeout(state), '长请求时限需要 workspace_version 30')
    from novel_writer.domain.memory_rollups import contains_chapter_rollup
    _require(state['workspace_version']>=31 or not contains_chapter_rollup(state), '章节独立汇总需要 workspace_version 31')
    from novel_writer.domain.deep_review import contains as has_deep_review
    _require(state['workspace_version']>=41 or not has_deep_review(state), '深层审核需要 workspace_version 41')
    if state['workspace_version']==1:state['document']=normalize_persistent_document(state['document'])
    _exact(state["document"], NovelDocument, "document")
    _require(state["document"]["schema_version"] == 1, "document.schema_version：仅支持版本 1")
    for index, version in enumerate(state["document"]["versions"]):
        _exact(version["snapshot"], MODEL_TYPES[version["entity_type"]], f"document.versions[{index}].snapshot", snapshot=True)
    _exact(state["ideas"], dict[str, str], "workspace.ideas")
    _exact(state["worldbuilding"], str, "workspace.worldbuilding")
    _exact(state["writing_rules"], str, "workspace.writing_rules")
    if state['workspace_version']>=2:
        from novel_writer.domain.memory import validate_memory_state
        validate_memory_state(state)
    if state['workspace_version']>=3:
        from novel_writer.domain.tasks import validate_task_state
        validate_task_state(state)
    if state['workspace_version']>=4:
        from novel_writer.domain.review import validate_review_state
        validate_review_state(state)
    if state['workspace_version']>=5:
        from novel_writer.domain.knowledge import validate_knowledge_state
        validate_knowledge_state(state)
    if state['workspace_version']>=6:
        from novel_writer.domain.model_contract import validate_model_state
        validate_model_state(state)
    if state['workspace_version']>=7:
        from novel_writer.domain.experiments import validate_experiment_state
        validate_experiment_state(state)
    if state['workspace_version']>=8:
        from novel_writer.domain.workflows import validate_workflow_state
        validate_workflow_state(state)
    if state['workspace_version']>=10:
        from novel_writer.domain.creation_presets import validate_creation_state
        validate_creation_state(state)
    if state['workspace_version']>=11:
        from novel_writer.domain.book_creation import validate_state as validate_book_creation
        validate_book_creation(state)
    if state['workspace_version']>=12:
        from novel_writer.domain.book_ai import validate_state as validate_book_ai
        validate_book_ai(state)
    if state['workspace_version']>=13:
        from novel_writer.domain.styles import validate_state as validate_styles
        validate_styles(state)
    if state['workspace_version']>=14:
        from novel_writer.domain.public_search import validate_state as validate_web
        validate_web(state)
    if state['workspace_version']>=15:
        from novel_writer.domain.style_trials import validate_state as validate_trials
        validate_trials(state)
    if state['workspace_version']>=16:
        from novel_writer.domain.chapter_writing import validate_state as validate_writing
        validate_writing(state)
    if state['workspace_version']>=17:
        from novel_writer.domain.chapter_planning import validate_state as validate_chapter_planning
        validate_chapter_planning(state)
    if state['workspace_version']>=18:
        from novel_writer.domain.scene_expansion import validate_state as validate_scene_expansion
        validate_scene_expansion(state)
    if state['workspace_version']>=19:
        from novel_writer.domain.chapter_lifecycle import validate_state as validate_chapter_lifecycle
        validate_chapter_lifecycle(state)
    if state['workspace_version']>=20:
        from novel_writer.domain.console import validate_state as validate_console
        validate_console(state)
    if state['workspace_version']>=46:
        from novel_writer.domain.rule_reviews import validate_state as validate_rule_reviews
        validate_rule_reviews(state)
    if state['workspace_version']>=21:
        from novel_writer.domain.scoped_rules import validate_state as validate_scoped_rules
        validate_scoped_rules(state)
    if state['workspace_version']>=23:
        from novel_writer.domain.memory_rollups import validate_state as validate_memory_rollups
        validate_memory_rollups(state)
    if state['workspace_version']>=25:
        from novel_writer.domain.materials import validate_state as validate_materials
        validate_materials(state)
    if state['workspace_version']>=26:
        from novel_writer.domain.full_book_planning import validate_state as validate_full_book_planning
        validate_full_book_planning(state)
    if state['workspace_version']>=27:
        from novel_writer.domain.chapter_trash import validate_state as validate_chapter_trash
        validate_chapter_trash(state)
    if state['workspace_version']>=41:
        from novel_writer.domain.deep_review import validate_state as validate_deep_review
        validate_deep_review(state)
    if state['workspace_version']>=42:
        from novel_writer.domain.incremental_memory import validate_state as validate_automation
        validate_automation(state)
    from novel_writer.domain.body_planning import validate_state as validate_body_planning
    validate_body_planning(state)
    if state['workspace_version']>=45:
        from novel_writer.domain.graph_extraction import validate_state as validate_graph
        validate_graph(state)
    from novel_writer.domain.graph_items import validate_state as validate_graph_items
    validate_graph_items(state)
    if state['workspace_version']>=49:
        from novel_writer.domain.semantic_retrieval import validate_state as validate_semantic
        validate_semantic(state)
    if state['workspace_version']>=50:
        from novel_writer.domain.memory_refresh import validate_state as validate_refresh
        validate_refresh(state)
    if state['workspace_version']>=52:
        from novel_writer.domain.console_background import validate_state as validate_background
        validate_background(state)
    if 'canon_maintenance_settings' in state:
        from novel_writer.domain.canon_maintenance import validate_state as validate_canon
        validate_canon(state)
    from novel_writer.domain.model_planning import validate_state as validate_model_planning
    validate_model_planning(state)
    if state['workspace_version']>=48:
        from novel_writer.domain.author_scope import validate_state
        validate_state(state)
    return state


def _resource_limits(connection, check):
    """SQL 只返回有界标量，在任何业务列取回 Python 前检查全库资源。"""
    total_rows = 0
    for table in _trusted_profile(connection.execute('PRAGMA user_version').fetchone()[0])['tables']:
        check()
        limit = min(MAX_TABLE_ROWS[table], MAX_DATABASE_ROWS)
        count = connection.execute(f"SELECT count(*) FROM (SELECT 1 FROM {table} LIMIT ?)", (limit + 1,)).fetchone()[0]
        _require(count <= MAX_TABLE_ROWS[table], f"{table}：记录数超过限额")
        total_rows += count
        _require(total_rows <= MAX_DATABASE_ROWS, "database：全库记录数超过限额")
    for table, columns in TABLE_COLUMNS.items():
        if table not in _trusted_profile(connection.execute('PRAGMA user_version').fetchone()[0])['tables']:continue
        check()
        lengths = [f"coalesce(length(CAST({name} AS BLOB)),0)" for name in columns]
        limits = [min(MAX_SQL_VALUE_BYTES, MAX_JSON_BYTES) if name in ("payload", "files_json")
                  else MAX_SQL_VALUE_BYTES for name in columns]
        oversized = connection.execute(f"SELECT 1 FROM {table} WHERE "
                                       + " OR ".join(f"{size} > ?" for size in lengths) + " LIMIT 1", limits).fetchone()
        _require(oversized is None, f"{table}：SQL 列字节超过限额")
        oversized_row = connection.execute(f"SELECT 1 FROM {table} WHERE " + "+".join(lengths)
                                           + " > ? LIMIT 1", (MAX_SQL_ROW_BYTES,)).fetchone()
        _require(oversized_row is None, f"{table}：SQL 整行字节超过限额")
    # 项目 ID 在 scope 和 counts 各出现一次；Skills ID 在 scope 出现一次。
    # 聚合只返回整数，防止先将巨大的 ID 载入列表再发现清单越限。
    project_ids = connection.execute("SELECT coalesce(sum(length(CAST(id AS BLOB))),0) FROM projects").fetchone()[0]
    skill_ids = connection.execute("SELECT coalesce(sum(length(CAST(id AS BLOB))),0) FROM skills").fetchone()[0]
    _require(2 * project_ids + skill_ids <= MAX_MANIFEST_ID_BYTES, "manifest：清单 ID 字节总量超过限额")


def _rows(connection, table, *, where="", parameters=(), order="", check):
    columns = TABLE_COLUMNS[table]
    suffix = (" WHERE " + where if where else "") + (" ORDER BY " + order if order else "")
    # 全库各列与整行的字节限额已在 _resource_limits 中用标量查询核对。
    for values in connection.execute(f"SELECT {','.join(columns)} FROM {table}{suffix}", parameters):
        check()
        row = dict(zip(columns, values))
        for name, value in row.items():
            if name == "revision":
                _require(type(value) is int and value >= 1, f"{table}.revision：SQL 值必须为正整数")
            else:
                _require(type(value) is str, f"{table}.{name}：SQL 值必须为非 NULL 的 TEXT")
                try:
                    value.encode("utf-8", errors="strict")
                except UnicodeError:
                    raise BackupValidationError(f"{table}.{name}：UTF-8 编码无效") from None
                if name in ("id", "project_id"):
                    _require(bool(value.strip()), f"{table}.{name}：ID 不能为空")
                if name in ("updated_at", "saved_at", "imported_at"):
                    try:
                        _timestamp(value, name)
                    except (ValueError, TypeError):
                        raise BackupValidationError(f"{table}.{name}：必须为 UTC ISO 8601 时间") from None
        yield row


def validate_database(path: str | Path, *, check=None) -> dict:
    """只读验证冻结三表与全历史，返回可直接写入 manifest 的真实结构和计数。"""
    check = check or (lambda: None)
    check()
    path = Path(path).resolve()
    callback_error = []

    def progress():
        try:
            check()
            return 0
        except BaseException as error:
            callback_error.append(error)
            return 1

    try:
        _require(path.is_file(), "database：输入快照文件不存在")
        _require(not any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")),
                 "database：冻结快照不能带 WAL、SHM 或 journal")
        with path.open("rb") as stream:
            header = stream.read(100)
        _require(len(header) == 100 and header[:16] == b"SQLite format 3\0", "database：SQLite 文件头无效")
        _require(header[18:20] == b"\x01\x01", "database：冻结快照必须为独立的非 WAL 数据库")
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)) as connection:
            # SQLite 本身也限制记录物化大小；64 KiB 只给记录头等编码开销留余量。
            connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_SQL_ROW_BYTES + 64 * 1024)
            connection.execute("PRAGMA query_only=ON")
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.set_progress_handler(progress, 1000)
            connection.execute("BEGIN")
            return validate_connection(connection, check=check)
    except BackupValidationError:
        # validate_connection may classify SQLite's interruption as an integrity
        # read error; the progress callback's original exception takes priority.
        if callback_error:
            raise callback_error[0]
        raise
    except sqlite3.Error:
        if callback_error:
            raise callback_error[0]
        raise BackupValidationError("database：SQLite 读取或完整性校验失败") from None
    except (DataValidationError, KeyError, TypeError, UnicodeError, RecursionError):
        raise BackupValidationError("payload：持久字段、历史快照语义或引用关联校验失败") from None
    except OSError:
        raise BackupValidationError("database：快照文件读取失败") from None


def validate_connection(connection, *, check=None):
    """复用严格三表/全历史预检；调用者持有读事务或BEGIN IMMEDIATE锁。"""
    check = check or (lambda: None)
    connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_SQL_ROW_BYTES + 64 * 1024)
    database = _schema(connection, check)
    check()
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.Error:
        raise BackupValidationError("database.integrity_check：数据库完整性读取失败") from None
    _require(integrity == [("ok",)], "database.integrity_check：数据库完整性失败")
    _resource_limits(connection, check)
    _require(connection.execute("PRAGMA foreign_key_check").fetchone() is None, "database.foreign_key_check：外键关联失败")
    counts = {"projects": [], "skills": 0}
    project_ids, skill_ids = [], []
    metadata_bytes = len(json.dumps({"database": database, "counts": counts,
        "project_ids": [], "skill_ids": []}, ensure_ascii=False, indent=2).encode("utf-8")) + 64

    def claim_metadata(value, padding):
        nonlocal metadata_bytes
        # indent=8 保守覆盖最终 manifest 中 counts.projects 的缩进。
        metadata_bytes += len(json.dumps(value, ensure_ascii=False, indent=8).encode("utf-8")) + padding
        _require(metadata_bytes <= MAX_REPORT_BYTES, "manifest：清单元数据字节超过限额")

    claim_metadata(None, 0)
    snapshot_count = 0
    for project in _rows(connection, "projects", order="id", check=check):
        state = _workspace(project["payload"])
        database['workspace_version']=max(database['workspace_version'],state['workspace_version'])
        document = state["document"]
        project_id = project["id"]
        _require(project_id == document["project"]["id"] and project["title"] == document["project"]["title"]
                 and project["revision"] == state["revision"], "projects：SQL 与 payload 项目元信息不一致")
        history = WorkspaceHistoryValidator()
        revision, latest, saved_at = 0, None, None
        latest_raw=None
        for row in _rows(connection, "project_snapshots", where="project_id=?", parameters=(project_id,), order="revision", check=check):
            historical = _workspace(row["payload"])
            latest_raw=strict_loads(row['payload'])
            database['workspace_version']=max(database['workspace_version'],historical['workspace_version'])
            revision += 1
            _require(row["revision"] == revision and historical["revision"] == revision,
                     "project_snapshots.revision：整书 revision 必须连续且与 payload 一致")
            _require(historical["document"]["project"]["id"] == project_id,
                     "project_snapshots.project_id：历史项目归属不一致")
            latest = history.validate(historical)
            saved_at = row["saved_at"]
        _require(revision == project["revision"], "project_snapshots：缺失整书历史")
        _require(latest == state and saved_at == project["updated_at"], "projects：当前状态或时间与最新快照不一致")
        _require(strict_loads(project['payload'])==latest_raw,'projects：当前原始表示与最新快照不一致')
        # 当前 payload 也独立验证，不以 JSON 相等掩盖 Python bool/int 的相等性。
        validate_workspace(state)
        project_count = {"project_id": project_id, "revision": revision,
            "chapters": len(document["chapters"]), "characters": len(document["characters"]),
            "chapter_outlines": len(document["chapter_outlines"]), "entity_versions": len(document["versions"]),
            "project_snapshots": revision}
        if state['workspace_version']>=2:
            project_count.update(memories=len(state['memories']),memory_edits=len(state['memory_history']))
        if state['workspace_version']>=3:
            project_count.update(generation_tasks=len(state['generation_tasks']),task_events=len(state['task_events']),generation_candidates=len(state['generation_candidates']),adoption_receipts=len(state['adoption_receipts']))
        if state['workspace_version']>=4:
            from novel_writer.domain.review import REVIEW_COLLECTIONS
            project_count.update({name:len(state[name]) for name in REVIEW_COLLECTIONS})
        if state['workspace_version']>=5:
            from novel_writer.domain.knowledge import KNOWLEDGE_COLLECTIONS
            project_count.update({name:len(state[name]) for name in KNOWLEDGE_COLLECTIONS})
        if state['workspace_version']>=6:
            from novel_writer.domain.model_contract import MODEL_COLLECTIONS
            project_count.update({name:len(state[name]) for name in MODEL_COLLECTIONS})
        if state['workspace_version']>=7:
            from novel_writer.domain.experiments import EXPERIMENT_COLLECTIONS
            project_count.update({name:len(state[name]) for name in EXPERIMENT_COLLECTIONS})
        if state['workspace_version']>=8:
            from novel_writer.domain.workflows import WORKFLOW_COLLECTIONS
            project_count.update({name:len(state[name]) for name in WORKFLOW_COLLECTIONS})
        if state['workspace_version']>=10:
            from novel_writer.domain.creation_presets import CREATION_COLLECTIONS
            project_count.update({name:len(state[name]) for name in CREATION_COLLECTIONS})
        if state['workspace_version']>=11:
            from novel_writer.domain.book_creation import COLLECTIONS as BOOK_CREATION_COLLECTIONS
            project_count.update({name:len(state[name]) for name in BOOK_CREATION_COLLECTIONS})
        if state['workspace_version']>=12:
            from novel_writer.domain.book_ai import COLLECTIONS as BOOK_AI_COLLECTIONS
            project_count.update({name:len(state[name]) for name in BOOK_AI_COLLECTIONS})
        if state['workspace_version']>=13:
            from novel_writer.domain.styles import COLLECTIONS as STYLE_COLLECTIONS
            from novel_writer.storage.content_blobs import validate_refs
            validate_refs(connection,state)
            project_count.update({name:len(state[name]) for name in STYLE_COLLECTIONS})
        if state['workspace_version']>=14:
            from novel_writer.domain.public_search import COLLECTIONS as WEB_COLLECTIONS
            project_count.update({name:len(state[name]) for name in WEB_COLLECTIONS})
        if state['workspace_version']>=15:
            from novel_writer.domain.style_trials import COLLECTIONS as TRIAL_COLLECTIONS
            project_count.update({name:len(state[name]) for name in TRIAL_COLLECTIONS})
        if state['workspace_version']>=16:
            from novel_writer.domain.chapter_writing import COLLECTIONS as WRITING_COLLECTIONS
            project_count.update({name:len(state[name]) for name in WRITING_COLLECTIONS})
        if state['workspace_version']>=17:
            from novel_writer.domain.chapter_planning import COLLECTIONS as PLANNING_COLLECTIONS
            project_count.update({name:len(state[name]) for name in PLANNING_COLLECTIONS})
        if state['workspace_version']>=18:
            from novel_writer.domain.scene_expansion import COLLECTIONS as EXPANSION_COLLECTIONS
            project_count.update({name:len(state[name]) for name in EXPANSION_COLLECTIONS})
        if state['workspace_version']>=19:
            from novel_writer.domain.chapter_lifecycle import COLLECTIONS as LIFECYCLE_COLLECTIONS
            project_count.update({name:len(state[name]) for name in LIFECYCLE_COLLECTIONS})
        if state['workspace_version']>=20:
            from novel_writer.domain.console import COLLECTIONS as CONSOLE_COLLECTIONS
            project_count.update({name:len(state[name]) for name in CONSOLE_COLLECTIONS})
        if state['workspace_version']>=21:
            project_count['scoped_rules']=len(state['scoped_rules'])
        if state['workspace_version']>=22:
            project_count['scoped_rule_history']=len(state['scoped_rule_history'])
        if state['workspace_version']>=46:
            from novel_writer.domain.rule_reviews import COLLECTIONS as RULE_REVIEW_COLLECTIONS
            for name in RULE_REVIEW_COLLECTIONS:project_count[name]=len(state[name])
        if state['workspace_version']>=36:
            project_count['rule_task_bindings']=len(state['rule_task_bindings'])
        if state['workspace_version']>=23:
            project_count['memory_rollups']=len(state['memory_rollups'])
            project_count['memory_rollup_history']=len(state['memory_rollup_history'])
        if state['workspace_version']>=24:
            from novel_writer.domain.console import RUN_COLLECTIONS
            project_count.update({name:len(state[name]) for name in RUN_COLLECTIONS})
        if state['workspace_version']>=25:
            from novel_writer.domain.materials import COLLECTIONS as MATERIAL_COLLECTIONS
            project_count.update({name:len(state[name]) for name in MATERIAL_COLLECTIONS})
        if state['workspace_version']>=26:
            from novel_writer.domain.full_book_planning import COLLECTIONS as PLANNING_V26_COLLECTIONS
            project_count.update({name:len(state[name]) for name in PLANNING_V26_COLLECTIONS})
        if state['workspace_version']>=27:
            from novel_writer.domain.chapter_trash import COLLECTIONS as TRASH_COLLECTIONS
            project_count.update({name:len(state[name]) for name in TRASH_COLLECTIONS})
        if state['workspace_version']>=41:project_count['deep_review_actions']=len(state['deep_review_actions'])
        if state['workspace_version']>=43:
            from novel_writer.domain.body_planning import COLLECTIONS as BODY_PLANNING_COLLECTIONS
            project_count.update({name:len(state[name]) for name in BODY_PLANNING_COLLECTIONS})
        if state['workspace_version']>=47:
            from novel_writer.domain.model_planning import COLLECTIONS as MODEL_PLANNING_COLLECTIONS
            project_count.update({name:len(state[name]) for name in MODEL_PLANNING_COLLECTIONS})
        if state['workspace_version']>=48:project_count['author_scope_events']=len(state['author_scope_events'])
        if state['workspace_version']>=49:
            from novel_writer.domain.semantic_retrieval import COLLECTIONS as SEMANTIC_COLLECTIONS
            project_count.update({name:len(state[name]) for name in SEMANTIC_COLLECTIONS})
        if state['workspace_version']>=50:project_count['memory_refresh_events']=len(state['memory_refresh_events'])
        if state['workspace_version']>=51:project_count['graph_item_decisions']=len(state['graph_item_decisions'])
        if state['workspace_version']>=52:
            from novel_writer.domain.console_background import COLLECTIONS as BACKGROUND_COLLECTIONS
            project_count.update({name:len(state[name]) for name in BACKGROUND_COLLECTIONS})
        if 'canon_maintenance_settings' in state:
            from novel_writer.domain.canon_maintenance import COLLECTIONS as CANON_COLLECTIONS
            project_count.update({name:len(state[name]) for name in CANON_COLLECTIONS})
        claim_metadata(project_count, 32)
        claim_metadata(project_id, 16)
        project_ids.append(project_id)
        snapshot_count += revision
        counts["projects"].append(project_count)
    from novel_writer.application.skill_import import _validated_files
    for skill in _rows(connection, "skills", order="id", check=check):
        files = strict_loads(skill["files_json"])
        _, primary = _validated_files(files)
        _require(skill["primary_path"] == primary["path"], "skills.primary_path：与唯一 SKILL.md 的精确路径不一致")
        claim_metadata(skill["id"], 16)
        skill_ids.append(skill["id"])
    counts["skills"] = len(skill_ids)
    actual_counts = {"projects": len(project_ids), "project_snapshots": snapshot_count, "skills": len(skill_ids)}
    if database['sqlite_user_version']==2:
        from novel_writer.storage.content_blobs import decode
        amount=0
        for blob in _rows(connection,'content_blobs',check=check):decode(blob['data_base64'],blob['sha256']);amount+=1
        actual_counts['content_blobs']=amount;counts['content_blobs']=amount
    for table in database["tables"]:
        actual_count = connection.execute(f'SELECT count(*) FROM {table["name"]}').fetchone()[0]
        _require(actual_count == actual_counts[table["name"]], f'{table["name"]}：存在孤立或未校验记录')
        table["rows"] = actual_count
    check()
    report = {"database": database, "counts": counts, "project_ids": project_ids, "skill_ids": skill_ids}
    # 最终精确检查同样流式计数，不为校验再分配一个完整清单字符串。
    encoded_bytes = 0
    for piece in json.JSONEncoder(ensure_ascii=False, indent=2).iterencode(report):
        encoded_bytes += len(piece.encode("utf-8"))
        _require(encoded_bytes <= MAX_REPORT_BYTES, "manifest：清单元数据字节超过限额")
    return report
