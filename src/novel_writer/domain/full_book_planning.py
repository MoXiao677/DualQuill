"""V26 explicit full-book arcs, key events, chapter dependencies, and deviation view."""
from dataclasses import dataclass
from typing import Literal

from novel_writer.domain.chapter_lifecycle import archived_ids
from novel_writer.domain.chapter_trash import trashed_ids
from novel_writer.domain.models import _timestamp
from novel_writer.domain.tasks import check_types, parse, require, uuid_value


ARC_STATUSES = ('planned', 'occurred', 'dropped')
EVENT_STATUSES = ('planned', 'occurred', 'dropped')
DEPENDENCY_KINDS = ('setup', 'payoff', 'continuity', 'causal', 'knowledge')
DEPENDENCY_KIND_LABELS = {
    'setup': '铺垫', 'payoff': '回收', 'continuity': '连续性', 'causal': '因果', 'knowledge': '信息传递',
}
ACTIONS = (
    'create_arc', 'update_arc', 'archive_arc', 'restore_arc',
    'create_stage', 'update_stage', 'occur_stage', 'drop_stage', 'reopen_stage',
    'create_event', 'update_event', 'occur_event', 'drop_event', 'reopen_event',
    'create_dependency', 'update_dependency', 'set_dependency_enabled',
    'archive_dependency', 'restore_dependency',
)
ACTION_TARGET = {
    'create_arc': 'arc', 'update_arc': 'arc', 'archive_arc': 'arc', 'restore_arc': 'arc',
    'create_stage': 'stage', 'update_stage': 'stage', 'occur_stage': 'stage',
    'drop_stage': 'stage', 'reopen_stage': 'stage',
    'create_event': 'event', 'update_event': 'event', 'occur_event': 'event',
    'drop_event': 'event', 'reopen_event': 'event',
    'create_dependency': 'dependency', 'update_dependency': 'dependency',
    'set_dependency_enabled': 'dependency', 'archive_dependency': 'dependency',
    'restore_dependency': 'dependency',
}
MAX_TEXT = 4000
MAX_TITLE = 200


def _control(value):
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def _optional_uuid(value):
    if value is not None:
        uuid_value(value)


class Value:
    def __post_init__(self):
        check_types(type(self), self)
        uuid_value(self.id)
        require(type(self.project_id) is str and bool(self.project_id.strip()), 'full_book_planning.invalid_project')
        if hasattr(self, 'created_at'):
            _timestamp(self.created_at, 'full_book_planning.created_at')


@dataclass(frozen=True, kw_only=True)
class CharacterArc(Value):
    id: str
    project_id: str
    character_id: str
    title: str
    summary: str
    archived: bool
    revision: int
    created_at: str
    updated_at: str

    def __post_init__(self):
        super().__post_init__()
        uuid_value(self.character_id)
        _timestamp(self.updated_at, 'full_book_planning.updated_at')
        require(type(self.title) is str and 0 < len(self.title) <= MAX_TITLE
                and self.title == self.title.strip() and not _control(self.title), 'full_book_planning.invalid_title')
        require(type(self.summary) is str and len(self.summary) <= MAX_TEXT and '\x00' not in self.summary,
                'full_book_planning.invalid_summary')
        require(type(self.archived) is bool and type(self.revision) is int and self.revision >= 1,
                'full_book_planning.invalid_arc')


