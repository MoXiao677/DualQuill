"""Deterministic context retrieval; no paid summarization or silent hard-rule trim."""
import hashlib
import json
import re
from novel_writer.domain.chapter_trash import hidden_ids
from novel_writer.domain.body_planning import archived
from novel_writer.domain.memory import outdated, effective_position, capture_source
from novel_writer.domain.models import DataValidationError
from novel_writer.application import scoped_rules

LIMIT = 360000


def checked_context(value):
    if len(json.dumps(value, ensure_ascii=False)) > LIMIT:
        raise ValueError('所需完整上下文超过360000字符；请缩小任务范围或整理资料。没有截断正文、世界观或写作规则，未发送模型请求')
    return value


def safe_action_result(tool, result):
    if tool == 'read_material':
        return result
    if isinstance(result, dict):
        keys = ('saved', 'generated', 'reviewed', 'passed', 'revised', 'chapter', 'chapter_id', 'number', 'chars', 'report_id', 'material_id', 'maintenance_saved', 'created_book', 'title', 'exact_source', 'workflow_accepted', 'accepted', 'status', 'acceptance_reason', 'independent_review_status', 'revision_iteration', 'previous_review_report_id', 'synced', 'receipt_id', 'receipt_status')
        safe = {k: result[k] for k in keys if k in result and isinstance(result[k], (str, int, float, bool, type(None)))}
        if isinstance(result.get('issues'), list):
            safe['issue_count'] = len(result['issues'])
        return safe or {'summary': '工具执行成功；完整结果保留于已保存资料'}
    return str(result)[:1000]


def _prose(value):
    if isinstance(value, str): return value
    if isinstance(value, list): return ' '.join(_prose(item) for item in value)
    if isinstance(value, dict): return ' '.join(_prose(value.get(k, '')) for k in ('title', 'summary', 'core_idea', 'objective', 'story_time', 'scenes', 'text', 'content', 'role', 'personality', 'background', 'notes', 'goals'))
    return ''


