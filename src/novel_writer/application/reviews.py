"""审核持久报告、追加处理与原子提案接受；不写正文。"""
from copy import deepcopy
from uuid import uuid4,uuid5,NAMESPACE_URL
from novel_writer.domain.review import *
from novel_writer.domain.tasks import parse,encode,require,uuid_value,capture_dependency,dependency_equal
from novel_writer.domain.models import utc_now,DataValidationError
from novel_writer.storage.sqlite_repository import ConflictError
from novel_writer.application.fields import check_fields,text

def persist_output(state,task,output,now):
    validate_output(output,task.frozen.parameters)
    def identity(name):return str(uuid5(NAMESPACE_URL,task.id+'/'+name))
    report_id=identity('report');issue_ids=[];proposal_ids=[]
    for index,finding in enumerate(output.issues):
        record=ReviewIssue(id=identity('issue/'+str(index)),project_id=task.project_id,report_id=report_id,finding=finding,created_at=now)
        issue_ids.append(record.id);state['review_issues'].append(encode(record))
    for index,draft in enumerate(output.proposals):
        record=MemoryProposal(id=identity('proposal/'+str(index)),project_id=task.project_id,report_id=report_id,proposal=draft,created_at=now)
        proposal_ids.append(record.id);state['memory_proposals'].append(encode(record))
    record=ReviewReport(id=report_id,project_id=task.project_id,task_id=task.id,chapter_id=task.chapter_id,rule_version=task.frozen.parameters.rules.version,method='offline_literal_and_structured_rules',policy_sha256=policy_digest(task.frozen.parameters.rules),previous_report_id=task.frozen.parameters.previous_report_id,issue_ids=tuple(issue_ids),proposal_ids=tuple(proposal_ids),limited=output.limited,limitations=output.limitations,created_at=now)
    state['review_reports'].append(encode(record));return record
def find_report(state,identifier):
    report=next((r for r in state.get('review_reports',[]) if r['id']==identifier),None);require(report is not None,'报告不属于当前书')
    from novel_writer.application.tasks import get_task
    return parse(ReviewReport,report),get_task(state,report['task_id'])
def assert_fresh(coordinator,state,task):
    if task.frozen.context_options.rule_task_id is not None:
        from novel_writer.application.scoped_rules import require_fresh_rules
        require_fresh_rules(state,task)
    from novel_writer.application.deep_reviews import assert_fresh as require_deep_fresh
    require_deep_fresh(state,task)
    from novel_writer.application.semantic_summaries import require_fresh
    require_fresh(state,task)
    from novel_writer.application.semantic_summaries import is_summary
    if is_summary(task):
        try:coordinator.registry.validate_preparation(task)
        except (ValueError,OSError):raise DataValidationError('摘要连接配置已变化或不可用，请重新准备并核对') from None
    for dep in task.frozen.dependencies:
        skill=coordinator.service._skills([dep.entity_id])[0] if dep.kind=='skill' else None
        actual=capture_dependency(state,dep.kind,dep.entity_id,use=dep.use,skill=skill,file_path=dep.file_path)
        require(dependency_equal(dep,actual),'来源/相关规则变化，请重新审核')
def is_outdated(coordinator,state,task):
    try:assert_fresh(coordinator,state,task);return False
    except (DataValidationError,KeyError):return True
def conflicts(state,proposal):
    draft=proposal['proposal'];e=draft['evidence']
    return [m for m in state.get('memories',[]) if m['active'] and m['kind']==draft['kind'] and m['source']['kind']==e['source_kind'] and m['source']['entity_id']==e['entity_id'] and m['text']!=draft['text']]
