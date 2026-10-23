"""标准库字面扫描。搜索派生结果不入库，选入上下文时重新核对。"""
from novel_writer.application.fields import check_fields,text,text_list
from novel_writer.application.context_preview import find_dict
from novel_writer.domain.models import DataValidationError
from novel_writer.domain.memory import capture_source,fingerprint,outdated,effective_position
from novel_writer.domain.materials import current_version,index_status,material_chunks,require_current_index
import json

SCOPES={'body','planning','characters','memories','worldbuilding','writing_rules','skills','materials'}
SELECTION_FIELDS={'project_id','kind','entity_id','workspace_revision','version_id','source_sha256','scope','file_path'}

def sources(state,skills=()):
    doc=state['document'];project=doc['project']['id'];positions={c['id']:c['number'] for c in doc['chapters']}
    from novel_writer.domain.chapter_trash import hidden_ids
    hidden=hidden_ids(state)
    def item(kind,identifier,content,scope,locator,position=None,extra=None):
        if kind=='memory':
            memory=next(m for m in state.get('memories',[]) if m['id']==identifier)
            version=next(h['id'] for h in reversed(state['memory_history']) if h['memory_id']==identifier)
            digest=fingerprint(memory)
        elif kind=='skill':
            skill=extra['skill'];version=None;digest=fingerprint(skill)
        else:
            source=capture_source(state,dict(kind=kind,entity_id=identifier));version=source['version_id'];digest=source['source_sha256']
        selection=dict(project_id=project,kind=kind,entity_id=identifier,workspace_revision=state['revision'],
            version_id=version,source_sha256=digest,scope='global' if kind=='skill' else 'book',file_path=extra.get('file_path') if extra else None)
        return dict(kind=kind,entity_id=identifier,content=content,scope=scope,position=position,
            selection=selection,locator=dict(project_id=project,version_id=version,**locator),**({k:v for k,v in extra.items() if k not in ('skill','file_path')} if extra else {}))
    for chapter in sorted(doc['chapters'],key=lambda c:c['number']):
        if chapter['id'] in hidden:continue
        yield item('chapter',chapter['id'],chapter['title']+'\n'+chapter['content']+'\n','body',dict(view='writing',chapter_id=chapter['id']),chapter['number'])
    if doc['book_outline']:
        b=doc['book_outline'];yield item('book_outline',b['id'],json.dumps(b,ensure_ascii=False)+'\n','planning',dict(view='outline'),extra=dict(unlocated=True))
    for outline in doc['chapter_outlines']:
        if outline['chapter_id'] in hidden:continue
        yield item('chapter_outline',outline['id'],json.dumps(outline,ensure_ascii=False)+'\n','planning',dict(view='writing',chapter_id=outline['chapter_id'],pane='outline'),positions[outline['chapter_id']])
    for character in doc['characters']:
        yield item('character',character['id'],json.dumps(character,ensure_ascii=False)+'\n','characters',dict(view='characters',character_id=character['id']),extra=dict(unlocated=True))
    for memory in state.get('memories',[]):
        if memory['position_chapter_id'] in hidden or memory.get('source',{}).get('chapter_id') in hidden:continue
        yield item('memory',memory['id'],memory['title']+'\n'+memory['text']+'\n','memories',dict(view='memory',memory_id=memory['id']),effective_position(state,memory),
            dict(confirmed=memory['confirmed'],active=memory['active'],outdated=outdated(state,memory['source'])))
    for key,view in (('worldbuilding','world'),('writing_rules','rules')):
        yield item(key,project,state[key]+'\n',key,dict(view=view),extra=dict(unlocated=True))
    for skill in skills:
        for file in skill['files']:
            yield item('skill',skill['id'],file['content']+'\n','skills',dict(view='skills',skill_id=skill['id'],file_path=file['path']),
                extra=dict(skill=skill,file_path=file['path'],global_scope=True,version_basis='全局资料完整记录SHA256（非workspace实体版本）'))

