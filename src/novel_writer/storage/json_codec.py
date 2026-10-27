"""JSON 转换与读取；不提供保存、覆盖或自动修改小说文件的操作。"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict,fields,MISSING
from copy import deepcopy
from itertools import chain
from pathlib import Path
from typing import Any

from novel_writer.domain.models import (
    BookOutline, Chapter, ChapterOutline, Character, CharacterRelationship,
    DataValidationError, NovelDocument, NovelProject, ScenePlan, VersionRecord,
    VolumePlan, validate_document, validate_snapshot_references,
)


MAX_JSON_DEPTH = 64
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_JSON_NODES = 1_000_000
_STRING_SPECIAL = re.compile(r'["\\]')
_PRIMITIVE = re.compile(r'[^ \t\r\n{}\[\]:,"]+')
_NONSPACE = re.compile(r'[^ \t\r\n]')
_STRING_OR_CONTAINER = re.compile(r'"[^"\\]*(?:\\[\s\S][^"\\]*)*"|[{}\[\]]|"')


def _check_json_resources(text: str) -> None:
    """解析前只计数，不解码或改写字符串；语法仍由 JSON 解析器核验。

    容器、对象键和每个标量分别计一个节点；容器嵌套最多 64 层。
    跳过字符串时只识别引号和反斜杠，长篇正文不会按字符生成 token。
    """
    # This is a conservative upper bound, including punctuation INSIDE prose.
    # Every primitive needs a preceding comma/colon, except a root primitive.
    # A bound above the quota falls back to the original exact node counter.
    upper=(text.count('"')//2+text.count('{')+text.count('[')
           +text.count(':')+text.count(',')+1)
    if upper<=MAX_JSON_NODES:
        # Consume complete strings, including escapes, in the C regex engine.
        # Only containers outside strings affect depth; nothing is decoded.
        # An unmatched quote falls back to the original exact scanner.
        depth=0
        for match in _STRING_OR_CONTAINER.finditer(text):
            character=text[match.start()]
            if character=='"':
                if match.end()==match.start()+1:break
                continue
            if character in '[{':
                depth+=1
                if depth>MAX_JSON_DEPTH:raise DataValidationError(f"JSON 嵌套深度超过 {MAX_JSON_DEPTH} 层限额")
            else:depth=max(0,depth-1)
        else:return
    depth = nodes = position = 0
    while match := _NONSPACE.search(text, position):
        character = text[match.start()]
        position = match.end()
        if character == '"':
            nodes += 1
            if nodes > MAX_JSON_NODES:
                raise DataValidationError(f"JSON 节点数量超过 {MAX_JSON_NODES} 个限额")
            while special := _STRING_SPECIAL.search(text, position):
                position = special.end()
                if text[special.start()] == '"':break
                position += 1
            else:return
        elif character in "[{":
            nodes += 1;depth += 1
            if depth > MAX_JSON_DEPTH:raise DataValidationError(f"JSON 嵌套深度超过 {MAX_JSON_DEPTH} 层限额")
        elif character in "]}":depth = max(0, depth - 1)
        elif character not in ":,":
            nodes += 1
            primitive = _PRIMITIVE.match(text, match.start())
            position = primitive.end() if primitive is not None else position
        if nodes > MAX_JSON_NODES:
            raise DataValidationError(f"JSON 节点数量超过 {MAX_JSON_NODES} 个限额")


def strict_json_loads(text: str | bytes) -> Any:
    """持久化 JSON 的有界、无私有内容错误解析；字符串内原文保持不变。"""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise DataValidationError("JSON 含重复字段")
            result[key] = value
        return result

    def constant(_value):
        raise DataValidationError("JSON 不允许非法数值常量")

    def finite_float(number):
        value=float(number)
        if not math.isfinite(value):raise DataValidationError('JSON 含非法数值')
        return value

    try:
        if type(text) is bytes:
            if len(text) > MAX_JSON_BYTES:
                raise DataValidationError("JSON 单条记录超过 64 MiB 限额")
            text = text.decode("utf-8", errors="strict")
        if type(text) is not str:
            raise DataValidationError("JSON 输入必须为 UTF-8 文本")
        if len(text.encode("utf-8", errors="strict")) > MAX_JSON_BYTES:
            raise DataValidationError("JSON 单条记录超过 64 MiB 限额")
        if text.startswith("\ufeff"):
            raise DataValidationError("JSON 不允许文件头 BOM")
        _check_json_resources(text)
        value = json.loads(text, object_pairs_hook=unique, parse_constant=constant,parse_float=finite_float)
        # Literal UTF-8 was checked before decode. Only a Unicode escape can
        # introduce a surrogate that was not present in that checked text.
        # Finite floats are checked by the decoder hook, including 1e999.
        if '\\u' not in text:return value
        # 每层只保留一个迭代器；宽数组不会产生与元素数量同规模的待遍历元组。
        frames = [iter((value,))]
        while frames:
            try:
                item = next(frames[-1])
            except StopIteration:
                frames.pop()
                continue
            if type(item) is str:
                item.encode("utf-8", errors="strict")
            elif type(item) is float and not math.isfinite(item):
                raise DataValidationError("JSON 含非法数值")
            elif type(item) is dict:
                frames.append(iter(chain(item.keys(), item.values())))
            elif type(item) is list:
                frames.append(iter(item))
        return value
    except json.JSONDecodeError as error:
        raise DataValidationError(f"JSON 格式有误：第 {error.lineno} 行，第 {error.colno} 列") from None
    except (UnicodeError, RecursionError, OverflowError, ValueError) as error:
        if isinstance(error, DataValidationError):
            raise
        raise DataValidationError("JSON 编码、语法或嵌套深度无效") from None


def _list_field(data: dict[str, Any], name: str) -> list[Any]:
    value = data.get(name, [])
    if type(value) is not list:
        raise DataValidationError(f"{name} 必须是列表")
    return value


def normalize_persistent_document(raw):
    """V1旧持久文档的声明默认值；不调用ID/时间工厂、不丢未知字段。"""
    if type(raw) is not dict or 'schema_version' not in raw:raise DataValidationError('旧文档缺少格式声明')
    def node(value,model,*,snapshot=False):
        if type(value) is not dict:raise DataValidationError('旧文档字段类型非法')
        names={f.name:f for f in fields(model) if not(snapshot and model is Chapter and f.name=='current_version_id')}
        if set(value)-set(names):raise DataValidationError('旧文档含未知字段')
        result=deepcopy(value)
        for name,f in names.items():
            if name not in result:
                # 持久实体快照原契约完整，兼容唯一明确旧可选project.language；
                # 当前实体按构造器已声明默认兼容，但身份和时间始终必需。
                if name in ('id','created_at','updated_at') or (snapshot and not(model is NovelProject and name=='language')):raise DataValidationError('旧持久身份/时间或快照字段缺失')
                if f.default is not MISSING:result[name]=deepcopy(f.default)
                elif f.default_factory is list:result[name]=[]
                elif f.default_factory is dict:result[name]={}
                else:raise DataValidationError('旧持久必需字段缺失')
        nested={'volumes':VolumePlan,'relationships':CharacterRelationship,'scenes':ScenePlan}
        for name,child in nested.items():
            if name in result:
                if type(result[name]) is not list:raise DataValidationError('旧文档列表字段非法')
                result[name]=[node(item,child,snapshot=snapshot) for item in result[name]]
        return result
    data=node(raw,NovelDocument)
    if type(data['schema_version']) is not int or data['schema_version']!=1:raise DataValidationError('未知小说版本')
    data['project']=node(data['project'],NovelProject)
    if data['book_outline'] is not None:data['book_outline']=node(data['book_outline'],BookOutline)
    for key,model in (('chapters',Chapter),('characters',Character),('chapter_outlines',ChapterOutline)):
        if type(data[key]) is not list:raise DataValidationError('旧文档列表字段非法')
        data[key]=[node(item,model) for item in data[key]]
    models={'project':NovelProject,'chapter':Chapter,'character':Character,'book_outline':BookOutline,'chapter_outline':ChapterOutline}
    normalized=[]
    for raw_version in data['versions']:
        version=node(raw_version,VersionRecord)
        if version['entity_type'] not in models:raise DataValidationError('未知版本实体类型')
        version['snapshot']=node(version['snapshot'],models[version['entity_type']],snapshot=True);normalized.append(version)
    data['versions']=normalized
    return data


def _same_json_types(left,right):
    if type(left) is not type(right):return False
    # Called only AFTER full value equality. Strings/None cannot equal a
    # different valid JSON scalar type; bool/int/float aliases still must be
    # checked. A subclass or non-JSON container goes through the exact check.
    if type(left) is dict:
        return all(type(k) is str and (type(v) in (str,type(None)) or _same_json_types(v,right[k])) for k,v in left.items())
    if type(left) is list:
        return all(type(a) in (str,type(None)) or _same_json_types(a,b) for a,b in zip(left,right))
    return True


def document_from_dict(data: dict[str, Any], *, _validated_versions=None,_verified_version_ids=None) -> NovelDocument:
    """将 JSON 字典转换为数据对象，拒绝未知字段并校验关联。"""
    try:
        if type(data) is not dict or "schema_version" not in data:
            raise DataValidationError("小说 JSON 必须是包含 schema_version 的对象")
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise DataValidationError("不支持此 schema_version；当前只支持 1")
        outline_data = data.get("book_outline")
        book_outline = None if outline_data is None else BookOutline(
            **{key: value for key, value in outline_data.items() if key != "volumes"},
            volumes=[VolumePlan(**item) for item in _list_field(outline_data, "volumes")],
        )
        characters = [
            Character(
                **{key: value for key, value in item.items() if key != "relationships"},
                relationships=[CharacterRelationship(**relation) for relation in _list_field(item, "relationships")],
            )
            for item in _list_field(data, "characters")
        ]
        chapter_outlines = [
            ChapterOutline(
                **{key: value for key, value in item.items() if key != "scenes"},
                scenes=[ScenePlan(**scene) for scene in _list_field(item, "scenes")],
            )
            for item in _list_field(data, "chapter_outlines")
        ]
        handled = {"project", "book_outline", "characters", "chapter_outlines", "chapters", "versions"}
        raw_versions=_list_field(data,'versions')
        validated_ids=set()
        if _validated_versions:
            for raw in raw_versions:
                if type(raw) is dict and type(raw.get('id')) is str and raw['id'] in _validated_versions:
                    previous=_validated_versions[raw['id']]
                    # Python equality alone aliases True/1 and 1/1.0. Exact
                    # container/scalar types must match the trusted record too.
                    if raw==previous and _same_json_types(raw,previous):validated_ids.add(raw['id'])
        document = NovelDocument(
            **{key: value for key, value in data.items() if key not in handled},
            project=NovelProject(**data["project"]),
            book_outline=book_outline,
            characters=characters,
            chapter_outlines=chapter_outlines,
            chapters=[Chapter(**item) for item in _list_field(data, "chapters")],
            versions=[VersionRecord(**item) for item in raw_versions],
        )
    except (KeyError, TypeError, AttributeError) as error:
        raise DataValidationError(f"小说 JSON 的字段或结构有误：{error}") from error
    validate_document(document,_validated_version_ids=validated_ids)
    if _verified_version_ids is not None:_verified_version_ids.update(validated_ids)
    return document


def document_to_dict(document: NovelDocument) -> dict[str, Any]:
    validate_document(document)
    return asdict(document)


def document_from_json(text: str) -> NovelDocument:
    data = strict_json_loads(text)
    if not isinstance(data, dict):
        raise DataValidationError("小说 JSON 的根节点必须是对象")
    document = document_from_dict(data)
    chapter_ids = {item.id for item in document.chapters}
    character_ids = {item.id for item in document.characters}
    for version in document.versions:
        validate_snapshot_references(version, chapter_ids=chapter_ids, character_ids=character_ids)
    return document


def document_to_json(document: NovelDocument) -> str:
    return json.dumps(document_to_dict(document), ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def read_document(path: str | Path) -> NovelDocument:
    """只读打开 UTF-8 小说文档，兼容带 BOM 的编辑器保存结果。"""
    return document_from_json(Path(path).read_text(encoding="utf-8-sig"))
