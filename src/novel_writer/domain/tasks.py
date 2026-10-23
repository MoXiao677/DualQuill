"""V3任务领域类型。加载完整校验；冻结输入深不可变，不调用ID/时间工厂。"""
from __future__ import annotations
from dataclasses import dataclass,fields,is_dataclass
from types import UnionType
from typing import Literal,Union,get_args,get_origin,get_type_hints
from hashlib import sha256
from novel_writer.domain.models import DataValidationError,_timestamp
from novel_writer.domain.memory import fingerprint
from novel_writer.domain.memory import capture_source,source_catalog,outdated,effective_position
from uuid import UUID
from functools import lru_cache

@lru_cache(maxsize=None)
def _hints(model):
    # 仅缓存稳定类型声明，不缓存实例或“已验证”标记；每次仍逐字段验值。
    return get_type_hints(model)

Capability=Literal['rewrite_chapter','audit_chapter','draft_chapter','continue_chapter']
SourceKind=Literal['project','chapter','character','chapter_outline','book_outline','worldbuilding','writing_rules','idea','memory','memory_rollup','skill','rule','material']
class _TaskValue:
    def __post_init__(self):
        check_types(type(self),self)
        validate_local(self)
@dataclass(frozen=True,kw_only=True)
class Reference(_TaskValue):
    path:str
    kind:Literal['project','chapter','character','chapter_outline','book_outline','version','memory','memory_version','memory_rollup','memory_rollup_history','skill','material','material_version']
    entity_id:str
@dataclass(frozen=True,kw_only=True)
class Dependency(_TaskValue):
    project_id:str
    kind:SourceKind
    entity_id:str
    version_id:str|None
    source_sha256:str
    source_revision:int
    chapter_id:str|None
    position_number:int|None
    references:tuple[Reference,...]
    use:Literal['target','context','plan_guard','analysis']
    scope:Literal['book','global']
    file_path:str|None
    memory_fresh:bool|None
@dataclass(frozen=True,kw_only=True)
class SearchExcerpt(_TaskValue):
    start:int
    end:int
    sha256:str
@dataclass(frozen=True,kw_only=True)
class SearchSelection(_TaskValue):
    project_id:str
    kind:SourceKind
    entity_id:str
    workspace_revision:int
    version_id:str|None
    source_sha256:str
    scope:Literal['book','global']
    file_path:str|None
    excerpt:SearchExcerpt|None=None
@dataclass(frozen=True,kw_only=True)
class ContextOptions(_TaskValue):
    chapter_id:str
    scope:Literal['previous','through_current']
    budget_chars:int
    include_current_plan:bool
    include_book_outline:bool
    include_characters:bool
    character_ids:tuple[str,...]
    include_worldbuilding:bool
    include_writing_rules:bool
    include_memories:bool
    memory_ids:tuple[str,...]
    include_search_results:bool
    search_selections:tuple[SearchSelection,...]
    include_memory_rollups:bool=False
    rule_task_id:str|None=None
    include_automatic_memories:bool=False
    retrieval_owner:str|None=None
@dataclass(frozen=True,kw_only=True)
class TaskParameters(_TaskValue):
    instruction:str
    max_output_chars:int
    timeout_ms:int
from novel_writer.domain.review import AnalysisParameters
from novel_writer.domain.model_contract import ModelTaskParameters,ModelAnalysisParameters,ModelCandidate,validate_binding,WritingParameters,ModelWritingParameters
@dataclass(frozen=True,kw_only=True)
class Target(_TaskValue):
    chapter_id:str
    version_id:str|None
    title:str
    text:str
    status:Literal['draft','confirmed']
    number:int
    source_sha256:str
@dataclass(frozen=True,kw_only=True)
class SkillFile(_TaskValue):
    path:str
    content:str
@dataclass(frozen=True,kw_only=True)
class SkillSnapshot(_TaskValue):
    id:str
    name:str
    description:str
    imported_at:str
    primary_path:str
    files:tuple[SkillFile,...]
