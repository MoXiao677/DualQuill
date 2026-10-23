"""工作区V2的显式记忆和不可变编辑历史，不依赖存储/模型服务。"""
from dataclasses import dataclass,asdict,fields
import hashlib,json
from uuid import uuid5,NAMESPACE_URL
from typing import Literal
from novel_writer.domain.models import DataValidationError,_check_type,_timestamp

MemoryKind=Literal['book_summary','volume_summary','chapter_summary','character_state','event','foreshadow','payoff']
SourceKind=Literal['project','chapter','character','chapter_outline','book_outline','worldbuilding','writing_rules','idea','rule']

@dataclass(kw_only=True)
class MemorySource:
    project_id:str
    kind:SourceKind
    entity_id:str
    chapter_id:str|None
    version_id:str|None
    workspace_revision:int
    source_sha256:str

@dataclass(kw_only=True)
class MemoryRecord:
    id:str
    project_id:str
    revision:int
    kind:MemoryKind
    title:str
    text:str
    position_chapter_id:str
    character_id:str|None
    volume_number:int|None
    confirmed:bool
    active:bool
    source:MemorySource
    created_at:str
    updated_at:str

@dataclass(kw_only=True)
class MemoryEdit:
    id:str
    memory_id:str
    revision:int
    previous_version_id:str|None
    snapshot:MemoryRecord
    saved_at:str
    action:Literal['create','edit','archive','review']

def _exact(raw,model):
    if type(raw) is not dict or set(raw)!={f.name for f in fields(model)}:raise DataValidationError('记忆持久字段缺失或未知')
    value=dict(raw)
    if model is MemoryRecord:value['source']=_exact(value['source'],MemorySource)
    if model is MemoryEdit:value['snapshot']=_exact(value['snapshot'],MemoryRecord)
    result=model(**value);_check_type(result,model,'memory')
    return result

def _content(value):
    if isinstance(value,dict):
        return {k:_content(v) for k,v in value.items() if k not in ('id','project_id','created_at','updated_at','current_version_id','previous_version_id','chapter_id','target_character_id','version_id','entity_id','position_chapter_id','character_id') and not k.endswith('_ids')}
    if isinstance(value,list):return [_content(v) for v in value]
    return value

