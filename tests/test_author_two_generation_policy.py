import unittest
from unittest.mock import Mock
from novel_writer.application import chat_agent, chat_context


class AuthorThreeRevisionPolicyTests(unittest.TestCase):
    def test_three_revisions_are_allowed(self):
        self.assertEqual(chat_agent.RUNTIME_AUTHOR_POLICY['automatic_revision_save_limit_per_chapter_per_job'], 3)

    def test_review_budget_and_context_are_enlarged(self):
        self.assertEqual(chat_agent.REVIEWER_MAX_OUTPUT_TOKENS, 393216)
        self.assertEqual(chat_context.LIMIT, 1048576)

    def test_existing_three_revisions_do_not_generate_again(self):
        chapter = {'id': 'chapter', 'number': 1, 'content': '已修订正文'}
        agent = chat_agent.ChatAgent.__new__(chat_agent.ChatAgent)
        agent._review_guard = Mock(return_value={})
        agent._chapter = Mock(return_value=chapter)
        agent._author_rule_release = Mock(return_value={'workflow_accepted': True})
        agent._request = Mock(side_effect=AssertionError('Unexpected extra generation'))
        job = {'automatic_revision_saves': {'chapter': 3}, 'reviews': []}
        result = agent._review_chapter(job, chapter)
        self.assertTrue(result['workflow_accepted'])
        agent._author_rule_release.assert_called_once()
        agent._request.assert_not_called()
