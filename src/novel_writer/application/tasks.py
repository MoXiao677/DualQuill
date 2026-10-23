"""唯一持久task coordinator。adapter选择不改变执行/取消/结果/采纳管线。"""
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4
import threading,time
from novel_writer.domain.models import DataValidationError,utc_now
from novel_writer.domain.tasks import (FrozenInput,ContextOptions,TaskParameters,GenerationTask,Candidate,TaskEvent,AdoptionReceipt,
    COLLECTIONS,parse,encode,require,uuid_value,digest,capture_dependency,dependency_equal)
from novel_writer.application.fields import check_fields
from novel_writer.application.task_protocol import AdapterCall,CancellationToken,TaskCancelled,TaskTimeout
from novel_writer.storage.sqlite_repository import ConflictError
from novel_writer.storage.json_codec import document_from_dict,document_to_dict
from novel_writer.application import chapters

def upgrade(state,capability='rewrite_chapter'):
    if capability in ('draft_chapter','continue_chapter'):
        from novel_writer.application.style_trials import upgrade as prior
        from novel_writer.domain.chapter_writing import COLLECTIONS as WRITING_COLLECTIONS
        prior(state);state['workspace_version']=max(state['workspace_version'],16)
        for name in WRITING_COLLECTIONS:state.setdefault(name,[])
        return state
    state['workspace_version']=max(state['workspace_version'],4 if capability=='audit_chapter' else 3);state.setdefault('memories',[]);state.setdefault('memory_history',[])
    for name in COLLECTIONS:state.setdefault(name,[])
    if state['workspace_version']>=4:
        from novel_writer.domain.review import REVIEW_COLLECTIONS
        for name in REVIEW_COLLECTIONS:state.setdefault(name,[])
    return state

def context_options(raw):
    defaults=dict(scope='previous',budget_chars=6000,include_current_plan=False,include_book_outline=False,include_characters=False,
        character_ids=[],include_worldbuilding=False,include_writing_rules=False,include_memories=False,memory_ids=[],include_search_results=False,search_selections=[],include_memory_rollups=False,rule_task_id=None,include_automatic_memories=False)
    check_fields(raw,set(defaults)|{'chapter_id','retrieval_owner'})
    if raw.get('retrieval_owner') is not None:uuid_value(raw['retrieval_owner'])
    # Composition may carry frozen options, but a prior process owner is data,
    # never authorization for a new preparation. _preparer binds its own owner.
    clean={key:deepcopy(value) for key,value in raw.items() if key!='retrieval_owner'}
    return parse(ContextOptions,{**defaults,**clean})

def get_task(state,identifier):
    task=next((t for t in state.get('generation_tasks',[]) if t['id']==identifier),None)
    if task is None:raise DataValidationError('任务不存在或不属于当前书')
    return parse(GenerationTask,task)

def put_task(state,task):
    state['generation_tasks']=[encode(task) if t['id']==task.id else t for t in state['generation_tasks']]

def require_fresh_rollups(state,task):
    # New excerpt/material selections must be checked even when no saved rollup
    # was selected. Freeze revision only for comparing identity, never content.
    selected=task.frozen.context_options.search_selections
    if any(s.excerpt is not None or s.kind=='material' for s in selected):
        from novel_writer.application.context_preview import preview
        report=preview(dict(state,revision=task.frozen.source_revision),encode(task.frozen.context_options),skills=encode(task.frozen.skill_snapshots))
        require(digest(report['context_text'])==task.frozen.context_sha256,'检索引文或来源时效已变化，请重新准备')
        for dep in task.frozen.dependencies:
            if dep.kind=='material':require(dependency_equal(dep,capture_dependency(state,dep.kind,dep.entity_id,use=dep.use)) and dep.memory_fresh is True,'检索资料版本、归档或索引已变化')
    dependencies=[d for d in task.frozen.dependencies if d.kind=='memory_rollup']
    if not (task.frozen.context_options.include_memory_rollups or task.frozen.context_options.include_automatic_memories):return
    for dep in dependencies:
        actual=capture_dependency(state,dep.kind,dep.entity_id,use=dep.use)
        require(actual.memory_fresh is True and dependency_equal(dep,actual),'汇总或其来源已变化，请重新预览和冻结请求')
    from novel_writer.application.context_preview import preview
    report=preview(dict(state,revision=task.frozen.source_revision),encode(task.frozen.context_options),skills=encode(task.frozen.skill_snapshots))
    require(digest(report['context_text'])==task.frozen.context_sha256,'汇总上下文范围或来源已变化，请重新准备')


