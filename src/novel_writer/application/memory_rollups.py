"""Explicit book/volume memory rollups and derived conflict reports."""
from copy import deepcopy
from uuid import uuid4
from novel_writer.domain.memory import effective_position,outdated,capture_source,MemorySource
from novel_writer.domain.memory_rollups import (
    KINDS,MemoryRollup,MemoryRollupEdit,RollupSource,render_text,source_sort_key,
)
from novel_writer.domain.models import utc_now
from novel_writer.domain.tasks import encode,require,uuid_value
from novel_writer.application.fields import check_fields
from novel_writer.storage.sqlite_repository import ConflictError


def upgrade(state):
    from novel_writer.application.scoped_rules import upgrade as previous
    previous(state);state['workspace_version']=max(state['workspace_version'],23)
    state.setdefault('memory_rollups',[]);state.setdefault('memory_rollup_history',[])
    return state


def _chapter(state,chapter_id):
    return next((value for value in state['document']['chapters'] if value['id']==chapter_id),None)


def _effective_chapter(state,memory):
    declared=_chapter(state,memory['position_chapter_id'])
    sourced=_chapter(state,memory['source']['chapter_id']) if memory['source']['chapter_id'] else None
    require(declared is not None,'memory_rollups.invalid_memory_position')
    return sourced if sourced is not None and sourced['number']>declared['number'] else declared


def _volume(state,number):
    outline=state['document']['book_outline']
    return next((value for value in (outline['volumes'] if outline else []) if value['number']==number),None)


def _parse_scope(state,request_fields):
    check_fields(request_fields,{'scope','scope_volume_number','through_chapter_id'})
    require(set(request_fields)=={'scope','scope_volume_number','through_chapter_id'},'memory_rollups.invalid_scope_request')
    scope=request_fields['scope'];volume_number=request_fields['scope_volume_number'];through_id=request_fields['through_chapter_id']
    require(scope in ('book','volume','chapter'),'memory_rollups.invalid_scope')
    chapter=_chapter(state,through_id)
    require(chapter is not None,'memory_rollups.invalid_through_chapter')
    if scope in ('book','chapter'):
        require(volume_number is None,'memory_rollups.invalid_scope')
        if scope=='chapter':
            from novel_writer.domain.chapter_lifecycle import require_active
            require_active(state,through_id)
        return scope,None,chapter
    volume=_volume(state,volume_number)
    require(volume is not None,'memory_rollups.invalid_volume')
    require(through_id in volume['chapter_ids'],'memory_rollups.through_not_in_volume')
    return scope,volume_number,chapter


def _in_volume(state,memory,volume):
    if memory['volume_number'] is not None:
        return memory['volume_number']==volume['number']
    return _effective_chapter(state,memory)['id'] in volume['chapter_ids']


def _eligible(state,scope,volume_number,through_position):
    volume=_volume(state,volume_number) if scope=='volume' else None
    if scope=='chapter':
        from novel_writer.domain.chapter_trash import hidden_ids
        hidden=hidden_ids(state)
    result=[]
    for memory in state.get('memories',[]):
        if not memory['active'] or not memory['confirmed']:continue
        if outdated(state,memory['source']):continue
        chapter=_effective_chapter(state,memory)
        if chapter['number']>through_position:continue
        if scope=='chapter':
            if chapter['number']!=through_position or chapter['id'] in hidden or memory['position_chapter_id'] in hidden or memory['source']['chapter_id'] in hidden:continue
        if volume is not None and not _in_volume(state,memory,volume):continue
        result.append(memory)
    return result


def _conflicts_from(state,memories):
    groups={}
    for memory in memories:
        chapter=_effective_chapter(state,memory)
        key=(memory['kind'],memory['character_id'],memory['volume_number'],chapter['id'],memory['title'].strip())
        groups.setdefault(key,[]).append(memory)
    conflicts=[]
    for (kind,character_id,volume_number,position_id,title),items in groups.items():
        texts={item['text'].strip() for item in items}
        if len(texts)<2:continue
        items=sorted(items,key=lambda value:value['id'])
        conflicts.append(dict(kind=kind,title=title,character_id=character_id,volume_number=volume_number,
            position_chapter_id=position_id,memory_ids=[item['id'] for item in items],
            texts=[dict(memory_id=item['id'],revision=item['revision'],text=item['text']) for item in items]))
    return sorted(conflicts,key=lambda value:(value['position_chapter_id'],value['title'],value['memory_ids']))


