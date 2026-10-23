"""同一事务准备两任务；公开盲评投影不返回私有绑定。"""
from copy import deepcopy
from novel_writer.domain.sampling import kwargs as sampling_kwargs
from types import SimpleNamespace
from dataclasses import replace
from datetime import datetime
from uuid import uuid4,uuid5,NAMESPACE_URL
import secrets
from novel_writer.domain.experiments import *
from novel_writer.domain.models import utc_now
from novel_writer.domain.tasks import GenerationTask,capture_dependency
from novel_writer.application.tasks import get_task,put_task,context_options
from novel_writer.application.model_reviews import canonical_options
from novel_writer.application.fields import check_fields,text
from novel_writer.application.extensions import upgrade

def experiment(state,identifier):
    raw=next((e for e in state.get('comparison_experiments',[]) if e['id']==identifier),None)
    if raw is None:raise KeyError('实验不存在或不属于当前书')
    return raw
def hidden_task_ids(state):
    revealed={r['experiment_id'] for r in state.get('comparison_reveals',[])}
    return {c['task_id'] for e in state.get('comparison_experiments',[]) if e['id'] not in revealed for c in e['configurations']}
def public_score(score):return {k:v for k,v in score.items() if k!='candidate_id'}

def public_workspace(state):
    hidden=hidden_task_ids(state)
    if not hidden:return state
    result=deepcopy(state);reports={r['id'] for name in ('model_reports','review_reports') for r in state.get(name,[]) if r['task_id'] in hidden};revealed={r['experiment_id'] for r in state.get('comparison_reveals',[])}
    for name in ('generation_tasks','task_events','generation_candidates','adoption_receipts','model_results','model_reports','review_reports','writing_corrections','writing_decisions','writing_late_results','style_trial_tasks','style_trial_events','style_trial_candidates','style_trial_results')+tuple(kind+'_'+suffix for kind in ('scene_expansion','chapter_planning') for suffix in ('tasks','events','results','candidates','reviews','adoptions','late_results')):
        if name in result:result[name]=[v for v in result[name] if (v['id'] if name.endswith('_tasks') else v['task_id']) not in hidden]
    for name in ('model_memory_proposals','model_bridge_proposals','model_proposal_receipts','review_issues','memory_proposals','review_actions','proposal_receipts','rule_waivers'):
        result[name]=[v for v in result.get(name,[]) if v['report_id'] not in reports]
    result['comparison_experiments']=[e if e['id'] in revealed else dict(id=e['id'],project_id=e['project_id'],title=e['title'],chapter_id=e['chapter_id'],created_at=e['created_at'],identity_hidden=True) for e in result['comparison_experiments']]
    result['comparison_scores']=[s if s['experiment_id'] in revealed else public_score(s) for s in result['comparison_scores']]
    result['read_only_projection']=True
    return result

