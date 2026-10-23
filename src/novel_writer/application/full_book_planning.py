"""Explicit V26 full-book planning writes and deterministic progress/deviation reads."""
import hashlib
import json
from uuid import NAMESPACE_URL, uuid5

from novel_writer.application.fields import check_fields
from novel_writer.domain.body_planning import archived as entity_archived, require_unlocked
from novel_writer.domain.chapter_lifecycle import archived_ids, require_active
from novel_writer.domain.chapter_trash import hidden_ids, trashed_ids
from novel_writer.domain.full_book_planning import (
    ACTIONS, COLLECTIONS, DEPENDENCY_KINDS, DEPENDENCY_KIND_LABELS,
    CharacterArc, CharacterArcStage, ChapterDependency, KeyEvent, PlanningOperation, deviation_report,
)
from novel_writer.domain.models import utc_now
from novel_writer.domain.tasks import require, uuid_value
from novel_writer.storage.sqlite_repository import ConflictError


def upgrade(state):
    from novel_writer.application.materials import upgrade as previous
    previous(state)
    state['workspace_version'] = max(state['workspace_version'], 26)
    for name in COLLECTIONS:
        state.setdefault(name, [])
    return state


def _uid(operation, suffix):
    return str(uuid5(NAMESPACE_URL, 'novel-writer/full-book-planning/1/' + operation + '/' + suffix))