def conflicts(state,scope=None,volume_number=None,through_chapter_id=None):
    if scope is None:
        memories=[memory for memory in state.get('memories',[])
            if memory['active'] and memory['confirmed'] and not outdated(state,memory['source'])]
    else:
        _scope,_volume_number,chapter=_parse_scope(state,dict(scope=scope,scope_volume_number=volume_number,through_chapter_id=through_chapter_id))
        memories=_eligible(state,_scope,_volume_number,chapter['number'])
    return _conflicts_from(state,memories)


def _sources(state,memories):
    sources=[]
    for memory in memories:
        chapter=_effective_chapter(state,memory)
        sources.append(RollupSource(memory_id=memory['id'],memory_revision=memory['revision'],kind=memory['kind'],
            title=memory['title'],text=memory['text'],position_chapter_id=chapter['id'],position_number=chapter['number'],
            character_id=memory['character_id'],volume_number=memory['volume_number']))
    return sorted(sources,key=source_sort_key)


def _title(state,scope,volume_number,chapter):
    project=state['document']['project']['title']
    if scope=='book':return project+' · 全书记忆汇总（截至第'+str(chapter['number'])+'章）'
    if scope=='chapter':return project+' · 第'+str(chapter['number'])+'章《'+chapter['title']+'》独立记忆汇总'
    volume=_volume(state,volume_number);label=volume['title'].strip() or '未命名'
    return project+' · 第'+str(volume_number)+'卷《'+label+'》记忆汇总（截至第'+str(chapter['number'])+'章）'


def _build(state,scope,volume_number,chapter):
    if scope=='chapter':
        from novel_writer.domain.chapter_lifecycle import require_active
        require(chapter is not None,'memory_rollups.invalid_through_chapter');require_active(state,chapter['id'])
    memories=_eligible(state,scope,volume_number,chapter['number'])
    sources=_sources(state,memories)
    title=_title(state,scope,volume_number,chapter)
    return dict(scope=scope,scope_volume_number=volume_number,through_chapter_id=chapter['id'],
        through_position=chapter['number'],title=title,text=render_text(title,sources),
        sources=[encode(source) for source in sources],source_memory_ids=[source.memory_id for source in sources],
        conflicts=_conflicts_from(state,memories),eligible_count=len(memories))


def _find(state,scope,volume_number,through_id):
    return next((value for value in state.get('memory_rollups',[])
        if value['scope']==scope and value['scope_volume_number']==volume_number and value['through_chapter_id']==through_id),None)


def context_candidates(state,chapter,scope):
    """Read-only deterministic selection; excluded reports contain no source prose."""
    from novel_writer.domain.chapter_trash import hidden_ids
    hidden=hidden_ids(state);cutoff=chapter['number']-(scope=='previous')
    volume=next((v for v in (state['document']['book_outline'] or {}).get('volumes',[]) if chapter['id'] in v['chapter_ids']),None)
    conflict_ids={i for c in conflicts(state) for i in c['memory_ids']}
    memories={m['id']:m for m in state.get('memories',[])};chosen=set();result=[]
    candidates=sorted(state.get('memory_rollups',[]),key=lambda r:(-r['through_position'],{'chapter':0,'volume':1,'book':2}[r['scope']],r['id']))
    for r in candidates:
        reason='selected_rollup'
        if r['project_id']!=state['document']['project']['id']:reason='rollup_other_book'
        elif r['through_position']>cutoff or (_chapter(state,r['through_chapter_id']) or {}).get('number',cutoff+1)>cutoff:reason='rollup_current' if r['through_position']==chapter['number'] else 'rollup_future'
        elif r['through_chapter_id'] in hidden:reason='rollup_hidden'
        elif r['scope']=='volume' and (volume is None or volume['number']!=r['scope_volume_number'] or r['through_chapter_id'] not in volume['chapter_ids']):reason='rollup_other_volume'
        elif any(s['position_number']>cutoff for s in r['sources']):reason='rollup_future_source'
        elif any(s['position_chapter_id'] in hidden or (memories.get(s['memory_id']) or {}).get('source',{}).get('chapter_id') in hidden or (memories.get(s['memory_id']) or {}).get('position_chapter_id') in hidden for s in r['sources']):reason='rollup_hidden_source'
        elif any(s['memory_id'] in conflict_ids for s in r['sources']):reason='rollup_conflict'
        elif stale(state,r):reason='rollup_stale'
        key=(r['scope'],r['scope_volume_number'],r['through_chapter_id'] if r['scope']=='chapter' else None)
        if reason=='selected_rollup':
            if key in chosen:reason='rollup_superseded'
            else:chosen.add(key)
        edit=next(v for v in reversed(state['memory_rollup_history']) if v['rollup_id']==r['id'])
        result.append((r,edit['id'],reason))
    return result