def recheck_evidence(coordinator,state,report,task):
    children=[r for r in state['review_reports'] if r['previous_report_id']==report.id]
    if not children:return []
    child,new_task=find_report(state,children[-1]['id']);new_params=new_task.frozen.parameters
    new_sources={(s.kind,s.entity_id):s for s in new_params.sources};new_issues=[i for i in state['review_issues'] if i['report_id']==child.id]
    def key(e):return e['source_kind'],e['entity_id'],e['field_path']
    result=[]
    for old in [i for i in state['review_issues'] if i['report_id']==report.id]:
        finding=old['finding'];changes=[];covered=True
        for e in finding['evidence']:
            source=new_sources.get((e['source_kind'],e['entity_id']))
            if source is None:covered=False;continue
            changes.append(dict(source_kind=source.kind,entity_id=source.entity_id,field_path=e['field_path'],previous_version=e['version_id'],new_version=source.version_id,previous_sha256=e['source_sha256'],new_sha256=source.source_sha256,source_revision=source.source_revision))
        changed=any(c['previous_version']!=c['new_version'] or c['previous_sha256']!=c['new_sha256'] for c in changes)
        status='unverified';reason='待核实'
        signature=tuple(WaiverEvidence(source_kind=e['source_kind'],entity_id=e['entity_id'],field_path=e['field_path'],quote_sha256=e['quote_sha256']) for e in finding['evidence'])
        waived=any(w.rule_id==finding['rule_id'] and w.policy_sha256==report.policy_sha256 and w.evidence==signature for w in new_params.waivers)
        matched=None
        for candidate in new_issues:
            nf=candidate['finding']
            if nf['rule_id']!=finding['rule_id'] or [key(e) for e in nf['evidence']]!=[key(e) for e in finding['evidence']]:continue
            if finding['rule_id'] in ('forbidden_literal','duplicate_exact','duplicate_near'):
                if [e['quote_sha256'] for e in nf['evidence']]!=[e['quote_sha256'] for e in finding['evidence']]:continue
            if finding['rule_id']=='missing_literal' and nf['message']!=finding['message']:continue
            matched=candidate;break
        if child.policy_sha256!=report.policy_sha256:reason='规则快照不同，不能声称原问题修复'
        elif not covered:reason='新范围未覆盖原问题所有来源/双侧'
        elif is_outdated(coordinator,state,new_task):reason='最近复审的来源现也已变化，需再次审核'
        elif waived:reason='本次有效白名单/豁免可造成未检出，不能作为修复证据'
        elif matched:status='still_found';reason='同一明确规则/来源位置仍有新报告证据'
        elif child.limited:reason='计算上限使比对不完整，不能判定未检出'
        elif not changed:reason='正文/来源版本未变，重复执行不作为修复证据'
        else:
            locatable=True
            if finding['rule_id']=='timeline_order':
                from novel_writer.application.review_rules import ordinal
                for e in finding['evidence']:
                    parts=e['field_path'].split('.')
                    source=new_sources.get((e['source_kind'],e['entity_id']))
                    previous=next((s for s in task.frozen.parameters.sources if s.kind==e['source_kind'] and s.entity_id==e['entity_id']),None)
                    if len(parts)!=3 or parts[0]!='scenes' or source is None or previous is None:locatable=False;break
                    index=int(parts[1])
                    if index>=len(source.scenes) or index>=len(previous.scenes) or source.scenes[index].order!=previous.scenes[index].order or ordinal(source.scenes[index].story_time) is None:locatable=False;break
            if locatable:status='not_found';reason='来源版本已变化、规则/范围一致且未豁免，本次未检出；不等于已解决或语义无错'
            else:reason='结构位置或时间声明不可比较，不能当成修复'
        result.append(dict(issue_id=old['id'],new_report_id=child.id,new_issue_id=matched['id'] if matched else None,status=status,reason=reason,source_changed=changed,source_changes=changes))
    return result
def describe(coordinator,project_id,report_id):
    state=coordinator.service.get(project_id);report,task=find_report(state,report_id);issues=[];proposals=[]
    for raw in state['review_issues']:
        if raw['report_id']==report_id:
            actions=[a for a in state['review_actions'] if a['issue_id']==raw['id'] and a['kind']!='revoke_waiver']
            issues.append(dict(deepcopy(raw),status=actions[-1]['kind'] if actions else 'open'))
    for raw in state['memory_proposals']:
        if raw['report_id']==report_id:proposals.append(dict(deepcopy(raw),receipt=deepcopy(next((r for r in state['proposal_receipts'] if r['proposal_id']==raw['id']),None)),conflicts=deepcopy(conflicts(state,raw))))
    return dict(report=encode(report),revision=state['revision'],outdated=is_outdated(coordinator,state,task),issues=issues,proposals=proposals,sources=[encode(s) for s in task.frozen.parameters.sources],actions=[deepcopy(a) for a in state['review_actions'] if a['report_id']==report_id],waivers=[deepcopy(w) for w in state['rule_waivers'] if w['report_id']==report_id],parameters=encode(task.frozen.parameters),rechecks=recheck_evidence(coordinator,state,report,task))
