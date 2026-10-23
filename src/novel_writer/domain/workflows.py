"""V8白名单工作流图、尝试/事件/审批。模板无运行输入或授权。"""
from __future__ import annotations
from novel_writer.domain.sampling import Sampling
from dataclasses import dataclass,replace
from typing import Literal
import re
from novel_writer.domain.tasks import check_types,parse,encode,require,uuid_value,SearchSelection
from novel_writer.domain.models import _timestamp
from novel_writer.domain.model_contract import ModelBinding,validate_model_options
from novel_writer.domain.workflow_contract import InputSnapshot,WorkflowAudit

class Value:
    def __post_init__(self):
        check_types(type(self),self)
        if hasattr(self,'id') and not isinstance(self,Node):uuid_value(self.id)
        if hasattr(self,'created_at'):_timestamp(self.created_at,'workflow.created_at')
        if isinstance(self,TaskParameters):require(128<=self.context_budget<=20000 and 128<=self.max_output_chars<=100000 and 100<=self.timeout_ms<=30000,'节点请求上限非法')
        elif isinstance(self,ReferenceParameters):require(1<=self.max_chars<=20000,'引用字符上限非法')
        elif isinstance(self,SearchParameters):require(1<=self.max_results<=20,'检索结果上限非法')
        elif isinstance(self,LoopParameters):require(1<=self.iterations<=3 and 0<len(self.nodes)<=20,'循环须有明确1至3次上限')
        elif isinstance(self,Limits):require(1<=self.concurrency<=3 and 0<=self.max_external_calls<=10 and 0<=self.max_reserved_output_tokens<=81920 and 1<=self.max_node_attempts<=256 and 0<=self.max_retries<=2 and 1<=self.max_iterations<=3,'运行次数/并行/token/重试/循环上限非法')
        elif isinstance(self,RoleBinding):
            from novel_writer.domain.tasks import digest
            options=encode(self);options.pop('role');validate_model_options(options)

@dataclass(frozen=True,kw_only=True)
class EmptyParameters(Value):pass
@dataclass(frozen=True,kw_only=True)
class ManualParameters(Value):slot:Literal['instruction','query','plan_text']
@dataclass(frozen=True,kw_only=True)
class ReferenceParameters(Value):max_chars:int
@dataclass(frozen=True,kw_only=True)
class SearchParameters(Value):max_results:int
@dataclass(frozen=True,kw_only=True)
class TaskParameters(Value):
    context_budget:int
    max_output_chars:int
    timeout_ms:int
@dataclass(frozen=True,kw_only=True)
class CandidateParameters(TaskParameters):
    count:int
    def __post_init__(self):
        super().__post_init__()
        require(1<=self.count<=3,'初稿候选数量必须为1至3')
@dataclass(frozen=True,kw_only=True)
class AuditParameters(TaskParameters):forbidden_literals:tuple[str,...]
@dataclass(frozen=True,kw_only=True)
class PlanParameters(Value):
    target_kind:Literal['book_outline','chapter_outline']
    field:Literal['theme','premise','main_plot','ending','core_idea','objective','story_time']
@dataclass(frozen=True,kw_only=True)
class ProposalParameters(Value):index:int
@dataclass(frozen=True,kw_only=True)
class ActionParameters(Value):action:Literal['body','memory','plan']
@dataclass(frozen=True,kw_only=True)
class BranchParameters(Value):expected:Literal['succeeded','failed','has_findings','no_findings','approved','rejected']
@dataclass(frozen=True,kw_only=True)
class LoopParameters(Value):
    iterations:int
    nodes:tuple[Node,...]
@dataclass(frozen=True,kw_only=True)
class Gate(Value):
    source:str
    equals:bool