@dataclass(frozen=True,kw_only=True)
class FrozenInput(_TaskValue):
    project_id:str
    chapter_id:str
    source_revision:int
    target:Target
    context_text:str
    context_sha256:str
    context_options:ContextOptions
    dependencies:tuple[Dependency,...]
    parameters:TaskParameters|AnalysisParameters|ModelTaskParameters|ModelAnalysisParameters|CandidateModelParameters|WorkflowModelParameters|CandidateAuditParameters|WritingParameters|ModelWritingParameters
    skill_snapshots:tuple[SkillSnapshot,...]

    @classmethod
    def from_dict(cls,value):
        result=parse(cls,value);validate_frozen(result);return result

def encode(value):
    if is_dataclass(value):
        from novel_writer.domain.sampling import Sampling
        return {f.name:encode(getattr(value,f.name)) for f in fields(value) if not (type(value) is ContextOptions and f.name=='retrieval_owner' and value.retrieval_owner is None) and not (type(value) is SearchSelection and f.name=='excerpt' and value.excerpt is None) and not (f.name=='stream_mode' and getattr(value,f.name)=='json') and (f.name not in ('sampling','chapter_source','summary_memory_sha256','response_record_id','rule_task_id','deep_review','rule_sources') or getattr(value,f.name) is not None) and not (type(value) is ContextOptions and f.name in ('include_memory_rollups','include_automatic_memories') and getattr(value,f.name) is False) and not (type(value) is Sampling and f.name in ('temperature_mode','chat_token_field') and getattr(value,f.name)==f.default)}
    if isinstance(value,tuple):return [encode(v) for v in value]
    if isinstance(value,list):return [encode(v) for v in value]
    if isinstance(value,dict):return {k:encode(v) for k,v in value.items()}
    return value

def parse(annotation,value):
    origin,args=get_origin(annotation),get_args(annotation)
    if origin in (Union,UnionType):
        for option in args:
            try:return parse(option,value)
            except DataValidationError:pass
        raise DataValidationError('任务字段类型非法')
    if origin is Literal:
        if not any(type(v) is type(value) and value==v for v in args):raise DataValidationError('任务字段枚举非法')
        return value
    if origin is tuple:
        if type(value) not in (list,tuple):raise DataValidationError('任务集合必须是列表')
        if len(value)>100000:raise DataValidationError('任务集合超过资源上限')
        return tuple(parse(args[0],v) for v in value)
    if is_dataclass(annotation):
        names={f.name for f in fields(annotation)}
        optional={f.name for f in fields(annotation) if f.name in ('sampling','chapter_source','summary_memory_sha256','response_record_id','rule_task_id','deep_review','rule_sources') and f.default is None}
        from novel_writer.domain.sampling import Sampling
        if annotation is Sampling:optional|={'temperature_mode','chat_token_field'}
        if annotation is ContextOptions:optional|={'include_memory_rollups','rule_task_id','include_automatic_memories','retrieval_owner'}
        if annotation is SearchSelection:optional.add('excerpt')
        optional|={f.name for f in fields(annotation) if f.name=='stream_mode' and f.default=='json'}
        if type(value) is not dict or not names-optional<=set(value)<=names or 'sampling' in value and value['sampling'] is None:raise DataValidationError('任务持久字段缺失或未知')
        hints=_hints(annotation)
        return annotation(**{name:parse(hints[name],value[name]) for name in value})
    if type(value) is not annotation:raise DataValidationError('任务字段类型非法')
    if annotation is str:
        try:value.encode('utf8',errors='strict')
        except UnicodeError:raise DataValidationError('任务字段UTF8非法') from None
    return value

def require(ok,message):
    if not ok:raise DataValidationError(message)
def digest(text):return sha256(text.encode('utf8')).hexdigest()
def hash_value(value):return type(value) is str and len(value)==64 and all(c in '0123456789abcdef' for c in value)
def identifier(value):return type(value) is str and bool(value.strip())

