"""V11 planning proposals, branches, locks and explicit formal-planning receipts."""
from dataclasses import dataclass,fields
from typing import Literal
import json
from novel_writer.domain.tasks import check_types,parse,encode,require,uuid_value,digest
from novel_writer.domain.models import _timestamp

STEPS=('idea','audience','scope','conflict','world','plot','structure')
STEP_FIELDS={'idea':{'title','creative_idea'},'audience':{'genre','readership'},'scope':{'target_words','manuscript_language'},'conflict':{'theme','core_conflict'},'world':{'worldbuilding','characters'},'plot':{'main_plot','subplots','ending'},'structure':{'volumes'}}
STEP_FIELDS['dialogue']=set().union(*STEP_FIELDS.values())
LOCK_FIELDS=tuple(sorted(STEP_FIELDS['dialogue']))
def fingerprint(value):return digest(json.dumps(encode(value),ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False))
class Value:
    def __post_init__(self):
        check_types(type(self),self)
        for field in fields(self):
            value=getattr(self,field.name)
            if type(value) is str:require(len(value)<=200000,'creation.invalid_data')
        if hasattr(self,'id'):uuid_value(self.id)
        if hasattr(self,'project_id'):require(type(self.project_id) is str and bool(self.project_id.strip()),'creation.invalid_data');uuid_value(self.operation_id);_timestamp(self.created_at,'creation.created_at');require(len(self.request_sha256)==64 and all(c in '0123456789abcdef' for c in self.request_sha256),'creation.invalid_data')
        if isinstance(self,PlanCharacter):require(0<len(self.name.strip())<=300 and len(self.goals)<=100,'creation.invalid_character')
        elif isinstance(self,PlanChapter):uuid_value(self.outline_id);require(0<len(self.title.strip())<=300,'creation.invalid_chapter')
        elif isinstance(self,PlanVolume):require(0<len(self.title.strip())<=300 and len(self.chapters)<=1000,'creation.invalid_structure')
        elif isinstance(self,PlanData):
            require(0<len(self.title.strip())<=300 and 0<=self.target_words<=100000000 and 0<len(self.manuscript_language.strip())<=100 and len(self.characters)<=100 and len(self.volumes)<=50 and len(self.subplots)<=200,'creation.invalid_data')
            ids=[c.id for c in self.characters]+[v.id for v in self.volumes]+[c.id for v in self.volumes for c in v.chapters]+[c.outline_id for v in self.volumes for c in v.chapters]
            require(len(ids)==len(set(ids)) and sum(len(v.chapters) for v in self.volumes)<=2000,'creation.duplicate_entities')
            require(len(json.dumps(encode(self),ensure_ascii=False).encode('utf-8'))<=2000000,'creation.too_large')
        elif isinstance(self,PlanVersion):
            uuid_value(self.branch_id);require(self.revision>=1 and 0<len(self.branch_name.strip())<=100 and self.current_step in STEPS,'creation.invalid_data')
            require(set(self.completed_steps)<=set(STEPS) and set(self.skipped_steps)<=set(STEPS) and not set(self.completed_steps)&set(self.skipped_steps) and len(set(self.completed_steps))==len(self.completed_steps) and len(set(self.skipped_steps))==len(self.skipped_steps),'creation.invalid_progress')
            for value in (self.previous_version_id,self.derived_from_version_id):
                if value is not None:uuid_value(value)
        elif isinstance(self,PlanChoice):uuid_value(self.version_id)
        elif isinstance(self,PlanLock):uuid_value(self.version_id);require(self.field in LOCK_FIELDS,'creation.invalid_lock')
        elif isinstance(self,PlanPreview):uuid_value(self.version_id);uuid_value(self.owner_id)
        elif isinstance(self,PlanDecision):
            uuid_value(self.preview_id);uuid_value(self.version_id)
            require(self.decision!='accepted' or self.confirmed and self.create_entities,'creation.confirm_required')
            if self.decision!='accepted':require(not self.confirmed and not self.create_entities and not self.authorize_confirmed_metadata and not self.chapter_ids and not self.character_ids and not self.outline_ids and not self.document_version_ids,'creation.invalid_decision')