def fingerprint(value):
    return hashlib.sha256(json.dumps(_content(value),ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf8')).hexdigest()

def capture_source(state,ref,*,_index=None):
    if type(ref) is not dict or set(ref)!={'kind','entity_id'}:raise DataValidationError('来源只接受类型和本书实体编号')
    kind,identifier=ref['kind'],ref['entity_id'];doc=state['document'];project=doc['project']['id']
    if type(kind) is not str or type(identifier) is not str:raise DataValidationError('来源类型/编号无效')
    version_id=None;chapter_id=None
    if kind in ('worldbuilding','writing_rules'):
        if identifier!=project:raise DataValidationError('来源不属于当前书')
        value=state[kind]
    elif kind=='idea':
        if identifier not in (_index['chapter_ids'] if _index is not None else {c['id'] for c in doc['chapters']}):raise DataValidationError('来源章节不属于当前书')
        value=state['ideas'].get(identifier,'')
        chapter_id=identifier
    elif kind=='rule':
        rule=_index['entities']['rule'].get(identifier) if _index is not None else next((item for item in state.get('scoped_rules',[]) if item['id']==identifier),None)
        if rule is None:
            legacy_id=str(uuid5(NAMESPACE_URL,project+'/legacy-writing-rules'))
            if identifier==legacy_id and state.get('writing_rules','').strip():
                rule=dict(id=legacy_id,project_id=project,scope='book',scope_id=project,kind='guidance',text=state['writing_rules'],enabled=True,archived=False,source='legacy',version=1,created_at='1970-01-01T00:00:00+00:00',updated_at='1970-01-01T00:00:00+00:00')
            else:raise DataValidationError('来源规则不存在或不属于当前书')
        value=rule
    else:
        collections={'project':[doc['project']],'chapter':doc['chapters'],'character':doc['characters'],
            'chapter_outline':doc['chapter_outlines'],'book_outline':[] if doc['book_outline'] is None else [doc['book_outline']]}
        if kind not in collections:raise DataValidationError('不支持的来源类型')
        value=_index['entities'][kind].get(identifier) if _index is not None else next((item for item in collections[kind] if item['id']==identifier),None)
        if value is None:raise DataValidationError('来源实体不存在或不属于当前书')
        if kind=='chapter':chapter_id=identifier
        elif kind=='chapter_outline':chapter_id=value['chapter_id']
        # Chapters already carry the authoritative current pointer. Do not scan
        # the whole immutable version collection once for every chapter.
        version_id=value.get('current_version_id') if kind=='chapter' else (_index['versions'].get((kind,identifier)) if _index is not None else next(
            (v['id'] for v in reversed(doc['versions']) if v['entity_type']==kind and v['entity_id']==identifier),None))
    return dict(project_id=project,kind=kind,entity_id=identifier,chapter_id=chapter_id,version_id=version_id,
        workspace_revision=state['revision'],source_sha256=fingerprint(value))

def source_catalog(state):
    doc=state['document'];p=doc['project']['id']
    # This index exists only for this exact validated state, never across
    # revisions, repositories or public capture_source() calls. setdefault
    # preserves the original first-match behavior even for duplicate input.
    entities={}
    for kind,items in (('project',[doc['project']]),('chapter',doc['chapters']),('character',doc['characters']),('chapter_outline',doc['chapter_outlines']),('book_outline',[] if doc['book_outline'] is None else [doc['book_outline']]),('rule',state.get('scoped_rules',[]))):
        entities[kind]={}
        for item in items:entities[kind].setdefault(item['id'],item)
    index=dict(entities=entities,chapter_ids=set(entities['chapter']),versions={(v['entity_type'],v['entity_id']):v['id'] for v in doc['versions']})
    refs=[dict(kind=k,entity_id=p) for k in ('project','worldbuilding','writing_rules')]
    for key,kind in (('chapters','chapter'),('characters','character'),('chapter_outlines','chapter_outline')):
        refs.extend(dict(kind=kind,entity_id=item['id']) for item in doc[key])
    if doc['book_outline']:refs.append(dict(kind='book_outline',entity_id=doc['book_outline']['id']))
    refs.extend(dict(kind='idea',entity_id=c['id']) for c in doc['chapters'])
    refs.extend(dict(kind='rule',entity_id=rule['id']) for rule in state.get('scoped_rules',[]))
    if state.get('writing_rules','').strip():refs.append(dict(kind='rule',entity_id=str(uuid5(NAMESPACE_URL,p+'/legacy-writing-rules'))))
    return {(r['kind'],r['entity_id']):capture_source(state,r,_index=index) for r in refs}

def outdated(state,source):
    try:actual=capture_source(state,{'kind':source['kind'],'entity_id':source['entity_id']})
    except (DataValidationError,KeyError):return True
    if actual['version_id']!=source['version_id'] or actual['source_sha256']!=source['source_sha256']:return True
    # V6模型记忆的全部引文仍保存在提案/接受收据中；旧单源表示不改写。
    # 显式重新复核会创建新的source revision，不自动沿用旧模型意见的确认。
    for receipt in state.get('model_proposal_receipts',[]):
        if receipt['decision']!='accepted' or receipt['memory_version_id'] is None or receipt['saved_revision']!=source['workspace_revision']+1:continue
        edit=next((e for e in state.get('memory_history',[]) if e['id']==receipt['memory_version_id']),None)
        if edit is None or edit['snapshot']['source']!=source:continue
        proposal=next((p for p in state.get('model_memory_proposals',[]) if p['id']==receipt['proposal_id']),None)
        if proposal is None:return True
        for evidence in proposal['draft']['evidence']:
            try:value=capture_source(state,dict(kind=evidence['source_kind'],entity_id=evidence['entity_id']))
            except (DataValidationError,KeyError):return True
            if (value['version_id'],value['source_sha256'])!=(evidence['version_id'],evidence['source_sha256']):return True
    return False

def effective_position(state,memory):
    positions={c['id']:c['number'] for c in state['document']['chapters']}
    return max(positions[memory['position_chapter_id']],positions.get(memory['source']['chapter_id'],0))

def validate_record(raw,state):
    m=_exact(raw,MemoryRecord);project=state['document']['project']['id']
    chapters={c['id'] for c in state['document']['chapters']};chars={c['id'] for c in state['document']['characters']}
    volumes={v['number'] for v in (state['document']['book_outline'] or {}).get('volumes',[])}
    if not m.id.strip() or m.project_id!=project or m.revision<1:raise DataValidationError('记忆编号/归属/版本非法')
    if not m.title.strip() or m.position_chapter_id not in chapters or (m.character_id is not None and m.character_id not in chars):raise DataValidationError('记忆标题或当时本书引用非法')
    if m.volume_number is not None and m.volume_number not in volumes:raise DataValidationError('记忆当时分卷不存在')
    if _timestamp(m.updated_at,'memory.updated_at')<_timestamp(m.created_at,'memory.created_at'):raise DataValidationError('记忆时间顺序非法')
    s=m.source
    if s.chapter_id is not None and s.chapter_id not in chapters:raise DataValidationError('记忆出处章节不属于当时本书')
    if s.project_id!=project or not 1<=s.workspace_revision<=state['revision'] or len(s.source_sha256)!=64 or any(c not in '0123456789abcdef' for c in s.source_sha256):raise DataValidationError('记忆出处身份/指纹非法')
    return m

def validate_memory_state(state):
    current=state['memories'];history=state['memory_history'];project=state['document']['project']['id']
    if type(current) is not list or type(history) is not list:raise DataValidationError('记忆集合必须为列表')
    if len(current)>10000 or len(history)>100000:raise DataValidationError('记忆数量超过资源上限')
    chapters={c['id'] for c in state['document']['chapters']};chars={c['id'] for c in state['document']['characters']}
    volumes={v['number'] for v in (state['document']['book_outline'] or {}).get('volumes',[])}
    ids=set();latest={};edits={};counts={}
    for raw in current:
        m=validate_record(raw,state)
        if not m.id.strip() or m.id in ids or m.project_id!=project or m.revision<1:raise DataValidationError('记忆编号/归属/版本非法')
        ids.add(m.id)
        if not m.title.strip() or m.position_chapter_id not in chapters or (m.character_id is not None and m.character_id not in chars):raise DataValidationError('记忆标题或本书引用非法')
        if m.volume_number is not None and m.volume_number not in volumes:raise DataValidationError('记忆分卷不存在')
        if _timestamp(m.updated_at,'memory.updated_at')<_timestamp(m.created_at,'memory.created_at'):raise DataValidationError('记忆时间顺序非法')
        s=m.source
        if s.project_id!=project or not 1<=s.workspace_revision<=state['revision'] or len(s.source_sha256)!=64 or any(c not in '0123456789abcdef' for c in s.source_sha256):raise DataValidationError('记忆出处身份/指纹非法')
    for raw in history:
        h=_exact(raw,MemoryEdit);m=h.snapshot
        if h.id in edits or not h.id.strip() or h.memory_id not in ids or m.id!=h.memory_id or m.project_id!=project:raise DataValidationError('记忆编辑身份非法')
        count=counts.get(h.memory_id,0)+1
        if h.revision!=count or m.revision!=count or h.previous_version_id!=edits.get(h.memory_id):raise DataValidationError('记忆编辑版本链非法')
        if _timestamp(h.saved_at,'memory.saved_at')<_timestamp(m.updated_at,'memory.updated_at'):raise DataValidationError('记忆保存时间非法')
        counts[h.memory_id]=count;edits[h.memory_id]=h.id;edits[h.id]=h.id;latest[h.memory_id]=asdict(m)
    for m in current:
        if latest.get(m['id'])!=m:raise DataValidationError('记忆当前值与最后编辑快照不一致')
    return state