def validate_frozen(value):
    require(type(value) is FrozenInput,'执行只接受领域冻结输入')
    check_types(FrozenInput,value)
    require(identifier(value.project_id) and identifier(value.chapter_id),'冻结项目/章节身份非法')
    require(value.source_revision>=1 and value.target.chapter_id==value.chapter_id,'冻结来源/目标归属非法')
    target=value.target
    require(target.number>=1 and bool(target.title.strip()),'冻结目标非法')
    require(target.source_sha256==fingerprint(dict(number=target.number,title=target.title,content=target.text,status=target.status)),'冻结原稿指纹不匹配')
    options=value.context_options
    require(options.chapter_id==value.chapter_id and 128<=options.budget_chars<=20000,'冻结上下文范围非法')
    if any(s.excerpt is not None or s.kind=='material' for s in options.search_selections):require(options.retrieval_owner is not None,'精确检索冻结必须绑定本次会话')
    require(len(value.context_text)<=options.budget_chars and value.context_sha256==digest(value.context_text),'冻结资料串/字符预算不符')
    p=value.parameters
    if isinstance(p,(WorkflowModelParameters,CandidateAuditParameters,CandidateModelParameters)):p.upstream.__post_init__();require(encode(p.upstream.saved_target)==encode(value.target),'上游必须保留正式目标原保存版本守卫')
    if isinstance(p,(ModelTaskParameters,ModelAnalysisParameters)):validate_binding(value)
    require(len(p.instruction)<=4000 and 128<=p.max_output_chars<=100000 and 100<=p.timeout_ms<=300000,'任务参数超限')
    targets=[d for d in value.dependencies if d.use=='target']
    require(len(targets)==1,'冻结任务必须有唯一目标依赖')
    require(targets[0].kind=='chapter' and targets[0].entity_id==value.chapter_id and targets[0].version_id==target.version_id and targets[0].source_sha256==target.source_sha256,'目标与冻结依赖不一致')
    for dep in value.dependencies:
        require(dep.project_id==value.project_id and identifier(dep.entity_id),'依赖不属于冻结项目')
        require(dep.source_revision==value.source_revision and hash_value(dep.source_sha256),'依赖来源/指纹非法')
        require((dep.kind=='skill')==(dep.scope=='global'),'依赖全局范围非法')
        require(dep.position_number is None or dep.position_number>=1,'依赖故事位置非法')
        for ref in dep.references:require(identifier(ref.entity_id) and len(ref.path)<=200,'依赖引用非法')
    for selected in options.search_selections:
        require(selected.project_id==value.project_id and selected.workspace_revision==value.source_revision and hash_value(selected.source_sha256),'冻结搜索来源过期或跨书')
    for skill in value.skill_snapshots:
        require(identifier(skill.id) and 0<len(skill.files)<=100,'冻结Skills字段非法')
        _timestamp(skill.imported_at,'task.skill.imported_at')
        require(skill.primary_path in {f.path for f in skill.files},'冻结Skill主文件缺失')
    if isinstance(p,AnalysisParameters):
        from novel_writer.domain.review import source_value
        require(value.chapter_id in p.selected_chapter_ids,'审核主章不在显式范围')
        for source in p.sources:
            require(source.project_id==value.project_id and source.source_revision==value.source_revision,'审核来源跨书/revision不符')
            dep=next((d for d in value.dependencies if d.use=='analysis' and d.kind==source.kind and d.entity_id==source.entity_id),None)
            require(dep is not None and (dep.version_id,dep.source_sha256,dep.chapter_id,dep.position_number)==(source.version_id,source.source_sha256,source.chapter_id,source.chapter_number),'审核快照未绑定真实版本/章位依赖')
            require(dep.references==_refs(source_value(source),source.kind),'审核结构引用与依赖不符')
        for waiver in p.waivers:require(waiver.project_id==value.project_id,'审核白名单跨书')

Status=Literal['pending','running','succeeded','failed','cancelled','interrupted']
@dataclass(frozen=True,kw_only=True)
class GenerationTask(_TaskValue):
    id:str
    request_id:str
    project_id:str
    chapter_id:str
    task_type:Capability
    frozen:FrozenInput
    status:Status
    attempt_id:str|None
    owner_id:str|None
    candidate_id:str|None
    created_at:str
    updated_at:str
    started_at:str|None
    finished_at:str|None
    error_code:str|None
@dataclass(frozen=True,kw_only=True)
class Candidate(_TaskValue):
    id:str
    project_id:str
    chapter_id:str
    task_id:str
    attempt_id:str
    output_text:str
    created_at:str
    provenance:Literal['local_protocol_fixture']
    token_count:None
    cost:None
@dataclass(frozen=True,kw_only=True)
class TaskEvent(_TaskValue):
    id:str
    task_id:str
    seq:int
    previous_event_id:str|None
    kind:Literal['prepared','started','succeeded','failed','cancelled','interrupted','adopted']
    from_status:Status|None
    status:Status
    attempt_id:str|None
    owner_id:str|None
    candidate_id:str|None
    adoption_id:str|None
    created_at:str
    error_code:str|None
