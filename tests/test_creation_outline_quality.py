import test_book_creation as helpers
import unittest
from novel_writer.application.book_ai import parse_candidate
from types import SimpleNamespace
import json


class CreationOutlineQualityTests(unittest.TestCase):
    setUp = helpers.BookCreationTests.setUp
    call = helpers.BookCreationTests.call
    selected = helpers.BookCreationTests.selected
    seed = helpers.BookCreationTests.seed
    preview = helpers.BookCreationTests.preview
    decide = helpers.BookCreationTests.decide
    def test_rollback_marks_downstream_stale_and_preserves_history(self):
        original = self.seed()
        self.call('save_step', base_version_id=original['id'], step='structure',
                  fields={}, mark='save', next_step='plot')
        report = self.engine.describe(self.pid)
        self.assertIn('structure', report['stale_steps'])
        self.assertNotIn('structure', report['selected']['completed_steps'])
        self.assertEqual(report['versions'][-2], original)
        self.assertTrue(any(c['code'] == 'creation.stale_step'
                            for c in self.preview()['preview']['impact']['conflicts']))
        self.call('save_step', base_version_id=self.selected()['id'], step='plot',
                  fields={'ending': '作者修改结局'}, mark='complete', next_step='structure')
        self.assertIn('structure', self.engine.describe(self.pid)['stale_steps'])
        self.call('save_step', base_version_id=self.selected()['id'], step='structure',
                  fields={}, mark='complete', next_step='structure')
        self.assertNotIn('structure', self.engine.describe(self.pid)['stale_steps'])

    def test_each_step_field_can_be_locked(self):
        version = self.seed()
        self.call('set_lock', version_id=version['id'], field='core_conflict',
                  locked=True, current_lock_id=None, confirmed=True)
        before = self.service.get(self.pid)
        with self.assertRaisesRegex(ValueError, 'lock_conflict'):
            self.call('save_step', base_version_id=version['id'], step='conflict',
                      fields={'core_conflict': '重新生成'}, mark='save', next_step='conflict')
        self.assertEqual(before, self.service.get(self.pid))

    def test_empty_model_structure_is_invalid_candidate(self):
        version = self.seed()
        from novel_writer.domain.book_creation import PlanData, parse
        task = SimpleNamespace(step='structure', source_guard=parse(PlanData, version['data']), id='quality')
        plan, errors = parse_candidate(task, json.dumps({'volumes': []}))
        self.assertIsNone(plan)
        self.assertIn('creation.quality:volumes:required', errors)

    def test_two_candidate_branches_only_chosen_plan_applies(self):
        first = self.seed()
        self.call('fork', version_id=first['id'], name='B')
        self.call('save_step', base_version_id=self.selected()['id'], step='plot',
                  fields={'ending': 'B结局'}, mark='save', next_step='plot')
        second = self.selected()
        self.assertIsNone(self.service.get(self.pid)['document']['book_outline'])
        self.call('choose', version_id=first['id'])
        self.decide(self.preview())
        state = self.service.get(self.pid)
        self.assertEqual(state['document']['book_outline']['ending'], first['data']['ending'])
        self.assertEqual(next(v for v in state['book_creation_versions'] if v['id']==second['id'])['data']['ending'], 'B结局')
