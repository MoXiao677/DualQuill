"""V47 frozen model-planning records. Model output is never a formal plan."""
from dataclasses import dataclass
from typing import Literal

from novel_writer.domain.chapter_planning import Value, PlanningBinding, PlanningEvent, PlanningResult, PlanningCandidate
from novel_writer.domain.book_creation import fingerprint
from novel_writer.domain.tasks import parse, require, uuid_value, digest


@dataclass(frozen=True, kw_only=True)
class ModelPlanningBinding(PlanningBinding):
    adapter_id: Literal['body-planning-http-v1']
    prompt_version: Literal['body-planning-json-1']


@dataclass(frozen=True, kw_only=True)
class ModelPlanningTask(Value):
    id: str
    project_id: str
    request_id: str
    preparation_sha256: str
    owner_id: str
    chapter_id: str
    source_revision: int
    prepared_revision: int
    source_options: dict
    source_guard: dict
    source_sha256: str
    original_source_json: str
    original_source_sha256: str
    binding: ModelPlanningBinding
    budget_max_calls: int
    budget_max_output_tokens: int
    budget_sha256: str
    max_output_chars: int
    timeout_ms: int
    created_at: str

    def __post_init__(self):
        super().__post_init__()
        uuid_value(self.request_id); uuid_value(self.owner_id)
        require(self.source_revision >= 1 and self.prepared_revision == self.source_revision + 1, 'model_planning.invalid_revision')
        require(self.source_sha256 == fingerprint(self.source_guard) and self.original_source_sha256 == digest(self.original_source_json), 'model_planning.invalid_source')
        require(self.chapter_id == self.source_options.get('chapter_id') == self.source_guard['chapter']['id'], 'model_planning.invalid_chapter')
        require(1 <= self.budget_max_calls <= 10 and 128 <= self.budget_max_output_tokens <= 81920, 'model_planning.invalid_budget')
        require(128 <= self.max_output_chars <= 100000 and 100 <= self.timeout_ms <= 300000, 'model_planning.invalid_limits')
        require(self.budget_sha256 == fingerprint(dict(budget=dict(max_external_calls=self.budget_max_calls,
            max_reserved_output_tokens=self.budget_max_output_tokens), request_sha256=self.binding.request_sha256,
            max_output_chars=self.max_output_chars, timeout_ms=self.timeout_ms, budget_limit=self.binding.budget_limit)), 'model_planning.invalid_budget_hash')
        require(self.budget_max_output_tokens >= self.binding.max_tokens, 'model_planning.insufficient_budget')


@dataclass(frozen=True, kw_only=True)
class ModelPlanningCall:
    task_id: str
    attempt_id: str
    capability: Literal['body_planning']
    task: ModelPlanningTask
    request_sha256: str
    confirmed: bool

    def __post_init__(self):
        require(type(self.task) is ModelPlanningTask and self.task_id == self.task.id and self.confirmed is True,
                'model_planning.invalid_call')
        self.task.__post_init__(); uuid_value(self.attempt_id)
        require(self.capability == 'body_planning' and self.request_sha256 == self.task.binding.request_sha256, 'model_planning.invalid_call')


@dataclass(frozen=True, kw_only=True)
class ModelPlanningLink(Value):
    id: str
    project_id: str
    operation_id: str
    task_id: str
    candidate_id: str
    suggestion_index: int
    proposal_id: str
    request_sha256: str
    created_at: str

    def __post_init__(self):
        super().__post_init__()
        for v in (self.operation_id, self.task_id, self.candidate_id, self.proposal_id): uuid_value(v)
        require(0 <= self.suggestion_index < 20, 'model_planning.invalid_index')


COLLECTIONS = {'model_planning_tasks': ModelPlanningTask, 'model_planning_events': PlanningEvent,
               'model_planning_results': PlanningResult, 'model_planning_candidates': PlanningCandidate,
               'model_planning_links': ModelPlanningLink}