@dataclass(frozen=True,kw_only=True)
class AdoptionReceipt(_TaskValue):
    id:str
    project_id:str
    chapter_id:str
    task_id:str
    candidate_id:str
    version_before:str|None
    version_after:str
    applied_revision:int
    requested_revision:int
    authorize_confirmed:bool
    adopted_at:str

COLLECTIONS={'generation_tasks':GenerationTask,'task_events':TaskEvent,'generation_candidates':Candidate|ModelCandidate,'adoption_receipts':AdoptionReceipt}
def uuid_value(value):
    try:require(type(value) is str and str(UUID(value))==value,'任务操作身份必须为规范UUID')
    except (ValueError,TypeError,AttributeError):raise DataValidationError('任务操作身份必须为规范UUID') from None
    return value

def _refs(value,kind):
    refs=[]
    def add(path,k,i):
        if i is not None:refs.append(Reference(path=path,kind=k,entity_id=i))
    if kind=='book_outline':
        for n,v in enumerate(value['volumes']):
            for i,c in enumerate(v['chapter_ids']):add(f'volumes.{n}.chapter_ids.{i}','chapter',c)
    elif kind=='character':
        for i,r in enumerate(value['relationships']):add(f'relationships.{i}','character',r['target_character_id'])
    elif kind=='chapter_outline':
        add('chapter_id','chapter',value['chapter_id'])
        for i,c in enumerate(value['character_ids']):add(f'character_ids.{i}','character',c)
        for n,s in enumerate(value['scenes']):
            for i,c in enumerate(s['character_ids']):add(f'scenes.{n}.character_ids.{i}','character',c)
    elif kind=='memory':
        add('position_chapter_id','chapter',value['position_chapter_id']);add('character_id','character',value['character_id'])
        s=value['source'];add('source.project_id','project',s['project_id']);add('source.chapter_id','chapter',s['chapter_id'])
        k='project' if s['kind'] in ('worldbuilding','writing_rules') else 'chapter' if s['kind']=='idea' else s['kind']
        add('source.entity_id',k,s['entity_id']);add('source.version_id','version',s['version_id'])
    return tuple(refs)

def capture_dependency(state,kind,identifier,*,use='context',skill=None,file_path=None):
    doc=state['document'];positions={c['id']:c['number'] for c in doc['chapters']};project=doc['project']['id']
    fresh=None;refs=();chapter=None;position=None
    if kind=='skill':
        require(skill is not None and skill['id']==identifier and file_path in {f['path'] for f in skill['files']},'冻结全局资料不存在')
        sha=fingerprint(skill);version=None
    elif kind=='material':
        from novel_writer.domain.materials import current_version,require_current_index
        material=next((m for m in state.get('materials',[]) if m['id']==identifier),None);require(material is not None,'冻结资料不存在')
        current=current_version(state,material);version=current['id'];sha=current['text_sha256']
        fresh=not material['archived']
        try:require_current_index(state,material)
        except DataValidationError:fresh=False
        refs=(Reference(path='material_id',kind='material',entity_id=identifier),Reference(path='current_version_id',kind='material_version',entity_id=version))
    elif kind=='memory_rollup':
        rollup=next((v for v in state.get('memory_rollups',[]) if v['id']==identifier),None);require(rollup is not None,'冻结汇总不存在')
        edit=next(v for v in reversed(state['memory_rollup_history']) if v['rollup_id']==identifier)
        from novel_writer.domain.chapter_trash import hidden_ids
        hidden=hidden_ids(state);memories={m['id']:m for m in state.get('memories',[])}
        version=edit['id'];sha=fingerprint(rollup);chapter=rollup['through_chapter_id'];position=rollup['through_position']
        fresh=chapter not in hidden and (not rollup.get('chapter_source') or not outdated(state,rollup['chapter_source']))
        for s in rollup['sources']:
            m=memories.get(s['memory_id']);fresh=fresh and m is not None and m['revision']==s['memory_revision'] and m['active'] and m['confirmed'] and not outdated(state,m['source']) and m['position_chapter_id'] not in hidden and m['source']['chapter_id'] not in hidden
        refs=(Reference(path='through_chapter_id',kind='chapter',entity_id=chapter),)+tuple(Reference(path=f'sources.{n}.memory_id',kind='memory',entity_id=s['memory_id']) for n,s in enumerate(rollup['sources']))
    elif kind=='memory':
        memory=next((m for m in state.get('memories',[]) if m['id']==identifier),None);require(memory is not None,'冻结记忆不存在')
        edit=next(h for h in reversed(state['memory_history']) if h['memory_id']==identifier)
        version=edit['id'];sha=fingerprint(memory);refs=_refs(memory,kind)
        chapter=memory['position_chapter_id'];position=effective_position(state,memory)
        fresh=memory['active'] and memory['confirmed'] and not outdated(state,memory['source'])
    else:
        source=capture_source(state,{'kind':kind,'entity_id':identifier});version=source['version_id'];sha=source['source_sha256'];chapter=source['chapter_id']
        position=positions.get(chapter)
        collections={'project':[doc['project']],'chapter':doc['chapters'],'character':doc['characters'],'chapter_outline':doc['chapter_outlines'],'book_outline':[doc['book_outline']]}
        if kind in collections:refs=_refs(next(v for v in collections[kind] if v and v['id']==identifier),kind)
    return Dependency(project_id=project,kind=kind,entity_id=identifier,version_id=version,source_sha256=sha,
        source_revision=state['revision'],chapter_id=chapter,position_number=position,references=refs,use=use,
        scope='global' if kind=='skill' else 'book',file_path=file_path,memory_fresh=fresh)

