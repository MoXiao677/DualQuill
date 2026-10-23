"""Group frozen C04 requests and delegate every write to its original owner."""
from uuid import uuid4
import secrets
from novel_writer.application.fields import check_fields,text
from novel_writer.domain.tasks import encode,require,uuid_value
from novel_writer.domain.models import utc_now
from novel_writer.domain.writing_comparisons import WritingExperiment,KINDS,SIDES,task_record,common_input
from novel_writer.domain.experiments import Configuration,arena_records

class WritingComparisons:
    def __init__(self,parent):self.parent=parent

    def create(self,project,request):
        fields={'experiment_id','title','task_kind','task_ids','expected_revision'}
        check_fields(request,fields);require(set(request)==fields,'writing_comparison.invalid_fields')
        identity=uuid_value(request['experiment_id']);kind=request['task_kind'];ids=request['task_ids']
        require(kind in KINDS and type(ids) is list and 2<=len(ids)<=6 and len(set(ids))==len(ids),'writing_comparison.invalid_tasks')
        title=text(request['title'],'多候选名称',required=True)
        def operation(state):
            old=next((v for v in state.get('comparison_experiments',[]) if v['id']==identity),None)
            if old:
                require(old.get('trial_kind')=='writing_candidates' and old['title']==title and old['task_kind']==kind and old['source_revision']==request['expected_revision'] and [v['task_id'] for v in old['configurations']]==ids,'writing_comparison.identity_conflict')
                return None,dict(experiment_id=identity,revision=state['revision'])
            require(type(request['expected_revision']) is int and state['revision']==request['expected_revision'],'保存编号变化，请重新准备')
            tasks=[task_record(state,kind,v) for v in ids];common=common_input(tasks[0],kind)
            require(all(common_input(v,kind)==common for v in tasks),'writing_comparison.different_frozen_input')
            used={c['task_id'] for e in state.get('comparison_experiments',[]) for c in e['configurations']}
            require(not used.intersection(ids),'writing_comparison.task_already_grouped')
            require(all(arena_records(state)[0][v]['status']=='pending' for v in ids),'只能将尚未发送的冻结任务编为新组')
            from novel_writer.application.chapter_lifecycle import upgrade
            upgrade(state);state.setdefault('rule_task_bindings',[]);state['workspace_version']=max(state['workspace_version'],37)
            sides=list(SIDES[:len(ids)]);secrets.SystemRandom().shuffle(sides)
            record=WritingExperiment(id=identity,project_id=project,title=title,chapter_id=tasks[0]['chapter_id'],source_revision=state['revision'],task_kind=kind,common_input_sha256=common,
                configurations=tuple(Configuration(id=str(uuid4()),index=i,side=sides[i],task_id=v) for i,v in enumerate(ids)),created_at=utc_now())
            state['comparison_experiments'].append(encode(record));return state,dict(experiment_id=identity,revision=state['revision']+1)
        return self.parent.service.repository.atomic(project,operation,identity_claim=('comparison_experiments','id',identity))

    def engine(self,experiment):
        if experiment['task_kind']=='chapter_writing':return self.parent.tasks
        return getattr(self.parent.tasks,{'scene_expansion':'expansions','chapter_planning':'planning'}[experiment['task_kind']])

    def setup(self,state,e):
        configurations=[];arena_tasks=arena_records(state)[0]
        with self.parent.tasks.lock:live=set(self.parent.tasks.active)
        for c in e['configurations']:
            task=task_record(state,e['task_kind'],c['task_id'])
            binding=task['frozen']['parameters']['binding'] if e['task_kind']=='chapter_writing' else task['binding']
            raw_status=arena_tasks[task['id']]['status'];status=raw_status
            owner=task['frozen']['parameters']['writing']['prepared_owner'] if e['task_kind']=='chapter_writing' else task['owner_id']
            if raw_status in ('pending','running') and (owner!=self.parent.tasks.owner_id or (raw_status=='running' and task['id'] not in live)):status='interrupted'
            configurations.append(dict(configuration_id=c['id'],configuration_label='配置'+str(c['index']+1),profile=binding,request_body=binding['request_body'],request_sha256=binding['request_sha256'],destination=binding.get('destination'),status=status,submitted=status!='pending',can_cancel=raw_status in ('pending','running')))
        return dict(experiment_id=e['id'],title=e['title'],trial_kind=e['trial_kind'],configurations=configurations,common_messages_sha256=e['common_input_sha256'],executing=any(c['task_id'] in live for c in e['configurations']),can_submit=not live)
