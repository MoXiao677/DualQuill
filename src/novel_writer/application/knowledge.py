"""人工知识与反馈入口。每次写入在最新工作区同一事务中校验/留史。"""
from copy import deepcopy
from uuid import uuid5,NAMESPACE_URL
from dataclasses import replace
from novel_writer.domain.knowledge import *
from novel_writer.domain.memory import outdated,effective_position,capture_source
from novel_writer.domain.tasks import capture_dependency,dependency_equal
from novel_writer.domain.models import utc_now
from novel_writer.application.fields import check_fields,text,text_list
from novel_writer.storage.sqlite_repository import ConflictError

def upgrade(state):
    from novel_writer.application.tasks import upgrade as task_upgrade
    task_upgrade(state,'audit_chapter');state['workspace_version']=max(state['workspace_version'],5)
    for name in KNOWLEDGE_COLLECTIONS:state.setdefault(name,[])

def positions(state):return {c['id']:c['number'] for c in state['document']['chapters']}
def fresh(state,s):return not outdated(state,s)
def guarded(state,s):require(fresh(state,s),'来源/目标已变化，请重新准备提案')
def get(items,identifier):
    result=latest(items).get(identifier);require(result is not None,'对象不存在或不属于当前书');return result
def source(state,ref):return parse(Source,capture_source(state,ref))
def bool_value(value):require(type(value) is bool,'需要明确布尔值');return value
def bounded_text(value,label,limit=100000,required=False):
    value=text(value,label,required=required);require(len(value)<=limit,label+'超过长度限制');return value
def new_id(op,suffix):return str(uuid5(NAMESPACE_URL,op+'/'+suffix))
def current_source_number(state,item):return max(positions(state)[item['position_chapter_id']],positions(state).get(item['source']['chapter_id'],0))
def impact(state,chapter_id=None,kind=None,identifier=None,field=None):
    number=positions(state).get(chapter_id,0)
    return Impact(later_chapter_ids=tuple(c['id'] for c in state['document']['chapters'] if c['number']>number),foreshadow_node_ids=tuple(n['id'] for n in latest(state.get('knowledge_nodes',[])).values() if n['active'] and n['kind']=='foreshadow'),memory_ids=tuple(m['id'] for m in state.get('memories',[]) if chapter_id and m['source']['chapter_id']==chapter_id),locked=locked(state,kind,identifier,field) if kind else False,limitations=('仅按章节顺序与人工伏笔/记忆链接列影响，未判断语义矛盾或伏笔已解决。',))

