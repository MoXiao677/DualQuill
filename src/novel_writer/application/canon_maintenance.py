"""Automatic canon synchronization after a chapter save.

The analyzer is deliberately injected by the existing model/task layer. This
module owns the JSON contract, quote checks, transactional application and
reversible audit trail; it never edits chapter prose.
"""

from copy import deepcopy
import inspect
import json
from uuid import uuid4

from novel_writer.application.fields import check_fields
from novel_writer.domain.canon_maintenance import COLLECTIONS, KINDS
from novel_writer.domain.models import utc_now
from novel_writer.domain.tasks import require, uuid_value
from novel_writer.storage.json_codec import strict_json_loads, document_from_dict, document_to_dict
from novel_writer.storage.sqlite_repository import ConflictError


_ANALYZER = None
KNOWN_FIELDS = {
    "outline": {"theme", "premise", "main_plot", "ending", "key_events", "summary", "objective", "core_idea", "story_time"},
    "character": {"name", "role", "personality", "background", "goals", "notes", "relationships", "position", "ability", "resource", "status", "known_information"},
    "foreshadow": {"status", "summary", "description", "target", "resolved"},
    "timeline": {"story_time", "event", "order", "date", "description"},
    "worldbuilding": {"content", "fact", "rule", "location", "culture"},
}


class CanonAnalysisError(ValueError):
    pass


def set_analyzer(analyzer):
    """Install the controlled model adapter used by automatic maintenance."""
    global _ANALYZER
    if analyzer is not None and not callable(analyzer):
        raise TypeError("analyzer must be callable or None")
    _ANALYZER = analyzer


def upgrade(state):
    """Add the optional V52 collections without changing legacy projects."""
    from novel_writer.application.migrations import upgrade_console_background
    upgrade_console_background(state)
    for name in COLLECTIONS:
        state.setdefault(name, [])


def enabled(state):
    entries = state.get("canon_maintenance_settings", [])
    return bool(entries and entries[-1]["enabled"])


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def prompt(state, chapter):
    request = {
        "instruction": "Analyze the saved chapter and return JSON only: {changes:[{kind,entity,field,before,after,quote}]}",
        "allowed_kinds": list(KINDS),
        "chapter": {"id": chapter["id"], "number": chapter["number"], "title": chapter["title"], "content": chapter["content"]},
        "canon": state.get("canon_maintenance_facts", []),
        "quote_rule": "quote must be an exact non-empty substring of chapter.content; never infer uncertain changes",
    }
    return _json(request)


def _parse(output, content):
    if type(output) is str:
        try:
            output = strict_json_loads(output)
        except Exception as exc:
            raise CanonAnalysisError(f"invalid_json:{exc}") from None
    if type(output) is not dict or set(output) != {"changes"} or type(output["changes"]) is not list:
        raise CanonAnalysisError("response must contain only a changes array")
    result = []
    identities = set()
    for index, change in enumerate(output["changes"]):
        if type(change) is not dict or set(change) != {"kind", "entity", "field", "before", "after", "quote"}:
            raise CanonAnalysisError(f"change[{index}] has an invalid schema")
        if change["kind"] not in KINDS or type(change["entity"]) is not str or not change["entity"]:
            raise CanonAnalysisError(f"change[{index}] has an invalid identity")
        if change["field"] not in KNOWN_FIELDS[change["kind"]]:
            raise CanonAnalysisError(f"change[{index}] field is not recognized")
        if type(change["quote"]) is not str or not change["quote"] or change["quote"] not in content:
            raise CanonAnalysisError(f"change[{index}] quote is not an exact chapter quote")
        identity = (change["kind"], change["entity"], change["field"])
        if identity in identities:
            raise CanonAnalysisError(f"change[{index}] duplicates an earlier field")
        identities.add(identity)
        result.append(deepcopy(change))
    return result