def _hash(request):
    semantic = {key: value for key, value in request.items()
                if key not in ('operation_id', 'expected_revision')}
    raw = json.dumps(semantic, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf8')
    return hashlib.sha256(raw).hexdigest()


def _record(value):
    return {key: getattr(value, key) for key in value.__dataclass_fields__}


def _fields(request, required, optional=()):
    allowed = set(required) | set(optional)
    check_fields(request, allowed)
    require(set(required) <= set(request), 'full_book_planning.missing_fields')


def _revision(request):
    value = request.get('expected_revision')
    require(type(value) is int and value >= 1, 'full_book_planning.invalid_revision')
    return value


def _identity(request):
    return uuid_value(request.get('operation_id'))


def _title(value):
    require(type(value) is str, 'full_book_planning.invalid_title')
    value = value.strip()
    require(0 < len(value) <= 200 and not any(ord(char) < 32 or ord(char) == 127 for char in value),
            'full_book_planning.invalid_title')
    return value


def _summary(value):
    require(type(value) is str and len(value) <= 4000 and '\x00' not in value,
            'full_book_planning.invalid_summary')
    return value


def _note(value):
    require(type(value) is str and len(value) <= 4000 and '\x00' not in value,
            'full_book_planning.invalid_note')
    return value


def _body_reference(value):
    require(type(value) is str and 0 < len(value) <= 4000 and bool(value.strip()) and '\x00' not in value,
            'full_book_planning.invalid_occurrence')
    return value


def _optional_id(value):
    if value is not None:
        uuid_value(value)
    return value


def _chapter_name(value):
    return f"第{value['number']}章 {value['title']}" if value else None


def _chapter_view(value, archived, trashed):
    return {**value, 'archived': value['id'] in archived, 'trashed': value['id'] in trashed,
            'hidden': value['id'] in archived or value['id'] in trashed,
            'label': _chapter_name(value)}


def _listing(state, revision=None):
    archived = archived_ids(state)
    trashed = trashed_ids(state)
    chapters = sorted(state['document']['chapters'], key=lambda value: (value['number'], value['id']))
    chapter_map = {value['id']: value for value in chapters}
    characters = sorted(state['document']['characters'], key=lambda value: (value['name'], value['id']))
    character_map = {value['id']: value for value in characters}
    arcs = sorted(state['character_arcs'], key=lambda value: (value['archived'], value['title'], value['id']))
    arc_map = {value['id']: value for value in arcs}
    stages_by_arc = {}
    for stage in sorted(state['character_arc_stages'], key=lambda value: (value['ordinal'], value['id'])):
        planned = chapter_map.get(stage['planned_chapter_id'])
        occurred = chapter_map.get(stage['occurred_chapter_id'])
        stages_by_arc.setdefault(stage['arc_id'], []).append({
            **stage,
            'arc_title': arc_map[stage['arc_id']]['title'],
            'planned_chapter_number': planned['number'] if planned else None,
            'planned_chapter_title': planned['title'] if planned else None,
            'occurred_chapter_number': occurred['number'] if occurred else None,
            'occurred_chapter_title': occurred['title'] if occurred else None,
        })
    arc_views = [dict(arc, stages=stages_by_arc.get(arc['id'], []),
                      stage_count=len(stages_by_arc.get(arc['id'], [])),
                      occurred_stage_count=sum(1 for value in stages_by_arc.get(arc['id'], [])
                                               if value['status'] == 'occurred')) for arc in arcs]
    flat_stages = [stage for values in stages_by_arc.values() for stage in values]
    events = sorted(state['key_events'], key=lambda value: (value['planned_order'], value['title'], value['id']))
    event_views = []
    for event in events:
        planned = chapter_map.get(event['planned_chapter_id'])
        occurred = chapter_map.get(event['occurred_chapter_id'])
        character = character_map.get(event['character_id'])
        arc = arc_map.get(event['arc_id'])
        event_views.append({**event, 'character_name': character['name'] if character else None,
                            'arc_title': arc['title'] if arc else None,
                            'planned_chapter_number': planned['number'] if planned else None,
                            'planned_chapter_title': planned['title'] if planned else None,
                            'occurred_chapter_number': occurred['number'] if occurred else None,
                            'occurred_chapter_title': occurred['title'] if occurred else None})
    dependencies = sorted(state['chapter_dependencies'],
                          key=lambda value: (value['archived'], not value['enabled'], value['kind'], value['id']))
    dependency_views = []
    for dependency in dependencies:
        predecessor = chapter_map.get(dependency['predecessor_chapter_id'])
        successor = chapter_map.get(dependency['successor_chapter_id'])
        dependency_views.append({**dependency, 'kind_label': DEPENDENCY_KIND_LABELS[dependency['kind']],
                                 'predecessor_number': predecessor['number'] if predecessor else None,
                                 'predecessor_title': predecessor['title'] if predecessor else None,
                                 'successor_number': successor['number'] if successor else None,
                                 'successor_title': successor['title'] if successor else None})
    return {
        'revision': state['revision'] if revision is None else revision,
        'character_arcs': arc_views,
        'character_arc_stages': flat_stages,
        'key_events': event_views,
        'chapter_dependencies': dependency_views,
        'chapters': [_chapter_view(value, archived, trashed) for value in chapters],
        'characters': [{'id': value['id'], 'name': value['name'], 'role': value['role'],
                        'archived': entity_archived(state, 'character', value['id'])} for value in characters],
        'deviation': deviation_report(state),
        'dependency_kinds': [{'id': value, 'label': DEPENDENCY_KIND_LABELS[value]} for value in DEPENDENCY_KINDS],
        'actions': list(ACTIONS),
        'method': '本地显式规划；occurred 只接受作者记录的发生章节和正文引用，不从章节确认自动推导',
        'model_request_sent': False,
        'ai_completion': {'status': 'unavailable', 'reason': 'AI 补全未实现；当前入口不接受模型请求'},
    }


class FullBookPlanning:
    def __init__(self, service):
        self.service = service
        self.repository = service.repository

    def listing(self, project):
        state = self.service.get(project)
        upgrade(state)
        return _listing(state)

    def _arc(self, state, arc_id):
        uuid_value(arc_id)
        value = next((item for item in state['character_arcs'] if item['id'] == arc_id), None)
        if value is None:
            raise KeyError('人物弧光不存在')
        return value

    def _active_arc(self, state, arc_id):
        value = self._arc(state, arc_id)
        require_unlocked(state, 'arc', arc_id)
        require(not value['archived'], 'full_book_planning.archived_arc')
        self._character(state, value['character_id'])
        return value

    def _stage(self, state, stage_id):
        uuid_value(stage_id)
        value = next((item for item in state['character_arc_stages'] if item['id'] == stage_id), None)
        if value is None:
            raise KeyError('弧光阶段不存在')
        return value

    def _event(self, state, event_id):
        uuid_value(event_id)
        value = next((item for item in state['key_events'] if item['id'] == event_id), None)
        if value is None:
            raise KeyError('关键事件不存在')
        return value

    def _dependency(self, state, dependency_id):
        uuid_value(dependency_id)
        value = next((item for item in state['chapter_dependencies'] if item['id'] == dependency_id), None)
        if value is None:
            raise KeyError('章节依赖不存在')
        return value

    def _chapter(self, state, chapter_id, *, active=True):
        uuid_value(chapter_id)
        value = next((item for item in state['document']['chapters'] if item['id'] == chapter_id), None)
        if value is None:
            raise KeyError('章节不存在或不属于当前书')
        if active:
            require(chapter_id not in hidden_ids(state), 'full_book_planning.hidden_chapter')
        return value

    def _optional_chapter(self, state, chapter_id):
        return None if chapter_id is None else self._chapter(state, chapter_id)

    def _occurrence_chapter(self, state, chapter_id, body_reference):
        chapter = self._chapter(state, chapter_id)
        if state['workspace_version'] >= 43:
            require(chapter.get('current_version_id') is not None and body_reference in chapter['content'],
                    '发生记录须引用该章节实际已保存正文的精确片段')
        return chapter

    def _character(self, state, character_id):
        uuid_value(character_id)
        value = next((item for item in state['document']['characters'] if item['id'] == character_id), None)
        if value is None:
            raise KeyError('人物不存在或不属于当前书')
        from novel_writer.domain.body_planning import archived
        require(not archived(state, 'character', character_id), '人物已归档，请先恢复')
        return value

    def _replay(self, state, identity, action, request_hash, target_id):
        old = next((value for value in state['full_book_planning_operations']
                    if value['operation_id'] == identity), None)
        if old is None:
            from novel_writer.domain.full_book_planning import ACTION_TARGET
            from novel_writer.domain.body_planning import require_unlocked
            require_unlocked(state, ACTION_TARGET[action], target_id)
            return None
        require(old['action'] == action and old['target_id'] == target_id
                and old['request_sha256'] == request_hash, 'full_book_planning.operation_conflict')
        return old

    def _check(self, state, revision):
        if state['revision'] != revision:
            raise ConflictError('小说已在其他窗口更新，请重新读取全书规划后再操作')

    def _operation(self, state, project, identity, action, target_kind, target_id,
                   revision, request_hash):
        state['full_book_planning_operations'].append(_record(PlanningOperation(
            id=_uid(identity, 'operation'), project_id=project, operation_id=identity,
            action=action, target_kind=target_kind, target_id=target_id,
            expected_revision=revision, request_sha256=request_hash, created_at=utc_now())))

    def create_arc(self, project, request):
        _fields(request, {'operation_id', 'expected_revision', 'character_id', 'title'}, {'summary'})
        identity, revision = _identity(request), _revision(request)
        request_hash = _hash(request)
        arc_id = _uid(identity, 'arc')
        character_id = uuid_value(request['character_id'])
        title = _title(request['title'])
        summary = _summary(request.get('summary', ''))

        def operation(state):
            upgrade(state)
            old = self._replay(state, identity, 'create_arc', request_hash, arc_id)
            if old:
                return None, _listing(state)
            self._check(state, revision)
            self._character(state, character_id)
            require(all(value['id'] != arc_id for value in state['character_arcs']),
                    'full_book_planning.identity_conflict')
            now = utc_now()
            state['character_arcs'].append(_record(CharacterArc(
                id=arc_id, project_id=project, character_id=character_id, title=title,
                summary=summary, archived=False, revision=1, created_at=now, updated_at=now)))
            self._operation(state, project, identity, 'create_arc', 'arc', arc_id,
                            revision, request_hash)
            return state, _listing(state, state['revision'] + 1)
        return self.repository.atomic(project, operation,
                                      identity_claim=('full_book_planning_operations', 'operation_id', identity))

    def update_stage(self, project, request):
        _fields(request, {'operation_id', 'expected_revision', 'stage_id'},
                {'title', 'summary', 'planned_chapter_id'})
        require(any(key in request for key in ('title', 'summary', 'planned_chapter_id')),
                'full_book_planning.nothing_to_update')
        identity, revision, request_hash = _identity(request), _revision(request), _hash(request)
        stage_id = uuid_value(request['stage_id'])
        changes = {}
        if 'title' in request:
            changes['title'] = _title(request['title'])
        if 'summary' in request:
            changes['summary'] = _summary(request['summary'])
        if 'planned_chapter_id' in request:
            changes['planned_chapter_id'] = _optional_id(request['planned_chapter_id'])

        def operation(state):
            upgrade(state)
            old = self._replay(state, identity, 'update_stage', request_hash, stage_id)
            if old:
                return None, _listing(state)
            self._check(state, revision)
            stage = self._stage(state, stage_id)
            self._active_arc(state, stage['arc_id'])
            if 'planned_chapter_id' in changes:
                self._optional_chapter(state, changes['planned_chapter_id'])
            stage.update(changes)
            stage['revision'] += 1
            stage['updated_at'] = utc_now()
            self._operation(state, project, identity, 'update_stage', 'stage', stage_id,
                            revision, request_hash)
            return state, _listing(state, state['revision'] + 1)
        return self.repository.atomic(project, operation,
                                      identity_claim=('full_book_planning_operations', 'operation_id', identity))

    def occur_stage(self, project, request):
        _fields(request, {'operation_id', 'expected_revision', 'stage_id',
                          'occurrence_chapter_id', 'body_reference'})
        identity, revision, request_hash = _identity(request), _revision(request), _hash(request)
        stage_id = uuid_value(request['stage_id'])
        chapter_id = uuid_value(request['occurrence_chapter_id'])
        body_reference = _body_reference(request['body_reference'])

        def operation(state):
            upgrade(state)
            old = self._replay(state, identity, 'occur_stage', request_hash, stage_id)
            if old:
                return None, _listing(state)
            self._check(state, revision)
            stage = self._stage(state, stage_id)
            self._active_arc(state, stage['arc_id'])
            require(stage['status'] == 'planned', 'full_book_planning.stage_not_planned')
            self._occurrence_chapter(state, chapter_id, body_reference)
            stage.update(status='occurred', occurred_chapter_id=chapter_id,
                         body_reference=body_reference, revision=stage['revision'] + 1, updated_at=utc_now())
            self._operation(state, project, identity, 'occur_stage', 'stage', stage_id,
                            revision, request_hash)
            return state, _listing(state, state['revision'] + 1)
        return self.repository.atomic(project, operation,
                                      identity_claim=('full_book_planning_operations', 'operation_id', identity))

    def _change_stage_status(self, project, request, action, allowed_from, status):
        _fields(request, {'operation_id', 'expected_revision', 'stage_id'})
        identity, revision, request_hash = _identity(request), _revision(request), _hash(request)
        stage_id = uuid_value(request['stage_id'])

        def operation(state):
            upgrade(state)
            old = self._replay(state, identity, action, request_hash, stage_id)
            if old:
                return None, _listing(state)
            self._check(state, revision)
            stage = self._stage(state, stage_id)
            self._active_arc(state, stage['arc_id'])
            require(stage['status'] in allowed_from, 'full_book_planning.invalid_stage_state')
            stage.update(status=status, occurred_chapter_id=None, body_reference='',
                         revision=stage['revision'] + 1, updated_at=utc_now())
            self._operation(state, project, identity, action, 'stage', stage_id,
                            revision, request_hash)
            return state, _listing(state, state['revision'] + 1)
        return self.repository.atomic(project, operation,
                                      identity_claim=('full_book_planning_operations', 'operation_id', identity))

    def drop_stage(self, project, request):
        return self._change_stage_status(project, request, 'drop_stage', ('planned',), 'dropped')

    def reopen_stage(self, project, request):
        return self._change_stage_status(project, request, 'reopen_stage', ('occurred', 'dropped'), 'planned')

    def create_event(self, project, request):
        _fields(request, {'operation_id', 'expected_revision', 'title'},
                {'summary', 'character_id', 'arc_id', 'planned_chapter_id', 'planned_order'})
        identity, revision, request_hash = _identity(request), _revision(request), _hash(request)
        event_id = _uid(identity, 'event')
        title = _title(request['title'])
        summary = _summary(request.get('summary', ''))
        character_id = _optional_id(request.get('character_id'))
        arc_id = _optional_id(request.get('arc_id'))
        planned_chapter_id = _optional_id(request.get('planned_chapter_id'))
        planned_order = request.get('planned_order')
        if planned_order is not None:
            require(type(planned_order) is int and planned_order >= 1, 'full_book_planning.invalid_order')

        def operation(state):
            upgrade(state)
            old = self._replay(state, identity, 'create_event', request_hash, event_id)
            if old:
                return None, _listing(state)
            self._check(state, revision)
            if character_id is not None:
                self._character(state, character_id)
            if arc_id is not None:
                self._active_arc(state, arc_id)
            self._optional_chapter(state, planned_chapter_id)
            require(all(value['id'] != event_id for value in state['key_events']),
                    'full_book_planning.identity_conflict')
            order = planned_order if planned_order is not None else max(
                (value['planned_order'] for value in state['key_events']), default=0) + 1
            now = utc_now()
            state['key_events'].append(_record(KeyEvent(
                id=event_id, project_id=project, title=title, summary=summary,
                character_id=character_id, arc_id=arc_id,
                planned_chapter_id=planned_chapter_id, planned_order=order,
                status='planned', occurred_chapter_id=None, body_reference='', revision=1,
                created_at=now, updated_at=now)))
            self._operation(state, project, identity, 'create_event', 'event', event_id,
                            revision, request_hash)
            return state, _listing(state, state['revision'] + 1)
        return self.repository.atomic(project, operation,
                                      identity_claim=('full_book_planning_operations', 'operation_id', identity))

    def update_event(self, project, request):
        _fields(request, {'operation_id', 'expected_revision', 'event_id'},
                {'title', 'summary', 'character_id', 'arc_id', 'planned_chapter_id', 'planned_order'})
        require(any(key in request for key in
                    ('title', 'summary', 'character_id', 'arc_id', 'planned_chapter_id', 'planned_order')),
                'full_book_planning.nothing_to_update')
        identity, revision, request_hash = _identity(request), _revision(request), _hash(request)
        event_id = uuid_value(request['event_id'])
        changes = {}
        if 'title' in request:
            changes['title'] = _title(request['title'])
        if 'summary' in request:
            changes['summary'] = _summary(request['summary'])
        for key in ('character_id', 'arc_id', 'planned_chapter_id'):
            if key in request:
                changes[key] = _optional_id(request[key])
        if 'planned_order' in request:
            require(type(request['planned_order']) is int and request['planned_order'] >= 1,
                    'full_book_planning.invalid_order')
            changes['planned_order'] = request['planned_order']

        def operation(state):
            upgrade(state)
            old = self._replay(state, identity, 'update_event', request_hash, event_id)
            if old:
                return None, _listing(state)
            self._check(state, revision)
            event = self._event(state, event_id)
            if 'character_id' in changes and changes['character_id'] is not None:
                self._character(state, changes['character_id'])
            if 'arc_id' in changes and changes['arc_id'] is not None:
                self._active_arc(state, changes['arc_id'])
            if 'planned_chapter_id' in changes:
                self._optional_chapter(state, changes['planned_chapter_id'])
            event.update(changes)
            event['revision'] += 1
            event['updated_at'] = utc_now()
            self._operation(state, project, identity, 'update_event', 'event', event_id,
                            revision, request_hash)
            return state, _listing(state, state['revision'] + 1)
        return self.repository.atomic(project, operation,
                                      identity_claim=('full_book_planning_operations', 'operation_id', identity))

    def occur_event(self, project, request):
        _fields(request, {'operation_id', 'expected_revision', 'event_id',
                          'occurrence_chapter_id', 'body_reference'})
        identity, revision, request_hash = _identity(request), _revision(request), _hash(request)
        event_id = uuid_value(request['event_id'])
        chapter_id = uuid_value(request['occurrence_chapter_id'])
        body_reference = _body_reference(request['body_reference'])

        def operation(state):
            upgrade(state)
            old = self._replay(state, identity, 'occur_event', request_hash, event_id)
            if old:
                return None, _listing(state)
            self._check(state, revision)
            event = self._event(state, event_id)
            require(event['status'] == 'planned', 'full_book_planning.event_not_planned')
            if event['arc_id'] is not None:
                self._active_arc(state, event['arc_id'])
            self._occurrence_chapter(state, chapter_id, body_reference)
            event.update(status='occurred', occurred_chapter_id=chapter_id,
                         body_reference=body_reference, revision=event['revision'] + 1, updated_at=utc_now())
            self._operation(state, project, identity, 'occur_event', 'event', event_id,
                            revision, request_hash)
            return state, _listing(state, state['revision'] + 1)
        return self.repository.atomic(project, operation,
                                      identity_claim=('full_book_planning_operations', 'operation_id', identity))

    def _change_event_status(self, project, request, action, allowed_from, status):
        _fields(request, {'operation_id', 'expected_revision', 'event_id'})
        identity, revision, request_hash = _identity(request), _revision(request), _hash(request)
        event_id = uuid_value(request['event_id'])

        def operation(state):
            upgrade(state)
            old = self._replay(state, identity, action, request_hash, event_id)
            if old:
                return None, _listing(state)
            self._check(state, revision)
            event = self._event(state, event_id)
            require(event['status'] in allowed_from, 'full_book_planning.invalid_event_state')
            event.update(status=status, occurred_chapter_id=None, body_reference='',
                         revision=event['revision'] + 1, updated_at=utc_now())
            self._operation(state, project, identity, action, 'event', event_id,
                            revision, request_hash)
            return state, _listing(state, state['revision'] + 1)
        return self.repository.atomic(project, operation,
                                      identity_claim=('full_book_planning_operations', 'operation_id', identity))

    def drop_event(self, project, request):
        return self._change_event_status(project, request, 'drop_event', ('planned',), 'dropped')

    def reopen_event(self, project, request):
        return self._change_event_status(project, request, 'reopen_event', ('occurred', 'dropped'), 'planned')

    def _dependency_values(self, state, predecessor_id, successor_id, kind):
        predecessor = self._chapter(state, predecessor_id)
        successor = self._chapter(state, successor_id)
        require(predecessor['id'] != successor['id'], 'full_book_planning.self_dependency')
        require(kind in DEPENDENCY_KINDS, 'full_book_planning.invalid_dependency_kind')
        return predecessor, successor

    def create_dependency(self, project, request):
        _fields(request, {'operation_id', 'expected_revision', 'predecessor_chapter_id',
                          'successor_chapter_id', 'kind'}, {'note', 'enabled'})
        identity, revision, request_hash = _identity(request), _revision(request), _hash(request)
        dependency_id = _uid(identity, 'dependency')
        predecessor_id = uuid_value(request['predecessor_chapter_id'])
        successor_id = uuid_value(request['successor_chapter_id'])
        kind = request['kind']
        require(type(kind) is str and kind in DEPENDENCY_KINDS, 'full_book_planning.invalid_dependency_kind')
        note = _note(request.get('note', ''))
        enabled = request.get('enabled', True)
        require(type(enabled) is bool, 'full_book_planning.invalid_dependency')

        def operation(state):
            upgrade(state)
            old = self._replay(state, identity, 'create_dependency', request_hash, dependency_id)
            if old:
                return None, _listing(state)
            self._check(state, revision)
            self._dependency_values(state, predecessor_id, successor_id, kind)
            require(all(value['id'] != dependency_id for value in state['chapter_dependencies']),
                    'full_book_planning.identity_conflict')
            require(all(value['archived'] or (value['predecessor_chapter_id'], value['successor_chapter_id'], value['kind'])
                        != (predecessor_id, successor_id, kind) for value in state['chapter_dependencies']),
                    'full_book_planning.duplicate_dependency')
            now = utc_now()
            state['chapter_dependencies'].append(_record(ChapterDependency(
                id=dependency_id, project_id=project,
                predecessor_chapter_id=predecessor_id, successor_chapter_id=successor_id,
                kind=kind, note=note, enabled=enabled, archived=False, revision=1,
                created_at=now, updated_at=now)))
            self._operation(state, project, identity, 'create_dependency', 'dependency', dependency_id,
                            revision, request_hash)
            return state, _listing(state, state['revision'] + 1)
        return self.repository.atomic(project, operation,
                                      identity_claim=('full_book_planning_operations', 'operation_id', identity))

    def update_dependency(self, project, request):
        _fields(request, {'operation_id', 'expected_revision', 'dependency_id'},
                {'predecessor_chapter_id', 'successor_chapter_id', 'kind', 'note'})
        require(any(key in request for key in ('predecessor_chapter_id', 'successor_chapter_id', 'kind', 'note')),
                'full_book_planning.nothing_to_update')
        identity, revision, request_hash = _identity(request), _revision(request), _hash(request)
        dependency_id = uuid_value(request['dependency_id'])
        changes = {}
        for key in ('predecessor_chapter_id', 'successor_chapter_id'):
            if key in request:
                changes[key] = uuid_value(request[key])
        if 'kind' in request:
            require(type(request['kind']) is str and request['kind'] in DEPENDENCY_KINDS,
                    'full_book_planning.invalid_dependency_kind')
            changes['kind'] = request['kind']
        if 'note' in request:
            changes['note'] = _note(request['note'])

        def operation(state):
            upgrade(state)
            old = self._replay(state, identity, 'update_dependency', request_hash, dependency_id)
            if old:
                return None, _listing(state)
            self._check(state, revision)
            dependency = self._dependency(state, dependency_id)
            require(not dependency['archived'], 'full_book_planning.archived_dependency')
            predecessor = changes.get('predecessor_chapter_id', dependency['predecessor_chapter_id'])
            successor = changes.get('successor_chapter_id', dependency['successor_chapter_id'])
            kind = changes.get('kind', dependency['kind'])
            self._dependency_values(state, predecessor, successor, kind)
            require(all(value['id'] == dependency_id or value['archived'] or
                        (value['predecessor_chapter_id'], value['successor_chapter_id'], value['kind'])
                        != (predecessor, successor, kind) for value in state['chapter_dependencies']),
                    'full_book_planning.duplicate_dependency')
            dependency.update(changes)
            dependency['revision'] += 1
            dependency['updated_at'] = utc_now()
            self._operation(state, project, identity, 'update_dependency', 'dependency', dependency_id,
                            revision, request_hash)
            return state, _listing(state, state['revision'] + 1)
        return self.repository.atomic(project, operation,
                                      identity_claim=('full_book_planning_operations', 'operation_id', identity))

    def set_dependency_enabled(self, project, request):
        _fields(request, {'operation_id', 'expected_revision', 'dependency_id', 'enabled'})
        identity, revision, request_hash = _identity(request), _revision(request), _hash(request)
        dependency_id = uuid_value(request['dependency_id'])
        enabled = request['enabled']
        require(type(enabled) is bool, 'full_book_planning.invalid_dependency')

        def operation(state):
            upgrade(state)
            old = self._replay(state, identity, 'set_dependency_enabled', request_hash, dependency_id)
            if old:
                return None, _listing(state)
            self._check(state, revision)
            dependency = self._dependency(state, dependency_id)
            require(not dependency['archived'], 'full_book_planning.archived_dependency')
            dependency['enabled'] = enabled
            dependency['revision'] += 1
            dependency['updated_at'] = utc_now()
            self._operation(state, project, identity, 'set_dependency_enabled', 'dependency', dependency_id,
                            revision, request_hash)
            return state, _listing(state, state['revision'] + 1)
        return self.repository.atomic(project, operation,
                                      identity_claim=('full_book_planning_operations', 'operation_id', identity))

    def _set_dependency_archived(self, project, request, archived):
        action = 'archive_dependency' if archived else 'restore_dependency'
        _fields(request, {'operation_id', 'expected_revision', 'dependency_id'})
        identity, revision, request_hash = _identity(request), _revision(request), _hash(request)
        dependency_id = uuid_value(request['dependency_id'])

        def operation(state):
            upgrade(state)
            old = self._replay(state, identity, action, request_hash, dependency_id)
            if old:
                return None, _listing(state)
            self._check(state, revision)
            dependency = self._dependency(state, dependency_id)
            require(dependency['archived'] != archived, 'full_book_planning.invalid_dependency_state')
            dependency['archived'] = archived
            dependency['revision'] += 1
            dependency['updated_at'] = utc_now()
            self._operation(state, project, identity, action, 'dependency', dependency_id,
                            revision, request_hash)
            return state, _listing(state, state['revision'] + 1)
        return self.repository.atomic(project, operation,
                                      identity_claim=('full_book_planning_operations', 'operation_id', identity))

    def archive_dependency(self, project, request):
        return self._set_dependency_archived(project, request, True)

    def restore_dependency(self, project, request):
        return self._set_dependency_archived(project, request, False)

    def act(self, project, action, request):
        method = getattr(self, action, None) if action in ACTIONS else None
        if method is None:
            raise KeyError('全书规划操作不存在')
        return method(project, request)

    def update_arc(self, project, request):
        _fields(request, {'operation_id', 'expected_revision', 'arc_id'}, {'title', 'summary'})
        require('title' in request or 'summary' in request, 'full_book_planning.nothing_to_update')
        identity, revision, request_hash = _identity(request), _revision(request), _hash(request)
        arc_id = uuid_value(request['arc_id'])
        changes = {}
        if 'title' in request:
            changes['title'] = _title(request['title'])
        if 'summary' in request:
            changes['summary'] = _summary(request['summary'])

        def operation(state):
            upgrade(state)
            old = self._replay(state, identity, 'update_arc', request_hash, arc_id)
            if old:
                return None, _listing(state)
            self._check(state, revision)
            arc = self._active_arc(state, arc_id)
            arc.update(changes)
            arc['revision'] += 1
            arc['updated_at'] = utc_now()
            self._operation(state, project, identity, 'update_arc', 'arc', arc_id,
                            revision, request_hash)
            return state, _listing(state, state['revision'] + 1)
        return self.repository.atomic(project, operation,
                                      identity_claim=('full_book_planning_operations', 'operation_id', identity))

    def _set_arc_archived(self, project, request, archived):
        action = 'archive_arc' if archived else 'restore_arc'
        _fields(request, {'operation_id', 'expected_revision', 'arc_id'})
        identity, revision, request_hash = _identity(request), _revision(request), _hash(request)
        arc_id = uuid_value(request['arc_id'])

        def operation(state):
            upgrade(state)
            old = self._replay(state, identity, action, request_hash, arc_id)
            if old:
                return None, _listing(state)
            self._check(state, revision)
            arc = self._arc(state, arc_id)
            require(arc['archived'] != archived, 'full_book_planning.invalid_arc_state')
            arc['archived'] = archived
            arc['revision'] += 1
            arc['updated_at'] = utc_now()
            self._operation(state, project, identity, action, 'arc', arc_id,
                            revision, request_hash)
            return state, _listing(state, state['revision'] + 1)
        return self.repository.atomic(project, operation,
                                      identity_claim=('full_book_planning_operations', 'operation_id', identity))

    def archive_arc(self, project, request):
        return self._set_arc_archived(project, request, True)

    def restore_arc(self, project, request):
        return self._set_arc_archived(project, request, False)

    def create_stage(self, project, request):
        _fields(request, {'operation_id', 'expected_revision', 'arc_id', 'title'},
                {'summary', 'planned_chapter_id'})
        identity, revision, request_hash = _identity(request), _revision(request), _hash(request)
        stage_id = _uid(identity, 'stage')
        arc_id = uuid_value(request['arc_id'])
        title = _title(request['title'])
        summary = _summary(request.get('summary', ''))
        planned_chapter_id = _optional_id(request.get('planned_chapter_id'))

        def operation(state):
            upgrade(state)
            old = self._replay(state, identity, 'create_stage', request_hash, stage_id)
            if old:
                return None, _listing(state)
            self._check(state, revision)
            self._active_arc(state, arc_id)
            self._optional_chapter(state, planned_chapter_id)
            require(all(value['id'] != stage_id for value in state['character_arc_stages']),
                    'full_book_planning.identity_conflict')
            ordinal = max((value['ordinal'] for value in state['character_arc_stages']
                           if value['arc_id'] == arc_id), default=0) + 1
            now = utc_now()
            state['character_arc_stages'].append(_record(CharacterArcStage(
                id=stage_id, project_id=project, arc_id=arc_id, ordinal=ordinal, title=title,
                summary=summary, planned_chapter_id=planned_chapter_id, status='planned',
                occurred_chapter_id=None, body_reference='', revision=1,
                created_at=now, updated_at=now)))
            self._operation(state, project, identity, 'create_stage', 'stage', stage_id,
                            revision, request_hash)
            return state, _listing(state, state['revision'] + 1)
        return self.repository.atomic(project, operation,
                                      identity_claim=('full_book_planning_operations', 'operation_id', identity))
