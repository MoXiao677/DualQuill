"""V50 append-only refresh provenance and policy validation."""
from novel_writer.domain.tasks import require, uuid_value
from novel_writer.domain.memory import MemorySource, _exact

def validate_state(state):
    events=state.get('memory_refresh_events',[])
    require(type(events) is list and len(events)<=100000,'memory_refresh.invalid_events')
    seen=set();jobs={};operations=set();revision=0
    chapters={c['id'] for c in state['document']['chapters']}
    memories={m['id'] for m in state.get('memories',[])}
    rollups={r['id'] for r in state.get('memory_rollups',[])}
    for e in events:
        require(type(e) is dict,'memory_refresh.invalid_event')
        common={'id','kind','revision'};kind=e.get('kind')
        extra={'chapter_ids','memory_ids','rollup_ids','sources'} if kind=='impact' else {'operation_id','request_sha256','project_id','auto_refresh'} if kind=='policy' else {'operation_id','request_sha256','job_id','status','error','sources'} if kind=='attempt' else None
        require(extra is not None and set(e)==common|extra,'memory_refresh.invalid_fields')
        uuid_value(e['id']);require(e['id'] not in seen,'memory_refresh.duplicate_id');seen.add(e['id'])
        require(type(e['revision']) is int and revision<=e['revision']<=state['revision'],'memory_refresh.invalid_revision');revision=e['revision']
        if kind=='impact':
            for key,allowed in [('chapter_ids',chapters),('memory_ids',memories),('rollup_ids',rollups)]:
                values=e[key];require(type(values) is list and all(type(i) is str for i in values) and len(values)==len(set(values)) and set(values)<=allowed,'memory_refresh.invalid_dependencies')
            require(e['chapter_ids'] and (e['memory_ids'] or e['rollup_ids']),'memory_refresh.empty_job');jobs[e['id']]=e
        else:
            uuid_value(e['operation_id']);require(e['operation_id'] not in operations,'memory_refresh.duplicate_operation');operations.add(e['operation_id'])
            h=e['request_sha256'];require(type(h) is str and len(h)==64 and all(c in '0123456789abcdef' for c in h),'memory_refresh.invalid_hash')
            if kind=='policy':require(type(e['auto_refresh']) is bool and type(e['project_id']) is str and bool(e['project_id']),'memory_refresh.invalid_policy')
            else:
                require(e['job_id'] in jobs and e['status'] in ('failed','succeeded') and type(e['error']) is str and bool(e['error'])==(e['status']=='failed'),'memory_refresh.invalid_result')
        if 'sources' in e:
            ids=e['chapter_ids'] if kind=='impact' else jobs[e['job_id']]['chapter_ids']
            require(type(e['sources']) is list and len(e['sources'])==len(ids),'memory_refresh.invalid_sources')
            for cid,raw in zip(ids,e['sources']):
                s=_exact(raw,MemorySource)
                require(s.kind=='chapter' and s.entity_id==cid and s.chapter_id==cid and s.project_id==state['document']['project']['id'] and 1<=s.workspace_revision<=e['revision'],'memory_refresh.invalid_source')
                require(len(s.source_sha256)==64 and all(c in '0123456789abcdef' for c in s.source_sha256),'memory_refresh.invalid_source_hash')

def validate_transition(state,previous):
    old=previous.get('memory_refresh_events',[]);new=state.get('memory_refresh_events',[])
    require(len(new)>=len(old) and new[:len(old)]==old,'memory_refresh.history_not_append_only')