@dataclass(frozen=True,kw_only=True)
class Node(Value):
    id:str
    kind:Literal['manual','reference','search','offline_audit','model_rewrite','model_audit','model_candidate_audit','model_idea','model_outline','model_draft','plan_proposal','memory_proposal','human','apply','branch','join','loop','outline_source','generate_candidates','audit','await_author','adopt','model_saved_draft','model_deep_audit']
    parents:tuple[str,...]
    source:str|None
    role:Literal['writer','auditor']|None
    parameters:EmptyParameters|ManualParameters|ReferenceParameters|SearchParameters|TaskParameters|AuditParameters|PlanParameters|ProposalParameters|ActionParameters|BranchParameters|LoopParameters|CandidateParameters
    when:Gate|None
@dataclass(frozen=True,kw_only=True)
class Template(Value):
    workflow_format:Literal[1]
    interface_version:Literal[1]
    name:str
    permissions:tuple[Literal['read_saved_source','search_local','offline_analysis','prepare_model_request','propose_changes','human_approval','apply_approved_change'],...]
    nodes:tuple[Node,...]
@dataclass(frozen=True,kw_only=True)
class TemplateVersion(Value):
    id:str
    project_id:str
    operation_id:str
    template_id:str
    revision:int
    previous_version_id:str|None
    template:Template
    created_at:str
@dataclass(frozen=True,kw_only=True)
class Inputs(Value):
    instruction:str
    query:str
    plan_text:str
@dataclass(frozen=True,kw_only=True)
class RoleBinding(Value):
    role:Literal['writer','auditor']
    adapter_id:Literal['chat-completions-http-v1','configured-http-v2']
    connection_id:str
    model_id:str
    temperature:float
    max_tokens:int
    budget_limit:float
    allow_unknown_cost:bool
    prompt_version:Literal['rewrite-1','review-json-1']
    sampling:Sampling|None=None

@dataclass(frozen=True,kw_only=True)
class Limits(Value):
    max_external_calls:int
    max_reserved_output_tokens:int
    max_node_attempts:int
    max_retries:int
    max_iterations:int
    concurrency:int
@dataclass(frozen=True,kw_only=True)
class Run(Value):
    id:str
    project_id:str
    operation_id:str
    template_version_id:str
    template:Template
    expanded_nodes:tuple[Node,...]
    chapter_id:str
    inputs:Inputs
    roles:tuple[RoleBinding,...]
    limits:Limits
    execution_mode:Literal['step','queue']
    network_mode:Literal['disabled','confirm_each']
    created_at:str
@dataclass(frozen=True,kw_only=True)
class RunEvent(Value):
    id:str
    run_id:str
    seq:int
    previous_event_id:str|None
    kind:Literal['created','started','paused','resumed','recovered','cancelled','manual','queued','completed','failed','waiting','retry']
    status:Literal['pending','running','paused','waiting','completed','cancelled','failed']
    owner_id:str|None
    epoch:str|None
    external_calls:int
    reserved_output_tokens:int
    network_mode:Literal['disabled','confirm_each']
    execution_mode:Literal['step','queue']
    created_at:str
@dataclass(frozen=True,kw_only=True)
class ArtifactRef(Value):
    kind:Literal['chapter','task','candidate','review_report','model_report','workflow_audit','memory_proposal','model_memory_proposal','workflow_memory_proposal','planning_proposal','approval','adoption_receipt','proposal_receipt','model_proposal_receipt','planning_receipt','workflow_receipt','node_attempt','manual_value','search','chapter_outline']
    entity_id:str
    version_id:str|None
    content_sha256:str|None
@dataclass(frozen=True,kw_only=True)
class NodeAttempt(Value):
    id:str
    project_id:str
    run_id:str
    node_id:str
    number:int
    input_attempt_ids:tuple[str,...]
    input_refs:tuple[ArtifactRef,...]
    task_id:str|None
    created_at:str
@dataclass(frozen=True,kw_only=True)
class NodeEvent(Value):
    id:str
    run_id:str
    attempt_id:str
    seq:int
    previous_event_id:str|None
    status:Literal['pending','running','waiting_request','waiting_human','succeeded','failed','skipped','cancelled','rejected']
    output_refs:tuple[ArtifactRef,...]
    snapshot:InputSnapshot|None
    flag:bool|None
    error_code:str|None
    approval_id:str|None
    search_hits:tuple[SearchHit,...]
    created_at:str

