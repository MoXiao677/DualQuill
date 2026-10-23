"""SQLite 磁盘存储：事务保存、乐观锁、不可覆盖的项目快照。"""

from contextlib import contextmanager
from dataclasses import asdict,replace
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from types import MappingProxyType
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import threading
from hashlib import sha256

from novel_writer.domain.models import DataValidationError, VersionRecord, _timestamp, utc_now, validate_snapshot_references
from novel_writer.storage.json_codec import document_from_dict, document_to_dict, strict_json_loads, normalize_persistent_document
from novel_writer.domain.memory import validate_memory_state,source_catalog,validate_record
from novel_writer.domain.tasks import COLLECTIONS,validate_task_state,validate_task_transition,dependency_catalog


class ConflictError(ValueError):
    """其他窗口已经保存了新版本。"""


def _feature_values(state):
    # A schema-validated NovelDocument has no task/protocol feature fields.
    # Author prose stays literal text; feature declarations live in workspace
    # collections. Invalid document fields still fail full domain validation.
    return {key:value for key,value in state.items() if key!='document'}


def _upgrade_features(state):
    values=_feature_values(state)
    from novel_writer.domain.sampling import contains as sampling
    from novel_writer.application.sampling import upgrade as sampling_upgrade
    if sampling(values):sampling_upgrade(state)
    from novel_writer.domain.execution_limits import contains_long_timeout
    from novel_writer.application.execution_limits import upgrade_long_timeout
    if contains_long_timeout(values):upgrade_long_timeout(state)
    from novel_writer.domain.streaming import contains as streaming,upgrade as stream_upgrade
    if streaming(values):stream_upgrade(state)
    from novel_writer.domain.semantic_summaries import contains as summary,upgrade as summary_upgrade
    if summary(values):summary_upgrade(state)
    from novel_writer.domain.candidate_reviews import contains as review,upgrade as review_upgrade
    if review(values):review_upgrade(state)
    from novel_writer.domain.workflow_stages import contains as has_stages,upgrade as stage_upgrade
    if has_stages(values):stage_upgrade(state)


