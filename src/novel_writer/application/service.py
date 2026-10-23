"""业务入口：界面通过此服务访问独立模块和存储。"""
from copy import deepcopy

from novel_writer.application import (
    book_outlines, chapter_outlines, chapters, characters, deepseek_review, generation,
    gemini_revision, ideas, model_dispatch, outline_updates, plot_logic, projects,
    quality, settings, timeline, versions, worldbuilding, writing_rules,
)
from novel_writer.domain.models import DataValidationError, utc_now
from novel_writer.application.fields import text
from novel_writer.storage.json_codec import document_from_dict, document_to_dict
from novel_writer.storage.sqlite_repository import ConflictError


class NovelService:
    def __init__(self, repository):
        self.repository = repository

    def create(self, **values):
        return self.repository.create(projects.create(values))

    def list_projects(self):
        return self.repository.list_projects()

    def get(self, project_id):
        return self.repository.get(text(project_id, "项目编号", required=True))

    def settings(self):
        return settings.safe_status()

    def preview_context(self,project_id,options):
        from novel_writer.application.context_preview import preview
        selected=options.get('search_selections',[]) if type(options) is dict else []
        ids=[s['entity_id'] for s in selected if type(s) is dict and s.get('kind')=='skill' and type(s.get('entity_id')) is str] if type(selected) is list else []
        return preview(self.get(project_id),options,skills=self._skills(ids))

    def trash_preview(self,project_id,chapter_id):
        from novel_writer.application.chapter_lifecycle import preview_trash
        state=self.get(project_id);result=preview_trash(state,text(chapter_id,'章节编号',required=True))
        result['revision']=state['revision'];return result

    def trash_listing(self,project_id):
        from novel_writer.application.chapter_lifecycle import preview_trash
        from novel_writer.domain.chapter_trash import trashed_ids
        state=self.get(project_id);hidden=trashed_ids(state);chapters=sorted(state['document']['chapters'],key=lambda value:value['number'])
        items=[preview_trash(state,value['id']) for value in chapters if value['id'] in hidden]
        return dict(revision=state['revision'],chapters=items)

    def _skills(self,ids):
        from novel_writer.application.fields import text_list
        from novel_writer.storage.skills_repository import SkillsRepository
        ids=text_list(ids,'Skills选择')
        if not ids:return []
        repository=SkillsRepository(self.repository.path)
        try:return [repository.get(identifier) for identifier in dict.fromkeys(ids)]
        except KeyError:raise DataValidationError('选定全局Skills不存在') from None

    def search_local(self,project_id,options):
        from novel_writer.application.retrieval import search
        return search(self.get(project_id),options,self._skills(options.get('skill_ids',[])))

    def memory_records(self,project_id):
        from novel_writer.application.memories import records
        return records(self.get(project_id))

    def memory_automation(self,project_id):
        from novel_writer.application.incremental_memory import IncrementalMemory
        return IncrementalMemory(self).listing(project_id)

    def canon_maintenance(self, project_id):
        from novel_writer.application.canon_maintenance import CanonMaintenance
        return CanonMaintenance(self).listing(project_id)

    def configure_canon_maintenance(self, project_id, request):
        from novel_writer.application.canon_maintenance import CanonMaintenance
        return CanonMaintenance(self).configure(project_id, request)

    def rollback_canon_maintenance(self, project_id, request):
        from novel_writer.application.canon_maintenance import CanonMaintenance
        return CanonMaintenance(self).rollback(project_id, request)

    def change_memory_automation(self,project_id,request):
        from novel_writer.application.incremental_memory import IncrementalMemory
        return IncrementalMemory(self).change(project_id,request)

    def memory_source(self,project_id,memory_id):
        from novel_writer.domain.memory import outdated
        current=self.get(project_id)
        memory=next((m for m in current.get('memories',[]) if m['id']==memory_id),None)
        if memory is None:raise DataValidationError('记忆不存在或不属于当前书')
        source=memory['source'];historical=self.repository.get_revision(project_id,source['workspace_revision']);doc=historical['document']
        kind,identifier=source['kind'],source['entity_id']
        if kind in ('worldbuilding','writing_rules'):value=historical[kind]
        elif kind=='idea':value=historical['ideas'].get(identifier,'')
        elif source['version_id'] is not None:value=next(v['snapshot'] for v in doc['versions'] if v['id']==source['version_id'] and v['entity_id']==identifier and v['entity_type']==kind)
        else:
            collection={'project':[doc['project']],'chapter':doc['chapters'],'character':doc['characters'],'chapter_outline':doc['chapter_outlines'],'book_outline':[doc['book_outline']]}
            value=next(v for v in collection[kind] if v and v['id']==identifier)
        return dict(project_id=project_id,memory_id=memory_id,source=source,value=value,outdated=outdated(current,source))

    def memory_rollups(self,project_id):
        from novel_writer.application.memory_rollups import MemoryRollups
        return MemoryRollups(self).listing(project_id)

    def preview_memory_rollup(self,project_id,options):
        from novel_writer.application.memory_rollups import MemoryRollups
        return MemoryRollups(self).preview(project_id,options)

    def save_memory_rollup(self,project_id,options):
        from novel_writer.application.memory_rollups import MemoryRollups
        return MemoryRollups(self).save(project_id,options)

    def rebuild_memory_rollup(self,project_id,rollup_id,options):
        from novel_writer.application.memory_rollups import MemoryRollups
        return MemoryRollups(self).rebuild(project_id,rollup_id,options)

    def modules(self):
        modules = [projects, book_outlines, chapter_outlines, ideas, characters, worldbuilding,
                   generation, deepseek_review, gemini_revision, timeline, plot_logic, versions,
                   outline_updates, model_dispatch, writing_rules, quality, settings]
        result = [dict(module.MODULE) for module in modules]
        result.insert(11, {"id": "database", "name": "数据库管理", "status": "ready",
                           "description": "SQLite 事务保存、磁盘持久化、保存编号冲突检查与项目历史快照。"})
        return result

    def execute(self, project_id, action, values, *, expected_revision):
        project_id = text(project_id, "项目编号", required=True)
        action = text(action, "操作名称", required=True)
        if action=='save_chapter':
            from novel_writer.application.body_save import save
            return save(self.repository,project_id,values,expected_revision)
        if action in ('configure_canon_maintenance','canon_maintenance_policy'):
            return self.configure_canon_maintenance(project_id, values)
        if action in ('rollback_canon_maintenance','canon_maintenance_rollback'):
            return self.rollback_canon_maintenance(project_id, values)
        if action in ('archive_project','trash_project','restore_project','lock_body_range','unlock_body_range'):
            from novel_writer.application.author_scope import execute
            return execute(self.repository,project_id,action,values,expected_revision)
        if action in {"generate_body", "deepseek_review", "gemini_revision", "auto_update_outline"}:
            return model_dispatch.dispatch(action)
        if action in ('trash_chapter','restore_trashed_chapter'):
            from novel_writer.application.chapter_lifecycle import execute
            return execute(self.repository,project_id,action,values,expected_revision=expected_revision)
        state = self.repository.get(project_id)
        if type(expected_revision) is not int or expected_revision != state["revision"]:
            raise ConflictError("小说已更新，请保留当前输入并重新打开最新内容")
        if action=='preview_trash_chapter':
            from novel_writer.application.chapter_lifecycle import preview_trash
            return preview_trash(state,values.get('chapter_id'))
        if action in ('save_memory','archive_memory','review_memory'):
            from novel_writer.application.memories import save
            return self.repository.save(save(state,action,values),expected_revision=expected_revision)
        if action in ('move_chapter','move_chapter_to_volume','archive_chapter','unarchive_chapter'):
            from novel_writer.application.chapter_lifecycle import apply
            return self.repository.save(apply(state,action,values,expected_revision),expected_revision=expected_revision)
        if action=='import_chapters':
            from novel_writer.application.migration_text import import_chapters
            return self.repository.save(import_chapters(state,values),expected_revision=expected_revision)
        document = document_from_dict(state["document"])
        from novel_writer.domain.body_planning import archived as entity_archived
        if action=='save_character' and entity_archived(state,'character',values.get('character_id')):
            raise DataValidationError('人物已归档，请先明确恢复')
        if action in ('save_chapter_outline','save_character','add_character'):
            referenced=list(values['character_ids']) if type(values.get('character_ids')) is list else []
            for scene in values['scenes'] if type(values.get('scenes')) is list else []:
                if type(scene) is dict and type(scene.get('character_ids')) is list:referenced.extend(scene['character_ids'])
            for relation in values['relationships'] if type(values.get('relationships')) is list else []:
                if type(relation) is dict:referenced.append(relation.get('target_character_id'))
            if any(entity_archived(state,'character',identifier) for identifier in referenced):
                raise DataValidationError('新规划或人物关系引用了已归档人物，请先恢复')
        from novel_writer.application.knowledge import enforce_plan_locks
        enforce_plan_locks(state,action,values)
        from novel_writer.application.book_creation import enforce_formal_locks
        enforce_formal_locks(state,action,values)
        legacy_defaults=state['workspace_version']==1 and self.repository.has_legacy_defaults(project_id)
        original=deepcopy(state) if legacy_defaults else state
        handlers = {
            "save_project": projects.save, "save_book_outline": book_outlines.save,
            "add_character": characters.add, "save_character": characters.save,
            "add_chapter": chapters.add, "save_chapter": chapters.save,
            "save_chapter_outline": chapter_outlines.save, "restore_chapter": versions.restore,
        }
        if action in handlers:
            handlers[action](document, values)
        elif action == "save_idea":
            ideas.save(document, state, values)
        elif action == "save_worldbuilding":
            worldbuilding.save(state, values)
        elif action == "save_writing_rules":
            writing_rules.save(state, values)
        else:
            raise DataValidationError("未知操作")
        def semantic(doc):
            value=deepcopy(doc);value.pop('versions',None)
            def strip(node):
                if isinstance(node,dict):return {k:strip(v) for k,v in node.items() if k not in ('updated_at','current_version_id')}
                if isinstance(node,list):return [strip(v) for v in node]
                return node
            return strip(value)
        kind={'save_project':'project','save_book_outline':'book_outline','save_chapter':'chapter','save_character':'character','save_chapter_outline':'chapter_outline'}.get(action)
        target=values.get('chapter_id') if kind=='chapter' else values.get('character_id') if kind=='character' else original['document']['project']['id'] if kind=='project' else (original['document']['book_outline'] or {}).get('id') if kind=='book_outline' else next((o['id'] for o in original['document']['chapter_outlines'] if o['chapter_id']==values.get('chapter_id')),None)
        had_version=kind is None or any(v['entity_type']==kind and v['entity_id']==target for v in original['document']['versions'])
        if (legacy_defaults
                and action!='restore_chapter' and had_version and semantic(document_to_dict(document))==semantic(original['document'])
                and all(state[k]==original[k] for k in ('ideas','worldbuilding','writing_rules'))
                ):return original
        document.project.updated_at = utc_now()
        state["document"] = document_to_dict(document)
        return self.repository.save(state, expected_revision=expected_revision)
