"""One transaction for a manual chapter save from a validated workspace.

Only the edited chapter is materialized here. The repository still validates
the complete new document, domain collections and history before committing.
"""
from dataclasses import asdict
from copy import deepcopy
from novel_writer.application import chapters
from novel_writer.application.fields import check_fields
from novel_writer.domain.models import Chapter,NovelDocument,NovelProject,VersionRecord,utc_now
from novel_writer.storage.sqlite_repository import ConflictError


def save(repository,project_id,values,expected_revision):
    def operation(state):
        check_fields(values,{'chapter_id','title','content','status','authorize_confirmed','canon_analysis'})
        if type(expected_revision) is not int or state['revision']!=expected_revision:
            raise ConflictError('小说已更新，请保留当前输入并重新打开最新内容')
        from novel_writer.application.knowledge import enforce_plan_locks
        from novel_writer.application.book_creation import enforce_formal_locks
        enforce_plan_locks(state,'save_chapter',values);enforce_formal_locks(state,'save_chapter',values)
        previous=deepcopy(state)
        raw=state['document'];target=next((item for item in raw['chapters'] if item['id']==values.get('chapter_id')),None)
        # Keep the established handler's validation/error behavior for missing IDs.
        document=NovelDocument(project=NovelProject(**raw['project']),chapters=[] if target is None else [Chapter(**target)],
            versions=[VersionRecord(**item) for item in raw['versions'] if item['entity_type']=='chapter' and item['entity_id']==values.get('chapter_id')])
        previous_count=len(document.versions)
        chapter_values={key:value for key,value in values.items() if key!='canon_analysis'}
        chapters.save(document,chapter_values)
        chapter=asdict(document.chapters[0])
        if state['workspace_version']==1 and previous_count and repository.has_legacy_defaults(project_id):
            semantic=lambda value:{key:item for key,item in value.items() if key not in ('updated_at','current_version_id')}
            if semantic(chapter)==semantic(target):return None,state
        target.update(chapter)
        raw['versions'].append(asdict(document.versions[-1]))
        raw['project']['updated_at']=utc_now()
        from novel_writer.application.canon_maintenance import on_chapter_saved
        on_chapter_saved(previous,state,values.get('chapter_id'),values.get('canon_analysis'))
        return state,None
    return repository.atomic(project_id,operation,return_workspace=True)
