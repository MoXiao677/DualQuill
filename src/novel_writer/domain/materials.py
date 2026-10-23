"""V25 explicit TXT/Markdown materials with append-only versions and literal chunks."""
from dataclasses import dataclass
from typing import Literal

from novel_writer.domain.models import _timestamp
from novel_writer.domain.tasks import check_types,digest,parse,require,uuid_value

FORMATS=('txt','md')
ACTIONS=('create','update','archive','restore','rebuild','rebuild_all')
CHUNK_CHARS=800
CHUNK_OVERLAP=120
MAX_TEXT_CHARS=4_000_000
MAX_TAGS=20
MAX_TAG_CHARS=40


def _control(value):
    return any(ord(char)<32 or ord(char)==127 for char in value)


def chunk_ranges(length):
    """Deterministic fixed character windows with overlap; labels are not semantic."""
    require(type(length) is int and length>0,'materials.invalid_chunk_length')
    start=0
    while start<length:
        end=min(length,start+CHUNK_CHARS)
        yield start,end
        if end==length:return
        start=end-CHUNK_OVERLAP


class Value:
    def __post_init__(self):
        check_types(type(self),self)
        if hasattr(self,'id'):uuid_value(self.id)
        if hasattr(self,'project_id'):require(type(self.project_id) is str and bool(self.project_id.strip()),'materials.invalid_project')
        if hasattr(self,'created_at'):_timestamp(self.created_at,'materials.created')


@dataclass(frozen=True,kw_only=True)
class Material(Value):
    id:str
    project_id:str
    title:str
    format:Literal['txt','md']
    tags:tuple[str,...]
    archived:bool
    current_version_id:str
    revision:int
    created_at:str
    updated_at:str
    def __post_init__(self):
        super().__post_init__();_timestamp(self.updated_at,'materials.updated')
        require(self.format in FORMATS and type(self.archived) is bool and type(self.revision) is int and self.revision>=1,'materials.invalid_material')
        require(type(self.title) is str and 0<len(self.title)<=200 and self.title==self.title.strip() and not _control(self.title),'materials.invalid_title')
        require(type(self.tags) is tuple and len(self.tags)<=MAX_TAGS,'materials.invalid_tags')
        require(len(set(self.tags))==len(self.tags),'materials.duplicate_tags')
        for tag in self.tags:require(type(tag) is str and 0<len(tag)<=MAX_TAG_CHARS and tag==tag.strip() and not _control(tag),'materials.invalid_tags')
        uuid_value(self.current_version_id)


@dataclass(frozen=True,kw_only=True)
class MaterialVersion(Value):
    id:str
    project_id:str
    material_id:str
    version_number:int
    text:str
    text_sha256:str
    note:str
    created_at:str
    previous_version_id:str|None
    def __post_init__(self):
        super().__post_init__();uuid_value(self.material_id)
        require(type(self.version_number) is int and self.version_number>=1 and type(self.text) is str and 0<len(self.text)<=MAX_TEXT_CHARS and bool(self.text.strip()),'materials.invalid_version')
        require(not any(ord(char)==0 or (ord(char)<32 and char not in '\n\r\t') or ord(char)==127 for char in self.text),'materials.invalid_text')
        require(self.text_sha256==digest(self.text),'materials.invalid_text_hash')
        require(type(self.note) is str and len(self.note)<=1000 and '\x00' not in self.note,'materials.invalid_note')
        if self.previous_version_id is not None:uuid_value(self.previous_version_id)


@dataclass(frozen=True,kw_only=True)
class MaterialChunk(Value):
    id:str
    project_id:str
    material_id:str
    material_version_id:str
    ordinal:int
    start:int
    end:int
    text_sha256:str
    def __post_init__(self):
        super().__post_init__();uuid_value(self.material_id);uuid_value(self.material_version_id)
        require(type(self.ordinal) is int and type(self.start) is int and type(self.end) is int and self.ordinal>=0 and self.start>=0 and self.end>self.start,'materials.invalid_chunk')
        require(type(self.text_sha256) is str and len(self.text_sha256)==64 and all(char in '0123456789abcdef' for char in self.text_sha256),'materials.invalid_chunk_hash')


@dataclass(frozen=True,kw_only=True)
class MaterialOperation(Value):
    id:str
    project_id:str
    material_id:str|None
    operation_id:str
    action:Literal['create','update','archive','restore','rebuild','rebuild_all']
    expected_revision:int
    version_id:str|None
    request_sha256:str
    created_at:str
    def __post_init__(self):
        super().__post_init__();uuid_value(self.operation_id)
        require(self.action in ACTIONS and type(self.expected_revision) is int and self.expected_revision>=1,'materials.invalid_operation')
        for value in (self.material_id,self.version_id):
            if value is not None:uuid_value(value)
        require(type(self.request_sha256) is str and len(self.request_sha256)==64 and all(char in '0123456789abcdef' for char in self.request_sha256),'materials.invalid_operation')
        if self.action=='rebuild_all':require(self.material_id is None and self.version_id is None,'materials.invalid_operation')
        else:require(self.material_id is not None,'materials.invalid_operation')


COLLECTIONS={
    'materials':Material,
    'material_versions':MaterialVersion,
    'material_chunks':MaterialChunk,
    'material_operations':MaterialOperation,
}


def material_chunks(state,material_id,version_id=None):
    values=[item for item in state.get('material_chunks',[]) if item['material_id']==material_id and (version_id is None or item['material_version_id']==version_id)]
    return sorted(values,key=lambda item:item['ordinal'])


