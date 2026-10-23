"""Planning field boundaries independent of the UI and model transport."""
import unittest
from novel_writer.application.fields import structured_list, check_fields
from novel_writer.domain.models import VolumePlan, DataValidationError


class PlanningFieldsTests(unittest.TestCase):
    def test_unknown_volume_fields_rejected(self):
        with self.assertRaises(DataValidationError):
            structured_list([dict(number=1, title='卷', injected=True)], VolumePlan, '分卷')

    def test_non_object_and_missing_title_rejected(self):
        for value in ('卷', [None], [dict(number=1)]):
            with self.subTest(value=value), self.assertRaises(DataValidationError):
                structured_list(value, VolumePlan, '分卷')

    def test_step_fields_cannot_write_other_steps(self):
        from novel_writer.domain.book_creation import STEP_FIELDS
        with self.assertRaises(DataValidationError):
            check_fields(dict(ending='越界'), STEP_FIELDS['idea'])
