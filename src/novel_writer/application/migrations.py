"""已有库的新项目导入/复制。只映射声明的ID；全部写入同一事务。"""
from contextlib import closing
from copy import deepcopy
from dataclasses import MISSING, fields, is_dataclass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import UnionType
from typing import Union, get_args, get_origin, get_type_hints
from uuid import NAMESPACE_URL, uuid5

from novel_writer.application.backup_identity import _plain, operation_id as valid_operation_id
from novel_writer.application.backup_staging import OwnedTemporaryDirectory
from novel_writer.application.backups import (
    BackupError, BackupResult, Limits, _errors, _guard, _snapshot, _unpack, _publish, _write_all,
    _publication_directory,
    _insert_row as _stage_insert,
)
from novel_writer.domain.models import NovelDocument
from novel_writer.domain.memory_rollups import render_text,source_sort_key
from novel_writer.storage.backup_validation import (
    TABLE_COLUMNS, MODEL_TYPES, create_schema, strict_loads, validate_database, validate_connection,
)
from novel_writer.storage.json_codec import MAX_JSON_BYTES,normalize_persistent_document

PLACEHOLDER_TIME = '1970-01-01T00:00:00+00:00'
RECEIPT_LIMIT = 8 * 1024 * 1024


def upgrade_console_background(state):
    """First background grant upgrades the complete V50/V51 state to V52."""
    from novel_writer.application.memory_refresh import upgrade as prior
    from novel_writer.domain.console_background import COLLECTIONS
    prior(state)
    state.setdefault('graph_item_decisions', [])
    state['workspace_version'] = max(state['workspace_version'], 52)
    for name in COLLECTIONS:
        state.setdefault(name, [])


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _id(identity, project, kind, old):
    return str(uuid5(NAMESPACE_URL, _json(['novel-writer/migration/1', identity, project, kind, old])))


def _repair_task_source_hashes(histories, states):
    """ID映射会改变规则scope等历史指纹；按新项目自身历史重算冻结来源摘要。"""
    from novel_writer.domain.memory import fingerprint
    from novel_writer.domain.tasks import dependency_catalog
    revisions={next(iter(values.values()))['document']['project']['id']:values for values in histories.values() if values}
    for state in states:
        project_states=revisions[state['document']['project']['id']]
        for task in state.get('model_planning_tasks', []):
            origin=project_states.get(task['source_revision'])
            if origin is not None:
                from novel_writer.application.body_planning import formal_fingerprint
                from novel_writer.domain.book_creation import fingerprint as model_fingerprint
                task['source_guard']['formal_sha256']=formal_fingerprint(origin)
                task['source_guard']['all_scoped_rules_sha256']=model_fingerprint(origin.get('scoped_rules', []))
                task['source_sha256']=model_fingerprint(task['source_guard'])
        for task in state.get('generation_tasks',[]):
            frozen=task['frozen'];origin=project_states.get(frozen['source_revision'])
            if origin is None:continue
            catalog=None
            skills={value['id']:value for value in frozen.get('skill_snapshots',[])}
            for dep in frozen.get('dependencies',[]):
                if dep['kind']=='skill':
                    skill=skills.get(dep['entity_id'])
                    if skill is not None:dep['source_sha256']=fingerprint(skill)
                else:
                    if catalog is None:catalog=dependency_catalog(origin)
                    actual=catalog.get((dep['kind'],dep['entity_id']))
                    if actual is not None:dep['source_sha256']=actual.source_sha256
            for selection in frozen.get('context_options',{}).get('search_selections',[]):
                if selection['kind']=='skill':
                    skill=skills.get(selection['entity_id'])
                    if skill is not None:selection['source_sha256']=fingerprint(skill)
                elif selection['kind']!='material':
                    if catalog is None:catalog=dependency_catalog(origin)
                    actual=catalog.get((selection['kind'],selection['entity_id']))
                    if actual is not None:selection['source_sha256']=actual.source_sha256
            for source in frozen.get('parameters',{}).get('sources',[]):
                dep=next((value for value in frozen.get('dependencies',[]) if value['kind']==source['kind'] and value['entity_id']==source['entity_id']),None)
                if dep is not None:source['source_sha256']=dep['source_sha256']


