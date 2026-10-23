"""持久白名单执行图。共享任务负责生成，人工节点负责本次许可。"""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4,uuid5,NAMESPACE_URL
import json,threading,time
from novel_writer.domain.workflows import *
from novel_writer.domain.workflow_contract import *
from novel_writer.domain.tasks import Target,GenerationTask,CandidateAuditParameters,WorkflowModelParameters,capture_dependency,dependency_equal,digest
from novel_writer.domain.memory import fingerprint
from novel_writer.domain.models import utc_now
from novel_writer.application.fields import check_fields
from novel_writer.application.tasks import get_task,put_task,event as task_event
from novel_writer.domain.model_contract import request_body,request_digest
from novel_writer.application.model_reviews import canonical_options
from novel_writer.domain.workflow_stages import PROMPTS as STAGE_PROMPTS,PLAN_PROMPTS,typed_result,require_stage_source

def append(state,name,value):state[name].append(encode(value));return value
def find_run(state,identifier):
    value=next((r for r in state.get('workflow_runs',[]) if r['id']==identifier),None)
    if value is None:raise KeyError(identifier)
    return parse(Run,value)
def run_events(state,run_id):return [e for e in state.get('workflow_run_events',[]) if e['run_id']==run_id]
def run_state(state,run_id):return run_events(state,run_id)[-1]
def attempts(state,run_id):return [a for a in state.get('workflow_attempts',[]) if a['run_id']==run_id]
def node_events(state,attempt_id):return [e for e in state.get('workflow_node_events',[]) if e['attempt_id']==attempt_id]
def node_state(state,attempt_id):return node_events(state,attempt_id)[-1]
def latest(state,run_id):return {a['node_id']:a for a in attempts(state,run_id)}
def emit_run(state,run,kind,status=None,**changes):
    old=run_events(state,run.id);prev=old[-1] if old else None;values=dict(owner_id=None,epoch=None,external_calls=0,reserved_output_tokens=0,network_mode=run.network_mode,execution_mode=run.execution_mode)
    if prev:values.update({k:prev[k] for k in values})
    values.update(changes);return append(state,'workflow_run_events',RunEvent(id=str(uuid4()),run_id=run.id,seq=len(old)+1,previous_event_id=prev['id'] if prev else None,kind=kind,status=status or (prev['status'] if prev else 'pending'),created_at=utc_now(),**values))
def emit_node(state,attempt,status,**changes):
    old=node_events(state,attempt.id);prev=old[-1] if old else None;values=dict(output_refs=(),snapshot=None,flag=None,error_code=None,approval_id=None,search_hits=())
    if prev:
        values.update(output_refs=tuple(parse(ArtifactRef,r) for r in prev['output_refs']),snapshot=parse(InputSnapshot,prev['snapshot']) if prev['snapshot'] else None,flag=prev['flag'],error_code=prev['error_code'],approval_id=prev['approval_id'],search_hits=tuple(parse(SearchHit,h) for h in prev['search_hits']))
    values.update(changes);return append(state,'workflow_node_events',NodeEvent(id=str(uuid4()),run_id=attempt.run_id,attempt_id=attempt.id,seq=len(old)+1,previous_event_id=prev['id'] if prev else None,status=status,created_at=utc_now(),**values))
def ref(kind,identifier,version=None,sha=None):return ArtifactRef(kind=kind,entity_id=identifier,version_id=version,content_sha256=sha)
def target(state,chapter_id):
    c=next((c for c in state['document']['chapters'] if c['id']==chapter_id),None);require(c is not None,'目标章节不属于当前书');return SavedTarget(chapter_id=c['id'],version_id=c['current_version_id'],title=c['title'],text=c['content'],status=c['status'],number=c['number'],source_sha256=fingerprint(c))
def require_target(state,saved):require(encode(target(state,saved.chapter_id))==encode(saved),'正式目标已变化，请明确重新读取/重跑，不能沿旧候选覆盖')
def saved_snapshot(state,chapter_id,via,max_chars=20000):
    t=target(state,chapter_id);text=t.text[:max_chars];return InputSnapshot(kind='chapter',project_id=state['document']['project']['id'],chapter_id=chapter_id,entity_id=chapter_id,version_id=t.version_id,producer_task_id=None,producer_attempt_id=None,producer_node_attempt_id=None,via_node_attempt_id=via,review_id=None,search_node_attempt_id=None,title=t.title,text=text,start=0,end=len(text),text_sha256=digest(text),feedback='',saved_target=t)
def snapshot_for(state,run,node,parent_map,via):
    if node.source is None:return saved_snapshot(state,run.chapter_id,via)
    a=parent_map[node.source];e=node_state(state,a['id']);require(e['snapshot'] is not None,'声明上游没有可消费原文；合流需明确选择source，不接受任意output');s=parse(InputSnapshot,e['snapshot']);return replace(s,via_node_attempt_id=a['id'])
def candidate_snapshot(task,candidate,node_attempt_id):
    return InputSnapshot(kind='candidate',project_id=task.project_id,chapter_id=task.chapter_id,entity_id=candidate['id'],version_id=None,producer_task_id=task.id,producer_attempt_id=task.attempt_id,producer_node_attempt_id=node_attempt_id,via_node_attempt_id=node_attempt_id,review_id=None,search_node_attempt_id=None,title=task.frozen.target.title,text=candidate['output_text'],start=0,end=len(candidate['output_text']),text_sha256=digest(candidate['output_text']),feedback='',saved_target=parse(SavedTarget,encode(task.frozen.target)))

class CandidateRuleAdapter:
    adapter_id='candidate-offline-audit-v1';capabilities=('audit_chapter',)
    def run(self,call,token):
        from novel_writer.application.task_protocol import AdapterResult
        p=call.input.parameters;require(type(p) is CandidateAuditParameters,'候选规则只接受正式原文快照');s=p.upstream;found=[]
        for literal in p.forbidden_literals:
            cursor=0
            while len(found)<80:
                token.checkpoint();start=s.text.find(literal,cursor)
                if start<0:break
                e=CandidateEvidence(source_kind=s.kind,entity_id=s.entity_id,task_id=s.producer_task_id,attempt_id=s.producer_attempt_id,producer_node_attempt_id=s.producer_node_attempt_id,version_id=s.version_id,start=start,end=start+len(literal),quote=literal,quote_sha256=digest(literal));found.append(CandidateFinding(rule='forbidden_literal',message='上游原文命中字面规则：'+literal,evidence=(e,)));cursor=start+len(literal)
        output=CandidateAuditOutput(findings=tuple(found),method='offline_candidate_literal_rules_v1');validate_candidate_audit(output,p);return AdapterResult(task_id=call.task_id,attempt_id=call.attempt_id,capability=call.capability,output_text='离线候选字面规则完成，共'+str(len(found))+'项，不是语义审核。',complete=True,candidate_audit_output=output)

def persist_audit(state,task,output,now,response_record_id=None):
    a=next(a for a in state['workflow_attempts'] if a['task_id']==task.id);validate_candidate_audit(output,task.frozen.parameters);return append(state,'workflow_audits',WorkflowAudit(id=str(uuid5(NAMESPACE_URL,task.id+'/workflow-audit')),project_id=task.project_id,task_id=task.id,node_attempt_id=a['id'],upstream=task.frozen.parameters.upstream,output=output,created_at=now,response_record_id=response_record_id))

