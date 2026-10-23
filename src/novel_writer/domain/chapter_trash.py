"""V27 append-only chapter trash/restore markers with no physical deletion."""
from dataclasses import dataclass
from typing import Literal

from novel_writer.domain.chapter_lifecycle import archived_ids
from novel_writer.domain.models import _timestamp
from novel_writer.domain.tasks import check_types, encode, parse, require, uuid_value


def _optional_uuid(value):
    if value is not None:
        uuid_value(value)


class Value:
    def __post_init__(self):
        check_types(type(self), self)
        uuid_value(self.id)
        uuid_value(self.operation_id)
        require(bool(self.chapter_id.strip()), 'chapter_trash.invalid_chapter')
        require(type(self.project_id) is str and bool(self.project_id.strip()),
                'chapter_trash.invalid_project')
        _timestamp(self.created_at, 'chapter_trash.created_at')


@dataclass(frozen=True, kw_only=True)
class TrashEvent(Value):
    id: str
    project_id: str
    operation_id: str
    chapter_id: str
    kind: Literal['trash', 'restore']
    title_snapshot: str
    original_volume_number: int | None
    original_position: int | None
    original_number: int
    request_sha256: str
    trash_event_id: str | None
    created_at: str

    def __post_init__(self):
        super().__post_init__()
        require(self.kind in ('trash', 'restore'), 'chapter_trash.invalid_kind')
        require(type(self.title_snapshot) is str and 0 < len(self.title_snapshot) <= 300
                and self.title_snapshot == self.title_snapshot.strip()
                and '\x00' not in self.title_snapshot, 'chapter_trash.invalid_title')
        require(type(self.original_number) is int and self.original_number >= 1,
                'chapter_trash.invalid_number')
        require(self.original_volume_number is None
                or type(self.original_volume_number) is int and self.original_volume_number >= 1,
                'chapter_trash.invalid_volume')
        require((self.original_volume_number is None) == (self.original_position is None),
                'chapter_trash.invalid_position')
        require(self.original_position is None
                or type(self.original_position) is int and self.original_position >= 0,
                'chapter_trash.invalid_position')
        require(type(self.request_sha256) is str and len(self.request_sha256) == 64
                and all(char in '0123456789abcdef' for char in self.request_sha256),
                'chapter_trash.invalid_request_sha256')
        _optional_uuid(self.trash_event_id)
        require((self.kind == 'trash') == (self.trash_event_id is None),
                'chapter_trash.invalid_link')


COLLECTIONS = {'chapter_trash_events': TrashEvent}


def latest_event(state, chapter_id):
    return next((value for value in reversed(state.get('chapter_trash_events', []))
                 if value['chapter_id'] == chapter_id), None)


def is_trashed(state, chapter_id):
    event = latest_event(state, chapter_id)
    return event is not None and event['kind'] == 'trash'


def trashed_ids(state):
    return {event['chapter_id'] for event in state.get('chapter_trash_events', [])
            if is_trashed(state, event['chapter_id'])}


def hidden_ids(state):
    return archived_ids(state) | trashed_ids(state)


def is_hidden(state, chapter_id):
    return chapter_id in hidden_ids(state)


def event_for_operation(state, operation_id):
    return next((value for value in state.get('chapter_trash_events', [])
                 if value['operation_id'] == operation_id), None)


def validate_state(state):
    if state.get('workspace_version', 0) < 27:
        require('chapter_trash_events' not in state, 'chapter_trash.require_v27')
        return
    project = state['document']['project']['id']
    chapters = {value['id'] for value in state['document']['chapters']}
    events = state.get('chapter_trash_events', [])
    require(type(events) is list and len(events) <= 100000, 'chapter_trash.invalid_collection')
    identifiers, operations, by_chapter = set(), set(), {}
    for raw in events:
        value = parse(TrashEvent, raw)
        require(value.id not in identifiers and value.operation_id not in operations,
                'chapter_trash.duplicate_identity')
        require(value.project_id == project and value.chapter_id in chapters,
                'chapter_trash.orphan_event')
        identifiers.add(value.id)
        operations.add(value.operation_id)
        by_chapter.setdefault(value.chapter_id, []).append(value)
    for chapter_id, values in by_chapter.items():
        expected = 'trash'
        latest_trash = None
        for value in values:
            require(value.kind == expected, 'chapter_trash.invalid_sequence')
            if value.kind == 'trash':
                latest_trash = value.id
                expected = 'restore'
            else:
                require(value.trash_event_id == latest_trash, 'chapter_trash.invalid_link')
                latest_trash = None
                expected = 'trash'


def validate_transition(state, previous):
    validate_state(state)
    old = (previous or {}).get('chapter_trash_events', [])
    require(state['chapter_trash_events'][:len(old)] == old,
            'chapter_trash.history_append_only')
