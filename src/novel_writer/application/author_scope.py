"""Explicit author lifecycle/range operations; no persistent unlock permission."""
from uuid import NAMESPACE_URL,uuid5
from novel_writer.domain.author_scope import COLLECTION,active_locks,digest,project_state,require
from novel_writer.domain.models import utc_now
from novel_writer.domain.tasks import uuid_value
from novel_writer.storage.sqlite_repository import ConflictError

def upgrade(state):
    from novel_writer.application.chapter_lifecycle import upgrade as previous
    previous(state);state['workspace_version']=max(state['workspace_version'],48);state.setdefault(COLLECTION,[])
    state.setdefault('rule_task_bindings',[]);state.setdefault('deep_review_actions',[]);state.setdefault('memory_automation_events',[])
    from novel_writer.domain.body_planning import COLLECTIONS as BODY_PLANNING_COLLECTIONS
    from novel_writer.domain.graph_extraction import COLLECTIONS as GRAPH_COLLECTIONS
    from novel_writer.domain.rule_reviews import COLLECTIONS as RULE_REVIEW_COLLECTIONS
    from novel_writer.domain.model_planning import COLLECTIONS as MODEL_PLANNING_COLLECTIONS
    for name in (*BODY_PLANNING_COLLECTIONS,*GRAPH_COLLECTIONS,*RULE_REVIEW_COLLECTIONS,*MODEL_PLANNING_COLLECTIONS):state.setdefault(name,[])

def describe(state):
    return dict(project_state=project_state(state),revision=state['revision'],locks=list(active_locks(state).values()),
                lifecycle=[item for item in state.get(COLLECTION,[]) if item['kind']=='lifecycle'],
                unlock_permission='none; every unlock requires fresh explicit author confirmation',
                coordinates='Unicode code points, end exclusive')

def preview(state,action):
    require(action in ('archive','trash','restore'),'invalid_action')
    status=project_state(state)
    require(status=='active' if action=='archive' else status in ('active','archived') if action=='trash' else status in ('archived','deleted'),'invalid_lifecycle_source')
    doc=state['document']
    return dict(action=action,expected_revision=state['revision'],project_id=doc['project']['id'],title=doc['project']['title'],state=status,
                chapters=len(doc['chapters']),entity_versions=len(doc['versions']),body_characters=sum(len(item['content']) for item in doc['chapters']),
                active_range_locks=len(active_locks(state)),physical_deletion=False,
                effects='归档/回收后禁止正文及模型写入；正文、稳定ID、版本、范围锁和历史保留。恢复不授予模型外发或解锁许可。')

def execute(repository,project,action,values,expected_revision):
    require(type(values) is dict,'invalid_request')
    identity=values.get('operation_id');uuid_value(identity)
    def operation(state):
        old=next((item for item in state.get(COLLECTION,[]) if item['operation_id']==identity),None)
        # Replay is not permission: callers must still bind their current revision.
        if type(expected_revision) is not int or state['revision']!=expected_revision:raise ConflictError('保存编号已变化，请重新预览后确认')
        require(values.get('confirmed') is True,'explicit_confirmation_required')
        require(old is None,'operation_already_used')
        upgrade(state)
        if action in ('archive_project','trash_project','restore_project'):
            require(set(values)=={'operation_id','confirmed','confirm_title'},'invalid_lifecycle_fields')
            require(values['confirm_title']==state['document']['project']['title'],'exact_title_confirmation_required')
            kind=action.split('_')[0];preview(state,kind);before=project_state(state)
            last=next((item for item in reversed(state[COLLECTION]) if item['kind']=='lifecycle'),None)
            after='archived' if kind=='archive' else 'deleted' if kind=='trash' else 'active' if before=='archived' else last['data']['restore_state']
            data=dict(action=kind,before=before,after=after,restore_state=before if kind=='trash' else 'active',title_snapshot=values['confirm_title'])
            event_kind='lifecycle'
        elif action=='lock_body_range':
            require(set(values)=={'operation_id','confirmed','chapter_id','version_id','body_sha256','start','end','text_sha256'},'invalid_range_fields')
            require(project_state(state)=='active','inactive_project')
            chapter=next((item for item in state['document']['chapters'] if item['id']==values['chapter_id']),None)
            require(chapter is not None and chapter['current_version_id']==values['version_id'] and digest(chapter['content'])==values['body_sha256'],'stale_lock_source')
            data={key:values[key] for key in ('chapter_id','version_id','body_sha256','start','end','text_sha256')}
            data['lock_id']=str(uuid5(NAMESPACE_URL,identity+'/body-range-lock'));event_kind='lock'
        elif action=='unlock_body_range':
            require(set(values)=={'operation_id','confirmed','lock_id','version_id'},'invalid_unlock_fields')
            require(project_state(state)=='active','inactive_project')
            lock=active_locks(state).get(values['lock_id'])
            require(lock is not None and lock['version_id']==values['version_id'],'stale_unlock')
            data=dict(lock_id=values['lock_id'],version_id=values['version_id']);event_kind='unlock'
        else:require(False,'unknown_action')
        state[COLLECTION].append(dict(id=str(uuid5(NAMESPACE_URL,identity+'/author-scope-event')),project_id=project,operation_id=identity,kind=event_kind,data=data,created_at=utc_now()))
        return state,None
    repository.atomic(project,operation,identity_claim=(COLLECTION,'operation_id',identity))
    return repository.get(project)
