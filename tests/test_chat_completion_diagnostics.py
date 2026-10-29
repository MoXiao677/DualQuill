import unittest

from novel_writer.application.chat_completion import chat_completion_text


class ChatCompletionTextTests(unittest.TestCase):
    def payload(self, reason='stop', **message_fields):
        message = {'content': 'CONTENT_SECRET'}
        message.update(message_fields)
        return {
            'choices': [{'finish_reason': reason, 'message': message}],
            'api_key': 'CREDENTIAL_SECRET',
        }

    def assert_rejected(self, data, safe_reason, unauthorized=False):
        with self.assertRaises(ValueError) as caught:
            chat_completion_text(data)
        text = str(caught.exception)
        self.assertIn('finish_reason=' + safe_reason + ';', text)
        self.assertEqual('unauthorized tools' in text, unauthorized)
        self.assertNotIn('CONTENT_SECRET', text)
        self.assertNotIn('CREDENTIAL_SECRET', text)
        return text

    def test_normal_stop_returns_content_unchanged(self):
        for content in ('hello', '', '  hello\n'):
            with self.subTest(content=content):
                self.assertEqual(
                    chat_completion_text(self.payload(content=content)), content
                )

    def test_empty_call_fields_are_not_unauthorized(self):
        for fields in (
            {'tool_calls': []},
            {'tool_calls': None},
            {'function_call': {}},
            {'function_call': None},
            {'tool_calls': [], 'function_call': {}},
        ):
            with self.subTest(fields=fields):
                self.assertEqual(
                    chat_completion_text(self.payload(**fields)), 'CONTENT_SECRET'
                )

    def test_non_stop_reasons_are_rejected(self):
        for reason in ('length', 'content_filter', 'tool_calls', 'function_call', None):
            with self.subTest(reason=reason):
                self.assert_rejected(
                    self.payload(reason), 'null' if reason is None else reason
                )

    def test_missing_finish_reason_is_rejected_as_null(self):
        data = self.payload()
        del data['choices'][0]['finish_reason']
        self.assert_rejected(data, 'null')

    def test_unknown_reasons_are_redacted_and_rejected(self):
        for reason in (
            'PROVIDER_SECRET\nCREDENTIAL_SECRET',
            '', 'STOP', ' stop ', 'unknown', 'null',
            1, True, [], {}, ['PROVIDER_SECRET'],
        ):
            with self.subTest(reason=reason):
                text = self.assert_rejected(self.payload(reason), 'unknown')
                self.assertNotIn('PROVIDER_SECRET', text)
                self.assertNotIn('\n', text)

    def test_nonempty_calls_are_rejected_even_with_stop(self):
        for field, values in (
            ('tool_calls', ([{'id': 'CREDENTIAL_SECRET'}], {'x': 1}, 'CONTENT_SECRET')),
            ('function_call', ({'name': 'CREDENTIAL_SECRET'}, ['x'], 'CONTENT_SECRET')),
        ):
            for value in values:
                with self.subTest(field=field, value=value):
                    self.assert_rejected(
                        self.payload(**{field: value}), 'stop', unauthorized=True
                    )

    def test_finish_reason_and_unauthorized_tools_are_both_reported(self):
        for reason in ('length', 'content_filter', 'tool_calls', 'function_call', None):
            for field in ('tool_calls', 'function_call'):
                with self.subTest(reason=reason, field=field):
                    self.assert_rejected(
                        self.payload(reason, **{field: {'name': 'CREDENTIAL_SECRET'}}),
                        'null' if reason is None else reason,
                        unauthorized=True,
                    )

    def test_both_call_fields_are_rejected(self):
        self.assert_rejected(
            self.payload(
                tool_calls=[{'id': 'CREDENTIAL_SECRET'}],
                function_call={'name': 'CONTENT_SECRET'},
            ),
            'stop',
            unauthorized=True,
        )


if __name__ == '__main__':
    unittest.main()
