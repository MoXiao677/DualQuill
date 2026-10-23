"""Local, explicitly selected evidence -> shared model audit tasks -> review only."""
from copy import deepcopy
from dataclasses import replace
import json

from novel_writer.domain.deep_review import (
    ALL_CHECKS, LIMITATIONS, PROMPT, DeepReviewScope, SemanticSource,
    ReviewDecision, finding_signature, selection_digest, time_window,
)
from novel_writer.domain.tasks import digest, encode, parse, require, uuid_value
from novel_writer.application.fields import check_fields
from novel_writer.storage.sqlite_repository import ConflictError

SELECTION_FIELDS = {'checks', 'candidate_ids', 'material_ids', 'memory_ids', 'planning_ids'}


def canonical_selection(raw):
    check_fields(raw, SELECTION_FIELDS)
    require(set(raw) == SELECTION_FIELDS, '深层范围字段缺失')
    for name in SELECTION_FIELDS:
        values = raw[name]
        require(type(values) is list and all(type(v) is str and v for v in values) and len(values) == len(set(values)) and len(values) <= 80, '深层范围列表非法')
    require(bool(raw['checks']) and set(raw['checks']) <= set(ALL_CHECKS), '深层检查项非法')
    return deepcopy(raw)


def _strings(value):
    """Saved planning strings only; no ID remapping inside the outbound text."""
    if type(value) is str:
        return [value]
    if type(value) is list:
        return [text for v in value for text in _strings(v)]
    if type(value) is dict:
        return [text for k, v in value.items() if k not in ('id', 'project_id', 'created_at', 'updated_at') and not k.endswith('_id') and not k.endswith('_ids') for text in _strings(v)]
    return []


def _find(items, identifier):
    value = next((v for v in items if v['id'] == identifier), None)
    require(value is not None, '深层审核来源不存在/跨书')
    return value


