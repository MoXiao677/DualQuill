"""Saved-body proposals: preview, explicit atomic decision, locks and lifecycle."""
from copy import deepcopy
import threading
from uuid import NAMESPACE_URL, uuid4, uuid5

from novel_writer.application.fields import check_fields
from novel_writer.application.planning_preview import simulate, prepare_f1, reject_f1
from novel_writer.domain.body_planning import COLLECTIONS, TARGETS, archived
from novel_writer.domain.book_creation import fingerprint
from novel_writer.domain.chapter_trash import hidden_ids
from novel_writer.domain.memory import capture_source, outdated
from novel_writer.domain.models import utc_now
from novel_writer.domain.tasks import require, uuid_value
from novel_writer.storage.sqlite_repository import ConflictError


def upgrade(state):
    from novel_writer.application.chapter_lifecycle import upgrade as previous
    previous(state)
    state.setdefault('rule_task_bindings', [])
    state.setdefault('deep_review_actions', [])
    state.setdefault('memory_automation_events', [])
    state['workspace_version'] = max(state['workspace_version'], 43)
    for collection in COLLECTIONS:
        state.setdefault(collection, [])
    return state


def formal_fingerprint(state):
    names = ('document', 'ideas', 'worldbuilding', 'writing_rules', 'character_arcs',
             'character_arc_stages', 'key_events', 'chapter_dependencies', 'chapter_lifecycle_events',
             'chapter_trash_events', 'planning_locks', 'book_creation_locks', 'body_planning_locks', 'planning_entity_lifecycle',
             'knowledge_nodes', 'knowledge_edges', 'memories')
    return fingerprint({k: state.get(k, [] if k not in ('worldbuilding', 'writing_rules') else '') for k in names})


def proposal_of(state, identifier):
    item = next((v for v in state.get('body_planning_proposals', []) if v['id'] == identifier), None)
    if item is None:
        raise KeyError('正文规划提案不存在或不属于当前书')
    return item


def fresh(state, proposal):
    return (not outdated(state, proposal['source']) and proposal['source']['entity_id'] not in hidden_ids(state)
            and formal_fingerprint(state) == proposal['baseline_sha256'])


def evidence(state, values):
    chapter = next((c for c in state['document']['chapters'] if c['id'] == values.get('chapter_id')), None)
    require(chapter is not None and chapter['id'] not in hidden_ids(state), '须选择本书启用的已保存章节')
    start, end, quote = values.get('start'), values.get('end'), values.get('quote')
    require(type(start) is int and type(end) is int and type(quote) is str and 0 <= start < end <= len(chapter['content'])
            and 0 < len(quote) <= 4000 and chapter['content'][start:end] == quote, '引文须精确匹配已保存正文（Unicode字符偏移）')
    source = capture_source(state, dict(kind='chapter', entity_id=chapter['id']))
    require(source['version_id'] is not None, '正文尚无已保存版本')
    return source


def record(project, operation, request):
    return dict(id=operation, project_id=project, operation_id=operation,
                request_sha256=fingerprint({k: v for k, v in request.items() if k not in ('operation_id', 'expected_revision')}),
                created_at=utc_now())


def check_revision(state, request):
    if type(request.get('expected_revision')) is not int or request['expected_revision'] != state['revision']:
        raise ConflictError('保存版本已变化，请保留输入并重新预览')


