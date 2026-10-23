"""唯一执行协议与registry；本地adapter仅显式注册，默认没有供应商。"""
from dataclasses import dataclass
import threading,time
from novel_writer.domain.tasks import FrozenInput,validate_frozen,require,uuid_value
from novel_writer.domain.review import AnalysisParameters,AuditOutput,validate_output
from novel_writer.domain.model_contract import ExecutionPermit,ProviderResponse,ModelAuditOutput,ModelTaskParameters,ModelAnalysisParameters
from novel_writer.domain.workflow_contract import CandidateAuditParameters,CandidateAuditOutput,CandidateModelParameters,CandidateModelOutput,validate_candidate_audit
from novel_writer.domain.graph_extraction import GraphOutput

class TaskCancelled(RuntimeError):pass
class TaskTimeout(TimeoutError):pass
class WritingLateResponse(RuntimeError):
    def __init__(self,response,kind):self.response,self.kind=response,kind;super().__init__(kind)

@dataclass(frozen=True,kw_only=True)
class AdapterCall:
    task_id:str
    attempt_id:str
    capability:str
    input:FrozenInput
    permission:ExecutionPermit|None=None
    def __post_init__(self):
        uuid_value(self.task_id);uuid_value(self.attempt_id);require(self.capability in ('rewrite_chapter','audit_chapter','draft_chapter','continue_chapter'),'未知执行能力');validate_frozen(self.input)
        from novel_writer.domain.model_contract import ModelWritingParameters
        writing=isinstance(self.input.parameters,ModelWritingParameters)
        require(writing==(self.capability in ('draft_chapter','continue_chapter')),'任务能力与初稿/续写冻结输入不符')
        if writing:require((self.capability=='draft_chapter')==(self.input.parameters.writing.mode=='draft'),'初稿与续写执行能力不能互换')
        if self.permission is not None:
            require(type(self.permission) is ExecutionPermit,'外发确认必须是领域对象');self.permission.__post_init__()

@dataclass(frozen=True,kw_only=True)
class AdapterResult:
    task_id:str
    attempt_id:str
    capability:str
    output_text:str
    complete:bool
    analysis_output:AuditOutput|None=None
    model_response:ProviderResponse|None=None
    model_analysis:ModelAuditOutput|None=None
    candidate_audit_output:CandidateAuditOutput|CandidateModelOutput|None=None
    graph_output:GraphOutput|None=None
    def __post_init__(self):
        uuid_value(self.task_id);uuid_value(self.attempt_id);require(self.capability in ('rewrite_chapter','audit_chapter','draft_chapter','continue_chapter') and type(self.complete) is bool and type(self.output_text) is str,'协议结果字段非法')
        require(self.analysis_output is None or type(self.analysis_output) is AuditOutput,'分析输出必须是领域对象')
        require(self.model_response is None or type(self.model_response) is ProviderResponse,'模型响应必须是领域对象')
        require(self.model_analysis is None or type(self.model_analysis) is ModelAuditOutput,'模型审核必须是领域对象')
        require(self.candidate_audit_output is None or type(self.candidate_audit_output) in (CandidateAuditOutput,CandidateModelOutput),'候选审核必须是领域对象')
        require(self.graph_output is None or type(self.graph_output) is GraphOutput,'图谱抽取必须是领域对象')
        try:self.output_text.encode('utf8',errors='strict')
        except UnicodeError:raise ValueError('协议结果编码非法') from None

class CancellationToken:
    def __init__(self,event,deadline,publish=None):self.event,self.deadline,self._publish=event,deadline,publish
    def publish(self,text):
        self.checkpoint()
        if self._publish is not None:self._publish(text)
    def checkpoint(self):
        if self.event.is_set():raise TaskCancelled('任务已取消或中断')
        if time.monotonic()>=self.deadline:raise TaskTimeout('协议执行超时')