def _formal_value(state, change):
    kind, entity, field = change["kind"], change["entity"], change["field"]
    doc = state["document"]
    if kind == "outline":
        outline = doc.get("book_outline")
        if outline is not None and entity in ("book", "book_outline", outline["id"]):
            return outline.get(field)
        outline = next((o for o in doc["chapter_outlines"] if o["chapter_id"] == entity or o["id"] == entity), None)
        chapter = next((c for c in doc["chapters"] if c["id"] == entity or (outline is not None and c["id"] == outline["chapter_id"])), None)
        if chapter is not None and outline is not None:
            return outline.get(field)
    elif kind == "character":
        target = next((c for c in doc["characters"] if c["id"] == entity), None)
        if target is not None and field in target:
            return target[field]
    elif kind == "worldbuilding" and field == "content":
        return state.get("worldbuilding", "")
    return None


def _current(state, change):
    for fact in state.get("canon_maintenance_facts", []):
        if (fact["kind"], fact["entity"], fact["field"]) == (change["kind"], change["entity"], change["field"]):
            return fact["value"]
    return _formal_value(state, change)


def _snapshot(state):
    document = state["document"]
    return {"book_outline": deepcopy(document.get("book_outline")),
            "chapter_outlines": deepcopy(document.get("chapter_outlines", [])),
            "characters": deepcopy(document.get("characters", [])),
            "worldbuilding": state.get("worldbuilding", ""),
            "facts": deepcopy(state.get("canon_maintenance_facts", []))}


def _event(project_id, chapter_id, revision, *, kind, status, operation_id, entity=None, field=None,
           before=None, after=None, quote="", error=""):
    return dict(id=str(uuid4()), project_id=project_id, kind=kind, status=status, chapter_id=chapter_id,
                source_revision=revision, operation_id=operation_id, entity=entity, field=field,
                before=deepcopy(before), after=deepcopy(after), quote=quote, error=error, created_at=utc_now())


def _apply_formal(state, change):
    kind, entity, field, after = change["kind"], change["entity"], change["field"], change["after"]
    document = document_from_dict(state["document"])
    if kind == "outline" and field in {"theme", "premise", "main_plot", "ending", "key_events"} and entity in ("book", "book_outline"):
        from novel_writer.application.book_outlines import save
        save(document, {field: after})
    elif kind == "outline" and field in {"objective", "core_idea", "story_time"}:
        from novel_writer.application.chapter_outlines import save
        outline = next((item for item in document.chapter_outlines if item.id == entity or item.chapter_id == entity), None)
        chapter_id = outline.chapter_id if outline is not None else entity
        if any(c.id == chapter_id for c in document.chapters):
            save(document, {"chapter_id": chapter_id, field: after})
    elif kind == "character" and field in {"name", "role", "personality", "background", "notes", "goals", "relationships"}:
        from novel_writer.application.characters import save
        if any(c.id == entity for c in document.characters):
            save(document, {"character_id": entity, field: after})
    elif kind == "worldbuilding" and field == "content" and type(after) is str:
        from novel_writer.application.worldbuilding import save
        save(state, {"content": after})
    else:
        return
    state["document"] = document_to_dict(document)


def _upsert_fact(state, change, chapter_id, revision):
    existing = next((item for item in state["canon_maintenance_facts"]
                     if (item["kind"], item["entity"], item["field"]) == (change["kind"], change["entity"], change["field"])), None)
    value = dict(project_id=state["document"]["project"]["id"], kind=change["kind"], entity=change["entity"],
                 field=change["field"], value=deepcopy(change["after"]), chapter_id=chapter_id,
                 source_revision=revision, quote=change["quote"], updated_at=utc_now())
    if existing is None:
        state["canon_maintenance_facts"].append(dict(id=str(uuid4()), **value))
    else:
        existing.update(value)