@dataclass(frozen=True,kw_only=True)
class SearchHit(Value):
    title:str
    snippet:str
    selection:SearchSelection
@dataclass(frozen=True,kw_only=True)
class Approval(Value):
    id:str
    project_id:str
    run_id:str
    node_attempt_id:str
    epoch:str
    kind:Literal['external','body','memory','plan']
    decision:Literal['accepted','rejected']
    input_ref:ArtifactRef
    content_sha256:str
    authorize_confirmed:bool
    confirm_inference:bool
    preserve_conflicts:bool
    created_at:str

@dataclass(frozen=True,kw_only=True)
class MemoryProposal(Value):
    id:str
    project_id:str
    run_id:str
    node_attempt_id:str
    source:InputSnapshot
    text:str
    created_at:str

@dataclass(frozen=True,kw_only=True)
class ApplyReceipt(Value):
    id:str
    project_id:str
    run_id:str
    node_attempt_id:str
    approval_id:str
    action:Literal['body','plan','memory']
    business_kind:Literal['adoption_receipt','planning_receipt','model_proposal_receipt','workflow_memory']
    business_id:str
    memory_id:str|None
    memory_version_id:str|None
    created_at:str

WORKFLOW_COLLECTIONS={'workflow_templates':TemplateVersion,'workflow_runs':Run,'workflow_run_events':RunEvent,'workflow_attempts':NodeAttempt,'workflow_node_events':NodeEvent,'workflow_approvals':Approval,'workflow_audits':WorkflowAudit,'workflow_memory_proposals':MemoryProposal,'workflow_receipts':ApplyReceipt}
PARAMETERS={'manual':ManualParameters,'reference':ReferenceParameters,'search':SearchParameters,'offline_audit':AuditParameters,'model_rewrite':TaskParameters,'model_audit':TaskParameters,'model_candidate_audit':TaskParameters,'plan_proposal':PlanParameters,'memory_proposal':ProposalParameters,'human':ActionParameters,'apply':ActionParameters,'branch':BranchParameters,'join':EmptyParameters,'loop':LoopParameters}
PERMISSIONS={'manual':'read_saved_source','reference':'read_saved_source','search':'search_local','offline_audit':'offline_analysis','model_rewrite':'prepare_model_request','model_audit':'prepare_model_request','model_candidate_audit':'prepare_model_request','plan_proposal':'propose_changes','memory_proposal':'propose_changes','human':'human_approval','apply':'apply_approved_change'}
for _kind in ('model_idea','model_outline','model_draft'):
    PARAMETERS[_kind]=TaskParameters
    PERMISSIONS[_kind]='prepare_model_request'

PARAMETERS.update(outline_source=EmptyParameters,generate_candidates=CandidateParameters,audit=TaskParameters,
                  await_author=ActionParameters,adopt=ActionParameters,model_saved_draft=TaskParameters,model_deep_audit=TaskParameters)
PERMISSIONS.update(outline_source='read_saved_source',generate_candidates='prepare_model_request',audit='prepare_model_request',
                   await_author='human_approval',adopt='apply_approved_change',model_saved_draft='prepare_model_request',model_deep_audit='prepare_model_request')