def stale(state,rollup):
    if rollup['scope']=='chapter':
        from novel_writer.domain.chapter_trash import hidden_ids
        if _chapter(state,rollup['through_chapter_id']) is None or rollup['through_chapter_id'] in hidden_ids(state):return True
        if outdated(state,rollup['chapter_source']):return True
    review=_build(state,rollup['scope'],rollup['scope_volume_number'],_chapter(state,rollup['through_chapter_id']))
    return review['sources']!=rollup['sources']


class MemoryRollups:
    def __init__(self,service):
        self.service=service;self.repository=service.repository

    def preview(self,project,request):
        state=self.service.get(project);scope,volume_number,chapter=_parse_scope(state,request)
        result=_build(state,scope,volume_number,chapter);existing=_find(state,scope,volume_number,chapter['id'])
        result.update(revision=state['revision'],can_save=not result['conflicts'],
            existing=dict(id=existing['id'],revision=existing['revision'],stale=stale(state,existing)) if existing else None)
        return result

    def listing(self,project):
        state=self.service.get(project)
        values=[]
        for rollup in state.get('memory_rollups',[]):
            value=deepcopy(rollup);value['stale']=stale(state,rollup)
            if rollup['scope']=='chapter':
                from novel_writer.domain.chapter_trash import hidden_ids
                value['available']=_chapter(state,rollup['through_chapter_id']) is not None and rollup['through_chapter_id'] not in hidden_ids(state)
                value['unavailable_reason']='' if value['available'] else '目标章节已归档、在回收站或缺失；恢复后才能预览或重建'
            value['source_memory_ids']=[source['memory_id'] for source in rollup['sources']]
            values.append(value)
        return dict(revision=state['revision'],rollups=values,conflicts=conflicts(state))

    def save(self,project,request):
        check_fields(request,{'operation_id','scope','scope_volume_number','through_chapter_id','expected_revision'})
        require(set(request)=={'operation_id','scope','scope_volume_number','through_chapter_id','expected_revision'},'memory_rollups.invalid_request')
        identity=uuid_value(request['operation_id']);expected=request['expected_revision']
        require(type(expected) is int and expected>=1,'memory_rollups.invalid_expected_revision')
        def operation(state):
            entry=next((value for value in state.get('memory_rollup_history',[]) if value['operation_id']==identity),None)
            if entry is not None:
                snapshot=entry['snapshot']
                require(snapshot['scope']==request['scope'] and snapshot['scope_volume_number']==request['scope_volume_number'] and snapshot['through_chapter_id']==request['through_chapter_id'],'memory_rollups.operation_reused')
                return None,dict(revision=state['revision'],idempotent=True,rollup=deepcopy(snapshot),conflicts=conflicts(state))
            if state['revision']!=expected:raise ConflictError('小说已更新，请重新预览记忆汇总后再保存')
            scope,volume_number,chapter=_parse_scope(state,{key:request[key] for key in ('scope','scope_volume_number','through_chapter_id')})
            existing=_find(state,scope,volume_number,chapter['id'])
            require(existing is None,'memory_rollups.already_exists')
            built=_build(state,scope,volume_number,chapter);require(not built['conflicts'],'memory_rollups.conflicts_unresolved')
            upgrade(state)
            if scope=='chapter':
                from novel_writer.application.chapter_lifecycle import upgrade as upgrade_chapters
                upgrade_chapters(state);state['workspace_version']=max(state['workspace_version'],31)
            now=utc_now();identifier=str(uuid4())
            rollup=MemoryRollup(id=identifier,project_id=project,revision=1,scope=scope,scope_volume_number=volume_number,
                through_chapter_id=chapter['id'],through_position=chapter['number'],title=built['title'],text=built['text'],
                sources=tuple(RollupSource(**value) for value in built['sources']),created_at=now,updated_at=now,
                chapter_source=MemorySource(**capture_source(state,dict(kind='chapter',entity_id=chapter['id']))) if scope=='chapter' else None)
            encoded=encode(rollup);history=MemoryRollupEdit(id=str(uuid4()),rollup_id=identifier,revision=1,
                previous_version_id=None,snapshot=rollup,saved_at=now,action='create',operation_id=identity)
            state['memory_rollups'].append(encoded);state['memory_rollup_history'].append(encode(history))
            return state,dict(revision=state['revision']+1,idempotent=False,rollup=deepcopy(encoded),conflicts=[])
        return self.repository.atomic(project,operation,identity_claim=('memory_rollup_history','operation_id',identity))

    def rebuild(self,project,rollup_id,request):
        check_fields(request,{'operation_id','expected_revision','expected_rollup_revision'})
        require(set(request)=={'operation_id','expected_revision','expected_rollup_revision'},'memory_rollups.invalid_rebuild_request')
        identity=uuid_value(request['operation_id']);uuid_value(rollup_id);expected=request['expected_revision'];rollup_revision=request['expected_rollup_revision']
        require(type(expected) is int and expected>=1 and type(rollup_revision) is int and rollup_revision>=1,'memory_rollups.invalid_expected_revision')
        def operation(state):
            entry=next((value for value in state.get('memory_rollup_history',[]) if value['operation_id']==identity),None)
            if entry is not None:
                require(entry['rollup_id']==rollup_id,'memory_rollups.operation_reused')
                return None,dict(revision=state['revision'],idempotent=True,rollup=deepcopy(entry['snapshot']),conflicts=conflicts(state))
            if state['revision']!=expected:raise ConflictError('小说已更新，请重新读取记忆汇总后再重建')
            existing=next((value for value in state.get('memory_rollups',[]) if value['id']==rollup_id),None)
            require(existing is not None,'memory_rollups.not_found')
            if existing['revision']!=rollup_revision:raise ConflictError('记忆汇总已在其他窗口重建，请重新读取')
            chapter=_chapter(state,existing['through_chapter_id']);require(chapter is not None,'memory_rollups.invalid_through_chapter')
            built=_build(state,existing['scope'],existing['scope_volume_number'],chapter);require(not built['conflicts'],'memory_rollups.conflicts_unresolved')
            upgrade(state);now=utc_now()
            rollup=MemoryRollup(id=existing['id'],project_id=project,revision=existing['revision']+1,scope=existing['scope'],
                scope_volume_number=existing['scope_volume_number'],through_chapter_id=existing['through_chapter_id'],
                through_position=chapter['number'] if existing['scope']=='chapter' else existing['through_position'],title=built['title'],text=built['text'],
                sources=tuple(RollupSource(**value) for value in built['sources']),created_at=existing['created_at'],updated_at=now,
                chapter_source=MemorySource(**capture_source(state,dict(kind='chapter',entity_id=chapter['id']))) if existing['scope']=='chapter' else None)
            encoded=encode(rollup);history_entries=[value for value in state['memory_rollup_history'] if value['rollup_id']==rollup_id]
            history=MemoryRollupEdit(id=str(uuid4()),rollup_id=rollup_id,revision=rollup.revision,
                previous_version_id=history_entries[-1]['id'],snapshot=rollup,saved_at=now,action='rebuild',operation_id=identity)
            existing.clear();existing.update(encoded);state['memory_rollup_history'].append(encode(history))
            return state,dict(revision=state['revision']+1,idempotent=False,rollup=deepcopy(encoded),conflicts=[])
        return self.repository.atomic(project,operation,identity_claim=('memory_rollup_history','operation_id',identity))