def search(state,options,skills=()):
    check_fields(options,{'query','chapter_id','scopes','whole_book','skill_ids','material_ids','limit','mode'})
    mode=options.get('mode','literal')
    if mode not in ('literal','hybrid'):raise DataValidationError('检索模式只能为literal或hybrid')
    query=text(options.get('query'),'检索词',required=True)
    if len(query)>100:raise DataValidationError('检索词最多100字符')
    chapter=find_dict(state['document']['chapters'],options.get('chapter_id'),'写作章节')
    from novel_writer.domain.chapter_trash import hidden_ids
    if chapter['id'] in hidden_ids(state):raise DataValidationError('归档或回收站章节不能作为检索位置')
    scopes=text_list(options.get('scopes',['body','memories']),'检索范围')
    if not set(scopes)<=SCOPES:raise DataValidationError('未知检索范围')
    whole=options.get('whole_book',False)
    if type(whole) is not bool:raise DataValidationError('全书范围需要明确选择')
    ids=text_list(options.get('skill_ids',[]),'全局Skills')
    if 'skills' in scopes and not ids:raise DataValidationError('检索全局Skills必须明确选择资料')
    material_ids=[]
    for identifier in text_list(options.get('material_ids',[]),'本地资料选择'):
        if identifier not in material_ids:material_ids.append(identifier)
    if 'materials' in scopes and not material_ids:raise DataValidationError('检索本地资料必须明确选择资料')
    if material_ids and 'materials' not in scopes:raise DataValidationError('选择本地资料时检索范围必须包含资料')
    limit=options.get('limit',30)
    if type(limit) is not int or not 1<=limit<=50:raise DataValidationError('检索数量上限为1至50')
    if mode=='hybrid':
        from novel_writer.application.hybrid_retrieval import search as hybrid
        return hybrid(state,query,chapter,scopes,whole,skills,material_ids,limit)
    hits=[];limited=False
    for node in sources(state,skills):
        if node['scope'] not in scopes or (not whole and node['position'] is not None and node['position']>chapter['number']):continue
        offset=node['content'].find(query)
        if offset<0:continue
        if len(hits)>=limit:limited=True;break
        start=max(0,offset-60);end=min(len(node['content']),offset+len(query)+100)
        hits.append({k:v for k,v in node.items() if k!='content'}|dict(snippet=node['content'][start:end],snippet_offset=start))
    materials={value['id']:value for value in state.get('materials',[])}
    for material_id in material_ids:
        material=materials.get(material_id)
        if material is None:raise DataValidationError('选定本地资料不存在或不属于当前书')
        if material['archived']:raise DataValidationError('已归档资料不能检索，请先恢复')
        try:version=require_current_index(state,material)
        except DataValidationError:raise DataValidationError('资料索引缺失或过期，请先显式重建') from None
        chunks=material_chunks(state,material['id'])
        selection=dict(project_id=state['document']['project']['id'],kind='material',entity_id=material['id'],
            workspace_revision=state['revision'],version_id=version['id'],source_sha256=version['text_sha256'],scope='book',file_path=None)
        cursor=0
        while True:
            offset=version['text'].find(query,cursor)
            if offset<0:break
            if len(hits)>=limit:limited=True;break
            chunk=next((value for value in chunks if value['start']<=offset<value['end']),chunks[-1])
            start=max(0,offset-60);end=min(len(version['text']),offset+len(query)+100)
            hits.append(dict(kind='material',entity_id=material['id'],scope='materials',position=None,selection=selection,
                locator=dict(project_id=state['document']['project']['id'],version_id=version['id'],view='materials',material_id=material['id']),
                material_id=material['id'],material_title=material['title'],version_number=version['version_number'],
                version_id=version['id'],text_sha256=version['text_sha256'],start=offset,end=offset+len(query),
                chunk_ordinal=chunk['ordinal'],chunk_start=chunk['start'],chunk_end=chunk['end'],
                snippet=version['text'][start:end],snippet_offset=start))
            cursor=offset+max(1,len(query))
    warnings=[]
    if whole:warnings.append('已明确选择全书检索，结果可能包含后续章；选入上下文仍按写作章节重新过滤。')
    if set(scopes)&{'planning','characters','worldbuilding','writing_rules'}:warnings.append('已主动选入无故事位置的自由资料，可能包含未来设定；未做语义或剧透识别。')
    if 'skills' in scopes:warnings.append('Skills为明确选择的全局资料，不伪称本书专属或实体版本。')
    if 'materials' in scopes:warnings.append('资料为固定窗口的字面扫描，不是语义检索或向量索引。')
    return dict(project_id=state['document']['project']['id'],revision=state['revision'],query=query,
        chapter_id=chapter['id'],whole_book=whole,hits=hits,limited=limited,warnings=warnings,
        method='已保存资料的区分大小写字面扫描；不是语义检索',model_request_sent=False)