def view(service,project_id,options):
    check_fields(options,{'query','chapter_id','root_id','depth','ready_only','include_inactive'})
    state=service.get(project_id);chapter_id=options.get('chapter_id');cap=max(positions(state).values(),default=0)
    if chapter_id is not None:require(chapter_id in positions(state),'检索章位不属于当前书');cap=positions(state)[chapter_id]
    depth=options.get('depth',1);require(type(depth) is int and 0<=depth<=3,'链深度限0至3')
    ready=bool_value(options.get('ready_only',False));inactive=bool_value(options.get('include_inactive',False));query=bounded_text(options.get('query',''),'查询',300).casefold()
    from novel_writer.application.graph_index import sync,quoted_provenance,quotes_fresh,merged_sources
    from novel_writer.application.chapter_lifecycle import is_hidden
    index=sync(service,state);node_quotes,edge_quotes=quoted_provenance(state);node_sources=merged_sources(state,index['knowledge_nodes'])
    nodes=[]
    from novel_writer.domain.body_planning import archived
    for n in index['knowledge_nodes'].values():
        if archived(state,'knowledge_node',n['id']) and not inactive:continue
        evidence=node_quotes.get(n['id'],[])
        sources=node_sources.get(n['id'],[n['source']]);effective=max([current_source_number(state,n)]+[positions(state).get(s['chapter_id'],0) for s in sources]+[positions(state).get(e['chapter_id'],0) for e in evidence])
        old=any(not fresh(state,s) or (s['chapter_id'] is not None and is_hidden(state,s['chapter_id'])) for s in sources) or not quotes_fresh(state,evidence) or is_hidden(state,n['position_chapter_id']);fact=n['confirmed'] and n['basis']=='saved_source' and not old
        if (not n['active'] and not inactive) or effective>cap or (ready and not fact):continue
        nodes.append(dict(n,outdated=old,ready_as_declared_fact=fact,effective_chapter_number=effective,evidence=evidence))
    ids={n['id'] for n in nodes};edges=[]
    for e in index['knowledge_edges'].values():
        evidence=edge_quotes.get(e['id'],[])
        old=not fresh(state,e['source']) or not quotes_fresh(state,evidence) or is_hidden(state,e['position_chapter_id']) or (e['source']['chapter_id'] is not None and is_hidden(state,e['source']['chapter_id']));fact=e['confirmed'] and e['source']['kind'] not in ('book_outline','chapter_outline','idea') and not old
        effective=max([current_source_number(state,e)]+[positions(state).get(q['chapter_id'],0) for q in evidence])
        if e['from_id'] in ids and e['to_id'] in ids and (e['active'] or inactive) and effective<=cap and (not ready or fact):edges.append(dict(e,outdated=old,ready_as_declared_fact=fact,evidence=evidence))
    root=options.get('root_id')
    if root is not None:
        require(root in latest(state.get('knowledge_nodes',[])),'关系链起点不属于当前书');visited={root} if root in ids else set();front=set(visited)
        for _ in range(depth):
            neighbors={e['to_id'] if e['from_id'] in front else e['from_id'] for e in edges if e['from_id'] in front or e['to_id'] in front};front=neighbors-visited;visited|=front
            require(len(visited)<=100,'关系链超过100节点，请缩小深度')
        nodes=[n for n in nodes if n['id'] in visited]
    if query:nodes=[n for n in nodes if query in n['label'].casefold() or any(query in a.casefold() for a in n['aliases'])]
    require(len(nodes)<=1000,'图谱结果超过1000节点，请缩小检索范围');ids={n['id'] for n in nodes};edges=[e for e in edges if e['from_id'] in ids and e['to_id'] in ids]
    plans=[dict(p,outdated=not fresh(state,p['source']) or not fresh(state,p['target']),locked=locked(state,p['target_kind'],p['target_id'],p['field']),receipt=next((r for r in state.get('planning_receipts',[]) if r['proposal_id']==p['id']),None)) for p in state.get('planning_proposals',[])]
    edits=[dict(p,outdated=any(not dependency_equal(parse(Dependency,g),capture_dependency(state,g['kind'],g['entity_id'],use=g['use'])) for g in p['guards']),receipt=next((r for r in state.get('local_edit_receipts',[]) if r['proposal_id']==p['id']),None)) for p in latest(state.get('local_edit_proposals',[])).values()]
    merges=state.get('graph_merges',[]);restores=state.get('graph_restores',[]);locks=state.get('planning_locks',[])
    if chapter_id is not None:
        merges=[m for m in merges if all(current_source_number(state,n)<=cap for n in m['before_nodes']) and all(current_source_number(state,e)<=cap for e in m['before_edges'])]
        restores=[r for r in restores if any(m['id']==r['merge_id'] for m in merges)]
        plans=[p for p in plans if p['source']['chapter_id'] in positions(state) and positions(state)[p['source']['chapter_id']]<=cap and p['target']['chapter_id'] in positions(state) and positions(state)[p['target']['chapter_id']]<=cap]
        edits=[p for p in edits if all(positions(state).get(e['chapter_id'],cap+1)<=cap for e in p['evidence'])]
        locks=[l for l in locks if l['target_kind']=='chapter_outline' and any(o['id']==l['target_id'] and positions(state).get(o['chapter_id'],cap+1)<=cap for o in state['document']['chapter_outlines'])]
    return dict(project_id=project_id,revision=state['revision'],nodes=nodes,edges=edges,merges=merges,restores=restores,plans=plans,locks=locks,edits=edits,limits=dict(depth=3,chain_nodes=100,method='manual_links_and_saved_source_versions'))

def merge_data(state,source_id,target_id):
    nodes=latest(state.get('knowledge_nodes',[]));a=get(list(nodes.values()),source_id);b=get(list(nodes.values()),target_id)
    from novel_writer.domain.body_planning import archived
    require(not any(archived(state,'knowledge_node',identifier) for identifier in (source_id,target_id)),'结构化设定已归档，请先恢复再合并')
    require(a['id']!=b['id'] and a['active'] and b['active'] and a['kind']==b['kind'],'只能合并本书同类型的两个活跃节点')
    edges=[e for e in latest(state.get('knowledge_edges',[])).values() if e['from_id'] in (source_id,target_id) or e['to_id'] in (source_id,target_id)]
    return a,b,edges