def event(state,task,kind,*,now=None,candidate_id=None,adoption_id=None,error_code=None,attempt_id=None,owner_id=None):
    now=now or utc_now();events=[e for e in state['task_events'] if e['task_id']==task.id]
    status={'prepared':'pending','started':'running','adopted':'succeeded'}.get(kind,kind)
    attempt_id=attempt_id if attempt_id is not None else task.attempt_id;owner_id=owner_id if owner_id is not None else task.owner_id
    candidate_id=candidate_id if candidate_id is not None else task.candidate_id
    entry=TaskEvent(id=str(uuid4()),task_id=task.id,seq=len(events)+1,previous_event_id=events[-1]['id'] if events else None,
        kind=kind,from_status=events[-1]['status'] if events else None,status=status,attempt_id=attempt_id,owner_id=owner_id,
        candidate_id=candidate_id,adoption_id=adoption_id,created_at=now,error_code=error_code)
    state['task_events'].append(encode(entry))
    updated=replace(task,status=status,attempt_id=attempt_id,owner_id=owner_id,candidate_id=candidate_id,updated_at=now,error_code=error_code,
        started_at=now if kind=='started' else task.started_at,
        finished_at=now if kind in ('succeeded','failed','cancelled','interrupted') else task.finished_at)
    put_task(state,updated);return updated

class SharedExecutionSlot:
    """Keep existing producers in the same admission domain as workflows."""
    def __init__(self,coordinator):
        self.coordinator=coordinator
        self.condition=threading.Condition(coordinator.lock)
        self.identity=object()

    def acquire(self,blocking=True,timeout=None):
        with self.condition:
            claims=self.coordinator.execution_claims
            if claims:
                if not blocking:return False
                if not self.condition.wait_for(lambda:not claims,timeout):return False
            claims[self.identity]=(None,1)
            return True

    def release(self):
        with self.condition:
            if self.identity not in self.coordinator.execution_claims:
                raise ValueError('Execution slot released without acquisition')
            del self.coordinator.execution_claims[self.identity]
            self.condition.notify_all()