def sorted_nodes(nodes,depth=0):
    require(depth<=1 and 0<len(nodes)<=64,'图大小/嵌套循环超限');byid={n.id:n for n in nodes};require(len(byid)==len(nodes),'节点ID重复');done=[];visiting=set()
    def visit(n):
        if n.id in done:return
        require(n.id not in visiting,'工作流含未声明循环');visiting.add(n.id)
        require(re.fullmatch(r'[A-Za-z0-9_.@-]{1,100}',n.id) is not None and len(n.parents)==len(set(n.parents)) and set(n.parents)<=set(byid),'节点ID/父节点非法')
        require(n.source is None or n.source in n.parents,'上游source必须是声明的父节点');require(type(n.parameters) is PARAMETERS[n.kind],'节点参数契约与能力不符')
        if n.kind.startswith('model_') or n.kind in ('generate_candidates','audit'):require(n.role==('auditor' if n.kind in ('model_audit','model_candidate_audit','model_deep_audit','audit') else 'writer'),'模型角色与能力不符')
        else:require(n.role is None,'非模型节点不能绑定连接角色')
        if n.when:require(n.when.source in n.parents and byid[n.when.source].kind=='branch','跳过条件仅能引用声明分支')
        if n.kind=='loop':sorted_nodes(n.parameters.nodes,depth+1)
        if n.kind in ('human','apply','branch','memory_proposal','model_candidate_audit','model_idea','model_outline','model_draft'):require(n.source is not None,'该节点必须显式声明上游')
        if n.kind=='apply':require(byid[n.source].kind=='human' and byid[n.source].parameters.action==n.parameters.action,'写入前必须有同类型人工确认节点')
        if n.kind in ('generate_candidates','audit','await_author','adopt','model_saved_draft','model_deep_audit'):require(n.source is not None,'创作节点必须显式声明上游')
        if n.kind=='generate_candidates':require(byid[n.source].kind=='outline_source','初稿候选须读取保存章纲')
        if n.kind=='audit':require(byid[n.source].kind=='generate_candidates','审核须接初稿候选组')
        if n.kind=='await_author':require(byid[n.source].kind=='audit' and n.parameters.action=='body','选稿须接审核且仅用于正文')
        if n.kind=='adopt':require(byid[n.source].kind=='await_author' and n.parameters.action=='body','采纳须经过作者选稿')
        for p in n.parents:visit(byid[p])
        visiting.remove(n.id);done.append(n.id)
    for n in nodes:visit(n)
    return tuple(byid[i] for i in done)

def validate_template(template):
    require(0<len(template.name.strip())<=100,'工作流模板名称非法');needed={'read_saved_source'}
    def collect(nodes):
        for n in sorted_nodes(nodes):
            if n.kind in PERMISSIONS:needed.add(PERMISSIONS[n.kind])
            if n.kind=='loop':collect(n.parameters.nodes)
    collect(template.nodes);require(set(template.permissions)==needed and len(template.permissions)==len(needed),'模板权限不匹配或未注册');return template

def expand(template,limit):
    """Compile creative groups to the existing bounded task/approval graph."""
    groups={};compiled=[]
    for n in sorted_nodes(template.nodes):
        if n.kind in ('generate_candidates','audit'):
            sources=(n.source,) if n.kind=='generate_candidates' else groups[n.source]
            count=n.parameters.count if n.kind=='generate_candidates' else len(sources)
            ids=tuple(n.id+'.candidate'+str(i+1) for i in range(count))
            require(not set(ids)&{v.id for v in template.nodes},'展开候选节点ID冲突')
            p=TaskParameters(context_budget=n.parameters.context_budget,max_output_chars=n.parameters.max_output_chars,timeout_ms=n.parameters.timeout_ms)
            for i,identifier in enumerate(ids):
                source=n.source if n.kind=='generate_candidates' else sources[i]
                parents=tuple(dict.fromkeys((*n.parents,source)))
                compiled.append(replace(n,id=identifier,kind='model_saved_draft' if n.kind=='generate_candidates' else 'model_deep_audit',parents=parents,source=source,parameters=p))
            compiled.append(Node(id=n.id,kind='join',parents=ids,source=ids[0],role=None,parameters=EmptyParameters(),when=None))
            groups[n.id]=ids
        elif n.kind=='await_author':
            parents=tuple(dict.fromkeys((*n.parents,*groups[n.source])))
            compiled.append(replace(n,kind='human',parents=parents,source=groups[n.source][0]))
        elif n.kind=='adopt':compiled.append(replace(n,kind='apply'))
        else:compiled.append(n)
    return _expand_nodes(compiled,limit)