@dataclass(frozen=True, kw_only=True)
class CharacterArcStage(Value):
    id: str
    project_id: str
    arc_id: str
    ordinal: int
    title: str
    summary: str
    planned_chapter_id: str | None
    status: Literal['planned', 'occurred', 'dropped']
    occurred_chapter_id: str | None
    body_reference: str
    revision: int
    created_at: str
    updated_at: str

    def __post_init__(self):
        super().__post_init__()
        uuid_value(self.arc_id)
        _optional_uuid(self.planned_chapter_id)
        _optional_uuid(self.occurred_chapter_id)
        _timestamp(self.updated_at, 'full_book_planning.updated_at')
        require(type(self.ordinal) is int and self.ordinal >= 1 and type(self.revision) is int and self.revision >= 1,
                'full_book_planning.invalid_stage')
        require(type(self.title) is str and 0 < len(self.title) <= MAX_TITLE
                and self.title == self.title.strip() and not _control(self.title), 'full_book_planning.invalid_title')
        require(type(self.summary) is str and len(self.summary) <= MAX_TEXT and '\x00' not in self.summary,
                'full_book_planning.invalid_summary')
        require(self.status in ARC_STATUSES, 'full_book_planning.invalid_status')
        require(type(self.body_reference) is str and len(self.body_reference) <= MAX_TEXT
                and '\x00' not in self.body_reference, 'full_book_planning.invalid_occurrence')
        if self.status == 'occurred':
            require(self.occurred_chapter_id is not None and bool(self.body_reference.strip()),
                    'full_book_planning.occurrence_required')
        else:
            require(self.occurred_chapter_id is None and self.body_reference == '',
                    'full_book_planning.occurrence_not_allowed')


@dataclass(frozen=True, kw_only=True)
class KeyEvent(Value):
    id: str
    project_id: str
    title: str
    summary: str
    character_id: str | None
    arc_id: str | None
    planned_chapter_id: str | None
    planned_order: int
    status: Literal['planned', 'occurred', 'dropped']
    occurred_chapter_id: str | None
    body_reference: str
    revision: int
    created_at: str
    updated_at: str

    def __post_init__(self):
        super().__post_init__()
        _optional_uuid(self.character_id)
        _optional_uuid(self.arc_id)
        _optional_uuid(self.planned_chapter_id)
        _optional_uuid(self.occurred_chapter_id)
        _timestamp(self.updated_at, 'full_book_planning.updated_at')
        require(type(self.title) is str and 0 < len(self.title) <= MAX_TITLE
                and self.title == self.title.strip() and not _control(self.title), 'full_book_planning.invalid_title')
        require(type(self.summary) is str and len(self.summary) <= MAX_TEXT and '\x00' not in self.summary,
                'full_book_planning.invalid_summary')
        require(self.status in EVENT_STATUSES, 'full_book_planning.invalid_status')
        require(type(self.planned_order) is int and self.planned_order >= 1 and type(self.revision) is int
                and self.revision >= 1, 'full_book_planning.invalid_event')
        require(type(self.body_reference) is str and len(self.body_reference) <= MAX_TEXT
                and '\x00' not in self.body_reference, 'full_book_planning.invalid_occurrence')
        if self.status == 'occurred':
            require(self.occurred_chapter_id is not None and bool(self.body_reference.strip()),
                    'full_book_planning.occurrence_required')
        else:
            require(self.occurred_chapter_id is None and self.body_reference == '',
                    'full_book_planning.occurrence_not_allowed')


@dataclass(frozen=True, kw_only=True)
class ChapterDependency(Value):
    id: str
    project_id: str
    predecessor_chapter_id: str
    successor_chapter_id: str
    kind: Literal['setup', 'payoff', 'continuity', 'causal', 'knowledge']
    note: str
    enabled: bool
    archived: bool
    revision: int
    created_at: str
    updated_at: str

    def __post_init__(self):
        super().__post_init__()
        uuid_value(self.predecessor_chapter_id)
        uuid_value(self.successor_chapter_id)
        _timestamp(self.updated_at, 'full_book_planning.updated_at')
        require(self.kind in DEPENDENCY_KINDS, 'full_book_planning.invalid_dependency_kind')
        require(type(self.note) is str and len(self.note) <= MAX_TEXT and '\x00' not in self.note,
                'full_book_planning.invalid_note')
        require(type(self.enabled) is bool and type(self.archived) is bool and type(self.revision) is int
                and self.revision >= 1, 'full_book_planning.invalid_dependency')
        require(self.predecessor_chapter_id != self.successor_chapter_id,
                'full_book_planning.self_dependency')


