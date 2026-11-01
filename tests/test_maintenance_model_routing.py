import hashlib
import json
import unittest
import sys
import threading
from pathlib import Path
from unittest.mock import Mock
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from novel_writer.application.chat_agent import ChatAgent


class MaintenanceModelRoutingTests(unittest.TestCase):
    def test_only_body_generation_and_revision_use_writer(self):
        writer = {'id': 'writer', 'model_id': 'writing-model'}
        reviewer = {'id': 'reviewer', 'model_id': 'review-model'}
        for purpose in ('writer', 'revision', 'planner', 'maintenance', 'reviewer', 'request'):
            with self.subTest(purpose=purpose):
                agent = ChatAgent.__new__(ChatAgent)
                agent.lock = threading.RLock()
                agent._save = Mock()
                agent.events = {'job': threading.Event()}
                agent.data = {}
                agent.server = SimpleNamespace(offline=False, providers=SimpleNamespace(
                    status=lambda: {'writer': writer, 'reviewer': reviewer}))
                agent._review_guard = Mock()
                agent._freeze_reviewer = Mock(return_value=reviewer)
                agent._request_once = Mock(return_value='完整响应')
                job = {'id': 'job', 'connection': writer, 'configuration_frozen': True}
                self.assertEqual(agent._request(job, [], purpose=purpose), '完整响应')
                selected = agent._request_once.call_args.kwargs.get('connection_override') or writer
                expected = writer if purpose in ('writer', 'revision') else reviewer
                self.assertEqual(selected, expected)

    def test_saved_body_maintenance_uses_frozen_reviewer_connection(self):
        agent = ChatAgent.__new__(ChatAgent)
        agent.lock = threading.RLock()
        chapter = {'id': 'chapter-1', 'number': 1, 'content': '已保存的虚构正文'}
        state = {'document': {'chapters': [chapter]}, 'worldbuilding': '原世界观'}
        reviewer = {'id': 'reviewer', 'model_id': 'independent-review-model'}
        receipt = {'status': 'passed', 'chapter_id': chapter['id'],
                   'body_sha256': hashlib.sha256(chapter['content'].encode()).hexdigest()}
        agent._review_guard = Mock(return_value=state)
        agent._matching_review_receipt = Mock(return_value=receipt)
        agent._freeze_reviewer = Mock(return_value=reviewer)
        agent._save = Mock()
        agent._progress = Mock()
        agent._request = Mock(return_value=json.dumps({'summary': '虚构剧情摘要', 'characters': []}))
        agent._action = Mock()
        job = {'reviews': [receipt], 'connection': {'id': 'writer', 'model_id': 'writing-model'}}

        result = agent._maintain_reviewed_chapter(job, chapter)

        self.assertEqual(result, chapter)
        self.assertEqual(agent._request.call_args.kwargs.get('connection_override'), reviewer)
        self.assertEqual(agent._request.call_args.kwargs['purpose'], 'maintenance')
        self.assertEqual(agent._request.call_args.kwargs['tokens'], 12000)
        agent._action.assert_called_once_with(job, 'save_memory', {
            'title': '第1章剧情与伏笔', 'text': '虚构剧情摘要',
            'kind': 'chapter_summary', 'number': 1})


if __name__ == '__main__':
    unittest.main()