class ComparisonCoordinator:
    def __init__(self,service,tasks,planning=None):
        self.service,self.tasks,self.planning=service,tasks,planning
        from novel_writer.application.writing_comparisons import WritingComparisons
        self.writing=WritingComparisons(self)
    def _engine(self,e):
        if e.get('trial_kind')=='writing_candidates':return self.writing.engine(e)
        if e.get('trial_kind')=='style_trial':return self.tasks.trials
        if e.get('task_kind')=='outline_chapter':
            require(self.planning is not None,'细纲协调器不可用');return self.planning
        return self.tasks
    def _profile(self,raw):
        options=canonical_options(raw);self.tasks.registry.validate_options('rewrite_chapter',options);return options
    def create(self,project_id,request):
        if request.get('task_kind') in ('scene_expansion','chapter_planning','chapter_writing'):return self.writing.create(project_id,request)
        if 'task_kind' in request:
            from novel_writer.application.arena import create
            return create(self,project_id,request)
        fields={'experiment_id','title','chapter_id','context_options','context_sha256','instruction','rubric','parameters','profiles','expected_revision'};check_fields(request,fields);require(set(request)==fields,'实验输入字段缺失');identity=uuid_value(request['experiment_id']);options=context_options(request['context_options']);require(options.chapter_id==request['chapter_id'] and options.include_writing_rules,'同题比较必须明确包含写作规则');profiles=tuple(parse(Profile,self._profile(p)) for p in request['profiles']);require(len(profiles)==2,'比较须恰好两配置');check_fields(request['parameters'],{'max_output_chars','timeout_ms'});require(set(request['parameters'])=={'max_output_chars','timeout_ms'},'共同参数缺失')
        title=text(request['title'],'实验名称',required=True);instruction=text(request['instruction'],'共同要求');rubric=text(request['rubric'],'共同评价要求',required=True);base=dict(title=title,chapter_id=request['chapter_id'],source_revision=request['expected_revision'],context_options=options,context_sha256=request['context_sha256'],instruction=instruction,rubric=rubric,max_output_chars=request['parameters']['max_output_chars'],timeout_ms=request['parameters']['timeout_ms'],profiles=profiles)
        def apply(state):
            old=next((e for e in state.get('comparison_experiments',[]) if e['id']==identity),None)
            if old:
                expected={k:encode(v) for k,v in base.items()};require(all(old[k]==v for k,v in expected.items()),'同一实验身份绑定其它输入');return None,dict(experiment_id=identity,revision=state['revision'])
            require(type(request['expected_revision']) is int and state['revision']==request['expected_revision'],'保存编号变化，请重新预览');slots=[];sides=['A','B']
            if secrets.randbelow(2):sides.reverse()
            for i,profile in enumerate(profiles):
                child=dict(request_id=str(uuid5(NAMESPACE_URL,identity+'/task-request/'+str(i))),chapter_id=request['chapter_id'],task_type='rewrite_chapter',context_options=encode(options),context_sha256=request['context_sha256'],parameters=dict(instruction=common_instruction(instruction,rubric),**request['parameters']),model_options=encode(profile),expected_revision=state['revision']);operation,_=self.tasks._preparer(project_id,child);_,prepared=operation(state);task=parse(GenerationTask,prepared['task']);deps=task.frozen.dependencies
                if not any(d.kind=='writing_rules' for d in deps):deps=deps+(capture_dependency(state,'writing_rules',project_id,use='plan_guard'),);task=replace(task,frozen=replace(task.frozen,dependencies=deps));put_task(state,task)
                slots.append(Configuration(id=str(uuid5(NAMESPACE_URL,identity+'/configuration/'+str(i))),index=i,side=sides[i],task_id=task.id))
            upgrade(state);first=next(t for t in state['generation_tasks'] if t['id']==slots[0].task_id);record=ComparisonExperiment(id=identity,project_id=project_id,configurations=tuple(slots),common_messages_sha256=messages_sha(first['frozen']),created_at=utc_now(),**base);state['comparison_experiments'].append(encode(record));return state,dict(experiment_id=identity,revision=state['revision']+1)
        return self.service.repository.atomic(project_id,apply,identity_claim=('comparison_experiments','id',identity))
    def setup(self,project_id,identifier):
        state=self.service.get(project_id);e=experiment(state,identifier);result=[]
        if e.get('blind_protocol')==2:
            from novel_writer.application.strict_arena import sealed_setup
            sealed=sealed_setup(state,e)
            if sealed is not None:return sealed
        if e.get('trial_kind')=='writing_candidates':return self.writing.setup(state,e)
        if e.get('trial_kind')=='style_trial':return self.tasks.trials.comparison_setup(state,e)
        for c in e['configurations']:
            from novel_writer.application.arena import request_metrics
            projected=arena_records(state)[0];t=projected[c['task_id']]
            task=next(t for t in state['chapter_planning_tasks' if e.get('task_kind')=='outline_chapter' else 'generation_tasks'] if t['id']==c['task_id']);b=task['binding'] if e.get('task_kind')=='outline_chapter' else task['frozen']['parameters']['binding']
            interrupted=e.get('task_kind')=='outline_chapter' and task['owner_id']!=self.tasks.owner_id and t['status'] in ('pending','running')
            result.append(dict(configuration_id=c['id'],configuration_label='配置'+str(c['index']+1),profile=e['profiles'][c['index']],request_body=b['request_body'],request_sha256=b['request_sha256'],destination=b.get('destination'),submitted=t['status']!='pending' or interrupted,can_cancel=t['status'] in ('pending','running'),metrics=request_metrics(b,e['price_quotes'][c['index']] if 'arena_version' in e else None)))
        with self.tasks.lock:live=set(self.tasks.active)
        executing=any(c['task_id'] in live for c in e['configurations'])
        ready=all(arena_records(state)[0][c['task_id']]['status'] in TERMINAL for c in e['configurations'])
        return dict(experiment_id=identifier,title=e['title'],configurations=result,common_messages_sha256=e['common_messages_sha256'],executing=executing,can_submit=not live,results_ready=ready)
    def execute(self,project_id,identifier,configuration_id,confirmation):
        e=experiment(self.service.get(project_id),identifier)
        require(e.get('blind_protocol')!=2,'严格盲评须逐配置许可后统一启动或取消')
        if e.get('trial_kind')=='writing_candidates':
            c=next((v for v in e['configurations'] if v['id']==configuration_id),None);require(c is not None,'配置不属于实验')
            self.writing.engine(e).start(project_id,c['task_id'],confirmation);return dict(experiment_id=identifier,configuration_id=configuration_id,submitted=True)
        state=self.service.get(project_id);e=experiment(state,identifier);c=next((c for c in e['configurations'] if c['id']==configuration_id),None);require(c is not None,'配置不属于实验')
        if 'arena_version' in e and e['task_kind']!='outline_chapter':
            from novel_writer.application.reviews import assert_fresh
            assert_fresh(self.tasks,state,get_task(state,c['task_id']))
        self._engine(e).start(project_id,c['task_id'],confirmation);return dict(experiment_id=identifier,configuration_id=configuration_id,submitted=True)
    def blind(self,project_id,identifier):
        state=self.service.get(project_id);e=experiment(state,identifier);tasks,arena_candidates,arena_results=arena_records(state);ready=all(tasks[c['task_id']]['status'] in TERMINAL for c in e['configurations']);reveal=next((r for r in state['comparison_reveals'] if r['experiment_id']==identifier),None);candidates=[]
        strict=e.get('blind_protocol')==2
        if ready or strict:
            for c in sorted(e['configurations'],key=lambda c:c['side']):
                t=tasks[c['task_id']];candidate=next((v for v in arena_candidates if v['id']==t['candidate_id']),None);usage=next((v['response']['usage'] for v in arena_results if v['task_id']==t['id']),dict(prompt_tokens=None,completion_tokens=None,total_tokens=None));elapsed=max(0,(datetime.fromisoformat(t['finished_at'])-datetime.fromisoformat(t['started_at'])).total_seconds()) if t['started_at'] and t['finished_at'] else 0
                candidates.append(dict(side=c['side'],status=t['status'],text=candidate['output_text'] if candidate and t['status']=='succeeded' else None,usage=usage,cost=None,cost_status='unknown',usage_source='provider_reported' if any(v is not None for v in usage.values()) else 'unknown',elapsed_seconds=elapsed))
                if strict and not reveal:
                    candidates[-1]={k:candidates[-1][k] for k in ('side','status','text')}
                if reveal and 'arena_version' in e:
                    from novel_writer.domain.arena import cost_estimate
                    candidates[-1]['cost_estimate']=cost_estimate(usage,e['price_quotes'][c['index']])
        result=dict(experiment_id=identifier,title=e['title'],revision=state['revision'],ready=ready,revealed=reveal is not None,candidates=candidates,scores=[public_score(s) for s in state['comparison_scores'] if s['experiment_id']==identifier],quality_ranking_verified=False)
        if strict:result['blind_protocol']=2
        if 'arena_version' in e:
            from novel_writer.application.arena import source_fresh
            result.update(task_kind=e['task_kind'],configuration_count=len(e['configurations']),source_revision=e['source_revision'],source_changed=not source_fresh(self,state,e))
        if e.get('trial_kind'):result['trial_kind']=e['trial_kind']
        if reveal:
            def profile(c):
                if e.get('trial_kind')!='writing_candidates':return e['profiles'][c['index']]
                from novel_writer.domain.writing_comparisons import task_record
                t=task_record(state,e['task_kind'],c['task_id']);return t['frozen']['parameters']['binding'] if e['task_kind']=='chapter_writing' else t['binding']
            result['identities']=[dict(side=c['side'],task_id=c['task_id'],profile=profile(c),reported_model=next((r['response']['reported_model'] for r in arena_results if r['task_id']==c['task_id']),None)) for c in e['configurations']]
        if reveal and e.get('trial_kind')=='style_trial':
            for identity in result['identities']:
                task=next(t for t in state['style_trial_tasks'] if t['id']==identity['task_id']);identity.update(style=task['style'],style_mode=task['style_mode'])
        if strict and reveal:
            from novel_writer.application.strict_arena import reveal_requests
            reveal_requests(state,e,result)
        return result
    def execute_batch(self,project_id,identifier,request):
        from novel_writer.application.strict_arena import execute_batch
        return execute_batch(self,project_id,identifier,request)
    def cancel_batch(self,project_id,identifier,request):
        from novel_writer.application.strict_arena import cancel_batch
        return cancel_batch(self,project_id,identifier,request)
    def cancel(self,project_id,identifier,configuration_id):
        e=experiment(self.service.get(project_id),identifier)
        require(e.get('blind_protocol')!=2,'严格盲评须逐配置许可后统一启动或取消')
        if e.get('trial_kind')=='writing_candidates':
            slot=next((v for v in e['configurations'] if v['id']==configuration_id),None);require(slot is not None,'配置不属于实验');return self.writing.engine(e).cancel(project_id,slot['task_id'])
        state=self.service.get(project_id);e=experiment(state,identifier);slot=next((v for v in e['configurations'] if v['id']==configuration_id),None);require(slot is not None,'配置不属于实验');value=self._engine(e).cancel(project_id,slot['task_id']);return dict(accepted=value['accepted'])
    def score(self,project_id,identifier,request):
        check_fields(request,{'operation_id','side','rating','outcome','notes','expected_revision','dimensions'});identity=uuid_value(request.get('operation_id'));outcome=request.get('outcome','scored')
        def apply(state):
            e=experiment(state,identifier);old=next((s for s in state.get('comparison_scores',[]) if s['id']==identity),None)
            if old:require(old.get('dimensions')==request.get('dimensions'),'评分身份绑定不同维度');require((old['experiment_id'],old['side'],old['rating'],old['notes'],old['outcome'])==(identifier,request.get('side'),request.get('rating'),request.get('notes'),outcome),'评分身份绑定不同内容');return None,old
            tasks,arena_candidates,arena_results=arena_records(state)
            strict=e.get('blind_protocol')==2
            if not strict:require(all(tasks[c['task_id']]['status'] in TERMINAL for c in e['configurations']),'两个配置未终态，不能盲评')
            else:require(not any(s['experiment_id']==identifier and s['side']==request.get('side') for s in state['comparison_scores']),'本侧评价已封存，不可改写')
            slot=next((c for c in e['configurations'] if c['side']==request.get('side')),None);require(slot is not None,'比较侧非法');task=tasks[slot['task_id']];candidate=next((c for c in arena_candidates if c['id']==task['candidate_id']),None)
            require(task['status'] in TERMINAL,'本侧尚未完成')
            dimensions={}
            if strict:dimensions=dict(dimensions=parse(tuple[DimensionScore,...],request.get('dimensions')))
            else:require('dimensions' not in request,'旧实验使用原评分契约')
            if task['status']=='succeeded':require(candidate is not None and outcome=='scored','成功侧须绑定实际候选评分')
            else:require(outcome=='unscorable' and request.get('rating') is None,'失败/取消侧无可评分结果，不能填数字分')
            require(type(request.get('expected_revision')) is int and state['revision']==request['expected_revision'],'保存编号变化');require(not any(r['experiment_id']==identifier for r in state['comparison_reveals']),'已揭晓不能冒充盲评分');value=(DetailedComparisonScore if strict else ComparisonScore)(**dimensions,id=identity,project_id=project_id,experiment_id=identifier,side=request.get('side'),rating=request.get('rating'),outcome=outcome,candidate_id=candidate['id'] if candidate else None,result_sha256=digest(candidate['output_text']) if candidate else None,terminal_status=task['status'],notes=request.get('notes'),created_at=utc_now());state['comparison_scores'].append(encode(value));return state,encode(value)
        return public_score(self.service.repository.atomic(project_id,apply,identity_claim=('comparison_scores','id',identity)))
    def reveal(self,project_id,identifier,request):
        check_fields(request,{'operation_id','expected_revision'});identity=uuid_value(request.get('operation_id'))
        def apply(state):
            e=experiment(state,identifier);old=next((r for r in state['comparison_reveals'] if r['experiment_id']==identifier),None)
            if old:return None,True
            tasks,arena_candidates,arena_results=arena_records(state);require(all(tasks[c['task_id']]['status'] in TERMINAL for c in e['configurations']),'任务未全部终态，不能提前揭晓');require(type(request.get('expected_revision')) is int and state['revision']==request['expected_revision'],'保存编号变化');scores={s['side']:s for s in state['comparison_scores'] if s['experiment_id']==identifier};sides={c['side'] for c in e['configurations']};require(set(scores)==sides,'须先保存全部候选评价或无可评分结果确认，再明确揭晓');r=ComparisonReveal(id=identity,project_id=project_id,experiment_id=identifier,score_ids=tuple(scores[k]['id'] for k in sorted(sides)),created_at=utc_now());state['comparison_reveals'].append(encode(r));return state,True
        self.service.repository.atomic(project_id,apply,identity_claim=('comparison_reveals','id',identity));return self.blind(project_id,identifier)
    def choose(self,project_id,identifier,request):
        e=experiment(self.service.get(project_id),identifier)
        if e.get('trial_kind')=='writing_candidates':return self._choose_writing(project_id,identifier,request)
        check_fields(request,{'operation_id','side','action','name','expected_revision'});identity=uuid_value(request.get('operation_id'))
        def apply(state):
            e=experiment(state,identifier);old=next((r for r in state['comparison_choices'] if r['id']==identity),None)
            if old:require((old['experiment_id'],old['side'],old['action'])==(identifier,request.get('side'),request.get('action')),'胜者操作身份绑定不同选择');return None,old
            require(any(r['experiment_id']==identifier for r in state['comparison_reveals']),'揭晓前不能选胜者');require(type(request.get('expected_revision')) is int and state['revision']==request['expected_revision'],'保存编号变化');c=next((c for c in e['configurations'] if c['side']==request.get('side')),None);require(c is not None,'比较侧非法');task=SimpleNamespace(**arena_records(state)[0][c['task_id']]) if e.get('trial_kind')=='style_trial' or e.get('task_kind') in ('outline_chapter','audit_chapter') else get_task(state,c['task_id']);require(task.status=='succeeded' and task.candidate_id is not None,'失败侧不能作为胜者候选');require(not (e.get('trial_kind')=='style_trial' or e.get('task_kind') in ('outline_chapter','audit_chapter')) or request.get('action')=='open_candidate','此题型仅可只读打开结果；正式采用须另行复核');preset_id=None
            if request.get('action')=='save_preset':
                b=encode(task.frozen.parameters.binding);settings=PresetSettings(**sampling_kwargs(b),**{k:b[k] for k in ('adapter_id','connection_id','model_id','temperature','max_tokens','prompt_version')},max_output_chars=e['max_output_chars'],timeout_ms=e['timeout_ms']);p=GenerationPreset(id=str(uuid4()),project_id=project_id,name=text(request.get('name'),'预设名称',required=True),role='writer',experiment_id=identifier,side=c['side'],settings=settings,created_at=utc_now());state['generation_presets'].append(encode(p));preset_id=p.id
            require(request.get('action') in ('open_candidate','save_preset'),'胜者仅可打开候选或保存参数预设');r=ComparisonChoice(id=identity,project_id=project_id,experiment_id=identifier,side=c['side'],action=request['action'],task_id=task.id,candidate_id=task.candidate_id,preset_id=preset_id,created_at=utc_now());state['comparison_choices'].append(encode(r));return state,encode(r)
        return self.service.repository.atomic(project_id,apply,identity_claim=('comparison_choices','id',identity))
    def _choose_writing(self,project,identifier,request):
        fields={'operation_id','side','action','name','expected_revision'};check_fields(request,fields);require(set(request)==fields and request['action']=='open_candidate' and request['name']=='','多候选选择只打开原候选，正式采纳须另行复核')
        identity=uuid_value(request['operation_id'])
        def operation(state):
            e=experiment(state,identifier);old=next((v for v in state['comparison_choices'] if v['id']==identity),None)
            if old:require((old['experiment_id'],old['side'],old['action'])==(identifier,request['side'],request['action']),'选择身份冲突');return None,old
            require(any(v['experiment_id']==identifier for v in state['comparison_reveals']),'请先评分并明确揭晓');require(type(request['expected_revision']) is int and state['revision']==request['expected_revision'],'保存编号变化')
            slot=next((v for v in e['configurations'] if v['side']==request['side']),None);require(slot is not None,'比较侧非法');task=arena_records(state)[0][slot['task_id']]
            require(task['status']=='succeeded' and task['candidate_id'] is not None,'失败侧不可选择')
            value=ComparisonChoice(id=identity,project_id=project,experiment_id=identifier,side=slot['side'],action='open_candidate',task_id=slot['task_id'],candidate_id=task['candidate_id'],preset_id=None,created_at=utc_now());state['comparison_choices'].append(encode(value));return state,encode(value)
        return self.service.repository.atomic(project,operation,identity_claim=('comparison_choices','id',identity))
