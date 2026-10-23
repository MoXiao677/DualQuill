"""Disposable incremental graph index, rebuilt explicitly without editing source history."""
from copy import deepcopy
from hashlib import sha256
import json
import threading
from novel_writer.application.fields import check_fields
from novel_writer.domain.tasks import require

_lock = threading.RLock()


def sync(service, state, *, force=False):
    project = state['document']['project']['id']
    with _lock:
        if not hasattr(service, '_graph_indexes'):
            service._graph_indexes = {}
        caches = service._graph_indexes
        cache = caches.get(project)
        histories = {name: state.get(name, []) for name in ('knowledge_nodes', 'knowledge_edges')}
        if force or cache is None or any(len(histories[name]) < cache['counts'][name] or
                (cache['counts'][name] and histories[name][cache['counts'][name]-1]['edit_id'] != cache['tails'][name]) for name in histories):
            cache = dict(counts={name: 0 for name in histories}, tails={name: None for name in histories},
                         knowledge_nodes={}, knowledge_edges={})
        for name, history in histories.items():
            for item in history[cache['counts'][name]:]:
                cache[name][item['id']] = deepcopy(item)
            cache['counts'][name] = len(history)
            cache['tails'][name] = history[-1]['edit_id'] if history else None
        caches[project] = cache
        return {name: deepcopy(cache[name]) for name in histories}


