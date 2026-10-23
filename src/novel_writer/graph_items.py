"""V50 append-only individual decisions; original V45 responses stay immutable."""
from copy import deepcopy
from dataclasses import dataclass
from typing import Literal
from novel_writer.domain.graph_extraction import Decision, artifacts
from novel_writer.domain.tasks import parse, encode, require, digest

COLLECTION = 'graph_item_decisions'


@dataclass(frozen=True, kw_only=True)
class ItemDecision(Decision):
    item_kind: Literal['node', 'edge']
    item_index: int


def scope(state, extraction):
    task = next(t for t in state['generation_tasks'] if t['id'] == extraction['task_id'])
    return frozenset(s['entity_id'] for s in task['frozen']['parameters']['sources'])


def superseded(state, extraction):
    values = state.get('graph_extractions', [])
    index = next(i for i, e in enumerate(values) if e['id'] == extraction['id'])
    selected = scope(state, extraction)
    return any(scope(state, e) == selected for e in values[index + 1:])


def draft(extraction, receipt):
    values = extraction['output']['nodes' if receipt['item_kind'] == 'node' else 'edges']
    require(type(receipt['item_index']) is int and 0 <= receipt['item_index'] < len(values), '图谱候选序号越界')
    return values[receipt['item_index']]


def accepted_nodes(state, extraction):
    return {draft(extraction, r)['key']: r['node_ids'][0]
            for r in state.get(COLLECTION, []) if r['extraction_id'] == extraction['id']
            and r['item_kind'] == 'node' and r['decision'] == 'accepted'}


def item_artifacts(state, extraction, receipt):
    item = draft(extraction, receipt)
    # Reuse V45 formal graph construction, but never insert unreviewed endpoints.
    subset = deepcopy(extraction)
    generated = dict(receipt, node_ids=[], edge_ids=[])
    if receipt['item_kind'] == 'node':
        subset['output'].update(nodes=[item], edges=[])
        if receipt['node_ids']:
            generated['node_ids'] = receipt['node_ids']
        return artifacts(state, subset, generated)
    identifiers = accepted_nodes(state, extraction)
    require(item['from_key'] in identifiers and item['to_key'] in identifiers, '须先逐条接受关系两端实体')
    subset['output']['edges'] = [item]
    subset['output']['nodes'] = [n for n in subset['output']['nodes'] if n['key'] in (item['from_key'], item['to_key'])]
    generated['node_ids'] = [identifiers[n['key']] for n in subset['output']['nodes']]
    generated['edge_ids'] = receipt['edge_ids']
    _, edges = artifacts(state, subset, generated)
    return [], edges


def validate_state(state):
    receipts = state.get(COLLECTION, [])
    require(type(receipts) is list and len(receipts) <= 30000, '图谱单条决定集合非法/超限')
    require(state['workspace_version'] >= 50 or not receipts, '图谱单条决定需要V50')
    extractions = {e['id']: e for e in state.get('graph_extractions', [])}
    seen, ids = set(), set()
    bulk = {r['extraction_id'] for r in state.get('graph_decisions', [])}
    for raw in receipts:
        r = parse(ItemDecision, raw)
        identity = (r.extraction_id, r.item_kind, r.item_index)
        require(r.id not in ids and identity not in seen and r.extraction_id in extractions
                and r.extraction_id not in bulk and r.project_id == state['document']['project']['id']
                and 1 <= r.saved_revision <= state['revision'], '图谱单条决定重复/跨书/悬空/版本非法')
        ids.add(r.id)
        seen.add(identity)
        draft(extractions[r.extraction_id], raw)
        if r.decision == 'accepted':
            require(r.confirm_inference and len(r.node_ids) == (r.item_kind == 'node')
                    and len(r.edge_ids) == (r.item_kind == 'edge'), '图谱单条接受数量/确认非法')
            for name, values in (('knowledge_nodes', r.node_ids), ('knowledge_edges', r.edge_ids)):
                require(all(any(v['id'] == identifier and v['revision'] == 1 for v in state[name]) for identifier in values), '单条图谱接受缺少正式历史')
        else:
            require(not r.node_ids and not r.edge_ids, '单条拒绝/取消不能生成图谱')


def validate_transition(state, previous):
    previous = previous or {}
    old = previous.get(COLLECTION, [])
    current = state.get(COLLECTION, [])
    require(current[:len(old)] == old, '图谱单条决定只能追加')
    additions = current[len(old):]
    require(len(additions) <= 1, '每次仅允许一个明确的图谱候选决定')
    for r in additions:
        extraction = next((e for e in previous.get('graph_extractions', []) if e['id'] == r['extraction_id']), None)
        require(extraction is not None and not superseded(previous, extraction)
                and r['saved_revision'] == state['revision'], '图谱候选已被新抽取覆盖或不属于此前状态')
        nodes, edges = [], []
        if r['decision'] == 'accepted':
            from novel_writer.domain.tasks import GenerationTask, capture_dependency, dependency_equal
            from novel_writer.domain.chapter_trash import is_hidden
            task = parse(GenerationTask, next(t for t in previous['generation_tasks'] if t['id'] == extraction['task_id']))
            for dep in task.frozen.dependencies:
                require(not is_hidden(previous, dep.entity_id) and dependency_equal(dep, capture_dependency(previous, dep.kind, dep.entity_id, use=dep.use)), '图谱单条来源过期/归档')
            nodes, edges = item_artifacts(previous, extraction, r)
            for expected, actual in ((nodes, state['knowledge_nodes'][len(previous.get('knowledge_nodes', [])):]),
                                     (edges, state['knowledge_edges'][len(previous.get('knowledge_edges', [])):])):
                require(len(expected) == len(actual), '图谱单条新增数量不符')
                for item, saved in zip(expected, actual):
                    item['edit_id'] = saved['edit_id']  # copy uses a separate edit namespace
        require(r['node_ids'] == [v['id'] for v in nodes] and r['edge_ids'] == [v['id'] for v in edges], '图谱单条正式身份不符')
        require(state['knowledge_nodes'] == previous.get('knowledge_nodes', []) + nodes
                and state['knowledge_edges'] == previous.get('knowledge_edges', []) + edges, '图谱单条决定附带了未授权变更')
