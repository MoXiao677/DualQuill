"""Deterministic local memory maintenance; never grants model execution permission."""
from copy import deepcopy
import hashlib
import json

DEFAULT_POLICY = dict(track_updates=False, auto_select=False)
FACT_SOURCES = {'chapter'}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode('utf-8')).hexdigest()


def policy(state):
    project=state['document']['project']['id']
    entries=[e for e in state.get('memory_automation_events',[]) if e['kind']=='policy']
    if not entries or entries[-1]['authorization_project_id']!=project:return deepcopy(DEFAULT_POLICY)
    return deepcopy(entries[-1]['policy'])


def upgrade(state):
    from novel_writer.application.chapter_lifecycle import upgrade as prior
    prior(state)
    state.setdefault('rule_task_bindings', [])
    state.setdefault('deep_review_actions', [])
    state['workspace_version']=max(state['workspace_version'],42)
    state.setdefault('memory_automation_events',[])


def record_impact(previous,current):
    """Called inside the same transaction as the source save. No model/worker exists here."""
    if not policy(previous)['track_updates']:return
    affected=impact(previous,current)
    if not any(affected.values()):return
    from uuid import uuid5,NAMESPACE_URL
    revision=previous['revision']+1
    # Preserve this source-transaction digest as historical provenance on copy.
    basis=digest(dict(affected=affected,chapters=[chapter_basis(current,c)
        for c in current['document']['chapters'] if c['id'] in affected['chapter_ids']]))
    identity=str(uuid5(NAMESPACE_URL,current['document']['project']['id']+'/memory-impact/'+str(revision)+'/'+basis))
    upgrade(current)
    current['memory_automation_events'].append(dict(id=identity,operation_id=identity,
        revision=revision,kind='impact',request_sha256=basis,**affected))


class IncrementalMemory:
    def __init__(self,service):
        self.service=service;self.repository=service.repository

    def listing(self,project):
        state=self.service.get(project);events=state.get('memory_automation_events',[])
        statuses={e['job_id']:{'cancel':'cancelled','reopen':'pending','resolve':'reviewed'}[e['kind']] for e in events if 'job_id' in e}
        queue=[]
        for entry in events:
            if entry['kind']!='impact':continue
            status=statuses.get(entry['id'],'pending')
            queue.append(dict(deepcopy(entry),status=status,requires_request_confirmation=True))
        return dict(revision=state['revision'],policy=policy(state),queue=queue,
            external_execution_authorized=False)

    def change(self,project,request):
        from novel_writer.domain.tasks import require,uuid_value
        from novel_writer.application.fields import check_fields
        from novel_writer.storage.sqlite_repository import ConflictError
        require(type(request) is dict,'memory_automation.invalid_request')
        kind=request.get('action')
        require(kind in ('policy','cancel','reopen','resolve'),'memory_automation.invalid_action')
        fields={'action','operation_id','expected_revision'}|({'policy'} if kind=='policy' else {'job_id'})
        check_fields(request,fields);require(set(request)==fields,'memory_automation.invalid_request')
        identity=uuid_value(request['operation_id']);expected=request['expected_revision']
        require(type(expected) is int and expected>=1,'memory_automation.invalid_revision')
        if kind=='policy':
            value=request['policy']
            require(type(value) is dict and set(value)==set(DEFAULT_POLICY) and all(type(v) is bool for v in value.values()),'memory_automation.invalid_policy')
        else:uuid_value(request['job_id'])
        request_hash=digest(request)
        def operation(state):
            entries=state.get('memory_automation_events',[])
            existing=next((e for e in entries if e['operation_id']==identity),None)
            if existing:
                require(existing['request_sha256']==request_hash,'memory_automation.operation_reused')
                return None,dict(self.listing(project),idempotent=True)
            if state['revision']!=expected:raise ConflictError('记忆策略或来源已变化，请重新读取')
            if kind!='policy':require(any(e['kind']=='impact' and e['id']==request['job_id'] for e in entries),'memory_automation.job_not_found')
            upgrade(state)
            entry=dict(id=identity,operation_id=identity,revision=expected+1,kind=kind,request_sha256=request_hash)
            if kind=='policy':entry.update(policy=deepcopy(request['policy']),authorization_project_id=project)
            else:entry['job_id']=request['job_id']
            state['memory_automation_events'].append(entry)
            return state,dict(revision=expected+1,idempotent=False,policy=policy(state),event=deepcopy(entry),external_execution_authorized=False)
        return self.repository.atomic(project,operation,identity_claim=('memory_automation_events','operation_id',identity))


def chapter_basis(state, chapter, *, hidden=None, volume_map=None):
    from novel_writer.domain.chapter_trash import hidden_ids
    if hidden is None:hidden=hidden_ids(state)
    if volume_map is None:volume_map={c:[v['number'] for v in (state['document']['book_outline'] or {}).get('volumes',[]) if c in v['chapter_ids']] for c in (chapter['id'],)}
    return dict(id=chapter['id'], content=chapter['content'], title=chapter['title'],
        number=chapter['number'],status=chapter['status'],version_id=chapter.get('current_version_id'),
        hidden=chapter['id'] in hidden,volumes=volume_map.get(chapter['id'],[]))


