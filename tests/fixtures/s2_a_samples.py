"""S2-A 专用虚构样本及设计断言；不被应用导入，不提供备份/恢复入口。"""
from copy import deepcopy
from contextlib import closing
from dataclasses import asdict, fields
import json
from pathlib import Path
import sqlite3
import sys
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from novel_writer.domain.models import (
    BookOutline, Chapter, ChapterOutline, Character, CharacterRelationship,
    NovelDocument, NovelProject, ScenePlan, VersionRecord, VolumePlan,
)
from novel_writer.storage.json_codec import document_from_dict
from novel_writer.storage.sqlite_repository import SQLiteRepository, validate_workspace
from novel_writer.storage.skills_repository import SkillsRepository

MODEL_TYPES = {
    "project": NovelProject, "book_outline": BookOutline, "character": Character,
    "chapter": Chapter, "chapter_outline": ChapterOutline,
}
TABLE_COLUMNS = {
    "projects": ["id", "title", "revision", "payload", "updated_at"],
    "project_snapshots": ["project_id", "revision", "payload", "saved_at"],
    "skills": ["id", "name", "description", "imported_at", "primary_path", "files_json"],
}


def stamp(index=0):
    return f"2026-10-14T00:00:{index:02d}+00:00"


def _entity(identifier, project_id=None):
    value = {"id": identifier, "created_at": stamp(), "updated_at": stamp()}
    if project_id is not None:
        value["project_id"] = project_id
    return value


def _record(entity, kind, project_id, index=1, previous=None):
    snapshot = asdict(entity)
    snapshot.pop("current_version_id", None)
    return VersionRecord(
        id=f"shared-{kind}-version-{index}", project_id=project_id, entity_type=kind,
        entity_id=entity.id, version_number=index, snapshot=snapshot,
        created_at=stamp(index + 1), previous_version_id=previous,
        change_note=f"虚构 {kind} 第{index}版", source="manual")