def validate_workspace(state: dict, *, _validated_versions=None) -> dict:
    expected = {"workspace_version", "revision", "document", "ideas", "worldbuilding", "writing_rules"}
    if type(state) is dict and type(state.get('workspace_version')) is int and state['workspace_version'] in (2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52):
        expected |= {'memories','memory_history'}
        if state['workspace_version']>=3:expected |= set(COLLECTIONS)
        if state['workspace_version']>=4:
            from novel_writer.domain.review import REVIEW_COLLECTIONS
            expected |= set(REVIEW_COLLECTIONS)
        if state['workspace_version']>=5:
            from novel_writer.domain.knowledge import KNOWLEDGE_COLLECTIONS
            expected |= set(KNOWLEDGE_COLLECTIONS)
        if state['workspace_version']>=6:
            from novel_writer.domain.model_contract import MODEL_COLLECTIONS
            expected |= set(MODEL_COLLECTIONS)
        if state['workspace_version']>=7:
            from novel_writer.domain.experiments import EXPERIMENT_COLLECTIONS
            expected |= set(EXPERIMENT_COLLECTIONS)
        if state['workspace_version']>=8:
            from novel_writer.domain.workflows import WORKFLOW_COLLECTIONS
            expected |= set(WORKFLOW_COLLECTIONS)
        if state['workspace_version']>=10:
            from novel_writer.domain.creation_presets import CREATION_COLLECTIONS
            expected |= set(CREATION_COLLECTIONS)
        if state['workspace_version']>=11:
            from novel_writer.domain.book_creation import COLLECTIONS as BOOK_CREATION_COLLECTIONS
            expected |= set(BOOK_CREATION_COLLECTIONS)
        if state['workspace_version']>=12:
            from novel_writer.domain.book_ai import COLLECTIONS as BOOK_AI_COLLECTIONS
            expected |= set(BOOK_AI_COLLECTIONS)
        if state['workspace_version']>=13:
            from novel_writer.domain.styles import COLLECTIONS as STYLE_COLLECTIONS
            expected |= set(STYLE_COLLECTIONS)
        if state['workspace_version']>=14:
            from novel_writer.domain.public_search import COLLECTIONS as WEB_COLLECTIONS
            expected |= set(WEB_COLLECTIONS)
        if state['workspace_version']>=15:
            from novel_writer.domain.style_trials import COLLECTIONS as TRIAL_COLLECTIONS
            expected |= set(TRIAL_COLLECTIONS)
        if state['workspace_version']>=16:
            from novel_writer.domain.chapter_writing import COLLECTIONS as WRITING_COLLECTIONS
            expected |= set(WRITING_COLLECTIONS)
        if state['workspace_version']>=17:
            from novel_writer.domain.chapter_planning import COLLECTIONS as PLANNING_COLLECTIONS
            expected |= set(PLANNING_COLLECTIONS)
        if state['workspace_version']>=18:
            from novel_writer.domain.scene_expansion import COLLECTIONS as EXPANSION_COLLECTIONS
            expected |= set(EXPANSION_COLLECTIONS)
        if state['workspace_version']>=19:
            from novel_writer.domain.chapter_lifecycle import COLLECTIONS as LIFECYCLE_COLLECTIONS
            expected |= set(LIFECYCLE_COLLECTIONS)
        if state['workspace_version']>=20:
            from novel_writer.domain.console import COLLECTIONS as CONSOLE_COLLECTIONS
            expected |= set(CONSOLE_COLLECTIONS)
        if state['workspace_version']>=21:
            expected |= {'scoped_rules'}
        if state['workspace_version']>=46:
            from novel_writer.domain.rule_reviews import COLLECTIONS as RULE_REVIEW_COLLECTIONS
            expected |= set(RULE_REVIEW_COLLECTIONS)
        if state['workspace_version']>=36:
            expected |= {'rule_task_bindings'}
        if state['workspace_version']>=22:
            expected |= {'scoped_rule_history'}
        if state['workspace_version']>=23:
            from novel_writer.domain.memory_rollups import COLLECTIONS as ROLLUP_COLLECTIONS
            expected |= set(ROLLUP_COLLECTIONS)
        if state['workspace_version']>=24:
            from novel_writer.domain.console import RUN_COLLECTIONS
            expected |= set(RUN_COLLECTIONS)
        if state['workspace_version']>=25:
            from novel_writer.domain.materials import COLLECTIONS as MATERIAL_COLLECTIONS
            expected |= set(MATERIAL_COLLECTIONS)
        if state['workspace_version']>=26:
            from novel_writer.domain.full_book_planning import COLLECTIONS as PLANNING_V26_COLLECTIONS
            expected |= set(PLANNING_V26_COLLECTIONS)
        if state['workspace_version']>=27:
            from novel_writer.domain.chapter_trash import COLLECTIONS as TRASH_COLLECTIONS
            expected |= set(TRASH_COLLECTIONS)
        if state['workspace_version']>=41:expected.add('deep_review_actions')
        if state['workspace_version']>=42:expected.add('memory_automation_events')
        if state['workspace_version']>=43:
            from novel_writer.domain.body_planning import COLLECTIONS as BODY_PLANNING_COLLECTIONS
            expected |= set(BODY_PLANNING_COLLECTIONS)
        if state['workspace_version']>=45:
            from novel_writer.domain.graph_extraction import COLLECTIONS as GRAPH_COLLECTIONS
            expected |= set(GRAPH_COLLECTIONS)
        if state['workspace_version']>=47:
            from novel_writer.domain.model_planning import COLLECTIONS as MODEL_PLANNING_COLLECTIONS
            expected |= set(MODEL_PLANNING_COLLECTIONS)
        if state['workspace_version']>=48:expected.add('author_scope_events')
        if state['workspace_version']>=49:
            from novel_writer.domain.semantic_retrieval import COLLECTIONS as SEMANTIC_COLLECTIONS
            expected |= set(SEMANTIC_COLLECTIONS)
        if state['workspace_version']>=50:expected.add('memory_refresh_events')
        if state['workspace_version']>=50 and (state['workspace_version']>=51 or 'graph_item_decisions' in state):expected.add('graph_item_decisions')
        if state['workspace_version']>=52:
            from novel_writer.domain.console_background import COLLECTIONS as BACKGROUND_COLLECTIONS
            expected.update(BACKGROUND_COLLECTIONS)
        if any(name in state for name in ('canon_maintenance_settings','canon_maintenance_facts','canon_maintenance_events','canon_maintenance_checkpoints')):
            from novel_writer.domain.canon_maintenance import COLLECTIONS as CANON_COLLECTIONS
            expected.update(CANON_COLLECTIONS)
    if type(state) is not dict or set(state) != expected:
        raise DataValidationError("工作区字段不完整或含未知字段")
    if type(state["workspace_version"]) is not int or state["workspace_version"] not in (1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52):
        raise DataValidationError("不支持此工作区格式版本")
    if type(state["revision"]) is not int or state["revision"] < 0:
        raise DataValidationError("保存编号必须是非负整数")
    verified_versions=set()
    document = document_from_dict(normalize_persistent_document(state["document"]) if state['workspace_version']==1 else state['document'],_validated_versions=_validated_versions,_verified_version_ids=verified_versions)
    if type(state["ideas"]) is not dict:
        raise DataValidationError("IDEA 必须按章节编号组织")
    chapter_ids = {chapter.id for chapter in document.chapters}
    for chapter_id, idea in state["ideas"].items():
        if chapter_id not in chapter_ids or type(idea) is not str:
            raise DataValidationError("IDEA 必须引用当前小说的章节，内容必须是文字")
    for name in ("worldbuilding", "writing_rules"):
        if type(state[name]) is not str:
            raise DataValidationError(f"{name} 必须是文字")
    features=_feature_values(state)
    from novel_writer.domain.sampling import contains as has_sampling
    if state['workspace_version']<28 and has_sampling(features):raise DataValidationError('采样参数需要 V28 工作区')
    from novel_writer.domain.sampling import contains_native
    if state['workspace_version']<29 and contains_native(features):raise DataValidationError('原生请求配置需要 V29 工作区')
    from novel_writer.domain.execution_limits import contains_long_timeout
    if state['workspace_version']<30 and contains_long_timeout(features):raise DataValidationError('长请求时限需要 V30 工作区')
    from novel_writer.domain.memory_rollups import contains_chapter_rollup
    if state['workspace_version']<31 and contains_chapter_rollup(features):raise DataValidationError('章节独立汇总需要 V31 工作区')
    from novel_writer.domain.streaming import contains as has_streaming
    if state['workspace_version']<33 and has_streaming(features):raise DataValidationError('SSE冻结去向需要 V33 工作区')
    from novel_writer.domain.semantic_summaries import contains as has_summary
    if state['workspace_version']<34 and has_summary(features):raise DataValidationError('单章语义摘要需要 V34 工作区')
    from novel_writer.domain.candidate_reviews import contains as has_candidate_review
    if state['workspace_version']<35 and has_candidate_review(features):raise DataValidationError('候选模型审核需要 V35 工作区')
    from novel_writer.domain.workflow_stages import contains as has_stages
    if state['workspace_version']<40 and has_stages(features):raise DataValidationError('Dedicated chapter workflow requires V40')
    from novel_writer.domain.deep_review import contains as has_deep_review
    if state['workspace_version']<41 and has_deep_review(features):raise DataValidationError('深层审核需要 V41 工作区')
    if state['workspace_version']<45 and any(t.get('frozen',{}).get('parameters',{}).get('binding',{}).get('prompt_version')=='graph-extract-json-1' for t in state.get('generation_tasks',[])):
        raise DataValidationError('图谱抽取需要 V45 工作区')
    # Cache the same JSON container types that are committed to disk. Domain
    # records may contain tuples; retaining them makes warm reads differ from
    # reopened/restored libraries and breaks immutable transition comparisons.
    normalized = strict_json_loads(json.dumps(features,ensure_ascii=False,allow_nan=False))
    if verified_versions:
        # Only the validator's private, previously validated immutable records
        # are shared internally. Repository results and committed cache entries
        # still cross the existing deep-copy boundaries. New/changed records
        # are fully normalized and history equality is checked below as before.
        normalized['document']=asdict(replace(document,versions=[]))
        normalized['document']['versions']=[_validated_versions[v.id] if v.id in verified_versions else asdict(v) for v in document.versions]
    else:normalized["document"] = asdict(document)
    if state['workspace_version']>=45:
        from novel_writer.domain.graph_extraction import validate_state as validate_graph_state
        validate_graph_state(normalized)
    from novel_writer.domain.graph_items import validate_state as validate_graph_items
    validate_graph_items(normalized)
    if state['workspace_version']>=2:validate_memory_state(normalized)
    if state['workspace_version']>=3:validate_task_state(normalized)
    if state['workspace_version']>=4:
        from novel_writer.domain.review import validate_review_state
        validate_review_state(normalized)
    if state['workspace_version']>=5:
        from novel_writer.domain.knowledge import validate_knowledge_state
        validate_knowledge_state(normalized)
    if state['workspace_version']>=6:
        from novel_writer.domain.model_contract import validate_model_state
        validate_model_state(normalized)
    if state['workspace_version']>=7:
        from novel_writer.domain.experiments import validate_experiment_state
        validate_experiment_state(normalized)
    if state['workspace_version']>=8:
        from novel_writer.domain.workflows import validate_workflow_state
        validate_workflow_state(normalized)
    if state['workspace_version']>=10:
        from novel_writer.domain.creation_presets import validate_creation_state
        validate_creation_state(normalized)
    if state['workspace_version']>=11:
        from novel_writer.domain.book_creation import validate_state as validate_book_creation
        validate_book_creation(normalized)
    if state['workspace_version']>=12:
        from novel_writer.domain.book_ai import validate_state as validate_book_ai
        validate_book_ai(normalized)
    if state['workspace_version']>=13:
        from novel_writer.domain.styles import validate_state as validate_styles
        validate_styles(normalized)
    if state['workspace_version']>=14:
        from novel_writer.domain.public_search import validate_state as validate_web
        validate_web(normalized)
    if state['workspace_version']>=15:
        from novel_writer.domain.style_trials import validate_state as validate_trials
        validate_trials(normalized)
    if state['workspace_version']>=16:
        from novel_writer.domain.chapter_writing import validate_state as validate_writing
        validate_writing(normalized)
    if state['workspace_version']>=17:
        from novel_writer.domain.chapter_planning import validate_state as validate_chapter_planning
        validate_chapter_planning(normalized)
    if state['workspace_version']>=18:
        from novel_writer.domain.scene_expansion import validate_state as validate_scene_expansion
        validate_scene_expansion(normalized)
    if state['workspace_version']>=19:
        from novel_writer.domain.chapter_lifecycle import validate_state as validate_chapter_lifecycle
        validate_chapter_lifecycle(normalized)
    if state['workspace_version']>=20:
        from novel_writer.domain.console import validate_state as validate_console
        validate_console(normalized)
    if state['workspace_version']>=46:
        from novel_writer.domain.rule_reviews import validate_state as validate_rule_reviews
        validate_rule_reviews(normalized)
    if state['workspace_version']>=21:
        from novel_writer.domain.scoped_rules import validate_state as validate_scoped_rules
        validate_scoped_rules(normalized)
    if state['workspace_version']>=23:
        from novel_writer.domain.memory_rollups import validate_state as validate_memory_rollups
        validate_memory_rollups(normalized)
    if state['workspace_version']>=25:
        from novel_writer.domain.materials import validate_state as validate_materials
        validate_materials(normalized)
    if state['workspace_version']>=26:
        from novel_writer.domain.full_book_planning import validate_state as validate_full_book_planning
        validate_full_book_planning(normalized)
    if state['workspace_version']>=27:
        from novel_writer.domain.chapter_trash import validate_state as validate_chapter_trash
        validate_chapter_trash(normalized)
    if state['workspace_version']>=41:
        from novel_writer.domain.deep_review import validate_state as validate_deep_review
        validate_deep_review(normalized)
    if state['workspace_version']>=42:
        from novel_writer.domain.incremental_memory import validate_state as validate_automation
        validate_automation(normalized)
    from novel_writer.domain.body_planning import validate_state as validate_body_planning
    validate_body_planning(normalized)
    if state['workspace_version']>=49:
        from novel_writer.domain.semantic_retrieval import validate_state as validate_semantic
        validate_semantic(normalized)
    if state['workspace_version']>=50:
        from novel_writer.domain.memory_refresh import validate_state as validate_refresh
        validate_refresh(normalized)
    if state['workspace_version']>=52:
        from novel_writer.domain.console_background import validate_state as validate_background
        validate_background(normalized)
    if 'canon_maintenance_settings' in normalized:
        from novel_writer.domain.canon_maintenance import validate_state as validate_canon
        validate_canon(normalized)
    from novel_writer.domain.model_planning import validate_state as validate_model_planning
    validate_model_planning(normalized)
    if state['workspace_version']>=48:
        from novel_writer.domain.author_scope import validate_state
        validate_state(normalized)
    return normalized