def _transform(state, mapper,skill_mapper=None):
    """卷/场景无独立ID；文本、number/order、时间及其它字段逐字保留。"""
    from novel_writer.domain.book_creation import fingerprint
    state = deepcopy(state)
    if state['workspace_version']==1:
        state['document']=normalize_persistent_document(state['document'])
    document = state['document']
    project = document['project']['id']
    model_bridge_ids={item['id'] for item in state.get('model_bridge_proposals',[])}
    trial_task_ids={v['id'] for v in state.get('style_trial_tasks',[])}
    trial_candidate_ids={v['id'] for v in state.get('style_trial_candidates',[])}
    trial_experiment_ids={v['id'] for v in state.get('comparison_experiments',[]) if v.get('trial_kind')=='style_trial'}
    arena_reports={v['id'] for v in state.get('model_reports',[])}
    c04_tasks={v['id']:kind+'_task' for kind in ('scene_expansion','chapter_planning') for v in state.get(kind+'_tasks',[])}
    c04_candidates={v['id']:kind+'_candidate' for kind in ('scene_expansion','chapter_planning') for v in state.get(kind+'_candidates',[])}
    writing_book_locks={v['id'] for v in state.get('book_creation_locks',[])}
    original_book_lock_ids={v['id'] for v in state.get('book_creation_locks',[])}
    def ref(kind, identifier):
        return None if identifier is None else mapper(project, kind, identifier)
    for entry in state.get('memory_refresh_events',[]):
        entry['id']=ref('memory_refresh_event',entry['id'])
        if 'operation_id' in entry:entry['operation_id']=ref('memory_refresh_operation',entry['operation_id'])
        if 'job_id' in entry:entry['job_id']=ref('memory_refresh_event',entry['job_id'])
        for key,kind in (('chapter_ids','chapter'),('memory_ids','memory'),('rollup_ids','memory_rollup')):
            if key in entry:entry[key]=[ref(kind,i) for i in entry[key]]
        for source in entry.get('sources',[]):
            source['project_id']=ref('project',source['project_id'])
            source['entity_id']=ref('chapter',source['entity_id'])
            source['chapter_id']=ref('chapter',source['chapter_id'])
            source['version_id']=ref('version',source['version_id'])
        # Preserve policy origin so a copied project cannot inherit automatic execution.
    for entry in state.get('memory_automation_events',[]):
        entry['id']=ref('memory_automation_operation',entry['id'])
        entry['operation_id']=entry['id']
        if 'job_id' in entry:entry['job_id']=ref('memory_automation_operation',entry['job_id'])
        for key,kind in (('chapter_ids','chapter'),('memory_ids','memory'),('rollup_ids','memory_rollup')):
            if key in entry:entry[key]=[ref(kind,i) for i in entry[key]]
        # Deliberately preserve authorization_project_id: copied books must opt in again.
    def source_ref(kind, identifier, old_project_id):
        if kind=='rule' and identifier==str(uuid5(NAMESPACE_URL,old_project_id+'/legacy-writing-rules')):
            return str(uuid5(NAMESPACE_URL,ref('project',old_project_id)+'/legacy-writing-rules'))
        return ref(kind,identifier)
    def comparison_ref(kind,identifier):
        namespace=(c04_tasks if kind=='task' else c04_candidates).get(identifier)
        if namespace is None:namespace='style_trial_task' if kind=='task' and identifier in trial_task_ids else 'style_trial_candidate' if kind=='candidate' and identifier in trial_candidate_ids else 'model_report' if kind=='candidate' and identifier in arena_reports else kind
        return ref(namespace,identifier)
    def entity(item, kind):
        item['id'] = ref(kind, item['id'])
        if 'project_id' in item:
            item['project_id'] = ref('project', item['project_id'])
        if kind == 'book_outline':
            for volume in item['volumes']:
                volume['chapter_ids'] = [ref('chapter', value) for value in volume['chapter_ids']]
        elif kind == 'character':
            for relation in item['relationships']:
                relation['target_character_id'] = ref('character', relation['target_character_id'])
        elif kind == 'chapter_outline':
            item['chapter_id'] = ref('chapter', item['chapter_id'])
            item['character_ids'] = [ref('character', value) for value in item['character_ids']]
            for scene in item['scenes']:
                scene['character_ids'] = [ref('character', value) for value in scene['character_ids']]
        if 'current_version_id' in item:
            item['current_version_id'] = ref('version', item['current_version_id'])
    entity(document['project'], 'project')
    if document['book_outline'] is not None:
        entity(document['book_outline'], 'book_outline')
    for name, kind in (('chapters','chapter'), ('characters','character'), ('chapter_outlines','chapter_outline')):
        for item in document[name]: entity(item, kind)
    for version in document['versions']:
        version['id'] = ref('version', version['id'])
        version['project_id'] = ref('project', version['project_id'])
        version['entity_id'] = ref(version['entity_type'], version['entity_id'])
        version['previous_version_id'] = ref('version', version['previous_version_id'])
        entity(version['snapshot'], version['entity_type'])
    state['ideas'] = {ref('chapter', key): value for key, value in state['ideas'].items()}
    style_ids={v['id'] for v in state.get('style_cards',[])}
    for preset in state.get('creation_presets',[]):
        if preset['settings']['style_id'] in style_ids:preset['settings']['style_id']=ref('style_card',preset['settings']['style_id'])
    style_refs={'id':None,'project_id':'project','operation_id':'style_operation','source_id':'style_source','analysis_id':'style_analysis','owner_id':'style_owner','request_id':'style_request','result_id':'style_result','previous_event_id':'style_event','previous_candidate_id':'style_candidate','style_id':'style_family','previous_version_id':'style_card','version_id':'style_card','chapter_id':'chapter','preset_version_id':'creation_preset_version'}
    for collection,kind in [('style_sources','style_source'),('style_analyses','style_analysis'),('style_requests','style_request'),('style_events','style_event'),('style_results','style_result'),('style_candidates','style_candidate'),('style_cards','style_card'),('style_choices','style_choice'),('style_budgets','style_budget')]:
        for item in state.get(collection,[]):
            item['id']=ref(kind,item['id'])
            for key,reference in style_refs.items():
                if reference and key in item:item[key]=ref(reference,item[key])
            for covered in item.get('coverage',[]):
                for key,reference in [('source_id','style_source'),('request_id','style_request'),('candidate_id','style_candidate')]:covered[key]=ref(reference,covered[key])
    for card in state.get('style_cards',[]):card['coverage_sha256']=fingerprint(card['coverage'])
    for collection,kind in [('web_queries','web_query'),('web_events','web_event'),('web_results','web_result'),('web_sources','web_source'),('web_identities','web_identity'),('web_reads','web_read'),('web_pages','web_page'),('web_imports','web_import')]:
        for item in state.get(collection,[]):
            item['id']=ref(kind,item['id'])
            for key,reference in [('project_id','project'),('operation_id','web_operation'),('owner_id','web_owner'),('query_id','web_query'),('read_id','web_read'),('result_id','web_result'),('identity_id','web_identity'),('page_id','web_page'),('previous_event_id','web_event'),('preset_version_id','creation_preset_version')]:
                if key in item:item[key]=ref(reference,item[key])
            if 'source_id' in item:item['source_id']=ref('style_source' if collection=='web_imports' else 'web_source',item['source_id'])
            if collection=='web_reads':
                from novel_writer.domain.public_search import read_hash
                item['request_sha256']=read_hash(item['url'],item['source_id'],item['owner_id'])
    for task in state.get('style_trial_tasks',[]):
        old_budget=task['budget_id']
        for key,kind in [('id','style_trial_task'),('project_id','project'),('operation_id','style_trial_operation'),('owner_id','style_trial_owner'),('preset_version_id','creation_preset_version'),('retry_of','style_trial_task')]:task[key]=ref(kind,task[key])
        task['budget_id']=ref('comparison_experiment' if old_budget in trial_experiment_ids else 'style_trial_operation',old_budget)
        seed=task['seed'];seed['options']['chapter_id']=ref('chapter',seed['options']['chapter_id']);seed['options']['plan_version_id']=ref('book_creation_version',seed['options']['plan_version_id']);seed['preset_version_id']=ref('creation_preset_version',seed['preset_version_id']);seed['lock_ids']=[ref('book_creation_lock' if v in original_book_lock_ids else 'planning_lock',v) for v in seed['lock_ids']]
        for guard in seed['guards']:
            for key,kind in [('project_id','project'),('chapter_id','chapter'),('version_id','version')]:guard[key]=ref(kind,guard[key])
            guard['entity_id']=ref('project' if guard['kind'] in ('worldbuilding','writing_rules') else 'chapter' if guard['kind']=='idea' else guard['kind'],guard['entity_id'])
        if task['style'] is not None:
            task['style']['version_id']=ref('style_card',task['style']['version_id']);task['style']['style_id']=ref('style_family',task['style']['style_id'])
    for collection,kind in [('style_trial_events','style_trial_event'),('style_trial_results','style_trial_result'),('style_trial_candidates','style_trial_candidate'),('style_trial_choices','style_trial_choice')]:
        for item in state.get(collection,[]):
            item['id']=ref(kind,item['id'])
            for key,reference in [('project_id','project'),('operation_id','style_trial_operation'),('task_id','style_trial_task'),('previous_event_id','style_trial_event'),('owner_id','style_trial_owner'),('result_id','style_trial_result'),('candidate_id','style_trial_candidate'),('style_choice_id','style_choice'),('chapter_id','chapter')]:
                if key in item:item[key]=ref(reference,item[key])
    def memory(item):
        item['id']=ref('memory',item['id']);item['project_id']=ref('project',item['project_id'])
        item['position_chapter_id']=ref('chapter',item['position_chapter_id'])
        item['character_id']=ref('character',item['character_id'])
        source=item['source'];source['project_id']=ref('project',source['project_id'])
        source['chapter_id']=ref('chapter',source['chapter_id'])
        kind=source['kind'];entity_kind='project' if kind in ('worldbuilding','writing_rules') else 'chapter' if kind=='idea' else kind
        source['entity_id']=ref(entity_kind,source['entity_id']);source['version_id']=ref('version',source['version_id'])
    for item in state.get('creation_presets',[]):
        for key,kind in (('id','creation_preset_version'),('project_id','project'),('operation_id','creation_preset_operation'),('preset_id','creation_preset_family'),('previous_version_id','creation_preset_version')):item[key]=ref(kind,item[key])
    for item in state.get('creation_preset_choices',[]):
        for key,kind in (('id','creation_preset_choice'),('project_id','project'),('operation_id','creation_choice_operation'),('version_id','creation_preset_version')):item[key]=ref(kind,item[key])
    for item in state.get('book_creation_versions',[]):
        for key,kind in (('id','book_creation_version'),('project_id','project'),('operation_id','book_creation_operation'),('branch_id','book_creation_branch'),('previous_version_id','book_creation_version'),('derived_from_version_id','book_creation_version')):item[key]=ref(kind,item[key])
        for character in item['data']['characters']:character['id']=ref('character',character['id'])
        for volume in item['data']['volumes']:
            volume['id']=ref('book_creation_volume',volume['id'])
            for chapter in volume['chapters']:chapter['id']=ref('chapter',chapter['id']);chapter['outline_id']=ref('chapter_outline',chapter['outline_id'])
    creation_versions={value['id']:value for value in state.get('book_creation_versions',[])}
    for item in state.get('book_creation_choices',[]):
        for key,kind in (('id','book_creation_choice'),('project_id','project'),('operation_id','book_creation_choice_operation'),('version_id','book_creation_version')):item[key]=ref(kind,item[key])
    for item in state.get('book_creation_locks',[]):
        for key,kind in (('id','book_creation_lock'),('project_id','project'),('operation_id','book_creation_lock_operation'),('version_id','book_creation_version'),('previous_lock_id','book_creation_lock')):item[key]=ref(kind,item[key])
        from novel_writer.domain.book_creation import fingerprint
        item['value_sha256']=fingerprint(creation_versions[item['version_id']]['data'][item['field']])
    for item in state.get('book_creation_previews',[]):
        for key,kind in (('id','book_creation_preview'),('project_id','project'),('operation_id','book_creation_preview_operation'),('version_id','book_creation_version'),('owner_id','book_creation_owner')):item[key]=ref(kind,item[key])
        from novel_writer.domain.book_creation import fingerprint
        item['plan_sha256']=fingerprint(creation_versions[item['version_id']]['data'])
        for key,kind in (('chapter_creates','chapter'),('chapter_reuses','chapter'),('character_creates','character'),('character_reuses','character'),('outline_ids','chapter_outline')):item['impact'][key]=[ref(kind,value) for value in item['impact'][key]]
        for conflict in item['impact']['conflicts']:
            if conflict['entity_id'] is not None:conflict['entity_id']=ref('book_creation_lock' if conflict['code']=='creation.lock_conflict' else 'chapter',conflict['entity_id'])
    for item in state.get('book_creation_decisions',[]):
        for key,kind in (('id','book_creation_decision'),('project_id','project'),('operation_id','book_creation_decision_operation'),('version_id','book_creation_version'),('preview_id','book_creation_preview')):item[key]=ref(kind,item[key])
        for key,kind in (('chapter_ids','chapter'),('character_ids','character'),('outline_ids','chapter_outline'),('document_version_ids','version')):item[key]=[ref(kind,value) for value in item[key]]
    def book_ai_plan(data):
        for character in data['characters']:character['id']=ref('character',character['id'])
        for volume in data['volumes']:
            volume['id']=ref('book_creation_volume',volume['id'])
            for chapter in volume['chapters']:chapter['id']=ref('chapter',chapter['id']);chapter['outline_id']=ref('chapter_outline',chapter['outline_id'])
    for item in state.get('book_ai_tasks',[]):
        for key,kind in (('id','book_ai_task'),('request_id','book_ai_request'),('project_id','project'),('source_version_id','book_creation_version'),('branch_id','book_creation_branch'),('owner_id','book_ai_owner'),('preset_version_id','creation_preset_version')):item[key]=ref(kind,item[key])
        book_ai_plan(item['source_guard']);item['source_sha256']=fingerprint(item['source_guard'])
    for item in state.get('book_ai_events',[]):
        for key,kind in (('id','book_ai_event'),('task_id','book_ai_task'),('previous_event_id','book_ai_event'),('attempt_id','book_ai_attempt'),('owner_id','book_ai_owner'),('response_id','book_ai_result'),('candidate_id','book_ai_candidate')):item[key]=ref(kind,item[key])
    for item in state.get('book_ai_results',[]):
        for key,kind in (('id','book_ai_result'),('project_id','project'),('task_id','book_ai_task'),('attempt_id','book_ai_attempt')):item[key]=ref(kind,item[key])
    for item in state.get('book_ai_candidates',[]):
        for key,kind in (('id','book_ai_candidate'),('project_id','project'),('task_id','book_ai_task'),('response_id','book_ai_result'),('operation_id','book_ai_candidate_operation'),('previous_candidate_id','book_ai_candidate')):item[key]=ref(kind,item[key])
        if item['plan'] is not None:book_ai_plan(item['plan']);item['data_sha256']=fingerprint(item['plan'])
    book_ai_candidates={value['id']:value for value in state.get('book_ai_candidates',[])}
    for item in state.get('book_ai_reviews',[]):
        for key,kind in (('id','book_ai_review'),('project_id','project'),('operation_id','book_ai_review_operation'),('task_id','book_ai_task'),('candidate_id','book_ai_candidate'),('source_version_id','book_creation_version'),('owner_id','book_ai_owner')):item[key]=ref(kind,item[key])
        book_ai_plan(item['plan']);item['candidate_sha256']=book_ai_candidates[item['candidate_id']]['data_sha256'];item['source_sha256']=fingerprint(creation_versions[item['source_version_id']]['data'])
        from novel_writer.domain.book_ai import review_digest
        item['review_sha256']=review_digest(item)
    for item in state.get('book_ai_adoptions',[]):
        for key,kind in (('id','book_ai_adoption'),('project_id','project'),('task_id','book_ai_task'),('candidate_id','book_ai_candidate'),('review_id','book_ai_review'),('operation_id','book_ai_adoption_operation'),('version_id','book_creation_version')):item[key]=ref(kind,item[key])
    def planning_ids(value):
        if 'character_ids' in value:value['character_ids']=[ref('character',v) for v in value['character_ids']]
        for scene in value.get('scenes',[]):scene['character_ids']=[ref('character',v) for v in scene['character_ids']]
    for item in state.get('chapter_planning_tasks',[]):
        bound=item['source_options'].get('rule_task_id') is not None
        for key,kind in (('id','chapter_planning_task'),('request_id','task_request' if bound else 'chapter_planning_request'),('project_id','project'),('chapter_id','chapter'),('owner_id','chapter_planning_owner'),('preset_version_id','creation_preset_version')):item[key]=ref(kind,item[key])
        options=item['source_options'];options['chapter_id']=ref('chapter',options['chapter_id']);options['character_ids']=[ref('character',v) for v in options['character_ids']]
        if bound:options['rule_task_id']=ref('task_request',options['rule_task_id'])
        guard=item['source_guard'];guard['project_id']=ref('project',guard['project_id']);guard['chapter_id']=ref('chapter',guard['chapter_id'])
        guard['known_character_ids']=[ref('character',v) for v in guard['known_character_ids']]
        for character in guard['characters']:character['id']=ref('character',character['id'])
        if guard['outline'] is not None:
            guard['outline']['id']=ref('chapter_outline',guard['outline']['id']);guard['outline']['version_id']=ref('version',guard['outline']['version_id']);planning_ids(guard['outline'])
        for location in guard['locations']:location['chapter_id']=ref('chapter',location['chapter_id'])
        for fact in guard['facts']:
            fact['id']=ref('memory',fact['id']);fact['position_chapter_id']=ref('chapter',fact['position_chapter_id'])
        if guard['style'] is not None:guard['style']['id']=ref('style_card',guard['style']['id'])
        item['context_text']=json.dumps(guard,ensure_ascii=False,sort_keys=True,separators=(',',':'));item['context_sha256']=__import__('hashlib').sha256(item['context_text'].encode('utf8')).hexdigest();item['source_sha256']=fingerprint(guard)
    for item in state.get('chapter_planning_events',[]):
        for key,kind in (('id','chapter_planning_event'),('task_id','chapter_planning_task'),('previous_event_id','chapter_planning_event'),('attempt_id','chapter_planning_attempt'),('owner_id','chapter_planning_owner'),('response_id','chapter_planning_result'),('candidate_id','chapter_planning_candidate')):item[key]=ref(kind,item[key])
    for item in state.get('chapter_planning_results',[]):
        for key,kind in (('id','chapter_planning_result'),('project_id','project'),('task_id','chapter_planning_task'),('attempt_id','chapter_planning_attempt')):item[key]=ref(kind,item[key])
    for item in state.get('chapter_planning_candidates',[]):
        for key,kind in (('id','chapter_planning_candidate'),('project_id','project'),('task_id','chapter_planning_task'),('response_id','chapter_planning_result'),('operation_id','chapter_planning_candidate_operation'),('previous_candidate_id','chapter_planning_candidate')):item[key]=ref(kind,item[key])
        if item['plan'] is not None:planning_ids(item['plan']);item['data_sha256']=fingerprint(item['plan'])
    planning_candidates={value['id']:value for value in state.get('chapter_planning_candidates',[])}
    for item in state.get('chapter_planning_reviews',[]):
        for key,kind in (('id','chapter_planning_review'),('project_id','project'),('operation_id','chapter_planning_review_operation'),('task_id','chapter_planning_task'),('candidate_id','chapter_planning_candidate'),('owner_id','chapter_planning_owner')):item[key]=ref(kind,item[key])
        planning_ids(item['before']);planning_ids(item['after'])
        if item['plan'] is not None:planning_ids(item['plan'])
        from novel_writer.domain.chapter_planning import review_digest
        item['review_sha256']=review_digest(item)
    for item in state.get('chapter_planning_adoptions',[]):
        for key,kind in (('id','chapter_planning_adoption'),('project_id','project'),('task_id','chapter_planning_task'),('candidate_id','chapter_planning_candidate'),('review_id','chapter_planning_review'),('operation_id','chapter_planning_adoption_operation'),('outline_id','chapter_outline'),('outline_version_id','version')):item[key]=ref(kind,item[key])
        item['request_sha256']=fingerprint(dict(operation_id=item['operation_id'],task_id=item['task_id'],candidate_id=item['candidate_id'],candidate_sha256=planning_candidates[item['candidate_id']]['data_sha256'],review_id=item['review_id'],review_sha256=next(v['review_sha256'] for v in state['chapter_planning_reviews'] if v['id']==item['review_id']),expected_revision=item['expected_revision'],confirm_chapter=item['confirm_chapter']))
    for item in state.get('chapter_planning_late_results',[]):
        for key,kind in (('id','chapter_planning_late'),('project_id','project'),('task_id','chapter_planning_task'),('attempt_id','chapter_planning_attempt')):item[key]=ref(kind,item[key])
    def expansion_guard(guard):
        guard['chapter_id']=ref('chapter',guard['chapter_id']);guard['known_character_ids']=[ref('character',v) for v in guard['known_character_ids']]
        for character in guard['characters']:character['id']=ref('character',character['id'])
        if guard['scene'] is not None:guard['scene']['character_ids']=[ref('character',v) for v in guard['scene']['character_ids']]
        if guard['outline'] is not None:
            guard['outline']['id']=ref('chapter_outline',guard['outline']['id']);guard['outline']['version_id']=ref('version',guard['outline']['version_id'])
            guard['outline']['character_ids']=[ref('character',v) for v in guard['outline']['character_ids']]
            for scene in guard['outline']['scenes']:scene['character_ids']=[ref('character',v) for v in scene['character_ids']]
        if guard['style'] is not None:guard['style']['id']=ref('style_card',guard['style']['id'])
        for fact in guard['facts']:fact['id']=ref('memory',fact['id']);fact['position_chapter_id']=ref('chapter',fact['position_chapter_id'])
    for item in state.get('scene_expansion_tasks',[]):
        bound=item['source_options'].get('rule_task_id') is not None
        for key,kind in (('id','scene_expansion_task'),('request_id','task_request' if bound else 'scene_expansion_request'),('project_id','project'),('chapter_id','chapter'),('owner_id','scene_expansion_owner'),('preset_version_id','creation_preset_version')):item[key]=ref(kind,item[key])
        options=item['source_options'];options['chapter_id']=ref('chapter',options['chapter_id']);options['character_ids']=[ref('character',v) for v in options['character_ids']]
        if bound:options['rule_task_id']=ref('task_request',options['rule_task_id'])
        expansion_guard(item['source_guard']);item['source_sha256']=fingerprint(item['source_guard'])
    for item in state.get('scene_expansion_events',[]):
        for key,kind in (('id','scene_expansion_event'),('task_id','scene_expansion_task'),('previous_event_id','scene_expansion_event'),('attempt_id','scene_expansion_attempt'),('owner_id','scene_expansion_owner'),('response_id','scene_expansion_result'),('candidate_id','scene_expansion_candidate')):item[key]=ref(kind,item[key])
    for item in state.get('scene_expansion_results',[]):
        for key,kind in (('id','scene_expansion_result'),('project_id','project'),('task_id','scene_expansion_task'),('attempt_id','scene_expansion_attempt')):item[key]=ref(kind,item[key])
    for item in state.get('scene_expansion_candidates',[]):
        for key,kind in (('id','scene_expansion_candidate'),('project_id','project'),('task_id','scene_expansion_task'),('response_id','scene_expansion_result'),('operation_id','scene_expansion_candidate_operation'),('previous_candidate_id','scene_expansion_candidate')):item[key]=ref(kind,item[key])
    expansion_candidates={value['id']:value for value in state.get('scene_expansion_candidates',[])}
    for item in state.get('scene_expansion_reviews',[]):
        for key,kind in (('id','scene_expansion_review'),('project_id','project'),('operation_id','scene_expansion_review_operation'),('task_id','scene_expansion_task'),('candidate_id','scene_expansion_candidate'),('owner_id','scene_expansion_owner')):item[key]=ref(kind,item[key])
        from novel_writer.domain.scene_expansion import review_digest as expansion_review_digest
        item['review_sha256']=expansion_review_digest(item)
    for item in state.get('scene_expansion_adoptions',[]):
        for key,kind in (('id','scene_expansion_adoption'),('project_id','project'),('task_id','scene_expansion_task'),('candidate_id','scene_expansion_candidate'),('review_id','scene_expansion_review'),('operation_id','scene_expansion_adoption_operation'),('version_before','version'),('version_after','version')):item[key]=ref(kind,item[key])
        item['request_sha256']=fingerprint(dict(operation_id=item['operation_id'],task_id=item['task_id'],candidate_id=item['candidate_id'],candidate_sha256=expansion_candidates[item['candidate_id']]['data_sha256'],review_id=item['review_id'],review_sha256=next(v['review_sha256'] for v in state['scene_expansion_reviews'] if v['id']==item['review_id']),expected_revision=item['expected_revision'],confirm_chapter=item['confirm_chapter'],authorize_confirmed=item['authorize_confirmed']))
    for item in state.get('scene_expansion_late_results',[]):
        for key,kind in (('id','scene_expansion_late'),('project_id','project'),('task_id','scene_expansion_task'),('attempt_id','scene_expansion_attempt')):item[key]=ref(kind,item[key])
    for item in state.get('chapter_lifecycle_events',[]):
        for key,kind in (('id','chapter_lifecycle_event'),('project_id','project'),('operation_id','chapter_lifecycle_operation'),('chapter_id','chapter')):item[key]=ref(kind,item[key])
    for item in state.get('chapter_trash_events',[]):
        for key,kind in (('id','chapter_trash_event'),('project_id','project'),('operation_id','chapter_trash_operation'),('chapter_id','chapter'),('trash_event_id','chapter_trash_event')):
            if item[key] is not None:item[key]=ref(kind,item[key])
    from novel_writer.domain.author_scope import remap_events
    remap_events(state,ref)
    console_sessions={value['id']:{'project_id':value['project_id']} for value in state.get('console_sessions',[])}
    for item in state.get('console_sessions',[]):
        for key,kind in (('id','console_session'),('project_id','project')):item[key]=ref(kind,item[key])
    for item in state.get('console_messages',[]):
        for key,kind in (('id','console_message'),('project_id','project'),('session_id','console_session')):item[key]=ref(kind,item[key])
        for reference in item['refs']:
            reference['id']=ref('book_ai_task' if reference['kind']=='task' and any(v['id']==ref('book_ai_task',reference['id']) for v in state.get('book_ai_tasks',[])) else 'book_ai_candidate' if reference['kind']=='candidate' and any(v['id']==ref('book_ai_candidate',reference['id']) for v in state.get('book_ai_candidates',[])) else 'console_'+reference['kind'] if reference['kind'] in ('session','step') else reference['kind'],reference['id'])
    for item in state.get('console_plans',[]):
        for key,kind in (('id','console_plan'),('project_id','project'),('session_id','console_session')):item[key]=ref(kind,item[key])
        for step in item['steps']:step['id']=ref('console_step',step['id']);step['chapter_id']=ref('chapter',step['chapter_id'])
    for item in state.get('console_dispatches',[]):
        for key,kind in (('id','console_dispatch'),('project_id','project'),('session_id','console_session'),('step_id','console_step')):item[key]=ref(kind,item[key])
        task_kind={'chapter_planning':'chapter_planning_task','chapter_writing':'task','scene_expansion':'scene_expansion_task'}[item['engine']]
        item['task_id']=ref(task_kind,item['task_id'])
    for item in state.get('console_runs',[]):
        for key,kind in (('id','console_run'),('project_id','project'),('session_id','console_session'),('current_step_id','console_run_step')):item[key]=ref(kind,item[key])
    for item in state.get('console_run_steps',[]):
        for key,kind in (('id','console_run_step'),('project_id','project'),('run_id','console_run'),('plan_step_id','console_step'),('chapter_id','chapter'),('dispatch_id','console_dispatch')):item[key]=ref(kind,item[key])
        if item['engine'] is not None:
            task_kind={'chapter_planning':'chapter_planning_task','chapter_writing':'task','scene_expansion':'scene_expansion_task'}[item['engine']]
            item['task_id']=ref(task_kind,item['task_id'])
    for item in state.get('console_run_actions',[]):
        for key,kind in (('id','console_run_action'),('project_id','project'),('run_id','console_run'),('operation_id','console_run_operation'),('step_id','console_run_step')):item[key]=ref(kind,item[key])
    for item in state.get('materials',[]):
        for key,kind in (('id','material'),('project_id','project'),('current_version_id','material_version')):item[key]=ref(kind,item[key])
    for item in state.get('material_versions',[]):
        for key,kind in (('id','material_version'),('project_id','project'),('material_id','material'),('previous_version_id','material_version')):item[key]=ref(kind,item[key])
    for item in state.get('material_chunks',[]):
        for key,kind in (('id','material_chunk'),('project_id','project'),('material_id','material'),('material_version_id','material_version')):item[key]=ref(kind,item[key])
    for item in state.get('material_operations',[]):
        for key,kind in (('id','material_operation'),('project_id','project'),('material_id','material'),('operation_id','material_operation_token'),('version_id','material_version')):item[key]=ref(kind,item[key])
    for item in state.get('rule_task_bindings',[]):
        item['id']=ref('task_request',item['id']);item['project_id']=ref('project',item['project_id']);item['chapter_id']=ref('chapter',item['chapter_id'])
    for item in state.get('scoped_rules',[]):
        item['id']=ref('rule',item['id']);item['project_id']=ref('project',item['project_id'])
        if item['scope']=='book':item['scope_id']=ref('project',item['scope_id'])
        elif item['scope']=='chapter':item['scope_id']=ref('chapter',item['scope_id'])
        elif item['scope']=='task':item['scope_id']=ref('task_request',item['scope_id'])
    def rule_snapshot(item):
        item['id']=source_ref('rule',item['id'],item['project_id']);item['project_id']=ref('project',item['project_id'])
        if item['scope']=='book':item['scope_id']=ref('project',item['scope_id'])
        elif item['scope']=='chapter':item['scope_id']=ref('chapter',item['scope_id'])
        elif item['scope']=='task':item['scope_id']=ref('task_request',item['scope_id'])
    for name in ('chapter_planning_tasks','scene_expansion_tasks'):
        for item in state.get(name,[]):
            if item['source_guard'].get('rule_sources') is not None:
                for rule in item['source_guard']['rule_sources']:rule_snapshot(rule)
                item['source_sha256']=fingerprint(item['source_guard'])
                if name=='chapter_planning_tasks':
                    item['context_text']=json.dumps(item['source_guard'],ensure_ascii=False,sort_keys=True,separators=(',',':'));item['context_sha256']=__import__('hashlib').sha256(item['context_text'].encode('utf8')).hexdigest()
    for item in state.get('scoped_rule_history',[]):
        item['id']=ref('scoped_rule_history',item['id']);item['project_id']=ref('project',item['project_id']);item['rule_id']=ref('rule',item['rule_id'])
        if item['before'] is not None:rule_snapshot(item['before'])
        if item['after'] is not None:rule_snapshot(item['after'])
    for task in state.get('rule_review_tasks',[]):
        from novel_writer.domain.rule_reviews import source_digest
        before={key:deepcopy(task[key]) for key in ('project_id','chapter_id','target_task_id','rules')}
        for key,kind in (('id','rule_review_task'),('request_id','rule_review_request'),('owner_id','rule_review_owner'),('project_id','project'),('chapter_id','chapter'),('target_task_id','task_request')):task[key]=ref(kind,task[key])
        for rule in task['rules']:rule_snapshot(rule)
        after={key:deepcopy(task[key]) for key in ('project_id','chapter_id','target_task_id','rules')}
        task['copy_mappings'].append(dict(before=before,after=after))
        task['source_sha256']=source_digest(task['project_id'],task['chapter_id'],task['target_task_id'],task['rules'])
    for item in state.get('rule_review_events',[]):
        for key,kind in (('id','rule_review_event'),('task_id','rule_review_task'),('previous_event_id','rule_review_event'),('attempt_id','rule_review_attempt')):item[key]=ref(kind,item[key])
    for item in state.get('rule_review_results',[]):
        for key,kind in (('id','rule_review_result'),('project_id','project'),('task_id','rule_review_task'),('attempt_id','rule_review_attempt')):item[key]=ref(kind,item[key])
    for task in state.get('semantic_retrieval_tasks',[]):
        from novel_writer.domain.semantic_retrieval import source_digest
        keys=('project_id','chapter_id','source_options','windows','coverage')
        before={key:deepcopy(task[key]) for key in keys}
        for key,kind in (('id','semantic_retrieval_task'),('request_id','semantic_retrieval_request'),('owner_id','semantic_retrieval_owner'),('project_id','project'),('chapter_id','chapter')):task[key]=ref(kind,task[key])
        options=task['source_options'];options['chapter_id']=ref('chapter',options['chapter_id']);options['material_ids']=[ref('material',i) for i in options['material_ids']]
        for window in task['windows']:
            selection=window['selection'];selection['project_id']=ref('project',selection['project_id']);selection['entity_id']=ref('material',selection['entity_id']);selection['version_id']=ref('material_version',selection['version_id'])
            locator=window['locator'];locator['project_id']=ref('project',locator['project_id']);locator['material_id']=ref('material',locator['material_id']);locator['version_id']=ref('material_version',locator['version_id'])
        after={key:deepcopy(task[key]) for key in keys}
        task['copy_mappings'].append(dict(before=before,after=after));task['source_sha256']=source_digest(after)
        # Exact original wire/response and model window IDs remain byte-identical.
    for collection in ('semantic_retrieval_events','semantic_retrieval_results'):
        for item in state.get(collection,[]):
            for key,kind in (('id','semantic_retrieval_event' if collection.endswith('events') else 'semantic_retrieval_result'),('task_id','semantic_retrieval_task'),('previous_event_id','semantic_retrieval_event'),('attempt_id','semantic_retrieval_attempt'),('project_id','project')):
                if key in item:item[key]=ref(kind,item[key])
    def rollup_source(item):
        item['memory_id']=ref('memory',item['memory_id']);item['position_chapter_id']=ref('chapter',item['position_chapter_id'])
        if item['character_id'] is not None:item['character_id']=ref('character',item['character_id'])
    def rollup(item):
        item['id']=ref('memory_rollup',item['id']);item['project_id']=ref('project',item['project_id']);item['through_chapter_id']=ref('chapter',item['through_chapter_id'])
        if item.get('chapter_source') is not None:
            source=item['chapter_source']
            for key,kind in (('project_id','project'),('entity_id','chapter'),('chapter_id','chapter'),('version_id','version')):source[key]=ref(kind,source[key])
        for source in item['sources']:rollup_source(source)
        item['sources']=sorted(item['sources'],key=source_sort_key)
        item['text']=render_text(item['title'],item['sources'])
    for item in state.get('memory_rollups',[]):rollup(item)
    for edit in state.get('memory_rollup_history',[]):
        edit['id']=ref('memory_rollup_history',edit['id']);edit['rollup_id']=ref('memory_rollup',edit['rollup_id'])
        edit['previous_version_id']=ref('memory_rollup_history',edit['previous_version_id']);rollup(edit['snapshot'])
    for item in state.get('memories',[]):memory(item)
    for edit in state.get('memory_history',[]):
        edit['id']=ref('memory_version',edit['id']);edit['memory_id']=ref('memory',edit['memory_id'])
        edit['previous_version_id']=ref('memory_version',edit['previous_version_id']);memory(edit['snapshot'])
    skillref=skill_mapper or (lambda identifier:identifier)
    def evidence(item):
        if 'identity_sha256' in item:
            kind=item['record_kind'];item['entity_id']=ref(kind,item['entity_id']);item['version_id']=ref('material_version' if kind=='material' else 'memory_version' if kind=='memory' else 'version',item['version_id'])
            for key,k in (('producer_task_id','task'),('producer_attempt_id','task_attempt'),('producer_node_attempt_id','workflow_attempt')):item[key]=ref(k,item[key])
            return
        item['entity_id']=ref(item['source_kind'],item['entity_id'])
        if 'chapter_id' in item:item['chapter_id']=ref('chapter',item['chapter_id'])
        if 'version_id' in item:item['version_id']=ref('version',item['version_id'])
    def waiver(item):
        for key,kind in (('id','rule_waiver'),('project_id','project'),('report_id','review_report'),('issue_id','review_issue')):item[key]=ref(kind,item[key])
        for ev in item['evidence']:evidence(ev)
    def dependency(item):
        kind=item['kind'];entity_kind='project' if kind in ('worldbuilding','writing_rules') else 'chapter' if kind=='idea' else kind
        old_project_id=item['project_id']
        item['project_id']=ref('project',item['project_id'])
        item['entity_id']=skillref(item['entity_id']) if kind=='skill' else source_ref(entity_kind,item['entity_id'],old_project_id)
        item['version_id']=ref('memory_version' if kind=='memory' else 'memory_rollup_history' if kind=='memory_rollup' else 'material_version' if kind=='material' else 'version',item['version_id'])
        if 'chapter_id' in item:item['chapter_id']=ref('chapter',item['chapter_id'])
        for reference in item.get('references',[]):
            reference['entity_id']=skillref(reference['entity_id']) if reference['kind']=='skill' else ref(reference['kind'],reference['entity_id'])
    def workflow_snapshot(item):
        for key,kind in (('project_id','project'),('chapter_id','chapter'),('producer_task_id','task'),('producer_attempt_id','task_attempt'),('producer_node_attempt_id','workflow_attempt'),('via_node_attempt_id','workflow_attempt'),('review_id','workflow_audit'),('search_node_attempt_id','workflow_attempt'),('version_id','version')):item[key]=ref(kind,item[key])
        item['entity_id']=ref({'candidate':'candidate','chapter':'chapter','chapter_outline':'chapter_outline'}[item['kind']],item['entity_id']);t=item['saved_target'];t['chapter_id']=ref('chapter',t['chapter_id']);t['version_id']=ref('version',t['version_id'])
    def workflow_ref(item):
        if item['kind']=='chapter_outline':
            item['entity_id']=ref('chapter_outline',item['entity_id']);item['version_id']=ref('version',item['version_id']);return
        kinds={'task':'task','candidate':'candidate','chapter':'chapter','review_report':'review_report','model_report':'model_report','workflow_audit':'workflow_audit','memory_proposal':'memory_proposal','model_memory_proposal':'model_memory_proposal','workflow_memory_proposal':'workflow_memory_proposal','planning_proposal':'planning_proposal','approval':'workflow_approval','adoption_receipt':'adoption','proposal_receipt':'proposal_receipt','model_proposal_receipt':'model_proposal_receipt','planning_receipt':'planning_receipt','workflow_receipt':'workflow_receipt','node_attempt':'workflow_attempt','manual_value':'workflow_run','search':'workflow_attempt'}
        item['entity_id']=ref(kinds[item['kind']],item['entity_id'])
        if item['version_id'] is not None and item['kind']!='manual_value':item['version_id']=ref('task_attempt' if item['kind']=='task' else 'version',item['version_id'])
    for task in state.get('generation_tasks',[]):
        task['id']=ref('task',task['id']);task['request_id']=ref('task_request',task['request_id']);task['project_id']=ref('project',task['project_id']);task['chapter_id']=ref('chapter',task['chapter_id'])
        task['attempt_id']=ref('task_attempt',task['attempt_id']);task['owner_id']=ref('task_owner',task['owner_id']);task['candidate_id']=ref('candidate',task['candidate_id'])
        frozen=task['frozen'];frozen['project_id']=ref('project',frozen['project_id']);frozen['chapter_id']=ref('chapter',frozen['chapter_id'])
        frozen['target']['chapter_id']=ref('chapter',frozen['target']['chapter_id']);frozen['target']['version_id']=ref('version',frozen['target']['version_id'])
        options=frozen['context_options'];options['chapter_id']=ref('chapter',options['chapter_id']);options['character_ids']=[ref('character',v) for v in options['character_ids']];options['memory_ids']=[ref('memory',v) for v in options['memory_ids']]
        if options.get('rule_task_id') is not None:options['rule_task_id']=ref('task_request',options['rule_task_id'])
        if options.get('retrieval_owner') is not None:options['retrieval_owner']=ref('retrieval_owner',options['retrieval_owner'])
        for selection in options['search_selections']:dependency(selection)
        for dep in frozen['dependencies']:dependency(dep)
        for skill in frozen['skill_snapshots']:skill['id']=skillref(skill['id'])
        params=frozen['parameters']
        if 'writing' in params:
            writing=params['writing']
            old_style=writing['style_version_id']
            for key,kind in [('prepared_owner','task_owner'),('retry_of','task'),('preset_version_id','creation_preset_version')]:writing[key]=ref(kind,writing[key])
            writing['style_version_id']=ref('style_card' if old_style in style_ids else 'creation_preset_version',old_style)
            writing['lock_ids']=[ref('book_creation_lock' if value in writing_book_locks else 'planning_lock',value) for value in writing['lock_ids']]
        if 'upstream' in params:
            def candidate_identity_value(s):return dict(project_id=s['project_id'],entity_id=s['entity_id'],task_id=s['producer_task_id'],attempt_id=s['producer_attempt_id'],producer_node_attempt_id=s['producer_node_attempt_id'],text_sha256=s['text_sha256'])
            before=candidate_identity_value(params['upstream']) if 'wire_source' in params else None
            workflow_snapshot(params['upstream'])
            if before is not None:params['copy_mappings'].append(dict(before=before,after=candidate_identity_value(params['upstream'])))
        if 'sources' in params:
            params['selected_chapter_ids']=[ref('chapter',v) for v in params['selected_chapter_ids']]
            params['previous_report_id']=ref('review_report',params['previous_report_id'])
            for source in params['sources']:
                source['project_id']=ref('project',source['project_id']);source['entity_id']=ref(source['kind'],source['entity_id']);source['chapter_id']=ref('chapter',source['chapter_id']);source['version_id']=ref('version',source['version_id'])
                source['character_ids']=[ref('character',v) for v in source['character_ids']]
                for scene in source['scenes']:scene['character_ids']=[ref('character',v) for v in scene['character_ids']]
            for item in params['waivers']:waiver(item)
        if 'deep_review' in params:
            scope=params['deep_review']
            for source in scope['sources']:
                kind=source['record_kind'];source['project_id']=ref('project',source['project_id']);source['entity_id']=ref(kind,source['entity_id']);source['version_id']=ref('material_version' if kind=='material' else 'memory_version' if kind=='memory' else 'version',source['version_id'])
                for key,k in (('producer_task_id','task'),('producer_attempt_id','task_attempt'),('producer_node_attempt_id','workflow_attempt')):source[key]=ref(k,source[key])
            from novel_writer.domain.deep_review import selection_digest
            scope['selection_sha256']=selection_digest(scope['checks'],scope['sources'])
    for candidate in state.get('generation_candidates',[]):
        for key,kind in (('id','candidate'),('project_id','project'),('chapter_id','chapter'),('task_id','task'),('attempt_id','task_attempt')):candidate[key]=ref(kind,candidate[key])
    for entry in state.get('task_events',[]):
        for key,kind in (('id','task_event'),('task_id','task'),('previous_event_id','task_event'),('attempt_id','task_attempt'),('owner_id','task_owner'),('candidate_id','candidate'),('adoption_id','adoption')):entry[key]=ref(kind,entry[key])
    for receipt in state.get('adoption_receipts',[]):
        for key,kind in (('id','adoption'),('project_id','project'),('chapter_id','chapter'),('task_id','task'),('candidate_id','candidate'),('version_before','version'),('version_after','version')):receipt[key]=ref(kind,receipt[key])
    for item in state.get('writing_corrections',[]):
        for key,kind in [('id','writing_correction'),('operation_id','writing_correction_operation'),('project_id','project'),('chapter_id','chapter'),('task_id','task'),('candidate_id','candidate'),('previous_id','writing_correction')]:item[key]=ref(kind,item[key])
    for item in state.get('writing_decisions',[]):
        for key,kind in [('id','writing_decision'),('project_id','project'),('task_id','task'),('candidate_id','candidate'),('correction_id','writing_correction'),('receipt_id','adoption'),('review_id','writing_review')]:item[key]=ref(kind,item[key])
        receipt=next(v for v in state['adoption_receipts'] if v['id']==item['receipt_id']);item['request_sha256']=fingerprint(dict(candidate_id=item['candidate_id'],adoption_id=item['receipt_id'],expected_revision=receipt['requested_revision'],authorize_confirmed=receipt['authorize_confirmed'],correction_id=item['correction_id'],review_id=item['review_id'],confirmed_review=True))
    for item in state.get('writing_late_results',[]):
        for key,kind in [('id','writing_late_result'),('project_id','project'),('task_id','task'),('attempt_id','task_attempt')]:item[key]=ref(kind,item[key])
    for report in state.get('review_reports',[]):
        for key,kind in (('id','review_report'),('project_id','project'),('task_id','task'),('chapter_id','chapter'),('previous_report_id','review_report')):report[key]=ref(kind,report[key])
        report['issue_ids']=[ref('review_issue',v) for v in report['issue_ids']];report['proposal_ids']=[ref('memory_proposal',v) for v in report['proposal_ids']]
    for issue in state.get('review_issues',[]):
        issue['id']=ref('review_issue',issue['id']);issue['project_id']=ref('project',issue['project_id']);issue['report_id']=ref('review_report',issue['report_id'])
        for item in issue['finding']['evidence']:evidence(item)
    for proposal in state.get('memory_proposals',[]):
        proposal['id']=ref('memory_proposal',proposal['id']);proposal['project_id']=ref('project',proposal['project_id']);proposal['report_id']=ref('review_report',proposal['report_id'])
        proposal['proposal']['position_chapter_id']=ref('chapter',proposal['proposal']['position_chapter_id']);evidence(proposal['proposal']['evidence'])
    for action in state.get('review_actions',[]):
        for key,kind in (('id','review_action'),('project_id','project'),('report_id','review_report'),('issue_id','review_issue'),('waiver_id','rule_waiver')):action[key]=ref(kind,action[key])
    for item in state.get('rule_waivers',[]):waiver(item)
    for receipt in state.get('proposal_receipts',[]):
        for key,kind in (('id','proposal_receipt'),('project_id','project'),('report_id','review_report'),('proposal_id','memory_proposal'),('memory_id','memory'),('memory_version_id','memory_version')):receipt[key]=ref(kind,receipt[key])
        receipt['conflict_memory_ids']=[ref('memory',v) for v in receipt['conflict_memory_ids']]
    def knowledge_source(item):
        old_project_id=item['project_id']
        item['project_id']=ref('project',item['project_id']);item['chapter_id']=ref('chapter',item['chapter_id']);item['version_id']=ref('version',item['version_id'])
        kind='project' if item['kind'] in ('worldbuilding','writing_rules') else 'chapter' if item['kind']=='idea' else item['kind'];item['entity_id']=source_ref(kind,item['entity_id'],old_project_id)
    def node(item):
        for key,kind in (('id','graph_node'),('project_id','project'),('edit_id','knowledge_edit'),('position_chapter_id','chapter'),('merged_into','graph_node')):item[key]=ref(kind,item[key])
        item['memory_ids']=[ref('memory',v) for v in item['memory_ids']];knowledge_source(item['source'])
    def edge(item):
        for key,kind in (('id','graph_edge'),('project_id','project'),('edit_id','knowledge_edit'),('position_chapter_id','chapter'),('from_id','graph_node'),('to_id','graph_node')):item[key]=ref(kind,item[key])
        knowledge_source(item['source'])
    def impact(item):
        for key,kind in (('later_chapter_ids','chapter'),('foreshadow_node_ids','graph_node'),('memory_ids','memory')):item[key]=[ref(kind,v) for v in item[key]]
    for item in state.get('knowledge_nodes',[]):node(item)
    for item in state.get('knowledge_edges',[]):edge(item)
    for item in state.get('graph_merges',[]):
        for key,kind in (('id','graph_merge'),('project_id','project'),('source_id','graph_node'),('target_id','graph_node')):item[key]=ref(kind,item[key])
        for n in item['before_nodes']:node(n)
        for e in item['before_edges']:edge(e)
        item['after_edit_ids']=[ref('knowledge_edit',v) for v in item['after_edit_ids']]
    for item in state.get('graph_restores',[]):
        for key,kind in (('id','graph_restore'),('project_id','project'),('merge_id','graph_merge')):item[key]=ref(kind,item[key])
    for name in ('planning_proposals','planning_locks'):
        for item in state.get(name,[]):
            item['id']=ref('planning_proposal' if name=='planning_proposals' else 'planning_lock',item['id']);item['project_id']=ref('project',item['project_id']);item['target_id']=ref(item['target_kind'],item['target_id'])
            if name=='planning_proposals':knowledge_source(item['source']);knowledge_source(item['target']);impact(item['impact'])
    for item in state.get('planning_receipts',[]):
        for key,kind in (('id','planning_receipt'),('project_id','project'),('proposal_id','planning_proposal'),('version_before','version'),('version_after','version')):item[key]=ref(kind,item[key])
    for item in state.get('local_edit_proposals',[]):
        origin='model_bridge_proposal' if 'model_proposal_id' in item else 'review_issue'
        for key,kind in (('id','local_edit'),('project_id','project'),('edit_id','knowledge_edit'),('issue_id',origin),('chapter_id','chapter')):item[key]=ref(kind,item[key])
        if 'model_proposal_id' in item:item['model_proposal_id']=ref('model_bridge_proposal',item['model_proposal_id'])
        for ev in item['evidence']:evidence(ev)
        for guard in item['guards']:dependency(guard)
        impact(item['impact'])
    for item in state.get('local_edit_receipts',[]):
        for key,kind in (('id','local_edit_receipt'),('project_id','project'),('proposal_id','local_edit'),('chapter_id','chapter'),('version_before','version'),('version_after','version')):item[key]=ref(kind,item[key])
    for item in state.get('generation_candidates',[]):
        if 'response_record_id' in item:item['response_record_id']=ref('model_result',item['response_record_id'])
    for item in state.get('model_results',[]):
        for key,kind in (('id','model_result'),('project_id','project'),('chapter_id','chapter'),('task_id','task'),('attempt_id','task_attempt')):item[key]=ref(kind,item[key])
    def model_draft(item):
        for ev in item['evidence']:evidence(ev)
        item['position_chapter_id']=ref('chapter',item['position_chapter_id'])
    for item in state.get('graph_extractions', []):
        for key,kind in (('id','graph_extraction'),('project_id','project'),('task_id','task'),('response_record_id','model_result')):item[key]=ref(kind,item[key])
        for draft in item['output']['nodes']+item['output']['edges']:model_draft(draft)
    for item in state.get('graph_decisions', []):
        for key,kind in (('id','graph_decision'),('project_id','project'),('extraction_id','graph_extraction')):item[key]=ref(kind,item[key])
        item['node_ids']=[ref('graph_node',v) for v in item['node_ids']]
        item['edge_ids']=[ref('graph_edge',v) for v in item['edge_ids']]
    for item in state.get('graph_item_decisions', []):
        for key,kind in (('id','graph_item_decision'),('project_id','project'),('extraction_id','graph_extraction')):item[key]=ref(kind,item[key])
        item['node_ids']=[ref('graph_node',v) for v in item['node_ids']]
        item['edge_ids']=[ref('graph_edge',v) for v in item['edge_ids']]
    def background_step(step):
        for key,kind in (('id','console_run_step'),('project_id','project'),('run_id','console_run'),('plan_step_id','console_step'),('chapter_id','chapter'),('dispatch_id','console_dispatch')):
            if key in step:step[key]=ref(kind,step[key])
        if step.get('engine') is not None and step.get('task_id') is not None:
            kind={'chapter_planning':'chapter_planning_task','chapter_writing':'task','scene_expansion':'scene_expansion_task'}[step['engine']]
            step['task_id']=ref(kind,step['task_id'])
    for item in state.get('console_background_batches',[]):
        for key,kind in (('id','console_background_batch'),('project_id','project'),('run_id','console_run'),('operation_id','console_background_operation'),('owner_id','console_background_owner')):
            item[key]=ref(kind,item[key])
        item['request']['step_ids']=[ref('console_run_step',v) for v in item['request']['step_ids']]
        preview=item['preview'];preview['run_id']=ref('console_run',preview['run_id'])
        preview['request']['step_ids']=[ref('console_run_step',v) for v in preview['request']['step_ids']]
        for selected in preview['items']:
            selected['step_id']=ref('console_run_step',selected['step_id'])
            background_step(selected['source']['step'])
    for item in state.get('console_background_events',[]):
        for key,kind in (('id','console_background_event'),('batch_id','console_background_batch'),('step_id','console_run_step')):
            item[key]=ref(kind,item[key])
        if 'source' in item['detail']:background_step(item['detail']['source']['step'])
        if 'task_id' in item['detail']:item['detail']['task_id']=ref('chapter_planning_task',item['detail']['task_id'])
    # Automatic canon maintenance is a V52 optional extension. Its audit and
    # checkpoint IDs must follow copied projects just like the older queues.
    if 'canon_maintenance_settings' in state:
        for item in state.get('canon_maintenance_settings',[]):
            item['id']=ref('canon_setting',item['id']); item['project_id']=ref('project',item['project_id']); item['operation_id']=ref('canon_operation',item['operation_id'])
        for item in state.get('canon_maintenance_facts',[]):
            item['id']=ref('canon_fact',item['id']); item['project_id']=ref('project',item['project_id']); item['chapter_id']=ref('chapter',item['chapter_id'])
            entity_kind={'character':'character','outline':'book_outline'}.get(item['kind'])
            if entity_kind is not None and item['entity'] not in ('book','book_outline'):
                item['entity']=ref(entity_kind,item['entity'])
        for item in state.get('canon_maintenance_events',[]):
            item['id']=ref('canon_event',item['id']); item['project_id']=ref('project',item['project_id']); item['chapter_id']=ref('chapter',item['chapter_id']); item['operation_id']=ref('canon_operation',item['operation_id'])
        for item in state.get('canon_maintenance_checkpoints',[]):
            item['id']=ref('canon_checkpoint',item['id']); item['project_id']=ref('project',item['project_id']); item['chapter_id']=ref('chapter',item['chapter_id']); item['event_ids']=[ref('canon_event',v) for v in item['event_ids']]
    for item in state.get('model_reports',[]):
        for key,kind in (('id','model_report'),('project_id','project'),('task_id','task'),('response_record_id','model_result')):item[key]=ref(kind,item[key])
        for finding in item['output']['findings']:
            for ev in finding['evidence']:evidence(ev)
        for draft in item['output']['proposals']:model_draft(draft)
        for draft in item['output']['bridges']:
            for ev in draft['evidence']:evidence(ev)
    for item in state.get('model_memory_proposals',[]):
        for key,kind in (('id','model_memory_proposal'),('project_id','project'),('report_id','model_report')):item[key]=ref(kind,item[key])
        model_draft(item['draft'])
    for item in state.get('deep_review_actions',[]):
        for key,kind in (('id','deep_review_action'),('project_id','project'),('report_id','model_report')):item[key]=ref(kind,item[key])
        from novel_writer.domain.deep_review import finding_signature
        report=next(r for r in state['model_reports'] if r['id']==item['report_id'])
        item['signature_sha256']=finding_signature(report['output']['findings'][item['finding_index']])
    for item in state.get('model_bridge_proposals',[]):
        for key,kind in (('id','model_bridge_proposal'),('project_id','project'),('report_id','model_report')):item[key]=ref(kind,item[key])
        for ev in item['draft']['evidence']:evidence(ev)
    for item in state.get('model_proposal_receipts',[]):
        proposal_kind='model_bridge_proposal' if item['proposal_id'] in model_bridge_ids else 'model_memory_proposal'
        for key,kind in (('id','model_proposal_receipt'),('project_id','project'),('report_id','model_report'),('proposal_id',proposal_kind),('memory_id','memory'),('memory_version_id','memory_version'),('local_proposal_id','local_edit')):item[key]=ref(kind,item[key])
    for item in state.get('comparison_experiments',[]):
        for key,kind in (('id','comparison_experiment'),('project_id','project'),('chapter_id','chapter')):item[key]=ref(kind,item[key])
        options=item.get('context_options');
        if options is not None:options['chapter_id']=ref('chapter',options['chapter_id']);options['character_ids']=[ref('character',v) for v in options['character_ids']];options['memory_ids']=[ref('memory',v) for v in options['memory_ids']]
        for selection in options['search_selections'] if options is not None else []:dependency(selection)
        for configuration in item['configurations']:
            configuration['id']=ref('comparison_configuration',configuration['id']);configuration['task_id']=comparison_ref('task',configuration['task_id'])
        if item.get('trial_kind')=='writing_candidates':
            from novel_writer.domain.writing_comparisons import common_input,task_record
            item['common_input_sha256']=common_input(task_record(state,item['task_kind'],item['configurations'][0]['task_id']),item['task_kind'])
        if item.get('task_kind')=='outline_chapter':
            options=item['planning_options'];options['chapter_id']=ref('chapter',options['chapter_id']);options['character_ids']=[ref('character',v) for v in options['character_ids']]
            item['context_sha256']=next(t['context_sha256'] for t in state['chapter_planning_tasks'] if t['id']==item['configurations'][0]['task_id'])
    for name,kind in (('comparison_scores','comparison_score'),('comparison_reveals','comparison_reveal'),('comparison_choices','comparison_choice'),('generation_presets','generation_preset')):
        for item in state.get(name,[]):
            item['id']=ref(kind,item['id']);item['project_id']=ref('project',item['project_id']);item['experiment_id']=ref('comparison_experiment',item['experiment_id'])
            if name=='comparison_scores':
                item['candidate_id']=comparison_ref('candidate',item['candidate_id'])
                if item['candidate_id'] in {r['id'] for r in state.get('model_reports',[])}:
                    output=next(r['output'] for r in state['model_reports'] if r['id']==item['candidate_id']);item['result_sha256']=__import__('hashlib').sha256(json.dumps(output,ensure_ascii=False,sort_keys=True).encode('utf8')).hexdigest()
            if name=='comparison_reveals':item['score_ids']=[ref('comparison_score',v) for v in item['score_ids']]
            if name=='comparison_choices':
                for key,k in (('task_id','task'),('candidate_id','candidate'),('preset_id','generation_preset')):item[key]=comparison_ref(k,item[key]) if k in ('task','candidate') else ref(k,item[key])
    for item in state.get('extension_templates',[]):
        for key,kind in (('id','extension_template_version'),('project_id','project'),('operation_id','extension_template_operation'),('template_id','extension_template_family'),('previous_version_id','extension_template_version')):item[key]=ref(kind,item[key])
    for item in state.get('workflow_templates',[]):
        for key,kind in (('id','workflow_template_version'),('project_id','project'),('operation_id','workflow_template_operation'),('template_id','workflow_template_family'),('previous_version_id','workflow_template_version')):item[key]=ref(kind,item[key])
    for item in state.get('workflow_runs',[]):
        for key,kind in (('id','workflow_run'),('project_id','project'),('operation_id','workflow_run_operation'),('template_version_id','workflow_template_version'),('chapter_id','chapter')):item[key]=ref(kind,item[key])
    for item in state.get('workflow_run_events',[]):
        for key,kind in (('id','workflow_run_event'),('run_id','workflow_run'),('previous_event_id','workflow_run_event'),('owner_id','workflow_owner'),('epoch','workflow_epoch')):item[key]=ref(kind,item[key])
    for item in state.get('workflow_attempts',[]):
        for key,kind in (('id','workflow_attempt'),('project_id','project'),('run_id','workflow_run'),('task_id','task')):item[key]=ref(kind,item[key])
        item['input_attempt_ids']=[ref('workflow_attempt',v) for v in item['input_attempt_ids']]
        for r in item['input_refs']:workflow_ref(r)
    for item in state.get('workflow_node_events',[]):
        for key,kind in (('id','workflow_node_event'),('run_id','workflow_run'),('attempt_id','workflow_attempt'),('previous_event_id','workflow_node_event'),('approval_id','workflow_approval')):item[key]=ref(kind,item[key])
        for r in item['output_refs']:workflow_ref(r)
        if item['snapshot'] is not None:workflow_snapshot(item['snapshot'])
        for hit in item['search_hits']:dependency(hit['selection'])
    for item in state.get('workflow_approvals',[]):
        for key,kind in (('id','workflow_approval'),('project_id','project'),('run_id','workflow_run'),('node_attempt_id','workflow_attempt'),('epoch','workflow_epoch')):item[key]=ref(kind,item[key])
        workflow_ref(item['input_ref'])
    for item in state.get('workflow_audits',[]):
        for key,kind in (('id','workflow_audit'),('project_id','project'),('task_id','task'),('node_attempt_id','workflow_attempt')):item[key]=ref(kind,item[key])
        workflow_snapshot(item['upstream'])
        if 'response_record_id' in item:item['response_record_id']=ref('model_result',item['response_record_id'])
        for finding in item['output']['findings']:
            for ev in finding['evidence']:
                ev['entity_id']=ref('candidate' if ev['source_kind']=='candidate' else 'chapter',ev['entity_id'])
                for key,kind in (('task_id','task'),('attempt_id','task_attempt'),('producer_node_attempt_id','workflow_attempt'),('version_id','version')):ev[key]=ref(kind,ev[key])
    for item in state.get('workflow_memory_proposals',[]):
        for key,kind in (('id','workflow_memory_proposal'),('project_id','project'),('run_id','workflow_run'),('node_attempt_id','workflow_attempt')):item[key]=ref(kind,item[key])
        workflow_snapshot(item['source'])
    for item in state.get('workflow_receipts',[]):
        for key,kind in (('id','workflow_receipt'),('project_id','project'),('run_id','workflow_run'),('node_attempt_id','workflow_attempt'),('approval_id','workflow_approval'),('memory_id','memory'),('memory_version_id','memory_version')):item[key]=ref(kind,item[key])
        kind={'adoption_receipt':'adoption','planning_receipt':'planning_receipt','model_proposal_receipt':'model_proposal_receipt','workflow_memory':'workflow_business_operation'}[item['business_kind']];item['business_id']=ref(kind,item['business_id'])
    for item in state.get('character_arcs',[]):
        for key,kind in (('id','character_arc'),('project_id','project'),('character_id','character')):item[key]=ref(kind,item[key])
    for item in state.get('character_arc_stages',[]):
        for key,kind in (('id','character_arc_stage'),('project_id','project'),('arc_id','character_arc'),('planned_chapter_id','chapter'),('occurred_chapter_id','chapter')):item[key]=ref(kind,item[key])
    for item in state.get('key_events',[]):
        for key,kind in (('id','key_event'),('project_id','project'),('character_id','character'),('arc_id','character_arc'),('planned_chapter_id','chapter'),('occurred_chapter_id','chapter')):item[key]=ref(kind,item[key])
    for item in state.get('chapter_dependencies',[]):
        for key,kind in (('id','chapter_dependency'),('project_id','project'),('predecessor_chapter_id','chapter'),('successor_chapter_id','chapter')):item[key]=ref(kind,item[key])
    for item in state.get('full_book_planning_operations',[]):
        for key,kind in (('id','full_book_planning_operation'),('project_id','project'),('operation_id','full_book_planning_operation_token')):item[key]=ref(kind,item[key])
        target={'arc':'character_arc','stage':'character_arc_stage','event':'key_event','dependency':'chapter_dependency'}[item['target_kind']]
        item['target_id']=ref(target,item['target_id'])
    body_kinds={'arc':'character_arc','stage':'character_arc_stage','event':'key_event','dependency':'chapter_dependency'}
    for collection in ('body_planning_proposals','body_planning_receipts','body_planning_locks','planning_entity_lifecycle'):
        for item in state.get(collection,[]):
            item['id']=ref(collection,item['id']);item['project_id']=ref('project',item['project_id'])
            item['operation_id']=ref('body_planning_operation',item['operation_id'])
            if collection=='body_planning_proposals':
                knowledge_source(item['source'])
                item['planning_proposal_ids']=[ref('planning_proposal',identifier) for identifier in item['planning_proposal_ids']]
                for action in item['actions']:
                    values=action['values']
                    for key,kind in (('arc_id','character_arc'),('stage_id','character_arc_stage'),('event_id','key_event'),
                                     ('dependency_id','chapter_dependency'),('character_id','character'),('planned_chapter_id','chapter'),
                                     ('occurrence_chapter_id','chapter'),('predecessor_chapter_id','chapter'),('successor_chapter_id','chapter')):
                        if key in values:values[key]=ref(kind,values[key])
                    if action['action']=='prepare_plan':
                        values['target_id']=ref(values['target_kind'],values['target_id'])
                        values['source']['entity_id']=ref('chapter',values['source']['entity_id'])
            elif collection=='body_planning_receipts':item['proposal_id']=ref('body_planning_proposals',item['proposal_id'])
            elif collection=='body_planning_locks':item['target_id']=ref(body_kinds[item['target_kind']],item['target_id'])
            else:item['entity_id']=ref('character' if item['kind']=='character' else 'graph_node',item['entity_id'])
    # Model logical references are remapped; original wire/source text remains byte-for-byte provenance.
    def planning_action(action):
        values=action['values']
        for key,kind in (('arc_id','character_arc'),('stage_id','character_arc_stage'),('event_id','key_event'),
                         ('dependency_id','chapter_dependency'),('character_id','character'),('planned_chapter_id','chapter'),
                         ('occurrence_chapter_id','chapter'),('predecessor_chapter_id','chapter'),('successor_chapter_id','chapter')):
            if key in values:values[key]=ref(kind,values[key])
        if action['action']=='prepare_plan':
            values['target_id']=ref(values['target_kind'],values['target_id'])
            values['source']['entity_id']=ref('chapter',values['source']['entity_id'])
    for item in state.get('model_planning_tasks',[]):
        for key,kind in (('id','model_planning_task'),('project_id','project'),('request_id','model_planning_request'),
                         ('owner_id','model_planning_owner'),('chapter_id','chapter')):item[key]=ref(kind,item[key])
        options=item['source_options'];options['chapter_id']=ref('chapter',options['chapter_id'])
        options['character_ids']=[ref('character',v) for v in options['character_ids']]
        guard=item['source_guard'];knowledge_source(guard['source'])
        # Reuse the authoritative mapping for frozen chapter, selected people, rules and planning snapshots.
        shadow=dict(workspace_version=36, document=dict(project=deepcopy(guard['project']),
            chapters=[deepcopy(guard['chapter'])],characters=deepcopy(guard['characters']),
            book_outline=deepcopy(guard['book_outline']),chapter_outlines=[deepcopy(guard['chapter_outline'])] if guard['chapter_outline'] else [],versions=[]),
            ideas={},scoped_rules=deepcopy(guard['rules']), **deepcopy(guard['planning']), **deepcopy(guard['lifecycle']))
        shadow['planning_locks']=deepcopy(guard['locks']['planning_locks'])
        shadow['body_planning_locks']=deepcopy(guard['locks']['body_planning_locks'])
        # Book locks reference saved creation versions; mapping just their declared stable IDs is sufficient here.
        mapped=_transform(shadow,mapper,skill_mapper);doc=mapped['document']
        for key in ('project','characters','book_outline'):guard[key]=doc[key]
        guard['chapter']=doc['chapters'][0];guard['chapter_outline']=doc['chapter_outlines'][0] if doc['chapter_outlines'] else None
        guard['rules']=mapped['scoped_rules']
        for key in guard['planning']:guard['planning'][key]=mapped[key]
        for key in guard['lifecycle']:guard['lifecycle'][key]=mapped[key]
        guard['locks']['planning_locks']=mapped['planning_locks'];guard['locks']['body_planning_locks']=mapped['body_planning_locks']
        for lock in guard['locks']['book_creation_locks']:
            for key,kind in (('id','book_creation_lock'),('project_id','project'),('operation_id','book_creation_lock_operation'),('version_id','book_creation_version'),('previous_lock_id','book_creation_lock')):lock[key]=ref(kind,lock[key])
        item['source_sha256']=fingerprint(guard)
    for collection,kind in (('model_planning_events','model_planning_event'),('model_planning_results','model_planning_result'),
                            ('model_planning_candidates','model_planning_candidate'),('model_planning_links','model_planning_link')):
        for item in state.get(collection,[]):
            item['id']=ref(kind,item['id'])
            for key,target in (('project_id','project'),('task_id','model_planning_task'),('attempt_id','model_planning_attempt'),
                ('owner_id','model_planning_owner'),('previous_event_id','model_planning_event'),('response_id','model_planning_result'),
                ('candidate_id','model_planning_candidate'),('previous_candidate_id','model_planning_candidate'),('proposal_id','body_planning_proposals')):
                if key in item:item[key]=ref(target,item[key])
            if 'operation_id' in item:item['operation_id']=ref('model_planning_operation',item['operation_id'])
            if collection=='model_planning_candidates':
                for suggestion in item['plan']['suggestions']:
                    for action in suggestion['actions']:planning_action(action)
                item['data_sha256']=fingerprint(item['plan'])
    return state