def upgrade(state):
    from novel_writer.application.extensions import upgrade as previous_upgrade
    previous_upgrade(state);state['workspace_version']=max(state['workspace_version'],8)
    for name in WORKFLOW_COLLECTIONS:state.setdefault(name,[])

class WorkflowCoordinator:
    def __init__(self,service,tasks):
        self.service,self.tasks,self.repository=service,tasks,service.repository;self.owner_id=str(uuid4());self.leases={};self.closed=threading.Event();self.lock=threading.Lock();self.workers={};self.queue_wake=set()
        if not tasks.registry.supports('audit_chapter','candidate-offline-audit-v1'):tasks.registry.register('audit_chapter',CandidateRuleAdapter())
    def preflight(self,raw):
        spec=validate_template(parse(Template,raw));expand(spec,3);return dict(compatible=True,template=encode(spec),code_loaded=False,requires_runtime_inputs=True)
    def import_template(self,project_id,request):
        check_fields(request,{'operation_id','template_id','template','expected_revision'});identity=uuid_value(request.get('operation_id'));spec=parse(Template,self.preflight(request.get('template'))['template'])
        def apply(state):
            old=next((v for v in state.get('workflow_templates',[]) if v['operation_id']==identity),None)
            if old:require(old['template']==encode(spec),'同一模板身份绑定不同内容');return None,dict(template_id=old['template_id'],version_id=old['id'],revision=old['revision'])
            require(type(request.get('expected_revision')) is int and request['expected_revision']==state['revision'],'模板保存编号变化');upgrade(state);family=request.get('template_id');previous=None
            if family is not None:uuid_value(family);previous=next((v for v in reversed(state['workflow_templates']) if v['template_id']==family),None);require(previous is not None,'模板不属于当前书')
            else:family=str(uuid4())
            v=TemplateVersion(id=str(uuid4()),project_id=project_id,operation_id=identity,template_id=family,revision=previous['revision']+1 if previous else 1,previous_version_id=previous['id'] if previous else None,template=spec,created_at=utc_now());append(state,'workflow_templates',v);return state,dict(template_id=family,version_id=v.id,revision=v.revision)
        return self.repository.atomic(project_id,apply,identity_claim=('workflow_templates','operation_id',identity))
    def export_template(self,project_id,version_id):
        state=self.service.get(project_id);v=next((v for v in state.get('workflow_templates',[]) if v['id']==version_id),None)
        if v is None:raise KeyError(version_id)
        return deepcopy(v['template'])
    def create(self,project_id,request):
        fields={'operation_id','template_version_id','chapter_id','inputs','roles','limits','execution_mode','network_mode','expected_revision'};check_fields(request,fields);require(set(request)==fields,'工作流运行字段缺失');identity=uuid_value(request['operation_id']);inputs=parse(Inputs,request['inputs']);limits=parse(Limits,request['limits'])
        roles=[]
        for raw in request['roles']:
            require(type(raw) is dict and 'role' in raw,'模型角色字段缺失');options={k:v for k,v in raw.items() if k!='role'};roles.append(parse(RoleBinding,dict(canonical_options(options),role=raw['role'])))
        roles=tuple(roles);require(len({r.role for r in roles})==len(roles),'运行角色重复');require(len(inputs.instruction)<=2000 and len(inputs.query)<=200 and len(inputs.plan_text)<=100000,'运行输入超限')
        def apply(state):
            old=next((r for r in state.get('workflow_runs',[]) if r['operation_id']==identity),None)
            if old:require((old['template_version_id'],old['chapter_id'],old['inputs'],old['roles'],old['limits'])==(request['template_version_id'],request['chapter_id'],encode(inputs),[encode(r) for r in roles],encode(limits)),'运行身份绑定其它输入');return None,dict(run_id=old['id'],revision=state['revision'])
            require(type(request['expected_revision']) is int and request['expected_revision']==state['revision'],'运行保存编号变化');upgrade(state)
            if any(role.adapter_id=='configured-http-v2' for role in roles):state['workspace_version']=max(state['workspace_version'],9)
            v=next((v for v in state['workflow_templates'] if v['id']==request['template_version_id']),None);require(v is not None,'模板版本不属于当前书');spec=validate_template(parse(Template,v['template']));nodes=expand(spec,limits.max_iterations);require(len(nodes)<=limits.max_node_attempts,'展开节点已超过运行尝试上限');target(state,request['chapter_id']);require({n.role for n in nodes if n.role}<=set(r.role for r in roles),'运行缺少模型角色')
            if any(n.kind in ('model_draft','model_saved_draft') for n in nodes):require(target(state,request['chapter_id']).text=='','专用初稿链只支持空正文目标；已有正文请用改写链，未创建运行或发起请求')
            if limits.concurrency>1:
                from novel_writer.domain.workflow_stages import validate_parallel_targets
                validate_parallel_targets(nodes)
            run=Run(id=str(uuid4()),project_id=project_id,operation_id=identity,template_version_id=v['id'],template=spec,expanded_nodes=nodes,chapter_id=request['chapter_id'],inputs=inputs,roles=roles,limits=limits,execution_mode=request['execution_mode'],network_mode=request['network_mode'],created_at=utc_now());append(state,'workflow_runs',run);emit_run(state,run,'created','pending');return state,dict(run_id=run.id,revision=state['revision']+1)
        return self.repository.atomic(project_id,apply,identity_claim=('workflow_runs','operation_id',identity))
    def _allowed(self,state,run):
        current=run_state(state,run.id);require(not self.closed.is_set() and current['status'] in ('running','waiting') and self.leases.get(run.id)==current['epoch'] and current['owner_id']==self.owner_id,'运行暂停/取消或需要本次显式恢复，旧许可不可继承');return current
    def control(self,project_id,identifier,action):
        require(action in ('start','pause','cancel','resume','recover','manual','queue'),'未知运行控制');fresh=str(uuid4())
        def apply(state):
            run=find_run(state,identifier);cur=run_state(state,identifier);require(cur['status'] not in ('completed','cancelled'),'终态运行不能重新执行，须新建运行')
            if action=='pause':emit_run(state,run,'paused','paused')
            elif action=='cancel':
                emit_run(state,run,'cancelled','cancelled')
                for a in attempts(state,identifier):
                    if node_state(state,a['id'])['status'] in ('pending','running','waiting_request','waiting_human'):emit_node(state,parse(NodeAttempt,a),'cancelled')
            elif action=='manual':emit_run(state,run,'manual',cur['status'],execution_mode='step',network_mode='disabled')
            else:
                require(action!='start' or cur['status']=='pending','已开始的运行须明确恢复，不重发旧请求')
                if action=='recover':
                    for a in attempts(state,identifier):
                        if a['task_id']:
                            task=get_task(state,a['task_id'])
                            if task.status=='running' and task.owner_id!=self.tasks.owner_id:task_event(state,task,'interrupted',error_code='workflow_explicit_recovery')
                emit_run(state,run,{'start':'started','resume':'resumed','recover':'recovered','queue':'queued'}[action],'running',owner_id=self.owner_id,epoch=fresh,execution_mode='queue' if action=='queue' else cur['execution_mode'])
            return state,None
        self.repository.atomic(project_id,apply)
        if action in ('start','resume','recover','queue'):self.leases[identifier]=fresh
        if action in ('pause','cancel'):self.leases.pop(identifier,None)
        if action=='cancel':
            for a in attempts(self.service.get(project_id),identifier):
                if a['task_id']:self.tasks.cancel(project_id,a['task_id'])
        if action=='queue':self._queue(project_id,identifier)
        return self.describe(project_id,identifier)
    def describe(self,project_id,identifier):
        state=self.service.get(project_id);run=find_run(state,identifier);cur=run_state(state,identifier);result=[]
        for raw in attempts(state,identifier):
            a=parse(NodeAttempt,raw);e=node_state(state,a.id);node=next(n for n in run.expanded_nodes if n.id==a.node_id);item=dict(raw,node_kind=node.kind,status=e['status'],input_attempt_ids=list(a.input_attempt_ids),output_refs=e['output_refs'],error_code=e['error_code'])
            if a.task_id:
                t=get_task(state,a.task_id)
                item['task_status']=t.status
                item.update(self.tasks.stream_preview(t.id,t.status=='running'))
                if hasattr(t.frozen.parameters,'upstream'):item['input_snapshot']=encode(t.frozen.parameters.upstream)
                if hasattr(t.frozen.parameters,'binding'):item.update(request_sha256=t.frozen.parameters.binding.request_sha256,request_body=t.frozen.parameters.binding.request_body,destination=encode(getattr(t.frozen.parameters.binding,'destination',None)))
                if t.status=='succeeded' and node.kind in ('model_idea','model_outline'):
                    c=next(c for c in state['generation_candidates'] if c['id']==t.candidate_id)
                    item['typed_result']=typed_result(t.frozen,c['output_text'])
            if e['snapshot']:item.setdefault('input_snapshot',e['snapshot'])
            manifest=[dict(attempt_id=p,snapshot=node_state(state,p)['snapshot'],output_refs=node_state(state,p)['output_refs']) for p in a.input_attempt_ids]
            item['input_manifest_sha256']=digest(json.dumps(manifest,ensure_ascii=False,sort_keys=True,separators=(',',':')))
            if e['status']=='waiting_human':
                item['diff_sha256']=self._approval_data(state,run,node,a)[1];item['review']=self._approval_view(state,run,node,a)
                if self._is_author_choice(run,node):item['candidates']=self._choices(state,node,a)
            audit=next((r for r in state['workflow_audits'] if r['node_attempt_id']==a.id),None)
            if audit:item.update(audit=audit['output'],audit_record_id=audit['id'],response_record_id=audit.get('response_record_id'),upstream=audit['upstream'])
            result.append(item)
        recovery=cur['status'] not in ('pending','completed','cancelled') and (cur['owner_id']!=self.owner_id or (cur['status']!='paused' and self.leases.get(identifier)!=cur['epoch']))
        return dict(run_id=identifier,revision=state['revision'],status=cur['status'],requires_recovery=recovery,external_calls=cur['external_calls'],reserved_output_tokens=cur['reserved_output_tokens'],limits=encode(run.limits),execution_mode=cur['execution_mode'],network_mode=cur['network_mode'],nodes=[encode(n) for n in run.expanded_nodes],attempts=result,events=run_events(state,identifier))

    def _new_attempt(self,state,run,node,parent_map,*,renewal=False):
        all_attempts=attempts(state,run.id);require(len(all_attempts)<run.limits.max_node_attempts,'运行节点尝试上限已用完');number=sum(a['node_id']==node.id for a in all_attempts)+1
        if number>1 and not renewal:require(number<=run.limits.max_retries+1,'本节点显式重试上限已用完')
        identity=str(uuid4());parent_ids=tuple(parent_map[p]['id'] for p in node.parents);input_refs=tuple(ref('node_attempt',a) for a in parent_ids);snapshot=None;task_id=None
        skip_reason=None
        if node.when and node_state(state,parent_map[node.when.source]['id'])['flag'] is not node.when.equals:skip_reason='declared_branch_not_taken'
        elif node.kind not in ('join','branch') and any(node_state(state,parent_map[p]['id'])['status'] in ('skipped','rejected','failed') for p in node.parents):skip_reason='required_parent_not_available'
        if not skip_reason and (node.kind in ('reference','offline_audit','model_rewrite','model_audit','model_candidate_audit','model_deep_audit','plan_proposal') or node.kind in STAGE_PROMPTS):snapshot=snapshot_for(state,run,node,parent_map,identity)
        if snapshot and node.kind!='reference':require_target(state,snapshot.saved_target)
        if not skip_reason and node.kind in STAGE_PROMPTS:require_stage_source(state,node.kind,snapshot)
        if not skip_reason and (node.kind in ('offline_audit','model_rewrite','model_audit','model_candidate_audit','model_deep_audit') or node.kind in STAGE_PROMPTS):
            from novel_writer.application.context_preview import preview
            p=node.parameters;options=dict(chapter_id=run.chapter_id,budget_chars=p.context_budget,include_writing_rules=True);context=preview(state,options,skills=[]);params=dict(instruction=run.inputs.instruction,max_output_chars=p.max_output_chars,timeout_ms=p.timeout_ms);analysis=node.kind in ('offline_audit','model_audit','model_candidate_audit','model_deep_audit')
            if node.kind=='model_saved_draft':
                options.update(include_characters=True,include_current_plan=True)
                context=preview(state,options,skills=[])
                require(not any(s['truncated'] for s in context['sources']),'保存章纲/人物资料超过预算，请增大资料预算后准备')
            if analysis:params.update(rules=dict(version='offline-audit-1',forbidden_literals=list(p.forbidden_literals) if type(p) is AuditParameters else [],required_literals=[],normalization='whitespace',near_threshold=.85,minimum_fragment_chars=12,check_timeline=False),selected_chapter_ids=[run.chapter_id],previous_report_id=None)
            request=dict(request_id=str(uuid5(NAMESPACE_URL,identity+'/task-request')),chapter_id=run.chapter_id,task_type='audit_chapter' if analysis else 'rewrite_chapter',context_options=options,context_sha256=digest(context['context_text']),parameters=params,expected_revision=state['revision'])
            if node.kind.startswith('model_'):
                role=next(r for r in run.roles if r.role==node.role);opts=encode(role);opts.pop('role');request['model_options']=opts
                if node.kind=='model_audit':require(snapshot.kind=='chapter' and snapshot.text==snapshot.saved_target.text and snapshot.review_id is None and snapshot.search_node_attempt_id is None,'模型审核当前只接整段保存正文；候选/审核链请用离线规则或人工，不伪装成功')
            if node.kind=='model_deep_audit':
                from novel_writer.domain.deep_review import PROMPT
                from novel_writer.application.deep_reviews import canonical_selection
                require(snapshot.kind=='candidate','审核必须消费真实初稿候选')
                request['model_options']['prompt_version']=PROMPT
                request['parameters']['instruction']+='\ncharacter_consistency核对候选context中的冻结人物设定；rule_conflict核对同一context中的作者规则。指引不是硬性禁令；资料不足必须说明，不得编造事实。'
                request['context_sha256']=digest('')
                request['context_options']=dict(chapter_id=run.chapter_id,budget_chars=p.context_budget,include_current_plan=False,include_book_outline=False,include_characters=False,include_worldbuilding=False,include_writing_rules=False,include_memories=False,include_search_results=False)
                outlines=[o['id'] for o in state['document']['chapter_outlines'] if o['chapter_id']==run.chapter_id]
                request['deep_review']=canonical_selection(dict(checks=['relative_time','uncertain_time','duration','causality','motivation','character_knowledge','character_arc','character_consistency','rule_conflict'],candidate_ids=[snapshot.entity_id],material_ids=[],memory_ids=[],planning_ids=outlines))
            operation,_=self.tasks._preparer(run.project_id,request);_,prepared=operation(state);task=parse(GenerationTask,prepared['task'])
            inherited=[]
            if snapshot.kind=='candidate':inherited=list(get_task(state,snapshot.producer_task_id).frozen.dependencies)
            if snapshot.search_node_attempt_id:
                se=node_state(state,snapshot.search_node_attempt_id)
                for hit in se['search_hits']:
                    selected=hit['selection'];actual=capture_dependency(state,selected['kind'],selected['entity_id']);require((actual.version_id,actual.source_sha256)==(selected['version_id'],selected['source_sha256']),'检索资料已变化，请明确重跑检索');inherited.append(actual)
            deps=list(task.frozen.dependencies)
            for old in inherited:
                skill=self.service._skills([old.entity_id])[0] if old.kind=='skill' else None;actual=capture_dependency(state,old.kind,old.entity_id,use='context',skill=skill,file_path=old.file_path);require(dependency_equal(old,actual),'上游候选依赖已变化，不能给后继假装最新来源')
                if old.kind=='chapter' and old.entity_id==run.chapter_id:continue
                if not any((d.kind,d.entity_id,d.use,d.file_path)==(actual.kind,actual.entity_id,actual.use,actual.file_path) for d in deps):deps.append(actual)
            task=replace(task,frozen=replace(task.frozen,dependencies=tuple(deps)));put_task(state,task)
            if node.kind=='model_rewrite' or node.kind in STAGE_PROMPTS:
                prompt=STAGE_PROMPTS.get(node.kind,'workflow-rewrite-1')
                base=task.frozen.parameters;options=encode(base.binding);options['prompt_version']=prompt;proxy=SimpleNamespace(target=task.frozen.target,context_text=task.frozen.context_text,parameters=SimpleNamespace(instruction=base.instruction,upstream=snapshot));body=request_body(proxy,options);binding=replace(base.binding,prompt_version=prompt,request_body=body,request_sha256=request_digest(body,getattr(base.binding,'destination',None)));parameters=WorkflowModelParameters(instruction=base.instruction,max_output_chars=base.max_output_chars,timeout_ms=base.timeout_ms,binding=binding,upstream=snapshot);task=replace(task,frozen=replace(task.frozen,parameters=parameters));put_task(state,task)
            elif node.kind=='model_candidate_audit':
                from novel_writer.domain.workflow_contract import candidate_identity
                require(snapshot.kind=='candidate' and snapshot.text.strip(),'模型候选审核只接声明上游真实候选')
                base=task.frozen.parameters;options=encode(base.binding);options['prompt_version']='candidate-review-json-1'
                wire_source=candidate_identity(snapshot)
                proxy=SimpleNamespace(target=task.frozen.target,context_text='',parameters=SimpleNamespace(instruction=base.instruction,upstream=snapshot,wire_source=wire_source));body=request_body(proxy,options);binding=replace(base.binding,prompt_version='candidate-review-json-1',request_body=body,request_sha256=request_digest(body,getattr(base.binding,'destination',None)))
                parameters=CandidateModelParameters(instruction=base.instruction,max_output_chars=base.max_output_chars,timeout_ms=base.timeout_ms,binding=binding,upstream=snapshot,wire_source=wire_source,copy_mappings=())
                options=task.frozen.context_options;clean_options=replace(options,**{name:False for name in options.__dataclass_fields__ if name.startswith('include_')},character_ids=(),memory_ids=(),search_selections=())
                task=replace(task,frozen=replace(task.frozen,parameters=parameters,context_text='',context_sha256=digest(''),context_options=clean_options,skill_snapshots=()));put_task(state,task)
            elif node.kind=='offline_audit':
                parameters=CandidateAuditParameters(instruction=run.inputs.instruction,max_output_chars=p.max_output_chars,timeout_ms=p.timeout_ms,adapter_id='candidate-offline-audit-v1',upstream=snapshot,forbidden_literals=p.forbidden_literals);task=replace(task,frozen=replace(task.frozen,parameters=parameters));put_task(state,task)
            task_id=task.id
        a=NodeAttempt(id=identity,project_id=run.project_id,run_id=run.id,node_id=node.id,number=number,input_attempt_ids=parent_ids,input_refs=input_refs,task_id=task_id,created_at=utc_now());append(state,'workflow_attempts',a)
        status='skipped' if skip_reason else 'waiting_request' if node.kind.startswith('model_') else 'waiting_human' if node.kind=='human' else 'pending';refs=(ref('task',task_id),) if task_id else ();emit_node(state,a,status,snapshot=snapshot,output_refs=refs,error_code=skip_reason)
        return a

    def _sync_task(self,state,run,a,node):
        task=get_task(state,a.task_id);current=node_state(state,a.id)
        if task.status in ('pending','running'):return False
        if task.status!='succeeded':
            emit_node(state,a,'failed',error_code=task.error_code or task.status);handled=any(n.kind=='branch' and n.source==node.id and n.parameters.expected=='failed' for n in run.expanded_nodes);emit_run(state,run,'waiting' if handled else 'failed','running' if handled else 'failed');return True
        refs=[ref('task',task.id,task.attempt_id)];snapshot=parse(InputSnapshot,current['snapshot']) if current['snapshot'] else None;flag=None
        if task.task_type=='rewrite_chapter':
            candidate=next(c for c in state['generation_candidates'] if c['id']==task.candidate_id);snapshot=candidate_snapshot(task,candidate,a.id);refs.append(ref('candidate',candidate['id'],task.frozen.target.version_id,digest(candidate['output_text'])))
        elif isinstance(task.frozen.parameters,(CandidateAuditParameters,CandidateModelParameters)):
            record=next(r for r in state['workflow_audits'] if r['task_id']==task.id);output=parse(CandidateAuditOutput|CandidateModelOutput,record['output']);snapshot=replace(task.frozen.parameters.upstream,via_node_attempt_id=a.id,review_id=record['id'],search_node_attempt_id=None,feedback=feedback_text(output));refs.append(ref('workflow_audit',record['id']));flag=bool(output.findings)
            if snapshot.kind=='candidate':
                c=next(c for c in state['generation_candidates'] if c['id']==snapshot.entity_id);refs.append(ref('candidate',c['id'],snapshot.saved_target.version_id,digest(c['output_text'])))
        else:
            record=next(r for r in state['model_reports'] if r['task_id']==task.id);refs.append(ref('model_report',record['id']));flag=bool(record['output']['findings'])
            if node.kind=='model_deep_audit':
                refs.append(ref('candidate',snapshot.entity_id,snapshot.saved_target.version_id,snapshot.text_sha256))
        emit_node(state,a,'succeeded',output_refs=tuple(refs),snapshot=snapshot,flag=flag,error_code=None);return True

    def step(self,project_id,identifier):
        try:return self._step(project_id,identifier)
        except Exception:
            def rejected(state):
                run=find_run(state,identifier)
                try:self._allowed(state,run)
                except ValueError:return None,None
                current=latest(state,identifier)
                for n in run.expanded_nodes:
                    raw=current.get(n.id)
                    if raw and node_state(state,raw['id'])['status'] in ('succeeded','skipped','rejected'):continue
                    if raw:
                        a=parse(NodeAttempt,raw)
                        if node_state(state,a.id)['status'] not in ('failed','cancelled'):emit_node(state,a,'failed',error_code='node_source_or_parameters_rejected')
                    elif len(attempts(state,identifier))<run.limits.max_node_attempts and all(p in current for p in n.parents):
                        parent_ids=tuple(current[p]['id'] for p in n.parents);a=NodeAttempt(id=str(uuid4()),project_id=project_id,run_id=identifier,node_id=n.id,number=1,input_attempt_ids=parent_ids,input_refs=tuple(ref('node_attempt',p) for p in parent_ids),task_id=None,created_at=utc_now());append(state,'workflow_attempts',a);emit_node(state,a,'failed',error_code='node_source_or_parameters_rejected')
                    break
                emit_run(state,run,'failed','failed');return state,None
            self.repository.atomic(project_id,rejected);raise

    def _step(self,project_id,identifier):
        def apply(state):
            run=find_run(state,identifier);self._allowed(state,run);current=latest(state,identifier)
            for node in run.expanded_nodes:
                raw=current.get(node.id);a=parse(NodeAttempt,raw) if raw else None;e=node_state(state,a.id) if a else None
                if a and e['status'] in ('succeeded','skipped','rejected'):
                    if any(p not in current for p in node.parents) or tuple(current[p]['id'] for p in node.parents)!=a.input_attempt_ids:emit_run(state,run,'waiting','waiting');return state,dict(wait=True)
                    continue
                if a and e['status']=='cancelled':raise ValueError('节点已取消，须明确重试或新运行')
                if a and e['status']=='failed':
                    if any(n.kind=='branch' and n.source==node.id and n.parameters.expected=='failed' for n in run.expanded_nodes):continue
                    emit_run(state,run,'failed','failed');return state,dict(wait=False)
                if not all(p in current and node_state(state,current[p]['id'])['status'] in ('succeeded','skipped','rejected','failed') for p in node.parents):continue
                if node.kind=='apply' and not a:
                    human=current[node.source];he=node_state(state,human['id']);approval=next((p for p in state['workflow_approvals'] if p['id']==he['approval_id']),None)
                    if he['status']=='succeeded' and (approval is None or approval['epoch']!=run_state(state,identifier)['epoch']):
                        hnode=next(n for n in run.expanded_nodes if n.id==node.source);ha=self._new_attempt(state,run,hnode,current,renewal=True);emit_run(state,run,'waiting','waiting');return state,dict(wait=True)
                if not a:
                    if run.limits.concurrency>1 and node.kind.startswith('model_'):
                        pending=[p for p in latest(state,identifier).values() if node_state(state,p['id'])['status'] in ('running','waiting_request')]
                        if len(pending)>=run.limits.concurrency:continue
                    a=self._new_attempt(state,run,node,current);e=node_state(state,a.id)
                if e['status']=='skipped':return state,dict(wait=False)
                if node.when:
                    source=node_state(state,current[node.when.source]['id'])
                    if source['flag'] is not node.when.equals:emit_node(state,a,'skipped',error_code='declared_branch_not_taken');return state,dict(wait=False)
                if node.kind not in ('join','branch') and any(node_state(state,current[p]['id'])['status'] in ('skipped','rejected','failed') for p in node.parents):emit_node(state,a,'skipped',error_code='required_parent_not_available');return state,dict(wait=False)
                if a.task_id:
                    task=get_task(state,a.task_id)
                    if task.status in ('succeeded','failed','cancelled','interrupted'):self._sync_task(state,run,a,node);return state,dict(wait=False)
                    if node.kind.startswith('model_'):
                        if run.limits.concurrency>1:continue
                        emit_run(state,run,'waiting','waiting' if task.status=='pending' else 'running');return state,dict(wait=task.status=='pending')
                    return state,dict(start_local=a.id)
                if node.kind=='human':
                    if run.limits.concurrency>1:continue
                    emit_run(state,run,'waiting','waiting');return state,dict(wait=True)
                if node.kind in ('apply','plan_proposal'):return state,dict(business=a.id)
                if node.kind=='outline_source':
                    from novel_writer.domain.creative_workflow import outline_payload
                    outline=next((o for o in state['document']['chapter_outlines'] if o['chapter_id']==run.chapter_id),None)
                    require(outline is not None,'请先保存章节细纲')
                    version=next((v for v in reversed(state['document']['versions']) if v['entity_type']=='chapter_outline' and v['entity_id']==outline['id']),None);require(version is not None,'请先保存章节细纲')
                    value=outline_payload(outline);require(bool(value['core_idea'].strip()) and bool(value['scenes']),'初稿需要非空核心情节和保存场景')
                    text=json.dumps(value,ensure_ascii=False,sort_keys=True);s=saved_snapshot(state,run.chapter_id,a.id);require(s.saved_target.text=='','初稿仅允许空正文目标');s=replace(s,kind='chapter_outline',entity_id=outline['id'],version_id=version['id'],text=text,start=0,end=len(text),text_sha256=digest(text))
                    emit_node(state,a,'succeeded',snapshot=s,output_refs=(ref('chapter_outline',outline['id'],version['id'],digest(text)),))
                elif node.kind=='reference':
                    s=parse(InputSnapshot,e['snapshot']);text=s.text[:node.parameters.max_chars];s=replace(s,text=text,end=s.start+len(text),text_sha256=digest(text),via_node_attempt_id=a.id);emit_node(state,a,'succeeded',snapshot=s,output_refs=(ref(s.kind,s.entity_id,s.version_id,s.text_sha256),))
                elif node.kind=='manual':
                    value=getattr(run.inputs,node.parameters.slot);emit_node(state,a,'succeeded',output_refs=(ref('manual_value',run.id,node.parameters.slot,digest(value)),))
                elif node.kind=='search':
                    result=self.service.search_local(project_id,dict(query=run.inputs.query,chapter_id=run.chapter_id,whole_book=False,scopes=['body'],skill_ids=[]));hits=tuple(SearchHit(title=next(c['title'] for c in state['document']['chapters'] if c['id']==h['entity_id']),snippet=h['snippet'],selection=parse(SearchSelection,h['selection'])) for h in result['hits'][:node.parameters.max_results]);s=saved_snapshot(state,run.chapter_id,a.id);s=replace(s,search_node_attempt_id=a.id,feedback=search_feedback(hits));emit_node(state,a,'succeeded',output_refs=tuple(ref('chapter',h['entity_id'],h['selection']['version_id'],h['selection']['source_sha256']) for h in result['hits'][:node.parameters.max_results]),flag=bool(hits),search_hits=hits,snapshot=s)
                elif node.kind=='branch':
                    source=node_state(state,current[node.source]['id']);wanted=node.parameters.expected;flag=(source['flag'] is True) if wanted=='has_findings' else (source['flag'] is False) if wanted=='no_findings' else source['status']==({'approved':'succeeded','rejected':'rejected','failed':'failed'}.get(wanted,wanted));emit_node(state,a,'succeeded',flag=flag,output_refs=(ref('node_attempt',current[node.source]['id']),))
                elif node.kind=='join':
                    source=node_state(state,current[node.source]['id']) if node.source else None;emit_node(state,a,'succeeded',output_refs=tuple(ref('node_attempt',current[p]['id']) for p in node.parents)+(tuple(parse(ArtifactRef,r) for r in source['output_refs']) if source else ()),snapshot=parse(InputSnapshot,source['snapshot']) if source and source['snapshot'] else None)
                elif node.kind=='memory_proposal':self._prepare_memory(state,run,node,a,current)
                else:raise ValueError('未实现节点能力，不能假装成功')
                return state,dict(wait=False)
            pending=[node_state(state,a['id']) for a in latest(state,identifier).values() if node_state(state,a['id'])['status'] not in ('succeeded','skipped','rejected','failed')]
            if pending:
                running=any(e['status']=='running' for e in pending);emit_run(state,run,'waiting','running' if running else 'waiting');return state,dict(wait=not running)
            require(len(latest(state,identifier))==len(run.expanded_nodes),'尚有节点未执行，不能标记完成')
            emit_run(state,run,'completed','completed');return state,dict(wait=False)
        action=self.repository.atomic(project_id,apply)
        if action.get('start_local'):
            state=self.service.get(project_id);a=parse(NodeAttempt,next(a for a in state['workflow_attempts'] if a['id']==action['start_local']))
            def started(state,task):
                run=find_run(state,identifier);self._allowed(state,run);require(node_state(state,a.id)['status']=='pending','本地节点不再待执行');emit_node(state,a,'running',output_refs=(ref('task',task.id,task.attempt_id),))
            if get_task(state,a.task_id).status=='pending':self.tasks.start(project_id,a.task_id,_workflow=started)
            self.tasks.wait_idle(3)
            return self.step(project_id,identifier)
        if action.get('business'):self._business(project_id,identifier,action['business'])
        return self.describe(project_id,identifier)

    def _prepare_memory(self,state,run,node,a,parent_map):
        source_a=parent_map[node.source];e=node_state(state,source_a['id']);refs=e['output_refs'];model=next((r for r in refs if r['kind']=='model_report'),None)
        if model:
            items=[p for p in state['model_memory_proposals'] if p['report_id']==model['entity_id']];require(0<=node.parameters.index<len(items),'上游模型没有该记忆提案');p=items[node.parameters.index];emit_node(state,a,'succeeded',output_refs=(ref('model_memory_proposal',p['id']),),snapshot=parse(InputSnapshot,e['snapshot']) if e['snapshot'] else None);return
        require(e['snapshot'] is not None,'上游无保存原文');s=parse(InputSnapshot,e['snapshot']);require(s.kind=='chapter' and s.text.strip(),'未采纳候选不得直接产生确认事实记忆');require_target(state,s.saved_target);proposal=MemoryProposal(id=str(uuid5(NAMESPACE_URL,a.id+'/memory-proposal')),project_id=run.project_id,run_id=run.id,node_attempt_id=a.id,source=s,text=s.text[:4000],created_at=utc_now());append(state,'workflow_memory_proposals',proposal);emit_node(state,a,'succeeded',output_refs=(ref('workflow_memory_proposal',proposal.id,s.version_id,digest(proposal.text)),),snapshot=s)

    def _parent_for_attempt(self,state,node,a):
        selected=node_state(state,a.id)['snapshot']
        if node.kind=='human' and selected and len(node.parents)>1:
            for identifier in a.input_attempt_ids:
                e=node_state(state,identifier)
                if e['snapshot'] and e['snapshot']['entity_id']==selected['entity_id']:
                    parent=next(p for p in state['workflow_attempts'] if p['id']==identifier)
                    return parent,e
        parent=next((p for p in state['workflow_attempts'] if p['id'] in a.input_attempt_ids and p['node_id']==node.source),None);require(parent is not None,'人工/写入节点缺声明的上游尝试');return parent,node_state(state,parent['id'])

    def _is_author_choice(self,run,node):
        return any(n.id==node.id and n.kind=='await_author' for n in run.template.nodes)

    def _choices(self,state,node,a):
        result=[];seen=set()
        for identifier in a.input_attempt_ids:
            e=node_state(state,identifier)
            for r in e['output_refs']:
                if r['kind']!='candidate' or r['entity_id'] in seen:continue
                seen.add(r['entity_id']);c=next(c for c in state['generation_candidates'] if c['id']==r['entity_id'])
                report=next((state_ref['entity_id'] for state_ref in e['output_refs'] if state_ref['kind']=='model_report'),None)
                output=next((r['output'] for r in state['model_reports'] if r['id']==report),None)
                result.append(dict(candidate_id=c['id'],text=c['output_text'],audit_report_id=report,audit=deepcopy(output)))
        return result

    def select_candidate(self,project_id,identifier,attempt_id,request):
        check_fields(request,{'candidate_id','expected_revision'});require(set(request)=={'candidate_id','expected_revision'},'选稿字段缺失')
        def apply(state):
            run=find_run(state,identifier);self._allowed(state,run)
            raw=next((a for a in attempts(state,identifier) if a['id']==attempt_id),None);require(raw is not None,'选稿节点不属于运行');a=parse(NodeAttempt,raw);node=next(n for n in run.expanded_nodes if n.id==a.node_id)
            require(self._is_author_choice(run,node) and node_state(state,a.id)['status']=='waiting_human','节点不在等待作者选稿')
            require(type(request['expected_revision']) is int and request['expected_revision']==state['revision'],'选稿保存编号变化')
            require(request['candidate_id'] in {c['candidate_id'] for c in self._choices(state,node,a)},'候选不属于该审核组')
            source=next(node_state(state,p) for p in a.input_attempt_ids if node_state(state,p)['snapshot'] and node_state(state,p)['snapshot']['entity_id']==request['candidate_id'])
            s=parse(InputSnapshot,source['snapshot']);require_target(state,s.saved_target)
            emit_node(state,a,'waiting_human',snapshot=s);return state,None
        self.repository.atomic(project_id,apply)
        return self.describe(project_id,identifier)
    def _approval_data(self,state,run,node,a):
        parent,e=self._parent_for_attempt(state,node,a);action=node.parameters.action
        if action=='body':
            r=next((r for r in e['output_refs'] if r['kind']=='candidate'),None);require(r is not None and e['snapshot'] is not None,'上游无完成候选，不能授予正文写入许可');s=parse(InputSnapshot,e['snapshot']);candidate=next(c for c in state['generation_candidates'] if c['id']==r['entity_id']);producer=get_task(state,candidate['task_id']);require(getattr(getattr(producer.frozen.parameters,'binding',None),'prompt_version',None) not in PLAN_PROMPTS,'IDEA/细纲typed候选不能通过正文人工门写正文');value=json.dumps(dict(action=action,before=s.saved_target.text,after=candidate['output_text']),ensure_ascii=False,sort_keys=True);return parse(ArtifactRef,r),digest(value)
        kind='planning_proposal' if action=='plan' else None;r=next((r for r in e['output_refs'] if r['kind']==kind),None) if kind else next((r for r in e['output_refs'] if r['kind'] in ('workflow_memory_proposal','model_memory_proposal')),None);require(r is not None,'上游没有该类型提案')
        if action=='plan':p=next(p for p in state['planning_proposals'] if p['id']==r['entity_id']);value=dict(action=action,field=p['field'],old=p['old_text'],new=p['new_text'])
        elif r['kind']=='workflow_memory_proposal':p=next(p for p in state['workflow_memory_proposals'] if p['id']==r['entity_id']);value=dict(action=action,text=p['text'],quote=p['source']['text'])
        else:p=next(p for p in state['model_memory_proposals'] if p['id']==r['entity_id']);value=dict(action=action,text=p['draft']['text'],quotes=[e['quote'] for e in p['draft']['evidence']])
        return parse(ArtifactRef,r),digest(json.dumps(value,ensure_ascii=False,sort_keys=True))
    def _approval_view(self,state,run,node,a):
        parent,e=self._parent_for_attempt(state,node,a);r,sha=self._approval_data(state,run,node,a)
        if node.parameters.action=='body':s=parse(InputSnapshot,e['snapshot']);candidate=next(c for c in state['generation_candidates'] if c['id']==r.entity_id);return dict(kind='body',before=s.saved_target.text,after=candidate['output_text'],target_version=s.saved_target.version_id,diff_sha256=sha,input_ref=encode(r))
        collection={'planning_proposal':'planning_proposals','workflow_memory_proposal':'workflow_memory_proposals','model_memory_proposal':'model_memory_proposals'}[r.kind];return dict(kind=node.parameters.action,proposal=next(p for p in state[collection] if p['id']==r.entity_id),diff_sha256=sha,input_ref=encode(r))

    def confirm(self,project_id,identifier,attempt_id,request):
        fields={'operation_id','decision','request_sha256','diff_sha256','authorize_confirmed','confirm_inference','preserve_conflicts','expected_revision'};check_fields(request,fields);require(set(request)==fields,'节点确认字段缺失');identity=uuid_value(request['operation_id']);require(request['decision'] in ('accepted','rejected') and all(type(request[k]) is bool for k in ('authorize_confirmed','confirm_inference','preserve_conflicts')),'作者决定/授权类型非法');state=self.service.get(project_id);run=find_run(state,identifier);a=parse(NodeAttempt,next(a for a in attempts(state,identifier) if a['id']==attempt_id));node=next(n for n in run.expanded_nodes if n.id==a.node_id);old=next((p for p in state['workflow_approvals'] if p['id']==identity),None)
        if old:require(old['node_attempt_id']==attempt_id and old['decision']==request['decision'],'确认身份绑定其它节点/决定');return self.describe(project_id,identifier)
        if node.kind.startswith('model_'):
            require(request['decision']=='accepted','模型请求可取消节点，不以拒绝记录伪装已执行');task=get_task(state,a.task_id);binding=task.frozen.parameters.binding;require(request['request_sha256']==binding.request_sha256,'本次请求摘要不符')
            def started(state,actual_task):
                run=find_run(state,identifier);cur=self._allowed(state,run);require(cur['network_mode']=='confirm_each' and node_state(state,a.id)['status']=='waiting_request','当前为完全手动/离线或节点不再等待本次请求确认');require(cur['external_calls']<run.limits.max_external_calls and cur['reserved_output_tokens']+binding.max_tokens<=run.limits.max_reserved_output_tokens,'本次外发次数/保留输出token上限已用完，不退款式重试');require(type(request['expected_revision']) is int and request['expected_revision']==state['revision'],'确认保存编号变化，请重看请求')
                snapshot=actual_task.frozen.parameters.upstream if hasattr(actual_task.frozen.parameters,'upstream') else None
                if snapshot:require_target(state,snapshot.saved_target)
                if node.kind in STAGE_PROMPTS:require_stage_source(state,node.kind,snapshot)
                from novel_writer.application.reviews import assert_fresh
                assert_fresh(self.tasks,state,actual_task)
                p=Approval(id=identity,project_id=project_id,run_id=identifier,node_attempt_id=a.id,epoch=cur['epoch'],kind='external',decision='accepted',input_ref=ref('task',actual_task.id,actual_task.attempt_id,binding.request_sha256),content_sha256=binding.request_sha256,authorize_confirmed=False,confirm_inference=False,preserve_conflicts=False,created_at=utc_now());append(state,'workflow_approvals',p);emit_run(state,run,'started','running',external_calls=cur['external_calls']+1,reserved_output_tokens=cur['reserved_output_tokens']+binding.max_tokens);emit_node(state,a,'running',approval_id=p.id,output_refs=(ref('task',actual_task.id,actual_task.attempt_id,binding.request_sha256),))
            self.tasks.start(project_id,a.task_id,confirmation=dict(confirm_external=True,request_sha256=request['request_sha256']),_workflow=started,_workflow_group=run.id if run.limits.concurrency>1 else None,_workflow_limit=run.limits.concurrency)
        else:
            require(node.kind=='human','该节点不是人工确认节点')
            def apply(state):
                run=find_run(state,identifier);cur=self._allowed(state,run);require(node_state(state,a.id)['status']=='waiting_human','该人工节点不再等待');current=latest(state,identifier);require(tuple(current[p]['id'] for p in node.parents)==a.input_attempt_ids,'上游已产生新结果，请明确重跑本人工节点');r,sha=self._approval_data(state,run,node,a);require(sha==request['diff_sha256'],'本次差异摘要不符');require(type(request['expected_revision']) is int and request['expected_revision']==state['revision'],'确认保存编号变化，请重看差异');parent,e=self._parent_for_attempt(state,node,a)
                if request['decision']=='accepted':
                    if self._is_author_choice(run,node):require(node_state(state,a.id)['snapshot'] is not None,'请先明确选择候选，再核对差异确认采纳')
                    if e['snapshot']:require_target(state,parse(InputSnapshot,e['snapshot']).saved_target)
                    if node.parameters.action=='body':s=parse(InputSnapshot,e['snapshot']);require(s.saved_target.status!='confirmed' or request['authorize_confirmed'],'正式章需要本次明确作者授权')
                    if node.parameters.action=='memory':require(request['confirm_inference'],'记忆/推断必须明确核对与确认')
                p=Approval(id=identity,project_id=project_id,run_id=identifier,node_attempt_id=a.id,epoch=cur['epoch'],kind=node.parameters.action,decision=request['decision'],input_ref=r,content_sha256=sha,authorize_confirmed=request['authorize_confirmed'],confirm_inference=request['confirm_inference'],preserve_conflicts=request['preserve_conflicts'],created_at=utc_now());append(state,'workflow_approvals',p);emit_node(state,a,'succeeded' if request['decision']=='accepted' else 'rejected',output_refs=(ref('approval',p.id,None,sha),),approval_id=p.id,snapshot=parse(InputSnapshot,e['snapshot']) if e['snapshot'] else None,flag=request['decision']=='accepted');emit_run(state,run,'started','running');return state,None
            self.repository.atomic(project_id,apply,identity_claim=('workflow_approvals','id',identity))
        if run_state(self.service.get(project_id),identifier)['execution_mode']=='queue':self._queue(project_id,identifier)
        return self.describe(project_id,identifier)

    def _write_guard(self,state,identifier,a,node):
        run=find_run(state,identifier);cur=self._allowed(state,run);require(node_state(state,a.id)['status']=='pending','写节点不再待执行');parent,e=self._parent_for_attempt(state,node,a);p=next((p for p in state['workflow_approvals'] if p['id']==e['approval_id']),None);require(p is not None and p['decision']=='accepted' and p['epoch']==cur['epoch'] and p['kind']==node.parameters.action,'旧/复制/恢复审批不能授权本次写入');human=next(n for n in run.expanded_nodes if n.id==parent['node_id']);r,sha=self._approval_data(state,run,human,parse(NodeAttempt,parent));require(sha==p['content_sha256'] and encode(r)==p['input_ref'],'人工许可与本次具体差异/目标不符');require(not any(r['approval_id']==p['id'] for r in state['workflow_receipts']),'该人工许可已消费，不得授权第二次写入');return run,p,r
    def _finish_apply(self,state,run,a,p,business_kind,business_id,memory_id=None,memory_version_id=None):
        receipt=ApplyReceipt(id=str(uuid5(NAMESPACE_URL,a.id+'/workflow-receipt')),project_id=run.project_id,run_id=run.id,node_attempt_id=a.id,approval_id=p['id'],action=p['kind'],business_kind=business_kind,business_id=business_id,memory_id=memory_id,memory_version_id=memory_version_id,created_at=utc_now());append(state,'workflow_receipts',receipt);snapshot=saved_snapshot(state,run.chapter_id,a.id);emit_node(state,a,'succeeded',output_refs=(ref('workflow_receipt',receipt.id),ref('chapter',run.chapter_id,snapshot.version_id,snapshot.text_sha256)),snapshot=snapshot)

    def _business(self,project_id,identifier,attempt_id):
        state=self.service.get(project_id);run=find_run(state,identifier);a=parse(NodeAttempt,next(a for a in attempts(state,identifier) if a['id']==attempt_id));node=next(n for n in run.expanded_nodes if n.id==a.node_id)
        try:
            if node.kind=='plan_proposal':
                from novel_writer.application.knowledge import command
                s=parse(InputSnapshot,node_state(state,a.id)['snapshot']);require(s.kind=='chapter','候选不是保存事实来源；请先经过正文人工采纳');doc=state['document'];target_obj=doc['book_outline'] if node.parameters.target_kind=='book_outline' else next((o for o in doc['chapter_outlines'] if o['chapter_id']==run.chapter_id),None);require(target_obj is not None,'请先创建该规划实体')
                def hook(state,phase,result):
                    run=find_run(state,identifier);self._allowed(state,run);require(node_state(state,a.id)['status']=='pending','提案节点不再待执行');require_target(state,s.saved_target)
                    if phase=='after':emit_node(state,a,'succeeded',output_refs=(ref('planning_proposal',result['id'],result['target']['version_id']),),snapshot=s)
                command(self.service,project_id,'prepare_plan',dict(operation_id=str(uuid5(NAMESPACE_URL,a.id+'/prepare-plan')),expected_revision=state['revision'],target_kind=node.parameters.target_kind,target_id=target_obj['id'],field=node.parameters.field,new_text=run.inputs.plan_text,source=dict(kind='chapter',entity_id=run.chapter_id),reason='工作流人工规划提案，未作语义推断'),_workflow=hook);return
            run,p,r=self._write_guard(state,identifier,a,node);operation_id=str(uuid5(NAMESPACE_URL,a.id+'/apply'))
            if r.kind=='candidate':
                candidate=next(c for c in state['generation_candidates'] if c['id']==r.entity_id)
                def hook(state,task,phase,result):
                    run,p,_=self._write_guard(state,identifier,a,node)
                    if phase=='after':self._finish_apply(state,run,a,p,'adoption_receipt',result['id'])
                self.tasks.adopt(project_id,candidate['task_id'],dict(candidate_id=candidate['id'],adoption_id=operation_id,expected_revision=state['revision'],authorize_confirmed=p['authorize_confirmed']),_workflow=hook)
            elif r.kind=='planning_proposal':
                from novel_writer.application.knowledge import command
                def hook(state,phase,result):
                    run,p,_=self._write_guard(state,identifier,a,node)
                    if phase=='after':self._finish_apply(state,run,a,p,'planning_receipt',result['id'])
                command(self.service,project_id,'decide_plan',dict(operation_id=operation_id,expected_revision=state['revision'],proposal_id=r.entity_id,decision='accepted'),_workflow=hook)
            elif r.kind=='model_memory_proposal':
                proposal=next(x for x in state['model_memory_proposals'] if x['id']==r.entity_id)
                def hook(state,phase,result):
                    run,p,_=self._write_guard(state,identifier,a,node)
                    if phase=='after':self._finish_apply(state,run,a,p,'model_proposal_receipt',result['id'],result['memory_id'],result['memory_version_id'])
                self.tasks.decide_model_proposal(project_id,proposal['report_id'],dict(decision_id=operation_id,proposal_id=r.entity_id,decision='accepted',expected_revision=state['revision'],confirm_inference=p['confirm_inference'],preserve_conflicts=p['preserve_conflicts']),_workflow=hook)
            elif r.kind=='workflow_memory_proposal':
                from novel_writer.application.memories import save
                def apply(state):
                    run,p,r=self._write_guard(state,identifier,a,node);proposal=next(x for x in state['workflow_memory_proposals'] if x['id']==r.entity_id);s=parse(InputSnapshot,proposal['source']);require(s.kind=='chapter','未采纳候选不能成为确认事实');require_target(state,s.saved_target);require(p['confirm_inference'],'作者未明确确认记忆');before={m['id'] for m in state['memories']};state=save(state,'save_memory',dict(kind='chapter_summary',title='工作流已保存原文摘录',text=proposal['text'],position_chapter_id=run.chapter_id,confirmed=True,source=dict(kind='chapter',entity_id=run.chapter_id)));m=next(m for m in state['memories'] if m['id'] not in before);self._finish_apply(state,run,a,p,'workflow_memory',operation_id,m['id'],state['memory_history'][-1]['id']);return state,None
                self.repository.atomic(project_id,apply)
            else:raise ValueError('未注册的正式写入引用')
        except Exception:
            def failed(state):
                run=find_run(state,identifier);cur=run_state(state,identifier)
                if cur['status'] in ('paused','cancelled'):return None,None
                if node_state(state,a.id)['status']=='pending':emit_node(state,a,'failed',error_code='business_guard_or_storage_failure');emit_run(state,run,'failed','failed');return state,None
                return None,None
            self.repository.atomic(project_id,failed);raise

    def retry(self,project_id,identifier,node_id):
        def apply(state):
            run=find_run(state,identifier);cur=run_state(state,identifier);require(self.leases.get(identifier)==cur['epoch'] and cur['owner_id']==self.owner_id and cur['status'] not in ('cancelled','completed','paused'),'本次会话未恢复或不能重试');nodes={n.id:n for n in run.expanded_nodes};require(node_id in nodes,'节点不属于运行');current=latest(state,identifier);old=current.get(node_id);require(old is not None,'节点尚未尝试');oldstate=node_state(state,old['id']);changed=tuple(current[p]['id'] for p in nodes[node_id].parents)!=tuple(old['input_attempt_ids']);require(oldstate['status'] in ('failed','cancelled') or changed,'已完成结果不自动重发；只明确重试失败或上游变化节点');self._new_attempt(state,run,nodes[node_id],current);emit_run(state,run,'retry','running');return state,None
        self.repository.atomic(project_id,apply);return self.describe(project_id,identifier)
    def _queue(self,project_id,identifier):
        with self.lock:
            if identifier in self.workers and self.workers[identifier].is_alive():self.queue_wake.add(identifier);return
            def work():
                try:
                    while not self.closed.is_set():
                        view=self.describe(project_id,identifier)
                        if view['requires_recovery'] or view['status'] in ('paused','cancelled','completed','failed'):break
                        view=self.step(project_id,identifier)
                        if view['status']=='waiting':break
                        self.closed.wait(.05)
                except Exception:pass
                finally:
                    with self.lock:
                        self.workers.pop(identifier,None);restart=identifier in self.queue_wake;self.queue_wake.discard(identifier)
                    if restart and not self.closed.is_set():self._queue(project_id,identifier)
            worker=threading.Thread(target=work,daemon=True);self.workers[identifier]=worker;worker.start()
    def close(self):
        self.closed.set();self.leases.clear()
        for worker in list(self.workers.values()):worker.join(2)