def dependency_equal(left,right):
    a=encode(left);b=encode(right)
    for key in ('source_revision','use'):a.pop(key);b.pop(key)
    return a==b

def dependency_catalog(state):
    result={key:capture_dependency(state,*key) for key in source_catalog(state)}
    for m in state.get('memories',[]):result['memory',m['id']]=capture_dependency(state,'memory',m['id'])
    for r in state.get('memory_rollups',[]):result['memory_rollup',r['id']]=capture_dependency(state,'memory_rollup',r['id'])
    for m in state.get('materials',[]):result['material',m['id']]=capture_dependency(state,'material',m['id'])
    return result

def validate_task_state(state):
    project=state['document']['project']['id'];chapters={c['id']:c for c in state['document']['chapters']}
    parsed={}
    for name,model in COLLECTIONS.items():
        raw=state[name];require(type(raw) is list and len(raw)<=100000,'任务持久集合非法或超限')
        parsed[name]=[parse(model,v) for v in raw]
        ids=[r.id for r in parsed[name]];require(len(ids)==len(set(ids)),'任务持久集合ID重复')
        for record in parsed[name]:uuid_value(record.id)
    tasks={t.id:t for t in parsed['generation_tasks']};candidates={c.id:c for c in parsed['generation_candidates']};receipts={r.id:r for r in parsed['adoption_receipts']}
    requests=[]
    for task in tasks.values():
        uuid_value(task.request_id);requests.append(task.request_id);validate_frozen(task.frozen)
        require(state['workspace_version']>=36 or task.frozen.context_options.rule_task_id is None,'任务规则冻结需要V36工作区')
        require(state['workspace_version']>=32 or not any(d.kind=='memory_rollup' for d in task.frozen.dependencies),'汇总上下文依赖需要V32工作区')
        require(state['workspace_version']>=42 or not task.frozen.context_options.include_automatic_memories,'自动记忆上下文需要V42工作区')
        require(state['workspace_version']>=44 or not any(s.excerpt is not None or s.kind=='material' for s in task.frozen.context_options.search_selections),'精确检索上下文需要V44工作区')
        require(state['workspace_version']>=44 or task.frozen.context_options.retrieval_owner is None,'检索会话许可需要V44工作区')
        require(state['workspace_version']>=44 or not any(d.kind=='material' for d in task.frozen.dependencies),'资料依赖需要V44工作区')
        if state['workspace_version']==3:require(task.task_type=='rewrite_chapter' and type(task.frozen.parameters) is TaskParameters,'V3不声明分析能力')
        if state['workspace_version']<6:require(not isinstance(task.frozen.parameters,(ModelTaskParameters,ModelAnalysisParameters)),'模型冻结数据需要正式V6')
        require((task.task_type=='audit_chapter')==isinstance(task.frozen.parameters,(AnalysisParameters,CandidateAuditParameters,CandidateModelParameters)),'任务能力与参数类型不符')
        if state['workspace_version']<8:require(not isinstance(task.frozen.parameters,(WorkflowModelParameters,CandidateAuditParameters,CandidateModelParameters)),'工作流输入必须使用正式V8')
        writing=task.task_type in ('draft_chapter','continue_chapter')
        require(writing==isinstance(task.frozen.parameters,ModelWritingParameters),'正文用途与冻结参数不符')
        if writing:require(state['workspace_version']>=16 and (task.frozen.parameters.writing.mode=='draft')==(task.task_type=='draft_chapter') and ((task.frozen.target.text=='') if task.task_type=='draft_chapter' else bool(task.frozen.target.text.strip())),'初稿须空正文，已有正文请续写或改写')
        require(task.project_id==project==task.frozen.project_id and task.chapter_id==task.frozen.chapter_id and task.chapter_id in chapters,'任务归属/目标非法')
        require(task.frozen.source_revision<=state['revision'],'冻结来源revision在未来')
        for value in (task.attempt_id,task.owner_id,task.candidate_id):
            if value is not None:uuid_value(value)
        _timestamp(task.created_at,'task.created_at');_timestamp(task.updated_at,'task.updated_at')
    require(len(requests)==len(set(requests)),'准备请求身份重复')
    per_task={i:[] for i in tasks}
    for event in parsed['task_events']:
        require(event.task_id in tasks,'任务事件悬空');per_task[event.task_id].append(event)
    transitions={'pending':{'running','cancelled'},'running':{'succeeded','failed','cancelled','interrupted'}}
    for task in tasks.values():
        events=per_task[task.id];require(bool(events),'任务缺少事件历史')
        previous=None;started=None;terminal=None
        for index,event in enumerate(events):
            require(event.seq==index+1 and event.previous_event_id==(previous.id if previous else None),'任务事件链不连续')
            require(event.from_status==(previous.status if previous else None),'任务事件前状态不一致')
            _timestamp(event.created_at,'event.created_at')
            if previous:require(event.created_at>=previous.created_at,'任务事件时间回退')
            if event.kind=='prepared':require(index==0 and event.status=='pending' and event.attempt_id is None and event.owner_id is None,'准备事件非法')
            elif event.kind=='adopted':
                require(previous is not None and previous.status=='succeeded' and event.status=='succeeded' and event.adoption_id in receipts,'采纳事件非法')
            else:
                require(previous is not None and event.status in transitions.get(previous.status,set()),'非法任务状态转移')
                if event.kind=='started':
                    require(started is None and event.status=='running' and event.attempt_id is not None and event.owner_id is not None,'执行attempt非法');started=event
                else:
                    require(event.kind==event.status,'终态事件类别不符');terminal=event
            if started:require((event.attempt_id,event.owner_id)==(started.attempt_id,started.owner_id),'执行身份被替换')
            previous=event
        require((task.status,task.attempt_id,task.owner_id,task.candidate_id,task.error_code)==(previous.status,previous.attempt_id,previous.owner_id,previous.candidate_id,previous.error_code),'任务当前值与事件不一致')
        require(task.created_at==events[0].created_at and task.updated_at==events[-1].created_at and task.started_at==(started.created_at if started else None) and task.finished_at==(terminal.created_at if terminal else None),'任务当前时间与历史不符')
        if task.status=='succeeded' and task.task_type in ('rewrite_chapter','draft_chapter','continue_chapter'):require(task.candidate_id in candidates,'成功正文任务缺少候选')
        elif task.status=='succeeded':require(task.candidate_id is None and sum(r['task_id']==task.id for r in state.get('review_reports',[])+state.get('model_reports',[])+state.get('workflow_audits',[])+state.get('graph_extractions',[]))==1,'成功分析任务缺少唯一报告')
        else:require(task.candidate_id is None,'未成功任务不能有候选')
    for candidate in candidates.values():
        if state['workspace_version']<6:require(type(candidate) is Candidate,'旧格式不能携带V6模型候选')
        require(candidate.task_id in tasks,'候选任务悬空');task=tasks[candidate.task_id]
        require((candidate.project_id,candidate.chapter_id,candidate.attempt_id,candidate.id)==(project,task.chapter_id,task.attempt_id,task.candidate_id) and task.status=='succeeded','候选归属/终态不符')
        require(bool(candidate.output_text.strip()) and len(candidate.output_text)<=task.frozen.parameters.max_output_chars,'候选为空或超限')
        require(any(e.kind=='succeeded' and e.candidate_id==candidate.id and e.created_at==candidate.created_at for e in per_task[task.id]),'候选没有真实完成事件')
    versions={v['id']:v for v in state['document']['versions']}
    adopted_candidates=set()
    for receipt in receipts.values():
        require(receipt.task_id in tasks and receipt.candidate_id in candidates,'采纳收据悬空');task=tasks[receipt.task_id];candidate=candidates[receipt.candidate_id]
        require(receipt.project_id==project and receipt.chapter_id==task.chapter_id and candidate.task_id==task.id,'采纳收据归属不符')
        require(receipt.version_before==task.frozen.target.version_id and receipt.version_after in versions,'采纳目标版本不符')
        version=versions[receipt.version_after]
        applied=candidate.output_text
        if task.task_type in ('draft_chapter','continue_chapter'):
            from novel_writer.domain.chapter_writing import adopted_text
            applied=adopted_text(state,task,receipt)
        require(version['entity_type']=='chapter' and version['entity_id']==receipt.chapter_id and version['snapshot']['content']==applied,'采纳版本与候选原文不符')
        require(1<=receipt.requested_revision<receipt.applied_revision<=state['revision'],'采纳revision不符')
        require(task.frozen.target.status!='confirmed' or receipt.authorize_confirmed,'正式章缺少作者授权')
        require(receipt.candidate_id not in adopted_candidates,'候选重复采纳');adopted_candidates.add(receipt.candidate_id)
        require(sum(e.adoption_id==receipt.id for e in per_task[task.id])==1,'采纳收据缺事件或重复事件')
        _timestamp(receipt.adopted_at,'receipt.adopted_at')
    return parsed