def capture(state, kind, identifier, record_kind=None):
    from novel_writer.domain.chapter_trash import hidden_ids
    from novel_writer.domain.memory import outdated
    project = state['document']['project']['id']
    chapter_numbers = {c['id']: c['number'] for c in state['document']['chapters']}
    version = None
    chapter_number = None; producer_task = producer_attempt = producer_node = None
    record_kind = record_kind or kind
    if kind == 'chapter':
        value = _find(state['document']['chapters'], identifier)
        require(identifier not in hidden_ids(state), '深层审核章节已归档/回收')
        text = value['content']; version = value['current_version_id']
        chapter_number = value['number']
        identity = dict(number=value['number'], status=value['status'])
        basis = 'saved_body'
    elif kind == 'candidate':
        from novel_writer.application.comparisons import hidden_task_ids
        value = _find(state.get('generation_candidates', []), identifier)
        task = _find(state.get('generation_tasks', []), value['task_id'])
        require(value['project_id'] == project and task['project_id'] == project and task['status'] == 'succeeded' and task['candidate_id'] == identifier and task['attempt_id'] == value['attempt_id'], '候选不是本书真实完成生产者的结果')
        require(task['id'] not in hidden_task_ids(state), '未揭晓比较候选不能进入深层审核')
        from novel_writer.domain.tasks import capture_dependency, dependency_equal, Dependency
        for raw in task['frozen']['dependencies']:
            dep = parse(Dependency, raw)
            require(dep.kind != 'skill', '候选含全局资料依赖，当前深层审核无法复核，请使用原工作流候选审核入口')
            require(dependency_equal(dep, capture_dependency(state, dep.kind, dep.entity_id, use=dep.use, file_path=dep.file_path)), '候选生产者来源已变化，请重新生成或使用保存正文审核')
        require(not any(r['candidate_id'] == identifier for r in state.get('adoption_receipts', [])), '深层审核仅接受未采纳候选')
        require(value['chapter_id'] not in hidden_ids(state), '候选目标章节已归档/回收')
        text = value['output_text']; identity = dict(provenance=value['provenance'], status=task['status'])
        # New saved-outline tasks explicitly select the saved character/rule
        # context. Keep it frozen with the candidate, with its original deps.
        if task['frozen']['parameters'].get('upstream',{}).get('kind')=='chapter_outline':
            identity['creation_context']=task['frozen']['context_text']
        chapter_number = next(c['number'] for c in state['document']['chapters'] if c['id'] == value['chapter_id'])
        producer_task = value['task_id']; producer_attempt = value['attempt_id']
        producer_node = next((a['id'] for a in state.get('workflow_node_attempts', []) if a.get('task_id') == producer_task), None)
        basis = 'unadopted_candidate'
    elif kind == 'material':
        from novel_writer.domain.materials import require_current_index, index_status
        value = _find(state.get('materials', []), identifier)
        require(value['project_id'] == project and not value['archived'] and index_status(state, value) == 'current', '深层资料已归档/索引缺失或过期，须显式重建')
        current = require_current_index(state, value)
        version = current['id']; text = current['text']
        identity = dict(version_number=current['version_number'], index_status='current', archived=False)
        basis = 'reference_only'
    elif kind == 'memory':
        value = _find(state.get('memories', []), identifier)
        require(value['project_id'] == project and value['active'] and value['confirmed'] and not outdated(state, value['source']), '未确认/归档/过期记忆不能作为事实来源')
        require(value['position_chapter_id'] not in hidden_ids(state), '记忆有效章节已归档/回收')
        text = value['text']; version = next((e['id'] for e in reversed(state.get('memory_history', [])) if e['memory_id'] == identifier), None)
        identity = dict(kind=value['kind'], active=True, confirmed=True, position_number=next(c['number'] for c in state['document']['chapters'] if c['id'] == value['position_chapter_id']))
        identity['subject_name'] = next((c['name'] for c in state['document']['characters'] if c['id'] == value.get('character_id')), None)
        chapter_number = identity['position_number']
        basis = 'confirmed_memory'
    else:
        require(kind == 'planning', '未知深层来源类型')
        catalogs = dict(book_outline=[state['document']['book_outline']] if state['document']['book_outline'] else [], chapter_outline=state['document']['chapter_outlines'], character_arc=state.get('character_arcs', []), key_event=state.get('key_events', []))
        if record_kind == 'planning':
            matches = [(k, v) for k, values in catalogs.items() for v in values if v['id'] == identifier]
            require(len(matches) == 1, '规划不存在/跨书/身份不唯一')
            record_kind, value = matches[0]
        else:
            require(record_kind in catalogs, '规划来源类型非法'); value = _find(catalogs[record_kind], identifier)
        require(not value.get('archived', False), '深层审核规划已归档')
        if record_kind == 'chapter_outline':
            require(value['chapter_id'] not in hidden_ids(state), '规划章节已归档/回收')
            chapter_number = next(c['number'] for c in state['document']['chapters'] if c['id'] == value['chapter_id'])
        texts = _strings(value)
        stages = sorted((s for s in state.get('character_arc_stages', []) if s['arc_id'] == identifier), key=lambda s: s['ordinal']) if record_kind == 'character_arc' else []
        if record_kind == 'character_arc':texts += [text for s in stages for text in _strings(s)]
        text = '\n'.join(texts); version = value.get('current_version_id')
        def position(item):
            return dict(status=item.get('status'), ordinal=item.get('ordinal', item.get('planned_order')), planned_chapter_number=chapter_numbers.get(item.get('planned_chapter_id')), occurred_chapter_number=chapter_numbers.get(item.get('occurred_chapter_id')), revision=item.get('revision'))
        identity = dict(record_kind=record_kind, text_sha256=digest(text), revision=value.get('revision'), saved_status=position(value), stages=[position(s) for s in stages])
        if record_kind == 'chapter_outline':
            identity['declared_times'] = [dict(field='story_time', text=value['story_time'], literal_window=time_window(value['story_time']))] + [dict(field='scenes.'+str(i)+'.story_time', text=s['story_time'], literal_window=time_window(s['story_time'])) for i, s in enumerate(value['scenes'])]
        basis = 'planning_record'
    context_text = json.dumps(identity, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    identity_sha = digest(json.dumps(dict(kind=kind, basis=basis, text_sha256=digest(text), identity=identity), sort_keys=True, ensure_ascii=False, separators=(',', ':')))
    return SemanticSource(project_id=project, kind=kind, entity_id=identifier, version_id=version, text=text, text_sha256=digest(text), basis=basis, identity_sha256=identity_sha, record_kind=record_kind, chapter_number=chapter_number, producer_task_id=producer_task, producer_attempt_id=producer_attempt, producer_node_attempt_id=producer_node, context_text=context_text)


def freeze_scope(state, chapter_ids, selection):
    selection = canonical_selection(selection)
    require(bool(selection['candidate_ids']) or all(_find(state['document']['chapters'],i)['content'].strip() for i in chapter_ids),'空正文不能单独审核')
    sources = [capture(state, 'chapter', i) for i in chapter_ids]
    for name, kind in [('candidate_ids', 'candidate'), ('material_ids', 'material'), ('memory_ids', 'memory'), ('planning_ids', 'planning')]:
        sources += [capture(state, kind, i) for i in selection[name]]
    checks = tuple(selection['checks']); sources = tuple(sources)
    from novel_writer.domain.chapter_trash import hidden_ids
    count = sum(c['id'] not in hidden_ids(state) for c in state['document']['chapters'])
    return DeepReviewScope(checks=checks, sources=sources, selection_sha256=selection_digest(checks, sources), book_chapter_count=count)


def selection_from_scope(scope):
    return dict(checks=list(scope.checks), **{name: [s.entity_id for s in scope.sources if s.kind == kind] for name, kind in [('candidate_ids', 'candidate'), ('material_ids', 'material'), ('memory_ids', 'memory'), ('planning_ids', 'planning')]})


def assert_fresh(state, task):
    scope = getattr(task.frozen.parameters, 'deep_review', None)
    if scope is None:
        return
    from novel_writer.domain.chapter_trash import hidden_ids
    require(sum(c['id'] not in hidden_ids(state) for c in state['document']['chapters']) == scope.book_chapter_count, '全书章节范围已变化，请重新冻结')
    for source in scope.sources:
        require(capture(state, source.kind, source.entity_id, source.record_kind) == source, '深层审核来源/身份/状态已变化，请重新冻结并确认')


def decorate(result, state, task):
    decisions = state.get('deep_review_actions', [])
    views = []
    for i, finding in enumerate(result['output']['findings']):
        signature = finding_signature(finding)
        related = [a for a in decisions if a['signature_sha256'] == signature]
        views.append(dict(index=i, finding=finding, status=related[-1]['kind'] if related else 'unverified', history=related, signature_sha256=signature))
    scope = encode(task.frozen.parameters.deep_review)
    selected = sum(s['kind'] == 'chapter' for s in scope['sources'])
    return dict(result, findings=views, scope=scope, method='model_semantic_opinion', limitations=list(LIMITATIONS), fact_confirmation=False, auto_edit=False, coverage=dict(mode='full_book' if selected == scope['book_chapter_count'] else 'selected_chapters', selected_chapters=selected, total_active_chapters=scope['book_chapter_count']))


class DeepReviews:
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.service = coordinator.service

    def prepare(self, project_id, request):
        from novel_writer.application.review_rules import canonical_request
        fields = {'request_id', 'chapter_id', 'chapter_ids', 'selection', 'instruction', 'model_options', 'max_output_chars', 'timeout_ms', 'expected_revision'}
        check_fields(request, fields); require(set(request) == fields, '深层审核准备字段缺失')
        require(type(request['model_options']) is dict and request['model_options'].get('prompt_version') == PROMPT, '深层审核须使用专用提示词')
        chapter_ids = request['chapter_ids']
        require(type(chapter_ids) is list and request['chapter_id'] in chapter_ids, '审核主章须在明确正文范围中')
        selection = canonical_selection(request['selection'])
        params = canonical_request(dict(instruction=request['instruction'], max_output_chars=request['max_output_chars'], timeout_ms=request['timeout_ms'], selected_chapter_ids=chapter_ids, previous_report_id=None, rules=dict(version='offline-audit-1', forbidden_literals=[], required_literals=[], normalization='whitespace', near_threshold=.9, minimum_fragment_chars=12, check_timeline=False)))
        context = dict(chapter_id=request['chapter_id'], budget_chars=1000, include_current_plan=False, include_book_outline=False, include_characters=False, include_worldbuilding=False, include_writing_rules=False, include_memories=False, include_search_results=False)
        return self.coordinator.prepare(project_id, dict(request_id=request['request_id'], chapter_id=request['chapter_id'], task_type='audit_chapter', context_options=context, context_sha256=digest(''), parameters=params, model_options=request['model_options'], expected_revision=request['expected_revision'], deep_review=selection))

    def describe(self, project_id, report_id):
        if not any(r['id'] == report_id for r in self.service.get(project_id).get('model_reports', [])):
            raise KeyError('深层审核报告不存在/跨书')
        result = self.coordinator.model_review(project_id, report_id)
        require('scope' in result, '报告不是深层审核')
        return result

    def decide(self, project_id, report_id, request):
        fields = {'operation_id', 'expected_revision', 'finding_index', 'kind', 'reason'}
        check_fields(request, fields); require(set(request) == fields, '深层意见处理字段缺失')
        identity = uuid_value(request['operation_id'])
        require(type(request['expected_revision']) is int, '保存编号非法')
        def apply(state):
            if not any(r['id'] == report_id for r in state.get('model_reports', [])):
                raise KeyError('深层审核报告不存在/跨书')
            report = _find(state.get('model_reports', []), report_id)
            task = _find(state['generation_tasks'], report['task_id'])
            require('deep_review' in task['frozen']['parameters'], '报告不是深层审核')
            i = request['finding_index']
            require(type(i) is int and 0 <= i < len(report['output']['findings']), '深层意见序号非法')
            signature = finding_signature(report['output']['findings'][i])
            old = next((a for a in state.get('deep_review_actions', []) if a['id'] == identity), None)
            if old is not None:
                require((old['report_id'], old['finding_index'], old['kind'], old['reason']) == (report_id, i, request['kind'], request['reason']), '同一处理编号绑定其他决定')
                return None, old
            if request['expected_revision'] != state['revision']:
                raise ConflictError('保存编号已变化，请重新核对')
            from novel_writer.domain.models import utc_now
            action = ReviewDecision(id=identity, project_id=project_id, report_id=report_id, finding_index=i, kind=request['kind'], reason=request['reason'], signature_sha256=signature, saved_revision=state['revision'] + 1, created_at=utc_now())
            state['deep_review_actions'].append(encode(action))
            return state, encode(action)
        return self.coordinator.repository.atomic(project_id, apply, identity_claim=('deep_review_actions', 'id', identity))

    def _book(self, project_id, run_id):
        from novel_writer.storage.review_batches import ReviewBatchStore
        self.service.get(project_id)
        run = next((r for r in ReviewBatchStore(self.coordinator.repository).list(project_id) if r['id'] == run_id), None)
        if run is None:
            raise KeyError('整书审核不存在/跨书')
        return run

    def create_book(self, project_id, request):
        from novel_writer.domain.chapter_trash import hidden_ids
        from novel_writer.storage.review_batches import ReviewBatchStore
        from novel_writer.domain.models import utc_now
        fields = {'request_id', 'batch_size', 'selection', 'instruction', 'model_options', 'max_output_chars', 'timeout_ms', 'expected_revision'}
        check_fields(request, fields); require(set(request) == fields, '整书审核准备字段缺失')
        identity = uuid_value(request['request_id'])
        require(type(request['batch_size']) is int and 1 <= request['batch_size'] <= 40, '每批章数必须为1–40')
        require(type(request['expected_revision']) is int, '保存编号非法')
        selection = canonical_selection(request['selection'])
        require(type(request['model_options']) is dict and request['model_options'].get('prompt_version') == PROMPT, '深层审核须使用专用提示词')
        state = self.service.get(project_id)
        # Replays return the original frozen scope even if the book has since changed.
        store = ReviewBatchStore(self.coordinator.repository)
        old = next((r for r in store.list(project_id) if r['id'] == identity), None)
        if old:
            require(old['request'] == request, '整书审核编号已绑定其他输入')
            return self.describe_book(project_id, identity)
        chapters = sorted((c for c in state['document']['chapters'] if c['id'] not in hidden_ids(state)), key=lambda c: c['number'])
        require(bool(chapters), '空书不能创建整书审核')
        sources = [capture(state, 'chapter', c['id']) for c in chapters]
        batches = []
        size = request['batch_size']
        for start in range(0, len(chapters), size):
            ids = [c['id'] for c in chapters[start:start + size]]
            # Validate the existing 80-source / 200k-char contract at creation too.
            freeze_scope(state, ids, selection)
            batches.append(dict(index=len(batches), chapter_ids=ids))
        manifest = dict(id=identity, project_id=project_id, created_at=utc_now(), request=deepcopy(request),
                        chapters=[dict(id=s.entity_id, number=s.chapter_number, identity_sha256=s.identity_sha256, version_id=s.version_id) for s in sources], batches=batches)
        store.create(manifest, request['expected_revision'])
        return self.describe_book(project_id, identity)

    def _batch_attempts(self, state, run, batch):
        from uuid import UUID, uuid5
        tasks = {t['request_id']: t for t in state.get('generation_tasks', [])}
        attempts = []
        for i in range(len(tasks) + 1):
            identity = str(uuid5(UUID(run['id']), 'batch/' + str(batch['index']) + '/attempt/' + str(i)))
            if identity not in tasks:
                break
            attempts.append(tasks[identity])
        return attempts

    def describe_book(self, project_id, run_id):
        from novel_writer.domain.chapter_trash import hidden_ids
        run = self._book(project_id, run_id)
        state = self.service.get(project_id)
        active = {c['id']: c for c in state['document']['chapters'] if c['id'] not in hidden_ids(state)}
        frozen = {c['id']: c for c in run['chapters']}
        stale = []
        for cid, c in frozen.items():
            if cid not in active or not active[cid]['content'].strip() or capture(state, 'chapter', cid).identity_sha256 != c['identity_sha256'] or active[cid]['current_version_id'] != c['version_id']:
                stale.append(cid)
        batches = []; reports = []; reviewed = []; failed = []
        for batch in run['batches']:
            attempts = self._batch_attempts(state, run, batch)
            views = [self.coordinator.describe(project_id, t['id']) for t in attempts]
            latest = views[-1] if views else None
            status = latest['display_status'] if latest else 'queued'
            # Success requires a persisted validated report, not just task completion.
            if latest and latest['task']['status'] == 'succeeded' and latest['model_reports']:
                reviewed.extend(batch['chapter_ids'])
                reports.extend(latest['model_reports'])
                status = 'completed'
            if status in ('failed', 'cancelled', 'interrupted'):
                failed.append(batch['index'])
            batches.append(dict(batch, status=status, attempts=[dict(task_id=v['task']['id'], status=v['display_status'], error_code=v['task'].get('error_code'), report_ids=[r['id'] for r in v['model_reports']]) for v in views]))
        current_reviewed = [cid for cid in reviewed if cid in active and cid not in stale]
        unreviewed = [cid for cid in active if cid not in current_reviewed]
        complete = bool(active) and not unreviewed and set(active) == set(frozen)
        return dict(id=run_id, created_at=run['created_at'], revision=state['revision'], chapters=run['chapters'], batches=batches, reports=reports, failed_batches=failed,
                    coverage=dict(mode='full_book_batches', total_chapters=len(active), reviewed_chapters=current_reviewed, historically_reviewed_chapters=reviewed, unreviewed_chapters=unreviewed, stale_chapters=stale,
                                  ratio=len(current_reviewed) / len(active) if active else 0, complete=complete),
                    auto_edit=False, limitations=list(LIMITATIONS) + ['全书覆盖表示逐章分批已审；未进行跨批成对比较，不保证发现跨批重复或整书弧光问题。', '批次清单保留在原库同目录的 .deep-reviews.sqlite3 辅助库；备份/恢复/复制不包含此本机清单，原单批任务和报告仍按原格式备份。', '失败或中断的外发可能已计费；明确重试会生成新的付费风险请求。'])

    def list_books(self, project_id):
        from novel_writer.storage.review_batches import ReviewBatchStore
        self.service.get(project_id)
        return dict(runs=[self.describe_book(project_id, r['id']) for r in ReviewBatchStore(self.coordinator.repository).list(project_id)])

    def prepare_batch(self, project_id, run_id, request):
        from uuid import UUID, uuid5
        fields = {'batch_index', 'retry_failed', 'expected_revision'}
        check_fields(request, fields); require(set(request) == fields, '批次准备字段缺失')
        run = self._book(project_id, run_id)
        index = request['batch_index']
        require(type(index) is int and 0 <= index < len(run['batches']), '批次序号非法')
        require(type(request['retry_failed']) is bool and type(request['expected_revision']) is int, '批次许可/保存编号非法')
        state = self.service.get(project_id); batch = run['batches'][index]
        attempts = self._batch_attempts(state, run, batch)
        if attempts:
            latest = self.coordinator.describe(project_id, attempts[-1]['id'])
            # Never automatically resend, including pending/running/completed tasks.
            if latest['display_status'] not in ('failed', 'cancelled', 'interrupted') or not request['retry_failed']:
                return latest
            require(latest['task']['status'] != 'running', '请先在任务页显式恢复中断状态，再决定是否重试；请求可能已计费')
        if request['expected_revision'] != state['revision']:
            raise ConflictError('保存编号已变化，请刷新后准备批次')
        # Fixed scope: edits/additions/archive require a new book run, never silently rebind.
        from novel_writer.domain.chapter_trash import hidden_ids
        active = {c['id'] for c in state['document']['chapters'] if c['id'] not in hidden_ids(state)}
        require(active == {c['id'] for c in run['chapters']}, '全书章节范围已变化，请新建整书审核')
        for c in run['chapters']:
            source = capture(state, 'chapter', c['id'])
            require(source.identity_sha256 == c['identity_sha256'] and source.version_id == c['version_id'], '整书正文来源已变化，请新建整书审核')
        raw = {k: deepcopy(v) for k, v in run['request'].items() if k != 'batch_size'}
        raw.update(request_id=str(uuid5(UUID(run_id), 'batch/' + str(index) + '/attempt/' + str(len(attempts)))), chapter_ids=batch['chapter_ids'], chapter_id=batch['chapter_ids'][0], expected_revision=state['revision'])
        return self.prepare(project_id, raw)