def merge_preview(service,project_id,values):
    check_fields(values,{'source_id','target_id'});state=service.get(project_id);a,b,edges=merge_data(state,values.get('source_id'),values.get('target_id'))
    return dict(source=a,target=b,edges=edges,memory_ids=list(dict.fromkeys(a['memory_ids']+b['memory_ids'])),aliases=list(dict.fromkeys(b['aliases']+[a['label']]+a['aliases'])),revision=state['revision'],note='仅合并人工节点/别名和节点记忆链接；保留原记忆/正文。恢复会拒绝覆盖之后的节点/关系编辑。')

def source_detail(service,project_id,values):
    check_fields(values,{'source'});s=encode(parse(Source,values.get('source')));state=service.get(project_id)
    known=[v['source'] for name in ('knowledge_nodes','knowledge_edges','planning_proposals') for v in state.get(name,[])]+[v['target'] for v in state.get('planning_proposals',[])]
    known += [dict(project_id=project_id,kind=e['source_kind'],entity_id=e['entity_id'],chapter_id=e['chapter_id'],version_id=e['version_id'],workspace_revision=e['source_revision'],source_sha256=e['source_sha256']) for x in state.get('graph_extractions',[]) for draft in x['output']['nodes']+x['output']['edges'] for e in draft['evidence']]
    require(s in known and s['project_id']==project_id,'出处不属于本书已保存知识记录')
    old=service.repository.get_revision(project_id,s['workspace_revision']);require(capture_source(old,dict(kind=s['kind'],entity_id=s['entity_id']))==s,'固定出处与历史不符')
    if s['kind'] in ('worldbuilding','writing_rules'):value=old[s['kind']]
    elif s['kind']=='idea':value=old['ideas'].get(s['entity_id'],'')
    elif s['version_id']:value=next(v['snapshot'] for v in old['document']['versions'] if v['id']==s['version_id'])
    else:
        doc=old['document'];items={'project':[doc['project']],'book_outline':[doc['book_outline']],'chapter':doc['chapters'],'chapter_outline':doc['chapter_outlines'],'character':doc['characters']}[s['kind']];value=next(v for v in items if v and v['id']==s['entity_id'])
    return dict(source=s,value=value,outdated=not fresh(state,s))

ALLOWED={
 'save_node':{'node_id','kind','label','aliases','memory_ids','position_chapter_id','source','confirmed'},
 'save_edge':{'edge_id','from_id','to_id','relation','position_chapter_id','source','confirmed'},
 'merge':{'source_id','target_id'},'restore_merge':{'merge_id'},
 'prepare_plan':{'target_kind','target_id','field','new_text','reason','source'},
 'set_plan_lock':{'target_kind','target_id','field','locked','reason'},
 'decide_plan':{'proposal_id','decision'},
 'prepare_edit':{'issue_id','side','mode','replacement','reason'},
 'revise_edit':{'proposal_id','mode','replacement','reason'},
 'decide_edit':{'proposal_id','proposal_revision','decision','authorize_confirmed'}}
CLAIMS={'save_node':('knowledge_nodes','edit_id'),'save_edge':('knowledge_edges','edit_id'),'merge':('graph_merges','id'),'restore_merge':('graph_restores','id'),'prepare_plan':('planning_proposals','id'),'set_plan_lock':('planning_locks','id'),'decide_plan':('planning_receipts','id'),'prepare_edit':('local_edit_proposals','edit_id'),'revise_edit':('local_edit_proposals','edit_id'),'decide_edit':('local_edit_receipts','id')}

def replay(state,action,v,op):
    collection,key=CLAIMS[action];old=next((x for x in state.get(collection,[]) if x[key]==op),None)
    if old is None:return None
    compare={'node_id':'id','edge_id':'id','proposal_id':'id'} if action in ('save_node','save_edge','revise_edit') else {}
    for name,value in v.items():
        if name in ('operation_id','expected_revision'):continue
        field=compare.get(name,name)
        if name=='source':require(value==dict(kind=old['source']['kind'],entity_id=old['source']['entity_id']),'操作身份已绑定其它来源')
        elif field in old:require(old[field]==value,'操作身份已绑定其它内容/目标')
    if action=='prepare_edit':require(old['revision']==1,'操作身份不属于初始提案')
    return old

