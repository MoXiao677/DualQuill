"""V27 chapter ordering, cross-volume moves, archive, and recoverable trash."""
from copy import deepcopy
import hashlib
import json
from uuid import NAMESPACE_URL, uuid4, uuid5

from novel_writer.application.fields import check_fields
from novel_writer.domain.chapter_lifecycle import (
    LifecycleEvent, archived_ids, is_archived, require_active,
)
from novel_writer.domain.chapter_trash import (
    TrashEvent, event_for_operation, hidden_ids, is_hidden, is_trashed,
    latest_event as latest_trash_event, trashed_ids,
)
from novel_writer.domain.models import utc_now
from novel_writer.domain.tasks import encode, require, uuid_value
from novel_writer.storage.sqlite_repository import ConflictError


def upgrade_base(state):
    from novel_writer.application.scene_expansion import upgrade as previous
    previous(state)
    state['workspace_version'] = max(state['workspace_version'], 19)
    state.setdefault('chapter_lifecycle_events', [])
    return state


def upgrade(state):
    from novel_writer.application.full_book_planning import upgrade as previous
    previous(state)
    state['workspace_version'] = max(state['workspace_version'], 27)
    state.setdefault('chapter_lifecycle_events', [])
    state.setdefault('chapter_trash_events', [])
    return state


def active_chapters(state):
    hidden = hidden_ids(state)
    return [value for value in sorted(state['document']['chapters'], key=lambda item: item['number'])
            if value['id'] not in hidden]


def _chapter(document, identifier):
    value = next((item for item in document['chapters'] if item['id'] == identifier), None)
    require(value is not None, '章节不存在或不属于当前书')
    return value


def _volume(document, number):
    outline = document.get('book_outline')
    require(outline is not None, '本书还没有分卷')
    value = next((item for item in outline['volumes'] if item['number'] == number), None)
    require(value is not None, '目标分卷不存在')
    return value


def _book_outline(document):
    outline = document.get('book_outline')
    require(outline is not None, '本书还没有分卷')
    return outline


def _volume_location(document, chapter_id):
    outline = document.get('book_outline')
    if outline is None:
        return None, None
    for volume in outline['volumes']:
        if chapter_id in volume['chapter_ids']:
            return volume['number'], volume['chapter_ids'].index(chapter_id)
    return None, None


def _event(state, chapter_id, kind, operation):
    kind = 'archive' if kind == 'archive_chapter' else 'restore'
    state['chapter_lifecycle_events'].append(encode(LifecycleEvent(
        id=str(uuid4()), project_id=state['document']['project']['id'],
        operation_id=str(uuid4()), chapter_id=chapter_id, kind=kind, created_at=utc_now())))


def _renumber(document):
    chapters = {value['id']: value for value in document['chapters']}
    order = []
    outline = document.get('book_outline')
    if outline is not None:
        for volume in sorted(outline['volumes'], key=lambda item: item['number']):
            for chapter_id in volume['chapter_ids']:
                if chapter_id in chapters and chapter_id not in order:
                    order.append(chapter_id)
    order.extend(value['id'] for value in sorted(document['chapters'], key=lambda item: item['number'])
                 if value['id'] not in order)
    for number, chapter_id in enumerate(order, 1):
        chapters[chapter_id]['number'] = number
    if outline is not None:
        positions = {chapter_id: number for number, chapter_id in enumerate(order, 1)}
        for volume in outline['volumes']:
            volume['chapter_ids'] = sorted(volume['chapter_ids'], key=lambda item: positions[item])


def move(state, values):
    check_fields(values, {'chapter_id', 'direction', 'confirmed'})
    require(set(values) == {'chapter_id', 'direction', 'confirmed'}
            and values['direction'] in ('up', 'down') and values['confirmed'] is True,
            '章节重排需要明确方向与确认')
    document = state['document']
    chapter = _chapter(document, values['chapter_id'])
    visible = active_chapters(state)
    require(chapter['id'] in {value['id'] for value in visible}, '归档或回收站章节不参与排序')
    index = next(position for position, value in enumerate(visible) if value['id'] == chapter['id'])
    target = index - 1 if values['direction'] == 'up' else index + 1
    require(0 <= target < len(visible), '已到可见章节顺序边界')
    neighbor = visible[target]
    chapter['number'], neighbor['number'] = neighbor['number'], chapter['number']
    positions = {value['id']: value['number'] for value in document['chapters']}
    if document['book_outline'] is not None:
        for volume in document['book_outline']['volumes']:
            volume['chapter_ids'] = sorted(volume['chapter_ids'],
                                           key=lambda identifier: positions.get(identifier, 10**9))
    return state