def _expand_nodes(nodes,limit):
    result=[]
    for n in sorted_nodes(nodes):
        if n.kind!='loop':result.append(n);continue
        require(n.parameters.iterations<=limit,'循环超过本次运行声明上限');start=n.id+'.start';result.append(Node(id=start,kind='join',parents=n.parents,source=n.source,role=None,parameters=EmptyParameters(),when=n.when));previous=start;body=sorted_nodes(n.parameters.nodes)
        for i in range(n.parameters.iterations):
            mapping={c.id:n.id+'.'+str(i+1)+'.'+c.id for c in body};parents={p for c in body for p in c.parents};leaves=[c.id for c in body if c.id not in parents]
            for c in body:
                gate=Gate(source=mapping[c.when.source],equals=c.when.equals) if c.when else None;result.append(replace(c,id=mapping[c.id],parents=tuple(mapping[p] for p in c.parents) or (previous,),source=mapping[c.source] if c.source else None,when=gate))
            previous=n.id+'.'+str(i+1)+'.end';leafids=tuple(mapping[p] for p in leaves);result.append(Node(id=previous,kind='join',parents=leafids,source=leafids[0] if len(leafids)==1 else None,role=None,parameters=EmptyParameters(),when=None))
        result.append(Node(id=n.id,kind='join',parents=(previous,),source=previous,role=None,parameters=EmptyParameters(),when=None))
    require(len(result)<=128,'展开执行图超限');return tuple(result)

def validate_snapshot(state,snapshot):
    from novel_writer.domain.tasks import digest
    from novel_writer.domain.memory import fingerprint
    s=parse(InputSnapshot,snapshot) if type(snapshot) is dict else snapshot;t=s.saved_target;project=state['document']['project']['id'];require(s.project_id==project and t.chapter_id in {c['id'] for c in state['document']['chapters']},'节点原文跨书/目标非法');require(t.source_sha256==fingerprint(dict(number=t.number,title=t.title,content=t.text,status=t.status)),'正式保存目标摘要不符')
    attempts={a['id']:a for a in state['workflow_attempts']};require(s.via_node_attempt_id in attempts,'声明上游尝试悬空')
    if s.kind=='chapter_outline':
        from novel_writer.domain.creative_workflow import require_outline_source
        require_outline_source(state,s,fresh=False)
    if s.kind=='candidate':
        c=next((c for c in state['generation_candidates'] if c['id']==s.entity_id),None);require(c is not None and (c['task_id'],c['attempt_id'])==(s.producer_task_id,s.producer_attempt_id),'候选原文生产者归属不符');require(c['output_text'][s.start:s.end]==s.text and s.end<=len(c['output_text']),'节点未消费候选原文范围');require(s.producer_node_attempt_id in attempts and attempts[s.producer_node_attempt_id]['task_id']==s.producer_task_id,'候选节点生产者不符');producer=next(t for t in state['generation_tasks'] if t['id']==s.producer_task_id);require(producer['frozen']['target']==encode(s.saved_target),'候选链不得重置正式保存目标守卫')
    elif t.version_id is not None:
        v=next((v for v in state['document']['versions'] if v['id']==t.version_id),None);require(v is not None and v['entity_type']=='chapter' and v['entity_id']==t.chapter_id,'保存引用版本悬空');value=v['snapshot'];require((value['content'],value['title'],value['number'],value['status'])==(t.text,t.title,t.number,t.status),'保存原文目标快照与版本不符')
    if s.review_id is not None:
        from novel_writer.domain.workflow_contract import CandidateAuditOutput,CandidateModelOutput,feedback_text
        audit=next((r for r in state['workflow_audits'] if r['id']==s.review_id),None);require(audit is not None and audit['node_attempt_id']==s.via_node_attempt_id,'审核资料与选定上游不符');require(s.feedback==feedback_text(parse(CandidateAuditOutput|CandidateModelOutput,audit['output'])) and (audit['upstream']['entity_id'],audit['upstream']['text'])==(s.entity_id,s.text),'后继审核反馈/原文不是上游实际结果')
    if s.search_node_attempt_id is not None:
        rows=[e for e in state['workflow_node_events'] if e['attempt_id']==s.search_node_attempt_id and e['status']=='succeeded'];require(rows and s.via_node_attempt_id==s.search_node_attempt_id,'检索资料生产者不符');require(s.feedback==search_feedback(tuple(parse(SearchHit,h) for h in rows[-1]['search_hits'])),'后继未消费上游实际检索结果')
    return s

