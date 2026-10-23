"""C14 dedicated chapter stages; typed plans remain unadopted candidates.

The shared generation task is the transport envelope. Its purpose is frozen in
the prompt version, never inferred from a title or from arbitrary JSON fields.
"""
from novel_writer.domain.tasks import require, digest

PROMPTS = {
    'model_idea': 'workflow-idea-json-1',
    'model_outline': 'workflow-outline-json-1',
    'model_draft': 'workflow-draft-1',
    'model_saved_draft': 'workflow-draft-1',
}
PLAN_PROMPTS = tuple(PROMPTS[k] for k in ('model_idea', 'model_outline'))


def contains(value):
    if isinstance(value, dict):
        return (value.get('kind') in PROMPTS or value.get('prompt_version') in PROMPTS.values()
                or (type(value.get('concurrency')) is int and value['concurrency'] > 1)
                or any(contains(v) for v in value.values()))
    if isinstance(value, (list, tuple)):
        return any(contains(v) for v in value)
    return False


def upgrade(state):
    if contains(state):
        from novel_writer.application.chapter_lifecycle import upgrade as prior
        prior(state)
        state.setdefault('rule_task_bindings', [])
        state['workspace_version'] = max(state['workspace_version'], 40)


def typed_result(frozen, text):
    """Re-parse the real candidate using its frozen character allowlist."""
    prompt = frozen.parameters.binding.prompt_version
    require(prompt in PLAN_PROMPTS, '该节点没有已接通的typed规划结果')
    from novel_writer.domain.chapter_planning import parse_candidate
    # This workflow variant proposes narrative beats, not entity associations.
    # Empty IDs also make historical wire JSON immutable through library copy.
    value, errors = parse_candidate('brainstorm' if prompt == PLAN_PROMPTS[0] else 'outline', text, ())
    require(not errors and value is not None, 'workflow.invalid_typed_plan:' + ','.join(errors))
    return value


def source_payload(frozen):
    source = frozen.parameters.upstream
    return dict(input_origin=source.kind, input_sha256=source.text_sha256,
                source_text=source.text, saved_target_sha256=source.saved_target.source_sha256)


def require_stage_source(state, node_kind, snapshot):
    """Join/loop forwarding cannot turn saved text into an upstream typed plan."""
    if node_kind == 'model_saved_draft':
        from novel_writer.domain.creative_workflow import require_outline_source
        return require_outline_source(state, snapshot)
    if node_kind == 'model_idea':
        require(snapshot.kind == 'chapter', 'IDEA节点只接声明的保存原文/空章引用')
        return None
    require(snapshot.kind == 'candidate', '细纲/初稿必须消费真实上游typed候选')
    from novel_writer.domain.tasks import parse, GenerationTask
    raw = next((t for t in state['generation_tasks'] if t['id'] == snapshot.producer_task_id), None)
    require(raw is not None, 'typed候选生产任务不存在')
    task = parse(GenerationTask, raw)
    expected = PROMPTS['model_idea' if node_kind == 'model_outline' else 'model_outline']
    require(task.frozen.parameters.binding.prompt_version == expected, '专用节点上游typed用途不符')
    candidate = next((c for c in state['generation_candidates'] if c['id'] == snapshot.entity_id), None)
    require(candidate is not None and task.status == 'succeeded' and task.candidate_id == candidate['id']
            and candidate['output_text'] == snapshot.text and digest(candidate['output_text']) == snapshot.text_sha256,
            '必须消费完整、成功且摘要匹配的typed候选')
    if node_kind == 'model_draft':
        require(snapshot.saved_target.text == '', '初稿节点仅支持原保存目标为空的章节；已有正文请改写')
    return typed_result(task.frozen, snapshot.text)


def validate_parallel_targets(nodes):
    """Unordered formal writes to the same chapter/action are unsupported.

    Model nodes write isolated task/candidate IDs. All apply operations keep the
    existing atomic business transaction and original saved-target guard.
    """
    by_id={n.id:n for n in nodes}
    ancestors={}
    def parents(identifier):
        if identifier not in ancestors:
            ancestors[identifier]=set(by_id[identifier].parents)
            for parent in by_id[identifier].parents:ancestors[identifier].update(parents(parent))
        return ancestors[identifier]
    writes=[n for n in nodes if n.kind=='apply']
    for index,left in enumerate(writes):
        for right in writes[index+1:]:
            if left.parameters.action==right.parameters.action:
                require(left.id in parents(right.id) or right.id in parents(left.id),
                        '并行正式写目标冲突；同一章节/动作必须显式串行连线')