def _invoke_analyzer(state, chapter, output):
    if output is not None:
        return output
    if _ANALYZER is None:
        raise CanonAnalysisError("analyzer_unavailable")
    request = prompt(state, chapter)
    context = {"project_id": state["document"]["project"]["id"], "chapter_id": chapter["id"], "source_revision": state["revision"] + 1}
    try:
        signature = inspect.signature(_ANALYZER)
        return _ANALYZER(request, context) if len(signature.parameters) >= 2 else _ANALYZER(request)
    except (ValueError, TypeError):
        return _ANALYZER(request)


def apply(state, previous, chapter_id, output=None):
    target = state
    state = deepcopy(state)
    chapter = next((item for item in state["document"]["chapters"] if item["id"] == chapter_id), None)
    if chapter is None:
        raise CanonAnalysisError("chapter_not_found")
    revision = previous["revision"] + 1
    operation_id = str(uuid4())
    changes = _parse(_invoke_analyzer(state, chapter, output), chapter["content"])
    before = _snapshot(previous)
    events = [_event(state["document"]["project"]["id"], chapter_id, revision, kind="analysis", status="synced",
                     operation_id=operation_id, after={"change_count": len(changes)})]
    for change in changes:
        current = _current(state, change)
        expected = change["before"]
        if not ((current == expected) or (current == "" and expected is None)):
            raise CanonAnalysisError(f"change_before_mismatch:{change['kind']}:{change['entity']}:{change['field']}")
    for change in changes:
        _apply_formal(state, change)
        _upsert_fact(state, change, chapter_id, revision)
        events.append(_event(state["document"]["project"]["id"], chapter_id, revision, kind="change", status="synced",
                             operation_id=operation_id, entity=change["entity"], field=change["field"],
                             before=_current(previous, change), after=change["after"], quote=change["quote"]))
    state["canon_maintenance_events"].extend(events)
    after = _snapshot(state)
    state["canon_maintenance_checkpoints"].append(dict(id=str(uuid4()), project_id=state["document"]["project"]["id"],
        chapter_id=chapter_id, source_revision=revision, before=before, after=after,
        event_ids=[event["id"] for event in events], created_at=utc_now()))
    target.clear(); target.update(state)
    return target


def on_chapter_saved(previous, state, chapter_id, output=None):
    if "canon_maintenance_settings" not in state:
        # A controlled analyzer or an explicit frozen response opts a book
        # into the default-on policy on its first saved chapter. Plain legacy
        # saves remain byte-for-byte compatible until the model layer is used.
        if _ANALYZER is None and output is None:
            return state
        upgrade(state)
        state["canon_maintenance_settings"].append(dict(
            id=str(uuid4()), project_id=state["document"]["project"]["id"],
            operation_id=str(uuid4()), enabled=True, auto_authorized=True, created_at=utc_now()))
    if not enabled(state):
        return state
    try:
        return apply(state, previous, chapter_id, output)
    except Exception as exc:
        state["canon_maintenance_events"].append(_event(
            state["document"]["project"]["id"], chapter_id, previous["revision"] + 1,
            kind="failure", status="failed", operation_id=str(uuid4()), error=str(exc) or type(exc).__name__))
        return state