def move_to_volume(state, values):
    check_fields(values, {'chapter_id', 'target_volume_number', 'target_index', 'confirmed'})
    require(set(values) == {'chapter_id', 'target_volume_number', 'target_index', 'confirmed'}
            and values['confirmed'] is True, '跨卷移动需要目标分卷、位置与明确确认')
    require(type(values['target_volume_number']) is int and values['target_volume_number'] >= 1,
            '目标分卷编号无效')
    require(type(values['target_index']) is int and values['target_index'] >= 0,
            '目标位置必须是从 0 开始的整数')
    document = state['document']
    chapter = _chapter(document, values['chapter_id'])
    require(not is_hidden(state, chapter['id']), '归档或回收站章节不能跨卷移动')
    outline = _book_outline(document)
    target = _volume(document, values['target_volume_number'])
    current_volume, current_index = _volume_location(document, chapter['id'])
    remaining = [identifier for identifier in target['chapter_ids'] if identifier != chapter['id']]
    require(values['target_index'] <= len(remaining), '目标位置超过分卷末尾')
    if current_volume == target['number'] and current_index == values['target_index']:
        require(False, '章节已位于目标分卷和位置')
    for volume in outline['volumes']:
        volume['chapter_ids'] = [identifier for identifier in volume['chapter_ids']
                                 if identifier != chapter['id']]
    remaining.insert(values['target_index'], chapter['id'])
    target['chapter_ids'] = remaining
    _renumber(document)
    return state


def archive(state, values):
    check_fields(values, {'chapter_id', 'confirmed'})
    require(set(values) == {'chapter_id', 'confirmed'} and values['confirmed'] is True,
            '归档章节需要明确确认')
    chapter_id = values['chapter_id']
    _chapter(state['document'], chapter_id)
    require(not is_trashed(state, chapter_id), '回收站章节不能归档，请先恢复')
    require(not is_archived(state, chapter_id), '章节已经归档')
    _event(state, chapter_id, 'archive_chapter', None)
    return state


def restore(state, values):
    check_fields(values, {'chapter_id', 'confirmed'})
    require(set(values) == {'chapter_id', 'confirmed'} and values['confirmed'] is True,
            '恢复章节需要明确确认')
    chapter_id = values['chapter_id']
    _chapter(state['document'], chapter_id)
    require(not is_trashed(state, chapter_id), '回收站章节请先从回收站恢复')
    require(is_archived(state, chapter_id), '章节未归档')
    _event(state, chapter_id, 'unarchive_chapter', None)
    return state