@dataclass(frozen=True, kw_only=True)
class PlanningOperation(Value):
    id: str
    project_id: str
    operation_id: str
    action: Literal['create_arc', 'update_arc', 'archive_arc', 'restore_arc',
                    'create_stage', 'update_stage', 'occur_stage', 'drop_stage', 'reopen_stage',
                    'create_event', 'update_event', 'occur_event', 'drop_event', 'reopen_event',
                    'create_dependency', 'update_dependency', 'set_dependency_enabled',
                    'archive_dependency', 'restore_dependency']
    target_kind: Literal['arc', 'stage', 'event', 'dependency']
    target_id: str
    expected_revision: int
    request_sha256: str
    created_at: str

    def __post_init__(self):
        super().__post_init__()
        uuid_value(self.operation_id)
        uuid_value(self.target_id)
        require(self.action in ACTIONS and ACTION_TARGET[self.action] == self.target_kind,
                'full_book_planning.invalid_operation')
        require(type(self.expected_revision) is int and self.expected_revision >= 1,
                'full_book_planning.invalid_operation')
        require(type(self.request_sha256) is str and len(self.request_sha256) == 64
                and all(char in '0123456789abcdef' for char in self.request_sha256),
                'full_book_planning.invalid_operation')


COLLECTIONS = {
    'character_arcs': CharacterArc,
    'character_arc_stages': CharacterArcStage,
    'key_events': KeyEvent,
    'chapter_dependencies': ChapterDependency,
    'full_book_planning_operations': PlanningOperation,
}


def _parse_collections(state):
    parsed = {}
    for name, model in COLLECTIONS.items():
        require(type(state[name]) is list and len(state[name]) <= 100000,
                'full_book_planning.invalid_collection')
        values = [parse(model, item) for item in state[name]]
        require(len({item.id for item in values}) == len(values), 'full_book_planning.duplicate_id')
        parsed[name] = values
    return parsed


def validate_state(state):
    if state.get('workspace_version', 0) < 26:
        require(not any(name in state for name in COLLECTIONS), 'full_book_planning.require_v26')
        return
    parsed = _parse_collections(state)
    project = state['document']['project']['id']
    chapters = {value['id']: value for value in state['document']['chapters']}
    characters = {value['id'] for value in state['document']['characters']}
    arcs = {value.id: value for value in parsed['character_arcs']}
    for arc in arcs.values():
        require(arc.project_id == project and arc.character_id in characters,
                'full_book_planning.orphan_arc')
    stages_by_arc = {}
    for stage in parsed['character_arc_stages']:
        require(stage.project_id == project and stage.arc_id in arcs,
                'full_book_planning.orphan_stage')
        require(stage.planned_chapter_id is None or stage.planned_chapter_id in chapters,
                'full_book_planning.missing_planned_chapter')
        require(stage.occurred_chapter_id is None or stage.occurred_chapter_id in chapters,
                'full_book_planning.missing_occurrence_chapter')
        stages_by_arc.setdefault(stage.arc_id, []).append(stage)
    for items in stages_by_arc.values():
        ordinals = [item.ordinal for item in items]
        require(len(ordinals) == len(set(ordinals)), 'full_book_planning.duplicate_ordinal')
    for event in parsed['key_events']:
        require(event.project_id == project, 'full_book_planning.invalid_project')
        require(event.character_id is None or event.character_id in characters,
                'full_book_planning.orphan_event_character')
        require(event.arc_id is None or event.arc_id in arcs, 'full_book_planning.orphan_event_arc')
        require(event.planned_chapter_id is None or event.planned_chapter_id in chapters,
                'full_book_planning.missing_planned_chapter')
        require(event.occurred_chapter_id is None or event.occurred_chapter_id in chapters,
                'full_book_planning.missing_occurrence_chapter')
    active_edges = set()
    for dependency in parsed['chapter_dependencies']:
        require(dependency.project_id == project, 'full_book_planning.invalid_project')
        require(dependency.predecessor_chapter_id in chapters and dependency.successor_chapter_id in chapters,
                'full_book_planning.orphan_dependency')
        key = (dependency.predecessor_chapter_id, dependency.successor_chapter_id, dependency.kind)
        if not dependency.archived:
            require(key not in active_edges, 'full_book_planning.duplicate_dependency')
            active_edges.add(key)
    operations = set()
    for operation in parsed['full_book_planning_operations']:
        require(operation.project_id == project, 'full_book_planning.invalid_project')
        require(operation.operation_id not in operations, 'full_book_planning.duplicate_operation')
        operations.add(operation.operation_id)
        targets = {
            'arc': {value.id for value in arcs.values()},
            'stage': {value.id for value in parsed['character_arc_stages']},
            'event': {value.id for value in parsed['key_events']},
            'dependency': {value.id for value in parsed['chapter_dependencies']},
        }
        require(operation.target_id in targets[operation.target_kind], 'full_book_planning.orphan_operation')


