"""V23 deterministic book/volume memory rollups with append-only history."""
from dataclasses import dataclass
from typing import Literal
from novel_writer.domain.tasks import check_types,parse,encode,require,uuid_value
from novel_writer.domain.models import _timestamp
from novel_writer.domain.memory import MemorySource,fingerprint

SCOPES=('book','volume','chapter')
ACTIONS=('create','rebuild')
KINDS=('book_summary','volume_summary','chapter_summary','character_state','event','foreshadow','payoff')
KIND_ORDER={kind:index for index,kind in enumerate(KINDS)}


class _RollupValue:
    def __post_init__(self):
        check_types(type(self),self)


@dataclass(frozen=True,kw_only=True)
class RollupSource(_RollupValue):
    memory_id:str
    memory_revision:int
    kind:Literal['book_summary','volume_summary','chapter_summary','character_state','event','foreshadow','payoff']
    title:str
    text:str
    position_chapter_id:str
    position_number:int
    character_id:str|None
    volume_number:int|None


@dataclass(frozen=True,kw_only=True)
class MemoryRollup(_RollupValue):
    id:str
    project_id:str
    revision:int
    scope:Literal['book','volume','chapter']
    scope_volume_number:int|None
    through_chapter_id:str
    through_position:int
    title:str
    text:str
    sources:tuple[RollupSource,...]
    created_at:str
    updated_at:str
    chapter_source:MemorySource|None=None


@dataclass(frozen=True,kw_only=True)
class MemoryRollupEdit(_RollupValue):
    id:str
    rollup_id:str
    revision:int
    previous_version_id:str|None
    snapshot:MemoryRollup
    saved_at:str
    action:Literal['create','rebuild']
    operation_id:str


COLLECTIONS={'memory_rollups':MemoryRollup,'memory_rollup_history':MemoryRollupEdit}

def contains_chapter_rollup(state):
    def chapter(value):return type(value) is dict and (value.get('scope')=='chapter' or 'chapter_source' in value)
    rollups=state.get('memory_rollups',[]);history=state.get('memory_rollup_history',[])
    return (type(rollups) is list and any(chapter(v) for v in rollups)) or (type(history) is list and any(type(v) is dict and chapter(v.get('snapshot')) for v in history))

def validate_chapter_source(rollup,state):
    source=rollup.chapter_source
    if rollup.scope!='chapter':
        require(source is None,'memory_rollups.unexpected_chapter_source');return
    require(source is not None and rollup.scope_volume_number is None,'memory_rollups.invalid_chapter_source')
    require(source.project_id==rollup.project_id and source.kind=='chapter' and source.entity_id==source.chapter_id==rollup.through_chapter_id,'memory_rollups.invalid_chapter_source')
    require(1<=source.workspace_revision<=state['revision'] and len(source.source_sha256)==64 and all(c in '0123456789abcdef' for c in source.source_sha256),'memory_rollups.invalid_chapter_source')
    if source.version_id is not None:
        version=next((v for v in state['document']['versions'] if v['id']==source.version_id),None)
        require(version is not None and version['entity_type']=='chapter' and version['entity_id']==source.entity_id and fingerprint(version['snapshot'])==source.source_sha256,'memory_rollups.invalid_chapter_source_version')
    require(all(s.position_chapter_id==rollup.through_chapter_id and s.position_number==rollup.through_position for s in rollup.sources),'memory_rollups.source_outside_chapter')


def _source_value(source,name):
    return source[name] if isinstance(source,dict) else getattr(source,name)


def source_sort_key(source):
    return (_source_value(source,'position_number'),KIND_ORDER[_source_value(source,'kind')],
        _source_value(source,'title'),_source_value(source,'memory_id'))


def render_text(title,sources):
    blocks=[]
    for source in sources:
        blocks.append('### '+_source_value(source,'title')+'\n来源记忆：'+_source_value(source,'memory_id')+
            ' · 第'+str(_source_value(source,'memory_revision'))+'版\n'+_source_value(source,'text'))
    body='\n\n'.join(blocks) if blocks else '截至所选故事位置，没有可汇总的已确认且来源未变记忆。'
    return title+'\n\n'+body


