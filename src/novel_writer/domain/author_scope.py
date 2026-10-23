"""V48 append-only project lifecycle and code-point body-range protection."""
from difflib import SequenceMatcher
from hashlib import sha256
from uuid import UUID, NAMESPACE_URL, uuid5

from .models import DataValidationError, _timestamp

COLLECTION='author_scope_events'

def require(condition,message):
    if not condition:raise DataValidationError('author_scope.'+message)

def digest(text):return sha256(text.encode('utf-8')).hexdigest()

def _uuid(value):
    require(type(value) is str,'invalid_identity')
    try:UUID(value)
    except (ValueError,TypeError):raise DataValidationError('author_scope.invalid_identity') from None

def project_state(state):
    value='archived' if state['document']['project']['status']=='archived' else 'active'
    for event in state.get(COLLECTION,[]):
        if event['kind']=='lifecycle':value=event['data']['after']
    return value

def active_locks(state):
    result={}
    for event in state.get(COLLECTION,[]):
        data=event['data']
        if event['kind'] in ('lock','rebase'):result[data['lock_id']]=data
        elif event['kind']=='unlock':result.pop(data['lock_id'],None)
    return result

def mapped_ranges(before,after,locks):
    if before==after:return {item['lock_id']:(item['start'],item['end']) for item in locks}
    # Exact common boundaries remain unambiguous for repeated prose. In the
    # middle, reject duplicate text rather than silently switching occurrences.
    prefix=0;limit=min(len(before),len(after))
    while prefix<limit and before[prefix]==after[prefix]:prefix+=1
    suffix=0
    while suffix<limit-prefix and before[-suffix-1]==after[-suffix-1]:suffix+=1
    equal=None
    result={}
    for item in locks:
        if item['end']<=prefix:
            result[item['lock_id']]=(item['start'],item['end']);continue
        if item['start']>=len(before)-suffix:
            offset=len(after)-len(before)
            result[item['lock_id']]=(item['start']+offset,item['end']+offset);continue
        text=before[item['start']:item['end']]
        require(before.find(text)==before.rfind(text) and after.find(text)==after.rfind(text),'ambiguous_locked_body_range')
        if equal is None:equal=[(a,b,c,d) for tag,a,b,c,d in SequenceMatcher(None,before,after,autojunk=True).get_opcodes() if tag=='equal']
        match=next(((a,c) for a,b,c,d in equal if a<=item['start'] and item['end']<=b),None)
        require(match is not None,'locked_body_range_changed')
        offset=match[1]-match[0]
        result[item['lock_id']]=(item['start']+offset,item['end']+offset)
    return result

def validate_state(state):
    events=state.get(COLLECTION,[])
    require(type(events) is list,'invalid_events')
    project=state['document']['project']['id']
    chapters={item['id']:item for item in state['document']['chapters']}
    versions={item['id']:item for item in state['document']['versions']}
    seen=set();operations=set();locks={};lock_ids=set()
    first_lifecycle=next((event for event in events if type(event) is dict and event.get('kind')=='lifecycle'),None)
    if first_lifecycle:require(type(first_lifecycle.get('data')) is dict,'invalid_lifecycle_origin')
    status=first_lifecycle.get('data',{}).get('before') if first_lifecycle else ('archived' if state['document']['project']['status']=='archived' else 'active')
    require(status in ('active','archived'),'invalid_lifecycle_origin')
    restore_state='active'
    for event in events:
        require(type(event) is dict and set(event)=={'id','project_id','operation_id','kind','data','created_at'},'invalid_event_fields')
        _uuid(event['id']);_uuid(event['operation_id']);_timestamp(event['created_at'],'author_scope.created_at')
        require(event['id'] not in seen and event['operation_id'] not in operations and event['project_id']==project,'duplicate_or_foreign_event')
        seen.add(event['id']);operations.add(event['operation_id']);data=event['data'];kind=event['kind']
        require(type(data) is dict,'invalid_event_data')
        if kind=='lifecycle':
            require(set(data)=={'action','before','after','restore_state','title_snapshot'},'invalid_lifecycle_fields')
            require(data['before']==status and type(data['title_snapshot']) is str,'invalid_lifecycle_source')
            action=data['action']
            if action=='archive':require(status=='active' and data['after']=='archived' and data['restore_state']=='active','invalid_archive')
            elif action=='trash':require(status in ('active','archived') and data['after']=='deleted' and data['restore_state']==status,'invalid_trash')
            elif action=='restore':require(status in ('archived','deleted') and data['after']==('active' if status=='archived' else restore_state) and data['restore_state']=='active','invalid_restore')
            else:require(False,'invalid_lifecycle_action')
            restore_state=data['restore_state'];status=data['after']
        elif kind in ('lock','rebase'):
            require(set(data)=={'lock_id','chapter_id','version_id','body_sha256','start','end','text_sha256'},'invalid_lock_fields')
            _uuid(data['lock_id']);require(data['chapter_id'] in chapters,'missing_chapter')
            version=versions.get(data['version_id'])
            require(version is not None and version['entity_type']=='chapter' and version['entity_id']==data['chapter_id'],'invalid_lock_version')
            body=version['snapshot']['content']
            require(type(data['start']) is int and type(data['end']) is int and 0<=data['start']<data['end']<=len(body),'invalid_codepoint_range')
            require(data['body_sha256']==digest(body) and data['text_sha256']==digest(body[data['start']:data['end']]),'lock_hash_mismatch')
            old=locks.get(data['lock_id'])
            if kind=='lock':
                require(data['lock_id'] not in lock_ids and status=='active','duplicate_lock_or_inactive')
                lock_ids.add(data['lock_id'])
                require(not any(item['chapter_id']==data['chapter_id'] and max(item['start'],data['start'])<min(item['end'],data['end']) for item in locks.values()),'overlapping_lock')
                require(sum(item['chapter_id']==data['chapter_id'] for item in locks.values())<128,'lock_limit')
            else:require(old is not None and old['chapter_id']==data['chapter_id'] and old['text_sha256']==data['text_sha256'],'invalid_lock_rebase')
            locks[data['lock_id']]=data
        elif kind=='unlock':
            require(set(data)=={'lock_id','version_id'} and data['lock_id'] in locks,'invalid_unlock')
            require(status=='active' and data['version_id']==locks[data['lock_id']]['version_id'],'stale_unlock')
            locks.pop(data['lock_id'])
        else:require(False,'unknown_event_kind')
    for item in locks.values():
        chapter=chapters[item['chapter_id']]
        require(chapter['current_version_id']==item['version_id'] and digest(chapter['content'])==item['body_sha256'],'stale_active_lock')

