"""Bounded, deterministic path queries over the visible saved-source graph."""
from collections import deque
from novel_writer.application.fields import check_fields
from novel_writer.domain.tasks import require


def paths(service, project_id, options):
    from novel_writer.application.knowledge import view
    check_fields(options, {'from_id', 'to_id', 'chapter_id', 'max_depth',
                           'max_paths', 'direction', 'relations'})
    depth = options.get('max_depth', 4)
    limit = options.get('max_paths', 20)
    require(type(depth) is int and 1 <= depth <= 6, '路径深度限1至6')
    require(type(limit) is int and 1 <= limit <= 50, '路径数量限1至50')
    direction = options.get('direction', 'outgoing')
    require(direction in ('outgoing', 'incoming', 'both'), '路径方向非法')
    relations = options.get('relations', [])
    require(type(relations) is list and len(relations) <= 20 and
            all(type(x) is str and 0 < len(x) <= 300 for x in relations), '关系过滤非法')
    graph = view(service, project_id, dict(chapter_id=options.get('chapter_id'), ready_only=True))
    ids = {n['id'] for n in graph['nodes']}
    start, goal = options.get('from_id'), options.get('to_id')
    require(start in ids and goal in ids, '路径端点不存在、过期、未确认或晚于当前章位')
    adjacency = {identifier: [] for identifier in ids}
    for edge in sorted(graph['edges'], key=lambda e: e['id']):
        if relations and edge['relation'] not in relations:
            continue
        if direction in ('outgoing', 'both'):
            adjacency[edge['from_id']].append((edge['to_id'], edge['id']))
        if direction in ('incoming', 'both'):
            adjacency[edge['to_id']].append((edge['from_id'], edge['id']))
    queue = deque([([start], [])])
    found, expansions = [], 0
    truncated = False
    while queue:
        nodes, edges = queue.popleft()
        if nodes[-1] == goal:
            found.append(dict(node_ids=nodes, edge_ids=edges))
            if len(found) >= limit:
                truncated = bool(queue)
                break
            continue
        if len(edges) >= depth:
            continue
        for neighbor, edge_id in adjacency[nodes[-1]]:
            if neighbor in nodes:
                continue
            expansions += 1
            if expansions > 5000:
                truncated = True
                break
            queue.append((nodes + [neighbor], edges + [edge_id]))
        if truncated:
            break
    return dict(project_id=project_id, revision=graph['revision'], paths=found,
                truncated=truncated, expansions=min(expansions, 5000),
                limits=dict(max_depth=depth, max_paths=limit, expansions=5000),
                method='confirmed_fresh_saved_links_only')