@dataclass(frozen=True,kw_only=True)
class PlanCharacter(Value):
    id:str
    name:str
    role:str
    personality:str
    background:str
    goals:tuple[str,...]
    notes:str
@dataclass(frozen=True,kw_only=True)
class PlanChapter(Value):
    id:str
    outline_id:str
    title:str
    core_idea:str
    objective:str
    story_time:str
@dataclass(frozen=True,kw_only=True)
class PlanVolume(Value):
    id:str
    title:str
    summary:str
    chapters:tuple[PlanChapter,...]
@dataclass(frozen=True,kw_only=True)
class PlanData(Value):
    title:str
    creative_idea:str
    genre:str
    readership:str
    target_words:int
    manuscript_language:str
    theme:str
    core_conflict:str
    worldbuilding:str
    characters:tuple[PlanCharacter,...]
    main_plot:str
    subplots:tuple[str,...]
    ending:str
    volumes:tuple[PlanVolume,...]
@dataclass(frozen=True,kw_only=True)
class PlanVersion(Value):
    id:str
    project_id:str
    operation_id:str
    request_sha256:str
    branch_id:str
    branch_name:str
    revision:int
    previous_version_id:str|None
    derived_from_version_id:str|None
    data:PlanData
    current_step:str
    completed_steps:tuple[str,...]
    skipped_steps:tuple[str,...]
    created_at:str
@dataclass(frozen=True,kw_only=True)
class PlanChoice(Value):
    id:str
    project_id:str
    operation_id:str
    request_sha256:str
    version_id:str
    created_at:str
@dataclass(frozen=True,kw_only=True)
class PlanLock(Value):
    id:str
    project_id:str
    operation_id:str
    request_sha256:str
    version_id:str
    field:str
    locked:bool
    value_sha256:str
    previous_lock_id:str|None
    created_at:str
@dataclass(frozen=True,kw_only=True)
class Conflict(Value):
    field:str
    code:str
    entity_id:str|None
@dataclass(frozen=True,kw_only=True)
class Impact(Value):
    chapter_creates:tuple[str,...]
    chapter_reuses:tuple[str,...]
    character_creates:tuple[str,...]
    character_reuses:tuple[str,...]
    outline_ids:tuple[str,...]
    requires_confirmed_metadata:bool
    conflicts:tuple[Conflict,...]
@dataclass(frozen=True,kw_only=True)
class PlanPreview(Value):
    id:str
    project_id:str
    operation_id:str
    request_sha256:str
    version_id:str
    owner_id:str
    document_sha256:str
    locks_sha256:str
    plan_sha256:str
    impact:Impact
    created_at:str
@dataclass(frozen=True,kw_only=True)
class PlanDecision(Value):
    id:str
    project_id:str
    operation_id:str
    request_sha256:str
    preview_id:str
    version_id:str
    decision:Literal['accepted','rejected','cancelled']
    confirmed:bool
    create_entities:bool
    authorize_confirmed_metadata:bool
    chapter_ids:tuple[str,...]
    character_ids:tuple[str,...]
    outline_ids:tuple[str,...]
    document_version_ids:tuple[str,...]
    created_at:str

COLLECTIONS={'book_creation_versions':PlanVersion,'book_creation_choices':PlanChoice,'book_creation_locks':PlanLock,'book_creation_previews':PlanPreview,'book_creation_decisions':PlanDecision}
def current_locks(state):
    result={}
    for lock in state.get('book_creation_locks',[]):result[lock['field']]=lock
    return {field:value for field,value in result.items() if value['locked']}
