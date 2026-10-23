"""Fictional loopback only. These tests validate plumbing, not semantic quality."""
from contextlib import closing, contextmanager
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
import json
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
from novel_writer.application.deep_reviews import DeepReviews, freeze_scope
from novel_writer.application.model_adapter import ChatCompletionsAdapter, ChatHttpTransport
from novel_writer.application.service import NovelService
from novel_writer.application.task_protocol import AdapterRegistry
from novel_writer.application.tasks import TaskCoordinator
from novel_writer.domain.deep_review import CHECKS, PROMPT, verify, time_window, elapsed_days
from novel_writer.domain.tasks import digest, encode
from novel_writer.storage.sqlite_repository import SQLiteRepository, validate_workspace
from test_s5a_review import rows


@contextmanager
def semantic_wire(protocol='openai-chat', stream=False):
    """Real HTTP/JSON or SSE using exact quotes from the actual request."""
    from novel_writer.domain.connections import canonical_messages
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            messages = canonical_messages(body, protocol); sources = json.loads(messages[1]['content'])['sources']
            calls.append(dict(body=body, messages=messages))
            ev = [dict(source_index=i, start=0, end=len(s['text']), quote=s['text']) for i, s in enumerate(sources[:2])]
            content = json.dumps(dict(overview='虚构语义意见待核实', findings=[dict(check='semantic_repetition', statement='可能是合法回环，需要作者判断。', assessment='model_opinion', status='unverified', evidence=ev)]), ensure_ascii=False)
            if stream:
                from test_sse_protocols import event, chat
                if protocol == 'openai-chat':
                    raw = event(chat(content)) + event(chat('', 'stop')) + b'data: [DONE]\r\n\r\n'
                elif protocol == 'anthropic-messages':
                    raw = event(dict(type='message_start', message=dict(id='fake', role='assistant', content=[])), 'message_start') + event(dict(type='content_block_start', index=0, content_block=dict(type='text', text='')), 'content_block_start') + event(dict(type='content_block_delta', index=0, delta=dict(type='text_delta', text=content)), 'content_block_delta') + event(dict(type='content_block_stop', index=0), 'content_block_stop') + event(dict(type='message_delta', delta=dict(stop_reason='end_turn')), 'message_delta') + event(dict(type='message_stop'), 'message_stop')
                else:
                    raw = event(dict(candidates=[dict(index=0, content=dict(role='model', parts=[dict(text=content)]))])) + event(dict(candidates=[dict(index=0, finishReason='STOP')]))
                mime = 'text/event-stream'
            else:
                if protocol == 'openai-chat':
                    payload = dict(id='fictional', choices=[dict(message=dict(role='assistant', content=content), finish_reason='stop')])
                elif protocol == 'anthropic-messages':
                    payload = dict(id='fictional', type='message', role='assistant', model='fiction-model', content=[dict(type='text', text=content)], stop_reason='end_turn')
                else:
                    payload = dict(responseId='fictional', candidates=[dict(content=dict(role='model', parts=[dict(text=content)]), finishReason='STOP')])
                raw = json.dumps(payload, ensure_ascii=False).encode('utf8'); mime = 'application/json'
            self.send_response(200); self.send_header('Content-Type', mime); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler); server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True); thread.start()
    try:
        yield dict(url='http://127.0.0.1:' + str(server.server_port) + '/v1', calls=calls)
    finally:
        server.shutdown(); thread.join(2); server.server_close()


class Providers:
    offline = False
    def validate_sampling(self, options): pass
    def assert_prepared(self, connection, created): pass
    def generation_connection(self, *args, **kwargs):
        return dict(base_url='https://fictional.invalid/v1', api_key='fictional-local-test-only')


class DeepReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='deep-review-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.db = self.root / 'fictional.sqlite3'
        self.service = NovelService(SQLiteRepository(self.db))
        from novel_writer.application.skill_import import SkillLibrary
        SkillLibrary(self.db)
        state = self.service.create(title='虚构时钟城'); self.pid = state['document']['project']['id']
        self.save('add_chapter', title='出发')
        self.cid = self.service.get(self.pid)['document']['chapters'][0]['id']
        self.save('save_chapter', chapter_id=self.cid, content='🙂黎明时，阿澄尚不知道钥匙在桥下。\n大约三至五天后她才收到信。')
        self.save('add_chapter', title='回声')
        self.cid2 = self.service.get(self.pid)['document']['chapters'][1]['id']
        self.save('save_chapter', chapter_id=self.cid2, content='阿澄望着桥下。🙂她或许听说了钥匙的位置，但来信尚未抵达。')
        self.mode = 'good'; self.calls = []; self.ready = threading.Event(); self.release = threading.Event()
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.calls.append(body); owner.ready.set()
                data = json.loads(body['messages'][1]['content'])
                if owner.mode == 'slow': owner.release.wait(3)
                if 'checks' in data:
                    ev = [dict(source_index=i, start=0, end=len(s['text']), quote=s['text']) for i, s in enumerate(data['sources'][:2])]
                    finding = dict(check='semantic_repetition', statement='两处可能重复同一信息，需作者核对；不是已证实重复。', assessment='model_opinion', status='unverified', evidence=ev)
                    value = dict(overview='仅本次本地范围；时间、知识状态仍未知。', findings=[finding])
                    if owner.mode == 'fake_quote': ev[1]['quote'] = '伪造'
                    if owner.mode == 'utf16': ev[0]['end'] += 1
                    if owner.mode == 'fact': finding['status'] = 'confirmed'
                    if owner.mode == 'edit': value['replacement'] = '自动改稿'
                    if owner.mode == 'one_side': finding['evidence'] = ev[:1]
                    content = json.dumps(value, ensure_ascii=False)
                else: content = '🙂真实本地生产候选，阿澄在桥边等待来信。'
                raw = json.dumps(dict(id='fictional-loopback', model='fictional', choices=[dict(index=0, message=dict(role='assistant', content=content), finish_reason='stop')]), ensure_ascii=False).encode('utf8')
                self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(raw))); self.end_headers()
                try: self.wfile.write(raw)
                except OSError: pass
        self.remote = ThreadingHTTPServer(('127.0.0.1', 0), Handler); self.remote.daemon_threads = True
        self.thread = threading.Thread(target=self.remote.serve_forever, kwargs={'poll_interval': .01}, daemon=True); self.thread.start()
        self.addCleanup(self.stop)
        adapter = ChatCompletionsAdapter(Providers(), enabled=True, transport=ChatHttpTransport(endpoint_override='http://127.0.0.1:' + str(self.remote.server_address[1]) + '/v1'))
        registry = AdapterRegistry(); registry.register('audit_chapter', adapter); registry.register('rewrite_chapter', adapter)
        self.engine = TaskCoordinator(self.service, registry); self.addCleanup(self.engine.close)
        self.reviews = DeepReviews(self.engine)

    def stop(self):
        self.release.set(); self.remote.shutdown(); self.thread.join(2); self.remote.server_close()

    def save(self, action, **values):
        return self.service.execute(self.pid, action, values, expected_revision=self.service.get(self.pid)['revision'])

    def request(self, **changes):
        request = dict(request_id=str(uuid4()), chapter_id=self.cid, chapter_ids=[self.cid, self.cid2], selection=dict(checks=list(CHECKS), candidate_ids=[], material_ids=[], memory_ids=[], planning_ids=[]), instruction='核对相对时间、人物未知与重复桥段；仅提案。', model_options=dict(adapter_id='chat-completions-http-v1', connection_id='gg', model_id='fictional', temperature=.3, max_tokens=2048, budget_limit=1.0, allow_unknown_cost=True, prompt_version=PROMPT), max_output_chars=20000, timeout_ms=2000, expected_revision=self.service.get(self.pid)['revision'])
        request.update(changes); return request

    def run_task(self, prepared):
        task = prepared['task']; binding = task['frozen']['parameters']['binding']
        self.engine.start(self.pid, task['id'], confirmation=dict(confirm_external=True, request_sha256=binding['request_sha256']))
        self.engine.wait_idle(5); return self.engine.describe(self.pid, task['id'])

    def test_unicode_both_sides_explicit_scope_and_opinion_fact_isolation(self):
        before = self.service.get(self.pid)
        prepared = self.reviews.prepare(self.pid, self.request())
        self.assertFalse(self.calls)
        frozen = prepared['task']['frozen']; self.assertEqual(frozen['context_text'], '')
        self.assertEqual(self.service.get(self.pid)['workspace_version'], 41)
        view = self.run_task(prepared); self.assertEqual(view['task']['status'], 'succeeded', view)
        report = self.reviews.describe(self.pid, view['model_reports'][0]['id'])
        finding = report['findings'][0]
        self.assertEqual(finding['status'], 'unverified')
        self.assertEqual(finding['finding']['evidence'][0]['quote'][0], '🙂')
        self.assertEqual(len(finding['finding']['evidence']), 2)
        self.assertFalse(report['fact_confirmation']); self.assertFalse(report['quality_verified'])
        after = self.service.get(self.pid)
        self.assertEqual(before['document'], after['document']); self.assertFalse(after['model_memory_proposals']); self.assertFalse(after['model_bridge_proposals'])
        self.assertFalse(after['knowledge_nodes']); self.assertFalse(after['memories'])
        snapshot = rows(self.db)
        self.reviews.describe(self.pid, view['model_reports'][0]['id'])
        self.assertEqual(rows(self.db), snapshot)

    def test_explicit_deep_scope_rejects_task_rules_without_silent_omission(self):
        before=self.service.get(self.pid)
        original=self.engine.prepare
        def prepare(project,request):
            request['context_options']['rule_task_id']=request['request_id']
            return original(project,request)
        with patch.object(self.engine,'prepare',side_effect=prepare):
            with self.assertRaisesRegex(ValueError,'不支持任务规则绑定'):
                self.reviews.prepare(self.pid,self.request())
        self.assertEqual(self.service.get(self.pid),before)
        self.assertFalse(self.calls)

    def test_forged_utf16_single_side_confirmed_and_auto_edit_rejected(self):
        for mode in ('fake_quote', 'utf16', 'one_side', 'fact', 'edit'):
            with self.subTest(mode=mode):
                self.mode = mode; before = len(self.service.get(self.pid).get('model_reports', []))
                view = self.run_task(self.reviews.prepare(self.pid, self.request()))
                self.assertEqual(view['task']['status'], 'failed', view)
                self.assertEqual(len(self.service.get(self.pid)['model_reports']), before)
                self.assertEqual(view['model_results'][0]['response']['error_code'], 'invalid_model_analysis_or_evidence')

    def test_budget_confirmation_cancel_timeout_and_stale_sources(self):
        for key, value in [('budget_limit', 0.0), ('allow_unknown_cost', False)]:
            request = self.request(); request['model_options'][key] = value
            with self.assertRaises(ValueError): self.reviews.prepare(self.pid, request)
        prepared = self.reviews.prepare(self.pid, self.request())
        with self.assertRaises(ValueError): self.engine.start(self.pid, prepared['task']['id'])
        self.save('save_chapter', chapter_id=self.cid2, content='作者修改了实际来源🙂')
        with self.assertRaises(ValueError): self.run_task(prepared)
        self.assertFalse(self.calls)
        self.mode = 'slow'; prepared = self.reviews.prepare(self.pid, self.request())
        task = prepared['task']; self.engine.start(self.pid, task['id'], confirmation=dict(confirm_external=True, request_sha256=task['frozen']['parameters']['binding']['request_sha256']))
        self.assertTrue(self.ready.wait(1)); self.engine.cancel(self.pid, task['id']); self.release.set(); self.engine.wait_idle(3)
        self.assertEqual(self.engine.describe(self.pid, task['id'])['task']['status'], 'cancelled')
        self.assertFalse(self.service.get(self.pid)['model_reports'])
        self.release.clear(); self.ready.clear()
        view = self.run_task(self.reviews.prepare(self.pid, self.request(timeout_ms=120)))
        self.release.set(); self.assertEqual(view['task']['error_code'], 'timeout')
        self.assertFalse(view['model_reports'])

    def test_decisions_append_only_and_precise_exemption(self):
        view = self.run_task(self.reviews.prepare(self.pid, self.request())); report_id = view['model_reports'][0]['id']
        decision = dict(operation_id=str(uuid4()), expected_revision=self.service.get(self.pid)['revision'], finding_index=0, kind='waive', reason='作者有意让信息回环')
        result = self.reviews.decide(self.pid, report_id, decision); before = rows(self.db)
        self.assertEqual(self.reviews.decide(self.pid, report_id, decision), result); self.assertEqual(rows(self.db), before)
        self.assertEqual(self.reviews.describe(self.pid, report_id)['findings'][0]['status'], 'waive')
        second = self.run_task(self.reviews.prepare(self.pid, self.request()))
        self.assertEqual(self.reviews.describe(self.pid, second['model_reports'][0]['id'])['findings'][0]['status'], 'waive')
        state = self.service.get(self.pid); state['deep_review_actions'][0]['reason'] = '偷改'
        with self.assertRaises(ValueError): self.service.repository.save(state, expected_revision=state['revision'])
        decision.update(operation_id=str(uuid4()), expected_revision=self.service.get(self.pid)['revision'], kind='reopen', reason='作者重新复核')
        self.reviews.decide(self.pid, report_id, decision)
        self.assertEqual(self.reviews.describe(self.pid, report_id)['findings'][0]['status'], 'reopen')
        self.save('save_chapter', chapter_id=self.cid2, content='新的引文🙂桥上的来信。')
        third = self.run_task(self.reviews.prepare(self.pid, self.request()))
        self.assertEqual(self.reviews.describe(self.pid, third['model_reports'][0]['id'])['findings'][0]['status'], 'unverified')

    def test_declared_intervals_relative_anchors_and_duration_never_invent_unknown(self):
        a = time_window('第3天至第5天'); self.assertEqual((a['earliest'], a['latest']), (3, 5))
        b = time_window('三天后', a); self.assertEqual((b['earliest'], b['latest']), (6, 8))
        self.assertIsNone(time_window('三天后')); self.assertIsNone(time_window('大约第5天'))
        self.assertIsNone(time_window('第5天至第3天')); self.assertIsNone(time_window('2026-02-30'))
        self.assertIsNone(time_window('次日', {'earliest': None, 'latest': None, 'unit': 'story_day'}))
        self.assertEqual(elapsed_days(a, time_window('第4天至第7天'))['minimum'], -1)
        self.assertEqual(elapsed_days(a, time_window('第4天至第7天'))['maximum'], 4)
        self.assertIsNone(elapsed_days(a, None)); self.assertIsNone(elapsed_days(a, time_window('2026-10-21')))
        date = time_window('2026-10-20至2026-10-22')
        self.assertEqual(elapsed_days(date, time_window('次日', date))['maximum'], 3)

    def test_all_checks_keep_uncertainty_conflicts_and_character_unknown_as_opinions(self):
        scope = freeze_scope(self.service.get(self.pid), [self.cid, self.cid2], self.request()['selection'])
        evidence = [dict(source_index=i, start=0, end=len(s.text), quote=s.text) for i, s in enumerate(scope.sources)]
        wire = dict(overview='不同叙述未足以确认矛盾', findings=[dict(check=c, statement='存在未知或矛盾信息，待作者核实时间区间与人物信息来源。', assessment='model_opinion', status='unverified', evidence=evidence) for c in CHECKS])
        output = verify(json.dumps(wire, ensure_ascii=False), scope)
        self.assertEqual(len(output.findings), 9)
        self.assertTrue(all(f.assessment == 'model_opinion' and f.statement.startswith('[待核实/') for f in output.findings))
        self.assertFalse(output.proposals); self.assertFalse(output.bridges)
        self.assertIn('尚不知道', output.findings[0].evidence[0].quote)
        self.assertIn('大约三至五天', output.findings[1].evidence[0].quote)
        self.assertIn('或许', output.findings[1].evidence[1].quote)
        self.assertFalse(self.service.get(self.pid).get('knowledge_nodes'))

    def material(self, title='虚构参考', text='🙂第三日至第五日可收到来信，具体时间未知。'):
        from novel_writer.application.materials import Materials
        engine = Materials(self.service)
        detail = engine.create(self.pid, dict(operation_id=str(uuid4()), expected_revision=self.service.get(self.pid)['revision'], title=title, format='txt', tags=[], text=text, note='虚构测试'))
        return engine, detail['material']['id']

    def test_material_explicit_authorization_archived_missing_stale_and_cross_book(self):
        engine, mid = self.material()
        request = self.request(chapter_ids=[self.cid]); request['selection']['material_ids'] = [mid]
        before = rows(self.db)
        with self.assertRaises(ValueError): self.reviews.prepare(self.pid, request)
        self.assertEqual(rows(self.db), before); self.assertFalse(self.calls)
        engine.rebuild(self.pid, mid, dict(operation_id=str(uuid4()), expected_revision=self.service.get(self.pid)['revision']))
        request = self.request(chapter_ids=[self.cid]); request['selection']['material_ids'] = [mid]
        prepared = self.reviews.prepare(self.pid, request)
        view = self.run_task(prepared); self.assertEqual(view['task']['status'], 'succeeded', view)
        evidence = view['model_reports'][0]['output']['findings'][0]['evidence']
        self.assertEqual(evidence[1]['source_kind'], 'material')
        self.assertEqual(prepared['task']['frozen']['parameters']['deep_review']['sources'][1]['basis'], 'reference_only')
        pending = self.reviews.prepare(self.pid, dict(request, request_id=str(uuid4()), expected_revision=self.service.get(self.pid)['revision']))
        engine.update(self.pid, mid, dict(operation_id=str(uuid4()), expected_revision=self.service.get(self.pid)['revision'], title='参考已更新', format='txt', tags=[], text='🙂更新后需要重建。', note='虚构修改'))
        before = len(self.calls)
        with self.assertRaises(ValueError): self.run_task(pending)
        self.assertEqual(len(self.calls), before)
        request['request_id'] = str(uuid4()); request['expected_revision'] = self.service.get(self.pid)['revision']
        with self.assertRaises(ValueError): self.reviews.prepare(self.pid, request)
        engine.rebuild(self.pid, mid, dict(operation_id=str(uuid4()), expected_revision=self.service.get(self.pid)['revision']))
        engine.archive(self.pid, mid, dict(operation_id=str(uuid4()), expected_revision=self.service.get(self.pid)['revision']))
        request['expected_revision'] = self.service.get(self.pid)['revision']
        with self.assertRaises(ValueError): self.reviews.prepare(self.pid, request)
        other = self.service.create(title='另一虚构书'); other_id = other['document']['project']['id']
        from novel_writer.application.materials import Materials
        detail = Materials(self.service).create(other_id, dict(operation_id=str(uuid4()), expected_revision=other['revision'], title='另一书资料', format='md', tags=[], text='跨书材料🙂', note=''))
        request['selection']['material_ids'] = [detail['material']['id']]
        with self.assertRaises(ValueError): self.reviews.prepare(self.pid, request)
        self.assertEqual(self.service.get(other_id)['document']['project']['title'], '另一虚构书')

    def test_actual_candidate_producer_quotes_and_copy_identity(self):
        options = dict(chapter_id=self.cid, budget_chars=2000)
        preview = self.service.preview_context(self.pid, options)
        profile = dict(self.request()['model_options'], prompt_version='rewrite-1')
        prepared = self.engine.prepare(self.pid, dict(request_id=str(uuid4()), chapter_id=self.cid, task_type='rewrite_chapter', context_options=options, context_sha256=digest(preview['context_text']), parameters=dict(instruction='虚构候选', max_output_chars=2000, timeout_ms=2000), model_options=profile, expected_revision=self.service.get(self.pid)['revision']))
        produced = self.run_task(prepared); candidate = produced['candidates'][0]
        request = self.request(chapter_ids=[self.cid]); request['selection']['candidate_ids'] = [candidate['id']]
        view = self.run_task(self.reviews.prepare(self.pid, request)); self.assertEqual(view['task']['status'], 'succeeded', view)
        evidence = view['model_reports'][0]['output']['findings'][0]['evidence'][1]
        self.assertEqual(evidence['source_kind'], 'candidate'); self.assertIsNone(evidence['version_id'])
        self.assertEqual(evidence['producer_task_id'], candidate['task_id']); self.assertEqual(evidence['producer_attempt_id'], candidate['attempt_id'])
        self.assertEqual(evidence['quote'], candidate['output_text'])
        from novel_writer.application.backups import create_backup
        from novel_writer.application.migrations import migrate
        from novel_writer.application.skill_import import SkillLibrary
        package = self.root / 'candidate-deep.nwbak'; create_backup(self.db, package)
        for index in (1, 2):
            target = self.root / ('candidate-copy-' + str(index) + '.sqlite3'); SQLiteRepository(target); SkillLibrary(target)
            copied = migrate(package, target, operation_id=str(uuid4())); clone = NovelService(SQLiteRepository(target)).get(copied['projects'][0]['new_id'])
            report = clone['model_reports'][0]; ev = report['output']['findings'][0]['evidence'][1]
            actual = next(c for c in clone['generation_candidates'] if c['id'] == ev['entity_id'])
            self.assertEqual(ev['producer_task_id'], actual['task_id']); self.assertEqual(ev['producer_attempt_id'], actual['attempt_id'])
            self.assertEqual(ev['quote'], actual['output_text'])
            package = self.root / ('candidate-copy-' + str(index) + '.nwbak'); create_backup(target, package)
        self.assertEqual(len(self.calls), 2)

    def test_confirmed_conflicting_memories_preserved_and_unconfirmed_or_stale_refused(self):
        for text, confirmed in [('人物尚不知道钥匙位置。', False), ('人物仍不知道钥匙位置。', True), ('人物已知道钥匙位置。', True)]:
            self.save('save_memory', kind='character_state', title='虚构知识状态', text=text, position_chapter_id=self.cid, source=dict(kind='chapter', entity_id=self.cid), confirmed=confirmed)
        memories = self.service.get(self.pid)['memories']
        request = self.request(); request['selection']['memory_ids'] = [memories[0]['id']]
        with self.assertRaises(ValueError): self.reviews.prepare(self.pid, request)
        request['selection']['memory_ids'] = [m['id'] for m in memories[1:]]
        prepared = self.reviews.prepare(self.pid, request)
        scope = prepared['task']['frozen']['parameters']['deep_review']; texts = [s['text'] for s in scope['sources'] if s['kind'] == 'memory']
        self.assertEqual(len(texts), 2); self.assertTrue(any('仍不知道' in t for t in texts)); self.assertTrue(any('已知道' in t for t in texts))
        self.save('save_chapter', chapter_id=self.cid, content='来源变更导致记忆过期🙂')
        before = len(self.calls)
        with self.assertRaises(ValueError): self.run_task(prepared)
        self.assertEqual(len(self.calls), before)

    def test_planning_is_existing_source_and_partial_book_not_full_coverage(self):
        from novel_writer.application.full_book_planning import FullBookPlanning
        engine = FullBookPlanning(self.service)
        engine.create_event(self.pid, dict(operation_id=str(uuid4()), expected_revision=self.service.get(self.pid)['revision'], title='计划收到信', summary='计划第三日至第五日，尚未发生。', planned_chapter_id=self.cid2))
        event = self.service.get(self.pid)['key_events'][0]
        request = self.request(chapter_ids=[self.cid]); request['selection']['planning_ids'] = [event['id']]
        prepared = self.reviews.prepare(self.pid, request)
        scope = prepared['task']['frozen']['parameters']['deep_review']; self.assertEqual(scope['sources'][1]['basis'], 'planning_record')
        self.assertIn('planned', scope['sources'][1]['context_text'])
        view = self.run_task(prepared); report = self.reviews.describe(self.pid, view['model_reports'][0]['id'])
        self.assertEqual(report['coverage']['mode'], 'selected_chapters')
        self.assertEqual(report['coverage']['total_active_chapters'], 2)
        self.assertEqual(self.service.get(self.pid)['key_events'][0]['status'], 'planned')

    def test_restore_copy_reopen_and_zero_automatic_execution(self):
        from novel_writer.application.backups import create_backup, restore_backup
        from novel_writer.application.migrations import migrate
        from novel_writer.application.skill_import import SkillLibrary
        SkillLibrary(self.db)
        view = self.run_task(self.reviews.prepare(self.pid, self.request())); rid = view['model_reports'][0]['id']
        self.reviews.decide(self.pid, rid, dict(operation_id=str(uuid4()), expected_revision=self.service.get(self.pid)['revision'], finding_index=0, kind='false_positive', reason='人工确认叙述角度差异'))
        package = self.root / 'deep.nwbak'; manifest = create_backup(self.db, package)
        self.assertEqual(manifest['backup_format_version'], 51)
        restored = Path(restore_backup(package, self.root / 'restore')['database_path'])
        self.assertEqual(rows(restored), rows(self.db))
        target = self.root / 'copy.sqlite3'; SQLiteRepository(target); SkillLibrary(target)
        copied = migrate(package, target, operation_id=str(uuid4())); pid = copied['projects'][0]['new_id']
        state = NovelService(SQLiteRepository(target)).get(pid); validate_workspace(state)
        self.assertNotEqual(state['model_reports'][0]['id'], rid)
        self.assertEqual(state['generation_tasks'][0]['frozen']['parameters']['binding']['request_body'], view['task']['frozen']['parameters']['binding']['request_body'])
        self.assertEqual(state['deep_review_actions'][0]['kind'], 'false_positive'); self.assertEqual(len(self.calls), 1)

    def test_mixed_sources_restore_two_copies_and_pending_needs_new_confirmation(self):
        from novel_writer.application.backups import create_backup, restore_backup
        from novel_writer.application.migrations import migrate
        from novel_writer.application.skill_import import SkillLibrary
        from novel_writer.application.full_book_planning import FullBookPlanning
        from novel_writer.application.deep_reviews import assert_fresh
        from novel_writer.domain.tasks import GenerationTask, parse
        materials, mid = self.material()
        materials.rebuild(self.pid, mid, dict(operation_id=str(uuid4()), expected_revision=self.service.get(self.pid)['revision']))
        self.save('save_memory', kind='character_state', title='人物尚未知情', text='🙂阿澄尚不知道来信内容。', position_chapter_id=self.cid, source=dict(kind='chapter', entity_id=self.cid), confirmed=True)
        self.save('save_book_outline', theme='虚构等待与知识边界')
        self.save('save_chapter_outline', chapter_id=self.cid, objective='等待来信', story_time='第3天至第5天')
        self.save('add_character', name='阿澄')
        planning = FullBookPlanning(self.service)
        def act(action, **values):
            return planning.act(self.pid, action, dict(operation_id=str(uuid4()), expected_revision=self.service.get(self.pid)['revision'], **values))
        state = self.service.get(self.pid)
        act('create_arc', character_id=state['document']['characters'][0]['id'], title='了解真相', summary='从未知到知情')
        arc = self.service.get(self.pid)['character_arcs'][0]['id']
        act('create_stage', arc_id=arc, title='等待信息', summary='尚未发生', planned_chapter_id=self.cid2)
        act('create_event', title='收到来信', summary='计划第三至第五日', planned_chapter_id=self.cid2)
        state = self.service.get(self.pid)
        request = self.request()
        request['selection'].update(material_ids=[mid], memory_ids=[state['memories'][0]['id']], planning_ids=[state['document']['book_outline']['id'], state['document']['chapter_outlines'][0]['id'], arc, state['key_events'][0]['id']])
        completed = self.run_task(self.reviews.prepare(self.pid, request))
        self.assertEqual(completed['task']['status'], 'succeeded', completed)
        request.update(request_id=str(uuid4()), expected_revision=self.service.get(self.pid)['revision'])
        pending = self.reviews.prepare(self.pid, request)['task']
        body = pending['frozen']['parameters']['binding']['request_body']
        package = self.root / 'mixed.nwbak'; create_backup(self.db, package)
        restored = Path(restore_backup(package, self.root / 'mixed-restore')['database_path'])
        self.assertEqual(rows(restored), rows(self.db))
        libraries = [(restored, self.pid)]
        for index in (1, 2):
            target = self.root / ('mixed-copy-' + str(index) + '.sqlite3'); SQLiteRepository(target); SkillLibrary(target)
            copied = migrate(package, target, operation_id=str(uuid4())); pid = copied['projects'][0]['new_id']
            libraries.append((target, pid))
            package = self.root / ('mixed-copy-' + str(index) + '.nwbak'); create_backup(target, package)
        for path, pid in libraries:
            with self.subTest(database=path.name):
                service = NovelService(SQLiteRepository(path)); clone = service.get(pid)
                task = next(t for t in clone['generation_tasks'] if t['status'] == 'pending')
                parsed = parse(GenerationTask, task)
                assert_fresh(clone, parsed)
                self.assertEqual(task['frozen']['parameters']['binding']['request_body'], body)
                scope = parsed.frozen.parameters.deep_review
                self.assertEqual({s.record_kind for s in scope.sources}, {'chapter', 'material', 'memory', 'book_outline', 'chapter_outline', 'character_arc', 'key_event'})
                for source in scope.sources:
                    if source.kind == 'material':self.assertIn(source.version_id, {v['id'] for v in clone['material_versions']})
                    if source.kind == 'memory':self.assertIn(source.version_id, {v['id'] for v in clone['memory_history']})
                engine = TaskCoordinator(service, self.engine.registry); self.addCleanup(engine.close)
                before = rows(path)
                with self.assertRaises(ValueError):engine.start(pid, task['id'])
                with self.assertRaises(ValueError):engine.start(pid, task['id'], confirmation=dict(confirm_external=True, request_sha256='0' * 64))
                self.assertEqual(rows(path), before)
                self.assertEqual(engine.describe(pid, task['id'])['task']['status'], 'pending')
                self.assertFalse(engine.active)
        self.assertEqual(len(self.calls), 1)


