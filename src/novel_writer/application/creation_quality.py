"""Deterministic planning checks; semantic judgements remain author reviews."""
from novel_writer.domain.book_creation import STEPS, STEP_FIELDS, fingerprint


def stale_steps(state, version):
    if version is None:
        return []
    versions = {v['id']: v for v in state.get('book_creation_versions', [])}
    chain = []
    cursor = version
    while cursor:
        chain.append(cursor)
        cursor = versions.get(cursor['previous_version_id'] or cursor['derived_from_version_id'])
    stale = set()
    for current in reversed(chain):
        previous = versions.get(current['previous_version_id'] or current['derived_from_version_id'])
        if previous is None:
            continue
        changed = [s for s in STEPS if any(fingerprint(current['data'][f]) != fingerprint(previous['data'][f]) for f in STEP_FIELDS[s])]
        for step in changed:
            stale.update(s for s in STEPS[STEPS.index(step)+1:]
                         if s in previous['completed_steps'] or s in stale)
        if STEPS.index(current['current_step']) < STEPS.index(previous['current_step']):
            stale.update(s for s in STEPS[STEPS.index(current['current_step'])+1:]
                         if s in previous['completed_steps'])
        # An explicit completion (including re-completion after invalidation)
        # acknowledges the saved downstream proposal, without rewriting history.
        stale.difference_update(set(current['completed_steps']) - set(previous['completed_steps']))
        stale.difference_update(current['skipped_steps'])
    return [s for s in STEPS if s in stale]


def quality_report(data, step='dialogue'):
    errors = []
    selected = set(STEPS if step == 'dialogue' else [step])
    def issue(field, code):
        errors.append(dict(field=field, code=code))
    for current in selected:
        for name in STEP_FIELDS[current] - {'subplots', 'characters', 'volumes', 'target_words'}:
            if not getattr(data, name).strip():
                issue(name, 'required')
    if 'scope' in selected and data.target_words <= 0:
        issue('target_words', 'positive_required')
    if 'world' in selected:
        if not data.characters:
            issue('characters', 'required')
        names = [c.name.strip().casefold() for c in data.characters]
        if len(names) != len(set(names)):
            issue('characters', 'ambiguous_names')
        for c in data.characters:
            if not c.role.strip():
                issue('characters', 'missing_role')
    if 'structure' in selected:
        if not data.volumes:
            issue('volumes', 'required')
        for volume in data.volumes:
            if not volume.chapters:
                issue('volumes', 'empty_volume')
            for chapter in volume.chapters:
                if not (chapter.core_idea.strip() or chapter.objective.strip()):
                    issue('volumes', 'missing_chapter_event')
    return dict(errors=errors, semantic_review_required=True,
                author_checks=['人物目标与事件因果是否矛盾', '主线和结局是否回应核心冲突',
                               '卷章事件是否齐全、顺序是否合理'],
                method='确定性结构检查；不推断自然语言中的矛盾或冲突偏离')