class CanonMaintenance:
    def __init__(self, service):
        self.service = service

    def set_analyzer(self, analyzer):
        set_analyzer(analyzer)

    def listing(self, project_id):
        state = self.service.get(project_id)
        settings = state.get("canon_maintenance_settings", [])
        return {"revision": state["revision"], "enabled": enabled(state), "settings": deepcopy(settings),
                "facts": deepcopy(state.get("canon_maintenance_facts", [])),
                "events": deepcopy(state.get("canon_maintenance_events", [])),
                "checkpoints": deepcopy(state.get("canon_maintenance_checkpoints", [])),
                "sync_status": "failed" if state.get("canon_maintenance_events", []) and state["canon_maintenance_events"][-1]["status"] == "failed" else "synced"}

    def configure(self, project_id, request):
        check_fields(request, {"operation_id", "enabled", "expected_revision"})
        require(set(request) == {"operation_id", "enabled", "expected_revision"} and type(request["enabled"]) is bool, "canon.invalid_policy")
        uuid_value(request["operation_id"])
        def operation(state):
            previous = next((item for item in state.get("canon_maintenance_events", [])
                             if item["operation_id"] == request["operation_id"] and item["kind"] == "rollback"), None)
            if previous is not None:
                checkpoint_id = (previous.get("after") or {}).get("checkpoint_id")
                return None, {"status": "rolled_back", "checkpoint_id": checkpoint_id,
                              "revision": state["revision"], "idempotent": True}
            if state["revision"] != request["expected_revision"]:
                raise ConflictError("canon policy revision conflict")
            upgrade(state)
            if any(item["operation_id"] == request["operation_id"] for item in state["canon_maintenance_settings"]):
                return state, {"revision": state["revision"], "enabled": enabled(state), "idempotent": True}
            state["canon_maintenance_settings"].append(dict(id=str(uuid4()), project_id=project_id,
                operation_id=request["operation_id"], enabled=request["enabled"], auto_authorized=True, created_at=utc_now()))
            return state, {"revision": state["revision"] + 1, "enabled": request["enabled"]}
        return self.service.repository.atomic(project_id, operation,
                                              identity_claim=("canon_maintenance_settings", "operation_id", request["operation_id"]))

    def rollback(self, project_id, request):
        check_fields(request, {"operation_id", "chapter_id", "expected_revision", "checkpoint_id"})
        require(set(request) in (
            {"operation_id", "chapter_id", "expected_revision"},
            {"operation_id", "chapter_id", "checkpoint_id", "expected_revision"},
            {"operation_id", "checkpoint_id", "expected_revision"},
        ), "canon.invalid_rollback")
        uuid_value(request["operation_id"])
        def operation(state):
            if state["revision"] != request["expected_revision"]:
                raise ConflictError("canon rollback revision conflict")
            checkpoint = next((item for item in reversed(state.get("canon_maintenance_checkpoints", []))
                               if ("checkpoint_id" in request and item["id"] == request["checkpoint_id"])
                               or ("checkpoint_id" not in request and "chapter_id" in request and item["chapter_id"] == request["chapter_id"])), None)
            require(checkpoint is not None, "canon.checkpoint_not_found")
            snapshot = deepcopy(checkpoint["before"])
            document = state["document"]
            if snapshot["book_outline"] is None and document.get("book_outline") is not None:
                # Version history is append-only, so retain an entity created
                # by an automatic update while restoring its editable fields.
                outline = document["book_outline"]
                outline.update(theme="", premise="", main_plot="", ending="", key_events=[], volumes=[])
            else:
                document["book_outline"] = snapshot["book_outline"]
            if not snapshot["chapter_outlines"] and document.get("chapter_outlines"):
                for outline in document["chapter_outlines"]:
                    outline.update(core_idea="", objective="", character_ids=[], scenes=[], story_time="")
            else:
                document["chapter_outlines"] = snapshot["chapter_outlines"]
            document["characters"] = snapshot["characters"]
            state["worldbuilding"] = snapshot["worldbuilding"]
            state["canon_maintenance_facts"] = snapshot["facts"]
            rollback_chapter_id = request.get("chapter_id", checkpoint["chapter_id"])
            state["canon_maintenance_events"].append(_event(project_id, rollback_chapter_id, state["revision"] + 1,
                kind="rollback", status="rolled_back", operation_id=request["operation_id"], after={"checkpoint_id": checkpoint["id"]}))
            return state, {"status": "rolled_back", "checkpoint_id": checkpoint["id"], "revision": state["revision"] + 1}
        return self.service.repository.atomic(project_id, operation,
                                              identity_claim=("canon_maintenance_events", "operation_id", request["operation_id"]))