def validate_task_transition(state,previous,catalogs):
    validate_task_state(state)
    for name in ('task_events','generation_candidates','adoption_receipts'):
        old=previous.get(name,[]);require(state[name][:len(old)]==old,'已有任务事件/候选/收据不可改写/删除/重排')
    old_tasks=previous.get('generation_tasks',[]);require([t['id'] for t in state['generation_tasks'][:len(old_tasks)]]==[t['id'] for t in old_tasks],'任务身份列表不可删改')
    for old,new in zip(old_tasks,state['generation_tasks']):
        for key in ('id','request_id','project_id','chapter_id','task_type','frozen','created_at'):require(old[key]==new[key],'冻结任务输入不可改写')
    for raw in state['generation_tasks'][len(old_tasks):]:
        task=parse(GenerationTask,raw);catalog=catalogs.get(task.frozen.source_revision,{})
        for dep in task.frozen.dependencies:
            if dep.kind=='skill':
                skill=next((encode(s) for s in task.frozen.skill_snapshots if s.id==dep.entity_id),None)
                require(skill is not None and fingerprint(skill)==dep.source_sha256,'冻结全局来源缺少匹配原始快照')
            else:
                actual=catalog.get((dep.kind,dep.entity_id));require(actual is not None and dependency_equal(dep,actual),'冻结依赖不属于所声明的历史状态')