def command(service,project_id,action,values,*,_workflow=None,_body_review=None):
    require(action in ALLOWED,'未知知识操作');check_fields(values,ALLOWED[action]|{'operation_id','expected_revision'});op=uuid_value(values.get('operation_id'));v=deepcopy(values)
    def apply(state):
        old=replay(state,action,v,op)
        if old is not None:return None,old
        if action=='decide_plan':
            body_owner=next((p['id'] for p in state.get('body_planning_proposals',[])
                             if v.get('proposal_id') in p['planning_proposal_ids']),None)
            require(body_owner is None or _body_review==body_owner,'正文规划关联提案须先经过其影响预览与人工决定')
            from novel_writer.application.workflow_hooks import owned_artifact
            require(not owned_artifact(state,'planning_proposal',v.get('proposal_id')) or _workflow is not None,'工作流规划提案须先经过其人工节点')
        if _workflow is not None:_workflow(state,'before',None)
        require(type(v.get('expected_revision')) is int and v['expected_revision']==state['revision'],'保存编号已变化，请保留输入并刷新')
        # 一次身份不能跨不同知识动作重用；检查所有历史修订而非仅当前值。
        for name,key in set(CLAIMS.values()):require(not any(x[key]==op for x in state.get(name,[])),'操作身份已用于其它操作')
        require(not any(x['id']==op for x in state.get('graph_decisions',[])),'操作身份已用于图谱抽取决定')
        require(not any(x['id']==op for x in state.get('graph_decisions',[])+state.get('graph_item_decisions',[])),'操作身份已用于图谱抽取决定')
        upgrade(state);now=utc_now();project=state['document']['project']['id']
        def append(name,obj):raw=encode(obj);state[name].append(raw);return raw
        if action in ('save_node','save_edge'):
            position=v.get('position_chapter_id');require(position in positions(state),'章位不属于当前书');s=source(state,v.get('source'));confirmed=bool_value(v.get('confirmed'))
            if action=='save_node':
                identifier=v.get('node_id') or op;oldnode=get(state['knowledge_nodes'],identifier) if v.get('node_id') else None
                from novel_writer.domain.body_planning import archived
                require(not archived(state,'knowledge_node',identifier),'结构化设定已归档，请先恢复')
                require(oldnode is None or oldnode['active'],'已合并节点需先恢复');aliases=text_list(v.get('aliases',[]),'别名');memory_ids=text_list(v.get('memory_ids',[]),'记忆链接')
                obj=Node(id=identifier,project_id=project,edit_id=op,revision=oldnode['revision']+1 if oldnode else 1,kind=v.get('kind'),label=bounded_text(v.get('label'),'节点名称',300,True),aliases=tuple(aliases),memory_ids=tuple(memory_ids),position_chapter_id=position,source=s,basis='plan' if s.kind in ('book_outline','chapter_outline','idea') else 'saved_source',confirmed=confirmed,active=True,merged_into=None,created_at=now);result=append('knowledge_nodes',obj)
            else:
                nodes=latest(state['knowledge_nodes']);require(v.get('from_id') in nodes and v.get('to_id') in nodes and nodes[v['from_id']]['active'] and nodes[v['to_id']]['active'],'关系端点不属于本书活跃节点')
                from novel_writer.domain.body_planning import archived
                require(not any(archived(state,'knowledge_node',v[k]) for k in ('from_id','to_id')),'关系端点含已归档结构化设定')
                identifier=v.get('edge_id') or op;oldedge=get(state['knowledge_edges'],identifier) if v.get('edge_id') else None
                obj=Edge(id=identifier,project_id=project,edit_id=op,revision=oldedge['revision']+1 if oldedge else 1,from_id=v['from_id'],to_id=v['to_id'],relation=bounded_text(v.get('relation'),'关系',300,True),position_chapter_id=position,source=s,confirmed=confirmed,active=True,created_at=now);result=append('knowledge_edges',obj)
        elif action=='merge':
            a,b,edges=merge_data(state,v.get('source_id'),v.get('target_id'));after=[]
            for raw in (a,b):
                n=parse(Node,raw);n=replace(n,edit_id=new_id(op,n.id),revision=n.revision+1,created_at=now)
                if n.id==a['id']:n=replace(n,active=False,merged_into=b['id'])
                else:n=replace(n,aliases=tuple(dict.fromkeys(list(n.aliases)+[a['label']]+a['aliases'])),memory_ids=tuple(dict.fromkeys(list(n.memory_ids)+a['memory_ids'])))
                append('knowledge_nodes',n);after.append(n.edit_id)
            for raw in edges:
                e=parse(Edge,raw);e=replace(e,edit_id=new_id(op,e.id),revision=e.revision+1,from_id=b['id'] if e.from_id==a['id'] else e.from_id,to_id=b['id'] if e.to_id==a['id'] else e.to_id,created_at=now);append('knowledge_edges',e);after.append(e.edit_id)
            result=append('graph_merges',Merge(id=op,project_id=project,source_id=a['id'],target_id=b['id'],before_nodes=(parse(Node,a),parse(Node,b)),before_edges=tuple(parse(Edge,e) for e in edges),after_edit_ids=tuple(after),created_at=now))
        elif action=='restore_merge':
            m=get(state['graph_merges'],v.get('merge_id'));require(not any(r['merge_id']==m['id'] for r in state['graph_restores']),'合并已恢复');nodes=latest(state['knowledge_nodes']);edges=latest(state['knowledge_edges'])
            current=[nodes[m['source_id']],nodes[m['target_id']]]+[e for e in edges.values() if e['from_id'] in (m['source_id'],m['target_id']) or e['to_id'] in (m['source_id'],m['target_id'])]
            require({x['edit_id'] for x in current}==set(m['after_edit_ids']),'合并后节点/关系有后续编辑或新增关系，恢复不能覆盖')
            for name,raws,model,values in (('knowledge_nodes',m['before_nodes'],Node,nodes),('knowledge_edges',m['before_edges'],Edge,edges)):
                for raw in raws:append(name,replace(parse(model,raw),revision=values[raw['id']]['revision']+1,edit_id=new_id(op,raw['id']),created_at=now))
            result=append('graph_restores',Restore(id=op,project_id=project,merge_id=m['id'],created_at=now))
        elif action in ('prepare_plan','set_plan_lock'):
            kind,identifier,field=v.get('target_kind'),v.get('target_id'),v.get('field');target=plan_target(state,kind,identifier,field);reason=bounded_text(v.get('reason'),'理由',4000,True)
            if action=='set_plan_lock':result=append('planning_locks',PlanLock(id=op,project_id=project,target_kind=kind,target_id=identifier,field=field,locked=bool_value(v.get('locked')),reason=reason,created_at=now))
            else:
                s=source(state,v.get('source'));require(s.kind in ('chapter','character','worldbuilding'),'反馈来源限已保存正文或结构资料，计划不能作为已发生事实');newtext=bounded_text(v.get('new_text'),'建议值');require(newtext!=target[field],'建议没有实际变化')
                result=append('planning_proposals',Plan(id=op,project_id=project,target_kind=kind,target_id=identifier,field=field,old_text=target[field],new_text=newtext,reason=reason,source=s,target=source(state,dict(kind=kind,entity_id=identifier)),impact=impact(state,s.chapter_id,kind,identifier,field),created_at=now))
        elif action=='decide_plan':
            p=get(state['planning_proposals'],v.get('proposal_id'));require(not any(r['proposal_id']==p['id'] for r in state['planning_receipts']),'提案已有处理收据');decision=v.get('decision');require(decision in ('accepted','rejected'),'提案决定非法');after=None
            if decision=='accepted':
                guarded(state,p['source']);guarded(state,p['target']);require(not locked(state,p['target_kind'],p['target_id'],p['field']),'目标字段已锁定，作者需明确解除');target=plan_target(state,p['target_kind'],p['target_id'],p['field']);require(target[p['field']]==p['old_text'],'目标值已变化')
                from novel_writer.storage.json_codec import document_from_dict,document_to_dict
                from novel_writer.application import book_outlines,chapter_outlines
                document=document_from_dict(state['document']);args={p['field']:p['new_text']}
                from novel_writer.application.book_creation import enforce_formal_locks
                enforce_formal_locks(state,'save_book_outline' if p['target_kind']=='book_outline' else 'save_chapter_outline',args)
                if p['target_kind']=='book_outline':book_outlines.save(document,args)
                else:args['chapter_id']=target['chapter_id'];chapter_outlines.save(document,args)
                state['document']=document_to_dict(document);after=state['document']['versions'][-1]['id']
            result=append('planning_receipts',PlanReceipt(id=op,project_id=project,proposal_id=p['id'],decision=decision,version_before=p['target']['version_id'],version_after=after,saved_revision=state['revision']+1,created_at=now))
        elif action in ('prepare_edit','revise_edit'):
            if action=='prepare_edit':
                issue=get(state['review_issues'],v.get('issue_id'));finding=issue['finding'];require(finding['rule_id'] in ('duplicate_exact','duplicate_near') and len(finding['evidence'])==2,'只能从真实双侧查重证据准备局部修改');side=v.get('side');require(type(side) is int and side in (0,1),'请选择双侧之一');e=finding['evidence'][side];require(e['source_kind']=='chapter','局部修改只作用于正文')
                guards=[]
                for ev in finding['evidence']:
                    dep=capture_dependency(state,ev['source_kind'],ev['entity_id'],use='target');require((dep.version_id,dep.source_sha256)==(ev['version_id'],ev['source_sha256']),'查重来源已变化，请重新审核');guards.append(dep)
                chapter=next(c for c in state['document']['chapters'] if c['id']==e['chapter_id']);before=chapter['content'];require(before[e['start']:e['end']]==e['quote'],'原文证据位置已变化')
                base=dict(id=op,project_id=project,edit_id=op,revision=1,issue_id=issue['id'],side=side,chapter_id=chapter['id'],start=e['start'],end=e['end'],before_text=before,evidence=tuple(parse(Evidence,x) for x in finding['evidence']),guards=tuple(guards),impact=impact(state,chapter['id']),created_at=now)
            else:
                p=get(state['local_edit_proposals'],v.get('proposal_id'));require(not any(r['proposal_id']==p['id'] for r in state['local_edit_receipts']),'已处理提案不能修订');base=encode(parse(LocalEdit|ModelLocalEdit,p));base.update(edit_id=op,revision=p['revision']+1,created_at=now);base['evidence']=tuple(parse(Evidence,x) for x in p['evidence']);base['guards']=tuple(parse(Dependency,x) for x in p['guards']);base['impact']=parse(Impact,p['impact']);base.pop('replacement');base.pop('mode');base.pop('reason');base.pop('after_text')
            replacement=bounded_text(v.get('replacement'),'替换文字');mode=v.get('mode');require(mode in ('delete','merge','rewrite') and (mode!='delete' or replacement==''),'修改类型/删除内容非法');reason=bounded_text(v.get('reason'),'修改理由',4000,True);after=base['before_text'][:base['start']]+replacement+base['before_text'][base['end']:];require(after!=base['before_text'],'没有实际正文变化')
            edit_type=ModelLocalEdit if 'model_proposal_id' in base else LocalEdit
            result=append('local_edit_proposals',edit_type(**base,mode=mode,replacement=replacement,reason=reason,after_text=after))
        else:
            p=get(state['local_edit_proposals'],v.get('proposal_id'));require(not any(r['proposal_id']==p['id'] for r in state['local_edit_receipts']),'局部提案已有决定');require(type(v.get('proposal_revision')) is int and v['proposal_revision']==p['revision'],'局部提案已修订，请核对最新差异');decision=v.get('decision');require(decision in ('accepted','rejected','cancelled'),'局部决定非法');authorize=bool_value(v.get('authorize_confirmed',False));before=next(g['version_id'] for g in p['guards'] if g['entity_id']==p['chapter_id']);after=None
            if decision=='accepted':
                for g in p['guards']:require(dependency_equal(parse(Dependency,g),capture_dependency(state,g['kind'],g['entity_id'],use=g['use'])),'双侧来源已变化，请重新审核')
                chapter=next(c for c in state['document']['chapters'] if c['id']==p['chapter_id']);require(chapter['content']==p['before_text'],'目标正文已改变')
                from novel_writer.storage.json_codec import document_from_dict,document_to_dict
                from novel_writer.application.chapters import save
                document=document_from_dict(state['document']);save(document,dict(chapter_id=p['chapter_id'],content=p['after_text'],status='draft',authorize_confirmed=authorize));state['document']=document_to_dict(document);after=state['document']['versions'][-1]['id']
            result=append('local_edit_receipts',EditReceipt(id=op,project_id=project,proposal_id=p['id'],proposal_revision=p['revision'],decision=decision,authorize_confirmed=authorize,chapter_id=p['chapter_id'],version_before=before,version_after=after,saved_revision=state['revision']+1,created_at=now))
        if _workflow is not None:_workflow(state,'after',result)
        return state,result
    return service.repository.atomic(project_id,apply,identity_claim=(*CLAIMS[action],op))

def enforce_plan_locks(state,action,values):
    kind={'save_book_outline':'book_outline','save_chapter_outline':'chapter_outline'}.get(action)
    if kind is None:return
    target=state['document']['book_outline'] if kind=='book_outline' else next((o for o in state['document']['chapter_outlines'] if o['chapter_id']==values.get('chapter_id')),None)
    if not target:return
    for field in PLAN_FIELDS[kind]:
        if field in values and values[field]!=target[field]:require(not locked(state,kind,target['id'],field),'此规划字段已锁定，请先明确解除')