def _normalize(value, model, path, identity, changes, *, snapshot=False):
    """只补dataclass声明的旧格式默认值；生成值确定且逐字段报告。"""
    origin, args = get_origin(model), get_args(model)
    if origin in (Union, UnionType):
        if value is None and type(None) in args: return None
        model = next(option for option in args if option is not type(None))
        origin, args = get_origin(model), get_args(model)
    if origin is list:
        if type(value) is not list: raise ValueError('legacy list')
        return [_normalize(item, args[0], f'{path}[{index}]', identity, changes, snapshot=snapshot)
                for index, item in enumerate(value)]
    if not is_dataclass(model): return deepcopy(value)
    if type(value) is not dict: raise ValueError('legacy object')
    model_fields = {f.name:f for f in fields(model)}
    if snapshot and model is MODEL_TYPES['chapter']:
        model_fields.pop('current_version_id')
    if set(value) - set(model_fields): raise ValueError('legacy unknown field')
    hints = get_type_hints(model)
    result = {}
    for name, field in model_fields.items():
        child = path+'.'+name
        if name in value:
            result[name] = _normalize(value[name], hints[name], child, identity, changes, snapshot=snapshot)
        else:
            if name == 'id': result[name] = _id(identity, 'legacy-default', child, child)
            elif name in ('created_at','updated_at'): result[name] = PLACEHOLDER_TIME
            elif field.default is not MISSING: result[name] = deepcopy(field.default)
            elif field.default_factory is not MISSING: result[name] = field.default_factory()
            else: raise ValueError('legacy missing required field')
            changes.append(child)
    return result


