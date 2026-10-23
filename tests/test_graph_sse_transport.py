"""C10-specific SSE from authenticated HTTP request through author adoption."""
import json
from pathlib import Path
import time
import unittest
from uuid import uuid4
import test_graph_http as fixtures
from graph_sse_fixture import graph_sse_wire, PROTOCOLS
from novel_writer.domain.model_contract import request_digest


class GraphSSETransportTests(unittest.TestCase):
    request = fixtures.GraphHTTPTests.request
    stop = fixtures.GraphHTTPTests.stop

    def setUp(self):
        fixtures.GraphHTTPTests.setUp(self)
        self.root = Path(self.temp.name)
        self.body = '\n阿岚🙂到达灯塔。\r\n作者保存的第一份精确原文。'
        self.save_action('save_chapter', chapter_id=self.cid, content=self.body)
        state = self.save_action('add_chapter', title='第二来源')
        self.second = state['document']['chapters'][-1]['id']
        self.save_action('save_chapter', chapter_id=self.second, content='灯塔是小岚的归处🙂。')
        state = self.save_action('add_chapter', title='未来章')
        self.future = state['document']['chapters'][-1]['id']
        self.save_action('save_chapter', chapter_id=self.future, content='未来章秘密，不得混入请求。')

    def save_action(self, action, **fields):
        state = self.server.service.get(self.pid)
        return self.server.service.execute(self.pid, action, fields, expected_revision=state['revision'])

    def prepare(self, wire, protocol, timeout=4000):
        providers = self.server.providers
        connection = providers.save_custom(id=str(uuid4()), name='图谱专用SSE虚构连接', base_url=wire['url'],
            protocol=protocol, model_id='fiction-graph-sse', api_key='fiction-graph-sse-key', allow_local=True)
        providers.manage(id=connection['id'], action='stream_profile', confirmed=True, stream_mode='sse')
        state = self.server.service.get(self.pid)
        request = dict(request_id=str(uuid4()), chapter_id=self.second, selected_chapter_ids=[self.cid, self.second],
            expected_revision=state['revision'], instruction='仅从明确选择的保存正文抽取待核实图谱', max_output_chars=20000, timeout_ms=timeout,
            model_options=dict(adapter_id='configured-http-v2', connection_id=connection['id'], model_id='fiction-graph-sse',
                temperature=.3, max_tokens=2048, budget_limit=.37, allow_unknown_cost=True, prompt_version='graph-extract-json-1'))
        code, result = self.request('POST', self.base+'/knowledge/extract-prepare', request)
        self.assertEqual(code, 200, result)
        self.assertEqual(wire['calls'], [])
        task = result['task']
        binding = task['frozen']['parameters']['binding']
        self.assertEqual(binding['destination']['stream_mode'], 'sse')
        self.assertEqual(binding['budget_limit'], .37)
        self.assertEqual(request_digest(binding['request_body'], binding['destination']), binding['request_sha256'])
        self.assertNotIn('未来章秘密', binding['request_body'])
        self.assertEqual([s['text'] for s in task['frozen']['parameters']['sources']], [self.body, '灯塔是小岚的归处🙂。'])
        self.assertEqual(task['frozen']['context_text'], '')
        return task

    def begin(self, task):
        route = self.base+'/tasks/'+task['id']
        binding = task['frozen']['parameters']['binding']
        permission = dict(confirm_external=True, request_sha256=binding['request_sha256'])
        self.assertEqual(self.request('POST', route+'/execute', dict(permission, confirm_external=False))[0], 422)
        self.assertEqual(self.request('POST', route+'/execute', dict(permission, request_sha256='0'*64))[0], 422)
        self.assertEqual(self.request('POST', route+'/execute', permission, token=False)[0], 403)
        self.assertEqual(self.request('POST', route+'/execute', permission)[0], 202)
        return route

    def preview(self, route, wire):
        self.assertTrue(wire['ready'].wait(2))
        deadline = time.monotonic()+2
        while time.monotonic() < deadline:
            view = self.request('GET', route)[1]
            if view.get('stream_preview', {}).get('text'):
                self.assertTrue(view['stream_preview']['temporary'])
                self.assertNotIn('stream_preview', json.dumps(self.server.service.get(self.pid)))
                self.assertNotIn('fiction-graph-sse-key', json.dumps(view))
                return view
            time.sleep(.01)
        self.fail('Graph SSE did not expose temporary preview before final frames')

    def accept(self, extraction):
        request = dict(operation_id=str(uuid4()), extraction_id=extraction['id'], decision='accepted',
            confirm_inference=False, expected_revision=self.server.service.get(self.pid)['revision'])
        base = self.base+'/knowledge/extract-decide'
        self.assertEqual(self.request('POST', base, request)[0], 422)
        request['confirm_inference'] = True
        code, receipt = self.request('POST', base, request)
        self.assertEqual(code, 200, receipt)
        self.assertEqual(self.request('POST', base, request), (200, receipt))
        return receipt

    def reopen_engine(self, database):
        from novel_writer.application.service import NovelService
        from novel_writer.storage.sqlite_repository import SQLiteRepository
        from novel_writer.application.tasks import TaskCoordinator
        from novel_writer.application.task_protocol import AdapterRegistry
        from novel_writer.application.custom_protocols import ConfiguredHttpAdapter
        service = NovelService(SQLiteRepository(database))
        registry = AdapterRegistry()
        registry.register('audit_chapter', ConfiguredHttpAdapter(self.server.providers, enabled=True))
        engine = TaskCoordinator(service, registry)
        self.addCleanup(engine.close)
        return service, engine

    def test_three_protocols_exact_wire_preview_usage_tail_proposal_and_author_accept(self):
        for protocol in PROTOCOLS:
            with self.subTest(protocol=protocol), graph_sse_wire(protocol) as wire:
                task = self.prepare(wire, protocol)
                before = self.server.service.get(self.pid)
                route = self.begin(task)
                self.preview(route, wire)
                running = self.server.service.get(self.pid)
                self.assertEqual(running['graph_extractions'], before['graph_extractions'])
                self.assertEqual(running['knowledge_nodes'], before['knowledge_nodes'])
                self.assertEqual(wire['calls'][0]['raw'], task['frozen']['parameters']['binding']['request_body'])
                self.assertEqual([s['text'] for s in wire['calls'][0]['payload']['sources']], [self.body, '灯塔是小岚的归处🙂。'])
                wire['release'].set()
                self.server.task_coordinator.wait_idle(5)
                result = self.request('GET', route)[1]
                self.assertEqual(result['task']['status'], 'succeeded', result)
                self.assertNotIn('stream_preview', result)
                self.assertEqual(result['candidates'], [])
                proposal = result['graph_extractions'][0]
                self.assertEqual(len(proposal['output']['nodes'][0]['evidence']), 2)
                self.assertEqual(proposal['output']['nodes'][0]['evidence'][0]['quote'], self.body)
                response = result['model_results'][0]['response']
                self.assertEqual(response['usage'], dict(prompt_tokens=17, completion_tokens=23, total_tokens=40))
                state = self.server.service.get(self.pid)
                self.assertEqual(state['knowledge_nodes'], before['knowledge_nodes'])
                self.assertEqual(state['document'], before['document'])
                listing = self.request('POST', self.base+'/knowledge/extract-list', dict(chapter_id=self.second))[1]
                self.assertFalse(listing['extractions'][-1]['quality_verified'])
                receipt = self.accept(proposal)
                final = self.server.service.get(self.pid)
                self.assertEqual(len(final['knowledge_nodes']), len(before['knowledge_nodes'])+2)
                self.assertEqual(len(final['knowledge_edges']), len(before['knowledge_edges'])+1)
                self.assertEqual(final['document'], before['document'])
                self.assertEqual(len(receipt['node_ids']), 2)
                self.assertEqual(len(wire['calls']), 1)

    def test_three_protocols_invalid_graph_quotes_types_and_missing_evidence_never_propose(self):
        for protocol in PROTOCOLS:
            for outcome in ('quote', 'typed', 'missing'):
                with self.subTest(protocol=protocol, outcome=outcome), graph_sse_wire(protocol, outcome) as wire:
                    task = self.prepare(wire, protocol)
                    before = self.server.service.get(self.pid)
                    route = self.begin(task)
                    self.preview(route, wire)
                    wire['release'].set()
                    self.server.task_coordinator.wait_idle(5)
                    result = self.request('GET', route)[1]
                    self.assertEqual(result['task']['status'], 'failed', result)
                    self.assertEqual(result['model_results'][0]['response']['error_code'], 'invalid_graph_or_evidence')
                    self.assertNotIn('stream_preview', result)
                    for name in ('graph_extractions','knowledge_nodes','knowledge_edges','document'):
                        self.assertEqual(self.server.service.get(self.pid)[name], before[name])

    def test_three_protocols_error_disconnect_truncation_cancel_timeout_and_late_tail(self):
        for protocol in PROTOCOLS:
            for outcome in ('error', 'disconnect', 'truncated', 'cancel', 'timeout'):
                with self.subTest(protocol=protocol, outcome=outcome), graph_sse_wire(protocol, outcome) as wire:
                    task = self.prepare(wire, protocol, timeout=1200 if outcome=='timeout' else 4000)
                    before = self.server.service.get(self.pid)
                    route = self.begin(task)
                    self.preview(route, wire)
                    if outcome == 'cancel':
                        self.assertEqual(self.request('POST', route+'/cancel', {})[0], 200)
                    if outcome in ('cancel', 'timeout'):
                        self.server.task_coordinator.wait_idle(3)
                        terminal = self.request('GET', route)[1]
                        self.assertEqual(terminal['task']['status'], 'cancelled' if outcome=='cancel' else 'failed', terminal)
                        self.assertNotIn('stream_preview', terminal)
                        # The supplier is still gated when local cancellation/timeout wins.
                        self.assertFalse(wire['attempted'].is_set())
                    wire['release'].set()
                    self.assertTrue(wire['closed'].wait(2))
                    self.server.task_coordinator.wait_idle(3)
                    done = self.request('GET', route)[1]
                    self.assertEqual(done['task']['status'], 'cancelled' if outcome=='cancel' else 'failed', done)
                    self.assertNotIn('stream_preview', done)
                    self.assertEqual(done['graph_extractions'], [])
                    current = self.server.service.get(self.pid)
                    for name in ('graph_extractions','knowledge_nodes','knowledge_edges','document'):
                        self.assertEqual(current[name], before[name])
                    database = self.root/'fiction.sqlite3'
                    before_bytes = database.read_bytes()
                    reopened, engine = self.reopen_engine(database)
                    self.assertEqual(engine.describe(self.pid, task['id'])['task'], done['task'])
                    self.assertEqual(reopened.get(self.pid), current)
                    self.assertEqual(database.read_bytes(), before_bytes)
                    with self.assertRaises(ValueError):
                        engine.start(self.pid, task['id'], dict(confirm_external=True, request_sha256=task['frozen']['parameters']['binding']['request_sha256']))
                    self.assertEqual(len(wire['calls']), 1)
                    engine.close()

    def test_three_protocols_reopen_restore_double_copy_need_new_execution_and_author_permission(self):
        from novel_writer.application.backups import create_backup, restore_backup
        from novel_writer.application.migrations import migrate
        from novel_writer.application.skill_import import SkillLibrary
        from novel_writer.storage.sqlite_repository import SQLiteRepository
        from novel_writer.application import graph_extraction
        for protocol in PROTOCOLS:
            with self.subTest(protocol=protocol), graph_sse_wire(protocol) as wire:
                task = self.prepare(wire, protocol)
                route = self.begin(task)
                self.preview(route, wire)
                wire['release'].set()
                self.server.task_coordinator.wait_idle(5)
                done = self.request('GET', route)[1]
                self.assertEqual(done['task']['status'], 'succeeded', done)
                self.accept(done['graph_extractions'][0])
                pending = self.prepare_pending_same_destination(task)
                saved = self.server.service.get(self.pid)
                database = self.root/'fiction.sqlite3'
                before_bytes = database.read_bytes()
                reopened, engine = self.reopen_engine(database)
                self.assertEqual(reopened.get(self.pid), saved)
                self.assertEqual(engine.describe(self.pid, task['id'])['graph_extractions'], done['graph_extractions'])
                self.assertNotIn('stream_preview', engine.describe(self.pid, task['id']))
                self.assertEqual(database.read_bytes(), before_bytes)
                self.assertEqual(len(wire['calls']), 1)
                engine.close()
                SkillLibrary(database)
                package = self.root/(protocol+'-sse.nwbak')
                create_backup(database, package)
                restored = Path(restore_backup(package, self.root/(protocol+'-restored'))['database_path'])
                candidates = [(restored, self.pid)]
                copy_source_pid = self.pid
                for index in (1, 2):
                    target = self.root/(protocol+'-copy-'+str(index)+'.sqlite3')
                    SQLiteRepository(target)
                    SkillLibrary(target)
                    result = migrate(package, target, operation_id=str(uuid4()))
                    copied_pid = next(x['new_id'] for x in result['projects'] if x['old_id']==copy_source_pid)
                    candidates.append((target, copied_pid))
                    if index == 1:
                        # Chain the second copy from the first, retaining frozen wire identity.
                        package = self.root/(protocol+'-copy-package.nwbak')
                        create_backup(target, package)
                        copy_source_pid = copied_pid
                for target, project in candidates:
                    service, restored_engine = self.reopen_engine(target)
                    state = service.get(project)
                    restored_task = state['generation_tasks'][-1]
                    self.assertEqual(restored_task['status'], 'pending')
                    self.assertEqual(restored_task['frozen']['parameters']['binding'], pending['frozen']['parameters']['binding'])
                    calls = len(wire['calls'])
                    with self.assertRaises(ValueError):
                        restored_engine.start(project, restored_task['id'])
                    self.assertEqual(len(wire['calls']), calls)
                    self.assertEqual(len(state['graph_decisions']), len(saved['graph_decisions']))
                    permission = dict(confirm_external=True, request_sha256=restored_task['frozen']['parameters']['binding']['request_sha256'])
                    restored_engine.start(project, restored_task['id'], permission)
                    restored_engine.wait_idle(5)
                    result = restored_engine.describe(project, restored_task['id'])
                    self.assertEqual(result['task']['status'], 'succeeded', result)
                    self.assertEqual(len(wire['calls']), calls+1)
                    proposal = result['graph_extractions'][0]
                    state = service.get(project)
                    self.assertEqual(len(state['knowledge_nodes']), len(saved['knowledge_nodes']))
                    request = dict(operation_id=str(uuid4()), expected_revision=state['revision'],
                        extraction_id=proposal['id'], decision='accepted', confirm_inference=False)
                    with self.assertRaises(ValueError):
                        graph_extraction.decide(restored_engine, project, request)
                    request['confirm_inference'] = True
                    graph_extraction.decide(restored_engine, project, request)
                    self.assertEqual(len(service.get(project)['knowledge_nodes']), len(saved['knowledge_nodes'])+2)
                    restored_engine.close()

    def prepare_pending_same_destination(self, task):
        binding = task['frozen']['parameters']['binding']
        request = dict(request_id=str(uuid4()), chapter_id=self.second, selected_chapter_ids=[self.cid,self.second],
            expected_revision=self.server.service.get(self.pid)['revision'], instruction='恢复后仍须新的执行许可', max_output_chars=20000, timeout_ms=4000,
            model_options={key:binding[key] for key in ('adapter_id','connection_id','model_id','temperature','max_tokens','budget_limit','allow_unknown_cost','prompt_version')})
        code, result = self.request('POST', self.base+'/knowledge/extract-prepare', request)
        self.assertEqual(code, 200, result)
        return result['task']


if __name__ == '__main__':
    unittest.main()
