"""C12 composes S6A requests; existing coordinators own all execution."""
from dataclasses import replace
import json,secrets
from uuid import uuid5,NAMESPACE_URL
from novel_writer.domain.experiments import ArenaExperiment,StrictArenaExperiment,Profile,Configuration,SIDES,common_instruction,messages_sha
from novel_writer.domain.arena import VERSION,validate_budget,validate_quotes
from novel_writer.domain.connections import canonical_messages
from novel_writer.domain.models import utc_now
from novel_writer.domain.tasks import parse,encode,require,uuid_value,digest,GenerationTask,capture_dependency
from novel_writer.application.tasks import context_options,put_task
from novel_writer.application.fields import check_fields,text
from novel_writer.application.model_reviews import canonical_options

def create(coordinator,project,request):
    fields={'experiment_id','title','chapter_id','context_options','context_sha256','instruction','rubric','parameters','profiles','expected_revision','task_kind','planning_options','budget'}
    check_fields(request,fields|{'price_quotes','blind_protocol'});require(fields<=set(request),'竞技场输入字段缺失')
    if 'blind_protocol' in request:require(type(request['blind_protocol']) is int and request['blind_protocol']==2,'未知盲评协议')
    identity=uuid_value(request['experiment_id']);kind=request['task_kind'];require(kind in ('rewrite_chapter','outline_chapter','audit_chapter'),'不支持的竞技场题型')
    require(type(request['profiles']) is list and 2<=len(request['profiles'])<=8,'竞技场须有2至8个明确配置')
    profiles=tuple(parse(Profile,canonical_options(p)) for p in request['profiles'])
    for p in profiles:
        require(p.prompt_version==('review-json-1' if kind=='audit_chapter' else 'rewrite-1'),'配置提示词与竞技场题型不兼容')
        if kind!='outline_chapter':coordinator.tasks.registry.validate_options(kind,encode(p))
    options=context_options(request['context_options']);require(options.chapter_id==request['chapter_id'] and options.include_writing_rules,'竞技场须包含共同写作规则与目标章')
    parameters=request['parameters'];check_fields(parameters,{'max_output_chars','timeout_ms'});require(set(parameters)=={'max_output_chars','timeout_ms'},'共同参数缺失')
    title=text(request['title'],'实验名称',required=True);instruction=text(request['instruction'],'共同要求');rubric=text(request['rubric'],'共同评价要求',required=True)
    validate_budget(request['budget'],profiles)
    quotes=request.get('price_quotes',[None]*len(profiles));validate_quotes(quotes,len(profiles));quotes=tuple(quotes)
    planning=request['planning_options']
    if kind=='outline_chapter':
        require(coordinator.planning is not None and type(planning) is dict and planning.get('mode')=='outline' and planning.get('chapter_id')==request['chapter_id'] and planning.get('include_writing_rules') is True,'细纲竞技场须明确本章人物与共同规则来源')
        require(planning.get('instruction')==common_instruction(instruction,rubric),'细纲来源要求须包含共同要求及评价要求')
    else:require(planning is None,'当前题型不接受细纲来源选项')
    base=dict(title=title,chapter_id=request['chapter_id'],source_revision=request['expected_revision'],context_options=options,context_sha256=request['context_sha256'],instruction=instruction,rubric=rubric,
              max_output_chars=parameters['max_output_chars'],timeout_ms=parameters['timeout_ms'],profiles=profiles,arena_version=1,task_kind=kind,planning_options=planning,budget=request['budget'],price_quotes=quotes)
    if 'blind_protocol' in request:base['blind_protocol']=2
    def operation(state):
        old=next((e for e in state.get('comparison_experiments',[]) if e['id']==identity),None)
        if old:
            require(all(old.get(k)==encode(v) for k,v in base.items()),'同一竞技场身份绑定其它输入');return None,dict(experiment_id=identity,revision=state['revision'])
        require(type(request['expected_revision']) is int and request['expected_revision']==state['revision'],'保存编号变化，请重新预览')
        slots=[];sides=list(SIDES[:len(profiles)]);secrets.SystemRandom().shuffle(sides);common_sha=None
        if kind=='outline_chapter':
            from novel_writer.application.chapter_planning import build_source
            source=build_source(state,planning);require(source['context_sha256']==request['context_sha256'],'细纲共同来源已变化')
        for i,profile in enumerate(profiles):
            child_id=str(uuid5(NAMESPACE_URL,identity+'/task-request/'+str(i)))
            if kind=='outline_chapter':
                child=dict(operation_id=child_id,source_options=planning,source_sha256=source['source_sha256'],model_options=encode(profile),**parameters)
                prepare,_=coordinator.planning._preparer(project,child,state=state);_,prepared=prepare(state);task=prepared['task'];task_id=task['id']
                body=canonical_messages(json.loads(task['binding']['request_body']),task['binding']['destination']['protocol'])
                sha=digest(json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':')))
            else:
                p=dict(instruction=common_instruction(instruction,rubric),**parameters)
                if kind=='audit_chapter':
                    p.update(rules=dict(version='offline-audit-1',forbidden_literals=[],required_literals=[],normalization='whitespace',near_threshold=.8,minimum_fragment_chars=12,check_timeline=False),selected_chapter_ids=[request['chapter_id']],previous_report_id=None)
                child=dict(request_id=child_id,chapter_id=request['chapter_id'],task_type=kind,context_options=encode(options),context_sha256=request['context_sha256'],parameters=p,model_options=encode(profile),expected_revision=state['revision'])
                prepare,_=coordinator.tasks._preparer(project,child);_,prepared=prepare(state);task=parse(GenerationTask,prepared['task'])
                if not any(d.kind=='writing_rules' for d in task.frozen.dependencies):
                    task=replace(task,frozen=replace(task.frozen,dependencies=task.frozen.dependencies+(capture_dependency(state,'writing_rules',project,use='plan_guard'),)));put_task(state,task)
                task_id=task.id;sha=messages_sha(encode(task.frozen))
            require(common_sha is None or common_sha==sha,'配置未冻结相同共同消息');common_sha=sha
            slots.append(Configuration(id=str(uuid5(NAMESPACE_URL,identity+'/configuration/'+str(i))),index=i,side=sides[i],task_id=task_id))
        from novel_writer.application.chapter_lifecycle import upgrade
        upgrade(state);state.setdefault('rule_task_bindings',[]);state['workspace_version']=max(state['workspace_version'],VERSION)
        record=(StrictArenaExperiment if 'blind_protocol' in base else ArenaExperiment)(id=identity,project_id=project,configurations=tuple(slots),common_messages_sha256=common_sha,created_at=utc_now(),**base)
        state['comparison_experiments'].append(encode(record));return state,dict(experiment_id=identity,revision=state['revision']+1)
    return coordinator.service.repository.atomic(project,operation,identity_claim=('comparison_experiments','id',identity))

def request_metrics(binding,quote=None):
    """Token counts are unknown until supplied; chars are never called tokens."""
    return dict(input_tokens=None,input_tokens_source='unknown',request_utf8_bytes=len(binding['request_body'].encode('utf8')),
                output_token_limit=binding['max_tokens'],risk_budget=binding['budget_limit'],estimated_cost=None,actual_cost=None,currency=quote['currency'].upper() if quote else None,price_status='manual_unverified' if quote else 'unknown',price_source=quote['source'] if quote else None,price_quote=quote)

def assert_fresh(coordinator,state,task):
    owned=any('arena_version' in e and any(c['task_id']==task.id for c in e['configurations']) for e in state.get('comparison_experiments',[]))
    if owned:
        from novel_writer.application.reviews import assert_fresh as check
        check(coordinator,state,task)

def source_fresh(coordinator,state,e):
    try:
        if e['task_kind']=='outline_chapter':
            from novel_writer.application.chapter_planning import source_fresh as check,parse_task
            return check(state,parse_task(state,e['configurations'][0]['task_id']))
        from novel_writer.application.tasks import get_task
        assert_fresh(coordinator.tasks,state,get_task(state,e['configurations'][0]['task_id']));return True
    except (ValueError,KeyError,OSError):return False