class WorkspaceHistoryValidator:
    """按整书 revision 顺序校验；只在版本首现时检验其外部引用。"""

    def __init__(self):
        self.previous_versions = []
        self.identities = {}
        self.previous_memory_history=[]
        self.source_signatures={}
        self.workspace_version=1
        self.previous_task_state={}
        self.previous_normalized_state=None
        self.previous_review_state={}
        self.previous_knowledge_state={}

    def __deepcopy__(self,memo):
        # Scalar source signatures are frozen on creation. All mutable document,
        # task and identity state remains isolated by the normal deep copy.
        result=type(self).__new__(type(self));memo[id(self)]=result
        for name,value in self.__dict__.items():
            setattr(result,name,dict(value) if name=='source_signatures' else deepcopy(value,memo))
        return result

    def validate(self, state: dict) -> dict:
        normalized = validate_workspace(state,_validated_versions={v['id']:v for v in self.previous_versions})
        if normalized['workspace_version']>=41:
            previous=self.previous_normalized_state or {}
            old=previous.get('deep_review_actions',[])
            if normalized['deep_review_actions'][:len(old)]!=old:raise DataValidationError('深层审核处理历史不可改写、删除或重排')
            from novel_writer.application.deep_reviews import freeze_scope,selection_from_scope
            from novel_writer.domain.tasks import parse,GenerationTask
            for raw in normalized['generation_tasks'][len(previous.get('generation_tasks',[])):]:
                task=parse(GenerationTask,raw);scope=getattr(task.frozen.parameters,'deep_review',None)
                if scope is not None:
                    if previous.get('revision')!=task.frozen.source_revision:raise DataValidationError('深层审核缺少实际来源历史')
                    if freeze_scope(previous,task.frozen.parameters.selected_chapter_ids,selection_from_scope(scope))!=scope:raise DataValidationError('深层审核快照与实际保存来源不符')
        document = normalized["document"]
        versions = document["versions"]
        if normalized['workspace_version']<self.workspace_version:raise DataValidationError('工作区格式不能回退')
        self.workspace_version=normalized['workspace_version']
        self.source_signatures[normalized['revision']]=MappingProxyType({key:MappingProxyType(value) for key,value in source_catalog(normalized).items()})
        if normalized['workspace_version']>=3:
            # 准备入口冻结前一个已保存revision；只在任务首现时取证，
            # 不为每条旧V1/V2历史预建全量任务依赖索引。
            catalogs={}
            for raw in normalized['generation_tasks'][len(self.previous_task_state.get('generation_tasks',[])):]:
                revision=raw['frozen']['source_revision']
                origin=self.previous_normalized_state if self.previous_normalized_state and self.previous_normalized_state['revision']==revision else normalized if normalized['revision']==revision else None
                if origin is not None and revision not in catalogs:catalogs[revision]=dependency_catalog(origin)
            validate_task_transition(normalized,self.previous_task_state,catalogs)
            self.previous_task_state={name:deepcopy(normalized[name]) for name in COLLECTIONS}
        if normalized['workspace_version']>=4:
            from novel_writer.domain.review import REVIEW_COLLECTIONS
            for name in REVIEW_COLLECTIONS:
                old=self.previous_review_state.get(name,[])
                if normalized[name][:len(old)]!=old:raise DataValidationError('审核对象/处理历史不可改写、删除或重排')
            old_reports={r['id'] for r in self.previous_review_state.get('review_reports',[])}
            for report in normalized['review_reports'][len(self.previous_review_state.get('review_reports',[])):]:
                if report['previous_report_id'] is not None and report['previous_report_id'] not in old_reports:raise DataValidationError('复审必须引用此前已保存报告')
            self.previous_review_state={name:deepcopy(normalized[name]) for name in REVIEW_COLLECTIONS}
        if normalized['workspace_version']>=5:
            from novel_writer.domain.knowledge import KNOWLEDGE_COLLECTIONS,validate_knowledge_transition
            validate_knowledge_transition(normalized,self.previous_normalized_state)
            for name in KNOWLEDGE_COLLECTIONS:
                old=self.previous_knowledge_state.get(name,[])
                if normalized[name][:len(old)]!=old:raise DataValidationError('知识/提案修订历史不能改写、删除或重排')
                for item in normalized[name][len(old):]:
                    sources=[item['source']] if name in ('knowledge_nodes','knowledge_edges') else [item['source'],item['target']] if name=='planning_proposals' else []
                    for source in sources:
                        actual=self.source_signatures.get(source['workspace_revision'],{}).get((source['kind'],source['entity_id']))
                        if actual!=source:raise DataValidationError('知识出处与声明的保存历史不符')
                    if name=='local_edit_proposals':
                        for guard in item['guards']:
                            actual=self.source_signatures.get(guard['source_revision'],{}).get((guard['kind'],guard['entity_id']))
                            if actual is None or (actual['version_id'],actual['source_sha256'])!=(guard['version_id'],guard['source_sha256']):raise DataValidationError('局部提案guard来源历史不符')
            self.previous_knowledge_state={name:deepcopy(normalized[name]) for name in KNOWLEDGE_COLLECTIONS}
        if normalized['workspace_version']>=6:
            from novel_writer.domain.model_contract import validate_model_transition
            validate_model_transition(normalized,self.previous_normalized_state)
        if normalized['workspace_version']>=7:
            from novel_writer.domain.experiments import validate_experiment_transition
            validate_experiment_transition(normalized,self.previous_normalized_state)
        if normalized['workspace_version']>=8:
            from novel_writer.domain.workflows import validate_workflow_transition
            validate_workflow_transition(normalized,self.previous_normalized_state)
        if normalized['workspace_version']>=10:
            from novel_writer.domain.creation_presets import validate_creation_transition
            validate_creation_transition(normalized,self.previous_normalized_state)
        if normalized['workspace_version']>=11:
            from novel_writer.domain.book_creation import validate_transition as validate_book_creation_transition
            validate_book_creation_transition(normalized,self.previous_normalized_state)
        if normalized['workspace_version']>=12:
            from novel_writer.domain.book_ai import validate_transition as validate_book_ai_transition
            validate_book_ai_transition(normalized,self.previous_normalized_state)
        if normalized['workspace_version']>=13:
            from novel_writer.domain.styles import validate_transition as validate_styles_transition
            validate_styles_transition(normalized,self.previous_normalized_state)
        if normalized['workspace_version']>=14:
            from novel_writer.domain.public_search import validate_transition as validate_web_transition
            validate_web_transition(normalized,self.previous_normalized_state)
        if normalized['workspace_version']>=15:
            from novel_writer.domain.style_trials import validate_transition as validate_trial_transition
            validate_trial_transition(normalized,self.previous_normalized_state)
            old_count=len((self.previous_normalized_state or {}).get('style_trial_tasks',[]))
            for task in normalized['style_trial_tasks'][old_count:]:
                for guard in task['seed']['guards']:
                    actual=self.source_signatures.get(guard['workspace_revision'],{}).get((guard['kind'],guard['entity_id']))
                    if actual!=guard:raise DataValidationError('trial.invalid_source_history')
        if normalized['workspace_version']>=16:
            from novel_writer.domain.chapter_writing import validate_transition as validate_writing_transition
            validate_writing_transition(normalized,self.previous_normalized_state or {})
        if normalized['workspace_version']>=17:
            from novel_writer.domain.chapter_planning import validate_transition as validate_planning_transition
            validate_planning_transition(normalized,self.previous_normalized_state or {})
        if normalized['workspace_version']>=18:
            from novel_writer.domain.scene_expansion import validate_transition as validate_expansion_transition
            validate_expansion_transition(normalized,self.previous_normalized_state or {})
        if normalized['workspace_version']>=19:
            from novel_writer.domain.chapter_lifecycle import validate_transition as validate_lifecycle_transition
            validate_lifecycle_transition(normalized,self.previous_normalized_state or {})
        if normalized['workspace_version']>=20:
            from novel_writer.domain.console import validate_transition as validate_console_transition
            validate_console_transition(normalized,self.previous_normalized_state or {})
        if normalized['workspace_version']>=21:
            from novel_writer.domain.scoped_rules import validate_transition as validate_rule_transition
            validate_rule_transition(normalized,self.previous_normalized_state or {})
        if normalized['workspace_version']>=23:
            from novel_writer.domain.memory_rollups import validate_transition as validate_rollup_transition
            validate_rollup_transition(normalized,self.previous_normalized_state or {})
        if normalized['workspace_version']>=25:
            from novel_writer.domain.materials import validate_transition as validate_material_transition
            validate_material_transition(normalized,self.previous_normalized_state or {})
        if normalized['workspace_version']>=26:
            from novel_writer.domain.full_book_planning import validate_transition as validate_full_book_planning_transition
            validate_full_book_planning_transition(normalized,self.previous_normalized_state or {})
        if normalized['workspace_version']>=27:
            from novel_writer.domain.chapter_trash import validate_transition as validate_chapter_trash_transition
            validate_chapter_trash_transition(normalized,self.previous_normalized_state or {})
        if normalized['workspace_version']>=42:
            from novel_writer.domain.incremental_memory import validate_transition
            validate_transition(normalized,self.previous_normalized_state or {})
        from novel_writer.domain.body_planning import validate_transition as validate_body_planning_transition
        validate_body_planning_transition(normalized,self.previous_normalized_state or {})
        if normalized['workspace_version']>=50:
            from novel_writer.domain.memory_refresh import validate_transition as validate_refresh
            validate_refresh(normalized,self.previous_normalized_state or {})
            for event in normalized['memory_refresh_events'][len((self.previous_normalized_state or {}).get('memory_refresh_events',[])):] :
                for source in event.get('sources',[]):
                    actual=self.source_signatures.get(source['workspace_revision'],{}).get((source['kind'],source['entity_id']))
                    if actual!=source:raise DataValidationError('刷新来源与保存历史不符')
        if normalized['workspace_version']>=52:
            from novel_writer.domain.console_background import validate_transition as validate_background
            validate_background(normalized,self.previous_normalized_state or {})
        if 'canon_maintenance_settings' in normalized:
            from novel_writer.domain.canon_maintenance import validate_transition as validate_canon
            validate_canon(normalized,self.previous_normalized_state or {})
        if normalized['workspace_version']>=49:
            from novel_writer.domain.semantic_retrieval import validate_transition as validate_semantic
            from novel_writer.application.semantic_retrieval import source as semantic_source
            previous=self.previous_normalized_state or {}
            validate_semantic(normalized,previous)
            for task in normalized['semantic_retrieval_tasks'][len(previous.get('semantic_retrieval_tasks',[])):] :
                if not previous:raise DataValidationError('semantic_retrieval.missing_source_history')
                actual=semantic_source(previous,task['source_options'])
                if actual['source_sha256']!=task['source_sha256'] or actual['source_revision']!=task['source_revision']:
                    raise DataValidationError('semantic_retrieval.invalid_source_history')
        from novel_writer.domain.model_planning import validate_transition as validate_model_planning_transition
        validate_model_planning_transition(normalized,self.previous_normalized_state or {})
        for item in normalized.get('model_planning_tasks', [])[len((self.previous_normalized_state or {}).get('model_planning_tasks', [])):]:
            source=item['source_guard']['source']
            actual=self.source_signatures.get(source['workspace_revision'],{}).get((source['kind'],source['entity_id']))
            if actual!=source:raise DataValidationError('模型规划来源与声明的保存历史不符')
        for item in normalized.get('body_planning_proposals', [])[len((self.previous_normalized_state or {}).get('body_planning_proposals', [])):]:
            source=item['source']
            actual=self.source_signatures.get(source['workspace_revision'],{}).get((source['kind'],source['entity_id']))
            if actual!=source:raise DataValidationError('正文规划引文与声明的保存历史不符')
        if normalized['workspace_version']>=45:
            from novel_writer.domain.graph_extraction import validate_transition as validate_graph_transition
            validate_graph_transition(normalized,self.previous_normalized_state)
        from novel_writer.domain.graph_items import validate_transition as validate_graph_items
        validate_graph_items(normalized,self.previous_normalized_state)
        if normalized['workspace_version']>=46:
            from novel_writer.domain.rule_reviews import validate_transition as validate_rule_review_transition
            validate_rule_review_transition(normalized,self.previous_normalized_state or {})
            from novel_writer.application.rule_reviews import source as rule_review_source
            previous=self.previous_normalized_state or {}
            from novel_writer.application.scoped_rules import operation_rules
            for name in ('chapter_planning_tasks','scene_expansion_tasks'):
                for task in normalized.get(name,[])[len(previous.get(name,[])):]:
                    if task['source_options'].get('rule_task_id') is not None:
                        capability=('brainstorm_chapter' if task['mode']=='brainstorm' else 'outline_chapter') if name=='chapter_planning_tasks' else 'expand_scene_selection'
                        actual=operation_rules(previous,task['chapter_id'],task['source_options'],capability,task['request_id'])['rules']
                        if sorted(task['source_guard']['rule_sources'],key=lambda r:r['id'])!=sorted(actual,key=lambda r:r['id']):raise DataValidationError('scoped_rules.invalid_frozen_rule_history')
            for task in normalized['rule_review_tasks'][len(previous.get('rule_review_tasks',[])):]:
                if not previous:raise DataValidationError('rule_reviews.missing_source_history')
                actual=rule_review_source(previous,task['chapter_id'],task['target_task_id'])
                if task['source_revision']!=previous['revision'] or task['source_sha256']!=actual['source_sha256'] or sorted(task['rules'],key=lambda r:r['id'])!=sorted(actual['rules'],key=lambda r:r['id']):
                    raise DataValidationError('rule_reviews.invalid_source_history')
        if normalized['workspace_version']>=48 and self.previous_normalized_state is not None:
            from novel_writer.domain.author_scope import validate_transition
            validate_transition(normalized,self.previous_normalized_state)
        self.previous_normalized_state=normalized
        memory_history=normalized.get('memory_history',[])
        if memory_history[:len(self.previous_memory_history)]!=self.previous_memory_history:
            raise DataValidationError('记忆编辑历史必须完整保留，不能改写/删除/重排')
        for edit in memory_history[len(self.previous_memory_history):]:
            validate_record(edit['snapshot'],normalized)
            source=edit['snapshot']['source']
            actual=self.source_signatures.get(source['workspace_revision'],{}).get((source['kind'],source['entity_id']))
            if actual!=source:raise DataValidationError('记忆出处在所声明的历史revision不存在或与来源不符')
        self.previous_memory_history=deepcopy(memory_history)
        if versions[:len(self.previous_versions)] != self.previous_versions:
            raise DataValidationError("已有实体版本必须完整保留，不能改写、删除或重新排序")
        chapter_ids = {item["id"] for item in document["chapters"]}
        character_ids = {item["id"] for item in document["characters"]}
        for raw in versions[len(self.previous_versions):]:
            validate_snapshot_references(VersionRecord(**raw), chapter_ids=chapter_ids, character_ids=character_ids)
        entities = [("project", document["project"])]
        if document["book_outline"] is not None:
            entities.append(("book_outline", document["book_outline"]))
        for name, kind in (("chapters", "chapter"), ("characters", "character"),
                           ("chapter_outlines", "chapter_outline"), ("versions", "version")):
            entities.extend((kind, item) for item in document[name])
        for kind, item in entities:
            previous_kind = self.identities.setdefault(item["id"], kind)
            if previous_kind != kind:
                raise DataValidationError("同一项目的历史记录 ID 不能跨实体类型复用")
        self.previous_versions = versions
        return normalized