def _legacy(source, staged, identity):
    if source.stat().st_size > MAX_JSON_BYTES: raise ValueError('legacy size')
    with source.open('rb') as stream: value = strict_loads(stream.read(MAX_JSON_BYTES+1))
    if type(value) is not dict: raise ValueError('legacy root')
    changes, missing = [], ['project_snapshots','skills']
    original_revision = None
    if 'workspace_version' in value:
        if type(value['workspace_version']) is not int or value['workspace_version'] not in (1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50):
            raise ValueError('future workspace')
        names = {'workspace_version','revision','document','ideas','worldbuilding','writing_rules'}
        if value['workspace_version']>=2:
            # V2记忆出处依赖完整整书历史。单条workspace JSON不携带这些历史，
            # 不能重置revision伪造出处；请使用完整包迁移。
            raise BackupError('migration','history_required','V2/V3/V4出处及任务依赖需要完整整书历史，请使用完整备份包或SQLite库迁移')
        if set(value)-names or 'document' not in value: raise ValueError('legacy workspace fields')
        state = deepcopy(value)
        original_revision = state.get('revision')
        if original_revision is not None and (type(original_revision) is not int or original_revision < 0):
            raise ValueError('legacy revision')
        for name, default in (('ideas',{}),('worldbuilding',''),('writing_rules','')):
            if name not in state:
                state[name] = default; missing.append(name); changes.append('workspace.'+name)
        format_name = 'workspace_json_v1'
    else:
        state = {'document':value, 'ideas':{}, 'worldbuilding':'', 'writing_rules':''}
        missing += ['ideas','worldbuilding','writing_rules']
        format_name = 'novel_json_v1'
    doc = state['document']
    if type(doc) is not dict or type(doc.get('schema_version')) is not int or doc['schema_version'] != 1:
        raise ValueError('future document')
    # 同一输入的缺省值只规范化一次；不因重开页面生成不同ID/时间。
    with source.open('rb') as stream: raw_digest = hashlib.sha256(stream.read(MAX_JSON_BYTES+1)).hexdigest()
    default_identity = str(uuid5(NAMESPACE_URL,'legacy-json:'+raw_digest))
    state['document'] = _normalize(doc, NovelDocument, 'document', default_identity, changes)
    if 'versions' not in doc: missing.append('entity_versions')
    for index, version in enumerate(state['document']['versions']):
        kind = version['entity_type']
        if kind not in MODEL_TYPES: raise ValueError('legacy version kind')
        version['snapshot'] = _normalize(version['snapshot'], MODEL_TYPES[kind],
            f'document.versions[{index}].snapshot', default_identity, changes, snapshot=True)
    state.update(workspace_version=1, revision=1)
    project = state['document']['project']
    # 初始导入快照使用声明的占位时间；不伪称来源保存时间或丢失的revision历史。
    with closing(sqlite3.connect(staged)) as db, db:
        create_schema(db)
        _stage_insert(db,'projects',(project['id'],project['title'],1,_json(state),PLACEHOLDER_TIME))
        _stage_insert(db,'project_snapshots',(project['id'],1,_json(state),PLACEHOLDER_TIME))
    return {'source_format':format_name,'missing_scopes':missing,'normalizations':changes,
            'original_revision':original_revision,'source_identity':raw_digest,
            'legacy_notice':'仅保留输入实际数据；创建1条初始导入快照，不代表原整书历史。缺失时间使用1970年UTC占位，不代表原时间。'}