def build_dataset():
    result = {"fixture_version": 1, "projects": [], "project_snapshots": [], "skills": []}
    for project_id in ("s2-a-project-one", "s2-a-project-two"):
        project = NovelProject(**_entity(project_id), title="同名虚构小说", author="虚构测试作者",
                               genre="测试", summary="仅作样本", language="zh-CN", status="writing")
        chapters = [
            Chapter(**_entity("shared-chapter-1", project_id), number=1, title="同名章节",
                    content="\n\n虚构中文正文🙂。旧ID文本 shared-chapter-1 保持原样。\r\n尾空格  \n", status="confirmed"),
            Chapter(**_entity("shared-chapter-2", project_id), number=2, title="同名章节",
                    content="第二章虚构正文。", status="draft"),
        ]
        characters = [
            Character(**_entity("shared-character-1", project_id), name="同名人物", role="主角",
                      personality="谨慎", background="虚构港口", goals=["查证", "返回"], notes="角色备注",
                      relationships=[CharacterRelationship(target_character_id="shared-character-2",
                                                          relation="同伴", description="虚构关系")]),
            Character(**_entity("shared-character-2", project_id), name="同名人物", role="配角",
                      personality="直率", background="虚构灯塔", goals=["保存日志"], notes="另一备注"),
        ]
        outline = BookOutline(**_entity("shared-book-outline", project_id), theme="信任", premise="虚构来信",
                              main_plot="查找日志", ending="公开记录", key_events=["收到信", "找到日志"],
                              volumes=[VolumePlan(number=1, title="第一卷", summary="虚构分卷",
                                                  chapter_ids=["shared-chapter-1"]),
                                       VolumePlan(number=2, title="第二卷", summary="另一分卷",
                                                  chapter_ids=["shared-chapter-2"])], status="ready")
        detail = ChapterOutline(**_entity("shared-chapter-outline", project_id), chapter_id="shared-chapter-1",
                                core_idea="打开信封", objective="发现线索", character_ids=["shared-character-1"],
                                scenes=[ScenePlan(order=1, summary="读信", character_ids=["shared-character-2"],
                                                  location="雾港", story_time="虚构第一日")],
                                story_time="虚构清晨", status="ready")
        document = NovelDocument(project=project, schema_version=1, book_outline=outline,
                                 chapter_outlines=[detail], characters=characters, chapters=chapters)
        for kind, entity in (("project", project), ("book_outline", outline),
                             ("chapter_outline", detail), ("character", characters[0]), ("chapter", chapters[0])):
            version = _record(entity, kind, project_id)
            document.versions.append(version)
            if kind == "chapter":
                entity.current_version_id = version.id
        state = {"workspace_version": 1, "revision": 1, "document": asdict(document),
                 "ideas": {"shared-chapter-1": "\nIDEA 原文  \n", "shared-chapter-2": "另一灵感"},
                 "worldbuilding": "\ufeff虚构世界观\r\n灯塔与组织。", "writing_rules": "第三人称\n保留标点和空格  "}
        for revision in (1, 2, 3):
            state["revision"] = revision
            if revision == 2:
                document.chapters[0].content += "\n第二版。"
                document.chapters[0].updated_at = stamp(3)
                version = _record(document.chapters[0], "chapter", project_id, 2, document.versions[-1].id)
                document.versions.append(version)
                document.chapters[0].current_version_id = version.id
                document.project.updated_at = stamp(3)
                state["document"] = asdict(document)
            if revision == 3:
                # 整书 revision 增长，但实体版本列表保持；对应实际资料保存行为。
                state["ideas"]["shared-chapter-1"] += "资料保存。"
                state["worldbuilding"] += "\n新版世界观。"
                state["writing_rules"] += "\n新版规则。"
                state["document"]["project"]["updated_at"] = stamp(5)
            result["project_snapshots"].append({"project_id": project_id, "revision": revision,
                                                 "payload": deepcopy(state), "saved_at": stamp(revision + 10)})
        result["projects"].append({"id": project_id, "title": project.title, "revision": 3,
                                   "payload": deepcopy(state), "updated_at": stamp(13)})
    files = [{"path": "教材/notes/例子.md", "content": "\n原文包含 shared-character-1。\r\n末尾空格  "},
             {"path": "教材/SKILL.md", "content": "\ufeff---\r\nname: 同名虚构技能\r\ndescription: 样本\r\n---\r\n\r\n# 原文\r\n"}]
    for index in (1, 2, 3):
        skill_files = deepcopy(files)
        if index == 3:
            skill_files[0]["content"] += "另一独立资料。"
        result["skills"].append({"id": f"s2-a-skill-{index}", "name": "同名虚构技能", "description": "独立记录",
                                 "imported_at": stamp(), "primary_path": "教材/SKILL.md", "files_json": skill_files})
    return result


def create_fixture_database(path, dataset):
    """只创建新的虚构库；显式列名插入，不调用会重设历史元数据的 create/save。"""
    path = Path(path)
    if path.exists():
        raise ValueError("虚构样本目标必须是不存在的新文件")
    SQLiteRepository(path)
    SkillsRepository(path)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("PRAGMA foreign_keys=ON")
        for table in TABLE_COLUMNS:
            columns = TABLE_COLUMNS[table]
            for row in dataset[table]:
                values = [json.dumps(row[name], ensure_ascii=False, allow_nan=False) if name in ("payload", "files_json")
                          else row[name] for name in columns]
                connection.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", values)