class LegacyDeepReviewCompatibilityTests(unittest.TestCase):
    def test_generated_v1_through_v35_read_only_bytes_and_rows(self):
        """Empty feature collections supplement, not replace, real legacy fixtures."""
        from importlib import import_module
        from novel_writer.application.chapter_lifecycle import upgrade
        from novel_writer.application.projects import create
        from novel_writer.application.skill_import import SkillLibrary
        with tempfile.TemporaryDirectory(prefix='deep-legacy-') as directory:
            root = Path(directory)
            base = create(dict(title='虚构旧版只读兼容'))
            upgrade(base)
            introduced = {'memories': 2, 'memory_history': 2, 'scoped_rules': 21, 'scoped_rule_history': 22}
            specs = [(3, 'tasks', 'COLLECTIONS'), (4, 'review', 'REVIEW_COLLECTIONS'), (5, 'knowledge', 'KNOWLEDGE_COLLECTIONS'), (6, 'model_contract', 'MODEL_COLLECTIONS'), (7, 'experiments', 'EXPERIMENT_COLLECTIONS'), (8, 'workflows', 'WORKFLOW_COLLECTIONS'), (10, 'creation_presets', 'CREATION_COLLECTIONS'), (11, 'book_creation', 'COLLECTIONS'), (12, 'book_ai', 'COLLECTIONS'), (13, 'styles', 'COLLECTIONS'), (14, 'public_search', 'COLLECTIONS'), (15, 'style_trials', 'COLLECTIONS'), (16, 'chapter_writing', 'COLLECTIONS'), (17, 'chapter_planning', 'COLLECTIONS'), (18, 'scene_expansion', 'COLLECTIONS'), (19, 'chapter_lifecycle', 'COLLECTIONS'), (20, 'console', 'COLLECTIONS'), (23, 'memory_rollups', 'COLLECTIONS'), (24, 'console', 'RUN_COLLECTIONS'), (25, 'materials', 'COLLECTIONS'), (26, 'full_book_planning', 'COLLECTIONS'), (27, 'chapter_trash', 'COLLECTIONS')]
            for version, module, constant in specs:
                for key in getattr(import_module('novel_writer.domain.' + module), constant):introduced[key] = version
            for version in range(1, 36):
                with self.subTest(workspace_version=version):
                    state = {k: deepcopy(v) for k, v in base.items() if introduced.get(k, 1) <= version}
                    state['workspace_version'] = version
                    path = root / ('v' + str(version) + '.sqlite3')
                    repo = SQLiteRepository(path); SkillLibrary(path); saved = repo.create(state)
                    before, before_rows = path.read_bytes(), rows(path)
                    service = NovelService(SQLiteRepository(path))
                    actual = service.get(saved['document']['project']['id'])
                    self.assertEqual(actual, saved)
                    self.assertEqual(actual['workspace_version'], version)
                    self.assertNotIn('deep_review_actions', actual)
                    self.assertEqual(path.read_bytes(), before); self.assertEqual(rows(path), before_rows)