def _prepare(source, directory, identity, limits, check, drafts_path=None):
    source = Path(source).resolve(strict=True)
    with source.open('rb') as stream: header = stream.read(16)
    staged = directory/'source.sqlite3'
    meta = {'missing_scopes':[], 'normalizations':[], 'original_revision':None, 'legacy_notice':''}
    source_drafts=[]
    if header == b'SQLite format 3\0':
        _snapshot(source, staged, limits, check, None)
        meta['source_format'] = 'sqlite_v1'
        from novel_writer.application.drafts import DiskDrafts
        draft_listing=DiskDrafts(Path(drafts_path) if drafts_path is not None else source.parent/'drafts',create=False).list_all()
        source_drafts=draft_listing['drafts']
    elif header.startswith(b'PK'):
        manifest, staged, _, source_drafts = _unpack(source, directory, limits, check)
        meta['source_format'] = 'backup_v'+str(manifest['backup_format_version'])
        meta['backup_id'] = manifest['backup_id']
    else:
        meta.update(_legacy(source, staged, identity))
    report = validate_database(staged, check=check)
    if meta['source_format']=='sqlite_v1' and 'draft_listing' in locals():
        from novel_writer.application.drafts import validate_draft_record
        meta['drafts_sha256']=hashlib.sha256(_json([validate_draft_record(item) for item in source_drafts]).encode('utf-8')).hexdigest()
        meta['drafts_invalid_count']=len(draft_listing.get('corrupt',[]))+draft_listing.get('unreadable',0)
        meta['drafts_invalid_items']=[{'file_name':name,'reason':'invalid_record'} for name in draft_listing.get('corrupt',[])]+[{'file_name':name,'reason':'unreadable'} for name in draft_listing.get('unreadable_files',[])]
    elif source_drafts:
        meta['drafts_sha256']=hashlib.sha256(_json(source_drafts).encode('utf-8')).hexdigest()
    if meta['source_format'] in ('sqlite_v1','backup_v1','backup_v2','backup_v3','backup_v4'):
        with closing(sqlite3.connect(staged.as_uri()+'?mode=ro',uri=True)) as reader:
            for table in ('projects','project_snapshots'):
                for row in reader.execute('SELECT payload FROM '+table):
                    check();state=strict_loads(row[0])
                    if state['workspace_version']==1 and normalize_persistent_document(state['document'])!=state['document']:
                        meta['normalizations'].append('旧V1声明的可选字段在新项目转换中确定化补齐；原库及原历史不写回')
                        break
                if meta['normalizations']:break
    return staged, meta, report, source_drafts