def check_types(annotation,value):
    """无构造副作用的walker，构造/加载/registry共用，不递归调用parse。"""
    origin,args=get_origin(annotation),get_args(annotation)
    if origin in (Union,UnionType):
        for option in args:
            try:check_types(option,value);return
            except DataValidationError:pass
        raise DataValidationError('任务对象字段类型非法')
    if origin is Literal:
        require(any(type(value) is type(v) and value==v for v in args),'任务对象枚举非法');return
    if origin is tuple:
        require(type(value) is tuple,'冻结对象不接受可变嵌套列表')
        for item in value:check_types(args[0],item)
        return
    if is_dataclass(annotation):
        require(type(value) is annotation,'任务嵌套必须是领域对象')
        hints=_hints(annotation)
        for f in fields(annotation):check_types(hints[f.name],getattr(value,f.name))
        return
    require(type(value) is annotation,'任务对象字段类型非法')
    if annotation is str:
        try:value.encode('utf8',errors='strict')
        except UnicodeError:raise DataValidationError('任务对象编码非法') from None

def validate_local(value):
    if type(value) is FrozenInput:validate_frozen(value)
    elif type(value) is Target:
        require(identifier(value.chapter_id) and value.number>=1 and bool(value.title.strip()),'任务目标字段非法')
        require(value.source_sha256==fingerprint(dict(number=value.number,title=value.title,content=value.text,status=value.status)),'任务目标指纹非法')
    elif type(value) is TaskParameters:require(len(value.instruction)<=4000 and 128<=value.max_output_chars<=100000 and 100<=value.timeout_ms<=300000,'任务参数非法')
    elif type(value) is ContextOptions:
        require(identifier(value.chapter_id) and 128<=value.budget_chars<=20000,'上下文范围非法')
        if value.retrieval_owner is not None:uuid_value(value.retrieval_owner)
    elif type(value) is Reference:require(identifier(value.entity_id) and bool(value.path) and len(value.path)<=200,'任务引用非法')
    elif type(value) is Dependency:
        require(identifier(value.project_id) and identifier(value.entity_id) and hash_value(value.source_sha256) and value.source_revision>=1,'依赖字段非法')
        require((value.kind=='skill')==(value.scope=='global'),'依赖范围非法')
        require(value.position_number is None or value.position_number>=1,'依赖故事位置非法')
    elif type(value) is SearchExcerpt:require(value.start>=0 and value.end>value.start and value.end-value.start<=800 and hash_value(value.sha256),'检索引文范围/哈希非法')
    elif type(value) is SearchSelection:require(identifier(value.project_id) and identifier(value.entity_id) and hash_value(value.source_sha256) and value.workspace_revision>=1,'搜索引用非法')
    elif type(value) is SkillFile:require(identifier(value.path),'冻结文件路径为空')
    elif type(value) is SkillSnapshot:
        require(identifier(value.id) and 0<len(value.files)<=100 and value.primary_path in {f.path for f in value.files},'冻结Skill非法');_timestamp(value.imported_at,'task.skill')
    elif type(value) in (GenerationTask,Candidate,TaskEvent,AdoptionReceipt):
        uuid_value(value.id)
        if type(value) is GenerationTask:
            uuid_value(value.request_id);validate_frozen(value.frozen)
            require(value.project_id==value.frozen.project_id and value.chapter_id==value.frozen.chapter_id,'任务冻结归属非法')
            _timestamp(value.created_at,'task.created');_timestamp(value.updated_at,'task.updated')
            require(value.updated_at>=value.created_at,'任务更新时间回退')
            for identifier_value in (value.attempt_id,value.owner_id,value.candidate_id):
                if identifier_value is not None:uuid_value(identifier_value)
            if value.status=='pending':require(value.attempt_id is None and value.owner_id is None and value.candidate_id is None and value.started_at is None and value.finished_at is None and value.error_code is None,'待执行任务字段非法')
            elif value.status=='cancelled' and value.attempt_id is None:require(value.owner_id is None and value.started_at is None and value.finished_at is not None and value.candidate_id is None,'待执行取消字段非法')
            else:
                require(value.attempt_id is not None and value.owner_id is not None and value.started_at is not None,'执行记录缺少attempt/归属/时间')
                _timestamp(value.started_at,'task.started')
                require((value.finished_at is None)==(value.status=='running'),'执行终态时间非法')
                require((value.candidate_id is not None)==(value.status=='succeeded' and value.task_type in ('rewrite_chapter','draft_chapter','continue_chapter')),'正文候选仅能对应正文成功终态')
            if value.finished_at is not None:_timestamp(value.finished_at,'task.finished')
        elif type(value) is Candidate:
            uuid_value(value.task_id);uuid_value(value.attempt_id);require(identifier(value.project_id) and identifier(value.chapter_id) and bool(value.output_text.strip()),'候选字段非法');_timestamp(value.created_at,'candidate.created')
        elif type(value) is TaskEvent:
            uuid_value(value.task_id);require(value.seq>=1,'事件序号非法');_timestamp(value.created_at,'event.created')
        else:
            uuid_value(value.task_id);uuid_value(value.candidate_id);require(value.applied_revision>value.requested_revision>=1,'采纳revision非法');_timestamp(value.adopted_at,'receipt.at')

from novel_writer.domain.workflow_contract import WorkflowModelParameters,CandidateAuditParameters,CandidateModelParameters