def inspect_fixture_schema(path):
    """调用真实 PRAGMA，目标由测试创建；不访问默认 data 目录。"""
    result = {"user_version": None, "tables": {}, "triggers": {}, "objects": []}
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("PRAGMA query_only=ON")
        result["user_version"] = connection.execute("PRAGMA user_version").fetchone()[0]
        for kind, name, ddl in connection.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name"):
            result["objects"].append({"type": kind, "name": name})
            if kind == "trigger":
                result["triggers"][name] = ddl
            if kind == "table":
                result["tables"][name] = {
                    "ddl": ddl, "columns": [list(row) for row in connection.execute(f'PRAGMA table_xinfo("{name}")')],
                    "foreign_keys": [list(row) for row in connection.execute(f'PRAGMA foreign_key_list("{name}")')],
                    "indexes": [],
                }
                for index in connection.execute(f'PRAGMA index_list("{name}")'):
                    result["tables"][name]["indexes"].append({"definition": list(index), "columns": [
                        list(row) for row in connection.execute(f'PRAGMA index_xinfo("{index[1]}")')]})
    return result


def _exact_node(value, model, *, snapshot=False):
    expected = {item.name for item in fields(model)}
    if snapshot and model is Chapter:
        expected.remove("current_version_id")
    if type(value) is not dict or set(value) != expected:
        raise ValueError("样本缺持久字段或含未知字段")
    nested = {BookOutline: {"volumes": VolumePlan}, Character: {"relationships": CharacterRelationship},
              ChapterOutline: {"scenes": ScenePlan}}.get(model, {})
    for name, child in nested.items():
        for item in value[name]:
            _exact_node(item, child)


def _exact_workspace(state):
    if set(state) != {"workspace_version", "revision", "document", "ideas", "worldbuilding", "writing_rules"}:
        raise ValueError("样本工作区字段集合错误")
    document = state["document"]
    if set(document) != {item.name for item in fields(NovelDocument)}:
        raise ValueError("样本文档字段集合错误")
    _exact_node(document["project"], NovelProject)
    if document["book_outline"] is not None:
        _exact_node(document["book_outline"], BookOutline)
    for name, model in (("characters", Character), ("chapters", Chapter), ("chapter_outlines", ChapterOutline)):
        for item in document[name]:
            _exact_node(item, model)
    for version in document["versions"]:
        _exact_node(version, VersionRecord)
        _exact_node(version["snapshot"], MODEL_TYPES[version["entity_type"]], snapshot=True)
    validate_workspace(state)


def _snapshot_references(version, context):
    snapshot, kind = version["snapshot"], version["entity_type"]
    chapters = {item["id"] for item in context["chapters"]}
    characters = {item["id"] for item in context["characters"]}
    def require(condition, message):
        if not condition:
            raise ValueError(message)
    def numbers(values):
        require(all(type(value) is int and value > 0 for value in values) and len(values) == len(set(values)),
                "历史顺序非法或重复")
    if kind in ("project", "chapter"):
        require(bool(snapshot["title"].strip()), "历史标题不能为空")
    if kind == "chapter":
        numbers([snapshot["number"]])
    if kind == "character":
        require(bool(snapshot["name"].strip()), "历史人物名不能为空")
        require(all(item["target_character_id"] in characters for item in snapshot["relationships"]), "历史人物引用非法")
    if kind == "book_outline":
        numbers([item["number"] for item in snapshot["volumes"]])
        assigned = [identifier for item in snapshot["volumes"] for identifier in item["chapter_ids"]]
        require(len(assigned) == len(set(assigned)), "历史章节重复分卷")
        require(all(identifier in chapters for identifier in assigned), "历史章节引用非法")
    if kind == "chapter_outline":
        require(snapshot["chapter_id"] in chapters, "历史章节引用非法")
        require(all(identifier in characters for identifier in snapshot["character_ids"]), "历史人物引用非法")
        numbers([item["order"] for item in snapshot["scenes"]])
        require(all(identifier in characters for scene in snapshot["scenes"] for identifier in scene["character_ids"]),
                "历史场景人物引用非法")


