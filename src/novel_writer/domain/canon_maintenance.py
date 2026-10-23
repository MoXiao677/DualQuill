"""Validation rules for automatic, reversible canon maintenance records."""

from novel_writer.domain.models import _timestamp
from novel_writer.domain.tasks import require, uuid_value


COLLECTIONS = (
    "canon_maintenance_settings",
    "canon_maintenance_facts",
    "canon_maintenance_events",
    "canon_maintenance_checkpoints",
)
KINDS = ("outline", "character", "foreshadow", "timeline", "worldbuilding")
EVENT_KINDS = ("policy", "analysis", "change", "failure", "rollback")
EVENT_STATUSES = ("enabled", "disabled", "synced", "failed", "rolled_back")


def _json_value(value, path):
    if type(value) in (str, int, float, bool, type(None)):
        require(not (type(value) is float and value != value), path)
        return
    if type(value) is list:
        for index, item in enumerate(value):
            _json_value(item, f"{path}[{index}]")
        return
    if type(value) is dict:
        require(all(type(key) is str for key in value), path)
        for key, item in value.items():
            _json_value(item, f"{path}.{key}")
        return
    raise ValueError(path)


def validate_state(state):
    settings = state.get(COLLECTIONS[0], [])
    facts = state.get(COLLECTIONS[1], [])
    events = state.get(COLLECTIONS[2], [])
    checkpoints = state.get(COLLECTIONS[3], [])
    project_id = state["document"]["project"]["id"]
    require(type(settings) is list and type(facts) is list and type(events) is list and type(checkpoints) is list,
            "canon.collections")
    setting_ids, operations = set(), set()
    for item in settings:
        require(type(item) is dict and set(item) == {"id", "project_id", "operation_id", "enabled", "auto_authorized", "created_at"}, "canon.setting_fields")
        uuid_value(item["id"]); uuid_value(item["operation_id"])
        require(item["project_id"] == project_id and type(item["enabled"]) is bool and item["auto_authorized"] is True, "canon.setting_value")
        require(item["id"] not in setting_ids and item["operation_id"] not in operations, "canon.setting_duplicate")
        setting_ids.add(item["id"]); operations.add(item["operation_id"]); _timestamp(item["created_at"], "canon.created_at")
    fact_ids = set()
    for item in facts:
        require(type(item) is dict and set(item) == {"id", "project_id", "kind", "entity", "field", "value", "chapter_id", "source_revision", "quote", "updated_at"}, "canon.fact_fields")
        uuid_value(item["id"]); require(item["project_id"] == project_id and item["kind"] in KINDS, "canon.fact_value")
        require(type(item["entity"]) is str and item["entity"] and type(item["field"]) is str and item["field"], "canon.fact_identity")
        require(item["chapter_id"] in {c["id"] for c in state["document"]["chapters"]}, "canon.fact_chapter")
        require(type(item["source_revision"]) is int and item["source_revision"] >= 1 and type(item["quote"]) is str and item["quote"], "canon.fact_source")
        _json_value(item["value"], "canon.fact.value"); _timestamp(item["updated_at"], "canon.updated_at")
        require(item["id"] not in fact_ids, "canon.fact_duplicate"); fact_ids.add(item["id"])
    event_ids = set()
    for item in events:
        require(type(item) is dict and set(item) == {"id", "project_id", "kind", "status", "chapter_id", "source_revision", "operation_id", "entity", "field", "before", "after", "quote", "error", "created_at"}, "canon.event_fields")
        uuid_value(item["id"]); uuid_value(item["operation_id"])
        require(item["project_id"] == project_id and item["kind"] in EVENT_KINDS and item["status"] in EVENT_STATUSES, "canon.event_value")
        require(item["chapter_id"] in {c["id"] for c in state["document"]["chapters"]}, "canon.event_chapter")
        require(type(item["source_revision"]) is int and item["source_revision"] >= 1, "canon.event_revision")
        require(item["entity"] is None or type(item["entity"]) is str, "canon.event_entity")
        require(item["field"] is None or type(item["field"]) is str, "canon.event_field")
        require(type(item["quote"]) is str and type(item["error"]) is str, "canon.event_text")
        _json_value(item["before"], "canon.event.before"); _json_value(item["after"], "canon.event.after")
        _timestamp(item["created_at"], "canon.event.created_at")
        require(item["id"] not in event_ids, "canon.event_duplicate"); event_ids.add(item["id"])
    checkpoint_ids = set()
    for item in checkpoints:
        require(type(item) is dict and set(item) == {"id", "project_id", "chapter_id", "source_revision", "before", "after", "event_ids", "created_at"}, "canon.checkpoint_fields")
        uuid_value(item["id"]); require(item["project_id"] == project_id and item["chapter_id"] in {c["id"] for c in state["document"]["chapters"]}, "canon.checkpoint_ref")
        require(type(item["source_revision"]) is int and item["source_revision"] >= 1 and type(item["event_ids"]) is list, "canon.checkpoint_value")
        require(all(identifier in event_ids for identifier in item["event_ids"]), "canon.checkpoint_events")
        _json_value(item["before"], "canon.checkpoint.before"); _json_value(item["after"], "canon.checkpoint.after")
        _timestamp(item["created_at"], "canon.checkpoint.created_at")
        require(item["id"] not in checkpoint_ids, "canon.checkpoint_duplicate"); checkpoint_ids.add(item["id"])


def validate_transition(state, previous):
    validate_state(state)
    for name in ("canon_maintenance_settings", "canon_maintenance_events", "canon_maintenance_checkpoints"):
        old = previous.get(name, [])
        require(state[name][:len(old)] == old, "canon.append_only")
