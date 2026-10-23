"""V45 quoted model graph proposals; only an explicit author decision creates facts."""
from dataclasses import dataclass
import json
from typing import Literal
from novel_writer.domain.knowledge import Value, Node, Edge, Source
from novel_writer.domain.model_contract import QuoteRef
from novel_writer.domain.review import Evidence, validate_evidence, text_digest
from novel_writer.domain.tasks import parse, encode, require, GenerationTask, capture_dependency, dependency_equal

PROMPT = 'graph-extract-json-1'


@dataclass(frozen=True, kw_only=True)
class WireNode(Value):
    key: str
    kind: Literal['character', 'location', 'organization', 'event', 'prop', 'setting', 'foreshadow']
    label: str
    aliases: tuple[str, ...]
    evidence: tuple[QuoteRef, ...]


@dataclass(frozen=True, kw_only=True)
class WireEdge(Value):
    from_key: str
    to_key: str
    relation: str
    evidence: tuple[QuoteRef, ...]


@dataclass(frozen=True, kw_only=True)
class WireGraph(Value):
    overview: str
    nodes: tuple[WireNode, ...]
    edges: tuple[WireEdge, ...]


@dataclass(frozen=True, kw_only=True)
class NodeDraft(WireNode):
    evidence: tuple[Evidence, ...]
    position_chapter_id: str


@dataclass(frozen=True, kw_only=True)
class EdgeDraft(WireEdge):
    evidence: tuple[Evidence, ...]
    position_chapter_id: str


@dataclass(frozen=True, kw_only=True)
class GraphOutput(Value):
    overview: str
    nodes: tuple[NodeDraft, ...]
    edges: tuple[EdgeDraft, ...]


@dataclass(frozen=True, kw_only=True)
class Extraction(Value):
    id: str
    project_id: str
    task_id: str
    response_record_id: str
    output: GraphOutput
    created_at: str


@dataclass(frozen=True, kw_only=True)
class Decision(Value):
    id: str
    project_id: str
    extraction_id: str
    decision: Literal['accepted', 'rejected', 'cancelled']
    confirm_inference: bool
    node_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    saved_revision: int
    created_at: str


COLLECTIONS = {'graph_extractions': Extraction, 'graph_decisions': Decision}


def is_graph(task):
    return getattr(getattr(task.frozen.parameters, 'binding', None), 'prompt_version', None) == PROMPT


def verify(raw, parameters):
    require(type(raw) is str and len(raw.encode('utf8')) <= 64 * 1024 * 1024, '图谱输出不是有界UTF-8文本')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, '图谱JSON含重复字段')
            result[key] = value
        return result
    def constant(value):
        require(False, '图谱JSON含非法数值常量')
    require(parameters.binding.prompt_version == PROMPT, '图谱提示版本不符')
    data = parse(WireGraph, json.loads(raw, object_pairs_hook=unique, parse_constant=constant))
    require(len(data.overview) <= 4000 and 1 <= len(data.nodes) <= 40 and len(data.edges) <= 80, '图谱提案数量超限或没有实体')
    keys = [n.key for n in data.nodes]
    require(len(keys) == len(set(keys)) and all(0 < len(k.strip()) <= 80 for k in keys), '图谱实体临时标识重复/非法')

    def evidence(refs):
        require(1 <= len(refs) <= 4, '每个实体和关系均须有1至4条精确引文')
        result = []
        for ref in refs:
            require(ref.source_index < len(parameters.sources), '图谱来源序号越界')
            s = parameters.sources[ref.source_index]
            require(s.kind == 'chapter', '图谱抽取仅允许已保存正文，计划不能作为事实')
            e = Evidence(source_kind=s.kind, entity_id=s.entity_id, chapter_id=s.chapter_id,
                         source_revision=s.source_revision, version_id=s.version_id,
                         source_sha256=s.source_sha256, field_path='content', start=ref.start,
                         end=ref.end, quote=ref.quote, quote_sha256=text_digest(ref.quote))
            validate_evidence(e, parameters.sources)
            result.append(e)
        last = max(result, key=lambda e: next(s.chapter_number for s in parameters.sources if s.entity_id == e.entity_id))
        return tuple(result), last.chapter_id

    nodes, edges = [], []
    for node in data.nodes:
        require(0 < len(node.label.strip()) <= 300 and len(node.aliases) <= 100 and
                len(set(node.aliases)) == len(node.aliases) and all(0 < len(a.strip()) <= 300 for a in node.aliases), '实体名称/别名非法')
        ev, position = evidence(node.evidence)
        nodes.append(NodeDraft(key=node.key, kind=node.kind, label=node.label, aliases=node.aliases, evidence=ev, position_chapter_id=position))
    for edge in data.edges:
        require(edge.from_key in keys and edge.to_key in keys and 0 < len(edge.relation.strip()) <= 300, '关系端点/名称非法')
        ev, position = evidence(edge.evidence)
        edges.append(EdgeDraft(from_key=edge.from_key, to_key=edge.to_key, relation=edge.relation,
                               evidence=ev, position_chapter_id=position))
    return GraphOutput(overview=data.overview, nodes=tuple(nodes), edges=tuple(edges))