def assert_fixture_dataset(dataset):
    """有限样本的设计 oracle，不是生产包/通用数据库校验器。"""
    for row in dataset["projects"]:
        _exact_workspace(row["payload"])
        state = row["payload"]
        if row["id"] != state["document"]["project"]["id"] or row["revision"] != state["revision"] or row["title"] != state["document"]["project"]["title"]:
            raise ValueError("SQL 元数据不一致")
        history = sorted((item for item in dataset["project_snapshots"] if item["project_id"] == row["id"]),
                         key=lambda item: item["revision"])
        if [item["revision"] for item in history] != list(range(1, row["revision"] + 1)):
            raise ValueError("整书 revision 不连续")
        if history[-1]["payload"] != state or history[-1]["saved_at"] != row["updated_at"]:
            raise ValueError("最新整书快照不一致")
        seen, previous = {}, []
        for item in history:
            _exact_workspace(item["payload"])
            current = item["payload"]
            if current["revision"] != item["revision"] or current["document"]["project"]["id"] != row["id"]:
                raise ValueError("历史 SQL 元数据不一致")
            versions = current["document"]["versions"]
            if versions[:len(previous)] != previous:
                raise ValueError("历史版本前缀被改写")
            for version in versions:
                if version["id"] not in seen:
                    _snapshot_references(version, current["document"])
                    seen[version["id"]] = item["revision"]
            previous = versions
    from novel_writer.application.skill_import import _validated_files
    for row in dataset["skills"]:
        if set(row) != set(TABLE_COLUMNS["skills"]):
            raise ValueError("Skills 持久字段不完整")
        _, primary = _validated_files(row["files_json"])
        if row["primary_path"] != primary["path"]:
            raise ValueError("Skills 主路径不一致")


def transform_fixture_ids(dataset, mapper):
    """只转换样本中声明的引用字段，用于证明复制映射和原文保护方案。"""
    result = deepcopy(dataset)
    def transform_document(document, project_id):
        def map_id(kind, identifier):
            return mapper(project_id, kind, identifier) if identifier is not None else None
        def entity(item, kind):
            item["id"] = map_id(kind, item["id"])
            if "project_id" in item:
                item["project_id"] = map_id("project", item["project_id"])
            if kind == "book_outline":
                for volume in item["volumes"]:
                    volume["chapter_ids"] = [map_id("chapter", identifier) for identifier in volume["chapter_ids"]]
            if kind == "character":
                for relation in item["relationships"]:
                    relation["target_character_id"] = map_id("character", relation["target_character_id"])
            if kind == "chapter_outline":
                item["chapter_id"] = map_id("chapter", item["chapter_id"])
                item["character_ids"] = [map_id("character", identifier) for identifier in item["character_ids"]]
                for scene in item["scenes"]:
                    scene["character_ids"] = [map_id("character", identifier) for identifier in scene["character_ids"]]
            if "current_version_id" in item:
                item["current_version_id"] = map_id("version", item["current_version_id"])
        entity(document["project"], "project")
        if document["book_outline"]:
            entity(document["book_outline"], "book_outline")
        for name, kind in (("chapters", "chapter"), ("characters", "character"), ("chapter_outlines", "chapter_outline")):
            for item in document[name]:
                entity(item, kind)
        for version in document["versions"]:
            version["id"] = map_id("version", version["id"])
            version["project_id"] = map_id("project", version["project_id"])
            version["entity_id"] = map_id(version["entity_type"], version["entity_id"])
            version["previous_version_id"] = map_id("version", version["previous_version_id"])
            entity(version["snapshot"], version["entity_type"])
    for table, key in (("projects", "id"), ("project_snapshots", "project_id")):
        for row in result[table]:
            project_id = row[key]
            row[key] = mapper(project_id, "project", project_id)
            transform_document(row["payload"]["document"], project_id)
            row["payload"]["ideas"] = {mapper(project_id, "chapter", identifier): content
                                        for identifier, content in row["payload"]["ideas"].items()}
    return result


def proposed_copy_mapper(backup_id):
    """固定包身份下的项目/类型作用域映射示例，非应用导入实现。"""
    def mapper(project_id, kind, identifier):
        name = json.dumps(["ai-novel-writer/import/1", backup_id, project_id, kind, identifier],
                          ensure_ascii=False, separators=(",", ":"))
        return str(uuid5(NAMESPACE_URL, name))
    return mapper
