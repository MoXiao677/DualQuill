"""Deterministic context retrieval; no paid summarization or silent hard-rule trim."""
import json
import re
from novel_writer.domain.chapter_trash import hidden_ids
from novel_writer.domain.body_planning import archived

LIMIT = 360000


def checked_context(value):
    if len(json.dumps(value, ensure_ascii=False)) > LIMIT:
        raise ValueError('所需完整上下文超过360000字符；请缩小任务范围或整理资料。没有截断正文、世界观或写作规则，未发送模型请求')
    return value


def safe_action_result(tool, result):
    if tool == 'read_material':
        return result
    if isinstance(result, dict):
        keys = ('saved', 'generated', 'reviewed', 'passed', 'revised', 'chapter', 'chapter_id', 'number', 'chars', 'report_id', 'material_id', 'maintenance_saved', 'created_book', 'title', 'exact_source')
        safe = {k: result[k] for k in keys if k in result and isinstance(result[k], (str, int, float, bool, type(None)))}
        if isinstance(result.get('issues'), list):
            safe['issue_count'] = len(result['issues'])
        return safe or {'summary': '工具执行成功；完整结果保留于已保存资料'}
    return str(result)[:1000]


def _prose(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ' '.join(_prose(item) for item in value)
    if isinstance(value, dict):
        return ' '.join(_prose(value.get(k, '')) for k in ('title', 'summary', 'core_idea', 'objective', 'story_time', 'scenes', 'text', 'content', 'role', 'personality', 'background', 'notes', 'goals'))
    return ''


def build_context(state, target=None):
    doc = state['document']
    hidden = hidden_ids(state)
    chapters = sorted(doc.get('chapters', []), key=lambda c: c['number'])
    positions = {c['id']: c['number'] for c in chapters}
    visible = [c for c in chapters if c['id'] not in hidden]
    current = next((c for c in visible if c['number'] == target), None) if target is not None else None
    prior = [c for c in visible if target is None or c['number'] < target][-2:]
    outlines = doc.get('chapter_outlines', [])
    outline = next((o for o in outlines if current and o.get('chapter_id') == current['id']), None)
    selected_outlines = [o for o in outlines if target is None or o is outline]
    prose = ' '.join(_prose(c.get('content', '')) for c in prior + ([current] if current else [])) + ' ' + _prose(outline or {})
    prose_terms = {t.casefold() for t in re.findall(r'[A-Za-z0-9_\u4e00-\u9fff]{2,}', prose) if len(t) <= 40}
    active_characters = [c for c in doc.get('characters', []) if not archived(state, 'character', c['id'])]
    explicit_ids = set((outline or {}).get('character_ids', []))
    characters = [c for c in active_characters if c['id'] in explicit_ids or c.get('name', '').casefold() in prose.casefold() or any(t in _prose(c).casefold() for t in prose_terms)]
    if target is None:
        characters = active_characters[:30]
    selected_names = {c.get('name', '').casefold() for c in characters}
    active = [m for m in state.get('memories', []) if m.get('active', True)]
    eligible, future, unknown = [], [], []
    for memory in active:
        position_id = memory.get('position_chapter_id') or (memory.get('source') or {}).get('entity_id')
        position = positions.get(position_id)
        if memory.get('kind') == 'book_summary':
            eligible.append(memory)
        elif target is not None and position is None:
            unknown.append(memory)
        elif target is not None and position > target:
            future.append(memory)
        else:
            eligible.append(memory)
    pinned = [m for m in eligible if m.get('kind') in ('book_summary', 'foreshadow') and not m.get('resolved')]
    preceding = [m for m in eligible if m not in pinned and (positions.get(m.get('position_chapter_id')) in {c['number'] for c in prior} or any(name and name in _prose(m).casefold() for name in selected_names) or any(term in _prose(m).casefold() for term in prose_terms))]
    memories = pinned + preceding[-40:]
    selected_ids = {m.get('id') for m in memories}
    coverage = dict(selection='显式检索，并非已阅读全文；静态设定可能含未来规划，必须尊重目标细纲，不得提前兑现未来情节', target=target, full_body_chapters=[c['number'] for c in prior] + ([target] if current else []), characters=dict(selected=[c['id'] for c in characters], omitted=[c['id'] for c in active_characters if c not in characters]), memories=dict(selected=[m.get('id') for m in memories], omitted=[m.get('id') for m in active if m.get('id') not in selected_ids], future_excluded=len(future), unknown_position_excluded=len(unknown)), outlines=dict(selected=len(selected_outlines), omitted=len(outlines)-len(selected_outlines)), material_retrieval='read_material {material_id,offset,limit}；未读取页不能声称已读取')
    return checked_context(dict(project=doc['project'], revision=state['revision'], chapters=[dict(id=c['id'], number=c['number'], title=c['title'], chars=len(c.get('content', '')), deleted=c['id'] in hidden) for c in chapters], recent_bodies=[dict(number=c['number'], content=c.get('content', '')) for c in prior], target_chapter=current, target_outline=outline, characters=characters, book_outline=doc.get('book_outline'), chapter_outlines=selected_outlines, worldbuilding=state.get('worldbuilding', ''), writing_rules=state.get('writing_rules', ''), memories=memories, coverage=coverage, materials=[dict(id=m['id'], title=m['title'], format=m['format'], tags=m['tags'], current_version_id=m['current_version_id'], read_tool='read_material', data_only=True) for m in state.get('materials', []) if not m.get('archived') and m.get('project_id') == doc['project']['id']]))