class TaskCoordinator:
    def __init__(self,service,registry):
        self.service=service;self.repository=service.repository;self.registry=registry;self.owner_id=str(uuid4())
        self.lock=threading.Lock();self.active={};self.execution_claims={};self.closed=threading.Event()
        self.slot=SharedExecutionSlot(self)

    def _claim_execution(self,task_id,group,limit):
        with self.lock:
            require(task_id not in self.execution_claims,'此任务已占用执行名额')
            claims=list(self.execution_claims.values())
            require(not claims or (group is not None and all(g==group for g,_ in claims)
                    and len(claims)<min([limit]+[n for _,n in claims])), '已有本地协议执行占用名额或达到本次有界并行上限')
            self.execution_claims[task_id]=(group,limit)

    def _release_execution(self,task_id):
        with self.slot.condition:
            self.execution_claims.pop(task_id,None)
            self.slot.condition.notify_all()

    def prepare(self,project_id,request):
        operation,identity=self._preparer(project_id,request)
        return self.repository.atomic(project_id,operation,identity_claim=('generation_tasks','request_id',identity))

    def _preparer(self,project_id,request):
        """可信组合业务复用同一冻结/事件逻辑；本身不提交事务或执行请求。"""
        fields={'request_id','chapter_id','task_type','context_options','context_sha256','parameters','expected_revision'}
        check_fields(request,fields|{'model_options','deep_review'});require(fields<=set(request),'准备任务参数缺失')
        model_options=None
        if 'model_options' in request:
            from novel_writer.application.model_reviews import canonical_options
            model_options=canonical_options(request['model_options'])
            require(model_options['prompt_version']!='rule-conflicts-json-1','规则语义审核须使用专用只读入口')
            self.registry.validate_options(request['task_type'],model_options)
        identity=uuid_value(request['request_id']);require(request['task_type'] in ('rewrite_chapter','audit_chapter','draft_chapter','continue_chapter'),'未知任务能力')
        writing=request['task_type'] in ('draft_chapter','continue_chapter')
        options=context_options(request['context_options'])
        if options.rule_task_id is not None:
            require(options.rule_task_id==identity,'不能使用其他任务的规则绑定')
        if any(s.excerpt is not None or s.kind=='material' for s in options.search_selections):options=replace(options,retrieval_owner=self.owner_id)
        graph=model_options is not None and model_options['prompt_version']=='graph-extract-json-1'
        summary=model_options is not None and model_options['prompt_version'] in ('chapter-summary-json-1','graph-extract-json-1')
        if summary:require(options.rule_task_id is None,'单章摘要只接受已保存正文，不支持任务规则绑定')
        deep=model_options is not None and model_options['prompt_version']=='deep-review-json-1'
        require(deep==('deep_review' in request),'深层审核须有明确冻结范围及专用提示词')
        if deep:
            from novel_writer.application.deep_reviews import canonical_selection
            canonical_selection(request['deep_review'])
            require(request['task_type']=='audit_chapter' and not any((options.include_current_plan,options.include_book_outline,options.include_characters,options.include_worldbuilding,options.include_writing_rules,options.include_memories,options.include_search_results,options.include_memory_rollups,options.include_automatic_memories)) and not options.character_ids and not options.memory_ids and not options.search_selections,'深层审核只允许显式选择来源')
        if deep:require(options.rule_task_id is None,'深层审核只接受显式来源范围，不支持任务规则绑定')
        if summary:require(request['task_type']=='audit_chapter' and not any((options.include_current_plan,options.include_book_outline,options.include_characters,options.include_worldbuilding,options.include_writing_rules,options.include_memories,options.include_search_results,options.include_memory_rollups,options.include_automatic_memories)) and not options.character_ids and not options.memory_ids and not options.search_selections,'单章摘要只允许已保存的唯一目标正文')
        if request['task_type']=='audit_chapter':
            from novel_writer.application.review_rules import canonical_request
            request=deepcopy(request);request['parameters']=canonical_request(request['parameters'])
        from novel_writer.domain.model_contract import WritingParameters
        parameters=parse(WritingParameters if writing else TaskParameters,request['parameters']) if request['task_type']!='audit_chapter' else None
        if writing:require(model_options is not None,'初稿/续写必须明确配置实际模型')
        require(type(request['expected_revision']) is int and request['expected_revision']>=1,'准备保存编号非法')
        require(request['chapter_id']==options.chapter_id,'写作章与上下文章不一致')
        def operation(state):
            nonlocal parameters
            if any(v['id']==identity for v in state.get('rule_task_bindings',[])):
                require(options.rule_task_id==identity,'已绑定任务规则不能在冻结时省略')
            existing=next((t for t in state.get('generation_tasks',[]) if t['request_id']==identity),None)
            if existing:
                t=parse(GenerationTask,existing)
                saved_params=encode(t.frozen.parameters);saved_binding=saved_params.pop('binding',None)
                same_model=(saved_binding is None and model_options is None) or (saved_binding is not None and model_options is not None and {k:v for k,v in saved_binding.items() if k not in ('request_body','request_sha256','destination')}==model_options)
                same_params=saved_params==encode(parameters) if parameters is not None else {k:v for k,v in saved_params.items() if k not in ('sources','waivers','summary_memory_sha256','deep_review')}==request['parameters']
                if deep:
                    from novel_writer.application.deep_reviews import selection_from_scope
                    same_params=same_params and selection_from_scope(t.frozen.parameters.deep_review)==request['deep_review']
                require(t.chapter_id==request['chapter_id'] and t.task_type==request['task_type'] and t.frozen.context_options==options and same_params
                    and same_model and t.frozen.context_sha256==request['context_sha256'] and t.frozen.source_revision==request['expected_revision'],'同一准备身份对应不同输入')
                return None,dict(task=existing,revision=state['revision'])
            if state['revision']!=request['expected_revision'] and not writing:raise ConflictError('已保存资料变化，请重新预览后准备任务')
            if writing:self.writing.assert_spec(state,parameters.writing,options)
            if request['task_type']=='audit_chapter':
                from novel_writer.application.review_rules import prepare_parameters
                parameters=prepare_parameters(state,request['parameters'])
                if deep:
                    require(not parameters.rules.check_timeline and parameters.previous_report_id is None,'深层审核计划须显式选取，不继承离线复审或时间规则')
                    parameters=replace(parameters,waivers=())
                if summary and not graph:
                    require(parameters.selected_chapter_ids==(request['chapter_id'],) and len(parameters.sources)==1 and not parameters.rules.check_timeline and parameters.previous_report_id is None,'单章摘要不能选择其他章/计划')
                    require(bool(parameters.sources[0].text.strip()),'空正文不能准备模型语义摘要')
                    parameters=replace(parameters,waivers=())
                if graph:
                    require(1<=len(parameters.selected_chapter_ids)<=8 and len(parameters.sources)==len(parameters.selected_chapter_ids) and all(s.kind=='chapter' and bool(s.text.strip()) for s in parameters.sources) and not parameters.rules.check_timeline and parameters.previous_report_id is None,'图谱抽取只允许1至8个已保存正文')
                    parameters=replace(parameters,waivers=())
            target=next((c for c in state['document']['chapters'] if c['id']==request['chapter_id']),None);require(target is not None,'目标章节不属于当前书')
            if graph:
                require(all(s.chapter_number<=target['number'] for s in parameters.sources),'图谱抽取不能读取截至章之后的未来正文')
                from novel_writer.application.chapter_lifecycle import is_hidden
                require(all(not is_hidden(state,s.entity_id) for s in parameters.sources),'图谱抽取来源已归档/回收')
            from novel_writer.application.chapter_lifecycle import is_hidden
            require(not is_hidden(state,target['id']),'chapter_lifecycle.hidden_target')
            from novel_writer.application.scoped_rules import require_no_conflicts
            applicable_rules=require_no_conflicts(state,target['id'],options.rule_task_id,complete=graph)
            if options.rule_task_id is not None:
                from novel_writer.application.scoped_rules import task_binding
                require(task_binding(state,options.rule_task_id,target['id'])['task_type']==request['task_type'],'任务规则能力不匹配')
            selected_ids=[s.entity_id for s in options.search_selections if s.kind=='skill'] if options.include_search_results else []
            skills=self.service._skills(selected_ids)
            from novel_writer.application.context_preview import preview
            context=dict(context_text='',sources=[]) if summary or deep else preview(state,encode(options),skills=skills);require(digest(context['context_text'])==request['context_sha256'],'实际已保存资料串与预览不符')
            deps=[capture_dependency(state,'chapter',target['id'],use='target')]
            def add(kind,identifier,*,use='context',path=None):
                skill=next((s for s in skills if s['id']==identifier),None)
                d=capture_dependency(state,kind,identifier,use=use,skill=skill,file_path=path)
                if not any((a.kind,a.entity_id,a.use,a.file_path)==(d.kind,d.entity_id,d.use,d.file_path) for a in deps):deps.append(d)
            for source in context['sources']:
                if not source['included']:continue
                kind=source['kind'];identifier=source['entity_id']
                if kind=='chapter_plan':
                    outline=next((o for o in state['document']['chapter_outlines'] if o['id']==identifier),None)
                    if outline:add('chapter_outline',identifier)
                    add('idea',target['id'])
                elif kind=='search_result':
                    s=source['source'];add(s['kind'],s['entity_id'],path=s['file_path'])
                else:add('chapter' if kind=='chapter_body' else kind,identifier)
            if graph:
                for rule in applicable_rules['rules']:add('rule',rule['id'])
            outline=next((o for o in state['document']['chapter_outlines'] if o['chapter_id']==target['id']),None)
            if not summary and not deep:
                if outline:add('chapter_outline',outline['id'],use='plan_guard')
                add('idea',target['id'],use='plan_guard')
            if writing:add('project',project_id,use='plan_guard')
            if request['task_type']=='audit_chapter':
                for source in parameters.sources:add(source.kind,source.entity_id,use='analysis')
            frozen=FrozenInput.from_dict(dict(project_id=project_id,chapter_id=target['id'],source_revision=state['revision'],
                target=dict(chapter_id=target['id'],version_id=target['current_version_id'],title=target['title'],text=target['content'],status=target['status'],number=target['number'],source_sha256=deps[0].source_sha256),
                context_text=context['context_text'],context_sha256=digest(context['context_text']),context_options=encode(options),dependencies=[encode(d) for d in deps],parameters=encode(parameters),skill_snapshots=skills))
            if model_options is not None:
                from novel_writer.application.model_reviews import bind_parameters,upgrade as model_upgrade
                destination=None
                if model_options['adapter_id']=='configured-http-v2':
                    destination=self.registry.freeze_destination(request['task_type'],model_options)
                from novel_writer.application.semantic_summaries import memory_digest
                scope=None
                if deep:
                    from novel_writer.application.deep_reviews import freeze_scope
                    scope=freeze_scope(state,parameters.selected_chapter_ids,request['deep_review'])
                frozen=replace(frozen,parameters=bind_parameters(frozen,model_options,destination,summary_memory_sha256=memory_digest(state) if summary and not graph else None,deep_review=scope));model_upgrade(state)
                if deep:
                    from novel_writer.domain.deep_review import upgrade as deep_upgrade
                    deep_upgrade(state)
                if destination is not None:
                    from novel_writer.application.workflows import upgrade as workflow_upgrade
                    workflow_upgrade(state);state['workspace_version']=max(state['workspace_version'],9)
            now=utc_now();task=GenerationTask(id=str(uuid4()),request_id=identity,project_id=project_id,chapter_id=target['id'],task_type=request['task_type'],frozen=frozen,status='pending',
                attempt_id=None,owner_id=None,candidate_id=None,created_at=now,updated_at=now,started_at=None,finished_at=None,error_code=None)
            upgrade(state,task.task_type)
            if options.include_automatic_memories:
                from novel_writer.application.incremental_memory import upgrade as automation_upgrade
                automation_upgrade(state)
            if any(s.excerpt is not None or s.kind=='material' for s in options.search_selections):
                from novel_writer.application.chapter_lifecycle import upgrade as prior
                prior(state);state.setdefault('rule_task_bindings',[]);state.setdefault('deep_review_actions',[]);state.setdefault('memory_automation_events',[])
                from novel_writer.domain.body_planning import COLLECTIONS as BODY_PLANNING_COLLECTIONS
                for name in BODY_PLANNING_COLLECTIONS:state.setdefault(name,[])
                state['workspace_version']=max(state['workspace_version'],44)
            if graph:
                from novel_writer.application.graph_extraction import upgrade as graph_upgrade
                graph_upgrade(state)
            if any(d.kind=='memory_rollup' for d in deps):
                from novel_writer.application.chapter_lifecycle import upgrade as prior
                prior(state);state['workspace_version']=max(state['workspace_version'],32)
            state['generation_tasks'].append(encode(task));event(state,task,'prepared',now=now)
            return state,dict(task=encode(task),revision=state['revision']+1)
        return operation,identity

    def stream_token(self,deadline):
        token=CancellationToken(threading.Event(),deadline)
        token._stream_text=''
        def publish(text):
            with self.lock:
                token._stream_text=text if not token.event.is_set() and time.monotonic()<token.deadline else ''
        token._publish=publish
        return token
    def stream_preview(self,identifier,running):
        with self.lock:
            entry=self.active.get(identifier)
            if not running or entry is None:return {}
            token=entry[1]
            if token.event.is_set() or time.monotonic()>=token.deadline:return {}
            text=getattr(token,'_stream_text','')
            return dict(stream_preview=dict(text=text,chars=len(text),temporary=True)) if text else {}
    def describe(self,project_id,task_id=None):
        state=self.service.get(project_id)
        with self.lock:live={i for i in self.active}
        if task_id is None:
            return dict(revision=state['revision'],tasks=[self._describe(state,get_task(state,t['id']),live) for t in state.get('generation_tasks',[])])
        return self._describe(state,get_task(state,task_id),live)
    def _describe(self,state,task,live):
        result=dict(task=encode(task),revision=state['revision'],display_status='interrupted' if task.status=='running' and task.id not in live else task.status,
            candidates=[deepcopy(c) for c in state.get('generation_candidates',[]) if c['task_id']==task.id],
            events=[deepcopy(e) for e in state.get('task_events',[]) if e['task_id']==task.id],
            receipts=[deepcopy(r) for r in state.get('adoption_receipts',[]) if r['task_id']==task.id],
            reports=[deepcopy(r) for r in state.get('review_reports',[]) if r['task_id']==task.id],
            model_results=[deepcopy(r) for r in state.get('model_results',[]) if r['task_id']==task.id],
            model_reports=[deepcopy(r) for r in state.get('model_reports',[]) if r['task_id']==task.id],
            graph_extractions=[deepcopy(r) for r in state.get('graph_extractions',[]) if r['task_id']==task.id],
            selected_adapter_registered=self.registry.supports(task.task_type,self.registry.selected(task.task_type,task.frozen)),
            local_protocol_available=not hasattr(task.frozen.parameters,'binding') and self.registry.supports(task.task_type),real_model_request=hasattr(task.frozen.parameters,'binding'))
        result['rule_trace']=[dict(rule_id=d.entity_id,source_sha256=d.source_sha256,source_revision=d.source_revision) for d in task.frozen.dependencies if d.kind=='rule']
        result['rule_task_id']=task.frozen.context_options.rule_task_id
        from novel_writer.application.scoped_rules import require_fresh_rules
        try:require_fresh_rules(state,task);result['rules_fresh']=True
        except ValueError:result['rules_fresh']=False
        if task.task_type in ('draft_chapter','continue_chapter'):
            result['writing']=self.writing.describe(state,task)
            if task.status=='pending' and result['writing']['requires_new_preparation']:result['display_status']='interrupted'
        result.update(self.stream_preview(task.id,task.status=='running'))
        return result

    def start(self,project_id,task_id,confirmation=None,*,_workflow=None,_workflow_group=None,_workflow_limit=1,_arena_group=None):
        selected=get_task(self.service.get(project_id),task_id)
        if selected.frozen.context_options.retrieval_owner is not None:require(selected.frozen.context_options.retrieval_owner==self.owner_id,'旧会话/恢复复制的检索许可不继承，请明确准备新任务')
        if selected.frozen.context_options.retrieval_owner is not None:
            for dep in selected.frozen.dependencies:
                if dep.kind=='skill':
                    current=self.service._skills([dep.entity_id])[0]
                    require(dependency_equal(dep,capture_dependency(self.service.get(project_id),dep.kind,dep.entity_id,use=dep.use,skill=current,file_path=dep.file_path)),'检索全局资料已变化，请重新准备')
        from novel_writer.application.graph_extraction import assert_fresh as graph_fresh
        graph_fresh(self,self.service.get(project_id),selected)
        require(not self.closed.is_set(),'任务服务正在关闭');self.registry.validate_start(selected.task_type,selected.frozen,confirmation)
        self.registry.validate_preparation(selected)
        if selected.task_type in ('draft_chapter','continue_chapter'):self.writing.assert_fresh(self.service.get(project_id),selected,execute=True)
        from novel_writer.application.semantic_summaries import is_summary
        from novel_writer.application.reviews import assert_fresh
        if is_summary(selected) or getattr(selected.frozen.parameters,'deep_review',None) is not None:assert_fresh(self,self.service.get(project_id),selected)
        from novel_writer.domain.candidate_reviews import require_fresh as require_fresh_candidate
        require_fresh_candidate(self,self.service.get(project_id),selected)
        require(type(_workflow_limit) is int and 1<=_workflow_limit<=3,'执行并行上限非法')
        if _workflow_group is not None:
            from novel_writer.application.workflow_hooks import owned_task
            require(_workflow is not None and owned_task(self.service.get(project_id),task_id),'并行名额仅供已归属工作流的逐请求确认')
        else:require(_workflow_limit==1,'普通任务保持串行')
        if _arena_group is not None:
            from novel_writer.application.strict_arena import owned_group
            require(_workflow is None and owned_group(self.service.get(project_id),task_id,_arena_group),'竞技场并行名额归属非法')
        self._claim_execution(task_id,_arena_group if _arena_group is not None else _workflow_group,9 if _arena_group is not None else _workflow_limit)
        try:
            def operation(state):
                task=get_task(state,task_id);require(task.status=='pending','任务只能显式执行一次，终态/运行中不重跑')
                from novel_writer.application.arena import assert_fresh as require_fresh_arena
                require_fresh_arena(self,state,task)
                graph_fresh(self,state,task)
                require_fresh_rollups(state,task)
                from novel_writer.application.scoped_rules import require_fresh_rules
                require_fresh_rules(state,task)
                if is_summary(task) or getattr(task.frozen.parameters,'deep_review',None) is not None:assert_fresh(self,state,task)
                require_fresh_candidate(self,state,task)
                if task.task_type in ('draft_chapter','continue_chapter'):self.writing.assert_fresh(state,task,execute=True)
                from novel_writer.application.workflow_hooks import owned_task
                require(not owned_task(state,task_id) or _workflow is not None,'此任务由工作流管理，请从其节点进行本次确认')
                task=event(state,task,'started',attempt_id=str(uuid4()),owner_id=self.owner_id)
                if _workflow is not None:_workflow(state,task)
                return state,task
            task=self.repository.atomic(project_id,operation)
            token=self.stream_token(time.monotonic()+task.frozen.parameters.timeout_ms/1000)
            permission=None
            if hasattr(task.frozen.parameters,'binding'):
                from novel_writer.domain.model_contract import ExecutionPermit
                permission=ExecutionPermit(task_id=task.id,attempt_id=task.attempt_id,request_sha256=task.frozen.parameters.binding.request_sha256,confirmed=True)
            worker=threading.Thread(target=self._worker,args=(project_id,task,token,permission),daemon=True)
            with self.lock:self.active[task.id]=(worker,token)
            worker.start();return self.describe(project_id,task_id)
        except BaseException:
            self._release_execution(task_id);raise

    def _worker(self,project_id,task,token,permission=None):
        timer=threading.Timer(max(0,token.deadline-time.monotonic()),lambda:self._timeout(project_id,task,token));timer.daemon=True;timer.start()
        try:
            current=get_task(self.service.get(project_id),task.id)
            from novel_writer.application.graph_extraction import assert_fresh as graph_fresh
            graph_fresh(self,self.service.get(project_id),current)
            if current.status!='running' or current.attempt_id!=task.attempt_id:raise TaskCancelled('开始执行前任务已取消/中断')
            self.registry.validate_preparation(current)
            from novel_writer.application.scoped_rules import require_fresh_rules
            require_fresh_rules(self.service.get(project_id),current)
            from novel_writer.domain.candidate_reviews import require_fresh as require_fresh_candidate
            require_fresh_candidate(self,self.service.get(project_id),current)
            from novel_writer.application.semantic_summaries import is_summary
            if is_summary(current) or getattr(current.frozen.parameters,'deep_review',None) is not None:
                from novel_writer.application.reviews import assert_fresh
                assert_fresh(self,self.service.get(project_id),current)
            call=AdapterCall(task_id=task.id,attempt_id=task.attempt_id,capability=task.task_type,input=task.frozen,permission=permission)
            result=self.registry.execute(call,token);self._complete(project_id,task,result=result)
        except TaskTimeout:self._complete(project_id,task,error='timeout')
        except TaskCancelled:self._complete(project_id,task,error='interrupted' if self.closed.is_set() else 'cancelled')
        except Exception as error:
            from novel_writer.application.model_adapter import ModelExecutionFailure
            from novel_writer.application.task_protocol import WritingLateResponse
            if isinstance(error,WritingLateResponse):
                self._complete(project_id,task,error=error.kind);self.writing.capture_late(project_id,task,error.response)
            elif isinstance(error,ModelExecutionFailure):self._complete(project_id,task,error=error.response.error_code,model_response=error.response)
            else:self._complete(project_id,task,error='adapter_or_result_error')
        finally:
            timer.cancel()
            timer.join()  # cancel不能终止已进入的回调；退出active前等其SQLite连接关闭。
            with self.lock:
                token._stream_text='';self.active.pop(task.id,None)
            self._release_execution(task.id)
    def _timeout(self,project,task,token):
        try:self._complete(project,task,error='timeout')
        finally:token.event.set()
    def _complete(self,project,original,*,result=None,error=None,model_response=None):
        def operation(state):
            task=get_task(state,original.id)
            if task.status!='running' or task.attempt_id!=original.attempt_id or task.owner_id!=self.owner_id:
                if task.task_type in ('draft_chapter','continue_chapter') and model_response is not None and task.attempt_id==original.attempt_id and self.writing.append_late(state,task,model_response):return state,None
                return None,None
            now=utc_now()
            response_record=None
            if model_response is not None or (result is not None and result.model_response is not None):
                from novel_writer.application.model_reviews import persist_response
                response_record=persist_response(state,task,model_response or result.model_response,now)
            if result is not None:
                if result.graph_output is not None:
                    from novel_writer.application.graph_extraction import persist
                    persist(state,task,result.graph_output,response_record.id,now);event(state,task,'succeeded',now=now)
                elif result.candidate_audit_output is not None:
                    from novel_writer.application.workflows import persist_audit
                    persist_audit(state,task,result.candidate_audit_output,now,response_record.id if response_record else None);event(state,task,'succeeded',now=now)
                elif result.model_analysis is not None:
                    from novel_writer.application.model_reviews import persist_report
                    persist_report(state,task,result.model_analysis,response_record.id,now);event(state,task,'succeeded',now=now)
                elif task.task_type=='audit_chapter':
                    from novel_writer.application.reviews import persist_output
                    persist_output(state,task,result.analysis_output,now);event(state,task,'succeeded',now=now)
                else:
                    if response_record is not None:
                        from novel_writer.domain.model_contract import ModelCandidate
                        candidate=ModelCandidate(id=str(uuid4()),project_id=project,chapter_id=task.chapter_id,task_id=task.id,attempt_id=task.attempt_id,output_text=result.output_text,created_at=now,provenance='model_http_candidate',token_count=result.model_response.usage.total_tokens,cost=None,response_record_id=response_record.id)
                    else:candidate=Candidate(id=str(uuid4()),project_id=project,chapter_id=task.chapter_id,task_id=task.id,attempt_id=task.attempt_id,
                        output_text=result.output_text,created_at=now,provenance='local_protocol_fixture',token_count=None,cost=None)
                    state['generation_candidates'].append(encode(candidate));event(state,task,'succeeded',now=now,candidate_id=candidate.id)
            else:event(state,task,'interrupted' if error=='interrupted' else 'failed',now=now,error_code=error)
            return state,None
        return self.repository.atomic(project,operation)

    def model_review(self,project_id,report_id):
        from novel_writer.application.model_reviews import describe
        return describe(self,project_id,report_id)
    def decide_model_proposal(self,project_id,report_id,request,*,_workflow=None):
        from novel_writer.application.model_reviews import decide
        return decide(self,project_id,report_id,request,_workflow=_workflow)

    def cancel(self,project_id,task_id):
        def operation(state):
            task=get_task(state,task_id)
            if task.status not in ('pending','running'):return None,dict(accepted=False,task=encode(task))
            task=event(state,task,'cancelled',error_code='cancelled');return state,dict(accepted=True,task=encode(task))
        result=self.repository.atomic(project_id,operation)
        if result['accepted']:
            with self.lock:entry=self.active.get(task_id)
            if entry:entry[1].event.set()
        return result
    def recover(self,project_id):
        with self.lock:live=set(self.active)
        def operation(state):
            changed=[]
            for raw in list(state.get('generation_tasks',[])):
                task=parse(GenerationTask,raw)
                if task.status=='running' and task.id not in live:changed.append(encode(event(state,task,'interrupted',error_code='explicit_recovery')))
            return (state if changed else None),dict(interrupted=changed)
        return self.repository.atomic(project_id,operation)

    def adopt(self,project_id,task_id,request,*,_workflow=None):
        writing=get_task(self.service.get(project_id),task_id).task_type in ('draft_chapter','continue_chapter')
        fields={'candidate_id','adoption_id','expected_revision','authorize_confirmed'}|({'correction_id','review_id','confirmed_review'} if writing else set())
        check_fields(request,fields);require(set(request)==fields,'采纳参数缺失')
        identity=uuid_value(request['adoption_id']);require(type(request['authorize_confirmed']) is bool and type(request['expected_revision']) is int and request['expected_revision']>=1,'采纳授权/保存编号非法')
        def operation(state):
            existing=next((r for r in state.get('adoption_receipts',[]) if r['id']==identity),None)
            if existing:
                require(existing['task_id']==task_id and existing['candidate_id']==request['candidate_id'] and existing['project_id']==project_id,'同一采纳身份绑定不同任务/候选')
                if writing:self.writing.replay(state,existing,request)
                return None,deepcopy(existing)
            task=get_task(state,task_id);require(task.task_type in ('rewrite_chapter','draft_chapter','continue_chapter'),'分析报告不可经正文采纳入口写正文')
            from novel_writer.domain.workflow_stages import PLAN_PROMPTS
            require(getattr(getattr(task.frozen.parameters,'binding',None),'prompt_version',None) not in PLAN_PROMPTS,'IDEA/细纲候选不是正文，不能经正文采纳入口写入')
            from novel_writer.application.workflow_hooks import owned_task
            require(not owned_task(state,task_id) or _workflow is not None,'工作流候选须先绑定具体差异的人工节点')
            if _workflow is not None:_workflow(state,task,'before',None)
            require(task.status=='succeeded' and task.candidate_id==request['candidate_id'],'候选未完成/已取消或不属于当前任务')
            require_fresh_rollups(state,task)
            from novel_writer.application.scoped_rules import require_fresh_rules
            require_fresh_rules(state,task)
            if state['revision']!=request['expected_revision']:raise ConflictError('保存编号已变化，请保留输入并重新核对')
            require(not any(r['candidate_id']==task.candidate_id for r in state['adoption_receipts']),'候选已采纳，不得换身份重复写入')
            for dep in task.frozen.dependencies:
                skill=self.service._skills([dep.entity_id])[0] if dep.kind=='skill' else None
                actual=capture_dependency(state,dep.kind,dep.entity_id,use=dep.use,skill=skill,file_path=dep.file_path)
                require(dependency_equal(dep,actual),'目标或相关依赖已变化，候选已过期')
                require(dep.memory_fresh is not False,'未确认/归档/过期记忆不能作为事实')
            candidate=next(c for c in state['generation_candidates'] if c['id']==task.candidate_id)
            applied=self.writing.adoption_text(state,task,request) if writing else candidate['output_text']
            document=document_from_dict(state['document']);chapters.save(document,dict(chapter_id=task.chapter_id,content=applied,status='draft',authorize_confirmed=request['authorize_confirmed']))
            document.project.updated_at=utc_now();state['document']=document_to_dict(document)
            chapter=next(c for c in state['document']['chapters'] if c['id']==task.chapter_id);now=utc_now()
            receipt=AdoptionReceipt(id=identity,project_id=project_id,chapter_id=task.chapter_id,task_id=task.id,candidate_id=task.candidate_id,
                version_before=task.frozen.target.version_id,version_after=chapter['current_version_id'],applied_revision=state['revision']+1,
                requested_revision=request['expected_revision'],authorize_confirmed=request['authorize_confirmed'],adopted_at=now)
            state['adoption_receipts'].append(encode(receipt))
            if writing:self.writing.record_decision(state,task,request,applied)
            event(state,task,'adopted',now=now,adoption_id=identity)
            if _workflow is not None:_workflow(state,task,'after',encode(receipt))
            return state,encode(receipt)
        return self.repository.atomic(project_id,operation,identity_claim=('adoption_receipts','id',identity))
    def receipt(self,project_id,identity):
        value=next((r for r in self.service.get(project_id).get('adoption_receipts',[]) if r['id']==identity),None)
        if value is None:raise KeyError('采纳结果尚未提交')
        return deepcopy(value)
    def review_report(self,project_id,report_id):
        from novel_writer.application.reviews import describe
        return describe(self,project_id,report_id)
    def review_issue(self,project_id,report_id,request):
        from novel_writer.application.reviews import review_issue
        return review_issue(self,project_id,report_id,request)
    def decide_proposal(self,project_id,report_id,request):
        from novel_writer.application.reviews import decide_proposal
        return decide_proposal(self,project_id,report_id,request)
    def wait_idle(self,seconds=2):
        with self.lock:workers=[entry[0] for entry in self.active.values()]
        deadline=time.monotonic()+seconds
        for worker in workers:worker.join(max(0,deadline-time.monotonic()))
    def close(self):
        self.closed.set()
        with self.lock:entries=list(self.active.values())
        for worker,token in entries:token.event.set()
        self.wait_idle(2)