def search_feedback(hits):return '\n'.join(h.title+'：'+h.snippet for h in hits)

def validate_workflow_state(state):
    from novel_writer.domain.tasks import digest
    from novel_writer.domain.workflow_contract import CandidateAuditParameters,WorkflowModelParameters,CandidateModelParameters,validate_candidate_audit
    project=state['document']['project']['id'];parsed={}
    for name,model in WORKFLOW_COLLECTIONS.items():
        require(type(state[name]) is list and len(state[name])<=100000,'工作流集合非法/超限');parsed[name]=[parse(model,v) for v in state[name]];require(len({v.id for v in parsed[name]})==len(parsed[name]),'工作流集合身份重复')
        for v in parsed[name]:
            uuid_value(v.id)
            if hasattr(v,'project_id'):require(v.project_id==project,'工作流对象跨书')
    versions={v.id:v for v in parsed['workflow_templates']};runs={r.id:r for r in parsed['workflow_runs']};attempts={a.id:a for a in parsed['workflow_attempts']};approvals={a.id:a for a in parsed['workflow_approvals']};tasks={t['id']:t for t in state['generation_tasks']};current={};counts={};operations=set()
    for v in versions.values():
        uuid_value(v.operation_id);uuid_value(v.template_id);require(v.operation_id not in operations and v.revision==counts.get(v.template_id,0)+1 and v.previous_version_id==current.get(v.template_id),'工作流模板版本链/操作重复');validate_template(v.template);counts[v.template_id]=v.revision;current[v.template_id]=v.id;operations.add(v.operation_id)
    for run in runs.values():
        if run.limits.concurrency>1:
            from novel_writer.domain.workflow_stages import validate_parallel_targets
            require(state['workspace_version']>=40,'并行工作流需要V40')
            validate_parallel_targets(run.expanded_nodes)
        if any(role.adapter_id=='configured-http-v2' for role in run.roles):require(state['workspace_version']>=9,'配置协议角色须使用V9或更新工作区')
        require(run.template_version_id in versions and run.template==versions[run.template_version_id].template,'运行模板冻结不符');require(run.expanded_nodes==expand(run.template,run.limits.max_iterations),'运行图不是声明的有界展开');require(run.chapter_id in {c['id'] for c in state['document']['chapters']},'运行目标跨书')
        events=[e for e in parsed['workflow_run_events'] if e.run_id==run.id];require(bool(events),'运行无创建事件');previous=None
        for i,e in enumerate(events):
            require(e.seq==i+1 and e.previous_event_id==(previous.id if previous else None),'运行事件链断裂');require(e.external_calls<=run.limits.max_external_calls and e.reserved_output_tokens<=run.limits.max_reserved_output_tokens,'运行预算越界')
            if previous:require(e.external_calls>=previous.external_calls and e.reserved_output_tokens>=previous.reserved_output_tokens,'取消/失败不能退款式释放额度')
            else:require(e.kind=='created' and e.status=='pending' and e.external_calls==e.reserved_output_tokens==0,'运行初始事件非法')
            previous=e
        require(sum(a.run_id==run.id for a in attempts.values())<=run.limits.max_node_attempts,'运行尝试数越界')
    require(all(e.run_id in runs for e in parsed['workflow_run_events']),'运行事件悬空');counts={};node_latest={}
    for a in attempts.values():
        require(a.run_id in runs,'节点运行悬空');run=runs[a.run_id];node=next((n for n in run.expanded_nodes if n.id==a.node_id),None);require(node is not None,'节点不在冻结图');key=(a.run_id,a.node_id);require(a.number==counts.get(key,0)+1,'节点尝试序号断裂');counts[key]=a.number
        require(len(a.input_attempt_ids)==len(node.parents) and all(p in attempts for p in a.input_attempt_ids),'父尝试悬空');require(tuple(attempts[p].node_id for p in a.input_attempt_ids)==node.parents and all(attempts[p].run_id==a.run_id for p in a.input_attempt_ids),'节点未消费声明父尝试');require(tuple(r.entity_id for r in a.input_refs)==a.input_attempt_ids and all(r.kind=='node_attempt' for r in a.input_refs),'父输入引用不符')
        if a.task_id:require(a.task_id in tasks,'共享任务引用悬空')
        events=[e for e in parsed['workflow_node_events'] if e.attempt_id==a.id];require(bool(events),'节点无事件');previous=None
        for i,e in enumerate(events):
            require(e.run_id==a.run_id and e.seq==i+1 and e.previous_event_id==(previous.id if previous else None),'节点事件链断裂')
            if previous:require(previous.status not in ('succeeded','failed','skipped','cancelled','rejected'),'旧节点终态不可覆盖')
            if e.snapshot:validate_snapshot(state,e.snapshot)
            if node.kind=='human' and any(n.id==node.id and n.kind=='await_author' for n in run.template.nodes) and e.snapshot:
                require(e.snapshot.kind=='candidate' and any(
                    pe['attempt_id'] in a.input_attempt_ids and pe['status']=='succeeded' and pe['snapshot'] is not None
                    and pe['snapshot']==encode(e.snapshot) for pe in state['workflow_node_events']),
                    '作者选稿不是本次审核组的真实候选')
            if e.approval_id:require(e.approval_id in approvals and approvals[e.approval_id].node_attempt_id==a.id,'节点审批归属不符')
            previous=e
        node_latest[a.id]=events[-1]
        if a.task_id:
            task=tasks[a.task_id];p=task['frozen']['parameters']
            if node.kind=='model_deep_audit':
                scope=p.get('deep_review');snap=events[0].snapshot
                require(scope is not None and snap is not None and snap.kind=='candidate','创作审核缺少深层范围/候选快照')
                require(encode(snap.saved_target)==task['frozen']['target'] and snap.via_node_attempt_id in a.input_attempt_ids,'创作审核保存目标/上游不符')
                require([s['entity_id'] for s in scope['sources'] if s['kind']=='candidate']==[snap.entity_id],'创作审核未消费声明的单个候选')
                require({'character_consistency','rule_conflict','relative_time'}<=set(scope['checks']),'创作审核缺少人物/时间/规则检查')
            if 'upstream' in p:
                s=validate_snapshot(state,p['upstream']);require(encode(s.saved_target)==task['frozen']['target'],'节点任务丢失正式保存守卫');require(s.via_node_attempt_id in a.input_attempt_ids or (node.source is None and s.via_node_attempt_id==a.id),'任务未消费所选父结果')
            from novel_writer.domain.workflow_stages import PROMPTS,require_stage_source,typed_result
            if node.kind in PROMPTS:
                require(state['workspace_version']>=40 and p['binding']['prompt_version']==PROMPTS[node.kind],'专用章节节点提示词/格式不符')
                if node.kind=='model_saved_draft':
                    from novel_writer.domain.creative_workflow import require_outline_source
                    require_outline_source(state,parse(InputSnapshot,p['upstream']),fresh=False)
                else:require_stage_source(state,node.kind,parse(InputSnapshot,p['upstream']))
                if task['status']=='succeeded' and node.kind in ('model_idea','model_outline'):
                    from novel_writer.domain.tasks import GenerationTask
                    candidate=next(c for c in state['generation_candidates'] if c['id']==task['candidate_id'])
                    typed_result(parse(GenerationTask,task).frozen,candidate['output_text'])
    require(all(e.attempt_id in attempts for e in parsed['workflow_node_events']),'节点事件悬空')
    for p in approvals.values():require(p.run_id in runs and p.node_attempt_id in attempts and attempts[p.node_attempt_id].run_id==p.run_id and p.epoch is not None,'审批归属/会话非法')
    for audit in parsed['workflow_audits']:
        require(audit.node_attempt_id in attempts and attempts[audit.node_attempt_id].task_id==audit.task_id and audit.task_id in tasks,'候选审核生产者不符');task=tasks[audit.task_id];parameters=parse(CandidateAuditParameters|CandidateModelParameters,task['frozen']['parameters']);require(audit.upstream==parameters.upstream,'候选审核未消费实际冻结原文');validate_candidate_audit(audit.output,parameters)
        if isinstance(parameters,CandidateModelParameters):
            require(state['workspace_version']>=35 and audit.response_record_id is not None,'候选模型审核需要V35和真实响应')
            response=next((r for r in state['model_results'] if r['id']==audit.response_record_id),None)
            require(response is not None and response['task_id']==audit.task_id and response['attempt_id']==task['attempt_id'] and response['response']['complete'],'候选审核真实响应归属不符')
            from novel_writer.domain.candidate_reviews import verify
            require(audit.output==verify(response['response']['output_text'],parameters),'候选模型审核不是实际返回')
        else:require(audit.response_record_id is None,'离线审核不能冒用模型响应')
    for p in parsed['workflow_memory_proposals']:
        require(p.run_id in runs and p.node_attempt_id in attempts and p.source.kind=='chapter' and p.text==p.source.text[:4000],'未采纳候选/伪造文本不得转成事实记忆');validate_snapshot(state,p.source)
    receipt_ids=set();edits={h['id']:h for h in state['memory_history']}
    for r in parsed['workflow_receipts']:
        require(r.run_id in runs and r.node_attempt_id in attempts and r.approval_id in approvals and r.approval_id not in receipt_ids,'写入审批悬空/重复消费');receipt_ids.add(r.approval_id);p=approvals[r.approval_id];require(p.decision=='accepted' and p.kind==r.action and p.run_id==r.run_id,'正式写入未绑定明确人工决定');require(node_latest[r.node_attempt_id].status=='succeeded','收据与节点完成状态不符')
        if r.business_kind=='adoption_receipt':require(any(x['id']==r.business_id and x['candidate_id']==p.input_ref.entity_id for x in state['adoption_receipts']),'正文写入未走原原子采纳')
        elif r.business_kind=='planning_receipt':require(any(x['id']==r.business_id and x['proposal_id']==p.input_ref.entity_id for x in state['planning_receipts']),'规划写入未走原提案事务')
        elif r.business_kind=='model_proposal_receipt':require(any(x['id']==r.business_id and x['proposal_id']==p.input_ref.entity_id for x in state['model_proposal_receipts']),'模型记忆未走原提案事务')
        else:
            require(r.memory_version_id in edits and edits[r.memory_version_id]['memory_id']==r.memory_id,'工作流记忆缺同事务历史');proposal=next(x for x in state['workflow_memory_proposals'] if x['id']==p.input_ref.entity_id);require(edits[r.memory_version_id]['snapshot']['text']==proposal['text'] and edits[r.memory_version_id]['snapshot']['confirmed'] and p.confirm_inference,'工作流记忆未明确确认原文提案')

def validate_workflow_transition(state,previous):
    previous=previous or {}
    for name in WORKFLOW_COLLECTIONS:require(state[name][:len(previous.get(name,[]))]==previous.get(name,[]),'工作流定义/事件/结果/审批历史不可改写')
    old_approvals={a['id']:a for a in previous.get('workflow_approvals',[])}
    for receipt in state['workflow_receipts'][len(previous.get('workflow_receipts',[])):]:
        require(receipt['approval_id'] in old_approvals,'正式写入必须引用此前保存的人工决定');p=old_approvals[receipt['approval_id']];events=[e for e in previous['workflow_run_events'] if e['run_id']==receipt['run_id']];require(events and events[-1]['status'] in ('running','waiting') and events[-1]['epoch']==p['epoch'],'恢复/复制/暂停或旧会话许可不能推动新写入')