def validate_transition(state, previous):
    validate_state(state)
    old = previous or {}
    for name in COLLECTIONS:
        before = {item['id']: item for item in old.get(name, [])}
        after = {item['id']: item for item in state[name]}
        require(set(before) <= set(after), 'full_book_planning.cannot_delete')
        if name == 'full_book_planning_operations':
            require(state[name][:len(old.get(name, []))] == old.get(name, []),
                    'full_book_planning.operations_append_only')
            continue
        for identifier, old_value in before.items():
            new_value = after[identifier]
            for key in ('id', 'project_id', 'created_at'):
                require(old_value[key] == new_value[key], 'full_book_planning.binding_immutable')
            require(new_value['revision'] >= old_value['revision']
                    and new_value['updated_at'] >= old_value['updated_at'],
                    'full_book_planning.revision_invalid')
            changed = any(old_value[key] != new_value[key] for key in new_value if key not in ('revision', 'updated_at'))
            if changed:
                require(new_value['revision'] > old_value['revision'],
                        'full_book_planning.revision_required')


def _chapters(state):
    return {value['id']: value for value in state['document']['chapters']}


def _archived(state):
    return archived_ids(state)


def _trashed(state):
    return trashed_ids(state)


def _latest_confirmed(chapters):
    numbers = [value['number'] for value in chapters.values() if value['status'] == 'confirmed']
    return max(numbers, default=0)


