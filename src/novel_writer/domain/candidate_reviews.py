"""V35 explicit candidate opinions preserve real producer identity and provenance."""
from dataclasses import dataclass
PROMPT='candidate-review-json-1'

def contains(value):
    if isinstance(value,dict):return value.get('kind')=='model_candidate_audit' or value.get('prompt_version')==PROMPT or any(contains(v) for v in value.values())
    if isinstance(value,(list,tuple)):return any(contains(v) for v in value)
    return False

def upgrade(state):
    if contains(state):
        from novel_writer.application.chapter_lifecycle import upgrade as prior
        prior(state);state['workspace_version']=max(state['workspace_version'],35)

def payload(frozen):
    from novel_writer.domain.tasks import encode
    s=frozen.parameters.upstream
    return dict(instruction=frozen.parameters.instruction,input_origin='candidate',sources=[dict(source_index=0,kind='candidate',version_id=None,text=s.text,**encode(frozen.parameters.wire_source))])

def verify(raw,parameters):
    from novel_writer.storage.json_codec import strict_json_loads
    from novel_writer.domain.tasks import parse,require,digest
    from novel_writer.domain.model_contract import WireFinding,Value
    from novel_writer.domain.workflow_contract import CandidateModelOutput,CandidateModelFinding,CandidateEvidence,validate_candidate_audit
    @dataclass(frozen=True,kw_only=True)
    class Wire(Value):
        overview:str
        findings:tuple[WireFinding,...]
    value=parse(Wire,strict_json_loads(raw));s=parameters.upstream;findings=[]
    require(len(value.overview)<=4000 and len(value.findings)<=40,'候选模型意见超限')
    for f in value.findings:
        require(f.assessment=='model_opinion','候选审核只允许待核实意见');evidence=[]
        for e in f.evidence:
            require(e.source_index==0 and 0<=e.start<e.end<=len(s.text) and s.text[e.start:e.end]==e.quote,'候选引文区间/原文不符')
            evidence.append(CandidateEvidence(source_kind='candidate',entity_id=s.entity_id,task_id=s.producer_task_id,attempt_id=s.producer_attempt_id,producer_node_attempt_id=s.producer_node_attempt_id,version_id=None,start=e.start,end=e.end,quote=e.quote,quote_sha256=digest(e.quote)))
        findings.append(CandidateModelFinding(category=f.category,statement=f.statement,assessment='model_opinion',evidence=tuple(evidence)))
    output=CandidateModelOutput(overview=value.overview,findings=tuple(findings),method='model_candidate_semantic_review_v1');validate_candidate_audit(output,parameters);return output

def require_fresh(coordinator,state,task):
    from novel_writer.domain.workflow_contract import CandidateModelParameters
    if not isinstance(task.frozen.parameters,CandidateModelParameters):return
    from novel_writer.domain.workflows import validate_snapshot
    from novel_writer.application.workflows import require_target
    from novel_writer.application.reviews import assert_fresh
    snapshot=task.frozen.parameters.upstream
    validate_snapshot(state,snapshot);require_target(state,snapshot.saved_target)
    assert_fresh(coordinator,state,task)
