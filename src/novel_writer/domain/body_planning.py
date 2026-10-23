"""V43 review envelopes around the existing F1 and C07 command contracts."""
from novel_writer.domain.models import _timestamp
from novel_writer.domain.tasks import require, uuid_value

COLLECTIONS = ('body_planning_proposals', 'body_planning_receipts',
               'body_planning_locks', 'planning_entity_lifecycle')
TARGETS = {'arc': 'character_arcs', 'stage': 'character_arc_stages',
           'event': 'key_events', 'dependency': 'chapter_dependencies'}


def archived(state, kind, identifier):
    rows = [v for v in state.get('planning_entity_lifecycle', [])
            if v['kind'] == kind and v['entity_id'] == identifier]
    return bool(rows and rows[-1]['archived'])


def locked(state, kind, identifier):
    rows = [v for v in state.get('body_planning_locks', [])
            if v['target_kind'] == kind and v['target_id'] == identifier]
    return bool(rows and rows[-1]['locked'])


def require_unlocked(state, kind, identifier):
    require(not locked(state, kind, identifier), '全书规划目标已锁定，须由作者先明确解锁')
    collection = TARGETS.get(kind)
    item = next((v for v in state.get(collection, []) if v['id'] == identifier), None) if collection else None
    if kind in ('stage', 'event') and item and item.get('arc_id'):
        require(not locked(state, 'arc', item['arc_id']), '所属人物弧光已锁定')


def validate_state(state):
    if state.get('workspace_version', 0) < 43:
        require(not any(k in state for k in COLLECTIONS), '正文规划提案需要V43')
        return
    project = state['document']['project']['id']
    from novel_writer.domain.knowledge import Source
    from novel_writer.domain.tasks import parse
    proposals = {}
    all_operations = set()
    for collection in COLLECTIONS:
        rows = state[collection]
        require(type(rows) is list and len(rows) <= 30000, '正文规划集合非法或超限')
        for row in rows:
            require(type(row) is dict and row.get('project_id') == project, '正文规划记录跨书')
            uuid_value(row['id']); uuid_value(row['operation_id']); _timestamp(row['created_at'], 'body_planning.created_at')
            require(row['operation_id'] not in all_operations, '正文规划操作身份重复')
            all_operations.add(row['operation_id'])
            require(type(row['request_sha256']) is str and len(row['request_sha256']) == 64, '正文规划请求摘要非法')
            common = {'id', 'project_id', 'operation_id', 'request_sha256', 'created_at'}
            if collection == 'body_planning_proposals':
                require(set(row) == common | {'source', 'quote', 'start', 'end', 'actions', 'reason', 'origin', 'baseline_sha256', 'planning_proposal_ids'}, '正文规划提案字段非法')
                source = parse(Source, row['source'])
                require(source.kind == 'chapter' and source.project_id == project and source.version_id is not None, '规划来源必须为已保存正文版本')
                versions = {v['id']: v for v in state['document']['versions']}
                version = versions.get(source.version_id)
                require(version is not None and version['entity_type'] == 'chapter' and version['entity_id'] == source.entity_id, '规划正文版本悬空')
                require(type(row['start']) is int and type(row['end']) is int and 0 <= row['start'] < row['end'], '规划引文范围非法')
                require(type(row['quote']) is str and 0 < len(row['quote']) <= 4000 and version['snapshot']['content'][row['start']:row['end']] == row['quote'], '规划引文不符已保存正文')
                from novel_writer.domain.full_book_planning import ACTIONS
                require(type(row['actions']) is list and 1 <= len(row['actions']) <= 20 and all(type(a) is dict and set(a) == {'action', 'values'} and a['action'] in (*ACTIONS, 'prepare_plan') and type(a['values']) is dict and not {'operation_id', 'expected_revision'} & set(a['values']) for a in row['actions']), '规划动作非法')
                require(row['origin'] in ('author', 'body_excerpt', 'ai_import') and type(row['reason']) is str and 0 < len(row['reason'].strip()) <= 4000, '规划来源/理由非法')
                require(type(row['baseline_sha256']) is str and len(row['baseline_sha256']) == 64, '规划基线摘要非法')
                linked=row['planning_proposal_ids']
                f1=[a for a in row['actions'] if a['action']=='prepare_plan']
                require(type(linked) is list and len(linked)==len(f1)<=1 and all(any(p['id']==identifier for p in state.get('planning_proposals',[])) for identifier in linked), '正文规划关联F1提案非法')
                if f1:
                    plan=next(p for p in state['planning_proposals'] if p['id']==linked[0]);values=f1[0]['values']
                    require(all(plan[k]==values.get(k) for k in ('target_kind','target_id','field','new_text')), '正文规划关联F1目标不符')
                require(row['id'] not in proposals, '规划提案ID重复'); proposals[row['id']] = row
            elif collection == 'body_planning_receipts':
                require(set(row) == common | {'proposal_id', 'decision', 'preview_sha256', 'saved_revision'}, '规划收据字段非法')
                require(row['proposal_id'] in proposals and row['decision'] in ('accepted', 'rejected'), '规划收据无提案/决定非法')
                require(type(row['preview_sha256']) is str and (len(row['preview_sha256']) == 64 if row['decision'] == 'accepted' else row['preview_sha256'] == ''), '规划收据预览非法')
                require(type(row['saved_revision']) is int and 1 <= row['saved_revision'] <= state['revision'], '规划收据版本非法')
            elif collection == 'body_planning_locks':
                require(set(row) == common | {'target_kind', 'target_id', 'locked', 'reason'}, '规划锁字段非法')
                require(row['target_kind'] in TARGETS and any(v['id'] == row['target_id'] for v in state.get(TARGETS[row['target_kind']], [])), '规划锁目标不存在')
                require(type(row['locked']) is bool and type(row['reason']) is str and 0 < len(row['reason'].strip()) <= 4000, '规划锁参数非法')
            else:
                require(set(row) == common | {'kind', 'entity_id', 'archived'}, '规划实体生命周期字段非法')
                require(row['kind'] in ('character', 'knowledge_node') and type(row['archived']) is bool, '规划生命周期参数非法')
                items = state['document']['characters'] if row['kind'] == 'character' else state.get('knowledge_nodes', [])
                require(any(v['id'] == row['entity_id'] for v in items), '规划生命周期对象不存在')
    receipts = state['body_planning_receipts']
    require(len({r['proposal_id'] for r in receipts}) == len(receipts), '规划提案已有决定')


def validate_transition(state, previous):
    for collection in COLLECTIONS:
        before = previous.get(collection, [])
        require(state.get(collection, [])[:len(before)] == before, '正文规划历史不可删除/改写/重排')
    # Locks also protect direct repository writes and any future command adapter.
    for kind, collection in TARGETS.items():
        before = {v['id']: v for v in previous.get(collection, [])}
        after = {v['id']: v for v in state.get(collection, [])}
        for identifier, value in before.items():
            if locked(previous, kind, identifier):
                require(after.get(identifier) == value, '正式变更不可绕过全书规划锁')
        if kind in ('stage', 'event'):
            for identifier, value in after.items():
                if value.get('arc_id') and locked(previous, 'arc', value['arc_id']):
                    require(before.get(identifier) == value, '正式变更不可绕过所属弧光锁')
    for receipt in state.get('body_planning_receipts', [])[len(previous.get('body_planning_receipts', [])):]:
        require(any(p['id'] == receipt['proposal_id'] for p in previous.get('body_planning_proposals', [])), '正文规划决定须引用此前已保存提案')
        require(receipt['saved_revision'] == state['revision'], '正文规划决定保存版本不符')