def validate_state(state):
    if state.get('workspace_version', 0) < 47:
        require(not any(k in state for k in COLLECTIONS), 'model_planning.requires_v37'); return
    parsed = {}
    project = state['document']['project']['id']
    for name, model in COLLECTIONS.items():
        require(type(state[name]) is list and len(state[name]) <= 30000, 'model_planning.invalid_collection')
        parsed[name] = [parse(model,v) for v in state[name]]
        require(len({v.id for v in parsed[name]}) == len(parsed[name]), 'model_planning.duplicate_id')
        for value in parsed[name]:
            if hasattr(value,'project_id'): require(value.project_id == project, 'model_planning.cross_project')
    tasks = {t.id:t for t in parsed['model_planning_tasks']}
    require(len({t.request_id for t in tasks.values()}) == len(tasks), 'model_planning.duplicate_request')
    chapters = {c['id'] for c in state['document']['chapters']}
    versions = {v['id']:v for v in state['document']['versions']}
    for task in tasks.values():
        source = task.source_guard['source']; version = versions.get(source['version_id'])
        require(task.chapter_id in chapters and version is not None and version['entity_id'] == task.chapter_id
                and version['entity_type'] == 'chapter' and version['snapshot']['content'] == task.source_guard['chapter']['content'], 'model_planning.saved_body_missing')
    last = {}; attempts = {}
    for event in parsed['model_planning_events']:
        require(event.task_id in tasks and event.previous_event_id == (last[event.task_id].id if event.task_id in last else None), 'model_planning.event_chain')
        if event.task_id not in last: require(event.kind == 'prepared' and event.status == 'pending', 'model_planning.first_event')
        if event.kind == 'started':
            require(last[event.task_id].status == 'pending' and event.task_id not in attempts and event.attempt_id is not None, 'model_planning.duplicate_send')
            attempts[event.task_id] = event.attempt_id
        if event.kind == 'prepared': require(event.task_id not in last and event.attempt_id is None, 'model_planning.duplicate_prepare')
        elif event.kind == 'completed':
            require(last[event.task_id].status == 'running' and event.status in ('succeeded','failed','cancelled','interrupted'), 'model_planning.terminal_chain')
        elif event.kind == 'cancelled': require(last[event.task_id].status in ('pending','running') and event.status == 'cancelled', 'model_planning.cancel_chain')
        elif event.kind == 'response_recorded': require(last[event.task_id].status in ('failed','cancelled','interrupted') and event.status == last[event.task_id].status and event.candidate_id is None, 'model_planning.late_chain')
        else: require(event.kind == 'started' and event.status == 'running', 'model_planning.invalid_event')
        if event.task_id in attempts: require(event.attempt_id == attempts[event.task_id], 'model_planning.attempt_mismatch')
        last[event.task_id] = event
    require(set(last) == set(tasks), 'model_planning.missing_event')
    results = {r.id:r for r in parsed['model_planning_results']}
    require(len({r.task_id for r in results.values()}) == len(results), 'model_planning.duplicate_result')
    for result in results.values():
        require(result.task_id in tasks and result.attempt_id == attempts.get(result.task_id), 'model_planning.response_mismatch')
    candidates = {c.id:c for c in parsed['model_planning_candidates']}
    require(len({c.task_id for c in candidates.values()}) == len(candidates), 'model_planning.duplicate_candidate')
    for candidate in candidates.values():
        result = results.get(candidate.response_id)
        require(candidate.task_id in tasks and result is not None and result.task_id == candidate.task_id
                and result.response.complete and candidate.raw_text == result.response.output_text, 'model_planning.candidate_response_mismatch')
        require(candidate.origin == 'model' and candidate.revision == 1 and candidate.previous_candidate_id is None, 'model_planning.model_only_candidate')
        require(candidate.plan is not None and not candidate.errors and last[candidate.task_id].status == 'succeeded'
                and last[candidate.task_id].candidate_id == candidate.id, 'model_planning.invalid_candidate_status')
        if candidate.plan is not None:
            body = tasks[candidate.task_id].source_guard['chapter']['content']
            suggestions = candidate.plan.get('suggestions')
            require(type(suggestions) is list and 1 <= len(suggestions) <= 20, 'model_planning.invalid_suggestions')
            for suggestion in suggestions:
                start,end,quote=suggestion['start'],suggestion['end'],suggestion['quote']
                require(type(start) is int and type(end) is int and type(quote) is str and 0 <= start < end <= len(body)
                        and 0 < len(quote) <= 4000 and body[start:end] == quote, 'model_planning.invalid_quote')
    seen = set(); proposals = {p['id']:p for p in state.get('body_planning_proposals',[])}
    require(len({v.operation_id for v in parsed['model_planning_links']}) == len(parsed['model_planning_links'])
            and len({v.proposal_id for v in parsed['model_planning_links']}) == len(parsed['model_planning_links']), 'model_planning.duplicate_link_identity')
    for link in parsed['model_planning_links']:
        candidate=candidates.get(link.candidate_id)
        require(candidate is not None and candidate.task_id == link.task_id and candidate.plan is not None
                and 0 <= link.suggestion_index < len(candidate.plan['suggestions']) and link.proposal_id in proposals, 'model_planning.link_mismatch')
        key=(link.candidate_id,link.suggestion_index);require(key not in seen,'model_planning.suggestion_already_linked');seen.add(key)
        suggestion = candidate.plan['suggestions'][link.suggestion_index]; proposal = proposals[link.proposal_id]
        require(proposal['origin'] == 'ai_import' and proposal['source']['entity_id'] == tasks[link.task_id].chapter_id
                and all(proposal[k] == suggestion[k] for k in ('start','end','quote','reason','actions')), 'model_planning.proposal_content_mismatch')
    for event in parsed['model_planning_events']:
        if event.response_id is not None: require(event.response_id in results and results[event.response_id].task_id == event.task_id, 'model_planning.event_response_mismatch')
        if event.candidate_id is not None: require(event.candidate_id in candidates and candidates[event.candidate_id].task_id == event.task_id, 'model_planning.event_candidate_mismatch')