def validate_state(state):
    project=state['document']['project']['id']
    chapters={value['id']:value for value in state['document']['chapters']}
    characters={value['id'] for value in state['document']['characters']}
    outline=state['document']['book_outline']
    volumes={value['number'] for value in (outline['volumes'] if outline else [])}
    memories={value['id']:value for value in state.get('memories',[])}
    memory_versions={(value['memory_id'],value['revision']):value['snapshot'] for value in state.get('memory_history',[])}
    rollups=state.get('memory_rollups',[])
    require(type(rollups) is list and len(rollups)<=5000,'memory_rollups.invalid_collection')
    rollup_ids=set();keys=set()
    for raw in rollups:
        rollup=parse(MemoryRollup,raw)
        uuid_value(rollup.id);require(rollup.id not in rollup_ids and rollup.project_id==project,'memory_rollups.invalid_rollup');rollup_ids.add(rollup.id)
        require(rollup.revision>=1 and rollup.through_chapter_id in chapters and rollup.through_position>=1,'memory_rollups.invalid_scope')
        if rollup.scope in ('book','chapter'):require(rollup.scope_volume_number is None,'memory_rollups.invalid_scope')
        else:require(rollup.scope_volume_number in volumes,'memory_rollups.invalid_scope')
        validate_chapter_source(rollup,state)
        key=(rollup.scope,rollup.scope_volume_number,rollup.through_chapter_id)
        require(key not in keys,'memory_rollups.duplicate_scope');keys.add(key)
        require(0<len(rollup.title.strip())<=500 and len(rollup.sources)<=10000,'memory_rollups.invalid_rollup')
        require(len(rollup.text)<=8*1024*1024 and rollup.text==render_text(rollup.title,rollup.sources),'memory_rollups.text_not_deterministic')
        require(list(rollup.sources)==sorted(rollup.sources,key=source_sort_key),'memory_rollups.invalid_source_order')
        source_ids=set()
        for source in rollup.sources:
            require(source.memory_id not in source_ids and source.memory_id in memories and source.memory_revision>=1,'memory_rollups.invalid_source');source_ids.add(source.memory_id)
            require(source.position_chapter_id in chapters and source.position_number>=1,'memory_rollups.invalid_source_position')
            require(source.position_number<=rollup.through_position,'memory_rollups.source_after_scope')
            require(source.character_id is None or source.character_id in characters,'memory_rollups.invalid_source_character')
            require(source.volume_number is None or source.volume_number in volumes,'memory_rollups.invalid_source_volume')
            historical=memory_versions.get((source.memory_id,source.memory_revision))
            require(historical is not None,'memory_rollups.invalid_source_version')
            require((historical['kind'],historical['title'],historical['text'],historical['character_id'],historical['volume_number'])==(source.kind,source.title,source.text,source.character_id,source.volume_number),'memory_rollups.invalid_source_snapshot')
        _timestamp(rollup.created_at,'memory_rollups.created_at');_timestamp(rollup.updated_at,'memory_rollups.updated_at')
        require(_timestamp(rollup.updated_at,'memory_rollups.updated_at')>=_timestamp(rollup.created_at,'memory_rollups.created_at'),'memory_rollups.invalid_time')
    history=state.get('memory_rollup_history',[])
    require(type(history) is list and len(history)<=50000,'memory_rollups.invalid_history_collection')
    history_ids=set();operations=set();latest={};previous={};counts={}
    for raw in history:
        entry=parse(MemoryRollupEdit,raw)
        validate_chapter_source(entry.snapshot,state)
        uuid_value(entry.id);uuid_value(entry.rollup_id);uuid_value(entry.operation_id)
        require(entry.id not in history_ids and entry.operation_id not in operations,'memory_rollups.invalid_history');history_ids.add(entry.id);operations.add(entry.operation_id)
        require(entry.rollup_id in rollup_ids and entry.snapshot.id==entry.rollup_id and entry.snapshot.project_id==project,'memory_rollups.invalid_history')
        count=counts.get(entry.rollup_id,0)+1
        require(entry.revision==count and entry.snapshot.revision==count and entry.previous_version_id==previous.get(entry.rollup_id),'memory_rollups.invalid_history_chain')
        require((entry.action=='create')==(count==1),'memory_rollups.invalid_history_action')
        require(_timestamp(entry.saved_at,'memory_rollups.saved_at')>=_timestamp(entry.snapshot.updated_at,'memory_rollups.updated_at'),'memory_rollups.invalid_history_time')
        counts[entry.rollup_id]=count;previous[entry.rollup_id]=entry.id;latest[entry.rollup_id]=encode(entry.snapshot)
    for rollup in rollups:
        require(latest.get(rollup['id'])==rollup,'memory_rollups.current_snapshot_mismatch')


def validate_transition(state,previous):
    validate_state(state)
    old=previous.get('memory_rollup_history') if previous.get('workspace_version',0)>=23 else None
    if old is not None:
        new=state.get('memory_rollup_history',[])
        require(len(new)>=len(old) and new[:len(old)]==old,'memory_rollups.history_not_append_only')
        old_ids={value['id'] for value in previous.get('memory_rollups',[])}
        require(old_ids<={value['id'] for value in state.get('memory_rollups',[])},'memory_rollups.rollup_deleted')