class ConfiguredDeepReviewTests(unittest.TestCase):
    from test_configured_tasks import ConfiguredTaskTests as Fixture
    setUp = Fixture.setUp
    save = Fixture.save
    run_task = DeepReviewTests.run_task

    def test_three_protocols_json_and_sse_use_same_strict_deep_verifier(self):
        state = self.service.get(self.pid)
        state = self.service.execute(self.pid, 'add_chapter', dict(title='虚构第二章'), expected_revision=state['revision']); self.cid2 = state['document']['chapters'][1]['id']
        self.service.execute(self.pid, 'save_chapter', dict(chapter_id=self.cid2, content='🙂未知人物知识与时间范围，须复核。'), expected_revision=state['revision'])
        for stream in (False, True):
            for protocol in ('openai-chat', 'anthropic-messages', 'gemini-content'):
                with self.subTest(protocol=protocol, stream=stream), semantic_wire(protocol, stream) as wire:
                    connection = self.save(wire['url'], protocol)
                    if stream:
                        self.providers.manage(id=connection['id'], action='stream_profile', confirmed=True, stream_mode='sse')
                    request = DeepReviewTests.request(self)
                    request['model_options'].update(adapter_id='configured-http-v2', connection_id=connection['id'], model_id='fiction-model')
                    prepared = DeepReviews(self.engine).prepare(self.pid, request)
                    self.assertFalse(wire['calls'])
                    view = self.run_task(prepared); self.assertEqual(view['task']['status'], 'succeeded', view)
                    self.assertEqual(len(wire['calls']), 1)
                    self.assertEqual(view['model_reports'][0]['output']['findings'][0]['evidence'][1]['quote'][0], '🙂')
                    self.assertFalse(view['candidates']); self.assertFalse(self.service.get(self.pid)['memories'])