def validate_transition(state, previous):
    for name in COLLECTIONS:
        before=previous.get(name,[])
        require(state.get(name,[])[:len(before)] == before, 'model_planning.append_only')
    for link in state.get('model_planning_links', [])[len(previous.get('model_planning_links', [])):]:
        require(any(c['id'] == link['candidate_id'] for c in previous.get('model_planning_candidates', [])), 'model_planning.requires_saved_candidate')
    for receipt in state.get('body_planning_receipts', [])[len(previous.get('body_planning_receipts', [])):]:
        link = next((v for v in previous.get('model_planning_links', []) if v['proposal_id'] == receipt['proposal_id']), None)
        if link is not None and receipt['decision'] == 'accepted':
            # Rebuild only in-memory source; this validates rules/lifecycle as well as formal plans.
            task = next(v for v in previous['model_planning_tasks'] if v['id'] == link['task_id'])
            names = ('document','ideas','worldbuilding','writing_rules','character_arcs','character_arc_stages','key_events',
                'chapter_dependencies','chapter_lifecycle_events','chapter_trash_events','planning_locks','book_creation_locks',
                'body_planning_locks','planning_entity_lifecycle','knowledge_nodes','knowledge_edges','memories')
            current = {k:previous.get(k, [] if k not in ('worldbuilding','writing_rules') else '') for k in names}
            require(fingerprint(current) == task['source_guard']['formal_sha256']
                and fingerprint(previous.get('scoped_rules', [])) == task['source_guard']['all_scoped_rules_sha256'], 'model_planning.source_changed_before_accept')
