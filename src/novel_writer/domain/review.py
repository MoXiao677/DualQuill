"""V4离线审核/证据/提案契约；冻结结构，不以字面规则冒充语义。"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
from hashlib import sha256
from novel_writer.domain.models import DataValidationError,_timestamp
from novel_writer.domain.memory import fingerprint

class ReviewValue:
    def __post_init__(self):
        from novel_writer.domain.tasks import check_types,require,uuid_value
        check_types(type(self),self)
        if isinstance(self,AuditRules):
            require(len(self.forbidden_literals)<=30 and len(self.required_literals)<=30,'字面规则过多')
            require(all(0<len(t)<=100 for t in self.forbidden_literals+self.required_literals),'字面规则词为空或超限')
            require(.65<=self.near_threshold<=1 and 12<=self.minimum_fragment_chars<=200,'查重阈值/最短长度非法')
        elif isinstance(self,SceneSnapshot):require(self.order>=1,'冻结场景顺序非法')
        elif isinstance(self,AuditSource):
            require(bool(self.project_id) and bool(self.entity_id) and bool(self.chapter_id) and self.chapter_number>=1 and self.source_revision>=1,'审核来源身份/位置非法')
            require(self.source_sha256==fingerprint(source_value(self)),'审核来源快照指纹不符')
            if self.kind=='chapter':require(self.status in ('draft','confirmed') and not self.scenes and not self.character_ids,'正文来源快照非法')
            else:require(self.status in ('draft','ready') and self.text==outline_text(self.core_idea,self.objective,self.story_time,self.scenes),'规划来源快照非法')
        elif isinstance(self,Evidence):require(self.start>=0 and self.end>=self.start and self.quote_sha256==text_digest(self.quote),'证据范围/原文指纹非法')
        elif isinstance(self,(AnalysisParameters,AnalysisRequest)):
            require(len(self.instruction)<=4000 and 128<=self.max_output_chars<=100000 and 100<=self.timeout_ms<=300000,'审核任务参数非法')
            require(0<len(self.selected_chapter_ids)<=40 and len(self.selected_chapter_ids)==len(set(self.selected_chapter_ids)),'审核章范围非法')
            if self.previous_report_id is not None:uuid_value(self.previous_report_id)
            if isinstance(self,AnalysisParameters):
                require(0<len(self.sources)<=80 and sum(len(s.text) for s in self.sources)<=200000,'审核范围超过20万字符，请缩小范围')
                require({s.chapter_id for s in self.sources}<=set(self.selected_chapter_ids),'审核来源越界')
        elif isinstance(self,DetectedIssue):require(len(self.evidence) in (1,2) and (self.score is None or 0<=self.score<=1),'问题证据/分数非法')
        elif isinstance(self,ProposalDraft):require(self.text==self.evidence.quote and bool(self.text.strip()),'提案必须是原文/声明字段摘录')
        elif isinstance(self,AuditOutput):require(len(self.issues)<=80 and len(self.proposals)<=80,'审核输出数量超限')
        elif isinstance(self,WaiverEvidence):require(len(self.quote_sha256)==64,'白名单原文摘要非法')
        else:
            uuid_value(self.id)
            if hasattr(self,'created_at'):_timestamp(self.created_at,'review.created_at')

@dataclass(frozen=True,kw_only=True)
class AuditRules(ReviewValue):
    version:Literal['offline-audit-1']
    forbidden_literals:tuple[str,...]
    required_literals:tuple[str,...]
    normalization:Literal['whitespace','punctuation']
    near_threshold:float
    minimum_fragment_chars:int
    check_timeline:bool
@dataclass(frozen=True,kw_only=True)
class SceneSnapshot(ReviewValue):
    order:int
    summary:str
    character_ids:tuple[str,...]
    location:str
    story_time:str
@dataclass(frozen=True,kw_only=True)
class AuditSource(ReviewValue):
    project_id:str
    kind:Literal['chapter','chapter_outline']
    entity_id:str
    chapter_id:str
    chapter_number:int
    source_revision:int
    version_id:str|None
    source_sha256:str
    title:str
    text:str
    status:Literal['draft','confirmed','ready']
    core_idea:str
    objective:str
    story_time:str
    character_ids:tuple[str,...]
    scenes:tuple[SceneSnapshot,...]
@dataclass(frozen=True,kw_only=True)
class Evidence(ReviewValue):
    source_kind:Literal['chapter','chapter_outline']
    entity_id:str
    chapter_id:str
    source_revision:int
    version_id:str|None
    source_sha256:str
    field_path:str
    start:int
    end:int
    quote:str
    quote_sha256:str
@dataclass(frozen=True,kw_only=True)
class WaiverEvidence(ReviewValue):
    source_kind:Literal['chapter','chapter_outline']
    entity_id:str
    field_path:str
    quote_sha256:str
@dataclass(frozen=True,kw_only=True)
class RuleWaiver(ReviewValue):
    id:str
    project_id:str
    report_id:str
    issue_id:str
    rule_id:str
    policy_sha256:str
    evidence:tuple[WaiverEvidence,...]
    reason:str
    created_at:str
@dataclass(frozen=True,kw_only=True)
class AnalysisParameters(ReviewValue):
    instruction:str
    max_output_chars:int
    timeout_ms:int
    rules:AuditRules
    selected_chapter_ids:tuple[str,...]
    previous_report_id:str|None
    sources:tuple[AuditSource,...]
    waivers:tuple[RuleWaiver,...]
@dataclass(frozen=True,kw_only=True)
class AnalysisRequest(ReviewValue):
    instruction:str
    max_output_chars:int
    timeout_ms:int
    rules:AuditRules
    selected_chapter_ids:tuple[str,...]
    previous_report_id:str|None
@dataclass(frozen=True,kw_only=True)
class DetectedIssue(ReviewValue):
    rule_id:Literal['forbidden_literal','missing_literal','timeline_order','duplicate_exact','duplicate_near']
    severity:Literal['error','warning']
    message:str
    evidence:tuple[Evidence,...]
    score:float|None
@dataclass(frozen=True,kw_only=True)
class ProposalDraft(ReviewValue):
    kind:Literal['chapter_summary']
    title:str
    text:str
    position_chapter_id:str
    evidence:Evidence
    method:Literal['verbatim_excerpt']
@dataclass(frozen=True,kw_only=True)
class AuditOutput(ReviewValue):
    issues:tuple[DetectedIssue,...]
    proposals:tuple[ProposalDraft,...]
    limited:bool
    limitations:tuple[str,...]
@dataclass(frozen=True,kw_only=True)
class ReviewReport(ReviewValue):
    id:str
    project_id:str
    task_id:str
    chapter_id:str
    rule_version:Literal['offline-audit-1']
    method:Literal['offline_literal_and_structured_rules']
    policy_sha256:str
    previous_report_id:str|None
    issue_ids:tuple[str,...]
    proposal_ids:tuple[str,...]
    limited:bool
    limitations:tuple[str,...]
    created_at:str
@dataclass(frozen=True,kw_only=True)
class ReviewIssue(ReviewValue):
    id:str
    project_id:str
    report_id:str
    finding:DetectedIssue
    created_at:str
@dataclass(frozen=True,kw_only=True)
class MemoryProposal(ReviewValue):
    id:str
    project_id:str
    report_id:str
    proposal:ProposalDraft
    created_at:str
@dataclass(frozen=True,kw_only=True)
class ReviewAction(ReviewValue):
    id:str
    project_id:str
    report_id:str
    issue_id:str|None
    waiver_id:str|None
    kind:Literal['acknowledge','false_positive','waive','reopen','revoke_waiver']
    reason:str
    whitelist:bool
    created_at:str
@dataclass(frozen=True,kw_only=True)
class ProposalReceipt(ReviewValue):
    id:str
    project_id:str
    report_id:str
    proposal_id:str
    decision:Literal['accepted','rejected']
    memory_id:str|None
    memory_version_id:str|None
    conflict_memory_ids:tuple[str,...]
    requested_revision:int
    applied_revision:int
    confirmed:bool
    created_at:str

REVIEW_COLLECTIONS={'review_reports':ReviewReport,'review_issues':ReviewIssue,'memory_proposals':MemoryProposal,'review_actions':ReviewAction,'proposal_receipts':ProposalReceipt,'rule_waivers':RuleWaiver}
def text_digest(value):return sha256(value.encode('utf8')).hexdigest()
def source_value(source):
    from novel_writer.domain.tasks import encode
    if source.kind=='chapter':return dict(number=source.chapter_number,title=source.title,content=source.text,status=source.status)
    return dict(chapter_id=source.chapter_id,core_idea=source.core_idea,objective=source.objective,story_time=source.story_time,status=source.status,character_ids=list(source.character_ids),scenes=[encode(s) for s in source.scenes])
def outline_text(core,objective,story_time,scenes):
    return outline_layout(core,objective,story_time,scenes)[0]
def outline_layout(core,objective,story_time,scenes):
    text='';locations={}
    def add(prefix,value,path):
        nonlocal text
        start=len(text)+len(prefix);text+=prefix+value+'\n';locations[path]=(start,start+len(value))
    add('核心情节：',core,'core_idea');add('本章目标：',objective,'objective');add('剧情时间：',story_time,'story_time')
    for index,scene in enumerate(scenes):
        add(f'场景{scene.order} · 剧情时间：',scene.story_time,f'scenes.{index}.story_time')
        add('',scene.summary,f'scenes.{index}.summary');add('地点：',scene.location,f'scenes.{index}.location')
    return text,locations
def policy_digest(rules):
    from novel_writer.domain.tasks import encode
    import json
    return text_digest(json.dumps(encode(rules),ensure_ascii=False,sort_keys=True,separators=(',',':')))
def validate_evidence(evidence,sources):
    from novel_writer.domain.tasks import require
    source=next((s for s in sources if s.kind==evidence.source_kind and s.entity_id==evidence.entity_id),None)
    require(source is not None,'证据来源悬空')
    require((evidence.chapter_id,evidence.source_revision,evidence.version_id,evidence.source_sha256)==(source.chapter_id,source.source_revision,source.version_id,source.source_sha256),'证据版本/归属不符')
    require(evidence.end<=len(source.text) and source.text[evidence.start:evidence.end]==evidence.quote,'证据不是冻结原文范围')
    if source.kind=='chapter':require(evidence.field_path=='content','正文证据字段非法')
    else:
        locations=outline_layout(source.core_idea,source.objective,source.story_time,source.scenes)[1]
        require(locations.get(evidence.field_path)==(evidence.start,evidence.end),'证据位置不对应所声明的结构字段')
def validate_output(output,parameters):
    from novel_writer.domain.tasks import check_types,require
    check_types(AuditOutput,output)
    for issue in output.issues:
        for evidence in issue.evidence:validate_evidence(evidence,parameters.sources)
    for proposal in output.proposals:
        validate_evidence(proposal.evidence,parameters.sources)
        require(proposal.position_chapter_id==proposal.evidence.chapter_id and proposal.text==proposal.evidence.quote,'提案不是有出处摘录')

def validate_review_state(state):
    from novel_writer.domain.tasks import parse,require,uuid_value,GenerationTask,encode
    parsed={}
    for name,model in REVIEW_COLLECTIONS.items():
        require(type(state[name]) is list and len(state[name])<=100000,'审核集合非法/超限')
        parsed[name]=[parse(model,v) for v in state[name]];require(len({v.id for v in parsed[name]})==len(parsed[name]),'审核集合ID重复')
        for value in parsed[name]:require(value.project_id==state['document']['project']['id'],'审核对象跨书')
    tasks={t['id']:parse(GenerationTask,t) for t in state.get('generation_tasks',[])};reports={r.id:r for r in parsed['review_reports']};issues={i.id:i for i in parsed['review_issues']};proposals={p.id:p for p in parsed['memory_proposals']};waivers={w.id:w for w in parsed['rule_waivers']}
    for report in reports.values():
        require(report.task_id in tasks,'报告任务悬空');task=tasks[report.task_id]
        require(task.task_type=='audit_chapter' and task.status=='succeeded' and report.chapter_id==task.chapter_id and report.created_at==task.finished_at,'分析报告没有对应成功任务')
        require(isinstance(task.frozen.parameters,AnalysisParameters) and report.policy_sha256==policy_digest(task.frozen.parameters.rules),'报告规则版本不符')
        if report.previous_report_id is not None:require(report.previous_report_id in reports and report.previous_report_id!=report.id,'复审报告链非法')
        require(set(report.issue_ids)=={i.id for i in issues.values() if i.report_id==report.id} and set(report.proposal_ids)=={p.id for p in proposals.values() if p.report_id==report.id},'报告对象清单不完整')
    for issue in issues.values():
        require(issue.report_id in reports,'问题报告悬空')
        for e in issue.finding.evidence:validate_evidence(e,tasks[reports[issue.report_id].task_id].frozen.parameters.sources)
    for proposal in proposals.values():
        require(proposal.report_id in reports,'提案报告悬空');validate_evidence(proposal.proposal.evidence,tasks[reports[proposal.report_id].task_id].frozen.parameters.sources)
    for action in parsed['review_actions']:
        require(action.report_id in reports,'处理报告悬空')
        if action.kind=='revoke_waiver':require(action.waiver_id in waivers,'白名单处理悬空')
        else:require(action.issue_id in issues and issues[action.issue_id].report_id==action.report_id,'处理问题不属于报告')
    seen=set();memories={m['id']:m for m in state.get('memories',[])};edits={h['id']:h for h in state.get('memory_history',[])}
    for receipt in parsed['proposal_receipts']:
        require(receipt.proposal_id in proposals and proposals[receipt.proposal_id].report_id==receipt.report_id and receipt.proposal_id not in seen,'提案重复处理或归属不符');seen.add(receipt.proposal_id)
        require(1<=receipt.requested_revision<receipt.applied_revision<=state['revision'],'提案收据revision非法')
        if receipt.decision=='accepted':
            require(receipt.memory_id in memories and receipt.memory_version_id in edits,'提案接受缺少记忆/版本')
            snapshot=edits[receipt.memory_version_id]['snapshot'];require(snapshot['id']==receipt.memory_id and snapshot['text']==proposals[receipt.proposal_id].proposal.text,'提案与原始记忆写入不符')
        else:require(receipt.memory_id is None and receipt.memory_version_id is None,'拒绝提案不能新增记忆')
    for waiver in waivers.values():require(waiver.issue_id in issues and issues[waiver.issue_id].report_id==waiver.report_id and waiver.rule_id==issues[waiver.issue_id].finding.rule_id,'白名单来源不符')
    return parsed
