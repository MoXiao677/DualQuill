"""小说基础数据模型；这里只定义数据与校验，不执行写入或模型调用。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, fields, is_dataclass, replace
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from types import MappingProxyType, UnionType
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints
from uuid import uuid4

@lru_cache(maxsize=32)
def _model_type_hints(model):
    # Only immutable Python type metadata is reused. Author values, snapshot
    # bytes, version links and timestamps are validated on every invocation.
    return MappingProxyType(get_type_hints(model))


ProjectStatus = Literal["planning", "writing", "completed", "archived"]
OutlineStatus = Literal["draft", "ready"]
ChapterStatus = Literal["draft", "confirmed"]
EntityType = Literal["project", "book_outline", "chapter_outline", "character", "chapter"]


def new_id() -> str:
    """创建不依赖名称和章节顺序的稳定编号。"""
    return str(uuid4())


def utc_now() -> str:
    """创建带时区的 UTC 时间字符串。"""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class DataValidationError(ValueError):
    """小说文档存在格式错误或无法解析的关联。"""


@dataclass(kw_only=True)
class Entity:
    id: str = field(default_factory=new_id)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass(kw_only=True)
class ProjectEntity(Entity):
    project_id: str


@dataclass(kw_only=True)
class NovelProject(Entity):
    title: str
    author: str = ""
    genre: str = ""
    summary: str = ""
    language: str = "zh-CN"
    status: ProjectStatus = "planning"


@dataclass(kw_only=True)
class VolumePlan:
    number: int
    title: str
    summary: str = ""
    chapter_ids: list[str] = field(default_factory=list)


@dataclass(kw_only=True)
class BookOutline(ProjectEntity):
    theme: str = ""
    premise: str = ""
    main_plot: str = ""
    ending: str = ""
    key_events: list[str] = field(default_factory=list)
    volumes: list[VolumePlan] = field(default_factory=list)
    status: OutlineStatus = "draft"


@dataclass(kw_only=True)
class CharacterRelationship:
    target_character_id: str
    relation: str
    description: str = ""


@dataclass(kw_only=True)
class Character(ProjectEntity):
    name: str
    role: str = ""
    personality: str = ""
    background: str = ""
    goals: list[str] = field(default_factory=list)
    notes: str = ""
    relationships: list[CharacterRelationship] = field(default_factory=list)


@dataclass(kw_only=True)
class ScenePlan:
    order: int
    summary: str
    character_ids: list[str] = field(default_factory=list)
    location: str = ""
    story_time: str = ""


@dataclass(kw_only=True)
class ChapterOutline(ProjectEntity):
    chapter_id: str
    core_idea: str = ""
    objective: str = ""
    character_ids: list[str] = field(default_factory=list)
    scenes: list[ScenePlan] = field(default_factory=list)
    story_time: str = ""
    status: OutlineStatus = "draft"


@dataclass(kw_only=True)
class Chapter(ProjectEntity):
    number: int
    title: str
    content: str = ""
    status: ChapterStatus = "draft"
    current_version_id: str | None = None


@dataclass(kw_only=True)
class VersionRecord:
    project_id: str
    entity_type: EntityType
    entity_id: str
    version_number: int
    snapshot: dict[str, Any]
    id: str = field(default_factory=new_id)
    created_at: str = field(default_factory=utc_now)
    previous_version_id: str | None = None
    change_note: str = ""
    source: Literal["manual"] = "manual"


@dataclass(kw_only=True)
class NovelDocument:
    project: NovelProject
    schema_version: int = 1
    book_outline: BookOutline | None = None
    chapter_outlines: list[ChapterOutline] = field(default_factory=list)
    characters: list[Character] = field(default_factory=list)
    chapters: list[Chapter] = field(default_factory=list)
    versions: list[VersionRecord] = field(default_factory=list)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DataValidationError(message)


def _check_json_value(value: Any, path: str) -> None:
    if type(value) in (str, int, bool, type(None)):
        return
    if type(value) is float:
        _require(math.isfinite(value), f"{path} 不能包含 NaN 或无穷大")
        return
    if type(value) is list:
        for index, item in enumerate(value):
            _check_json_value(item, f"{path}[{index}]")
        return
    if type(value) is dict:
        for key, item in value.items():
            _require(type(key) is str, f"{path} 的 JSON 键必须是字符串")
            _check_json_value(item, f"{path}.{key}")
        return
    raise DataValidationError(f"{path} 必须是可保存到 JSON 的值")


def _check_type(value: Any, expected: Any, path: str, *, snapshot: bool = False) -> None:
    """检查声明的字段类型，尤其避免把布尔值当成章节编号。"""
    if expected is str or expected is int or expected is float or expected is bool or expected is type(None):
        # Same exact primitive check; avoid generic typing/dataclass reflection
        # for every scalar in thousands of immutable entity snapshots.
        _require(type(value) is expected, f"{path} 类型错误，应为 {expected.__name__}")
        return
    if expected is Any:
        _check_json_value(value, path)
        return
    origin, arguments = get_origin(expected), get_args(expected)
    if origin in (UnionType, Union):
        for alternative in arguments:
            try:
                _check_type(value, alternative, path, snapshot=snapshot)
                return
            except DataValidationError:
                pass
        raise DataValidationError(f"{path} 类型错误")
    if origin is Literal:
        _require(value in arguments, f"{path} 必须是 {arguments} 中的一项")
        return
    if origin is list:
        _require(type(value) is list, f"{path} 必须是列表")
        for index, item in enumerate(value):
            _check_type(item, arguments[0], f"{path}[{index}]", snapshot=snapshot)
        return
    if origin is dict:
        _require(type(value) is dict, f"{path} 必须是字典")
        for key, item in value.items():
            _check_type(key, arguments[0], f"{path} 的键", snapshot=snapshot)
            _check_type(item, arguments[1], f"{path}.{key}", snapshot=snapshot)
        return
    if snapshot and is_dataclass(expected):
        _require(type(value) is dict, f"{path} 必须是内容快照对象")
        snapshot_fields = [item for item in fields(expected) if item.name != "current_version_id"]
        names = {item.name for item in snapshot_fields}
        _require(set(value) == names, f"{path} 必须包含完整的内容字段；章节快照不含 current_version_id")
        hints = _model_type_hints(expected)
        for item in snapshot_fields:
            _check_type(value[item.name], hints[item.name], f"{path}.{item.name}", snapshot=True)
        return
    _require(type(value) is expected, f"{path} 类型错误，应为 {expected.__name__}")
    if is_dataclass(value):
        hints = _model_type_hints(expected)
        for item in fields(value):
            field_value = getattr(value, item.name)
            field_path = f"{path}.{item.name}"
            _check_type(field_value, hints[item.name], field_path)
            if item.name == "id" or item.name.endswith("_id"):
                _require(field_value is None or bool(field_value.strip()), f"{field_path} 不能为空")


def _timestamp(value: str, path: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
    except ValueError as error:
        raise DataValidationError(f"{path} 必须是 ISO 8601 时间") from error
    _require(result.utcoffset() == timedelta(0), f"{path} 必须包含 UTC 时区")
    return result


def _unique_positive_numbers(values: list[int], label: str) -> None:
    _require(all(value >= 1 for value in values), f"{label}必须从 1 开始")
    _require(len(values) == len(set(values)), f"{label}不能重复")


def validate_snapshot_references(version: VersionRecord, *, chapter_ids: set[str], character_ids: set[str]) -> None:
    """检查版本首现时的外部引用；调用方必须提供可核对的整书上下文。"""
    snapshot, kind = version.snapshot, version.entity_type
    if kind == "book_outline":
        _require(all(identifier in chapter_ids for volume in snapshot["volumes"] for identifier in volume["chapter_ids"]),
                 "历史章节关联缺失或上下文不足")
    elif kind == "character":
        _require(all(item["target_character_id"] in character_ids for item in snapshot["relationships"]),
                 "历史人物关联缺失或上下文不足")
    elif kind == "chapter_outline":
        _require(snapshot["chapter_id"] in chapter_ids, "历史细纲章节关联缺失或上下文不足")
        _require(all(identifier in character_ids for identifier in snapshot["character_ids"]),
                 "历史细纲人物关联缺失或上下文不足")
        _require(all(identifier in character_ids for scene in snapshot["scenes"] for identifier in scene["character_ids"]),
                 "历史场景人物关联缺失或上下文不足")


def _validate_snapshot_semantics(version: VersionRecord) -> None:
    snapshot, kind = version.snapshot, version.entity_type
    if kind in ("project", "chapter"):
        _require(bool(snapshot["title"].strip()), "历史快照标题不能为空")
    if kind == "chapter":
        _unique_positive_numbers([snapshot["number"]], "历史章节顺序")
    elif kind == "character":
        _require(bool(snapshot["name"].strip()), "历史快照人物姓名不能为空")
    elif kind == "book_outline":
        _unique_positive_numbers([item["number"] for item in snapshot["volumes"]], "历史分卷顺序")
        assigned = [identifier for item in snapshot["volumes"] for identifier in item["chapter_ids"]]
        _require(len(assigned) == len(set(assigned)), "历史快照中同一章节不能重复分卷")
    elif kind == "chapter_outline":
        _unique_positive_numbers([item["order"] for item in snapshot["scenes"]], "历史场景顺序")


def validate_document(document: NovelDocument, *, _validated_version_ids=frozenset()) -> None:
    """校验当前数据的类型、跨对象关联和线性版本链；失败时抛出中文异常。"""
    # The history reader may supply IDs only after matching each complete raw
    # record's values AND scalar/container types to a previously validated one.
    # Current entities,
    # all membership/identity checks and every newly seen version still run.
    typed=document if not _validated_version_ids else replace(document,versions=[v for v in document.versions if v.id not in _validated_version_ids])
    _check_type(typed, NovelDocument, "document")
    _require(document.schema_version == 1, "不支持此 schema_version；当前只支持 1")
    _require(bool(document.project.title.strip()), "小说书名不能为空")
    project_id = document.project.id
    project_entities: list[ProjectEntity] = [
        *document.characters, *document.chapters, *document.chapter_outlines,
    ]
    if document.book_outline is not None:
        project_entities.append(document.book_outline)
    all_records = [document.project, *project_entities, *document.versions]
    identifiers = [item.id for item in all_records]
    _require(len(identifiers) == len(set(identifiers)), "文档中的记录 ID 不能重复")

    for item in [*project_entities, *document.versions]:
        _require(item.project_id == project_id, f"记录 {item.id} 不属于当前小说")
    for item in all_records:
        if isinstance(item,VersionRecord) and item.id in _validated_version_ids:
            continue
        created = _timestamp(item.created_at, f"{item.id}.created_at")
        if isinstance(item, Entity):
            updated = _timestamp(item.updated_at, f"{item.id}.updated_at")
            _require(updated >= created, f"{item.id} 的更新时间不能早于创建时间")

    chapters = {item.id: item for item in document.chapters}
    characters = {item.id: item for item in document.characters}
    _unique_positive_numbers([item.number for item in document.chapters], "章节顺序")
    for chapter in document.chapters:
        _require(bool(chapter.title.strip()), f"章节 {chapter.id} 的标题不能为空")
    for character in document.characters:
        _require(bool(character.name.strip()), f"人物 {character.id} 的姓名不能为空")
        for relation in character.relationships:
            _require(relation.target_character_id in characters, f"人物关系引用了不存在的人物：{relation.target_character_id}")

    if document.book_outline is not None:
        volumes = document.book_outline.volumes
        _unique_positive_numbers([item.number for item in volumes], "分卷顺序")
        assigned = [chapter_id for volume in volumes for chapter_id in volume.chapter_ids]
        _require(len(assigned) == len(set(assigned)), "同一章节不能重复分配到分卷")
        _require(all(chapter_id in chapters for chapter_id in assigned), "分卷引用了不存在的章节")

    outline_chapters = [item.chapter_id for item in document.chapter_outlines]
    _require(len(outline_chapters) == len(set(outline_chapters)), "每章最多有一份当前细纲")
    for outline in document.chapter_outlines:
        _require(outline.chapter_id in chapters, f"细纲引用了不存在的章节：{outline.chapter_id}")
        _require(all(item in characters for item in outline.character_ids), f"细纲 {outline.id} 引用了不存在的人物")
        _unique_positive_numbers([item.order for item in outline.scenes], "场景顺序")
        for scene in outline.scenes:
            _require(all(item in characters for item in scene.character_ids), f"细纲 {outline.id} 的场景引用了不存在的人物")

    targets = {
        "project": {project_id: document.project},
        "book_outline": {} if document.book_outline is None else {document.book_outline.id: document.book_outline},
        "chapter_outline": {item.id: item for item in document.chapter_outlines},
        "character": characters,
        "chapter": chapters,
    }
    versions = {item.id: item for item in document.versions}
    version_keys = [(item.entity_type, item.entity_id, item.version_number) for item in document.versions]
    _require(len(version_keys) == len(set(version_keys)), "同一内容的版本号不能重复")
    for version in document.versions:
        _require(version.entity_id in targets[version.entity_type], f"版本 {version.id} 引用了不存在的内容")
        if version.id in _validated_version_ids:
            continue
        target = targets[version.entity_type][version.entity_id]
        _check_type(version.snapshot, type(target), f"版本 {version.id} 的快照", snapshot=True)
        _validate_snapshot_semantics(version)
        snapshot_created = _timestamp(version.snapshot["created_at"], f"{version.id}.snapshot.created_at")
        snapshot_updated = _timestamp(version.snapshot["updated_at"], f"{version.id}.snapshot.updated_at")
        _require(snapshot_updated >= snapshot_created, "快照的更新时间不能早于创建时间")
        _require(_timestamp(version.created_at, version.id) >= snapshot_updated, "版本保存时间不能早于快照的更新时间")
        _require(version.version_number >= 1, "版本号必须从 1 开始")
        _require(version.snapshot.get("id") == version.entity_id, f"版本 {version.id} 的快照编号与目标不一致")
        if version.entity_type != "project":
            _require(version.snapshot.get("project_id") == project_id, f"版本 {version.id} 的快照不属于当前小说")
        if version.version_number == 1:
            _require(version.previous_version_id is None, "第 1 版不能引用上一版")
        else:
            previous = versions.get(version.previous_version_id)
            _require(previous is not None, f"版本 {version.id} 缺少上一版")
            _require((previous.entity_type, previous.entity_id) == (version.entity_type, version.entity_id), "上一版本必须属于同一内容")
            _require(previous.version_number + 1 == version.version_number, "版本号必须沿版本链逐次递增")
            _require(_timestamp(version.created_at, version.id) >= _timestamp(previous.created_at, previous.id), "新版保存时间不能早于上一版")

    for chapter in document.chapters:
        if chapter.status == "confirmed":
            _require(chapter.current_version_id is not None, f"已确认章节 {chapter.id} 必须关联保存版本")
        if chapter.current_version_id is not None:
            current = versions.get(chapter.current_version_id)
            _require(current is not None, f"章节 {chapter.id} 的当前版本不存在")
            _require((current.entity_type, current.entity_id) == ("chapter", chapter.id), "章节的当前版本必须属于该章节正文")