def current_version(state,material):
    version=next((item for item in state.get('material_versions',[]) if item['id']==material['current_version_id']),None)
    require(version is not None and version['material_id']==material['id'],'materials.missing_version')
    return version


def require_current_index(state,material):
    """Return the current version only when its deterministic chunk index is complete."""
    version=current_version(state,material)
    chunks=material_chunks(state,material['id'])
    require(bool(chunks),'materials.index_missing')
    require(all(item['material_version_id']==version['id'] for item in chunks),'materials.index_stale')
    expected=list(chunk_ranges(len(version['text'])))
    require(len(chunks)==len(expected),'materials.index_incomplete')
    for ordinal,(item,(start,end)) in enumerate(zip(chunks,expected)):
        require(item['ordinal']==ordinal and item['start']==start and item['end']==end,'materials.index_incomplete')
        require(item['text_sha256']==digest(version['text'][start:end]),'materials.index_incomplete')
    return version


def index_status(state,material):
    chunks=material_chunks(state,material['id'])
    if not chunks:return 'missing'
    return 'current' if all(item['material_version_id']==material['current_version_id'] for item in chunks) else 'stale'


def index_version_id(state,material):
    chunks=material_chunks(state,material['id'])
    versions={item['material_version_id'] for item in chunks}
    return next(iter(versions)) if len(versions)==1 else None


def validate_state(state):
    if state.get('workspace_version',0)<25:
        require(not any(name in state for name in COLLECTIONS),'materials.require_v25');return
    parsed={}
    for name,model in COLLECTIONS.items():
        require(type(state[name]) is list and len(state[name])<=100000,'materials.invalid_collection')
        values=[parse(model,item) for item in state[name]]
        require(len({item.id for item in values})==len(values),'materials.duplicate_id')
        parsed[name]=values
    project=state['document']['project']['id']
    materials={item.id:item for item in parsed['materials']}
    for item in parsed['materials']:require(item.project_id==project,'materials.invalid_project')
    versions={item.id:item for item in parsed['material_versions']}
    by_material={}
    for item in parsed['material_versions']:
        material=materials.get(item.material_id)
        require(material is not None and item.project_id==project,'materials.orphan_version');by_material.setdefault(item.material_id,[]).append(item)
    for material_id,items in by_material.items():
        numbers=sorted(item.version_number for item in items)
        require(numbers==list(range(1,len(items)+1)),'materials.invalid_version_numbers')
        by_number={item.version_number:item for item in items}
        for item in items:
            if item.version_number==1:require(item.previous_version_id is None,'materials.invalid_version_chain')
            else:
                previous=versions.get(item.previous_version_id)
                require(previous is not None and previous.material_id==material_id and previous.version_number==item.version_number-1,'materials.invalid_version_chain')
        require(materials[material_id].current_version_id==by_number[len(items)].id,'materials.current_version_mismatch')
    chunks_by_version={}
    for item in parsed['material_chunks']:
        version=versions.get(item.material_version_id)
        require(version is not None and version.material_id==item.material_id and item.project_id==project,'materials.orphan_chunk')
        chunks_by_version.setdefault(item.material_version_id,[]).append(item)
    for version_id,items in chunks_by_version.items():
        version=versions[version_id];items=sorted(items,key=lambda item:item.ordinal)
        expected=list(chunk_ranges(len(version.text)))
        require(len(items)==len(expected),'materials.incomplete_chunks')
        for ordinal,(item,(start,end)) in enumerate(zip(items,expected)):
            require(item.ordinal==ordinal and item.start==start and item.end==end,'materials.invalid_chunk_range')
            require(item.text_sha256==digest(version.text[start:end]),'materials.invalid_chunk_hash')
    operations=set()
    for item in parsed['material_operations']:
        require(item.project_id==project and item.operation_id not in operations,'materials.invalid_operation');operations.add(item.operation_id)
        if item.material_id is not None:require(item.material_id in materials,'materials.orphan_operation')
        if item.version_id is not None:
            version=versions.get(item.version_id);require(version is not None and version.material_id==item.material_id,'materials.orphan_operation')
        if item.action=='create':require(item.version_id is not None and versions[item.version_id].version_number==1,'materials.invalid_operation')
        elif item.action=='update':require(item.version_id is not None and versions[item.version_id].version_number>=2,'materials.invalid_operation')
        elif item.action=='rebuild':require(item.version_id is not None,'materials.invalid_operation')
        else:require(item.version_id is None,'materials.invalid_operation')


def validate_transition(state,previous):
    validate_state(state);old=previous or {}
    old_materials={item['id']:item for item in old.get('materials',[])}
    new_materials={item['id']:item for item in state['materials']}
    require(set(old_materials)<=set(new_materials),'materials.cannot_delete')
    for identifier,before in old_materials.items():
        after=new_materials[identifier]
        for key in ('id','project_id','created_at'):require(before[key]==after[key],'materials.binding_immutable')
        require(after['revision']>=before['revision'] and after['updated_at']>=before['updated_at'],'materials.revision_invalid')
        changed=any(before[key]!=after[key] for key in ('title','format','tags','archived','current_version_id'))
        if changed:require(after['revision']>before['revision'],'materials.revision_required')
        if before['current_version_id']!=after['current_version_id']:
            versions={item['id']:item for item in state['material_versions']}
            require(versions[after['current_version_id']]['version_number']>versions[before['current_version_id']]['version_number'],'materials.version_regression')
    old_versions=old.get('material_versions',[]);require(state['material_versions'][:len(old_versions)]==old_versions,'materials.versions_append_only')
    old_operations=old.get('material_operations',[]);require(state['material_operations'][:len(old_operations)]==old_operations,'materials.operations_append_only')