def _hash(values, action):
    semantic = {'action': action, 'chapter_id': values['chapter_id']}
    if action == 'trash_chapter':
        semantic.update(confirm_title=values.get('confirm_title'),
                        acknowledge_references=values.get('acknowledge_references'))
    raw = json.dumps(semantic, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf8')
    return hashlib.sha256(raw).hexdigest()


def _records(items):
    return [dict(id=value['id']) for value in items]


def _references(state, chapter_id):
    document = state['document']
    references = []

    def add(kind, entity_id, field, **extra):
        references.append(dict(kind=kind, entity_id=entity_id, field=field,
                               requires_acknowledgement=True, **extra))

    outline = document.get('book_outline')
    if outline is not None:
        for volume in outline['volumes']:
            if chapter_id in volume['chapter_ids']:
                add('book_outline', outline['id'], f"volumes.{volume['number']}.chapter_ids",
                    volume_number=volume['number'], position=volume['chapter_ids'].index(chapter_id))
    for task in state.get('generation_tasks', []):
        if task.get('chapter_id') == chapter_id:
            add('generation_task', task['id'], 'chapter_id', status=task.get('status'))
    for name, kind in (('chapter_planning_tasks', 'chapter_planning_task'),
                       ('scene_expansion_tasks', 'scene_expansion_task'),
                       ('style_trial_tasks', 'style_trial_task')):
        for value in state.get(name, []):
            if value.get('chapter_id') == chapter_id:
                add(kind, value['id'], 'chapter_id')
    for value in state.get('memories', []):
        if value.get('position_chapter_id') == chapter_id:
            add('memory', value['id'], 'position_chapter_id')
        if value.get('source', {}).get('chapter_id') == chapter_id:
            add('memory', value['id'], 'source.chapter_id')
    for value in state.get('character_arc_stages', []):
        if value.get('planned_chapter_id') == chapter_id:
            add('character_arc_stage', value['id'], 'planned_chapter_id')
        if value.get('occurred_chapter_id') == chapter_id:
            add('character_arc_stage', value['id'], 'occurred_chapter_id')
    for value in state.get('key_events', []):
        if value.get('planned_chapter_id') == chapter_id:
            add('key_event', value['id'], 'planned_chapter_id')
        if value.get('occurred_chapter_id') == chapter_id:
            add('key_event', value['id'], 'occurred_chapter_id')
    for value in state.get('chapter_dependencies', []):
        if value.get('predecessor_chapter_id') == chapter_id:
            add('chapter_dependency', value['id'], 'predecessor_chapter_id')
        if value.get('successor_chapter_id') == chapter_id:
            add('chapter_dependency', value['id'], 'successor_chapter_id')
    for plan in state.get('console_plans', []):
        for step in plan.get('steps', []):
            if step.get('chapter_id') == chapter_id:
                add('console_plan_step', step['id'], 'chapter_id', plan_id=plan['id'])
    for step in state.get('console_run_steps', []):
        if step.get('chapter_id') == chapter_id:
            add('console_run_step', step['id'], 'chapter_id', run_id=step.get('run_id'))
    return references


def preview_trash(state, chapter_id):
    document = state['document']
    chapter = _chapter(document, chapter_id)
    volume_number, position = _volume_location(document, chapter_id)
    references = _references(state, chapter_id)
    preserved = {
        'chapter_versions': _records([value for value in document['versions']
                                      if value['entity_type'] == 'chapter'
                                      and value['entity_id'] == chapter_id]),
        'chapter_outlines': _records([value for value in document['chapter_outlines']
                                      if value['chapter_id'] == chapter_id]),
        'ideas': {'present': chapter_id in state.get('ideas', {}),
                  'chars': len(state.get('ideas', {}).get(chapter_id, ''))},
        'memories': _records([value for value in state.get('memories', [])
                              if value['position_chapter_id'] == chapter_id
                              or value.get('source', {}).get('chapter_id') == chapter_id]),
        'generation_tasks': _records([value for value in state.get('generation_tasks', [])
                                      if value.get('chapter_id') == chapter_id]),
        'task_events': _records([value for value in state.get('task_events', [])
                                 if value.get('task_id') in {
                                     task['id'] for task in state.get('generation_tasks', [])
                                     if task.get('chapter_id') == chapter_id}]),
        'chapter_planning_tasks': _records([value for value in state.get('chapter_planning_tasks', [])
                                            if value.get('chapter_id') == chapter_id]),
        'scene_expansion_tasks': _records([value for value in state.get('scene_expansion_tasks', [])
                                           if value.get('chapter_id') == chapter_id]),
        'character_arc_stages': _records([value for value in state.get('character_arc_stages', [])
                                          if chapter_id in (value.get('planned_chapter_id'),
                                                            value.get('occurred_chapter_id'))]),
        'key_events': _records([value for value in state.get('key_events', [])
                                if chapter_id in (value.get('planned_chapter_id'),
                                                  value.get('occurred_chapter_id'))]),
        'chapter_dependencies': _records([value for value in state.get('chapter_dependencies', [])
                                          if chapter_id in (value.get('predecessor_chapter_id'),
                                                            value.get('successor_chapter_id'))]),
        'console_plan_steps': _records([step for plan in state.get('console_plans', [])
                                        for step in plan.get('steps', [])
                                        if step.get('chapter_id') == chapter_id]),
        'console_run_steps': _records([value for value in state.get('console_run_steps', [])
                                       if value.get('chapter_id') == chapter_id]),
    }
    archived, trashed = is_archived(state, chapter_id), is_trashed(state, chapter_id)
    trash_event = latest_trash_event(state, chapter_id) if trashed else None
    restore_volume = (trash_event['original_volume_number'] if trash_event is not None
                      else volume_number)
    restore_position = (trash_event['original_position'] if trash_event is not None
                        else position)
    restore_volume_exists = (restore_volume is None or document.get('book_outline') is not None
                             and any(value['number'] == restore_volume
                                     for value in document['book_outline']['volumes']))
    blockers = []
    if archived:
        blockers.append('章节已归档；请先取消归档，再评估回收站操作。')
    if trashed:
        if not restore_volume_exists:
            blockers.append('回收前所在分卷已不存在；当前拒绝静默改投其它分卷。')
        else:
            blockers.append('章节已在回收站；可从回收站恢复。')
    return {
        'project_id': document['project']['id'],
        'chapter_id': chapter_id,
        'title': chapter['title'],
        'number': chapter['number'],
        'status': chapter['status'],
        'volume_number': volume_number,
        'position': position,
        'already_archived': archived,
        'already_trashed': trashed,
        'can_trash': not blockers,
        'blockers': blockers,
        'restorable': trashed and not archived and restore_volume_exists,
        'restore_target': {'volume_number': restore_volume, 'position': restore_position,
                           'version': 'stored snapshot at trash time' if trashed else 'current location'},
        'references': references,
        'reference_count': len(references),
        'preserved': preserved,
        'impact_preview': {'reference_count': len(references),
                           'content_deleted': False,
                           'history_deleted': False,
                           'existing_references_rewritten': False,
                           'remove_from_volume_membership': True,
                           'restore_policy': '恢复时按回收前分卷与位置插回；若分卷已不存在则明确拒绝，不静默改投其它分卷。'},
        'warnings': ['移入回收站不会删除正文、版本、细纲、IDEA、记忆或任务历史；现有 C07/任务/控制台引用保持原样并报告为已回收。'] if not trashed else [],
    }


def _require_operation(values):
    identity = uuid_value(values.get('operation_id'))
    return identity


def _check_replay(state, action, values, request_sha256):
    existing = event_for_operation(state, values['operation_id'])
    if existing is None:
        return False
    expected_kind = 'trash' if action == 'trash_chapter' else 'restore'
    require(existing['kind'] == expected_kind and existing['chapter_id'] == values['chapter_id']
            and existing['request_sha256'] == request_sha256,
            'chapter_trash.operation_conflict')
    return True


def _check_revision(state, expected_revision):
    require(type(expected_revision) is int and expected_revision >= 1,
            '章节回收站操作需要有效的 expected_revision')
    if state.get('revision') != expected_revision:
        raise ConflictError('小说已更新，请保留当前内容并重新打开最新状态')


def trash(state, values, expected_revision=None):
    check_fields(values, {'chapter_id', 'operation_id', 'confirm_title',
                          'acknowledge_references', 'confirmed'})
    require(set(values) == {'chapter_id', 'operation_id', 'confirm_title',
                            'acknowledge_references', 'confirmed'}
            and values['confirmed'] is True, '移入回收站需要明确确认')
    _require_operation(values)
    request_sha256 = _hash(values, 'trash_chapter')
    if _check_replay(state, 'trash_chapter', values, request_sha256):
        return state
    _check_revision(state, expected_revision)
    document = state['document']
    chapter = _chapter(document, values['chapter_id'])
    require(type(values['confirm_title']) is str and values['confirm_title'] == chapter['title'],
            '请输入与当前章节完全一致的标题')
    require(type(values['acknowledge_references']) is bool
            and values['acknowledge_references'] is True,
            '请确认已知悉现有引用与影响范围')
    require(not is_archived(state, chapter['id']), '归档章节不能直接移入回收站')
    require(not is_trashed(state, chapter['id']), '章节已在回收站')
    preview = preview_trash(state, chapter['id'])
    require(preview['can_trash'], '章节当前不能移入回收站')
    volume_number, position = _volume_location(document, chapter['id'])
    original_number = chapter['number']
    outline = document.get('book_outline')
    if outline is not None:
        for volume in outline['volumes']:
            volume['chapter_ids'] = [identifier for identifier in volume['chapter_ids']
                                     if identifier != chapter['id']]
    _renumber(document)
    event_id = str(uuid5(NAMESPACE_URL, 'novel-writer/chapter-trash/1/'
                         + values['operation_id'] + '/event'))
    state['chapter_trash_events'].append(encode(TrashEvent(
        id=event_id, project_id=document['project']['id'],
        operation_id=values['operation_id'], chapter_id=chapter['id'], kind='trash',
        title_snapshot=chapter['title'], original_volume_number=volume_number,
        original_position=position, original_number=original_number,
        request_sha256=request_sha256, trash_event_id=None, created_at=utc_now())))
    return state


def restore_trash(state, values, expected_revision=None):
    check_fields(values, {'chapter_id', 'operation_id', 'confirmed'})
    require(set(values) == {'chapter_id', 'operation_id', 'confirmed'}
            and values['confirmed'] is True, '从回收站恢复需要明确确认')
    _require_operation(values)
    request_sha256 = _hash(values, 'restore_trashed_chapter')
    if _check_replay(state, 'restore_trashed_chapter', values, request_sha256):
        return state
    _check_revision(state, expected_revision)
    document = state['document']
    chapter = _chapter(document, values['chapter_id'])
    require(is_trashed(state, chapter['id']), '章节不在回收站')
    trash_event = latest_trash_event(state, chapter['id'])
    require(trash_event is not None and trash_event['kind'] == 'trash', '找不到可恢复的回收记录')
    if trash_event['original_volume_number'] is not None:
        volume = _volume(document, trash_event['original_volume_number'])
        position = min(trash_event['original_position'], len(volume['chapter_ids']))
        volume['chapter_ids'].insert(position, chapter['id'])
    else:
        ordered = sorted((value for value in document['chapters'] if value['id'] != chapter['id']),
                         key=lambda value: value['number'])
        ordered.insert(min(trash_event['original_number'] - 1, len(ordered)), chapter)
        for number, value in enumerate(ordered, 1):
            value['number'] = number
    _renumber(document)
    state['chapter_trash_events'].append(encode(TrashEvent(
        id=str(uuid5(NAMESPACE_URL, 'novel-writer/chapter-trash/1/'
                     + values['operation_id'] + '/event')),
        project_id=document['project']['id'], operation_id=values['operation_id'],
        chapter_id=chapter['id'], kind='restore', title_snapshot=trash_event['title_snapshot'],
        original_volume_number=trash_event['original_volume_number'],
        original_position=trash_event['original_position'],
        original_number=trash_event['original_number'], request_sha256=request_sha256,
        trash_event_id=trash_event['id'], created_at=utc_now())))
    return state


def execute(repository, project_id, action, values, *, expected_revision):
    require(action in ('trash_chapter', 'restore_trashed_chapter'), '未知章节回收站操作')
    identity = uuid_value(values.get('operation_id'))

    def operation(state):
        upgrade(state)
        request_sha256 = _hash(values, action)
        existing = event_for_operation(state, identity)
        if existing is not None:
            _check_replay(state, action, values, request_sha256)
            return None, deepcopy(state)
        result = (trash(state, values, expected_revision) if action == 'trash_chapter'
                  else restore_trash(state, values, expected_revision))
        return result, result
    return repository.atomic(project_id, operation,
                             identity_claim=('chapter_trash_events', 'operation_id', identity))


def apply(state, action, values, expected_revision=None):
    if action in ('move_chapter', 'archive_chapter', 'unarchive_chapter'):
        upgrade_base(state)
    else:
        upgrade(state)
    if action == 'move_chapter':
        return move(state, values)
    if action == 'move_chapter_to_volume':
        return move_to_volume(state, values)
    if action == 'archive_chapter':
        return archive(state, values)
    if action == 'unarchive_chapter':
        return restore(state, values)
    if action == 'trash_chapter':
        return trash(state, values, expected_revision)
    if action == 'restore_trashed_chapter':
        return restore_trash(state, values, expected_revision)
    raise ValueError('未知章节生命周期操作')


__all__ = [
    'active_chapters', 'apply', 'archived_ids', 'execute', 'hidden_ids', 'is_archived',
    'is_hidden', 'is_trashed', 'move', 'move_to_volume', 'preview_trash',
    'require_active', 'restore', 'restore_trash', 'trashed_ids', 'trash', 'upgrade',
]
