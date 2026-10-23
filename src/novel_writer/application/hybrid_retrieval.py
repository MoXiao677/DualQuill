"""Explicit local phrase/BM25 fusion with exact source excerpts, never semantic."""
from novel_writer.application.lexical_rank import rank
from novel_writer.domain.materials import chunk_ranges,material_chunks,require_current_index
from novel_writer.domain.models import DataValidationError
from novel_writer.domain.tasks import digest

CAPABILITIES=dict(lexical=True,phrase=True,bm25=True,rrf=True,rerank='query_coverage',
    embeddings=False,semantic=False,remote_embeddings=False,network_requests=False)


def search(state,query,chapter,scopes,whole,skills,material_ids,limit):
    from novel_writer.application.retrieval import sources
    from novel_writer.application.memory_rollups import conflicts
    blocked={i for conflict in conflicts(state) for i in conflict['memory_ids']}
    documents=[];excluded=[]
    def add(node,body):
        for start,end in chunk_ranges(len(body)) if body else []:
            documents.append(dict(text=body[start:end],base=start,node=node))
    for node in sources(state,skills):
        if node['scope'] not in scopes:continue
        reason=None
        if not whole and node['position'] is not None and node['position']>chapter['number']:reason='future_search'
        elif node['kind']=='memory':
            if not node['active']:reason='memory_archived'
            elif not node['confirmed']:reason='memory_unconfirmed'
            elif node['outdated']:reason='memory_outdated'
            elif node['entity_id'] in blocked:reason='memory_conflict'
        if reason:
            excluded.append(dict(kind=node['kind'],entity_id=node['entity_id'],reason=reason));continue
        add(node,node['content'])
    materials={m['id']:m for m in state.get('materials',[])}
    for identifier in material_ids:
        material=materials.get(identifier)
        if material is None:raise DataValidationError('选定本地资料不存在或不属于当前书')
        if material['archived']:raise DataValidationError('已归档资料不能检索，请先恢复')
        version=require_current_index(state,material)
        selection=dict(project_id=state['document']['project']['id'],kind='material',entity_id=identifier,
            workspace_revision=state['revision'],version_id=version['id'],source_sha256=version['text_sha256'],scope='book',file_path=None)
        node=dict(kind='material',entity_id=identifier,scope='materials',position=None,selection=selection,
            locator=dict(project_id=selection['project_id'],version_id=version['id'],view='materials',material_id=identifier),
            material_id=identifier,material_title=material['title'],version_number=version['version_number'],
            version_id=version['id'],text_sha256=version['text_sha256'])
        for chunk in material_chunks(state,identifier):
            documents.append(dict(text=version['text'][chunk['start']:chunk['end']],base=chunk['start'],node=node,chunk=chunk))
    ranked=rank(query,documents);hits=[];seen=set()
    for match in ranked:
        document=match['document'];node=document['node'];start=document['base']+match['start'];end=document['base']+match['end']
        key=(node['kind'],node['entity_id'],node['selection']['file_path'],start,end)
        if key in seen:continue
        seen.add(key)
        excerpt=dict(start=document['base'],end=document['base']+len(document['text']),sha256=digest(document['text']))
        hit={k:v for k,v in node.items() if k!='content'}
        hit.update(selection=dict(node['selection'],excerpt=excerpt),start=start,end=end,
            snippet=document['text'],snippet_offset=document['base'],score=round(match['score'],8),explanation=match['explanation'],
            range_unit='unicode_code_points',range_basis='material_version_text' if node['kind']=='material' else 'retrieval_source_representation')
        if 'chunk' in document:
            chunk=document['chunk'];hit.update(chunk_ordinal=chunk['ordinal'],chunk_start=chunk['start'],chunk_end=chunk['end'],chunk_sha256=chunk['text_sha256'])
        hits.append(hit)
    warnings=['确定性字面混合检索：Unicode归一、短语/BM25融合与词项覆盖重排；不是语义检索，不调用模型。']
    if whole:warnings.append('已明确选择全书检索；选入上下文仍按写作章节重新排除未来来源。')
    if set(scopes)&{'planning','characters','worldbuilding','writing_rules','skills','materials'}:warnings.append('自由资料由作者明确选入，可能包含未来设定；未做语义或剧透识别。')
    return dict(project_id=state['document']['project']['id'],revision=state['revision'],query=query,chapter_id=chapter['id'],
        whole_book=whole,hits=hits[:limit],limited=len(hits)>limit,warnings=warnings,excluded=excluded,
        method='unicode_lexical_bm25_phrase_rrf_v1',capabilities=CAPABILITIES.copy(),model_request_sent=False)
