"""V52 immutable batch grants and append-only executor audit."""
from novel_writer.domain.tasks import require, uuid_value
from novel_writer.domain.models import _timestamp

COLLECTIONS = ('console_background_batches', 'console_background_events')
TERMINAL = ('completed','awaiting_human','step_limit','time_limit','paused','cancelled','interrupted','failed')


def validate_state(state):
    batches = state.get(COLLECTIONS[0], [])
    events = state.get(COLLECTIONS[1], [])
    require(type(batches) is list and type(events) is list, 'background.collections')
    runs = {r['id']: r for r in state.get('console_runs', [])}
    steps = {s['id']: s for s in state.get('console_run_steps', [])}
    ids, operations = set(), set()
    for b in batches:
        require(type(b) is dict and set(b)=={'id','project_id','run_id','operation_id','owner_id','request','preview','created_at'}, 'background.batch_fields')
        for key in ('id','run_id','operation_id','owner_id'):uuid_value(b[key])
        require(b['id'] not in ids and b['operation_id'] not in operations, 'background.duplicate')
        ids.add(b['id']); operations.add(b['operation_id'])
        require(b['run_id'] in runs and b['project_id']==state['document']['project']['id'], 'background.run')
        r = b['request']; require(type(r) is dict and set(r)=={'step_ids','max_steps','max_seconds'}, 'background.request')
        require(type(r['max_steps']) is int and 1<=r['max_steps']<=100, 'background.step_limit')
        require(type(r['max_seconds']) in (int,float) and 0<r['max_seconds']<=3600, 'background.time_limit')
        require(type(r['step_ids']) is list and 0<len(r['step_ids'])<=100 and len(set(r['step_ids']))==len(r['step_ids']), 'background.steps')
        require(all(s in steps and steps[s]['run_id']==b['run_id'] for s in r['step_ids']), 'background.step_ref')
        require(type(b['preview']) is dict and type(b['preview'].get('items')) is list, 'background.preview')
        _timestamp(b['created_at'], 'background.created_at')
    event_ids=set(); statuses={}
    for e in events:
        require(type(e) is dict and set(e)=={'id','batch_id','kind','step_id','elapsed_ms','detail','created_at'}, 'background.event_fields')
        uuid_value(e['id']); require(e['id'] not in event_ids and e['batch_id'] in ids, 'background.event_ref'); event_ids.add(e['id'])
        require(e['step_id'] is None or e['step_id'] in steps, 'background.event_step')
        require(e['kind'] in ('started','step_started','step_completed',*TERMINAL), 'background.event_kind')
        require(type(e['elapsed_ms']) is int and e['elapsed_ms']>=0 and type(e['detail']) is dict, 'background.event_detail')
        _timestamp(e['created_at'], 'background.created_at')
        require(statuses.get(e['batch_id']) not in TERMINAL, 'background.terminal_immutable')
        statuses[e['batch_id']]=e['kind']
    active=set()
    for b in batches:
        if statuses.get(b['id']) not in TERMINAL:
            require(b['run_id'] not in active, 'background.concurrent_batch'); active.add(b['run_id'])


def validate_transition(state, previous):
    validate_state(state)
    for name in COLLECTIONS:
        old=previous.get(name, [])
        require(state[name][:len(old)]==old, 'background.history_append_only')