def _read_project_history(connection, project_id: str, current, cached=None, *, mutable=False):
    # Hash EVERY exact snapshot on EVERY read. Stream SQLite UTF-8 blobs rather
    # than retaining/decoding all full-book snapshots together in Python memory.
    signatures=[];latest_payload=None
    # Bounded three-blob pipeline overlaps SQLite reads with two native SHA
    # workers. Every result is awaited in revision order, including failures.
    pending=deque()
    with ThreadPoolExecutor(max_workers=2,thread_name_prefix='snapshot-sha') as hashes:
        for row in connection.execute("SELECT revision,CAST(payload AS BLOB) AS payload,saved_at FROM project_snapshots WHERE project_id=? ORDER BY revision",(project_id,)):
            latest_payload=row['payload']
            pending.append((row['revision'],row['saved_at'],hashes.submit(sha256,latest_payload)))
            if len(pending)>=3:
                revision,saved_at,value=pending.popleft();signatures.append((revision,saved_at,value.result().digest()))
        while pending:
            revision,saved_at,value=pending.popleft();signatures.append((revision,saved_at,value.result().digest()))
    reusable=cached is not None and len(signatures)>=len(cached['signatures']) and signatures[:len(cached['signatures'])]==cached['signatures']
    offset=len(cached['signatures']) if reusable else 0
    has_new=offset<len(signatures)
    validator=(deepcopy(cached['validator']) if mutable or has_new else cached['validator']) if reusable else WorkspaceHistoryValidator()
    latest=validator.previous_normalized_state if reusable else None
    latest_raw=cached['raw'] if reusable else None
    expected_revision=offset+1
    for row in connection.execute("SELECT revision,CAST(payload AS BLOB) AS payload,saved_at FROM project_snapshots WHERE project_id=? AND revision>? ORDER BY revision",(project_id,offset)):
        raw=strict_json_loads(row['payload']);latest=validator.validate(raw);latest_raw=raw
        if row['revision']!=expected_revision or latest['revision']!=row['revision']:
            raise DataValidationError('整书历史 revision 不连续或与内容不一致')
        if latest['document']['project']['id']!=project_id:raise DataValidationError('整书历史项目归属不一致')
        _timestamp(row['saved_at'],'project_snapshots.saved_at');expected_revision+=1
    if not signatures or latest is None:raise DataValidationError('当前内容与最新整书历史快照不一致')
    if current['payload'].encode('utf-8')!=latest_payload:
        raw_current=strict_json_loads(current['payload']);state=validate_workspace(raw_current)
        if raw_current!=latest_raw:raise DataValidationError('当前原始字段表示与最新历史快照不一致')
        if latest!=state:raise DataValidationError('当前内容与最新整书历史快照不一致')
    if current['revision']!=expected_revision-1:raise DataValidationError('当前内容与最新整书历史快照不一致')
    if current['title']!=latest['document']['project']['title'] or current['updated_at']!=signatures[-1][1]:
        raise DataValidationError('当前项目元信息与最新整书历史快照不一致')
    validator.snapshot_signatures=signatures
    entry=cached if reusable and not has_new else dict(signatures=signatures,validator=deepcopy(validator) if mutable else validator,raw=latest_raw)
    return deepcopy(latest),validator,entry


