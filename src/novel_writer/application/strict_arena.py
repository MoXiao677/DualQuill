"""Strict anonymous evaluation over the existing, individually permitted adapters."""
import secrets
from novel_writer.domain.tasks import require
from novel_writer.domain.experiments import arena_records,TERMINAL
from novel_writer.application.fields import check_fields

def owned_group(state, task_id, group):
    return any(e['id']==group and e.get('blind_protocol')==2 and
               any(c['task_id']==task_id for c in e['configurations'])
               for e in state.get('comparison_experiments',[]))

def sealed_setup(state,e):
    tasks=arena_records(state)[0]
    if any(tasks[c['task_id']]['status']!='pending' for c in e['configurations']):
        # Never correlate a named configuration with completion, failure, or timing.
        return dict(experiment_id=e['id'],title=e['title'],configurations=[],
                    blind_protocol=2,sealed=True,can_submit=False,
                    executing=any(tasks[c['task_id']]['status']=='running' for c in e['configurations']))
    return None

def reveal_requests(state,e,result):
    for identity in result['identities']:
        slot=next(c for c in e['configurations'] if c['side']==identity['side'])
        task=next(t for t in state['chapter_planning_tasks' if e['task_kind']=='outline_chapter' else 'generation_tasks'] if t['id']==slot['task_id'])
        binding=task['binding'] if e['task_kind']=='outline_chapter' else task['frozen']['parameters']['binding']
        identity.update(request_body=binding['request_body'],request_sha256=binding['request_sha256'],
                        destination=binding.get('destination'),configuration_index=slot['index'],
                        parameters=dict(max_output_chars=e['max_output_chars'],timeout_ms=e['timeout_ms']))

def execute_batch(coordinator,project,identifier,request):
    from novel_writer.application.comparisons import experiment
    check_fields(request,{'confirmations'});require(set(request)=={'confirmations'},'缺少逐配置许可')
    state=coordinator.service.get(project);e=experiment(state,identifier)
    require(e.get('blind_protocol')==2,'仅严格盲评接受统一启动')
    confirmations=request['confirmations'];slots=e['configurations']
    require(type(confirmations) is list and len(confirmations)==len(slots),'须逐配置确认全部请求')
    by_id={}
    for confirmation in confirmations:
        check_fields(confirmation,{'configuration_id','confirm_external','request_sha256'})
        require(set(confirmation)=={'configuration_id','confirm_external','request_sha256'},'配置许可字段缺失')
        require(confirmation['configuration_id'] not in by_id,'重复配置许可')
        by_id[confirmation['configuration_id']]={k:confirmation[k] for k in ('confirm_external','request_sha256')}
    require(set(by_id)=={c['id'] for c in slots},'配置许可不属于本实验')
    tasks=arena_records(state)[0]
    require(all(tasks[c['task_id']]['status']=='pending' for c in slots),'本组已经启动或取消，不会重发')
    # Validate every permission before the first side can send anything.
    for c in slots:
        if e['task_kind']=='outline_chapter':
            from novel_writer.application.chapter_planning import parse_task,source_fresh
            task=parse_task(state,c['task_id'])
            coordinator.planning.adapter.validate_start(task,by_id[c['id']])
            require(source_fresh(state,task),'共同来源已变化')
        else:
            from novel_writer.application.tasks import get_task
            from novel_writer.application.arena import assert_fresh
            task=get_task(state,c['task_id'])
            coordinator.tasks.registry.validate_start(task.task_type,task.frozen,by_id[c['id']])
            assert_fresh(coordinator.tasks,state,task)
    shuffled=list(slots);secrets.SystemRandom().shuffle(shuffled)
    # Reserve the shared domain during admission, including very fast responses.
    reservation='arena-admission:'+identifier
    coordinator.tasks._claim_execution(reservation,identifier,9)
    try:
        for c in shuffled:
            try:
                coordinator._engine(e).start(project,c['task_id'],by_id[c['id']],_arena_group=identifier)
            except (ValueError,KeyError):
                # A changed source/configuration or admission failure affects this side only.
                coordinator._engine(e).cancel(project,c['task_id'])
    finally:
        coordinator.tasks._release_execution(reservation)
    return dict(experiment_id=identifier,submitted=True)

def cancel_batch(coordinator,project,identifier,request):
    from novel_writer.application.comparisons import experiment
    require(request=={},'统一取消不接受其它字段')
    state=coordinator.service.get(project);e=experiment(state,identifier)
    require(e.get('blind_protocol')==2,'仅严格盲评接受统一取消')
    tasks=arena_records(state)[0]
    for c in e['configurations']:
        if tasks[c['task_id']]['status'] not in TERMINAL:
            coordinator._engine(e).cancel(project,c['task_id'])
    return dict(accepted=True)