def _select(report, project_ids):
    available = report['project_ids']
    if project_ids is None: selected = available
    else:
        if (type(project_ids) is not list or not project_ids or any(type(p) is not str for p in project_ids)
                or len(set(project_ids)) != len(project_ids) or not set(project_ids) <= set(available)):
            raise BackupError('migration','selection','项目选择无效；禁止静默跳过缺失项目')
        selected = sorted(project_ids)
    return selected


def _select_skills(report, mode, identifiers):
    if mode not in ('all','selected','none'): raise ValueError('skills mode')
    available = report['skill_ids']
    if mode=='selected':
        if (type(identifiers) is not list or any(type(p) is not str for p in identifiers)
                or len(set(identifiers))!=len(identifiers) or not set(identifiers)<=set(available)):
            raise ValueError('skills selection')
        return sorted(identifiers)
    if identifiers is not None: raise ValueError('unexpected skill ids')
    return available if mode=='all' else []


def _rows(db, table, project=None):
    if table=='content_blobs' and not db.execute("SELECT 1 FROM sqlite_master WHERE name='content_blobs' AND type='table'").fetchone():return ()
    columns = TABLE_COLUMNS[table]
    where, params = '', ()
    if project is not None:
        where = ' WHERE '+('id' if table=='projects' else 'project_id')+'=?'; params = (project,)
    return db.execute('SELECT '+','.join(columns)+' FROM '+table+where+' ORDER BY 1,2', params)


