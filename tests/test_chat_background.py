"""Isolated background executor acceptance; no real providers or credentials."""
import threading
import time
import unittest
from uuid import uuid4
from unittest.mock import patch
import test_console_runs as fixture


class BackgroundChatTests(unittest.TestCase):
    setUp = fixture.ConsoleRunTests.setUp
    action = fixture.ConsoleRunTests.action
    session = fixture.ConsoleRunTests.session
    step = fixture.ConsoleRunTests.step
    save_plan = fixture.ConsoleRunTests.save_plan
    start = fixture.ConsoleRunTests.start
    configure = fixture.ConsoleRunTests.configure

    def runner(self, kinds=('chapter.inspect', 'context.preview')):
        from novel_writer.application.console_background import BackgroundExecutor
        sid = self.session()['id']
        self.save_plan(sid, [self.step(k) for k in kinds])
        run = self.start(sid)['run']['id']
        executor = BackgroundExecutor(self.console)
        self.addCleanup(executor.close)
        return executor, run

    def launch(self, executor, run, limit=10, seconds=10):
        detail = self.console.describe_run(self.pid, run)
        request = dict(step_ids=[v['id'] for v in detail['steps'] if v['status']=='queued'],
                       max_steps=limit, max_seconds=seconds)
        preview = executor.preview(self.pid, run, request)
        grant = dict(operation_id=str(uuid4()), expected_revision=preview['revision'],
                     preview_sha256=preview['sha256'], confirmed=True, **request)
        return executor.start(self.pid, run, grant), grant

    def wait(self, executor, run):
        self.assertTrue(executor.wait_idle(5))
        return executor.describe(self.pid, run)['batches'][-1]

    def test_feature_entry_point_exists(self):
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec('novel_writer.application.console_background'),
                             'Missing durable background executor')

    def test_executes_selected_plan_and_audits_every_step(self):
        executor, run = self.runner()
        self.launch(executor, run)
        batch = self.wait(executor, run)
        self.assertEqual(batch['status'], 'completed')
        detail = self.console.describe_run(self.pid, run)
        self.assertEqual([v['status'] for v in detail['steps']], ['completed', 'completed'])
        events = batch['events']
        done = [v for v in events if v['kind']=='step_completed']
        self.assertEqual(len(done), 2)
        for item in done:
            self.assertIn('source', item['detail'])
            self.assertIn('result', item['detail'])
            self.assertGreaterEqual(item['elapsed_ms'], 0)

    def test_human_node_stops_without_preparing_or_writing_body(self):
        executor, run = self.runner(('chapter.inspect', 'draft', 'context.preview'))
        before = self.service.get(self.pid)['document']
        self.launch(executor, run)
        self.assertEqual(self.wait(executor, run)['status'], 'awaiting_human')
        state = self.service.get(self.pid)
        self.assertEqual(state['document'], before)
        self.assertEqual(state['generation_tasks'], [])
        self.assertEqual([v['status'] for v in state['console_run_steps']], ['completed', 'queued', 'queued'])

    def test_changed_saved_body_is_rejected_before_step_completion(self):
        executor, run = self.runner()
        worker = executor._worker
        def changed(project, batch, token, deadline):
            self.action('save_chapter', dict(chapter_id=self.cid, content='Changed saved body'))
            worker(project, batch, token, deadline)
        with patch.object(executor, '_worker', side_effect=changed):
            self.launch(executor, run)
            batch = self.wait(executor, run)
        self.assertEqual(batch['status'], 'failed')
        self.assertEqual(batch['events'][-1]['detail']['completed_steps'], 0)
        self.assertEqual([v['status'] for v in self.console.describe_run(self.pid, run)['steps']], ['queued', 'queued'])

    def test_step_limit_stops_before_next_step(self):
        executor, run = self.runner()
        self.launch(executor, run, limit=1)
        self.assertEqual(self.wait(executor, run)['status'], 'step_limit')
        self.assertEqual([v['status'] for v in self.console.describe_run(self.pid, run)['steps']], ['completed','queued'])

    def test_cancel_rolls_back_unfinished_read_and_duplicate_start_is_not_parallel(self):
        executor, run = self.runner()
        entered, release = threading.Event(), threading.Event()
        original = self.console._read_tool
        def slow(state, step):
            if threading.current_thread().name.startswith('console-background'):
                entered.set()
                release.wait(3)
            return original(state, step)
        with patch.object(self.console, '_read_tool', side_effect=slow):
            _, grant = self.launch(executor, run)
            self.assertTrue(entered.wait(2))
            # Cancellation signals without waiting for the current read transaction.
            cancel = threading.Thread(target=lambda: executor.control(self.pid, run, 'cancel'))
            cancel.start()
            time.sleep(.03)
            release.set()
            cancel.join(3)
        batch = self.wait(executor, run)
        self.assertEqual(batch['status'], 'cancelled')
        self.assertEqual([v['status'] for v in self.console.describe_run(self.pid, run)['steps']], ['queued','queued'])
        replay = executor.start(self.pid, run, grant)
        self.assertEqual(replay['batch']['id'], batch['id'])
        self.assertEqual(len(executor.describe(self.pid, run)['batches']), 1)

    def test_time_limit_discards_unfinished_result(self):
        executor, run = self.runner()
        original = self.console._read_tool
        def slow(state, step):
            if threading.current_thread().name.startswith('console-background'):time.sleep(.08)
            return original(state, step)
        with patch.object(self.console, '_read_tool', side_effect=slow):
            self.launch(executor, run, seconds=.03)
            batch = self.wait(executor, run)
        self.assertEqual(batch['status'], 'time_limit')
        self.assertEqual([v['status'] for v in self.console.describe_run(self.pid, run)['steps']], ['queued','queued'])


if __name__ == '__main__':unittest.main()