class BodyPlanning:
    def __init__(self, service):
        self.service, self.repository = service, service.repository
        if not hasattr(service, '_body_planning_previews'):
            service._body_planning_previews = ({}, threading.Lock())
        self.previews, self.preview_lock = service._body_planning_previews

    def listing(self, project):
        state = self.service.get(project)
        receipts = {r['proposal_id']: r for r in state.get('body_planning_receipts', [])}
        from novel_writer.domain.knowledge import latest
        entities = [dict(kind='character', entity_id=c['id'], label=c['name'], archived=archived(state, 'character', c['id']))
                    for c in state['document']['characters']]
        entities += [dict(kind='knowledge_node', entity_id=n['id'], label=n['label'], archived=archived(state, 'knowledge_node', n['id']))
                     for n in latest(state.get('knowledge_nodes', [])).values()]
        return dict(revision=state['revision'], proposals=[dict(p, outdated=not fresh(state, p), receipt=receipts.get(p['id']))
                    for p in state.get('body_planning_proposals', [])], locks=state.get('body_planning_locks', []),
                    lifecycle=state.get('planning_entity_lifecycle', []), entities=entities, model_request_sent=False,
                    ai_completion=dict(status='native_model_and_review_import_available',
                        reason='可逐请求冻结并确认原生模型建议，也可导入；结果仅为待核实候选，须独立转提案、影响预览及人工接受'))

    def _write(self, project, request, collection, apply):
        identity = uuid_value(request.get('operation_id'))
        base = record(project, identity, request)
        def operation(state):
            for name in COLLECTIONS:
                old = next((v for v in state.get(name, []) if v['operation_id'] == identity), None)
                if old is not None:
                    require(name == collection and old['request_sha256'] == base['request_sha256'], '规划操作身份已绑定其它请求')
                    return None, deepcopy(old)
            check_revision(state, request)
            upgrade(state)
            result = apply(state, base)
            state[collection].append(result)
            return state, result
        return self.repository.atomic(project, operation, identity_claim=(collection, 'operation_id', identity))

    def prepare(self, project, request):
        check_fields(request, {'operation_id', 'expected_revision', 'chapter_id', 'start', 'end', 'quote', 'actions', 'reason', 'origin'})
        def apply(state, base):
            source = evidence(state, request)
            reason, origin = request.get('reason'), request.get('origin', 'author')
            require(type(reason) is str and 0 < len(reason.strip()) <= 4000, '规划提案须有理由')
            require(origin in ('author', 'body_excerpt', 'ai_import'), '规划提案来源非法')
            actions = deepcopy(request.get('actions'))
            require(type(actions) is list and sum(a.get('action') == 'prepare_plan' for a in actions if type(a) is dict) <= 1,
                    '每个正文规划提案最多含一个F1字段；多个字段请逐项提案和复核')
            for action in actions if type(actions) is list else []:
                if type(action) is dict and action.get('action') == 'prepare_plan':
                    require(action.get('values', {}).get('source') == dict(kind='chapter', entity_id=source['entity_id']), 'F1提案须绑定同一已保存正文')
                if type(action) is dict and action.get('action') in ('occur_stage', 'occur_event'):
                    values = action.get('values', {})
                    require(values.get('occurrence_chapter_id') == source['entity_id'] and values.get('body_reference') == request['quote'], '发生记录须保留本次已保存正文精确引文')
            simulate(state, actions, base['id'])
            state.update(prepare_f1(state, actions, base['id']))
            return dict(base, source=source, start=request['start'], end=request['end'], quote=request['quote'],
                        actions=actions, reason=reason, origin=origin, baseline_sha256=formal_fingerprint(state),
                        planning_proposal_ids=[str(uuid5(NAMESPACE_URL, base['id'] + '/change/' + str(i)))
                                               for i,a in enumerate(actions) if a['action']=='prepare_plan'])
        return self._write(project, request, 'body_planning_proposals', apply)

    def preview_state(self, state, identifier):
        proposal = proposal_of(state, identifier)
        from novel_writer.application.model_planning import revalidate_proposal
        revalidate_proposal(self.service, state, identifier)
        require(not any(r['proposal_id'] == identifier for r in state.get('body_planning_receipts', [])), '提案已有决定')
        if not fresh(state, proposal):
            raise ConflictError('正文、计划、引用或锁定项已变化，旧提案不可接受；请重新准备')
        changed, deviation = simulate(state, proposal['actions'], identifier, proposal['planning_proposal_ids'])
        from novel_writer.application.knowledge import impact
        source_id = proposal['source']['entity_id']
        diff = []
        for name in ('character_arcs', 'character_arc_stages', 'key_events', 'chapter_dependencies'):
            before = {v['id']: v for v in state.get(name, [])}
            for item in changed.get(name, []):
                if before.get(item['id']) != item:
                    diff.append(dict(collection=name, entity_id=item['id'], before=deepcopy(before.get(item['id'])), after=deepcopy(item)))
        for action in proposal['actions']:
            if action['action'] == 'prepare_plan':
                values = action['values']; kind, target_id, field = values['target_kind'], values['target_id'], values['field']
                from novel_writer.domain.knowledge import plan_target
                diff.append(dict(collection=kind, entity_id=target_id, field=field,
                                 before=plan_target(state, kind, target_id, field)[field], after=values['new_text']))
        value = dict(project_id=state['document']['project']['id'], proposal_id=identifier, revision=state['revision'],
                     source=proposal['source'], quote=proposal['quote'], actions=proposal['actions'], changes=diff,
                     deviation=deviation, impact=impact(state, source_id).__dict__, quality_verified=False,
                     limitations=['仅基于已保存正文引文、作者或导入建议和结构位置；不验证语义因果；不会改写正文。'])
        # Includes proposal, current revision, diff and impacts; no stored preview grants permission.
        # Simulation creates normal append-only version IDs/timestamps. Bind the
        # immutable proposal and complete formal baseline, not those fresh IDs.
        value['preview_sha256'] = fingerprint(dict(project_id=value['project_id'], proposal=proposal,
                                                  revision=state['revision'], formal_sha256=formal_fingerprint(state)))
        return value

    def preview(self, project, request):
        check_fields(request, {'proposal_id'})
        value = self.preview_state(self.service.get(project), request.get('proposal_id'))
        baseline = value['preview_sha256']
        token = fingerprint(dict(baseline=baseline, nonce=str(uuid4())))
        with self.preview_lock:
            self.previews[(project, value['proposal_id'])] = dict(baseline=baseline, token=token)
        value['preview_sha256'] = token
        return value

    def infer(self, project, request):
        """Literal matching only: produce a pending proposal, never an occurrence."""
        check_fields(request, {'operation_id', 'expected_revision', 'chapter_id', 'start', 'end', 'quote'})
        state = self.service.get(project)
        existing = next((p for p in state.get('body_planning_proposals', []) if p['operation_id'] == request.get('operation_id')), None)
        if existing is not None:
            require(existing['origin'] == 'body_excerpt' and existing['source']['entity_id'] == request.get('chapter_id')
                    and all(existing[k] == request.get(k) for k in ('start', 'end', 'quote')), '标题匹配操作身份已绑定其它来源')
            return self.prepare(project, dict(request, actions=existing['actions'], reason=existing['reason'], origin='body_excerpt'))
        check_revision(state, request); source = evidence(state, request); upgrade(state)
        actions = []
        for collection, action, key in (('key_events', 'occur_event', 'event_id'), ('character_arc_stages', 'occur_stage', 'stage_id')):
            for item in state[collection]:
                if item['status'] == 'planned' and len(item['title']) >= 2 and item['title'] in request['quote']:
                    actions.append(dict(action=action, values={key:item['id'], 'occurrence_chapter_id':source['entity_id'], 'body_reference':request['quote']}))
        require(actions, '所选已保存引文没有匹配的计划事件/阶段标题；请手动提出或导入建议')
        require(len(actions) <= 20, '标题匹配超过20项，请缩小引文范围')
        return self.prepare(project, dict(request, actions=actions, reason='正文原文精确包含计划标题；仅为待核实建议，不代表语义发生已确认', origin='body_excerpt'))

    def decide(self, project, request):
        check_fields(request, {'operation_id', 'expected_revision', 'proposal_id', 'decision', 'preview_sha256'})
        def apply(state, base):
            identifier, decision = request.get('proposal_id'), request.get('decision')
            proposal_of(state, identifier)
            require(decision in ('accepted', 'rejected'), '须明确接受或拒绝')
            require(not any(r['proposal_id'] == identifier for r in state['body_planning_receipts']), '提案已有决定')
            token = ''
            if decision == 'accepted':
                preview = self.preview_state(state, identifier)
                with self.preview_lock:
                    issued = self.previews.get((project, identifier))
                if not issued or issued['baseline'] != preview['preview_sha256'] or request.get('preview_sha256') != issued['token']:
                    raise ConflictError('影响预览已变化，请重新预览并确认')
                token = issued['token']
                proposal=proposal_of(state, identifier)
                changed, _ = simulate(state, proposal['actions'], identifier, proposal['planning_proposal_ids'])
                state.update(changed)
            else:
                proposal=proposal_of(state, identifier)
                state.update(reject_f1(state, proposal['actions'], identifier, proposal['planning_proposal_ids']))
            return dict(base, proposal_id=identifier, decision=decision, preview_sha256=token, saved_revision=state['revision'] + 1)
        result = self._write(project, request, 'body_planning_receipts', apply)
        with self.preview_lock:
            self.previews.pop((project, request.get('proposal_id')), None)
        return result

    def set_lock(self, project, request):
        check_fields(request, {'operation_id', 'expected_revision', 'target_kind', 'target_id', 'locked', 'reason'})
        def apply(state, base):
            kind, identifier = request.get('target_kind'), request.get('target_id')
            require(kind in TARGETS and any(v['id'] == identifier for v in state[TARGETS[kind]]), '规划锁定目标不存在')
            require(type(request.get('locked')) is bool and type(request.get('reason')) is str and 0 < len(request['reason'].strip()) <= 4000, '须明确锁定状态与理由')
            return dict(base, target_kind=kind, target_id=identifier, locked=request['locked'], reason=request['reason'])
        return self._write(project, request, 'body_planning_locks', apply)

    def lifecycle(self, project, request):
        check_fields(request, {'operation_id', 'expected_revision', 'kind', 'entity_id', 'archived', 'confirm'})
        def apply(state, base):
            kind, identifier = request.get('kind'), request.get('entity_id')
            self.references_state(state, kind, identifier)
            require(type(request.get('archived')) is bool and request.get('confirm') is True, '归档/恢复须明确确认；引用不会删除')
            require(archived(state, kind, identifier) != request['archived'], '实体已处于该归档状态')
            return dict(base, kind=kind, entity_id=identifier, archived=request['archived'])
        return self._write(project, request, 'planning_entity_lifecycle', apply)

    def references_state(self, state, kind, identifier):
        require(kind in ('character', 'knowledge_node'), '仅支持人物与结构化知识节点')
        items = state['document']['characters'] if kind == 'character' else state.get('knowledge_nodes', [])
        require(any(v['id'] == identifier for v in items), '生命周期对象不存在或跨书')
        references = []
        def scan(value, path):
            if isinstance(value, dict):
                for k, child in value.items():
                    if k not in ('versions', 'content'):
                        scan(child, path + '/' + k)
            elif isinstance(value, list):
                for index, child in enumerate(value): scan(child, path + '/' + str(index))
            elif value == identifier: references.append(path)
        for name in ('document', 'character_arcs', 'key_events', 'memories', 'knowledge_nodes', 'knowledge_edges'):
            scan(state.get(name, []), name)
        return dict(kind=kind, entity_id=identifier, archived=archived(state, kind, identifier), references=references,
                    revision=state['revision'], note='归档仅影响新规划选择；稳定ID、既有引用和历史完整保留，可显式恢复。')

    def references(self, project, request):
        check_fields(request, {'kind', 'entity_id'})
        return self.references_state(self.service.get(project), request.get('kind'), request.get('entity_id'))

    def completion(self, project, request):
        """Offline, inspectable AI-assistance entry; import output only as proposals."""
        check_fields(request, {'chapter_id', 'start', 'end', 'quote'})
        state = self.service.get(project); source = evidence(state, request)
        upgrade(state)  # In-memory only; completion never upgrades a saved library.
        from novel_writer.domain.full_book_planning import deviation_report
        return dict(revision=state['revision'], source=source, quote=request['quote'], deviation=deviation_report(state),
                    prompt='仅根据所给已保存正文提出规划变更；计划不等于已发生。返回actions数组，每项含action和values。不得修改正文或解锁；发生记录必须使用所给章节ID及精确quote。所有建议待作者预览和决定。',
                    allowed_actions=['create_event', 'update_event', 'occur_event', 'create_stage', 'update_stage', 'occur_stage', 'create_dependency', 'update_dependency', 'prepare_plan'],
                    model_request_sent=False, quality_verified=False, status='ready_for_explicit_import')
