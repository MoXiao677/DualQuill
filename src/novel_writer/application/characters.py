"""人物设定管理；稳定 ID 保证改名后关系不失效。"""

from novel_writer.application.fields import check_fields, find, text, update_text, structured_list, text_list
from novel_writer.application.versions import record
from novel_writer.domain.models import Character, CharacterRelationship

MODULE = {"id": "characters", "name": "人物设定管理", "status": "ready", "description": "新建和编辑人物姓名、身份、性格、背景、备注。"}
NAMES = ("name", "role", "personality", "background", "notes")


def add(document, values):
    check_fields(values, {*NAMES,'goals','relationships'})
    character = Character(project_id=document.project.id, name=text(values.get("name"), "人物姓名", required=True))
    update_text(character, values, NAMES, required=("name",))
    _planning(character,values)
    document.characters.append(character)
    record(document, "character", character, "创建人物")


def save(document, values):
    check_fields(values, {"character_id", *NAMES,'goals','relationships'})
    character = find(document.characters, values.get("character_id"), "人物")
    update_text(character, values, NAMES, required=("name",))
    _planning(character,values)
    record(document, "character", character, "修改人物设定")


def _planning(character,values):
    if 'goals' in values:
        character.goals = text_list(values['goals'],'人物目标')
    if 'relationships' in values:
        character.relationships = structured_list(values['relationships'],CharacterRelationship,'人物关系')