def review_issue(coordinator,project_id,report_id,request):
    check_fields(request,{'operation_id','issue_id','kind','reason','whitelist','expected_revision','waiver_id'})
    require({'operation_id','issue_id','kind','reason','whitelist','expected_revision'}<=set(request),'处理参数缺失')
    identity=uuid_value(request['operation_id']);reason=text(request['reason'],'理由')
    require(len(reason)<=4000 and type(request['whitelist']) is bool and type(request['expected_revision']) is int,'处理参数非法')
    require(request['kind'] in ('acknowledge','false_positive','waive','reopen','revoke_waiver'),'未知处理')
    if request['kind'] in ('false_positive','waive','revoke_waiver'):require(bool(reason.strip()),'误报/豁免/白名单变更须理由')
    def operation(state):
        old=next((a for a in state.get('review_actions',[]) if a['id']==identity),None)
        if old:
            require((old['report_id'],old['issue_id'],old['kind'],old['reason'],old['whitelist'])==(report_id,request['issue_id'],request['kind'],reason,request['whitelist']),'同一身份绑定不同处理')
            if request['kind']=='revoke_waiver':require(old['waiver_id']==request.get('waiver_id'),'不同白名单')
            return None,deepcopy(old)
        report,task=find_report(state,report_id)
        if state['revision']!=request['expected_revision']:raise ConflictError('保存编号变化，请保留输入重新核对')
        issue=next((i for i in state['review_issues'] if i['id']==request['issue_id'] and i['report_id']==report_id),None);require(issue is not None,'问题不属于报告')
        if request['kind'] not in ('revoke_waiver','reopen'):assert_fresh(coordinator,state,task)
        now=utc_now();waiver_id=None
        if request['kind']=='revoke_waiver':
            waiver_id=request.get('waiver_id');require(any(w['id']==waiver_id and w['issue_id']==issue['id'] for w in state['rule_waivers']),'白名单归属错误')
        elif request['whitelist']:
            require(request['kind'] in ('false_positive','waive'),'仅明确误报/豁免可白名单')
            finding=parse(DetectedIssue,issue['finding']);waiver_id=str(uuid4())
            waiver=RuleWaiver(id=waiver_id,project_id=project_id,report_id=report_id,issue_id=issue['id'],rule_id=finding.rule_id,policy_sha256=report.policy_sha256,evidence=tuple(WaiverEvidence(source_kind=e.source_kind,entity_id=e.entity_id,field_path=e.field_path,quote_sha256=e.quote_sha256) for e in finding.evidence),reason=reason,created_at=now)
            state['rule_waivers'].append(encode(waiver))
        action=ReviewAction(id=identity,project_id=project_id,report_id=report_id,issue_id=issue['id'],waiver_id=waiver_id,kind=request['kind'],reason=reason,whitelist=request['whitelist'],created_at=now)
        state['review_actions'].append(encode(action));return state,encode(action)
    return coordinator.repository.atomic(project_id,operation,identity_claim=('review_actions','id',identity))
def decide_proposal(coordinator,project_id,report_id,request):
    check_fields(request,{'decision_id','proposal_id','decision','expected_revision','confirmed','preserve_conflicts'})
    require(set(request)=={'decision_id','proposal_id','decision','expected_revision','confirmed','preserve_conflicts'},'提案参数缺失')
    identity=uuid_value(request['decision_id']);require(request['decision'] in ('accepted','rejected') and type(request['confirmed']) is bool and type(request['preserve_conflicts']) is bool and type(request['expected_revision']) is int,'提案决定非法')
    def operation(state):
        old=next((r for r in state.get('proposal_receipts',[]) if r['id']==identity),None)
        if old:
            require((old['report_id'],old['proposal_id'],old['decision'],old['confirmed'])==(report_id,request['proposal_id'],request['decision'],request['confirmed']),'同一身份绑定不同提案')
            return None,deepcopy(old)
        report,task=find_report(state,report_id)
        if state['revision']!=request['expected_revision']:raise ConflictError('保存编号变化，请保留输入重新核对')
        proposal=next((p for p in state['memory_proposals'] if p['id']==request['proposal_id'] and p['report_id']==report_id),None);require(proposal is not None,'提案归属错误')
        require(not any(r['proposal_id']==proposal['id'] for r in state['proposal_receipts']),'提案已有决定，请查看原收据或准备复审')
        memory_id=edit_id=None;conflicting=[]
        if request['decision']=='accepted':
            assert_fresh(coordinator,state,task);draft=parse(ProposalDraft,proposal['proposal']);require(draft.evidence.source_kind=='chapter','规划不能转换成事实记忆')
            conflicting=conflicts(state,proposal);require(not conflicting or request['preserve_conflicts'],'请确认保留现有不同记忆后新增')
            from novel_writer.application.memories import save
            state=save(state,'save_memory',dict(kind=draft.kind,title=draft.title,text=draft.text,position_chapter_id=draft.position_chapter_id,confirmed=request['confirmed'],active=True,source={'kind':draft.evidence.source_kind,'entity_id':draft.evidence.entity_id}))
            memory_id=state['memories'][-1]['id'];edit_id=state['memory_history'][-1]['id']
        receipt=ProposalReceipt(id=identity,project_id=project_id,report_id=report_id,proposal_id=proposal['id'],decision=request['decision'],memory_id=memory_id,memory_version_id=edit_id,conflict_memory_ids=tuple(m['id'] for m in conflicting),requested_revision=request['expected_revision'],applied_revision=state['revision']+1,confirmed=request['confirmed'],created_at=utc_now())
        state['proposal_receipts'].append(encode(receipt));return state,encode(receipt)
    return coordinator.repository.atomic(project_id,operation,identity_claim=('proposal_receipts','id',identity))
