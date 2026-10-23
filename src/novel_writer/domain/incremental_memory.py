"""V42 append-only local maintenance events; no execution grants are representable."""
from novel_writer.domain.tasks import require,uuid_value


def validate_state(state):
    events=state['memory_automation_events']
    require(type(events) is list and len(events)<=100000,'memory_automation.invalid_events')
    ids=set();jobs=set();previous_revision=0
    chapters={c['id'] for c in state['document']['chapters']}
    memories={m['id'] for m in state.get('memories',[])}
    rollups={r['id'] for r in state.get('memory_rollups',[])}
    for e in events:
        require(type(e) is dict,'memory_automation.invalid_event')
        common={'id','operation_id','revision','kind','request_sha256'}
        kind=e.get('kind')
        extra={'policy','authorization_project_id'} if kind=='policy' else {'chapter_ids','memory_ids','rollup_ids'} if kind=='impact' else {'job_id'} if kind in ('cancel','reopen','resolve') else None
        require(extra is not None and set(e)==common|extra,'memory_automation.invalid_event_fields')
        uuid_value(e['id']);uuid_value(e['operation_id'])
        require(e['id']==e['operation_id'] and e['id'] not in ids,'memory_automation.duplicate_operation');ids.add(e['id'])
        require(type(e['revision']) is int and 1<=e['revision']<=state['revision'] and previous_revision<=e['revision'],'memory_automation.invalid_event_revision');previous_revision=e['revision']
        h=e['request_sha256'];require(type(h) is str and len(h)==64 and all(c in '0123456789abcdef' for c in h),'memory_automation.invalid_hash')
        if kind=='policy':
            require(type(e['policy']) is dict and set(e['policy'])=={'track_updates','auto_select'} and all(type(v) is bool for v in e['policy'].values()),'memory_automation.invalid_policy')
            require(type(e['authorization_project_id']) is str and bool(e['authorization_project_id']),'memory_automation.invalid_authorization_origin')
        elif kind=='impact':
            for key,allowed in (('chapter_ids',chapters),('memory_ids',memories),('rollup_ids',rollups)):
                require(type(e[key]) is list and all(type(i) is str for i in e[key]) and len(e[key])==len(set(e[key])) and set(e[key])<=allowed,'memory_automation.invalid_affected_ids')
            require(any(e[key] for key in ('chapter_ids','memory_ids','rollup_ids')),'memory_automation.empty_impact');jobs.add(e['id'])
        else:require(type(e['job_id']) is str and e['job_id'] in jobs,'memory_automation.invalid_job')


def validate_transition(state,previous):
    old=previous.get('memory_automation_events',[])
    new=state.get('memory_automation_events',[])
    require(len(new)>=len(old) and new[:len(old)]==old,'memory_automation.history_not_append_only')
