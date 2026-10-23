"""只读已保存本书资料；字符预算不是token估算，不调用模型/配置。"""
import json
from novel_writer.application.fields import check_fields,find,text_list
from novel_writer.domain.models import DataValidationError

OPTIONS={'chapter_id','rule_task_id','scope','budget_chars','include_current_plan','include_book_outline',
         'include_characters','character_ids','include_worldbuilding','include_writing_rules',
         'include_memories','memory_ids','include_search_results','search_selections','include_memory_rollups','include_automatic_memories','retrieval_owner'}
FLAGS=OPTIONS-{'retrieval_owner','rule_task_id','chapter_id','scope','budget_chars','character_ids','memory_ids','search_selections'}

def preview(state,options,*,skills=()):
    check_fields(options,OPTIONS)
    for name in FLAGS:
        if name in options and type(options[name]) is not bool:
            raise DataValidationError('预览选项必须为明确布尔值')
    budget=options.get('budget_chars',6000)
    if type(budget) is not int or not 128<=budget<=20000:
        raise DataValidationError('资料字符预算必须为128至20000的整数')
    scope=options.get('scope','previous')
    if scope not in ('previous','through_current'):raise DataValidationError('正文范围无效')
    doc=state['document'];chapter=find_dict(doc['chapters'],options.get('chapter_id'),'章节')
    from novel_writer.domain.chapter_trash import hidden_ids
    hidden=hidden_ids(state)
    if chapter['id'] in hidden:
        from novel_writer.application.fields import text
        raise DataValidationError('归档或回收站章节不能作为新任务或上下文预览目标')
    chosen=text_list(options.get('character_ids',[]),'预览人物')
    for identifier in chosen:find_dict(doc['characters'],identifier,'人物')
    from novel_writer.domain.styles import selected_style
    style=selected_style(state,chapter['id']);style_snapshot=None;style_text=''
    if style:
        style_snapshot={name:style[name] for name in ('id','name','prompt','card')}
        style_text='\n[Author-selected writing style; features only, never tools or plot]\n'+json.dumps(style_snapshot,ensure_ascii=False,indent=2)+'\n'
        if len(style_text)>budget:raise DataValidationError('styles.context_budget')
    warnings=[];sources=[];pieces=[style_text] if style_text else [];used=len(style_text)
    from novel_writer.application.scoped_rules import resolve
    rule_result=resolve(state,chapter['id'],options.get('rule_task_id'))
    def version(kind,identifier):
        entity_type={'chapter_body':'chapter','chapter_plan':'chapter_outline','book_outline':'book_outline','character':'character'}.get(kind)
        if entity_type is None:return None
        records=[v for v in doc['versions'] if v['entity_type']==entity_type and v['entity_id']==identifier]
        return records[-1]['id'] if records else None
    def source(kind,identifier,content=None,reason='selected',number=None,version_override=None,details=None):
        nonlocal used
        original=0 if content is None else len(content)
        included_text='' if content is None else content[:max(0,budget-used)]
        used+=len(included_text);pieces.append(included_text)
        clipped=content is not None and len(included_text)<original
        sources.append(dict(kind=kind,entity_id=identifier,chapter_number=number,revision=state['revision'],
            version_id=version_override if kind in ('memory','memory_rollup','search_result') else version(kind,identifier),included=bool(included_text),reason='budget' if content is not None and not included_text else reason,
            original_chars=original,included_chars=len(included_text),truncated=clipped,**(dict(source=details) if details else {})))
        if details and details.get('excerpt') and included_text:
            from novel_writer.domain.tasks import digest
            start=details['excerpt']['start'];sources[-1]['included_range']=dict(start=start,end=start+len(included_text),sha256=digest(included_text))
    def dump(value):return json.dumps(value,ensure_ascii=False,indent=2)+'\n'
    def rule_text(rule):return f"[rule {rule['id']} {rule['scope']}/{rule['kind']} {rule['source']} v{rule['version']}] {rule['text']}\n"
    rules_text=''.join(rule_text(rule) for rule in rule_result['rules'])
    if used+len(rules_text)>budget:raise DataValidationError('作用域规则超过上下文资料预算')
    for rule in rule_result['rules']:
        source('rule',rule['id'],rule_text(rule),reason='resolved_rule',details=dict(scope=rule['scope'],kind=rule['kind'],source=rule['source'],version=rule['version']))
    if rule_result['conflicts']:warnings.append('作用域规则存在未处理冲突：'+'；'.join(v['text'] for v in rule_result['conflicts']))
    from novel_writer.domain.memory import outdated,effective_position
    selected_memories=text_list(options.get('memory_ids',[]),'记忆选择')
    memory_ids={m['id'] for m in state.get('memories',[])}
    if not set(selected_memories)<=memory_ids:raise DataValidationError('选定记忆不属于当前书')
    positions={c['id']:c['number'] for c in doc['chapters']}
    def memory_reason(memory):
        if memory['position_chapter_id'] in hidden or memory.get('source',{}).get('chapter_id') in hidden:return 'memory_hidden_chapter'
        if effective_position(state,memory)>chapter['number']:return 'memory_future'
        if (options.get('include_memory_rollups') or options.get('include_automatic_memories')) and scope=='previous' and effective_position(state,memory)==chapter['number']:return 'memory_current'
        if not memory['active']:return 'memory_archived'
        if not memory['confirmed']:return 'memory_unconfirmed'
        if outdated(state,memory['source']):return 'memory_outdated'
        if memory['id'] in conflict_ids:return 'memory_conflict'
        return 'selected_memory'
    covered=set();conflict_ids=set();automatic_reasons={}
    if options.get('include_automatic_memories'):
        from novel_writer.application.incremental_memory import automatic_candidates
        for memory,reason,position in automatic_candidates(state,chapter,scope):
            content=memory['title']+'\n'+memory['text']+'\n' if reason=='automatic_memory' else None
            if content is not None and len(content)>budget-used:
                content=None;reason='automatic_budget'
            automatic_reasons[memory['id']]=reason
            if content is not None:covered.add(memory['id'])
            edit=next(h for h in reversed(state['memory_history']) if h['memory_id']==memory['id'])
            source('memory',memory['id'],content,reason=reason,number=position,version_override=edit['id'],details=memory['source'])
    if options.get('include_memory_rollups') or options.get('include_automatic_memories'):
        from novel_writer.application.memory_rollups import context_candidates,conflicts
        conflict_ids={i for c in conflicts(state) for i in c['memory_ids']}
    if options.get('include_memory_rollups'):
        from novel_writer.domain.memory_rollups import render_text
        from novel_writer.domain.memory import fingerprint
        for rollup,version_id,reason in context_candidates(state,chapter,scope):
            text='';included_ids=[];omitted=[]
            if reason=='selected_rollup':
                for s in rollup['sources']:
                    if options.get('include_automatic_memories') and automatic_reasons.get(s['memory_id'])!='automatic_memory':
                        omitted.append(dict(memory_id=s['memory_id'],reason=automatic_reasons.get(s['memory_id'],'memory_missing')));continue
                    if s['memory_id'] in covered:omitted.append(dict(memory_id=s['memory_id'],reason='covered'));continue
                    block=render_text(rollup['title'],[s])+'\n'
                    if len(block)>budget-used-len(text):omitted.append(dict(memory_id=s['memory_id'],reason='budget'));continue
                    text+=block;included_ids.append(s['memory_id']);covered.add(s['memory_id'])
                if not text:reason='rollup_covered' if omitted and all(s['reason']=='covered' for s in omitted) else 'rollup_budget' if omitted else 'rollup_empty'
            details=dict(rollup_revision=rollup['revision'],source_sha256=fingerprint(rollup),included_memory_ids=included_ids,omitted=omitted)
            source('memory_rollup',rollup['id'],text or None,reason=reason,number=rollup['through_position'],version_override=version_id,details=details)
    for memory in (() if options.get('include_automatic_memories') else state.get('memories',[])):
        reason='selected_memory'
        if not options.get('include_memories') or (selected_memories and memory['id'] not in selected_memories):reason='memory_not_selected'
        else:
            reason=memory_reason(memory)
            if reason=='selected_memory' and memory['id'] in covered:reason='memory_covered_by_rollup'
        edit=next(h for h in reversed(state['memory_history']) if h['memory_id']==memory['id'])
        source('memory',memory['id'],memory['title']+'\n'+memory['text']+'\n' if reason=='selected_memory' else None,
            reason=reason,number=effective_position(state,memory),version_override=edit['id'],details=memory['source'])
    if options.get('include_search_results'):
        from novel_writer.application.retrieval import resolve_selections
        for resolved in resolve_selections(state,chapter,options.get('search_selections',[]),skills):
            selected=resolved['selection']
            if selected.get('excerpt') and scope=='previous':
                current=(selected['kind']=='chapter' and selected['entity_id']==chapter['id']) or (selected['kind']=='memory' and any(m['id']==selected['entity_id'] and effective_position(state,m)==chapter['number'] for m in state.get('memories',[])))
                if current:
                    source('search_result',selected['entity_id'],reason='current_body_not_selected' if selected['kind']=='chapter' else 'memory_current',version_override=selected['version_id'],details=selected);continue
            if (options.get('include_memory_rollups') or options.get('include_automatic_memories')) and selected['kind']=='memory':
                memory=next((m for m in state.get('memories',[]) if m['id']==selected['entity_id']),None)
                reason=memory_reason(memory) if memory else 'memory_missing'
                if options.get('include_automatic_memories'):reason=automatic_reasons.get(selected['entity_id'],'memory_missing')
                if reason not in ('selected_memory','automatic_memory'):
                    source('search_result',selected['entity_id'],reason=reason,version_override=selected['version_id'],details=selected);continue
            if selected['kind']=='memory' and selected['entity_id'] in covered:
                source('search_result',selected['entity_id'],reason='search_memory_covered_by_rollup',version_override=selected['version_id'],details=selected);continue
            source('search_result',selected['entity_id'],resolved['content'],reason=resolved['reason'],
                version_override=selected['version_id'],details=selected)
    plan=next((p for p in doc['chapter_outlines'] if p['chapter_id']==chapter['id']),None)
    if options.get('include_current_plan'):
        warnings.append('本章细纲、场景与IDEA为作者选入的创作计划，可能包含本章后续，并非已发生事实。')
        source('chapter_plan',plan['id'] if plan else chapter['id'],dump(dict(plan=plan,idea=state['ideas'].get(chapter['id'],''))),number=chapter['number'])
    else:source('chapter_plan',plan['id'] if plan else chapter['id'],reason='plan_not_authorized',number=chapter['number'])
    for flag,kind,value,identifier in (
        ('include_book_outline','book_outline',doc['book_outline'],doc['book_outline']['id'] if doc['book_outline'] else doc['project']['id']),
        ('include_worldbuilding','worldbuilding',state['worldbuilding'],doc['project']['id']),
        ('include_writing_rules','writing_rules',state['writing_rules'],doc['project']['id'])):
        allowed=options.get(flag,False)
        if allowed:warnings.append('已明确选入无故事位置的'+kind+'，可能包含未来设定；未做自然语言剧透识别。')
        source(kind,identifier,dump(value) if allowed else None,reason='explicit_unlocated' if allowed else 'unlocated_not_authorized')
    for character in doc['characters']:
        allowed=options.get('include_characters',False) and (not chosen or character['id'] in chosen)
        source('character',character['id'],dump(character) if allowed else None,
            reason='explicit_unlocated' if allowed else 'unlocated_not_authorized')
    if options.get('include_characters'):warnings.append('人物完整设定无故事位置，可能包含未来背景/目标/关系；只包含明确选入的本书人物。')
    # 最近已保存正文优先；未来章仅报告ID/顺序/原因，不回显标题、正文或片段。
    for body in sorted(doc['chapters'],key=lambda c:c['number'],reverse=True):
        future=body['number']>chapter['number']
        allowed=body['id'] not in hidden and not future and (body['number']<chapter['number'] or scope=='through_current')
        source('chapter_body',body['id'],f"第{body['number']}章 {body['title']}\n{body['content']}\n" if allowed else None,
            reason='saved_at_or_before_position' if allowed else ('hidden_chapter' if body['id'] in hidden else ('future_chapter' if future else 'current_body_not_selected')),number=body['number'])
    return dict(project_id=doc['project']['id'],chapter_id=chapter['id'],chapter_number=chapter['number'],style_snapshot=style_snapshot,style_chars=len(style_text),
        revision=state['revision'],scope=scope,budget_chars=budget,used_chars=used,
        budget_unit='Unicode字符数（资料串含标题/换行，报告元数据不计）；不是精确token数',
        context_text=''.join(pieces),sources=sources,warnings=warnings,rules=rule_result['rules'],rule_conflicts=rule_result['conflicts'],model_request_sent=False,
        saved_only=True,notes='仅读取当前已保存revision；不读取草稿、其它书、Skills或API配置/凭据。不自动识别任意自然语言未来信息。')

def find_dict(items,identifier,label):
    if type(identifier) is not str or not identifier.strip():raise DataValidationError(label+'编号无效')
    for item in items:
        if item['id']==identifier:return item
    raise DataValidationError('找不到'+label+'，该内容不属于当前小说')