def artifacts(state, extraction, decision):
    """Deterministic artifacts make repository-level acceptance independently checkable."""
    from uuid import uuid5, NAMESPACE_URL
    from novel_writer.domain.memory import capture_source
    output = extraction['output']
    ids = {n['key']: (decision['node_ids'][i] if decision['node_ids'] else str(uuid5(NAMESPACE_URL, decision['id'] + '/graph-node/' + n['key']))) for i, n in enumerate(output['nodes'])}
    nodes, edges = [], []

    def source(draft):
        return parse(Source, capture_source(state, dict(kind='chapter', entity_id=draft['position_chapter_id'])))

    for n in output['nodes']:
        identifier = ids[n['key']]
        nodes.append(encode(Node(id=identifier, project_id=decision['project_id'], edit_id=identifier, revision=1,
                                 kind=n['kind'], label=n['label'], aliases=tuple(n['aliases']), memory_ids=(),
                                 position_chapter_id=n['position_chapter_id'], source=source(n), basis='saved_source',
                                 confirmed=True, active=True, merged_into=None, created_at=decision['created_at'])))
    for index, e in enumerate(output['edges']):
        identifier = decision['edge_ids'][index] if decision['edge_ids'] else str(uuid5(NAMESPACE_URL, decision['id'] + '/graph-edge/' + str(index)))
        edges.append(encode(Edge(id=identifier, project_id=decision['project_id'], edit_id=identifier, revision=1,
                                 from_id=ids[e['from_key']], to_id=ids[e['to_key']], relation=e['relation'],
                                 position_chapter_id=e['position_chapter_id'], source=source(e), confirmed=True,
                                 active=True, created_at=decision['created_at'])))
    return nodes, edges


def validate_state(state):
    project = state['document']['project']['id']
    tasks = {t['id']: parse(GenerationTask, t) for t in state.get('generation_tasks', [])}
    responses = {r['id']: r for r in state.get('model_results', [])}
    parsed = {}
    for name, model in COLLECTIONS.items():
        values = state[name]
        require(type(values) is list and len(values) <= 30000, '图谱提案集合非法/超限')
        parsed[name] = [parse(model, v) for v in values]
        require(len({v.id for v in parsed[name]}) == len(values) and all(v.project_id == project for v in parsed[name]), '图谱提案身份重复或跨书')
    extractions = {e.id: e for e in parsed['graph_extractions']}
    require(len({e.task_id for e in extractions.values()}) == len(extractions), '图谱任务重复提案')
    for e in extractions.values():
        require(e.task_id in tasks and e.response_record_id in responses, '图谱提案缺少真实任务/响应')
        task, response = tasks[e.task_id], responses[e.response_record_id]
        require(is_graph(task) and task.status == 'succeeded' and response['task_id'] == task.id and response['response']['complete'], '图谱提案任务/响应归属不符')
        require(e.output == verify(response['response']['output_text'], task.frozen.parameters), '图谱提案与实际响应/引文不符')
    seen = set()
    for d in parsed['graph_decisions']:
        require(d.extraction_id in extractions and d.extraction_id not in seen and 1 <= d.saved_revision <= state['revision'], '图谱决定悬空/重复/版本非法')
        seen.add(d.extraction_id)
        if d.decision == 'accepted':
            e = extractions[d.extraction_id]
            require(d.confirm_inference and len(d.node_ids) == len(e.output.nodes) and len(d.edge_ids) == len(e.output.edges), '图谱接受未确认或实体/关系数量不符')
            require(len(set(d.node_ids)) == len(d.node_ids) and len(set(d.edge_ids)) == len(d.edge_ids), '图谱接受实体身份重复')
            for name, identifiers in (('knowledge_nodes', d.node_ids), ('knowledge_edges', d.edge_ids)):
                require(all(any(v['id'] == identifier and v['revision'] == 1 for v in state[name]) for identifier in identifiers), '图谱接受缺少正式历史')
        else:
            require(not d.node_ids and not d.edge_ids, '拒绝/取消不能生成正式图谱')


def validate_transition(state, previous):
    previous = previous or {}
    for name in COLLECTIONS:
        old = previous.get(name, [])
        require(state[name][:len(old)] == old, '图谱提案/决定历史只能追加')
    for d in state['graph_decisions'][len(previous.get('graph_decisions', [])):]:
        e = next((e for e in previous.get('graph_extractions', []) if e['id'] == d['extraction_id']), None)
        require(e is not None and d['saved_revision'] == state['revision'], '图谱决定须引用此前保存的提案')
        if d['decision'] != 'accepted':
            require(state['knowledge_nodes'] == previous.get('knowledge_nodes', []) and state['knowledge_edges'] == previous.get('knowledge_edges', []), '拒绝/取消不能附带图谱变更')
            continue
        task = parse(GenerationTask, next(t for t in previous['generation_tasks'] if t['id'] == e['task_id']))
        from novel_writer.domain.chapter_trash import is_hidden
        for dep in task.frozen.dependencies:
            require(not is_hidden(previous, dep.entity_id) and dependency_equal(dep, capture_dependency(previous, dep.kind, dep.entity_id, use=dep.use)), '图谱提案来源过期或已归档')
        nodes, edges = artifacts(previous, e, d)
        # Copy remaps node and edit IDs in separate declared namespaces.
        for expected, actual in ((nodes, state['knowledge_nodes'][len(previous.get('knowledge_nodes', [])):]),
                                 (edges, state['knowledge_edges'][len(previous.get('knowledge_edges', [])):])):
            require(len(expected) == len(actual), '图谱接受新增数量不符')
            for item, saved in zip(expected, actual):
                item['edit_id'] = saved['edit_id']
        require(d['node_ids'] == [v['id'] for v in nodes] and d['edge_ids'] == [v['id'] for v in edges], '图谱接受身份不符')
        require(state['knowledge_nodes'] == previous.get('knowledge_nodes', []) + nodes and state['knowledge_edges'] == previous.get('knowledge_edges', []) + edges, '图谱接受超出明确提案')
