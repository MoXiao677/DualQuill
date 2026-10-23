"""C10 fictional loopback contracts, no real provider/credential access."""
from contextlib import contextmanager
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import threading
import unittest
from uuid import uuid4

import test_configured_tasks as fixtures
from novel_writer.application import graph_extraction as graph
from novel_writer.application.graph_queries import paths
from novel_writer.application.graph_index import rebuild, sync
from novel_writer.application.knowledge import view, command, merge_preview


@contextmanager
def graph_wire(protocol='openai-chat', bad=None, gate=None):
    from novel_writer.domain.connections import canonical_messages
    calls = []
    called = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            payload = json.loads(canonical_messages(body, protocol)[1]['content'])
            calls.append(payload)
            called.set()
            if gate:
                gate.wait(2)
            sources = payload['sources']
            evidence = [dict(source_index=i, start=0, end=len(s['text']), quote=s['text']) for i, s in enumerate(sources)]
            output = dict(overview='虚构图谱，待作者核实', nodes=[
                dict(key='a', kind='character', label='阿岚', aliases=['小岚'], evidence=evidence),
                dict(key='b', kind='location', label='灯塔', aliases=['旧塔'], evidence=evidence[:1]),
                dict(key='c', kind='organization', label='守塔会', aliases=[], evidence=evidence[:1])],
                edges=[dict(from_key='a', to_key='b', relation='到达', evidence=evidence),
                       dict(from_key='b', to_key='c', relation='属于', evidence=evidence[:1])])
            if bad == 'missing':
                output['edges'][0]['evidence'] = []
            elif bad == 'quote':
                output['nodes'][0]['evidence'][0]['quote'] = '没有保存的引文'
            elif bad == 'span':
                output['nodes'][0]['evidence'][0]['end'] += 1
            elif bad == 'source':
                output['edges'][0]['evidence'][0]['source_index'] = 99
            elif bad == 'endpoint':
                output['edges'][0]['to_key'] = 'outside-book'
            elif bad == 'duplicate':
                output['nodes'][1]['key'] = 'a'
            content = json.dumps(output, ensure_ascii=False)
            if protocol == 'anthropic-messages':
                response = dict(role='assistant', content=[dict(type='text', text=content)], stop_reason='end_turn')
            elif protocol == 'gemini-content':
                response = dict(candidates=[dict(content=dict(role='model', parts=[dict(text=content)]), finishReason='STOP')])
            else:
                response = dict(choices=[dict(message=dict(role='assistant', content=content), finish_reason='stop')])
            data = json.dumps(response, ensure_ascii=False).encode('utf8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, kwargs=dict(poll_interval=.01), daemon=True)
    worker.start()
    try:
        yield dict(url='http://127.0.0.1:' + str(server.server_port) + '/v1', calls=calls, called=called)
    finally:
        if gate:
            gate.set()
        server.shutdown()
        server.server_close()
        worker.join(3)


class GraphTests(unittest.TestCase):
    setUp = fixtures.ConfiguredTaskTests.setUp
    save = fixtures.ConfiguredTaskTests.save

    def prepare(self, connection, **overrides):
        request = dict(request_id=str(uuid4()), chapter_id=self.cid, selected_chapter_ids=[self.cid],
                       expected_revision=self.service.get(self.pid)['revision'], instruction='仅引用已保存虚构正文',
                       max_output_chars=20000, timeout_ms=3000,
                       model_options=dict(adapter_id='configured-http-v2', connection_id=connection['id'],
                                          model_id='fiction-model', temperature=.3, max_tokens=2048,
                                          budget_limit=1.0, allow_unknown_cost=True, prompt_version=graph.PROMPT))
        request.update(overrides)
        return graph.prepare(self.engine, self.pid, request)

    def execute(self, task):
        binding = task['frozen']['parameters']['binding']
        self.engine.start(self.pid, task['id'], dict(confirm_external=True, request_sha256=binding['request_sha256']))
        self.engine.wait_idle(6)
        result = self.engine.describe(self.pid, task['id'])
        return result

    def decide(self, extraction, **changes):
        request = dict(operation_id=str(uuid4()), expected_revision=self.service.get(self.pid)['revision'],
                       extraction_id=extraction['id'], decision='accepted', confirm_inference=True)
        request.update(changes)
        return graph.decide(self.engine, self.pid, request)

    def extraction(self):
        return graph.describe(self.engine, self.pid, {})['extractions'][-1]

    def cmd(self, action, **values):
        return command(self.service, self.pid, action, dict(operation_id=str(uuid4()),
                       expected_revision=self.service.get(self.pid)['revision'], **values))

    def test_three_protocols_exact_evidence_proposal_only_manual_atomic_accept_reopen(self):
        from novel_writer.application.service import NovelService
        from novel_writer.storage.sqlite_repository import SQLiteRepository
        for protocol in ('openai-chat', 'anthropic-messages', 'gemini-content'):
            with self.subTest(protocol=protocol), graph_wire(protocol) as wire:
                before = self.service.get(self.pid)
                task = self.prepare(self.save(wire['url'], protocol))['task']
                self.assertEqual(wire['calls'], [])
                self.assertEqual(self.service.get(self.pid)['workspace_version'], 45)
                result = self.execute(task)
                self.assertEqual(result['task']['status'], 'succeeded', result)
                proposed = self.extraction()
                self.assertFalse(proposed['quality_verified'])
                self.assertEqual(len(proposed['output']['nodes']), 3)
                self.assertEqual(self.service.get(self.pid)['knowledge_nodes'], before.get('knowledge_nodes', []))
                self.assertEqual(self.service.get(self.pid)['document'], before['document'])
                with self.assertRaises(ValueError):
                    self.decide(proposed, confirm_inference=False)
                identity = str(uuid4())
                receipt = self.decide(proposed, operation_id=identity)
                self.assertEqual(self.decide(proposed, operation_id=identity), receipt)
                saved = self.service.get(self.pid)
                self.assertEqual(len(saved['knowledge_nodes']), len(before.get('knowledge_nodes', [])) + 3)
                self.assertEqual(saved['knowledge_nodes'][-3]['aliases'], ['小岚'])
                self.assertEqual(NovelService(SQLiteRepository(self.root / 'fiction.sqlite3')).get(self.pid), saved)
                self.assertEqual(len(wire['calls']), 1)

    def test_invalid_quote_missing_evidence_unknown_endpoint_and_duplicates_rejected(self):
        for bad in ('missing', 'quote', 'span', 'source', 'endpoint', 'duplicate'):
            with self.subTest(bad=bad), graph_wire(bad=bad) as wire:
                task = self.prepare(self.save(wire['url']))['task']
                result = self.execute(task)
                self.assertEqual(result['task']['status'], 'failed', result)
                self.assertEqual(result['task']['error_code'], 'invalid_graph_or_evidence')
                self.assertEqual(self.service.get(self.pid)['graph_extractions'], [])
                self.assertEqual(self.service.get(self.pid)['knowledge_nodes'], [])

    def test_multi_source_future_crossbook_expired_sources_and_bounded_paths(self):
        old = self.cid
        state = self.service.get(self.pid)
        state = self.service.execute(self.pid, 'add_chapter', dict(title='虚构后章'), expected_revision=state['revision'])
        later = state['document']['chapters'][-1]['id']
        state = self.service.execute(self.pid, 'save_chapter', dict(chapter_id=later, content='后来阿岚🙂加入守塔会。'), expected_revision=state['revision'])
        with graph_wire() as wire:
            c = self.save(wire['url'])
            before = self.service.get(self.pid)
            for selected in ([old, later], ['other-book']):
                with self.assertRaises(ValueError):
                    self.prepare(c, selected_chapter_ids=selected)
                self.assertEqual(self.service.get(self.pid), before)
            self.cid = later
            result = self.execute(self.prepare(c, selected_chapter_ids=[old, later])['task'])
            self.assertEqual(result['task']['status'], 'succeeded', result)
            self.assertEqual(len(self.extraction()['output']['nodes'][0]['evidence']), 2)
            self.assertEqual(graph.describe(self.engine, self.pid, dict(chapter_id=old))['extractions'], [])
            receipt = self.decide(self.extraction())
            a, b, c = receipt['node_ids']
            self.assertNotIn(a, {n['id'] for n in view(self.service, self.pid, dict(chapter_id=old))['nodes']})
            found = paths(self.service, self.pid, dict(from_id=a, to_id=c, chapter_id=later))
            self.assertEqual(found['paths'][0]['node_ids'], [a, b, c])
            self.assertFalse(paths(self.service, self.pid, dict(from_id=c, to_id=a))['paths'])
            self.assertTrue(paths(self.service, self.pid, dict(from_id=c, to_id=a, direction='both'))['paths'])
            self.assertFalse(paths(self.service, self.pid, dict(from_id=a, to_id=c, relations=['不存在']))['paths'])
            for options in (dict(max_depth=7), dict(max_paths=51), dict(to_id='other-book')):
                with self.assertRaises(ValueError):
                    paths(self.service, self.pid, {**dict(from_id=a, to_id=c), **options})
            state = self.service.get(self.pid)
            self.service.execute(self.pid, 'save_chapter', dict(chapter_id=old, content='作者改了较早来源'), expected_revision=state['revision'])
            self.assertTrue(next(n for n in view(self.service, self.pid, {})['nodes'] if n['id'] == a)['outdated'])
            with self.assertRaises(ValueError):
                paths(self.service, self.pid, dict(from_id=a, to_id=c))

    def test_stale_before_send_accept_and_cancel_reject_leave_no_official_graph(self):
        with graph_wire() as wire:
            c = self.save(wire['url'])
            task = self.prepare(c)['task']
            state = self.service.get(self.pid)
            self.service.execute(self.pid, 'save_chapter', dict(chapter_id=self.cid, content='更新虚构稿。'), expected_revision=state['revision'])
            with self.assertRaises(ValueError):
                self.execute(task)
            self.assertEqual(wire['calls'], [])
            result = self.execute(self.prepare(c)['task'])
            self.assertEqual(result['task']['status'], 'succeeded', result)
            p = self.extraction()
            state = self.service.get(self.pid)
            self.service.execute(self.pid, 'save_chapter', dict(chapter_id=self.cid, content='又一次更新虚构稿。'), expected_revision=state['revision'])
            with self.assertRaises(ValueError):
                self.decide(p)
            self.decide(p, decision='rejected', confirm_inference=False)
            result = self.execute(self.prepare(c)['task'])
            self.assertEqual(result['task']['status'], 'succeeded', result)
            self.decide(self.extraction(), decision='cancelled', confirm_inference=False)
            self.assertEqual(self.service.get(self.pid)['knowledge_nodes'], [])

    def test_cancel_running_has_no_late_extraction_or_formal_artifacts(self):
        gate = threading.Event()
        with graph_wire(gate=gate) as wire:
            task = self.prepare(self.save(wire['url']))['task']
            b = task['frozen']['parameters']['binding']
            self.engine.start(self.pid, task['id'], dict(confirm_external=True, request_sha256=b['request_sha256']))
            self.assertTrue(wire['called'].wait(2), 'fictional request must be in flight before cancellation')
            self.engine.cancel(self.pid, task['id'])
            gate.set()
            self.engine.wait_idle(4)
            state = self.service.get(self.pid)
            self.assertEqual(self.engine.describe(self.pid, task['id'])['task']['status'], 'cancelled')
            self.assertEqual(state['graph_extractions'], [])
            self.assertEqual(state['knowledge_nodes'], [])

    def test_merge_preview_restore_and_incremental_rebuild_same_graph_zero_source_write(self):
        with graph_wire() as wire:
            self.assertEqual(self.execute(self.prepare(self.save(wire['url']))['task'])['task']['status'], 'succeeded')
            receipt = self.decide(self.extraction())
            original = view(self.service, self.pid, {})
            b = receipt['node_ids'][1]
            extra = self.cmd('save_node', kind='location', label='新塔', aliases=[], memory_ids=[],
                             position_chapter_id=self.cid, source=dict(kind='chapter', entity_id=self.cid), confirmed=True)
            before = self.service.get(self.pid)
            preview = merge_preview(self.service, self.pid, dict(source_id=b, target_id=extra['id']))
            self.assertEqual(self.service.get(self.pid), before)
            self.assertEqual(len(preview['edges']), 2)
            merged = self.cmd('merge', source_id=b, target_id=extra['id'])
            self.cmd('restore_merge', merge_id=merged['id'])
            current = self.service.get(self.pid)
            incremental = sync(self.service, current)
            before_bytes = (self.root / 'fiction.sqlite3').read_bytes()
            rebuilt = rebuild(self.service, self.pid, dict(expected_revision=current['revision']))
            self.assertTrue(rebuilt['source_unchanged'])
            self.assertEqual(incremental, sync(self.service, current))
            self.assertEqual((self.root / 'fiction.sqlite3').read_bytes(), before_bytes)
            after = view(self.service, self.pid, {})
            self.assertEqual({e['id'] for e in after['edges']}, {e['id'] for e in original['edges']})

    def test_complete_backup_restore_double_copy_pending_request_needs_new_confirmation(self):
        from novel_writer.application.backups import create_backup, restore_backup
        from novel_writer.application.migrations import migrate
        from novel_writer.application.service import NovelService
        from novel_writer.application.skill_import import SkillLibrary
        from novel_writer.storage.sqlite_repository import SQLiteRepository, validate_workspace
        with graph_wire() as wire:
            c = self.save(wire['url'])
            self.assertEqual(self.execute(self.prepare(c)['task'])['task']['status'], 'succeeded')
            self.decide(self.extraction())
            pending = self.prepare(c)['task']
            state = self.service.get(self.pid)
            bad = deepcopy(state)
            bad['workspace_version'] = 35
            bad.pop('graph_extractions')
            bad.pop('graph_decisions')
            with self.assertRaises(ValueError):
                validate_workspace(bad)
            SkillLibrary(self.root / 'fiction.sqlite3')
            package = self.root / 'graph.nwbak'
            self.assertEqual(create_backup(self.root / 'fiction.sqlite3', package)['backup_format_version'], 51)
            restored = restore_backup(package, self.root / 'graph-restored')
            self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid), state)
            source_package = package
            for i in range(2):
                target = self.root / ('graph-copy-' + str(i) + '.sqlite3')
                SQLiteRepository(target)
                SkillLibrary(target)
                copied = migrate(source_package, target, operation_id=str(uuid4()))
                clone = NovelService(SQLiteRepository(target)).get(copied['projects'][0]['new_id'])
                self.assertEqual(len(clone['graph_extractions']), 1)
                self.assertEqual(len(clone['graph_decisions']), 1)
                self.assertEqual(clone['generation_tasks'][-1]['status'], 'pending')
                self.assertEqual(clone['generation_tasks'][-1]['frozen']['parameters']['binding'], pending['frozen']['parameters']['binding'])
                self.assertNotEqual(clone['knowledge_nodes'][0]['id'], state['knowledge_nodes'][0]['id'])
                source_package = self.root / ('copy-package-' + str(i) + '.nwbak')
                create_backup(target, source_package)
            self.assertEqual(len(wire['calls']), 1)

    def test_path_enumeration_has_work_bound_and_no_cycles(self):
        from unittest.mock import patch
        nodes = [dict(id=str(i)) for i in range(13)]
        edges = [dict(id=str(i)+'-'+str(j), from_id=str(i), to_id=str(j), relation='虚构') for i in range(12) for j in range(12) if i != j]
        with patch('novel_writer.application.knowledge.view', return_value=dict(nodes=nodes, edges=edges, revision=1)):
            found = paths(self.service, self.pid, dict(from_id='0', to_id='12', max_depth=6))
            self.assertTrue(found['truncated'])
            self.assertEqual(found['expansions'], 5000)
            result = paths(self.service, self.pid, dict(from_id='0', to_id='4', max_depth=6, max_paths=3))
            self.assertEqual(len(result['paths']), 3)
            self.assertTrue(all(len(p['node_ids']) == len(set(p['node_ids'])) for p in result['paths']))

    def test_accept_transaction_rollback_tamper_identity_conflict_and_retry(self):
        import sqlite3
        from contextlib import closing
        def rows(path):
            with closing(sqlite3.connect(path)) as connection:
                tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
                return {table: connection.execute('SELECT * FROM "'+table+'" ORDER BY 1').fetchall() for table in tables}
        with graph_wire() as wire:
            result = self.execute(self.prepare(self.save(wire['url']))['task'])
            self.assertEqual(result['task']['status'], 'succeeded')
            p = self.extraction()
            revision = self.service.get(self.pid)['revision']
            db = self.root/'fiction.sqlite3'
            identity = str(uuid4())
            with closing(sqlite3.connect(db)) as connection, connection:
                connection.execute("CREATE TRIGGER fail_graph BEFORE INSERT ON project_snapshots WHEN NEW.revision="+str(revision+1)+" BEGIN SELECT RAISE(ABORT,'fictional graph disk failure'); END")
            before = rows(db)
            with self.assertRaises(sqlite3.Error):
                self.decide(p, operation_id=identity)
            self.assertEqual(rows(db), before)
            with closing(sqlite3.connect(db)) as connection, connection:
                connection.execute('DROP TRIGGER fail_graph')
            receipt = self.decide(p, operation_id=identity)
            with self.assertRaises(ValueError):
                self.decide(p, operation_id=identity, decision='rejected')
            saved = self.service.get(self.pid)
            changed = deepcopy(saved)
            changed['graph_extractions'][0]['output']['nodes'][0]['aliases'] = ['伪造别名']
            with self.assertRaises(ValueError):
                self.service.repository.save(changed, expected_revision=saved['revision'])
            self.assertEqual(self.service.get(self.pid), saved)
            with self.assertRaises(ValueError):
                command(self.service, self.pid, 'save_node', dict(operation_id=receipt['id'], expected_revision=saved['revision'], kind='location', label='身份绕过', aliases=[], memory_ids=[], position_chapter_id=self.cid, source=dict(kind='chapter', entity_id=self.cid), confirmed=True))

    def test_archived_source_blocks_send_and_accept_and_excludes_accepted_paths(self):
        def action(name):
            self.service.execute(self.pid, name, dict(chapter_id=self.cid, confirmed=True),
                                 expected_revision=self.service.get(self.pid)['revision'])
        with graph_wire() as wire:
            connection = self.save(wire['url'])
            task = self.prepare(connection)['task']
            action('archive_chapter')
            with self.assertRaises(ValueError):
                self.execute(task)
            self.assertEqual(wire['calls'], [])
            action('unarchive_chapter')
            self.assertEqual(self.execute(self.prepare(connection)['task'])['task']['status'], 'succeeded')
            proposal = self.extraction()
            action('archive_chapter')
            with self.assertRaises(ValueError):
                self.decide(proposal)
            self.assertEqual(self.service.get(self.pid)['knowledge_nodes'], [])
            action('unarchive_chapter')
            receipt = self.decide(proposal)
            self.assertEqual(len(view(self.service, self.pid, dict(ready_only=True))['nodes']), 3)
            action('archive_chapter')
            self.assertEqual(view(self.service, self.pid, dict(ready_only=True))['nodes'], [])
            self.assertTrue(all(n['outdated'] for n in view(self.service, self.pid, {})['nodes']))
            with self.assertRaises(ValueError):
                paths(self.service, self.pid, dict(from_id=receipt['node_ids'][0], to_id=receipt['node_ids'][2]))
            self.assertEqual(len(wire['calls']), 1)

    def test_merge_keeps_future_aliases_out_of_earlier_view_and_restore_retains_quotes(self):
        early = self.cid
        first = self.cmd('save_node', kind='location', label='灯塔', aliases=[], memory_ids=[], position_chapter_id=early, source=dict(kind='chapter', entity_id=early), confirmed=True)
        state = self.service.get(self.pid)
        state = self.service.execute(self.pid, 'add_chapter', dict(title='未来章'), expected_revision=state['revision'])
        later = state['document']['chapters'][-1]['id']
        state = self.service.execute(self.pid, 'save_chapter', dict(chapter_id=later, content='未来别名秘密'), expected_revision=state['revision'])
        second = self.cmd('save_node', kind='location', label='未来别名秘密', aliases=[], memory_ids=[], position_chapter_id=later, source=dict(kind='chapter', entity_id=later), confirmed=True)
        merged = self.cmd('merge', source_id=second['id'], target_id=first['id'])
        earlier = view(self.service, self.pid, dict(chapter_id=early))
        self.assertNotIn('未来别名秘密', json.dumps(earlier, ensure_ascii=False))
        self.assertIn('未来别名秘密', json.dumps(view(self.service, self.pid, {}), ensure_ascii=False))
        self.cmd('restore_merge', merge_id=merged['id'])
        self.assertEqual([n['label'] for n in view(self.service, self.pid, dict(chapter_id=early))['nodes']], ['灯塔'])


if __name__ == '__main__':
    unittest.main()
