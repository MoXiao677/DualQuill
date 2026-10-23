"""Local, transactional refresh queue. Never calls a model."""
from copy import deepcopy
from uuid import uuid4
from novel_writer.domain.tasks import require, uuid_value
from novel_writer.domain.memory import capture_source, outdated
from novel_writer.domain.models import utc_now
from novel_writer.application.incremental_memory import impact, digest
from novel_writer.storage.sqlite_repository import ConflictError

COLLECTION='memory_refresh_events'

def upgrade(state):
    from novel_writer.application.semantic_retrieval import upgrade as prior
    prior(state);state['workspace_version']=max(50,state['workspace_version']);state.setdefault(COLLECTION,[])

def automatic(state):
    entries=[e for e in state.get(COLLECTION,[]) if e['kind']=='policy']
    return bool(entries and entries[-1]['project_id']==state['document']['project']['id'] and entries[-1]['auto_refresh'])

def sources(state,ids):
    return [capture_source(state,dict(kind='chapter',entity_id=i)) for i in ids]

def append(state,kind,**values):
    entry=dict(id=str(uuid4()),kind=kind,revision=state['revision'],**values)
    state[COLLECTION].append(entry);return entry

def rebuild(state,rollup):
    from novel_writer.application.memory_rollups import _build,_chapter
    chapter=_chapter(state,rollup['through_chapter_id'])
    built=_build(state,rollup['scope'],rollup['scope_volume_number'],chapter)
    require(not built['conflicts'],'刷新汇总存在冲突，请先核对记忆')
    old=deepcopy(rollup);now=utc_now()
    rollup.update(revision=old['revision']+1,title=built['title'],text=built['text'],sources=built['sources'],updated_at=now)
    if rollup['scope']=='chapter':
        rollup['through_position']=chapter['number'];rollup['chapter_source']=capture_source(state,dict(kind='chapter',entity_id=chapter['id']))
    previous=next(e for e in reversed(state['memory_rollup_history']) if e['rollup_id']==rollup['id'])
    state['memory_rollup_history'].append(dict(id=str(uuid4()),rollup_id=rollup['id'],revision=rollup['revision'],previous_version_id=previous['id'],snapshot=deepcopy(rollup),saved_at=now,action='rebuild',operation_id=str(uuid4())))

def perform(state,job,texts):
    """All-or-nothing local content edits and dependent rollups."""
    from novel_writer.application.memories import save
    from novel_writer.application.chapter_lifecycle import is_hidden
    require(type(texts) is dict and set(texts)<=set(job['memory_ids']),'刷新文本不属于本队列')
    result=deepcopy(state)
    for identifier in job['memory_ids']:
        memory=next(m for m in result['memories'] if m['id']==identifier)
        if not memory['active'] or not outdated(result,memory['source']):continue
        require(memory['source']['kind']=='chapter','非正文来源请使用原显式复核流程')
        cid=memory['source']['chapter_id'];require(not is_hidden(result,cid),'来源章节已归档或回收')
        replacement=texts.get(identifier)
        if replacement is None:
            require(memory['kind']=='chapter_summary','人工事实需要作者核对并填写刷新文本')
            replacement=next(c['content'] for c in result['document']['chapters'] if c['id']==cid)
        require(type(replacement) is str and bool(replacement.strip()),'刷新文本不能为空')
        result=save(result,'save_memory',dict(memory_id=identifier,text=replacement))
        result=save(result,'review_memory',dict(memory_id=identifier,confirmed=memory['confirmed']))
    for identifier in job['rollup_ids']:
        rollup=next(r for r in result['memory_rollups'] if r['id']==identifier)
        rebuild(result,rollup)
    return result

def attempt(state,job,texts,operation_id,request_hash):
    current_sources=sources(state,job['chapter_ids'])
    try:
        # Reject obsolete jobs; a newer save has its own queue entry.
        require([(s['version_id'],s['source_sha256']) for s in current_sources]==[(s['version_id'],s['source_sha256']) for s in job['sources']],'来源已再次修改，请处理最新待刷新项')
        result=perform(state,job,texts);status='succeeded';error=''
    except Exception as exc:
        result=state;status='failed';error=str(exc) or type(exc).__name__
    append(result,'attempt',operation_id=operation_id,request_sha256=request_hash,job_id=job['id'],status=status,error=error,sources=current_sources)
    return result,status,error

def record(previous,current):
    # Only saved chapter changes enqueue; memory edits cannot recursively queue.
    changed=impact(previous,current)
    if not changed['chapter_ids'] or not (changed['memory_ids'] or changed['rollup_ids']):return
    upgrade(current)
    revision=current['revision'];current['revision']=previous['revision']+1
    job=append(current,'impact',**changed,sources=sources(current,changed['chapter_ids']))
    if automatic(previous):
        updated,_,_=attempt(current,job,{},str(uuid4()),digest(dict(auto_job=job['id'])))
        if updated is not current:
            current.clear();current.update(updated)
    current['revision']=revision

class MemoryRefresh:
    def __init__(self,service):self.service=service
    def listing(self,project):
        state=self.service.get(project);events=state.get(COLLECTION,[]);queue=[]
        for job in events:
            if job['kind']!='impact':continue
            attempts=[e for e in events if e.get('job_id')==job['id']]
            last=attempts[-1] if attempts else {}
            queue.append(dict(deepcopy(job),status=last.get('status','pending'),error=last.get('error',''),attempts=deepcopy(attempts)))
        return dict(revision=state['revision'],auto_refresh=automatic(state),queue=queue)
    def change(self,project,request):
        require(type(request) is dict,'刷新请求无效')
        action=request.get('action');require(action in ('policy','refresh'),'未知刷新动作')
        fields={'action','operation_id','expected_revision'}|({'auto_refresh'} if action=='policy' else {'job_id','memory_texts'})
        require(set(request)==fields,'刷新请求字段不完整或含未知字段')
        identity=uuid_value(request['operation_id']);expected=request['expected_revision']
        require(type(expected) is int and expected>=1,'刷新保存编号无效')
        if action=='policy':require(type(request['auto_refresh']) is bool,'自动刷新开关必须为布尔值')
        else:uuid_value(request['job_id']);require(type(request['memory_texts']) is dict,'刷新文本无效')
        hashed=digest(request)
        def operation(state):
            events=state.get(COLLECTION,[])
            old=next((e for e in events if e.get('operation_id')==identity),None)
            if old:
                require(old['request_sha256']==hashed,'刷新操作编号已用于其他请求')
                return None,dict(revision=state['revision'],idempotent=True,status=old.get('status','saved'),error=old.get('error',''))
            if state['revision']!=expected:raise ConflictError('来源或刷新队列已变化，请重新读取')
            upgrade(state)
            if action=='policy':
                entry=append(state,'policy',operation_id=identity,request_sha256=hashed,project_id=project,auto_refresh=request['auto_refresh'])
                entry['revision']=expected+1;status='saved';error=''
            else:
                job=next((e for e in events if e['kind']=='impact' and e['id']==request['job_id']),None)
                require(job is not None,'待刷新项不存在')
                latest=next((e for e in reversed(events) if e.get('job_id')==job['id']),None)
                require(not latest or latest['status']!='succeeded','该项已经刷新完成')
                state,status,error=attempt(state,job,request['memory_texts'],identity,hashed)
                state[COLLECTION][-1]['revision']=expected+1
            return state,dict(revision=expected+1,idempotent=False,status=status,error=error)
        return self.service.repository.atomic(project,operation,identity_claim=(COLLECTION,'operation_id',identity))