def validate_transition(state,previous):
    old_events=previous.get(COLLECTION,[]);events=state.get(COLLECTION,[])
    require(events[:len(old_events)]==old_events,'history_is_append_only')
    added=events[len(old_events):]
    controls=[event for event in added if event['kind']!='rebase']
    if controls:
        require(len(controls)==1 and len(added)==1,'control_must_be_separate')
        if controls[0]['kind']=='lifecycle':require(controls[0]['data']['before']==project_state(previous),'stale_lifecycle_source')
        for key,value in previous.items():
            if key not in ('revision','workspace_version',COLLECTION):require(state.get(key)==value,'control_cannot_edit_content')
        if project_state(previous)!='active':require(controls[0]['kind']=='lifecycle','inactive_project')
        if controls[0]['kind']=='lock':
            data=controls[0]['data'];chapter=next(item for item in previous['document']['chapters'] if item['id']==data['chapter_id'])
            require(data['version_id']==chapter['current_version_id'],'stale_lock_source')
        return
    require(project_state(previous)=='active' or state==previous,'inactive_project')
    before={item['id']:item for item in previous['document']['chapters']}
    after={item['id']:item for item in state['document']['chapters']}
    active=active_locks(previous);required={}
    for chapter_id in {item['chapter_id'] for item in active.values()}:
        require(chapter_id in after,'locked_chapter_cannot_be_removed')
        locks=[item for item in active.values() if item['chapter_id']==chapter_id]
        mapping=mapped_ranges(before[chapter_id]['content'],after[chapter_id]['content'],locks)
        for lock in locks:
            if after[chapter_id]['current_version_id']!=lock['version_id']:
                required[lock['lock_id']]=(after[chapter_id],mapping[lock['lock_id']])
    require(len(added)==len(required),'missing_or_unexpected_lock_rebase')
    for event in added:
        data=event['data'];expected=required.pop(data['lock_id'],None)
        require(event['kind']=='rebase' and expected is not None,'unexpected_lock_rebase')
        chapter,positions=expected
        require((data['version_id'],data['start'],data['end'])==(chapter['current_version_id'],*positions),'incorrect_lock_rebase')

def guard_and_rebase(previous,state):
    """Central persistence gate for manual save, restore and every AI adopter."""
    controls=state.get(COLLECTION,[])[len(previous.get(COLLECTION,[])):]
    if any(event['kind']!='rebase' for event in controls):
        validate_transition(state,previous);return
    require(project_state(previous)=='active','inactive_project')
    locks=active_locks(previous)
    if not locks:return
    before={item['id']:item for item in previous['document']['chapters']}
    after={item['id']:item for item in state['document']['chapters']}
    for chapter_id in {item['chapter_id'] for item in locks.values()}:
        require(chapter_id in after,'locked_chapter_cannot_be_removed')
        relevant=[item for item in locks.values() if item['chapter_id']==chapter_id]
        mapping=mapped_ranges(before[chapter_id]['content'],after[chapter_id]['content'],relevant)
        chapter=after[chapter_id]
        for lock in relevant:
            if chapter['current_version_id']==lock['version_id']:continue
            start,end=mapping[lock['lock_id']]
            identity=str(uuid5(NAMESPACE_URL,'author-range-rebase/'+lock['lock_id']+'/'+chapter['current_version_id']))
            state[COLLECTION].append(dict(id=identity,project_id=state['document']['project']['id'],operation_id=identity,kind='rebase',
                data=dict(lock,version_id=chapter['current_version_id'],body_sha256=digest(chapter['content']),start=start,end=end),created_at=chapter['updated_at']))

def remap_events(state,ref):
    for event in state.get(COLLECTION,[]):
        for key,kind in (('id','author_scope_event'),('project_id','project'),('operation_id','author_scope_operation')):event[key]=ref(kind,event[key])
        data=event['data']
        for key,kind in (('lock_id','body_range_lock'),('chapter_id','chapter'),('version_id','version')):
            if key in data:data[key]=ref(kind,data[key])
