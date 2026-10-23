"""工作流传入共享任务的明确原文与生产者绑定，不伪装成保存正文。"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
from novel_writer.domain.model_contract import ModelTaskParameters

class Value:
    def __post_init__(self):
        from novel_writer.domain.tasks import check_types,require,digest
        check_types(type(self),self)
        if isinstance(self,InputSnapshot):
            require(self.text_sha256==digest(self.text) and self.start>=0 and self.end-self.start==len(self.text),'工作流原文快照摘要/范围非法')
            require(self.saved_target.chapter_id==self.chapter_id,'工作流正式目标守卫归属不符')
            if self.kind=='candidate':require(self.version_id is None and self.producer_task_id is not None and self.producer_attempt_id is not None and self.producer_node_attempt_id is not None,'未采纳候选须绑定真实生产者，不能带保存正文版本')
            elif self.kind=='chapter_outline':require(self.version_id is not None and self.start==0 and all(v is None for v in (self.producer_task_id,self.producer_attempt_id,self.producer_node_attempt_id)),'保存章纲须绑定历史版本且无模型生产者')
            else:require(self.version_id==self.saved_target.version_id and self.saved_target.text[self.start:self.end]==self.text,'保存原稿节选不符目标版本')
        elif isinstance(self,CandidateAuditParameters):require(len(self.instruction)<=4000 and 128<=self.max_output_chars<=100000 and 100<=self.timeout_ms<=30000 and len(self.forbidden_literals)<=30 and all(0<len(x)<=100 for x in self.forbidden_literals),'候选规则参数超限')

@dataclass(frozen=True,kw_only=True)
class SavedTarget(Value):
    chapter_id:str
    version_id:str|None
    title:str
    text:str
    status:Literal['draft','confirmed']
    number:int
    source_sha256:str

@dataclass(frozen=True,kw_only=True)
class InputSnapshot(Value):
    kind:Literal['chapter','candidate','chapter_outline']
    project_id:str
    chapter_id:str
    entity_id:str
    version_id:str|None
    producer_task_id:str|None
    producer_attempt_id:str|None
    producer_node_attempt_id:str|None
    via_node_attempt_id:str
    review_id:str|None
    search_node_attempt_id:str|None
    title:str
    text:str
    start:int
    end:int
    text_sha256:str
    feedback:str
    saved_target:SavedTarget

@dataclass(frozen=True,kw_only=True)
class WorkflowModelParameters(ModelTaskParameters):
    upstream:InputSnapshot

@dataclass(frozen=True,kw_only=True)
class CandidateIdentity(Value):
    project_id:str
    entity_id:str
    task_id:str
    attempt_id:str
    producer_node_attempt_id:str
    text_sha256:str
    def __post_init__(self):
        super().__post_init__()
        from uuid import UUID
        from novel_writer.domain.tasks import require
        for name in ('project_id','entity_id','task_id','attempt_id','producer_node_attempt_id'):
            value=getattr(self,name)
            try:valid=str(UUID(value))==value
            except (ValueError,TypeError,AttributeError):valid=False
            require(valid,'候选来源身份必须为真实UUID')
        require(len(self.text_sha256)==64 and all(c in '0123456789abcdef' for c in self.text_sha256),'候选来源摘要非法')

def candidate_identity(snapshot):
    return CandidateIdentity(project_id=snapshot.project_id,entity_id=snapshot.entity_id,task_id=snapshot.producer_task_id,attempt_id=snapshot.producer_attempt_id,producer_node_attempt_id=snapshot.producer_node_attempt_id,text_sha256=snapshot.text_sha256)

@dataclass(frozen=True,kw_only=True)
class CandidateIdentityMap(Value):
    before:CandidateIdentity
    after:CandidateIdentity

@dataclass(frozen=True,kw_only=True)
class CandidateModelParameters(ModelTaskParameters):
    upstream:InputSnapshot
    wire_source:CandidateIdentity
    copy_mappings:tuple[CandidateIdentityMap,...]
    def __post_init__(self):
        super().__post_init__()
        from novel_writer.domain.tasks import require
        require(self.binding.prompt_version=='candidate-review-json-1' and self.upstream.kind=='candidate','候选模型审核提示词或来源非法')
        require(len(self.copy_mappings)<=32,'候选来源复制链超限')
        current=self.wire_source
        for mapping in self.copy_mappings:
            require(mapping.before==current and mapping.before.text_sha256==mapping.after.text_sha256,'候选来源复制链断裂')
            current=mapping.after
        require(current==candidate_identity(self.upstream),'候选来源复制链与本地生产者不符')

@dataclass(frozen=True,kw_only=True)
class CandidateAuditParameters(Value):
    instruction:str
    max_output_chars:int
    timeout_ms:int
    adapter_id:Literal['candidate-offline-audit-v1']
    upstream:InputSnapshot
    forbidden_literals:tuple[str,...]

@dataclass(frozen=True,kw_only=True)
class CandidateEvidence(Value):
    source_kind:Literal['chapter','candidate']
    entity_id:str
    task_id:str|None
    attempt_id:str|None
    producer_node_attempt_id:str|None
    version_id:str|None
    start:int
    end:int
    quote:str
    quote_sha256:str

@dataclass(frozen=True,kw_only=True)
class CandidateFinding(Value):
    rule:Literal['forbidden_literal']
    message:str
    evidence:tuple[CandidateEvidence,...]

@dataclass(frozen=True,kw_only=True)
class CandidateAuditOutput(Value):
    findings:tuple[CandidateFinding,...]
    method:Literal['offline_candidate_literal_rules_v1']

@dataclass(frozen=True,kw_only=True)
class CandidateModelFinding(Value):
    category:Literal['consistency','repetition','quality']
    statement:str
    assessment:Literal['model_opinion']
    evidence:tuple[CandidateEvidence,...]

@dataclass(frozen=True,kw_only=True)
class CandidateModelOutput(Value):
    overview:str
    findings:tuple[CandidateModelFinding,...]
    method:Literal['model_candidate_semantic_review_v1']

@dataclass(frozen=True,kw_only=True)
class WorkflowAudit(Value):
    id:str
    project_id:str
    task_id:str
    node_attempt_id:str
    upstream:InputSnapshot
    output:CandidateAuditOutput|CandidateModelOutput
    created_at:str
    response_record_id:str|None=None

def validate_candidate_audit(output,parameters):
    from novel_writer.domain.tasks import check_types,require,digest
    model=isinstance(parameters,CandidateModelParameters)
    check_types(CandidateModelOutput if model else CandidateAuditOutput,output);s=parameters.upstream;require(len(output.findings)<=(40 if model else 80),'候选审核问题数量超限')
    if model:require(s.kind=='candidate' and len(output.overview)<=4000,'模型候选审核只接受真实候选/有限概览')
    for f in output.findings:
        if model:require(bool(f.statement.strip()) and len(f.statement)<=4000 and 1<=len(f.evidence)<=4,'模型候选意见或引文数量非法')
        for e in f.evidence:
            require((e.source_kind,e.entity_id,e.task_id,e.attempt_id,e.producer_node_attempt_id,e.version_id)==(s.kind,s.entity_id,s.producer_task_id,s.producer_attempt_id,s.producer_node_attempt_id,s.version_id),'候选审核证据冒用保存正文/其它生产者')
            require(0<=e.start<e.end<=len(s.text) and s.text[e.start:e.end]==e.quote and e.quote_sha256==digest(e.quote),'候选引文区间/原文不符')

def feedback_text(output):return '\n'.join((f.statement+'（模型意见待核实）' if isinstance(output,CandidateModelOutput) else f.message)+' '+e.quote for f in output.findings for e in f.evidence)