def _feed(digest, row):
    digest.update(_json(list(row)).encode('utf8')); digest.update(b'\n')


def _project_hash(db, project, check):
    digest = hashlib.sha256()
    if db.execute('SELECT 1 FROM projects WHERE id=?',(project,)).fetchone() is None: return None
    for table in ('projects','project_snapshots'):
        digest.update(table.encode())
        for row in _rows(db, table, project): check(); _feed(digest,row)
    current=strict_loads(db.execute('SELECT payload FROM projects WHERE id=?',(project,)).fetchone()[0])
    from novel_writer.domain.styles import blob_refs as style_blob_refs
    from novel_writer.domain.public_search import blob_refs as web_blob_refs
    from novel_writer.domain.style_trials import blob_refs as trial_blob_refs
    blob_refs=lambda state:style_blob_refs(state)|web_blob_refs(state)|trial_blob_refs(state)
    for sha in sorted(blob_refs(current)):
        row=db.execute('SELECT sha256,data_base64 FROM content_blobs WHERE sha256=?',(sha,)).fetchone();check();_feed(digest,row)
    return digest.hexdigest()


def _source_hash(db, selected, selected_skills, meta, check):
    # 排除范围只用于报告；目标库后来新增的其它书不能改变已选源小说的操作身份。
    identity_meta = {key:value for key,value in meta.items() if key not in ('excluded_project_ids','excluded_skill_ids','drafts_sha256','drafts_invalid_count','drafts_invalid_items')}
    digest = hashlib.sha256(_json(identity_meta).encode('utf8'))
    for p in selected:
        digest.update(p.encode('utf8')); digest.update(_project_hash(db,p,check).encode())
    for row in _rows(db,'skills'):
        check()
        if row[0] in selected_skills: _feed(digest,row)
    return digest.hexdigest()


def _receipt_path(target, identity, *, create=False):
    namespace = hashlib.sha256(str(target).encode('utf8')).hexdigest()[:24]
    root = target.parent/('.novel-migration-operations-'+namespace)
    if create: root.mkdir(exist_ok=True)
    if not root.exists(): raise KeyError('migration')
    _plain(root)
    if not root.is_dir(): raise ValueError('receipt root')
    return root/(valid_operation_id(identity)+'.json')


def _load(target, identity):
    path = _receipt_path(target, identity)
    if not path.exists(): raise KeyError('migration')
    _plain(path)
    if not path.is_file() or path.stat().st_size > RECEIPT_LIMIT: raise ValueError('receipt size')
    with path.open('rb') as stream: receipt = strict_loads(stream.read(RECEIPT_LIMIT+1))
    try: return _check_receipt(receipt,identity)
    except (KeyError,TypeError,IndexError): raise ValueError('corrupt receipt plan') from None


def _check_receipt(receipt,identity):
    if (type(receipt) is not dict or set(receipt) != {'version','operation_id','source_sha256','selection','result','expected_projects','expected_skills'}
            or type(receipt['version']) is not int or receipt['version']!=1 or receipt['operation_id']!=identity):
        raise ValueError('receipt fields')
    result = receipt['result']
    if (type(result) is not dict or result.get('operation_id')!=identity
            or type(receipt['selection']) is not list or type(result.get('projects')) is not list
            or type(result.get('skills')) is not list or type(receipt['expected_projects']) is not list
            or type(receipt['expected_skills']) is not list
            or [p['id'] for p in receipt['expected_projects']] != [p['new_id'] for p in result['projects']]
            or sorted(s['id'] for s in receipt['expected_skills']) != sorted(s['new_id'] for s in result['skills'])
            or [p['old_id'] for p in result['projects']] != receipt['selection']):
        raise ValueError('receipt plan')
    for value in [receipt['source_sha256']]+[p['sha256'] for p in receipt['expected_projects']+receipt['expected_skills']]:
        if type(value) is not str or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('receipt digest')
    return receipt


def _save(target, receipt):
    path = _receipt_path(target, receipt['operation_id'], create=True)
    data = _json(receipt).encode('utf8')
    if len(data)>RECEIPT_LIMIT: raise BackupError('migration','report_size','迁移映射报告超过8MiB，未写入目标')
    if sum(1 for _ in path.parent.iterdir()) >= 1024: raise ValueError('receipt quota')
    with OwnedTemporaryDirectory(kind='receipt',prefix='.receipt-',dir=path.parent) as temp:
        staged = Path(temp)/'receipt.json'
        with staged.open('xb') as stream:
            _write_all(stream,data); stream.flush(); os.fsync(stream.fileno())
        _publish(staged,path)


def _skill_hash(row):
    return hashlib.sha256(_json(list(row)).encode('utf8')).hexdigest()


def _status(db, receipt, check):
    absent = 0
    for expected in receipt['expected_projects']:
        actual = _project_hash(db, expected['id'], check)
        if actual is None: absent += 1
        elif actual != expected['sha256']:
            raise BackupError('migration','changed_target','迁移目标已编辑或编号冲突，拒绝复用或覆盖')
    if absent not in (0,len(receipt['expected_projects'])):
        raise BackupError('migration','partial_target','目标出现不完整导入，拒绝自动补写')
    new_skills, missing_skills = 0, 0
    for expected in receipt['expected_skills']:
        row = next(iter(db.execute('SELECT '+','.join(TABLE_COLUMNS['skills'])+' FROM skills WHERE id=?',(expected['id'],))),None)
        if not receipt['expected_projects']:
            if expected['action']!='reused':
                new_skills += 1
                if row is None: missing_skills += 1; continue
            if row is None or _skill_hash(row)!=expected['sha256']:
                raise BackupError('migration','changed_skills','全局Skills缺失或变化，拒绝复用')
            continue
        if absent:
            if expected['action']=='reused':
                if row is None or _skill_hash(row)!=expected['sha256']: raise ValueError('reused skill changed')
            elif row is not None: raise ValueError('partial skill')
        elif row is None or _skill_hash(row)!=expected['sha256']:
            raise BackupError('migration','changed_skills','已导入的全局Skills发生变化，拒绝声称幂等成功')
    if not receipt['expected_projects']:
        if missing_skills and missing_skills!=new_skills:
            raise BackupError('migration','partial_target','目标出现不完整Skills导入，拒绝自动补写')
        return 'not_applied' if missing_skills else 'already_present'
    return 'not_applied' if absent else 'already_present'


def _lock_target(db, check):
    db.execute('BEGIN IMMEDIATE')
    validate_connection(db, check=check)


def _before_commit(db, check):
    validate_connection(db, check=check)
    check()


def _insert_row(db, table, row):
    _stage_insert(db,table,row)


def _target(path):
    path = Path(path).resolve(strict=True)
    _plain(path)
    if not path.is_file(): raise ValueError('target missing')
    return path


def migration_status(target, identity, *, limits=Limits(), cancel=None):
    """库外收据仅说明意图；完成状态必须核对真实SQL及全部复制历史。"""
    with _errors('migration', allow_missing=True):
        check = _guard(limits,cancel)
        target = _target(target)
        receipt = _load(target,valid_operation_id(identity))
        with closing(sqlite3.connect(target.as_uri()+'?mode=ro',uri=True,timeout=.2)) as db:
            db.execute('PRAGMA query_only=ON'); db.execute('PRAGMA trusted_schema=OFF'); db.execute('BEGIN')
            validate_connection(db,check=check)
            state = _status(db,receipt,check)
        return dict(receipt['result'],state=state,verified=state=='already_present')