def rebuild(service, project, options):
    check_fields(options, {'expected_revision'})
    state = service.get(project)
    require(type(options.get('expected_revision')) is int and options['expected_revision'] == state['revision'], '重建前保存编号已变化')
    index = sync(service, state, force=True)
    raw = json.dumps(index, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf8')
    return dict(project_id=project, revision=state['revision'], index_sha256=sha256(raw).hexdigest(),
                node_count=len(index['knowledge_nodes']), edge_count=len(index['knowledge_edges']),
                method='rebuild_from_append_only_graph_history', source_unchanged=True)


def quoted_provenance(state):
    """Every quote remains linked even when its formal node has one primary source."""
    outputs = {e['id']: e['output'] for e in state.get('graph_extractions', [])}
    nodes, edges = {}, {}
    for receipt in state.get('graph_decisions', []):
        if receipt['decision'] != 'accepted':
            continue
        output = outputs[receipt['extraction_id']]
        for mapping, key, drafts in ((nodes, 'node_ids', output['nodes']), (edges, 'edge_ids', output['edges'])):
            for identifier, draft in zip(receipt[key], drafts):
                mapping[identifier] = deepcopy(draft['evidence'])
    restored = {r['merge_id'] for r in state.get('graph_restores', [])}
    for merge in state.get('graph_merges', []):
        if merge['id'] not in restored:
            target = merge['target_id']
            combined = nodes.get(target, []) + nodes.get(merge['source_id'], [])
            nodes[target] = list({json.dumps(e, sort_keys=True, ensure_ascii=False): e for e in combined}.values())
    return nodes, edges


def merged_sources(state, nodes):
    sources = {identifier: [n['source']] for identifier, n in nodes.items()}
    restored = {r['merge_id'] for r in state.get('graph_restores', [])}
    for merge in state.get('graph_merges', []):
        if merge['id'] not in restored:
            sources[merge['target_id']] = sources.get(merge['target_id'], []) + sources.get(merge['source_id'], [])
    return sources


def quotes_fresh(state, evidence):
    from novel_writer.domain.memory import capture_source
    from novel_writer.application.chapter_lifecycle import is_hidden
    for e in evidence:
        try:
            actual = capture_source(state, dict(kind=e['source_kind'], entity_id=e['entity_id']))
            if is_hidden(state, e['chapter_id']) or (actual['version_id'], actual['source_sha256']) != (e['version_id'], e['source_sha256']):
                return False
        except ValueError:
            return False
    return True
"""Disposable incremental graph index, rebuilt explicitly without editing source history."""
from copy import deepcopy
from hashlib import sha256
import json
import threading
from novel_writer.application.fields import check_fields
from novel_writer.domain.tasks import require

_lock = threading.RLock()


def sync(service, state, *, force=False):
    project = state['document']['project']['id']
    with _lock:
        if not hasattr(service, '_graph_indexes'):
            service._graph_indexes = {}
        caches = service._graph_indexes
        cache = caches.get(project)
        histories = {name: state.get(name, []) for name in ('knowledge_nodes', 'knowledge_edges')}
        if force or cache is None or any(len(histories[name]) < cache['counts'][name] or
                (cache['counts'][name] and histories[name][cache['counts'][name]-1]['edit_id'] != cache['tails'][name]) for name in histories):
            cache = dict(counts={name: 0 for name in histories}, tails={name: None for name in histories},
                         knowledge_nodes={}, knowledge_edges={})
        for name, history in histories.items():
            for item in history[cache['counts'][name]:]:
                cache[name][item['id']] = deepcopy(item)
            cache['counts'][name] = len(history)
            cache['tails'][name] = history[-1]['edit_id'] if history else None
        caches[project] = cache
        return {name: deepcopy(cache[name]) for name in histories}


def rebuild(service, project, options):
    check_fields(options, {'expected_revision'})
    state = service.get(project)
    require(type(options.get('expected_revision')) is int and options['expected_revision'] == state['revision'], '重建前保存编号已变化')
    index = sync(service, state, force=True)
    raw = json.dumps(index, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf8')
    return dict(project_id=project, revision=state['revision'], index_sha256=sha256(raw).hexdigest(),
                node_count=len(index['knowledge_nodes']), edge_count=len(index['knowledge_edges']),
                method='rebuild_from_append_only_graph_history', source_unchanged=True)


def quoted_provenance(state):
    """Every quote remains linked even when its formal node has one primary source."""
    outputs = {e['id']: e['output'] for e in state.get('graph_extractions', [])}
    nodes, edges = {}, {}
    for receipt in state.get('graph_decisions', []):
        if receipt['decision'] != 'accepted':
            continue
        output = outputs[receipt['extraction_id']]
        for mapping, key, drafts in ((nodes, 'node_ids', output['nodes']), (edges, 'edge_ids', output['edges'])):
            for identifier, draft in zip(receipt[key], drafts):
                mapping[identifier] = deepcopy(draft['evidence'])
    for receipt in state.get('graph_item_decisions', []):
        if receipt['decision'] != 'accepted':continue
        kind=receipt['item_kind'];key='node_ids' if kind=='node' else 'edge_ids'
        draft=outputs[receipt['extraction_id']]['nodes' if kind=='node' else 'edges'][receipt['item_index']]
        (nodes if kind=='node' else edges)[receipt[key][0]]=deepcopy(draft['evidence'])
    restored = {r['merge_id'] for r in state.get('graph_restores', [])}
    for merge in state.get('graph_merges', []):
        if merge['id'] not in restored:
            target = merge['target_id']
            combined = nodes.get(target, []) + nodes.get(merge['source_id'], [])
            nodes[target] = list({json.dumps(e, sort_keys=True, ensure_ascii=False): e for e in combined}.values())
    return nodes, edges


def merged_sources(state, nodes):
    sources = {identifier: [n['source']] for identifier, n in nodes.items()}
    restored = {r['merge_id'] for r in state.get('graph_restores', [])}
    for merge in state.get('graph_merges', []):
        if merge['id'] not in restored:
            sources[merge['target_id']] = sources.get(merge['target_id'], []) + sources.get(merge['source_id'], [])
    return sources


def quotes_fresh(state, evidence):
    from novel_writer.domain.memory import capture_source
    from novel_writer.application.chapter_lifecycle import is_hidden
    for e in evidence:
        try:
            actual = capture_source(state, dict(kind=e['source_kind'], entity_id=e['entity_id']))
            if is_hidden(state, e['chapter_id']) or (actual['version_id'], actual['source_sha256']) != (e['version_id'], e['source_sha256']):
                return False
        except ValueError:
            return False
    return True
