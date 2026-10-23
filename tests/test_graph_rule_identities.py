"""Complete graph rule identities, using only fictional fixtures when authorized to run."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid4, uuid5

from test_graph_extraction import GraphTests, graph_wire
from test_configured_tasks import ConfiguredTaskTests
from novel_writer.application.scoped_rules import RuleCoordinator, require_fresh_rules
from novel_writer.application.tasks import get_task
from novel_writer.domain.tasks import capture_dependency, dependency_equal


class GraphRuleIdentityTests(unittest.TestCase):
    setUp = GraphTests.setUp
    save = GraphTests.save
    prepare = GraphTests.prepare
    execute = GraphTests.execute
    decide = GraphTests.decide
    extraction = GraphTests.extraction

    def state(self):
        return self.service.get(self.pid)

    def save_rule(self, operation_id=None, text='虚构规则身份约束', scope='book', target=None):
        return RuleCoordinator(self.service).save(self.pid, dict(
            operation_id=operation_id or str(uuid4()), rule_id=None, scope=scope,
            scope_id=target if target is not None else self.pid,
            kind='guidance', text=text, enabled=True))

    def ordered_operations(self):
        # Pick deterministic UUID5 ordering without retrying any writes.
        choices = [str(uuid5(NAMESPACE_URL, 'fiction-graph-rule-operation/' + str(i))) for i in range(16)]
        choices.sort(key=lambda value: str(uuid5(NAMESPACE_URL, value + '/rule')))
        return choices[0], choices[-1]

    def confirmation(self, task):
        return dict(confirm_external=True,
                    request_sha256=task['frozen']['parameters']['binding']['request_sha256'])

    def test_hidden_same_text_new_identity_blocks_send_without_state_or_wire_change(self):
        first, later = self.ordered_operations()
        old = self.save_rule(first)
        with graph_wire() as wire:
            task = self.prepare(self.save(wire['url']))['task']
            duplicate = self.save_rule(later)
            self.assertLess(old['id'], duplicate['id'])
            visible = RuleCoordinator(self.service).resolve(self.pid, self.cid)['rules']
            self.assertEqual([v['id'] for v in visible], [old['id']])
            before = self.state()
            with self.assertRaises(ValueError):
                self.engine.start(self.pid, task['id'], self.confirmation(task))
            self.assertEqual(self.state(), before)
            self.assertEqual(wire['calls'], [])
            self.assertEqual(get_task(before, task['id']).status, 'pending')

    def test_hidden_same_text_new_identity_blocks_accept_without_official_artifacts(self):
        first, later = self.ordered_operations()
        self.save_rule(first)
        with graph_wire() as wire:
            task = self.prepare(self.save(wire['url']))['task']
            result = self.execute(task)
            self.assertEqual(result['task']['status'], 'succeeded')
            extraction = self.extraction()
            self.save_rule(later)
            before = self.state()
            with self.assertRaises(ValueError):
                self.decide(extraction)
            self.assertEqual(self.state(), before)
            self.assertEqual(len(wire['calls']), 1)
            self.assertEqual(before['knowledge_nodes'], [])
            self.assertEqual(before['knowledge_edges'], [])
            self.assertEqual(before['graph_decisions'], [])

    def test_preexisting_duplicates_all_freeze_and_stay_out_of_model_sources(self):
        first, later = self.ordered_operations()
        rules = [self.save_rule(value) for value in (first, later)]
        with graph_wire() as wire:
            task = self.prepare(self.save(wire['url']))['task']
            frozen = get_task(self.state(), task['id'])
            dependencies = [v for v in frozen.frozen.dependencies if v.kind == 'rule']
            self.assertEqual({v.entity_id for v in dependencies}, {v['id'] for v in rules})
            for dependency in dependencies:
                self.assertTrue(dependency_equal(dependency, capture_dependency(
                    self.state(), 'rule', dependency.entity_id, use=dependency.use)))
            self.assertEqual(task['frozen']['context_text'], '')
            result = self.execute(task)
            self.assertEqual(result['task']['status'], 'succeeded')
            self.assertEqual(len(wire['calls']), 1)
            self.assertNotIn('虚构规则身份约束', json.dumps(wire['calls'], ensure_ascii=False))
            self.decide(self.extraction())
            self.assertTrue(self.state()['knowledge_nodes'])

    def test_worker_rechecks_identity_added_after_atomic_start_before_adapter(self):
        first, later = self.ordered_operations()
        self.save_rule(first)
        with graph_wire() as wire:
            task = self.prepare(self.save(wire['url']))['task']
            # Retain normal atomic start, but hold the worker without a timing race.
            with patch.object(self.engine, '_worker') as held:
                self.engine.start(self.pid, task['id'], self.confirmation(task))
                self.engine.wait_idle(2)
            self.assertEqual(held.call_count, 1)
            self.save_rule(later)
            self.engine._worker(*held.call_args.args, **held.call_args.kwargs)
            result = self.engine.describe(self.pid, task['id'])
            self.assertEqual(result['task']['status'], 'failed')
            self.assertEqual(wire['calls'], [])
            self.assertEqual(self.state()['graph_extractions'], [])

    def test_unchanged_snapshot_readable_and_old_dedup_snapshot_fails_closed_after_addition(self):
        first, later = self.ordered_operations()
        self.save_rule(first)
        with graph_wire() as wire:
            task = self.prepare(self.save(wire['url']))['task']
            current = get_task(self.state(), task['id'])
            require_fresh_rules(self.state(), current)
            frozen_before = deepcopy(task['frozen'])
            self.save_rule(later)
            # This models an immutable older dedup-only snapshot; never patch stored history.
            with self.assertRaises(ValueError):
                require_fresh_rules(self.state(), current)
            stored = self.engine.describe(self.pid, task['id'])
            self.assertFalse(stored['rules_fresh'])
            self.assertEqual(stored['task']['frozen'], frozen_before)
            self.assertEqual(wire['calls'], [])

    def test_unrelated_task_binding_and_rule_do_not_expire_graph(self):
        self.save_rule()
        with graph_wire() as wire:
            task = self.prepare(self.save(wire['url']))['task']
            rules = RuleCoordinator(self.service)
            binding = str(uuid4())
            rules.bind_task(self.pid, dict(request_id=binding, chapter_id=self.cid,
                                          task_type='rewrite_chapter'))
            self.save_rule(scope='task', target=binding, text='仅另一个任务的虚构约束')
            require_fresh_rules(self.state(), get_task(self.state(), task['id']))
            self.assertEqual(self.execute(task)['task']['status'], 'succeeded')
            self.assertEqual(len(wire['calls']), 1)

    def test_non_graph_task_keeps_existing_dedup_contract(self):
        first, later = self.ordered_operations()
        self.save_rule(first)
        with graph_wire() as wire:
            task = ConfiguredTaskTests.prepare(self, self.save(wire['url']))['task']
            self.save_rule(later)
            require_fresh_rules(self.state(), get_task(self.state(), task['id']))
            self.assertEqual(wire['calls'], [])

    def test_hidden_duplicate_version_disable_and_archive_all_invalidate_frozen_graph(self):
        first, later = self.ordered_operations()
        self.save_rule(first)
        duplicate = self.save_rule(later)
        coordinator = RuleCoordinator(self.service)
        with graph_wire() as wire:
            for change in ('version', 'disable', 'archive'):
                with self.subTest(change=change):
                    task = self.prepare(self.save(wire['url']))['task']
                    if change == 'version':
                        coordinator.save(self.pid, dict(operation_id=str(uuid4()),
                            rule_id=duplicate['id'], scope='book', scope_id=self.pid,
                            kind='guidance', text='虚构规则身份约束', enabled=True))
                    elif change == 'disable':
                        coordinator.set_enabled(self.pid, dict(rule_id=duplicate['id'], enabled=False))
                    else:
                        coordinator.archive(self.pid, dict(rule_id=duplicate['id'], archived=True))
                    before = self.state()
                    with self.assertRaises(ValueError):
                        self.engine.start(self.pid, task['id'], self.confirmation(task))
                    self.assertEqual(self.state(), before)
                    self.assertEqual(wire['calls'], [])
                    if change == 'disable':
                        coordinator.set_enabled(self.pid, dict(rule_id=duplicate['id'], enabled=True))


if __name__ == '__main__':
    unittest.main()
