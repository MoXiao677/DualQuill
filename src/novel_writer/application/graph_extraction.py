"""Explicit saved chapters -> single budgeted request -> quoted proposal -> author decision."""
from copy import deepcopy
from uuid import uuid5, NAMESPACE_URL
from novel_writer.application.fields import check_fields
from novel_writer.domain.graph_extraction import *
from novel_writer.domain.tasks import digest, uuid_value
from novel_writer.domain.models import utc_now


def upgrade(state):
    from novel_writer.application.chapter_lifecycle import upgrade as prior
    prior(state)
    state.setdefault('rule_task_bindings', [])
    state.setdefault('deep_review_actions', [])
    state.setdefault('memory_automation_events', [])
    from novel_writer.domain.body_planning import COLLECTIONS as BODY_PLANNING_COLLECTIONS
    for name in BODY_PLANNING_COLLECTIONS:state.setdefault(name, [])
    state['workspace_version'] = max(state['workspace_version'], 45)
    for name in COLLECTIONS:
        state.setdefault(name, [])


def prepare(coordinator, project, request):
    fields = {'request_id', 'chapter_id', 'selected_chapter_ids', 'expected_revision', 'instruction', 'max_output_chars', 'timeout_ms', 'model_options'}
    check_fields(request, fields)
    require(set(request) == fields, '图谱抽取准备字段缺失')
    require(type(request['model_options']) is dict and request['model_options'].get('prompt_version') == PROMPT, '图谱抽取须使用专用提示版本')
    selected = request['selected_chapter_ids']
    require(type(selected) is list and 1 <= len(selected) <= 8 and all(type(v) is str for v in selected) and len(selected) == len(set(selected)) and request['chapter_id'] in selected, '图谱抽取须明确选择1至8个不重复章节，包含截至章')
    options = dict(chapter_id=request['chapter_id'], scope='previous', budget_chars=128, include_current_plan=False,
                   include_book_outline=False, include_characters=False, include_worldbuilding=False,
                   include_writing_rules=False, include_memories=False, include_search_results=False)
    rules = dict(version='offline-audit-1', forbidden_literals=[], required_literals=[], normalization='whitespace',
                 near_threshold=.9, minimum_fragment_chars=12, check_timeline=False)
    parameters = {k: request[k] for k in ('instruction', 'max_output_chars', 'timeout_ms')}
    parameters.update(rules=rules, selected_chapter_ids=selected, previous_report_id=None)
    return coordinator.prepare(project, dict(request_id=request['request_id'], chapter_id=request['chapter_id'],
                task_type='audit_chapter', context_options=options, context_sha256=digest(''), parameters=parameters,
                expected_revision=request['expected_revision'], model_options=request['model_options']))


def assert_fresh(coordinator, state, task):
    if not is_graph(task):
        return
    from novel_writer.application.reviews import assert_fresh as review_fresh
    from novel_writer.application.chapter_lifecycle import is_hidden
    from novel_writer.application.scoped_rules import require_fresh_rules
    coordinator.registry.validate_preparation(task)
    require_fresh_rules(state, task)
    require(all(not is_hidden(state, s.entity_id) for s in task.frozen.parameters.sources), '图谱来源已归档/回收')
    review_fresh(coordinator, state, task)


def persist(state, task, output, response_id, now):
    state['graph_extractions'].append(encode(Extraction(id=str(uuid5(NAMESPACE_URL, task.id + '/graph-extraction')),
        project_id=task.project_id, task_id=task.id, response_record_id=response_id, output=output, created_at=now)))


def describe(coordinator, project, options):
    check_fields(options, {'chapter_id'})
    state = coordinator.service.get(project)
    positions = {c['id']: c['number'] for c in state['document']['chapters']}
    cap = options.get('chapter_id')
    require(cap is None or cap in positions, '图谱提案截至章不属于本书')
    results = []
    for e in state.get('graph_extractions', []):
        task = parse(GenerationTask, next(t for t in state['generation_tasks'] if t['id'] == e['task_id']))
        if cap is not None and any(s.chapter_number > positions[cap] for s in task.frozen.parameters.sources):
            continue
        old = False
        try:
            assert_fresh(coordinator, state, task)
        except ValueError:
            old = True
        results.append(dict(deepcopy(e), outdated=old, quality_verified=False,
                           receipt=next((r for r in state['graph_decisions'] if r['extraction_id'] == e['id']), None)))
    return dict(revision=state['revision'], extractions=results)


def decide(coordinator, project, request):
    fields = {'operation_id', 'expected_revision', 'extraction_id', 'decision', 'confirm_inference'}
    check_fields(request, fields)
    require(set(request) == fields and type(request['confirm_inference']) is bool, '图谱决定字段不完整/确认非法')
    identity = uuid_value(request['operation_id'])
    require(request['decision'] in ('accepted', 'rejected', 'cancelled'), '图谱决定非法')

    def apply(state):
        old = next((r for r in state.get('graph_decisions', []) if r['id'] == identity), None)
        if old:
            require(all(old[k] == request[k] for k in ('extraction_id', 'decision', 'confirm_inference')), '图谱操作身份已绑定其它决定')
            return None, old
        from novel_writer.application.knowledge import CLAIMS
        require(not any(any(x[key]==identity for x in state.get(name,[])) for name,key in set(CLAIMS.values())), '图谱操作身份已用于其它知识操作')
        require(type(request['expected_revision']) is int and request['expected_revision'] == state['revision'], '保存编号已变化，请重新核对提案')
        e = next((e for e in state.get('graph_extractions', []) if e['id'] == request['extraction_id']), None)
        require(e is not None and not any(r['extraction_id'] == e['id'] for r in state.get('graph_decisions', [])), '图谱提案不存在、跨书或已有决定')
        decision = dict(id=identity, project_id=project, extraction_id=e['id'], decision=request['decision'],
                        confirm_inference=request['confirm_inference'], node_ids=[], edge_ids=[],
                        saved_revision=state['revision'] + 1, created_at=utc_now())
        if request['decision'] == 'accepted':
            require(request['confirm_inference'], '接受前须明确核对每个实体和关系的引文/推断')
            task = parse(GenerationTask, next(t for t in state['generation_tasks'] if t['id'] == e['task_id']))
            assert_fresh(coordinator, state, task)
            nodes, edges = artifacts(state, e, decision)
            state['knowledge_nodes'].extend(nodes)
            state['knowledge_edges'].extend(edges)
            decision.update(node_ids=[n['id'] for n in nodes], edge_ids=[e['id'] for e in edges])
        state['graph_decisions'].append(encode(parse(Decision, decision)))
        return state, decision
    return coordinator.repository.atomic(project, apply, identity_claim=('graph_decisions', 'id', identity))
