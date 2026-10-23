"""共享任务中的模型冻结请求、持久响应和人工确认的记忆提案。"""
from dataclasses import replace
from copy import deepcopy
from uuid import uuid4,uuid5,NAMESPACE_URL
from novel_writer.domain.model_contract import *
from novel_writer.domain.tasks import parse,encode,require,uuid_value,digest
from novel_writer.application.fields import check_fields

from novel_writer.domain.sampling import canonical as canonical_sampling,kwargs as sampling_kwargs

OPTION_FIELDS={'adapter_id','connection_id','model_id','temperature','max_tokens','budget_limit','allow_unknown_cost','prompt_version'}
def canonical_options(raw):
    check_fields(raw,OPTION_FIELDS|{'sampling'});require(set(raw) in (OPTION_FIELDS,OPTION_FIELDS|{'sampling'}),'模型选择/上限/预算/提示词版本字段缺失')
    result=deepcopy(raw)
    if 'sampling' in result:result['sampling']=canonical_sampling(result['sampling'])
    for name in ('temperature','budget_limit'):
        require(type(result[name]) in (int,float),'温度/预算必须是数字');result[name]=float(result[name])
    # 使用真正构造器验证全部值，空请求此处只作构造验证，不写入任务。
    validate_model_options(result)
    return result

def bind_parameters(frozen,options,destination=None,*,summary_memory_sha256=None,deep_review=None):
    request_frozen=frozen
    if deep_review is not None:
        from types import SimpleNamespace
        request_frozen=SimpleNamespace(target=frozen.target,context_text=frozen.context_text,parameters=SimpleNamespace(instruction=frozen.parameters.instruction,deep_review=deep_review))
    if options['adapter_id']=='configured-http-v2':
        from novel_writer.domain.connections import ConnectionDestination
        require(type(destination) is dict,'缺少配置版本与确切去向快照')
        selected=ConnectionDestination(**destination);body=request_body(request_frozen,dict(options,destination=destination));binding=ConfiguredModelBinding(**{k:v for k,v in options.items() if k!='sampling'},**sampling_kwargs(options),destination=selected,request_body=body,request_sha256=request_digest(body,selected))
    else:
        body=request_body(request_frozen,options);binding=ModelBinding(**{k:v for k,v in options.items() if k!='sampling'},**sampling_kwargs(options),request_body=body,request_sha256=digest(body))
    kind=ModelWritingParameters if isinstance(frozen.parameters,WritingParameters) else ModelAnalysisParameters if isinstance(frozen.parameters,AnalysisParameters) else ModelTaskParameters
    extra={'summary_memory_sha256':summary_memory_sha256} if summary_memory_sha256 is not None else {}
    if deep_review is not None:extra['deep_review']=encode(deep_review)
    return parse(kind,{**encode(frozen.parameters),'binding':encode(binding),**extra})

def upgrade(state):
    from novel_writer.application.tasks import upgrade as task_upgrade
    from novel_writer.domain.knowledge import KNOWLEDGE_COLLECTIONS
    task_upgrade(state,'audit_chapter');state['workspace_version']=max(state['workspace_version'],6)
    for name in set(KNOWLEDGE_COLLECTIONS)|set(MODEL_COLLECTIONS):state.setdefault(name,[])

def persist_response(state,task,response,now):
    record=ModelRunRecord(id=str(uuid5(NAMESPACE_URL,task.id+'/'+task.attempt_id+'/response')),project_id=task.project_id,chapter_id=task.chapter_id,task_id=task.id,attempt_id=task.attempt_id,response=response,created_at=now);state['model_results'].append(encode(record));return record

def persist_report(state,task,output,response_id,now):
    report=ModelReport(id=str(uuid5(NAMESPACE_URL,task.id+'/model-report')),project_id=task.project_id,task_id=task.id,response_record_id=response_id,output=output,created_at=now);state['model_reports'].append(encode(report))
    for i,draft in enumerate(output.proposals):state['model_memory_proposals'].append(encode(ModelMemoryProposal(id=str(uuid5(NAMESPACE_URL,report.id+'/proposal/'+str(i))),project_id=task.project_id,report_id=report.id,draft=draft,created_at=now)))
    for i,draft in enumerate(output.bridges):state['model_bridge_proposals'].append(encode(ModelBridgeProposal(id=str(uuid5(NAMESPACE_URL,report.id+'/bridge/'+str(i))),project_id=task.project_id,report_id=report.id,draft=draft,created_at=now)))

def report_task(state,identifier):
    from novel_writer.application.tasks import get_task
    report=next((r for r in state.get('model_reports',[]) if r['id']==identifier),None);require(report is not None,'模型报告不存在或不属于当前书');task=get_task(state,report['task_id']);require(isinstance(task.frozen.parameters,ModelAnalysisParameters),'报告不是模型分析任务');return report,task

def proposal_conflicts(state,draft):
    return [m for m in state.get('memories',[]) if m['active'] and m['kind']==draft['kind'] and m['source']['kind']=='chapter' and m['source']['entity_id']==draft['position_chapter_id'] and m['text']!=draft['text']]