def resolve_selections(state,chapter,selections,skills=()):
    if type(selections) is not list or len(selections)>50:raise DataValidationError('选定搜索来源必须为至多50项列表')
    catalog={(n['selection']['kind'],n['entity_id'],n['selection']['file_path']):n for n in sources(state,skills)}
    materials={value['id']:value for value in state.get('materials',[])}
    for selected in selections:
        if type(selected) is not dict or not SELECTION_FIELDS<=set(selected)<=SELECTION_FIELDS|{'excerpt'}:raise DataValidationError('搜索来源字段无效，不接受缓存正文或片段')
        base={key:selected[key] for key in SELECTION_FIELDS}
        if selected['project_id']!=state['document']['project']['id']:raise DataValidationError('搜索结果不属于当前书')
        if type(selected['kind']) is not str or type(selected['entity_id']) is not str or (selected['file_path'] is not None and type(selected['file_path']) is not str):raise DataValidationError('搜索来源身份无效')
        if selected['kind']=='material':
            if type(selected['workspace_revision']) is not int or selected['workspace_revision']<0:raise DataValidationError('搜索来源身份无效')
            material=materials.get(selected['entity_id']);version=None;reason=None
            if material is None:reason='stale_search'
            elif material['archived']:reason='material_archived'
            else:
                version=current_version(state,material)
                status=index_status(state,material)
                if status=='missing':reason='material_index_missing'
                elif status=='stale':reason='material_index_stale'
                elif selected['version_id']!=version['id'] or selected['source_sha256']!=version['text_sha256'] or selected['scope']!='book' or selected['file_path'] is not None:reason='stale_search'
                else:require_current_index(state,material)
            body=None if reason else version['text']
            yield dict(selection=selected,content=_excerpt(selected,body) if 'excerpt' in selected else None if reason else body+'\n',reason=reason or 'selected_material')
            continue
        node=catalog.get((selected['kind'],selected['entity_id'],selected['file_path']))
        reason=None
        if node is None or node['selection']!=base:reason='stale_search'
        elif node['position'] is not None and node['position']>chapter['number']:reason='future_search'
        elif node['kind']=='memory':
            if not node['active']:reason='memory_archived'
            elif not node['confirmed']:reason='memory_unconfirmed'
            elif node['outdated']:reason='memory_outdated'
            elif 'excerpt' in selected:
                from novel_writer.application.memory_rollups import conflicts
                if selected['entity_id'] in {i for c in conflicts(state) for i in c['memory_ids']}:reason='memory_conflict'
        yield dict(selection=selected,content=_excerpt(selected,None if reason else node['content']) if 'excerpt' in selected else None if reason else node['content'],reason=reason or 'selected_search')


def _excerpt(selected,body):
    from novel_writer.domain.tasks import parse,SearchExcerpt,digest
    excerpt=parse(SearchExcerpt,selected['excerpt'])
    if body is None:return None
    if excerpt.end>len(body) or digest(body[excerpt.start:excerpt.end])!=excerpt.sha256:raise DataValidationError('检索引文范围或哈希不匹配')
    return body[excerpt.start:excerpt.end]