def migrate(source, target, *, operation_id, project_ids=None, skills_mode='all', skill_ids=None,
            preview=False, limits=Limits(), cancel=None, drafts_path=None, target_drafts_path=None):
    """来源可为V1包/兼容SQLite/小说或工作区JSON；全部全局Skills明确纳入。"""
    with _errors('migration'):
        identity = valid_operation_id(operation_id)
        if type(preview) is not bool: raise ValueError('preview flag')
        check = _guard(limits,cancel)
        target = _target(target)
        cleanup = BackupResult()
        # 提交后的暂存故障只能成为警告，不能将已提交数据报告成回滚。
        with _publication_directory(Path(tempfile.gettempdir()),cleanup,kind='preflight') as directory:
            source_path, meta, report, source_drafts = _prepare(source,directory,identity,limits,check,drafts_path)
            selected = _select(report,project_ids)
            selected_skills = _select_skills(report,skills_mode,skill_ids)
            meta.update(skills_scope=skills_mode,
                excluded_project_ids=[p for p in report['project_ids'] if p not in selected],
                excluded_skill_ids=[s for s in report['skill_ids'] if s not in selected_skills])
            with closing(sqlite3.connect(source_path.as_uri()+'?mode=ro',uri=True)) as reader, \
                 closing(sqlite3.connect(target.as_uri()+'?mode=rw',uri=True,timeout=.2)) as writer:
                reader.execute('PRAGMA query_only=ON'); reader.execute('BEGIN')
                writer.execute('PRAGMA foreign_keys=ON'); writer.execute('PRAGMA trusted_schema=OFF')
                writer.execute('PRAGMA synchronous=FULL')
                fingerprint = _source_hash(reader,selected,selected_skills,meta,check)
                if Path(source).resolve()==target:
                    mapping_identity = identity  # 显式复制操作，可以多次各建独立副本。
                else:
                    mapping_identity = meta.get('backup_id') or str(uuid5(NAMESPACE_URL,'migration-source:'+fingerprint))
                _lock_target(writer,check)
                with writer:
                    try: receipt = _load(target,identity)
                    except KeyError: receipt = None
                    if receipt is not None:
                        if receipt['source_sha256']!=fingerprint or receipt['selection']!=selected:
                            raise BackupError('migration','identity_conflict','同一操作编号对应不同来源或范围，拒绝重试')
                        state = _status(writer,receipt,check)
                        already_present=state=='already_present'
                    else:
                        already_present=False
                    skills = []
                    skill_map = {}
                    historical_skill_map = {}
                    known_skills = {s['old_id']:s for s in receipt['result']['skills']} if receipt else {}
                    for values in _rows(reader,'skills'):
                        check(); old = values[0]
                        if old not in selected_skills: continue
                        existing = writer.execute('SELECT '+','.join(TABLE_COLUMNS['skills'])+' FROM skills WHERE id=?',(old,)).fetchone()
                        if receipt: decision = known_skills[old]
                        elif existing == values: decision = {'old_id':old,'new_id':old,'action':'reused'}
                        elif existing is None: decision = {'old_id':old,'new_id':old,'action':'inserted'}
                        else:
                            new_id = _id(mapping_identity,'global','skill',old)
                            mapped_existing = writer.execute('SELECT '+','.join(TABLE_COLUMNS['skills'])+' FROM skills WHERE id=?',(new_id,)).fetchone()
                            if mapped_existing is not None and mapped_existing!=(new_id,*values[1:]):
                                raise BackupError('migration','skill_conflict','稳定映射Skills编号冲突，拒绝覆盖')
                            decision = {'old_id':old,'new_id':new_id,'action':'reused' if mapped_existing else 'remapped'}
                        skills.append(decision); skill_map[old] = decision['new_id']
                    def map_skill(identifier):
                        if identifier in skill_map: return skill_map[identifier]
                        historical_skill_map.setdefault(identifier,_id(mapping_identity,'historical-global','skill',identifier))
                        return historical_skill_map[identifier]
                    mapping = {}
                    def collect(project,kind,old):
                        check()
                        mapping.setdefault((project,kind,old),_id(mapping_identity,project,kind,old))
                        return old
                    # 两遍流式遍历：先冻结全部历史联合集合，再按唯一映射转换每一行。
                    for project in selected:
                        for table in ('project_snapshots','projects'):
                            for row in _rows(reader,table,project):
                                _transform(strict_loads(row[TABLE_COLUMNS[table].index('payload')]),collect,map_skill)
                    def mapped(project,kind,old): return mapping[(project,kind,old)]
                    from novel_writer.application.drafts import filter_sensitive_fields,validate_draft_record
                    drafts_migrated=[];drafts_dropped=[]
                    for record in source_drafts:
                        check();record=filter_sensitive_fields(validate_draft_record(record));old_project=record['project_id']
                        reason=None
                        if old_project not in report['project_ids']:reason='missing_mapping'
                        elif old_project not in selected:
                            drafts_dropped.append({'document_key':record['document_key'],'reason':'unselected_project'})
                            continue
                        else:
                            parsed=json.loads(record['document_key']);_,view,entity,pane=parsed
                            kind={'writing':'chapter','characters':'character','memory':'memory'}.get(view)
                            mapped_entity=entity
                            if entity and kind:
                                try:mapped_entity=mapped(old_project,kind,entity)
                                except KeyError:reason='missing_mapping'
                            mapped_values=dict(record['values'])
                            for key,value in list(mapped_values.items()):
                                normalized=key.lower()
                                inferred=next((candidate for candidate in ('chapter','character','memory') if normalized.endswith(candidate+'_id') or normalized.endswith(candidate+'_ids')),None)
                                if inferred is None:continue
                                if normalized.endswith('_ids'):
                                    remapped=[]
                                    for identifier in value:
                                        try:remapped.append(mapped(old_project,inferred,identifier))
                                        except KeyError:reason='missing_mapping';break
                                    mapped_values[key]=remapped
                                elif value:
                                    try:mapped_values[key]=mapped(old_project,inferred,value)
                                    except KeyError:reason='missing_mapping'
                            if reason is None:
                                record['project_id']=mapped(old_project,'project',old_project)
                                record['document_key']=_json([record['project_id'],view,mapped_entity,pane])
                                record['values']=mapped_values
                        if reason is not None:
                            drafts_dropped.append({'document_key':record['document_key'],'reason':reason})
                        else:drafts_migrated.append(record)
                    drafts_dropped.extend(meta.get('drafts_invalid_items',[]))
                    histories={project:{} for project in selected};mapped_states={}
                    for project in selected:
                        for table in ('project_snapshots','projects'):
                            for row in _rows(reader,table,project):
                                check();values=dict(zip(TABLE_COLUMNS[table],row))
                                state=_transform(strict_loads(values['payload']),mapped,map_skill)
                                mapped_states[(table,project,values['revision'])]=state
                                histories[project][state['revision']]=state
                    _repair_task_source_hashes(histories,mapped_states.values())
                    for state in mapped_states.values():
                        for e in state.get('comparison_experiments',[]):
                            if e.get('trial_kind')=='writing_candidates':
                                from novel_writer.domain.writing_comparisons import common_input,task_record
                                e['common_input_sha256']=common_input(task_record(state,e['task_kind'],e['configurations'][0]['task_id']),e['task_kind'])
                    copied = directory/'mapped.sqlite3'
                    with closing(sqlite3.connect(copied)) as staged, staged:
                        create_schema(staged,reader.execute('PRAGMA user_version').fetchone()[0])
                        for project in selected:
                            for table,key in (('projects','id'),('project_snapshots','project_id')):
                                columns = TABLE_COLUMNS[table]
                                for values in _rows(reader,table,project):
                                    check(); row = dict(zip(columns,values))
                                    row[key] = mapped(project,'project',project)
                                    row['payload'] = _json(mapped_states[(table,project,row['revision'])])
                                    _stage_insert(staged,table,[row[c] for c in columns])
                        for values in _rows(reader,'skills'):
                            check()
                            if values[0] in skill_map:
                                _stage_insert(staged,'skills',(skill_map[values[0]],*values[1:]))
                        from novel_writer.domain.styles import blob_refs as style_blob_refs
                        from novel_writer.domain.public_search import blob_refs as web_blob_refs
                        from novel_writer.domain.style_trials import blob_refs as trial_blob_refs
                        blob_refs=lambda state:style_blob_refs(state)|web_blob_refs(state)|trial_blob_refs(state)
                        required=set()
                        for project in selected:
                            required.update(blob_refs(strict_loads(reader.execute('SELECT payload FROM projects WHERE id=?',(project,)).fetchone()[0])))
                        for blob in _rows(reader,'content_blobs'):
                            if blob[0] in required:_stage_insert(staged,'content_blobs',blob)
                    mapped_report = validate_database(copied,check=check)
                    result = dict(meta,operation_id=identity,state='completed',verified=True,
                        credentials_restored=False,
                        shared_skills_notice='Skills为当前库全局资料；同ID全字段相同才复用，不按名称或内容去重。',
                        projects=[{'old_id':p,'new_id':mapped(p,'project',p)} for p in selected],
                        id_map=[{'old_project_id':p,'new_project_id':mapped(p,'project',p),
                            'kind':k,'old_id':old,'new_id':new} for (p,k,old),new in sorted(mapping.items())],
                        skills=skills,counts=mapped_report['counts'],historical_skill_id_map=[{'old_id':old,'new_id':new} for old,new in sorted(historical_skill_map.items())],
                        drafts_migrated=[{'document_key':item['document_key'],'sensitive_fields_required':item.get('sensitive_fields_required',False)} for item in drafts_migrated],
                        drafts_dropped=drafts_dropped,
                        sensitive_fields_required=any(item.get('sensitive_fields_required') for item in drafts_migrated),
                        no_data_change=not selected and all(s['action']=='reused' for s in skills))
                    with closing(sqlite3.connect(copied.as_uri()+'?mode=ro',uri=True)) as staged:
                        expected_projects = [{'id':mapped(p,'project',p),'sha256':_project_hash(staged,mapped(p,'project',p),check)} for p in selected]
                        expected_skills = [{'id':row[0],'sha256':_skill_hash(row),'action':next(s['action'] for s in skills if s['new_id']==row[0])}
                                           for row in _rows(staged,'skills')]
                        if receipt is None:
                            existing_projects = [_project_hash(writer,p['id'],check) for p in expected_projects]
                            present = sum(value is not None for value in existing_projects)
                            if present and (present!=len(expected_projects) or any(value!=p['sha256'] for value,p in zip(existing_projects,expected_projects))):
                                raise BackupError('migration','id_conflict','映射项目部分存在或已编辑，拒绝覆盖或补写')
                            for s in expected_skills:
                                if s['action']!='reused' and writer.execute('SELECT 1 FROM skills WHERE id=?',(s['id'],)).fetchone():
                                    raise BackupError('migration','skill_conflict','映射Skills编号已存在，拒绝覆盖')
                            receipt = {'version':1,'operation_id':identity,'source_sha256':fingerprint,
                                'selection':selected,'result':result,'expected_projects':expected_projects,'expected_skills':expected_skills}
                            _save(target,receipt)
                            if present or (not expected_projects and all(s['action']=='reused' for s in skills)):
                                if _status(writer,receipt,check)!='already_present': raise ValueError('retry verification')
                                already_present=True
                        elif receipt['expected_projects']!=expected_projects or receipt['expected_skills']!=expected_skills:
                            raise ValueError('receipt mismatch')
                        if preview: return dict(result,state='ready',verified=False)
                        for table in TABLE_COLUMNS:
                            reused = {s['new_id'] for s in skills if s['action']=='reused'}
                            for row in (() if already_present else _rows(staged,table)):
                                check()
                                if table=='skills' and row[0] in reused: continue
                                if table=='content_blobs':
                                    from novel_writer.storage.content_blobs import ensure
                                    ensure(writer)
                                    existing=writer.execute('SELECT sha256,data_base64 FROM content_blobs WHERE sha256=?',(row[0],)).fetchone()
                                    if existing:
                                        if tuple(existing)!=tuple(row):raise ValueError('content hash mismatch')
                                        continue
                                _insert_row(writer,table,row)
                    _before_commit(writer,check)
                    if _status(writer,receipt,check)!='already_present': raise ValueError('write verification')
                if not preview and drafts_migrated:
                    from novel_writer.application.drafts import DiskDrafts
                    draft_store=DiskDrafts(Path(target_drafts_path) if target_drafts_path is not None else target.parent/'drafts')
                    for record in drafts_migrated:draft_store.import_record(record,only_if_missing=True)
                if already_present:
                    completed=dict(result,state='already_present',verified=True,no_data_change=True)
                else:
                    completed=None
                # 状态来自事务提交后新只读连接，不能只凭HTTP成功或收据判断。
                cleanup._published = True
                if completed is None:
                    verified = migration_status(target,identity,limits=limits)
                    completed = dict(verified,state='completed')
        if cleanup.cleanup_warnings: completed['cleanup_warnings'] = cleanup.cleanup_warnings
        return completed