def describe(coordinator,project_id,report_id):
    from novel_writer.application.reviews import is_outdated
    state=coordinator.service.get(project_id);report,task=report_task(state,report_id)
    proposals=[dict(p,receipt=next((r for r in state['model_proposal_receipts'] if r['proposal_id']==p['id']),None),conflicts=proposal_conflicts(state,p['draft'])) for p in state['model_memory_proposals'] if p['report_id']==report_id]
    bridges=[dict(p,receipt=next((r for r in state['model_proposal_receipts'] if r['proposal_id']==p['id']),None)) for p in state['model_bridge_proposals'] if p['report_id']==report_id]
    response=next(r for r in state['model_results'] if r['id']==report['response_record_id'])
    result=dict(revision=state['revision'],report=report,output=report['output'],proposals=proposals,bridges=bridges,outdated=is_outdated(coordinator,state,task),response=response,quality_verified=False)
    if task.frozen.parameters.deep_review is not None:
        from novel_writer.application.deep_reviews import decorate
        return decorate(result,state,task)
    return result

def decide(coordinator,project_id,report_id,request,*,_workflow=None):
    from novel_writer.application.reviews import assert_fresh
    from novel_writer.application.memories import save
    from novel_writer.domain.models import utc_now
    fields={'decision_id','proposal_id','decision','expected_revision','confirm_inference','preserve_conflicts'};check_fields(request,fields);require(set(request)==fields,'模型提案决定字段缺失');identity=uuid_value(request['decision_id']);require(type(request['confirm_inference']) is bool and type(request['preserve_conflicts']) is bool,'作者确认须是明确布尔值');require(request['decision'] in ('accepted','rejected'),'模型提案决定非法')
    def apply(state):
        old=next((r for r in state.get('model_proposal_receipts',[]) if r['id']==identity),None)
        if old is not None:
            require((old['project_id'],old['report_id'],old['proposal_id'],old['decision'],old['confirm_inference'])==(project_id,report_id,request['proposal_id'],request['decision'],request['confirm_inference']),'同一模型提案决定身份绑定其它对象/决定');return None,old
        report,task=report_task(state,report_id);proposal=next((p for p in state['model_memory_proposals']+state['model_bridge_proposals'] if p['id']==request['proposal_id'] and p['report_id']==report_id),None);require(proposal is not None,'模型提案不属于报告');require(not any(r['proposal_id']==proposal['id'] for r in state['model_proposal_receipts']),'提案已有决定，不能换身份重复接受')
        from novel_writer.application.workflow_hooks import owned_task
        require(not owned_task(state,task.id) or _workflow is not None,'工作流模型提案须先经过其人工节点')
        if _workflow is not None:_workflow(state,'before',None)
        require(type(request['expected_revision']) is int and request['expected_revision']==state['revision'],'保存编号变化，请保留输入并核对');memory_id=memory_version=local_id=None
        if request['decision']=='accepted':
            require(request['confirm_inference'],'必须先核对引文/推断并明确确认');assert_fresh(coordinator,state,task);draft=proposal['draft']
            if 'side' in draft:
                from novel_writer.domain.knowledge import ModelLocalEdit
                from novel_writer.application.knowledge import impact
                from novel_writer.domain.tasks import capture_dependency
                evidence=tuple(parse(Evidence,e) for e in draft['evidence']);e=evidence[draft['side']];chapter=next(c for c in state['document']['chapters'] if c['id']==e.chapter_id);before_text=chapter['content'];require(before_text[e.start:e.end]==e.quote,'桥段出处范围已变化');local_id=str(uuid5(NAMESPACE_URL,identity+'/model-local'))
                record=ModelLocalEdit(id=local_id,project_id=project_id,edit_id=str(uuid5(NAMESPACE_URL,identity+'/model-local-edit')),revision=1,issue_id=proposal['id'],model_proposal_id=proposal['id'],side=draft['side'],chapter_id=e.chapter_id,mode='merge' if draft['replacement'] else 'delete',replacement=draft['replacement'],reason='模型桥段建议，待作者核对：'+draft['statement'][:3900],start=e.start,end=e.end,before_text=before_text,after_text=before_text[:e.start]+draft['replacement']+before_text[e.end:],evidence=evidence,guards=tuple(capture_dependency(state,ev.source_kind,ev.entity_id,use='target') for ev in evidence),impact=impact(state,e.chapter_id),created_at=utc_now());state['local_edit_proposals'].append(encode(record))
            else:
                conflicts=proposal_conflicts(state,draft);require(not conflicts or request['preserve_conflicts'],'须明确保留已有不同记忆');before={m['id'] for m in state['memories']};state=save(state,'save_memory',dict(kind=draft['kind'],title=draft['title'],text=draft['text'],position_chapter_id=draft['position_chapter_id'],source=dict(kind='chapter',entity_id=draft['position_chapter_id']),confirmed=True));new=next(m for m in state['memories'] if m['id'] not in before);memory_id=new['id'];memory_version=state['memory_history'][-1]['id']
        receipt=ModelProposalReceipt(id=identity,project_id=project_id,report_id=report_id,proposal_id=proposal['id'],decision=request['decision'],confirm_inference=request['confirm_inference'],memory_id=memory_id,memory_version_id=memory_version,local_proposal_id=local_id,saved_revision=state['revision']+1,created_at=utc_now());state['model_proposal_receipts'].append(encode(receipt))
        if _workflow is not None:_workflow(state,'after',encode(receipt))
        return state,encode(receipt)
    return coordinator.repository.atomic(project_id,apply,identity_claim=('model_proposal_receipts','id',identity))