class AdapterRegistry:
    def __init__(self):self._adapters={}
    def register(self,capability,adapter):
        require(capability in ('rewrite_chapter','audit_chapter','draft_chapter','continue_chapter','brainstorm_book','outline_book','brainstorm_chapter','outline_chapter','expand_scene_selection','analyze_style','search_public_sources','read_public_sample','style_trial','review_rule_conflicts','body_planning','semantic_retrieval'),'未知任务能力')
        identity=getattr(adapter,'adapter_id',None);legacy={'local-protocol-demo-v1':('rewrite_chapter',),'offline-audit-rules-v1':('audit_chapter',)}
        declared=getattr(adapter,'capabilities',legacy.get(identity,()))
        entry='run_body_planning' if capability=='body_planning' else 'run_rules' if capability=='review_rule_conflicts' else 'run_trial' if capability=='style_trial' else 'run_web' if capability in ('search_public_sources','read_public_sample') else 'run_style' if capability=='analyze_style' else 'run_book' if capability in ('brainstorm_book','outline_book') else 'run_planning' if capability in ('brainstorm_chapter','outline_chapter') else 'run_expansion' if capability=='expand_scene_selection' else 'run'
        require(type(identity) is str and 0<len(identity)<=100 and type(declared) is tuple and capability in declared and callable(getattr(adapter,entry,None)),'adapter与显式声明能力不符')
        key=(capability,identity);require(key not in self._adapters,'能力/adapter已有注册，禁止静默替换');self._adapters[key]=adapter
    def selected(self,capability,frozen):return getattr(frozen.parameters,'binding',None).adapter_id if hasattr(frozen.parameters,'binding') else getattr(frozen.parameters,'adapter_id',{'rewrite_chapter':'local-protocol-demo-v1','audit_chapter':'offline-audit-rules-v1'}[capability])
    def supports(self,capability,adapter_id=None):return (capability,adapter_id or {'rewrite_chapter':'local-protocol-demo-v1','audit_chapter':'offline-audit-rules-v1'}.get(capability)) in self._adapters
    def freeze_destination(self,capability,options):
        adapter=self._adapters.get((capability,options['adapter_id']))
        require(adapter is not None and callable(getattr(adapter,'freeze_destination',None)),'未注册配置协议能力')
        return adapter.freeze_destination(options)
    def validate_preparation(self,task):
        adapter=self._adapters.get((task.task_type,self.selected(task.task_type,task.frozen)))
        check=getattr(adapter,'validate_preparation',None)
        if check is not None:check(task)
    def validate_options(self,capability,options):
        adapter=self._adapters.get((capability,options['adapter_id']))
        check=getattr(adapter,'validate_options',None)
        if check is not None:check(options)
    def validate_start(self,capability,frozen,confirmation):
        identity=self.selected(capability,frozen);require(self.supports(capability,identity),'任务所选adapter未明确注册')
        if hasattr(frozen.parameters,'binding'):self._adapters[(capability,identity)].validate_start(frozen.parameters.binding,confirmation)
        else:require(confirmation in (None,{}),'本地任务不接受外发确认或任意字段')
    def execute(self,call,token):
        require(type(call) is AdapterCall and type(call.input) is FrozenInput,'不能执行任意字典或伪造输入')
        call.__post_init__()  # 重验构造器被绕过后的根调用身份，adapter之前拒绝。
        validate_frozen(call.input)
        identity=self.selected(call.capability,call.input);require(call.capability in ('rewrite_chapter','audit_chapter','draft_chapter','continue_chapter') and self.supports(call.capability,identity),'真实模型关闭或能力未注册')
        require((call.capability=='audit_chapter')==isinstance(call.input.parameters,(AnalysisParameters,CandidateAuditParameters,CandidateModelParameters)),'能力/冻结参数不符')
        require(type(call.task_id) is str and bool(call.task_id) and type(call.attempt_id) is str and bool(call.attempt_id),'执行身份非法')
        require(type(token) is CancellationToken,'取消令牌非法')
        token.checkpoint();result=self._adapters[(call.capability,identity)].run(call,token)
        try:token.checkpoint()
        except (TaskCancelled,TaskTimeout) as error:
            if call.capability in ('draft_chapter','continue_chapter') and result.model_response is not None:raise WritingLateResponse(result.model_response,'timeout' if isinstance(error,TaskTimeout) else 'cancelled') from None
            raise
        require(type(result) is AdapterResult,'adapter必须返回typed结果')
        require((result.task_id,result.attempt_id,result.capability)==(call.task_id,call.attempt_id,call.capability),'adapter结果归属不符')
        require(type(result.complete) is bool and result.complete,'部分/未完成输出不是候选')
        require(type(result.output_text) is str and bool(result.output_text.strip()) and len(result.output_text)<=call.input.parameters.max_output_chars,'输出为空或超限')
        try:result.output_text.encode('utf8',errors='strict')
        except UnicodeError:raise ValueError('adapter结果编码非法') from None
        if hasattr(call.input.parameters,'binding'):
            require(result.analysis_output is None and result.model_response is not None and result.model_response.complete,'模型任务缺少实际完整供应商响应')
            require(result.output_text==result.model_response.output_text,'模型候选与实际供应商返回不符')
            result.model_response.__post_init__()
            if call.capability=='audit_chapter':
                from novel_writer.domain.model_contract import verify_audit
                if call.input.parameters.binding.prompt_version=='graph-extract-json-1':
                    from novel_writer.domain.graph_extraction import verify
                    require(result.model_analysis is None and result.candidate_audit_output is None and result.graph_output==verify(result.output_text,call.input.parameters),'图谱提案与真实返回/引文不符')
                elif isinstance(call.input.parameters,CandidateModelParameters):
                    from novel_writer.domain.candidate_reviews import verify
                    require(result.model_analysis is None and result.candidate_audit_output==verify(result.output_text,call.input.parameters),'候选模型意见与实际返回不符')
                else:require(result.graph_output is None and result.candidate_audit_output is None and result.model_analysis==verify_audit(result.output_text,call.input.parameters),'模型审核与原始返回/出处不符')
            else:require(result.model_analysis is None,'正文模型任务不能带审核结构')
        elif isinstance(call.input.parameters,CandidateAuditParameters):
            require(result.candidate_audit_output is not None and result.analysis_output is None and result.model_response is None,'候选规则结果能力不符');validate_candidate_audit(result.candidate_audit_output,call.input.parameters)
        elif call.capability=='audit_chapter':
            require(result.analysis_output is not None,'分析任务缺少结构化输出');validate_output(result.analysis_output,call.input.parameters)
        else:require(result.analysis_output is None,'正文任务不能携带分析产物')
        token.checkpoint()
        return result

    def execute_rules(self,task,attempt,confirmed,token):
        from novel_writer.domain.rule_reviews import RuleReviewTask
        require(type(task) is RuleReviewTask and confirmed is True and type(token) is CancellationToken,'rule_reviews.invalid_call')
        from novel_writer.domain.tasks import uuid_value
        task.__post_init__();uuid_value(attempt);token.checkpoint()
        adapter=self._adapters.get(('review_rule_conflicts',task.binding.adapter_id));require(adapter is not None,'rule_reviews.unsupported_adapter')
        response=adapter.run_rules(task,attempt,confirmed,token);require(type(response) is ProviderResponse,'rule_reviews.invalid_response');response.__post_init__();return response

    def execute_semantic(self,task,attempt,confirmed,token):
        from novel_writer.domain.semantic_retrieval import SemanticRetrievalTask
        require(type(task) is SemanticRetrievalTask and confirmed is True and type(token) is CancellationToken,'semantic_retrieval.invalid_call')
        from novel_writer.domain.tasks import uuid_value
        task.__post_init__();uuid_value(attempt);token.checkpoint()
        adapter=self._adapters.get(('semantic_retrieval',task.binding.adapter_id));require(adapter is not None,'semantic_retrieval.unsupported_adapter')
        response=adapter.run_semantic(task,attempt,confirmed,token);require(type(response) is ProviderResponse,'semantic_retrieval.invalid_response');response.__post_init__();return response

    def execute_trial(self,call,token):
        from novel_writer.domain.style_trials import TrialCall
        require(type(call) is TrialCall and type(token) is CancellationToken,'trial.invalid_call');call.__post_init__();token.checkpoint();adapter=self._adapters.get(('style_trial','style-trial-v1'));require(adapter is not None,'trial.unsupported_capability');response=adapter.run_trial(call,token);require(type(response) is ProviderResponse,'trial.invalid_response');response.__post_init__();return response

    def execute_web(self,call,token):
        from novel_writer.domain.public_search import SearchCall,ReadCall,SearchOutcome,FetchOutcome
        require(type(call) in (SearchCall,ReadCall) and type(token) is CancellationToken,'search.invalid_call');call.__post_init__();token.checkpoint();capability='search_public_sources' if type(call) is SearchCall else 'read_public_sample';adapter=self._adapters.get((capability,'grounded-search-v1'));require(adapter is not None,'search.unsupported_capability');result=adapter.run_web(call,token);require(type(result) is (SearchOutcome if type(call) is SearchCall else FetchOutcome),'search.invalid_result');result.__post_init__();return result

    def execute_style(self,call,token):
        from novel_writer.domain.styles import StyleCall
        require(type(call) is StyleCall and type(token) is CancellationToken,'styles.invalid_call');call.__post_init__();token.checkpoint();adapter=self._adapters.get(('analyze_style',call.configuration.adapter_id));require(adapter is not None,'styles.unsupported_capability');response=adapter.run_style(call,token);require(type(response) is ProviderResponse,'styles.invalid_response');response.__post_init__();return response

    def execute_book(self,call,token):
        from novel_writer.domain.book_ai import BookAdapterCall
        require(type(call) is BookAdapterCall and type(token) is CancellationToken,'book_ai.invalid_call');call.__post_init__();token.checkpoint()
        key=(call.capability,call.task.binding.adapter_id);require(key in self._adapters,'book_ai.unsupported_capability');adapter=self._adapters[key]
        require(call.capability in adapter.capabilities and callable(getattr(adapter,'run_book',None)),'book_ai.unsupported_capability')
        response=adapter.run_book(call,token);require(type(response) is ProviderResponse,'book_ai.invalid_response');response.__post_init__();return response

    def execute_planning(self,call,token):
        from novel_writer.domain.chapter_planning import PlanningAdapterCall
        require(type(call) is PlanningAdapterCall and type(token) is CancellationToken,'chapter_planning.invalid_call');call.__post_init__();token.checkpoint()
        key=(call.capability,call.task.binding.adapter_id);require(key in self._adapters,'chapter_planning.unsupported_capability');adapter=self._adapters[key]
        require(call.capability in adapter.capabilities and callable(getattr(adapter,'run_planning',None)),'chapter_planning.unsupported_capability')
        response=adapter.run_planning(call,token);require(type(response) is ProviderResponse,'chapter_planning.invalid_response');response.__post_init__();return response

    def execute_body_planning(self,call,token):
        from novel_writer.domain.model_planning import ModelPlanningCall
        require(type(call) is ModelPlanningCall and type(token) is CancellationToken,'model_planning.invalid_call')
        call.__post_init__();token.checkpoint()
        adapter=self._adapters.get((call.capability,call.task.binding.adapter_id))
        require(adapter is not None and call.capability in adapter.capabilities and callable(getattr(adapter,'run_body_planning',None)), 'model_planning.unsupported_capability')
        response=adapter.run_body_planning(call,token)
        require(type(response) is ProviderResponse,'model_planning.invalid_response');response.__post_init__();return response

    def execute_expansion(self,call,token):
        from novel_writer.domain.scene_expansion import ExpansionAdapterCall
        require(type(call) is ExpansionAdapterCall and type(token) is CancellationToken,'scene_expansion.invalid_call');call.__post_init__();token.checkpoint()
        key=(call.capability,call.task.binding.adapter_id);require(key in self._adapters,'scene_expansion.unsupported_capability');adapter=self._adapters[key]
        require(call.capability in adapter.capabilities and callable(getattr(adapter,'run_expansion',None)),'scene_expansion.unsupported_capability')
        response=adapter.run_expansion(call,token);require(type(response) is ProviderResponse,'scene_expansion.invalid_response');response.__post_init__();return response

class LocalProtocolAdapter:
    adapter_id='local-protocol-demo-v1'
    def __init__(self,*,delay_seconds=.75):self.delay_seconds=delay_seconds
    def run(self,call,token):
        end=time.monotonic()+self.delay_seconds
        while time.monotonic()<end:
            token.checkpoint();token.event.wait(min(.02,max(0,end-time.monotonic())))
        token.checkpoint()
        output='【本地协议验证夹具，不是真实AI输出】\n'+call.input.target.text+'\n本地协议验证已完成；待作者明确采纳。'
        return AdapterResult(task_id=call.task_id,attempt_id=call.attempt_id,capability=call.capability,output_text=output,complete=True)