def basis_catalog(state):
    from novel_writer.domain.chapter_trash import hidden_ids
    hidden=hidden_ids(state);volumes={}
    for volume in (state['document']['book_outline'] or {}).get('volumes',[]):
        for identifier in volume['chapter_ids']:volumes.setdefault(identifier,[]).append(volume['number'])
    return {c['id']:chapter_basis(state,c,hidden=hidden,volume_map=volumes) for c in state['document']['chapters']}


def evidence_chapters(state):
    """Keep every accepted model quotation dependency, not just the primary source."""
    memories={m['id']:m for m in state.get('memories',[])}
    result={m['id']:{c for c in (m['position_chapter_id'],m['source']['chapter_id']) if c} for m in memories.values()}
    edits={e['id']:e for e in state.get('memory_history',[])}
    proposals={p['id']:p for p in state.get('model_memory_proposals',[])}
    for receipt in state.get('model_proposal_receipts',[]):
        memory=memories.get(receipt.get('memory_id'));edit=edits.get(receipt.get('memory_version_id'))
        if receipt['decision']!='accepted' or memory is None or edit is None:continue
        if edit['snapshot']['source']!=memory['source'] or receipt['saved_revision']!=memory['source']['workspace_revision']+1:continue
        proposal=proposals.get(receipt['proposal_id'])
        if proposal is not None:result[memory['id']].update(e['chapter_id'] for e in proposal['draft']['evidence'])
    return result


def impact(previous, current):
    """Exact chapter changes and their transitive saved-memory/rollup dependants."""
    before=basis_catalog(previous);after=basis_catalog(current)
    changed=sorted(i for i in before.keys() | after.keys() if before.get(i)!=after.get(i))
    old_memories={m['id']:m for m in previous.get('memories',[])}
    new_memories={m['id']:m for m in current.get('memories',[])}
    affected=set(i for i in old_memories.keys() | new_memories.keys()
        if old_memories.get(i)!=new_memories.get(i))
    for memory in list(old_memories.values())+list(new_memories.values()):
        if memory['source']['chapter_id'] in changed or memory['position_chapter_id'] in changed:
            affected.add(memory['id'])
    for deps in (evidence_chapters(previous),evidence_chapters(current)):
        affected.update(identifier for identifier,chapters in deps.items() if chapters.intersection(changed))
    from novel_writer.application.memory_rollups import conflicts
    old_conflicts={digest(c):c['memory_ids'] for c in conflicts(previous)}
    new_conflicts={digest(c):c['memory_ids'] for c in conflicts(current)}
    for key in old_conflicts.keys() ^ new_conflicts.keys():
        affected.update((old_conflicts if key in old_conflicts else new_conflicts)[key])
    rollups=set()
    from novel_writer.application.memory_rollups import _eligible
    for r in previous.get('memory_rollups',[])+current.get('memory_rollups',[]):
        through=after.get(r['through_chapter_id'])
        if r['through_chapter_id'] in changed or any(s['memory_id'] in affected for s in r['sources']) or (affected and through and any(m['id'] in affected for m in _eligible(current,r['scope'],r['scope_volume_number'],through['number']))):
            rollups.add(r['id'])
    return dict(chapter_ids=changed,memory_ids=sorted(affected),rollup_ids=sorted(rollups))


def automatic_candidates(state, chapter, scope):
    """Returns candidates and prose-free exclusion reasons, in stable story order."""
    from novel_writer.domain.chapter_trash import hidden_ids
    from novel_writer.domain.memory import outdated
    from novel_writer.application.memory_rollups import conflicts
    hidden=hidden_ids(state)
    conflict_ids={i for c in conflicts(state) for i in c['memory_ids']}
    cutoff=chapter['number']-(scope=='previous')
    enabled=policy(state)['auto_select']
    result=[];dependencies=evidence_chapters(state);positions={c['id']:c['number'] for c in state['document']['chapters']}
    def position(memory):return max(positions.get(i,cutoff+1) for i in dependencies[memory['id']])
    for memory in sorted(state.get('memories',[]),key=lambda m:(-position(m),m['id'])):
        reason='automatic_memory'
        if not enabled:reason='automatic_disabled'
        elif not memory['active']:reason='memory_archived'
        elif not memory['confirmed']:reason='memory_unconfirmed'
        elif memory['source']['kind'] not in FACT_SOURCES:reason='memory_planning_source'
        elif dependencies[memory['id']].intersection(hidden):reason='memory_hidden_chapter'
        elif position(memory)>cutoff:reason='memory_future' if position(memory)>chapter['number'] else 'memory_current'
        elif outdated(state,memory['source']):reason='memory_outdated'
        elif memory['id'] in conflict_ids:reason='memory_conflict'
        result.append((memory,reason,position(memory)))
    return result