def validate_state(state):
    parsed={};project=state['document']['project']['id']
    for name,kind in COLLECTIONS.items():
        require(type(state[name]) is list and len(state[name])<=10000,'creation.too_large');parsed[name]=[parse(kind,item) for item in state[name]]
        require(len({item.id for item in parsed[name]})==len(parsed[name]) and len({item.operation_id for item in parsed[name]})==len(parsed[name]),'creation.duplicate_identity')
        for item in parsed[name]:require(item.project_id==project,'creation.wrong_book')
    versions={};branches={}
    for value in parsed['book_creation_versions']:
        previous=branches.get(value.branch_id);require((value.revision,value.previous_version_id)==((previous.revision+1,previous.id) if previous else (1,None)),'creation.broken_history')
        if value.derived_from_version_id is not None:require(previous is None and value.derived_from_version_id in versions,'creation.broken_history')
        versions[value.id]=value;branches[value.branch_id]=value
    for value in parsed['book_creation_choices']:require(value.version_id in versions,'creation.missing_version')
    locks={}
    for value in parsed['book_creation_locks']:
        require(value.version_id in versions and value.previous_lock_id==(locks[value.field].id if value.field in locks else None),'creation.invalid_lock')
        require(value.value_sha256==fingerprint(getattr(versions[value.version_id].data,value.field)),'creation.invalid_lock');locks[value.field]=value
    previews={}
    for value in parsed['book_creation_previews']:
        require(value.version_id in versions and value.plan_sha256==fingerprint(versions[value.version_id].data),'creation.invalid_preview');previews[value.id]=value
    decided=set();all_ids={v['id'] for v in state['document']['versions']}
    for value in parsed['book_creation_decisions']:
        require(value.preview_id in previews and value.version_id==previews[value.preview_id].version_id and value.preview_id not in decided,'creation.invalid_decision');decided.add(value.preview_id)
        require(set(value.document_version_ids)<=all_ids,'creation.invalid_decision')
def validate_transition(state,previous):
    previous=previous or {}
    for name in COLLECTIONS:
        old=previous.get(name,[]);require(state[name][:len(old)]==old,'creation.history_immutable')
    old_previews={value['id'] for value in previous.get('book_creation_previews',[])}
    for decision in state['book_creation_decisions'][len(previous.get('book_creation_decisions',[])):]:require(decision['preview_id'] in old_previews,'creation.preview_required')
    if not previous:return
    active=current_locks(previous)
    for name in ('ending','worldbuilding'):
        if name not in active:continue
        old=previous['worldbuilding'] if name=='worldbuilding' else (previous['document']['book_outline'] or {}).get('ending','')
        new=state['worldbuilding'] if name=='worldbuilding' else (state['document']['book_outline'] or {}).get('ending','')
        if new!=old:require(fingerprint(new)==active[name]['value_sha256'],'creation.lock_conflict:'+name)
    def semantic_characters(document):return [{k:v for k,v in c.items() if k!='updated_at'} for c in document['characters']]
    if 'characters' in active and semantic_characters(previous['document'])!=semantic_characters(state['document']):
        before={value['id']:value for value in previous['document']['characters']};after={value['id']:value for value in state['document']['characters']};allowed=False
        versions={value['id']:value for value in state['book_creation_versions']}
        for decision in state['book_creation_decisions'][len(previous.get('book_creation_decisions',[])):]:
            if decision['decision']!='accepted':continue
            plan=versions[decision['version_id']]['data']['characters']
            if fingerprint(plan)!=active['characters']['value_sha256']:continue
            proposed={value['id']:value for value in plan}
            if set(after)!=set(before)|set(proposed):continue
            if any(any(after[identifier].get(key)!=value for key,value in character.items()) for identifier,character in proposed.items()):continue
            if any({k:v for k,v in value.items() if k!='updated_at'}!={k:v for k,v in after[identifier].items() if k!='updated_at'} for identifier,value in before.items() if identifier not in proposed):continue
            if any(after[identifier]['relationships']!=value['relationships'] for identifier,value in before.items()):continue
            allowed=True
        require(allowed,'creation.lock_conflict:characters')