def deviation_report(state):
    """Read-only planned/occurred comparison; chapter confirmation never flips occurrence."""
    chapters = _chapters(state)
    archived = _archived(state)
    trashed = _trashed(state)
    latest = _latest_confirmed(chapters)
    references = []
    comparisons = []
    deviations = []
    counts = {'late': 0, 'early': 0, 'unplanned': 0, 'missing': 0, 'blocked': 0}

    def reference(kind, entity_id, field, chapter_id):
        if chapter_id is None:
            return None
        chapter = chapters.get(chapter_id)
        if chapter is None:
            references.append({'kind': kind, 'entity_id': entity_id, 'field': field,
                               'chapter_id': chapter_id, 'state': 'missing'})
            return 'missing'
        if chapter_id in archived:
            references.append({'kind': kind, 'entity_id': entity_id, 'field': field,
                               'chapter_id': chapter_id, 'state': 'archived',
                               'chapter_number': chapter['number'], 'chapter_title': chapter['title']})
            return 'archived'
        if chapter_id in trashed:
            references.append({'kind': kind, 'entity_id': entity_id, 'field': field,
                               'chapter_id': chapter_id, 'state': 'trashed',
                               'chapter_number': chapter['number'], 'chapter_title': chapter['title']})
            return 'trashed'
        return None

    def record(kind, identifier, title, item, planned_id, actual_id, status):
        planned = chapters.get(planned_id) if planned_id else None
        actual = chapters.get(actual_id) if actual_id else None
        comparison = {
            'kind': kind, 'entity_id': identifier, 'title': title, 'status': status,
            'planned_chapter_id': planned_id,
            'planned_chapter_number': planned['number'] if planned else None,
            'actual_chapter_id': actual_id,
            'actual_chapter_number': actual['number'] if actual else None,
            'planned_order': item.get('planned_order'),
        }
        comparisons.append(comparison)
        return planned, actual

    def deviate(item, kind, reason, detail, planned=None, actual=None):
        counts[reason] += 1
        deviations.append({
            'kind': kind, 'entity_id': item['id'], 'title': item['title'], 'reason': reason,
            'planned_chapter_id': item.get('planned_chapter_id'),
            'actual_chapter_id': item.get('occurred_chapter_id'),
            'planned_chapter_number': planned['number'] if planned else None,
            'actual_chapter_number': actual['number'] if actual else None,
            'detail': detail,
        })

    stages_by_arc = {}
    for stage in state['character_arc_stages']:
        stages_by_arc.setdefault(stage['arc_id'], []).append(stage)
    arcs = {arc['id']: arc for arc in state['character_arcs']}
    for stage in state['character_arc_stages']:
        arc = arcs[stage['arc_id']]
        title = f"{arc['title']} / {stage['title']}"
        planned, actual = record('arc_stage', stage['id'], title, stage,
                                 stage['planned_chapter_id'], stage['occurred_chapter_id'], stage['status'])
        planned_state = reference('arc_stage', stage['id'], 'planned_chapter_id', stage['planned_chapter_id'])
        actual_state = reference('arc_stage', stage['id'], 'occurred_chapter_id', stage['occurred_chapter_id'])
        if stage['status'] == 'planned':
            if planned_state == 'missing':
                deviate(stage, 'arc_stage', 'missing', '计划章节不存在，需作者修复引用。', planned)
            elif planned_state in ('archived', 'trashed'):
                deviate(stage, 'arc_stage', 'blocked', '计划章节已归档或移入回收站，阶段仍未记录发生。', planned)
            elif planned and planned['number'] <= latest:
                deviate(stage, 'arc_stage', 'missing', '计划位置已进入已确认章节范围，但没有作者记录的发生章节。', planned)
        elif stage['status'] == 'occurred':
            if actual_state in ('missing', 'archived', 'trashed'):
                deviate(stage, 'arc_stage', 'blocked' if actual_state in ('archived', 'trashed') else 'missing',
                        '发生章节缺失、已归档或已移入回收站，需作者修复引用。', planned, actual)
            elif stage['planned_chapter_id'] is None:
                deviate(stage, 'arc_stage', 'unplanned', '作者已记录发生，但没有计划章节。', planned, actual)
            elif planned is None:
                deviate(stage, 'arc_stage', 'missing', '计划章节引用无效，无法比较位置。', planned, actual)
            elif actual and actual['number'] > planned['number']:
                deviate(stage, 'arc_stage', 'late', '实际发生晚于计划章节。', planned, actual)
            elif actual and actual['number'] < planned['number']:
                deviate(stage, 'arc_stage', 'early', '实际发生早于计划章节。', planned, actual)

    for event in state['key_events']:
        planned, actual = record('key_event', event['id'], event['title'], event,
                                 event['planned_chapter_id'], event['occurred_chapter_id'], event['status'])
        planned_state = reference('key_event', event['id'], 'planned_chapter_id', event['planned_chapter_id'])
        actual_state = reference('key_event', event['id'], 'occurred_chapter_id', event['occurred_chapter_id'])
        if event['status'] == 'planned':
            if planned_state == 'missing':
                deviate(event, 'key_event', 'missing', '计划章节不存在，需作者修复引用。', planned)
            elif planned_state in ('archived', 'trashed'):
                deviate(event, 'key_event', 'blocked', '计划章节已归档或移入回收站，事件仍未记录发生。', planned)
            elif planned and planned['number'] <= latest:
                deviate(event, 'key_event', 'missing', '计划位置已进入已确认章节范围，但没有作者记录的发生章节。', planned)
        elif event['status'] == 'occurred':
            if actual_state in ('missing', 'archived', 'trashed'):
                deviate(event, 'key_event', 'blocked' if actual_state in ('archived', 'trashed') else 'missing',
                        '发生章节缺失、已归档或已移入回收站，需作者修复引用。', planned, actual)
            elif event['planned_chapter_id'] is None:
                deviate(event, 'key_event', 'unplanned', '作者已记录发生，但没有计划章节。', planned, actual)
            elif planned is None:
                deviate(event, 'key_event', 'missing', '计划章节引用无效，无法比较位置。', planned, actual)
            elif actual and actual['number'] > planned['number']:
                deviate(event, 'key_event', 'late', '实际发生晚于计划章节。', planned, actual)
            elif actual and actual['number'] < planned['number']:
                deviate(event, 'key_event', 'early', '实际发生早于计划章节。', planned, actual)

    for dependency in state['chapter_dependencies']:
        if dependency['archived'] or not dependency['enabled']:
            continue
        pred_state = reference('chapter_dependency', dependency['id'], 'predecessor_chapter_id',
                               dependency['predecessor_chapter_id'])
        succ_state = reference('chapter_dependency', dependency['id'], 'successor_chapter_id',
                               dependency['successor_chapter_id'])
        pred = chapters.get(dependency['predecessor_chapter_id'])
        succ = chapters.get(dependency['successor_chapter_id'])
        if pred_state == 'missing' or succ_state == 'missing':
            deviate({'id': dependency['id'], 'title': DEPENDENCY_KIND_LABELS[dependency['kind']],
                     'planned_chapter_id': dependency['successor_chapter_id'],
                     'occurred_chapter_id': None}, 'chapter_dependency', 'missing',
                    '依赖的一端章节不存在，需作者修复引用。', succ)
        elif pred_state in ('archived', 'trashed') or succ_state in ('archived', 'trashed'):
            deviate({'id': dependency['id'], 'title': DEPENDENCY_KIND_LABELS[dependency['kind']],
                     'planned_chapter_id': dependency['successor_chapter_id'],
                     'occurred_chapter_id': None}, 'chapter_dependency', 'blocked',
                    '依赖的一端章节已归档或移入回收站。', succ)
        elif succ and succ['status'] == 'confirmed' and (pred is None or pred['status'] != 'confirmed'):
            deviate({'id': dependency['id'], 'title': DEPENDENCY_KIND_LABELS[dependency['kind']],
                     'planned_chapter_id': dependency['successor_chapter_id'],
                     'occurred_chapter_id': None}, 'chapter_dependency', 'blocked',
                    '后继章节已确认，但前驱章节尚未确认。', succ)

    stages = state['character_arc_stages']
    events = state['key_events']
    dependencies = state['chapter_dependencies']
    return {
        'confirmed_chapter_count': sum(1 for value in chapters.values() if value['status'] == 'confirmed'),
        'latest_confirmed_chapter_number': latest or None,
        'stage_counts': {status: sum(1 for value in stages if value['status'] == status) for status in ARC_STATUSES},
        'event_counts': {status: sum(1 for value in events if value['status'] == status) for status in EVENT_STATUSES},
        'dependency_counts': {
            'enabled': sum(1 for value in dependencies if value['enabled'] and not value['archived']),
            'disabled': sum(1 for value in dependencies if not value['enabled'] and not value['archived']),
            'archived': sum(1 for value in dependencies if value['archived']),
        },
        'deviations_by_reason': counts,
        'deviations': deviations,
        'positions': comparisons,
        'references': references,
        'occurrence_policy': 'occurred 仅由作者显式记录发生章节和正文引用；章节确认不会自动改变规划状态',
    }