class SQLiteRepository:
    def __init__(self, path: str | Path):
        self._history_cache={}
        self._history_lock=threading.RLock()
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2):
                raise DataValidationError("数据库版本较新，请使用对应版本软件打开")
            if version in (1,2):
                # 已有库只读打开不重复PRAGMA赋值或重建DDL，保留原字节/历史。
                return
            original_version=connection.execute('PRAGMA user_version').fetchone()[0]
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, revision INTEGER NOT NULL,
                    payload TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project_snapshots (
                    project_id TEXT NOT NULL REFERENCES projects(id), revision INTEGER NOT NULL,
                    payload TEXT NOT NULL, saved_at TEXT NOT NULL,
                    PRIMARY KEY (project_id, revision)
                );
                CREATE TRIGGER IF NOT EXISTS snapshots_no_update
                    BEFORE UPDATE ON project_snapshots BEGIN
                    SELECT RAISE(ABORT, '历史快照不可改写'); END;
                CREATE TRIGGER IF NOT EXISTS snapshots_no_delete
                    BEFORE DELETE ON project_snapshots BEGIN
                    SELECT RAISE(ABORT, '历史快照不可删除'); END;
                CREATE TRIGGER IF NOT EXISTS snapshots_no_replace
                    BEFORE INSERT ON project_snapshots
                    WHEN EXISTS (SELECT 1 FROM project_snapshots
                        WHERE project_id = NEW.project_id AND revision = NEW.revision) BEGIN
                    SELECT RAISE(ABORT, '历史快照不可替换'); END;
                """
            )

            if original_version==0:connection.execute('PRAGMA user_version=1')

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA synchronous = FULL")
            with connection:
                yield connection
        finally:
            connection.close()

    def _history(self,connection,project_id,current,*,mutable=False):
        with self._history_lock:
            try:state,validator,entry=_read_project_history(connection,project_id,current,self._history_cache.get(project_id),mutable=mutable)
            except BaseException:
                self._history_cache.pop(project_id,None);raise
            self._history_cache[project_id]=entry
            # Bound retained validators; no history is removed from disk.
            while len(self._history_cache)>4:self._history_cache.pop(next(iter(self._history_cache)))
            return state,validator

    def blob(self,sha):
        from novel_writer.storage.content_blobs import read
        with self._connection() as connection:return read(connection,sha)

    def list_projects(self) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute("SELECT id,title,revision,updated_at,json_extract(payload,'$.document.project.status') AS legacy_status,json_extract(payload,'$.author_scope_events') AS scope FROM projects ORDER BY updated_at DESC,id").fetchall()
        result=[]
        for row in rows:
            item={key:row[key] for key in ('id','title','revision','updated_at')}
            item['author_state']='archived' if row['legacy_status']=='archived' else 'active'
            for event in strict_json_loads(row['scope'] or '[]'):
                if event['kind']=='lifecycle':item['author_state']=event['data']['after']
            result.append(item)
        return result

    def get(self, project_id: str) -> dict:
        with self._connection() as connection:
            connection.execute("BEGIN")
            row = connection.execute("SELECT title, revision, payload, updated_at FROM projects WHERE id = ?", (project_id,)).fetchone()
            if row is None:
                raise KeyError("找不到这本小说")
            state, _ = self._history(connection, project_id, row)
            if state['workspace_version']>=13:
                from novel_writer.storage.content_blobs import validate_refs
                validate_refs(connection,state)
            return state

    def has_legacy_defaults(self,project_id):
        with self._connection() as connection:
            row=connection.execute('SELECT payload FROM projects WHERE id=?',(project_id,)).fetchone()
            if row is None:return False
            raw=strict_json_loads(row['payload'])
            return raw.get('workspace_version')==1 and raw['document']!=normalize_persistent_document(raw['document'])

    def get_revision(self,project_id,revision):
        self.get(project_id)  # 先验证真实整书历史链，仅读取，不重写旧行。
        if type(revision) is not int or revision<1:raise DataValidationError('来源revision无效')
        with self._connection() as connection:
            row=connection.execute('SELECT payload FROM project_snapshots WHERE project_id=? AND revision=?',(project_id,revision)).fetchone()
            if row is None:raise DataValidationError('来源整书历史不存在')
            return validate_workspace(strict_json_loads(row['payload']))

    def create(self, state: dict) -> dict:
        # 仅明确新建入口允许构造器生成缺省身份/时间；读旧行和save仍严格。
        state = deepcopy(state)
        if type(state) is dict and type(state.get('document')) is dict:
            state['document'] = document_to_dict(document_from_dict(state['document']))
        saved = WorkspaceHistoryValidator().validate(state)
        saved["revision"] = 1
        project = saved["document"]["project"]
        payload = json.dumps(saved, ensure_ascii=False, allow_nan=False)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM projects WHERE id = ?", (project["id"],)).fetchone():
                raise ConflictError("小说项目已存在，不能重复创建或覆盖")
            now = utc_now()
            connection.execute("INSERT INTO projects VALUES (?, ?, ?, ?, ?)", (project["id"], project["title"], 1, payload, now))
            connection.execute("INSERT INTO project_snapshots VALUES (?, ?, ?, ?)", (project["id"], 1, payload, now))
        return saved

    def save(self, state: dict, *, expected_revision: int) -> dict:
        document=state.get('document') if type(state) is dict else None
        project=document.get('project') if type(document) is dict else None
        if type(project) is not dict or type(project.get('id')) is not str or not project['id']:
            raise DataValidationError('保存的小说必须保留有效项目身份')
        state=deepcopy(state)
        _upgrade_features(state)
        if type(expected_revision) is not int or expected_revision < 1:
            raise DataValidationError("保存时需要有效的上次保存编号")
        state["revision"] = expected_revision + 1
        project = state["document"]["project"]
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT title, revision, payload, updated_at FROM projects WHERE id = ?", (project["id"],)).fetchone()
            if row is None:
                raise KeyError("找不到这本小说")
            if row["revision"] != expected_revision:
                raise ConflictError("小说已在其他窗口更新，请先保留当前输入，再重新打开最新内容")
            current, history = self._history(connection, project["id"], row,mutable=True)
            from novel_writer.domain.author_scope import guard_and_rebase
            guard_and_rebase(current,state)
            comparison=deepcopy(state);comparison['revision']=current['revision']
            if comparison==current and current!=strict_json_loads(row['payload']):return current
            from novel_writer.application.incremental_memory import record_impact
            record_impact(current,state)
            from novel_writer.application.memory_refresh import record as record_refresh
            record_refresh(current,state)
            saved=history.validate(state)
            payload=json.dumps(saved,ensure_ascii=False,allow_nan=False)
            now = utc_now()
            connection.execute("UPDATE projects SET title = ?, revision = ?, payload = ?, updated_at = ? WHERE id = ? AND revision = ?",
                               (project["title"], saved["revision"], payload, now, project["id"], expected_revision))
            connection.execute("INSERT INTO project_snapshots VALUES (?, ?, ?, ?)", (project["id"], saved["revision"], payload, now))
        self._remember_commit(project['id'],saved,history,payload,now)
        return saved

    def _remember_commit(self,project_id,state,validator,payload,saved_at):
        # Called only AFTER the transaction context committed successfully.
        # Future reads still hash every on-disk snapshot before trusting this.
        private=deepcopy(validator)
        signatures=list(validator.snapshot_signatures)+[(state['revision'],saved_at,sha256(payload.encode('utf-8')).digest())]
        private.snapshot_signatures=signatures
        with self._history_lock:
            self._history_cache[project_id]=dict(signatures=signatures,validator=private,raw=private.previous_normalized_state)
            while len(self._history_cache)>4:self._history_cache.pop(next(iter(self._history_cache)))

    def atomic(self,project_id,operation,*,identity_claim=None,blobs=(),return_workspace=False):
        """最新状态上的单锁业务变更；正文、事件和收据一起提交或回滚。"""
        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row=connection.execute('SELECT title,revision,payload,updated_at FROM projects WHERE id=?',(project_id,)).fetchone()
            if row is None:raise KeyError('找不到这本小说')
            current,history=self._history(connection,project_id,row,mutable=True)
            if identity_claim is not None:
                collection,field,identity=identity_claim
                from novel_writer.application.knowledge import CLAIMS
                knowledge_claims=set(CLAIMS.values())
                knowledge_claims.add(('graph_decisions','id'))
                knowledge_claims.add(('graph_item_decisions','id'))
                from novel_writer.domain.experiments import EXPERIMENT_COLLECTIONS
                experiment_claims={(name,'operation_id' if name=='extension_templates' else 'id') for name in EXPERIMENT_COLLECTIONS}
                experiment_claims|={('workflow_templates','operation_id'),('workflow_runs','operation_id'),('workflow_approvals','id')}
                experiment_claims|={('creation_presets','operation_id'),('creation_preset_choices','operation_id')}
                from novel_writer.domain.book_creation import COLLECTIONS as BOOK_CREATION_COLLECTIONS
                experiment_claims|={(name,'operation_id') for name in BOOK_CREATION_COLLECTIONS}
                experiment_claims|={('book_ai_tasks','request_id'),('book_ai_candidates','operation_id'),('book_ai_reviews','operation_id'),('book_ai_adoptions','operation_id')}
                from novel_writer.domain.styles import COLLECTIONS as STYLE_COLLECTIONS
                experiment_claims|={(name,'operation_id') for name in STYLE_COLLECTIONS if name not in ('style_events','style_results')}
                experiment_claims|={(name,'operation_id') for name in ('web_queries','web_identities','web_reads','web_imports')}
                experiment_claims|={('style_trial_tasks','operation_id'),('style_trial_choices','operation_id')}
                experiment_claims|={('writing_corrections','operation_id')}
                experiment_claims|={('chapter_planning_tasks','request_id'),('chapter_planning_candidates','operation_id'),('chapter_planning_reviews','operation_id'),('chapter_planning_adoptions','operation_id')}
                experiment_claims|={('scene_expansion_tasks','request_id'),('scene_expansion_candidates','operation_id'),('scene_expansion_reviews','operation_id'),('scene_expansion_adoptions','operation_id')}
                experiment_claims|={('memory_rollup_history','operation_id'),('memory_automation_events','operation_id'),('memory_refresh_events','operation_id'),('console_background_batches','operation_id')}
                experiment_claims|={('console_run_actions','operation_id')}
                experiment_claims|={('material_operations','operation_id')}
                experiment_claims|={('full_book_planning_operations','operation_id')}
                experiment_claims|={('chapter_trash_events','operation_id')}
                experiment_claims|={('author_scope_events','operation_id')}
                experiment_claims|={('rule_review_tasks','request_id')}
                experiment_claims|={('semantic_retrieval_tasks','request_id')}
                from novel_writer.domain.body_planning import COLLECTIONS as BODY_PLANNING_COLLECTIONS
                experiment_claims|={(name,'operation_id') for name in BODY_PLANNING_COLLECTIONS}
                experiment_claims|={('model_planning_tasks','request_id'),('model_planning_links','operation_id')}
                experiment_claims|={('canon_maintenance_settings','operation_id'),
                                    ('canon_maintenance_events','operation_id')}
                if (collection,field) not in {('generation_tasks','request_id'),('adoption_receipts','id'),('review_actions','id'),('proposal_receipts','id'),('model_proposal_receipts','id'),('deep_review_actions','id')}|knowledge_claims|experiment_claims:raise DataValidationError('操作身份集合非法')
                for other in connection.execute('SELECT id,payload FROM projects WHERE id<>?',(project_id,)):
                    data=validate_workspace(strict_json_loads(other['payload']))
                    if any(item[field]==identity for item in data.get(collection,[])):raise ConflictError('同一操作身份已绑定其它小说')
                    if (collection,field) in knowledge_claims and any(any(item[key]==identity for item in data.get(name,[])) for name,key in knowledge_claims):raise ConflictError('知识操作身份已绑定其它小说')
                    if collection in BODY_PLANNING_COLLECTIONS and any(any(item['operation_id']==identity for item in data.get(name,[])) for name in BODY_PLANNING_COLLECTIONS):raise ConflictError('正文规划操作身份已绑定其它小说')
                    if collection=='model_planning_links' and any(any(item['operation_id']==identity for item in data.get(name,[])) for name in BODY_PLANNING_COLLECTIONS):raise ConflictError('模型建议转提案身份已绑定其它小说')
            changed,result=operation(deepcopy(current))
            if changed is None:return result
            _upgrade_features(changed)
            from novel_writer.application.incremental_memory import record_impact
            record_impact(current,changed)
            from novel_writer.application.memory_refresh import record as record_refresh
            record_refresh(current,changed)
            changed['revision']=current['revision']+1
            from novel_writer.domain.author_scope import guard_and_rebase
            guard_and_rebase(current,changed)
            changed=history.validate(changed)
            if blobs:
                from novel_writer.storage.content_blobs import insert
                for data in blobs:insert(connection,data)
            if changed['workspace_version']>=13:
                from novel_writer.storage.content_blobs import validate_refs
                validate_refs(connection,changed)
            payload=json.dumps(changed,ensure_ascii=False,allow_nan=False);now=utc_now();project=changed['document']['project']
            connection.execute('UPDATE projects SET title=?,revision=?,payload=?,updated_at=? WHERE id=?',(project['title'],changed['revision'],payload,now,project_id))
            connection.execute('INSERT INTO project_snapshots VALUES (?,?,?,?)',(project_id,changed['revision'],payload,now))
        self._remember_commit(project_id,changed,history,payload,now)
        return changed if return_workspace else result