class DeepReviewHttpTests(unittest.TestCase):
    from test_chapter_writing_http import ChapterWritingHttpTests as Fixture
    setUp = Fixture.setUp
    stop = Fixture.stop
    request = Fixture.request

    def test_prepare_auth_strict_fields_read_report_and_append_decision(self):
        state = self.request('GET', self.base)[1]
        code, state = self.request('POST', self.base + '/actions', dict(action='save_chapter', fields=dict(chapter_id=self.cid, content='🙂HTTP实际来源一。'), expected_revision=state['revision'])); self.assertEqual(code, 200)
        code, state = self.request('POST', self.base + '/actions', dict(action='add_chapter', fields=dict(title='第二章'), expected_revision=state['revision'])); self.assertEqual(code, 200)
        self.cid2 = state['document']['chapters'][1]['id']
        code, state = self.request('POST', self.base + '/actions', dict(action='save_chapter', fields=dict(chapter_id=self.cid2, content='HTTP实际来源二🙂。'), expected_revision=state['revision'])); self.assertEqual(code, 200)
        with semantic_wire() as wire:
            connection = self.server.providers.save_custom(id=str(uuid4()), name='虚构深层HTTP', base_url=wire['url'], protocol='openai-chat', model_id='fiction-model', api_key='fiction-only-key', allow_local=True)
            self.service = self.server.service
            request = DeepReviewTests.request(self)
            request['model_options'].update(adapter_id='configured-http-v2', connection_id=connection['id'], model_id='fiction-model')
            before = self.request('GET', self.base)[1]
            self.assertEqual(self.request('POST', self.base + '/deep-reviews/prepare', request, token=False)[0], 403)
            self.assertEqual(self.request('POST', self.base + '/deep-reviews/prepare', dict(request, surprise=True))[0], 422)
            self.assertEqual(self.request('GET', self.base)[1], before)
            code, prepared = self.request('POST', self.base + '/deep-reviews/prepare', request); self.assertEqual(code, 201, prepared)
            self.assertFalse(wire['calls']); task = prepared['task']; task_base = self.base + '/tasks/' + task['id']
            self.assertEqual(self.request('POST', task_base + '/execute', dict(confirm_external=True, request_sha256=task['frozen']['parameters']['binding']['request_sha256']))[0], 202)
            self.server.task_coordinator.wait_idle(5)
            done = self.request('GET', task_base)[1]; self.assertEqual(done['task']['status'], 'succeeded', done)
            rid = done['model_reports'][0]['id']; code, report = self.request('GET', self.base + '/deep-reviews/' + rid); self.assertEqual(code, 200)
            self.assertEqual(report['method'], 'model_semantic_opinion')
            decision = dict(operation_id=str(uuid4()), expected_revision=report['revision'], finding_index=0, kind='false_positive', reason='人工确认正常回环')
            self.assertEqual(self.request('POST', self.base + '/deep-reviews/' + rid + '/decision', decision, token=False)[0], 403)
            code, action = self.request('POST', self.base + '/deep-reviews/' + rid + '/decision', decision); self.assertEqual(code, 200, action)
            self.assertEqual(self.request('POST', self.base + '/deep-reviews/' + rid + '/decision', decision), (200, action))
            self.assertEqual(self.request('GET', self.base + '/model-reviews/' + rid)[1]['findings'][0]['status'], 'false_positive')
            other = self.request('POST', '/api/projects', dict(title='另一虚构书'))[1]; other_base = '/api/projects/' + other['document']['project']['id']
            own_before = self.request('GET', self.base)[1]
            self.assertEqual(self.request('GET', other_base + '/deep-reviews/' + rid)[0], 404)
            self.assertEqual(self.request('POST', other_base + '/deep-reviews/' + rid + '/decision', decision)[0], 409)
            fresh_decision = dict(decision, operation_id=str(uuid4()), expected_revision=other['revision'])
            self.assertEqual(self.request('POST', other_base + '/deep-reviews/' + rid + '/decision', fresh_decision)[0], 404)
            self.assertEqual(self.request('GET', other_base)[1], other)
            self.assertEqual(self.request('GET', self.base)[1], own_before)
            self.assertEqual(self.request('GET', self.base + '/deep-reviews/' + str(uuid4()))[0], 404)
            caps = self.request('GET', '/api/backups/capabilities')[1]; self.assertIn(41, caps['workspace_versions'])
            self.assertIn('backup_v41', self.request('GET', '/api/migrations/capabilities')[1]['formats'])
            self.assertEqual(len(wire['calls']), 1)



    def test_book_batch_http_auth_bounds_resume_and_report(self):
        state = self.request('GET', self.base)[1]
        code, state = self.request('POST', self.base + '/actions', dict(action='save_chapter', fields=dict(chapter_id=self.cid, content='HTTP整书第一处来源。'), expected_revision=state['revision']))
        self.assertEqual(code, 200)
        code, state = self.request('POST', self.base + '/actions', dict(action='add_chapter', fields=dict(title='第二处来源'), expected_revision=state['revision']))
        self.cid2 = state['document']['chapters'][1]['id']
        code, state = self.request('POST', self.base + '/actions', dict(action='save_chapter', fields=dict(chapter_id=self.cid2, content='HTTP整书第二处来源。'), expected_revision=state['revision']))
        with semantic_wire() as wire:
            connection = self.server.providers.save_custom(id=str(uuid4()), name='虚构整书', base_url=wire['url'], protocol='openai-chat', model_id='fiction-model', api_key='fiction-only-key', allow_local=True)
            self.service = self.server.service
            request = DeepReviewTests.request(self)
            request.pop('chapter_id'); request.pop('chapter_ids'); request['batch_size'] = 2
            request['model_options'].update(adapter_id='configured-http-v2', connection_id=connection['id'], model_id='fiction-model')
            base = self.base + '/deep-review-books'
            self.assertEqual(self.request('POST', base + '/create', request, token=False)[0], 403)
            self.assertEqual(self.request('POST', base + '/create', dict(request, batch_size=41))[0], 422)
            self.assertEqual(self.request('GET', base + '/list')[1]['runs'], [])
            code, run = self.request('POST', base + '/create', request)
            self.assertEqual(code, 201, run)
            self.assertEqual(len(self.request('GET', base + '/list')[1]['runs']), 1)
            prepare = dict(batch_index=0, retry_failed=False, expected_revision=run['revision'])
            self.assertEqual(self.request('POST', base + '/' + run['id'] + '/prepare', prepare, token=False)[0], 403)
            code, task = self.request('POST', base + '/' + run['id'] + '/prepare', prepare)
            self.assertEqual(code, 201, task); self.assertFalse(wire['calls'])
            task = task['task']
            self.assertEqual(self.request('POST', self.base + '/tasks/' + task['id'] + '/execute', dict(confirm_external=True, request_sha256=task['frozen']['parameters']['binding']['request_sha256']))[0], 202)
            self.server.task_coordinator.wait_idle(5)
            code, final = self.request('GET', base + '/' + run['id'])
            self.assertEqual(code, 200); self.assertTrue(final['coverage']['complete'], final)
            self.assertEqual(self.request('POST', base + '/' + run['id'] + '/prepare', prepare)[1]['task']['id'], task['id'])
            self.assertEqual(len(wire['calls']), 1)