def _rule_hash(rule):
    return hashlib.sha256(json.dumps(rule.get('text', rule), ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf8')).hexdigest()


def _rules(state, current):
    doc = state['document']; project = doc['project']['id']
    chapters = doc.get('chapters', [])
    visible_ids = {c['id'] for c in chapters} - set(hidden_ids(state))
    book_outline = doc.get('book_outline') or {}
    volumes = {str(v['number']): v for v in book_outline.get('volumes', []) if isinstance(v, dict) and 'number' in v}
    live_volumes = set()
    for number, volume in volumes.items():
        members = set(volume.get('chapter_ids', []))
        members.update(c['id'] for c in chapters if str(c.get('volume_number')) == number)
        if not members or members & visible_ids: live_volumes.add(number)
    bindings = state.get('rule_task_bindings', [])
    if not isinstance(bindings, list): bindings = []
    bindings = {b.get('id'): b for b in bindings if isinstance(b, dict) and b.get('id') is not None and b.get('project_id') == project and b.get('chapter_id') in visible_ids}
    original = state.get('scoped_rules', [])
    valid = []
    for rule in original:
        if rule.get('project_id') != project or not rule.get('enabled', True) or rule.get('archived', False): continue
        scope, scope_id = rule.get('scope'), rule.get('scope_id')
        binding = bindings.get(scope_id) if scope == 'task' else None
        live = (scope == 'global' or scope == 'book' and scope_id == project
                or scope == 'chapter' and scope_id in visible_ids
                or scope == 'volume' and str(scope_id) in live_volumes
                or scope == 'task' and binding is not None and binding.get('chapter_id') in visible_ids)
        if live: valid.append(dict(rule))
    if current is not None:
        result = scoped_rules.resolve(dict(state, scoped_rules=valid), current['id'])
        rules, conflicts = result['rules'], list(result.get('conflicts', []))
    else:
        legacy = scoped_rules.legacy_rule(state)
        rules = ([dict(legacy)] if legacy and legacy.get('enabled', True) and not legacy.get('archived', False) else []) + valid
        rules = [dict(r, applicability='conditional: scope=' + str(r.get('scope')) + '; scope_id=' + str(r.get('scope_id')) + '; apply only to this live target') if r.get('scope') in ('volume', 'chapter', 'task') else r for r in rules]
        conflicts = []
    seen = set(); deduped = []
    for rule in rules:
        key = (rule.get('kind'), rule.get('text'), rule.get('scope'), rule.get('scope_id'))
        if key not in seen: seen.add(key); deduped.append(rule)
    if current is None:
        by_text = {}
        for rule in deduped:
            if rule.get('scope') in ('global', 'book'): by_text.setdefault(rule.get('text'), []).append(rule)
        for text, values in by_text.items():
            if {'required', 'forbidden'} <= {v.get('kind') for v in values}:
                conflicts.append(dict(text=text, rule_ids=[v.get('id') for v in values], scopes=[v.get('scope') for v in values]))
    included_ids = {r.get('id') for r in deduped}
    omitted = sum(r.get('id') not in included_ids for r in original)
    conditional = sum(r.get('scope') in ('volume', 'chapter', 'task') for r in deduped) if current is None else 0
    return deduped, conflicts, conditional, omitted


def build_context(state, target=None):
    doc = state['document']; hidden = hidden_ids(state)
    chapters = sorted(doc.get('chapters', []), key=lambda c: c['number'])
    positions = {c['id']: c['number'] for c in chapters}; visible = [c for c in chapters if c['id'] not in hidden]
    current = next((c for c in visible if c['number'] == target), None) if target is not None else None
    if target is not None and current is None: raise ValueError('目标章节不存在或已隐藏')
    prior = [c for c in visible if target is None or c['number'] < target][-2:]
    visible_ids = {c['id'] for c in visible}
    outlines = [o for o in doc.get('chapter_outlines', []) if o.get('chapter_id') in visible_ids]
    outline = next((o for o in outlines if current and o.get('chapter_id') == current['id']), None)
    selected_outlines = [o for o in outlines if target is None or o is outline]
    prose = ' '.join(_prose(c.get('content', '')) for c in prior + ([current] if current else [])) + ' ' + _prose(outline or {})
    prose_terms = {t.casefold() for t in re.findall(r'[A-Za-z0-9_一-鿿]{2,}', prose) if len(t) <= 40}
    active_characters = [c for c in doc.get('characters', []) if not archived(state, 'character', c['id'])]
    explicit_ids = set((outline or {}).get('character_ids', []))
    characters = active_characters[:30] if target is None else [c for c in active_characters if c['id'] in explicit_ids or c.get('name', '').casefold() in prose.casefold() or any(t in _prose(c).casefold() for t in prose_terms)]
    rules, conflicts, conditional, rules_omitted = _rules(state, current)
    live_rules, _, _, _ = _rules(state, None) if current is not None else (rules, conflicts, conditional, rules_omitted)
    live_rule_ids = {r.get('id') for r in live_rules}
    project = doc['project']['id']
    known_character_ids = {c['id'] for c in doc.get('characters', [])}
    counts = dict(selected=0, omitted=0, relevance_omitted=0, future_excluded=0, unknown_position_excluded=0, inactive_excluded=0, unconfirmed_excluded=0, outdated_excluded=0, hidden_source_excluded=0, archived_character_excluded=0, invalid_source_excluded=0)
    eligible = []
    all_memories = state.get('memories', [])
    for memory in all_memories:
        if not memory.get('active', True): counts['inactive_excluded'] += 1; continue
        if not memory.get('confirmed', False): counts['unconfirmed_excluded'] += 1; continue
        source = memory.get('source')
        if not isinstance(source, dict) or memory.get('project_id') != project or source.get('project_id') != project:
            counts['invalid_source_excluded'] += 1; continue
        position_chapter = memory.get('position_chapter_id')
        if position_chapter in hidden:
            counts['hidden_source_excluded'] += 1; continue
        if position_chapter is None or position_chapter not in visible_ids:
            counts['unknown_position_excluded'] += 1; continue
        kind = source.get('kind'); entity_id = source.get('entity_id')
        try:
            actual = capture_source(state, {'kind': kind, 'entity_id': entity_id})
        except (DataValidationError, KeyError, TypeError):
            counts['invalid_source_excluded'] += 1; continue
        actual_chapter = actual.get('chapter_id')
        stored_chapter = source.get('chapter_id')
        if actual_chapter in hidden or stored_chapter in hidden:
            counts['hidden_source_excluded'] += 1; continue
        if ((actual_chapter is not None and actual_chapter not in visible_ids)
                or (stored_chapter is not None and stored_chapter not in visible_ids)
                or stored_chapter != actual_chapter):
            counts['invalid_source_excluded'] += 1; continue
        if kind == 'rule' and entity_id not in live_rule_ids:
            counts['invalid_source_excluded'] += 1; continue
        character_ids = [cid for cid in (memory.get('character_id'), entity_id if kind == 'character' else None) if cid is not None]
        if any(cid not in known_character_ids for cid in character_ids):
            counts['invalid_source_excluded'] += 1; continue
        if any(archived(state, 'character', cid) for cid in character_ids):
            counts['archived_character_excluded'] += 1; continue
        try: position = effective_position(state, memory)
        except (KeyError, TypeError, ValueError): counts['unknown_position_excluded'] += 1; continue
        if not isinstance(position, (int, float)):
            counts['unknown_position_excluded'] += 1; continue
        if target is not None and position > target: counts['future_excluded'] += 1; continue
        if outdated(state, source): counts['outdated_excluded'] += 1; continue
        eligible.append(memory)
    selected_names = {c.get('name', '').casefold() for c in characters}
    pinned = [m for m in eligible if m.get('kind') in ('book_summary', 'foreshadow') and not m.get('resolved')]
    preceding = [m for m in eligible if m not in pinned and (positions.get(m.get('position_chapter_id')) in {c['number'] for c in prior} or any(n and n in _prose(m).casefold() for n in selected_names) or any(t in _prose(m).casefold() for t in prose_terms))]
    memories = pinned + preceding[-40:]
    counts['selected'] = len(memories); counts['omitted'] = len(all_memories) - len(memories); counts['relevance_omitted'] = len(eligible) - len(memories)
    included_bodies = [c['number'] for c in prior] + ([current['number']] if current else [])
    book_outline = doc.get('book_outline')
    if isinstance(book_outline, dict):
        book_outline = dict(book_outline); book_outline['volumes'] = [dict(v, chapter_ids=[i for i in v.get('chapter_ids', []) if i in visible_ids]) for v in book_outline.get('volumes', []) if isinstance(v, dict)]
    coverage = dict(selection='显式检索，并非已阅读全文；静态设定可能含未来规划，必须尊重目标细纲，不得提前兑现未来情节', target=target, full_body_chapters=included_bodies, body_omitted_numbers=[c['number'] for c in visible if c['number'] not in included_bodies], hidden_chapter_count=len(hidden), characters=dict(selected=[c['id'] for c in characters], omitted=[c['id'] for c in active_characters if c not in characters]), memories=counts, outlines=dict(selected=[o.get('chapter_id') for o in selected_outlines], omitted=[o.get('chapter_id') for o in outlines if o not in selected_outlines]), rules=dict(included=[dict(id=r.get('id'), version=r.get('version'), scope=r.get('scope'), scope_id=r.get('scope_id'), sha256=_rule_hash(r)) for r in rules], omitted=rules_omitted, conflicts=conflicts, conditional=conditional), material_retrieval='read_material {material_id,offset,limit}；未读取页不能声称已读取')
    return checked_context(dict(project=doc['project'], revision=state['revision'], chapters=[dict(id=c['id'], number=c['number'], title=c['title'], chars=len(c.get('content', ''))) for c in visible], recent_bodies=[dict(id=c['id'], number=c['number'], content=c.get('content', '')) for c in prior], target_chapter=current, target_outline=outline, characters=characters, book_outline=book_outline, chapter_outlines=selected_outlines, worldbuilding=state.get('worldbuilding', ''), writing_rules=state.get('writing_rules', ''), scoped_rules=dict(rules=rules, conflicts=conflicts), memories=memories, coverage=coverage, materials=[dict(id=m['id'], title=m['title'], format=m['format'], tags=m['tags'], current_version_id=m['current_version_id'], read_tool='read_material', data_only=True) for m in state.get('materials', []) if not m.get('archived') and m.get('project_id') == doc['project']['id']]))
