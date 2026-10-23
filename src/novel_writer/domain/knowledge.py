"""V5人工知识图谱/规划反馈/局部编辑。所有修订显式追加，不从计划推定事实。"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
from novel_writer.domain.tasks import check_types,parse,encode,require,uuid_value,Dependency
from novel_writer.domain.memory import SourceKind,capture_source
from novel_writer.domain.review import Evidence
from novel_writer.domain.models import _timestamp

class Value:
    def __post_init__(self):
        check_types(type(self),self)
        if hasattr(self,'id'):uuid_value(self.id)
        if hasattr(self,'edit_id'):uuid_value(self.edit_id)
        if hasattr(self,'created_at'):_timestamp(self.created_at,'knowledge.created_at')
        if hasattr(self,'revision'):require(self.revision>=1,'知识对象版本非法')

@dataclass(frozen=True,kw_only=True)
class Source(Value):
    project_id:str
    kind:SourceKind
    entity_id:str
    chapter_id:str|None
    version_id:str|None
    workspace_revision:int
    source_sha256:str

@dataclass(frozen=True,kw_only=True)
class Node(Value):
    id:str
    project_id:str
    edit_id:str
    revision:int
    kind:Literal['character','location','organization','event','prop','setting','foreshadow']
    label:str
    aliases:tuple[str,...]
    memory_ids:tuple[str,...]
    position_chapter_id:str
    source:Source
    basis:Literal['plan','saved_source']
    confirmed:bool
    active:bool
    merged_into:str|None
    created_at:str

@dataclass(frozen=True,kw_only=True)
class Edge(Value):
    id:str
    project_id:str
    edit_id:str
    revision:int
    from_id:str
    to_id:str
    relation:str
    position_chapter_id:str
    source:Source
    confirmed:bool
    active:bool
    created_at:str

@dataclass(frozen=True,kw_only=True)
class Merge(Value):
    id:str
    project_id:str
    source_id:str
    target_id:str
    before_nodes:tuple[Node,...]
    before_edges:tuple[Edge,...]
    after_edit_ids:tuple[str,...]
    created_at:str

@dataclass(frozen=True,kw_only=True)
class Restore(Value):
    id:str
    project_id:str
    merge_id:str
    created_at:str

@dataclass(frozen=True,kw_only=True)
class Impact(Value):
    later_chapter_ids:tuple[str,...]
    foreshadow_node_ids:tuple[str,...]
    memory_ids:tuple[str,...]
    locked:bool
    limitations:tuple[str,...]

@dataclass(frozen=True,kw_only=True)
class Plan(Value):
    id:str
    project_id:str
    target_kind:Literal['book_outline','chapter_outline']
    target_id:str
    field:Literal['theme','premise','main_plot','ending','core_idea','objective','story_time']
    old_text:str
    new_text:str
    reason:str
    source:Source
    target:Source
    impact:Impact
    created_at:str

@dataclass(frozen=True,kw_only=True)
class PlanLock(Value):
    id:str
    project_id:str
    target_kind:Literal['book_outline','chapter_outline']
    target_id:str
    field:Literal['theme','premise','main_plot','ending','core_idea','objective','story_time']
    locked:bool
    reason:str
    created_at:str

@dataclass(frozen=True,kw_only=True)
class PlanReceipt(Value):
    id:str
    project_id:str
    proposal_id:str
    decision:Literal['accepted','rejected']
    version_before:str|None
    version_after:str|None
    saved_revision:int
    created_at:str

@dataclass(frozen=True,kw_only=True)
class LocalEdit(Value):
    id:str
    project_id:str
    edit_id:str
    revision:int
    issue_id:str
    side:int
    chapter_id:str
    mode:Literal['delete','merge','rewrite']
    replacement:str
    reason:str
    start:int
    end:int
    before_text:str
    after_text:str
    evidence:tuple[Evidence,...]
    guards:tuple[Dependency,...]
    impact:Impact
    created_at:str

@dataclass(frozen=True,kw_only=True)
class ModelLocalEdit(LocalEdit):
    model_proposal_id:str

@dataclass(frozen=True,kw_only=True)
class EditReceipt(Value):
    id:str
    project_id:str
    proposal_id:str
    proposal_revision:int
    decision:Literal['accepted','rejected','cancelled']
    authorize_confirmed:bool
    chapter_id:str
    version_before:str|None
    version_after:str|None
    saved_revision:int
    created_at:str

KNOWLEDGE_COLLECTIONS={'knowledge_nodes':Node,'knowledge_edges':Edge,'graph_merges':Merge,'graph_restores':Restore,'planning_proposals':Plan,'planning_locks':PlanLock,'planning_receipts':PlanReceipt,'local_edit_proposals':LocalEdit|ModelLocalEdit,'local_edit_receipts':EditReceipt}
PLAN_FIELDS={'book_outline':('theme','premise','main_plot','ending'),'chapter_outline':('core_idea','objective','story_time')}

def latest(items):return {v['id']:v for v in items}
def plan_target(state,kind,identifier,field):
    require(kind in PLAN_FIELDS and field in PLAN_FIELDS[kind],'规划只支持明确单个文本字段')
    items=[state['document']['book_outline']] if kind=='book_outline' else state['document']['chapter_outlines']
    value=next((v for v in items if v and v['id']==identifier),None);require(value is not None,'规划不属于当前书');return value
def locked(state,kind,identifier,field):
    events=[p for p in state.get('planning_locks',[]) if (p['target_kind'],p['target_id'],p['field'])==(kind,identifier,field)]
    return bool(events and events[-1]['locked'])

def validate_knowledge_state(state):
    project=state['document']['project']['id'];chapters={c['id'] for c in state['document']['chapters']};memories={m['id'] for m in state.get('memories',[])};versions={v['id']:v for v in state['document']['versions']}
    objects={}
    for name,model in KNOWLEDGE_COLLECTIONS.items():
        require(type(state[name]) is list and len(state[name])<=30000,'知识集合非法或超限')
        objects[name]=[parse(model,v) for v in state[name]]
        for item in objects[name]:require(item.project_id==project,'知识对象跨书')
        if name not in ('knowledge_nodes','knowledge_edges','local_edit_proposals'):require(len({v.id for v in objects[name]})==len(objects[name]),'知识对象ID重复')
    def source(s):
        require(s.project_id==project and 1<=s.workspace_revision<=state['revision'] and len(s.source_sha256)==64,'知识来源归属/版本非法')
        capture_source(state,dict(kind=s.kind,entity_id=s.entity_id))
        require(s.chapter_id is None or s.chapter_id in chapters,'知识来源章位非法')
        require(s.version_id is None or s.version_id in versions,'知识来源实体版本悬空')
    for name in ('knowledge_nodes','knowledge_edges','local_edit_proposals'):
        counts={};editids=set()
        for v in objects[name]:
            require(v.revision==counts.get(v.id,0)+1 and v.edit_id not in editids,'知识修订链断裂/操作身份重复');counts[v.id]=v.revision;editids.add(v.edit_id)
    nodes=latest(state['knowledge_nodes']);edges=latest(state['knowledge_edges']);plans={p.id:p for p in objects['planning_proposals']};edits=latest(state['local_edit_proposals']);issues={i['id']:i for i in state.get('review_issues',[])}
    for n in objects['knowledge_nodes']:
        source(n.source);require(n.position_chapter_id in chapters and bool(n.label.strip()) and len(n.label)<=300,'节点名称/位置非法')
        require(len(n.aliases)<=100 and len(set(n.aliases))==len(n.aliases) and all(0<len(a.strip())<=300 for a in n.aliases),'别名非法')
        require(len(set(n.memory_ids))==len(n.memory_ids) and set(n.memory_ids)<=memories,'节点记忆引用非法')
        require(n.basis==('plan' if n.source.kind in ('book_outline','chapter_outline','idea') else 'saved_source'),'计划不能声明为正文事实')
        require(n.merged_into is None or (n.merged_into in nodes and n.merged_into!=n.id and not n.active),'合并节点映射非法')
    for e in objects['knowledge_edges']:
        source(e.source);require(e.position_chapter_id in chapters and e.from_id in nodes and e.to_id in nodes and 0<len(e.relation.strip())<=300,'关系出处/端点非法')
    for e in edges.values():require(not e['active'] or (nodes[e['from_id']]['active'] and nodes[e['to_id']]['active']),'活跃关系引用已合并节点')
    merges={m.id:m for m in objects['graph_merges']}
    for m in merges.values():
        require(m.source_id in nodes and m.target_id in nodes and m.source_id!=m.target_id and {n.id for n in m.before_nodes}=={m.source_id,m.target_id},'合并记录引用非法')
        allids={v.edit_id for v in objects['knowledge_nodes']+objects['knowledge_edges']};require(set(m.after_edit_ids)<=allids,'合并后修订悬空')
        for n in m.before_nodes:require(encode(n) in state['knowledge_nodes'],'合并前节点快照不存在')
        for e in m.before_edges:require(encode(e) in state['knowledge_edges'],'合并前关系快照不存在')
    seen=set()
    for r in objects['graph_restores']:require(r.merge_id in merges and r.merge_id not in seen,'恢复合并不存在或重复');seen.add(r.merge_id)
    for p in objects['planning_proposals']:
        plan_target(state,p.target_kind,p.target_id,p.field);source(p.source);source(p.target)
        require(p.target.kind==p.target_kind and p.target.entity_id==p.target_id and p.source.kind in ('chapter','character','worldbuilding'),'规划反馈只接受已保存正文或明确结构来源')
        require(p.old_text!=p.new_text and bool(p.reason.strip()) and len(p.new_text)<=100000,'规划无变化/理由为空/超限')
    for p in objects['planning_locks']:plan_target(state,p.target_kind,p.target_id,p.field);require(bool(p.reason.strip()),'锁定/解锁需要理由')
    for p in objects['local_edit_proposals']:
        if type(p) is ModelLocalEdit:
            model=next((m for m in state.get('model_bridge_proposals',[]) if m['id']==p.model_proposal_id),None);require(state['workspace_version']>=6 and model is not None and p.issue_id==p.model_proposal_id,'模型局部提案来源悬空/格式不符');expected=model['draft']['evidence']
        else:
            require(p.issue_id in issues and issues[p.issue_id]['finding']['rule_id'] in ('duplicate_exact','duplicate_near'),'局部修改须引用实际查重问题');expected=issues[p.issue_id]['finding']['evidence']
        require(encode(p.evidence)==expected and len(p.evidence)==2 and p.side in (0,1),'局部修改双侧证据不符')
        ev=p.evidence[p.side];require(ev.source_kind=='chapter' and p.chapter_id==ev.chapter_id and p.chapter_id in chapters,'局部目标非法')
        require((p.start,p.end)==(ev.start,ev.end) and p.before_text[p.start:p.end]==ev.quote and p.end<=len(p.before_text),'局部范围不符原文')
        require(p.after_text==p.before_text[:p.start]+p.replacement+p.before_text[p.end:] and p.before_text!=p.after_text,'局部修改无变化或越界')
        require(p.mode!='delete' or p.replacement=='','删除不能携带替换文字');require(len(p.replacement)<=100000 and bool(p.reason.strip()),'局部修改超限/无理由')
        require(len(p.guards)==2 and {(g.kind,g.entity_id) for g in p.guards}=={(e.source_kind,e.entity_id) for e in p.evidence},'局部修改缺双侧来源guard')
    for name,targets in (('planning_receipts',plans),('local_edit_receipts',edits)):
        seen=set()
        for r in objects[name]:
            require(r.proposal_id in targets and r.proposal_id not in seen and 1<=r.saved_revision<=state['revision'],'提案收据归属/版本/重复非法');seen.add(r.proposal_id)
            if r.decision=='accepted':
                require(r.version_after in versions and r.version_before!=r.version_after,'接受收据缺新实体版本')
                v=versions[r.version_after];p=targets[r.proposal_id]
                if name=='planning_receipts':require(v['entity_type']==p.target_kind and v['entity_id']==p.target_id and v['snapshot'][p.field]==p.new_text,'规划收据实体/值不符')
                else:
                    matches=[p for p in objects['local_edit_proposals'] if p.id==r.proposal_id and p.revision==r.proposal_revision];require(len(matches)==1,'局部收据提案版本不存在');p=matches[0]
                    require(v['entity_type']=='chapter' and v['entity_id']==r.chapter_id==p.chapter_id and v['snapshot']['content']==p.after_text,'局部收据正文不符')
            else:require(r.version_after is None,'拒绝/取消不能写实体版本')
    return state

def validate_knowledge_transition(state,previous):
    """接受收据首次出现时，在真实前一保存状态上重核；备份/直接仓储也不能跳过。"""
    from novel_writer.domain.memory import outdated
    from novel_writer.domain.tasks import capture_dependency,dependency_equal
    from copy import deepcopy
    previous=previous or {}
    for name,proposals in (('planning_receipts','planning_proposals'),('local_edit_receipts','local_edit_proposals')):
        for receipt in state[name][len(previous.get(name,[])):]:
            p=latest(previous.get(proposals,[])).get(receipt['proposal_id']);require(p is not None,'决定须引用此前已保存提案')
            require(receipt['saved_revision']==state['revision'],'新收据保存编号不符')
            if name=='local_edit_receipts':require(receipt['proposal_revision']==p['revision'],'决定须引用当前提案修订')
            if receipt['decision']!='accepted':continue
            if name=='planning_receipts':
                require(not outdated(previous,p['source']) and not outdated(previous,p['target']),'规划收据来源/目标已过期')
                require(not locked(previous,p['target_kind'],p['target_id'],p['field']),'规划收据绕过字段锁')
                old=plan_target(previous,p['target_kind'],p['target_id'],p['field']);new=plan_target(state,p['target_kind'],p['target_id'],p['field']);expected=deepcopy(old);expected[p['field']]=p['new_text'];expected['updated_at']=new['updated_at'];require(new==expected and old[p['field']]==p['old_text'],'规划采纳越过明确单字段差异')
            else:
                for g in p['guards']:require(dependency_equal(parse(Dependency,g),capture_dependency(previous,g['kind'],g['entity_id'],use=g['use'])),'局部收据双侧来源过期')
                old=next(c for c in previous['document']['chapters'] if c['id']==p['chapter_id']);new=next(c for c in state['document']['chapters'] if c['id']==p['chapter_id']);require(old['status']!='confirmed' or receipt['authorize_confirmed'],'局部收据未取得正式章授权')
                expected=deepcopy(old);expected.update(content=p['after_text'],status='draft',updated_at=new['updated_at'],current_version_id=receipt['version_after']);require(old['content']==p['before_text'] and new==expected,'局部采纳越过明确正文差异')
            require(len(state['document']['versions'])==len(previous['document']['versions'])+1 and state['document']['versions'][-1]['id']==receipt['version_after'],'接受须只追加一个目标实体版本')