class WholeBookReviewTests(unittest.TestCase):
    setUp = DeepReviewTests.setUp
    stop = DeepReviewTests.stop
    save = DeepReviewTests.save
    request = DeepReviewTests.request
    run_task = DeepReviewTests.run_task

    def create_run(self, size=2):
        request = self.request()
        request.pop('chapter_id'); request.pop('chapter_ids')
        request['batch_size'] = size
        return self.reviews.create_book(self.pid, request)

    def prepare_batch(self, run, index=0, retry=False):
        return self.reviews.prepare_batch(self.pid, run['id'], dict(batch_index=index, retry_failed=retry, expected_revision=self.service.get(self.pid)['revision']))

    def test_empty_book_rejected_without_request(self):
        empty = self.service.create(title='空书')['document']['project']['id']
        request = self.request(); request.pop('chapter_id'); request.pop('chapter_ids'); request['batch_size'] = 2
        with self.assertRaisesRegex(ValueError, '空书'):
            self.reviews.create_book(empty, request)
        self.assertFalse(self.calls)

    def test_exact_batch_and_hard_limit(self):
        for size in (0, 41, True, 1.5):
            with self.subTest(size=size), self.assertRaises(ValueError): self.create_run(size)
        run = self.create_run()
        self.assertEqual([b['chapter_ids'] for b in run['batches']], [[self.cid, self.cid2]])
        self.assertEqual(run['coverage']['reviewed_chapters'], [])
        self.assertFalse(self.calls)

    def test_multi_batch_boundaries(self):
        for i in range(3): self.save('add_chapter', title='边界'+str(i))
        for c in self.service.get(self.pid)['document']['chapters'][2:]:
            self.save('save_chapter', chapter_id=c['id'], content='有界批次虚构正文。')
        run = self.create_run(2)
        self.assertEqual([len(b['chapter_ids']) for b in run['batches']], [2, 2, 1])
        self.assertEqual(len({cid for b in run['batches'] for cid in b['chapter_ids']}), 5)
        self.assertEqual(run['coverage']['total_chapters'], 5)

    def test_completed_batch_reopen_is_not_reprepared_or_billed(self):
        run = self.create_run()
        task = self.prepare_batch(run)
        self.assertFalse(self.calls)
        self.assertEqual(self.run_task(task)['task']['status'], 'succeeded')
        self.reviews = DeepReviews(TaskCoordinator(NovelService(SQLiteRepository(self.db)), AdapterRegistry()))
        self.addCleanup(self.reviews.coordinator.close)
        again = self.prepare_batch(run)
        self.assertEqual(again['task']['id'], task['task']['id'])
        report = self.reviews.describe_book(self.pid, run['id'])
        self.assertEqual(report['coverage']['ratio'], 1.0)
        self.assertEqual(report['coverage']['unreviewed_chapters'], [])
        self.assertEqual(len(report['reports']), 1)
        self.assertEqual(len(self.calls), 1)

    def test_failed_batch_requires_explicit_retry_and_keeps_history(self):
        run = self.create_run()
        self.mode = 'fake_quote'
        first = self.prepare_batch(run)
        self.assertEqual(self.run_task(first)['task']['status'], 'failed')
        self.assertEqual(self.prepare_batch(run)['task']['id'], first['task']['id'])
        report = self.reviews.describe_book(self.pid, run['id'])
        self.assertEqual(report['failed_batches'], [0])
        self.assertEqual(report['coverage']['ratio'], 0)
        self.mode = 'good'
        second = self.prepare_batch(run, retry=True)
        self.assertNotEqual(first['task']['id'], second['task']['id'])
        self.assertEqual(self.run_task(second)['task']['status'], 'succeeded')
        report = self.reviews.describe_book(self.pid, run['id'])
        self.assertEqual(len(report['batches'][0]['attempts']), 2)
        self.assertEqual(report['coverage']['ratio'], 1)
        self.assertEqual(self.prepare_batch(run, retry=True)['task']['id'], second['task']['id'])
        self.assertEqual(len(self.calls), 2)

    def test_changed_body_is_not_counted_as_current_coverage(self):
        run = self.create_run()
        self.run_task(self.prepare_batch(run))
        self.save('save_chapter', chapter_id=self.cid, content='作者已修改正文。')
        report = self.reviews.describe_book(self.pid, run['id'])
        self.assertIn(self.cid, report['coverage']['stale_chapters'])
        self.assertEqual(report['coverage']['ratio'], .5)
        self.assertFalse(report['coverage']['complete'])

    def test_manifest_idempotency_and_cross_project(self):
        request = self.request(); request.pop('chapter_id'); request.pop('chapter_ids'); request['batch_size'] = 2
        first = self.reviews.create_book(self.pid, request)
        self.assertEqual(self.reviews.create_book(self.pid, request)['id'], first['id'])
        self.assertEqual(len(self.reviews.list_books(self.pid)['runs']), 1)
        with self.assertRaises(ValueError): self.reviews.create_book(self.pid, dict(request, batch_size=1))
        other = self.service.create(title='另一书')['document']['project']['id']
        with self.assertRaises(KeyError): self.reviews.describe_book(other, first['id'])


    def test_multiple_batches_failure_resume_and_book_coverage(self):
        for i in range(2):
            self.save('add_chapter', title='续跑'+str(i))
        for c in self.service.get(self.pid)['document']['chapters'][2:]:
            self.save('save_chapter', chapter_id=c['id'], content='后续批次双侧证据正文。')
        run = self.create_run(2)
        first = self.prepare_batch(run, 0)
        self.assertEqual(self.run_task(first)['task']['status'], 'succeeded')
        self.mode = 'fake_quote'
        self.assertEqual(self.run_task(self.prepare_batch(run, 1))['task']['status'], 'failed')
        partial = self.reviews.describe_book(self.pid, run['id'])
        self.assertEqual(partial['coverage']['ratio'], .5)
        self.assertEqual(len(partial['coverage']['unreviewed_chapters']), 2)
        self.assertEqual(partial['failed_batches'], [1])
        self.mode = 'good'
        self.assertEqual(self.run_task(self.prepare_batch(run, 1, retry=True))['task']['status'], 'succeeded')
        final = self.reviews.describe_book(self.pid, run['id'])
        self.assertTrue(final['coverage']['complete'])
        self.assertEqual(len(final['coverage']['reviewed_chapters']), 4)
        self.assertEqual(final['coverage']['ratio'], 1)
        self.assertEqual(final['coverage']['unreviewed_chapters'], [])
        self.assertEqual(len(final['reports']), 2)
        self.assertEqual(self.prepare_batch(run, 0)['task']['id'], first['task']['id'])
        self.assertEqual(len(self.calls), 3)

    def test_pending_cancel_and_resume_needs_new_explicit_confirmation(self):
        run = self.create_run()
        first = self.prepare_batch(run)
        with self.assertRaises(ValueError): self.engine.start(self.pid, first['task']['id'])
        self.assertEqual(self.prepare_batch(run)['task']['id'], first['task']['id'])
        self.engine.cancel(self.pid, first['task']['id'])
        self.assertEqual(self.reviews.describe_book(self.pid, run['id'])['failed_batches'], [0])
        second = self.prepare_batch(run, retry=True)
        with self.assertRaises(ValueError): self.engine.start(self.pid, second['task']['id'])
        self.assertNotEqual(first['task']['id'], second['task']['id'])
        self.assertFalse(self.calls)

    def test_source_change_blocks_unprepared_batch_and_new_chapter_lowers_coverage(self):
        run = self.create_run()
        self.run_task(self.prepare_batch(run))
        self.save('add_chapter', title='新增尚未审核')
        view = self.reviews.describe_book(self.pid, run['id'])
        self.assertEqual(len(view['coverage']['unreviewed_chapters']), 1)
        self.assertEqual(view['coverage']['ratio'], 2/3)
        self.assertFalse(view['coverage']['complete'])
        self.assertEqual(len(self.calls), 1)

    def test_more_than_forty_chapters_stays_bounded(self):
        # Build a fictional in-memory source state to avoid quadratic disk snapshots.
        state = self.service.get(self.pid)
        template = deepcopy(state['document']['chapters'][0])
        state['document']['chapters'] = [dict(template, id=str(uuid4()), number=i+1) for i in range(41)]
        with patch.object(self.service, 'get', return_value=state):
            run = self.create_run(40)
        self.assertEqual([len(b['chapter_ids']) for b in run['batches']], [40, 1])
        self.assertEqual(len({cid for b in run['batches'] for cid in b['chapter_ids']}), 41)
        self.assertFalse(self.calls)


    def test_interrupted_execution_reopens_without_automatic_resend(self):
        run = self.create_run()
        self.mode = 'slow'
        prepared = self.prepare_batch(run)
        task = prepared['task']
        self.engine.start(self.pid, task['id'], confirmation=dict(confirm_external=True, request_sha256=task['frozen']['parameters']['binding']['request_sha256']))
        self.assertTrue(self.ready.wait(1))
        registry = self.engine.registry
        self.engine.close(); self.release.set()
        self.engine = TaskCoordinator(NovelService(SQLiteRepository(self.db)), registry)
        self.addCleanup(self.engine.close)
        self.service = self.engine.service; self.reviews = DeepReviews(self.engine)
        view = self.reviews.describe_book(self.pid, run['id'])
        self.assertEqual(view['failed_batches'], [0])
        self.assertEqual(view['coverage']['ratio'], 0)
        self.assertEqual(self.prepare_batch(run)['task']['id'], task['id'])
        self.assertEqual(len(self.calls), 1)
        self.mode = 'good'
        second = self.prepare_batch(run, retry=True)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.run_task(second)['task']['status'], 'succeeded')
        self.assertTrue(self.reviews.describe_book(self.pid, run['id'])['coverage']['complete'])
        self.assertEqual(len(self.calls), 2)


if __name__ == '__main__': unittest.main()
