import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from novel_writer.application.chat_agent import ChatAgent
from novel_writer.application.console import ConsoleCoordinator
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository


class FakeProviders:
    def status(self):
        return {
            'fixture': {
                'id': 'fixture',
                'name': 'Fixture connection',
                'enabled': True,
                'model_id': 'fixture-model',
            }
        }


class FakeServer:
    def __init__(self, service, database_path):
        self.service = service
        self.database_path = str(database_path)
        self.offline = False
        self.providers = FakeProviders()
        self.console = ConsoleCoordinator(service, None, None, None)


class ChatSessionSelectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='chat-session-selection-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.database = self.root / 'chat.sqlite3'
        self.service = NovelService(SQLiteRepository(self.database))
        self.project_id = self.service.create(title='Selection fixture')['document']['project']['id']
        self.other_project_id = self.service.create(title='Other fixture')['document']['project']['id']
        self.server = FakeServer(self.service, self.database)
        self.agent = ChatAgent(self.server)
        self.addCleanup(self.agent.close)

        # ChatAgent.start still creates its worker thread, but the worker is never
        # started automatically during these tests. The context test invokes it
        # synchronously with _request replaced by a deterministic local stub.
        class AgentThread(threading.Thread):
            pass

        thread_patch = patch.object(AgentThread, 'start', autospec=True)
        self.thread_start = thread_patch.start()
        self.addCleanup(thread_patch.stop)

        class ThreadingProxy:
            Thread = AgentThread
            RLock = threading.RLock
            Event = threading.Event

            def __getattr__(self, name):
                return getattr(threading, name)

        threading_patch = patch(
            'novel_writer.application.chat_agent.threading',
            new=ThreadingProxy(),
        )
        threading_patch.start()
        self.addCleanup(threading_patch.stop)

    def session(self, project_id=None, title='Fixture session'):
        return self.server.console.create(
            project_id or self.project_id,
            {'operation_id': str(uuid4()), 'title': title},
        )

    def message(self, project_id, session_id, role, text):
        return self.server.console.append_message(
            project_id,
            {
                'operation_id': str(uuid4()),
                'session_id': session_id,
                'role': role,
                'text': text,
            },
        )

    def revision(self, project_id=None):
        return self.service.get(project_id or self.project_id)['revision']

    def test_invalid_explicit_sessions_have_no_persisted_side_effects(self):
        other_project_session = self.session(self.other_project_id, 'Other project')
        archived_session = self.session(self.project_id, 'Archived')
        self.server.console.archive(
            self.project_id,
            {'session_id': archived_session['id'], 'archived': True},
        )
        before_project = self.service.get(self.project_id)
        before_other_project = self.service.get(self.other_project_id)
        attachments = __import__(
            'novel_writer.application.chat_attachments', fromlist=['ChatAttachments']
        ).ChatAttachments(self.database)

        invalid_ids = (
            'not-a-uuid',
            str(uuid4()),
            other_project_session['id'],
            archived_session['id'],
        )
        for session_id in invalid_ids:
            with self.subTest(session_id=session_id):
                attachment = attachments.save('fixture.txt', b'local fixture text')
                request = {
                    'operation_id': str(uuid4()),
                    'project_id': self.project_id,
                    'text': 'A rejected request',
                    'expected_revision': before_project['revision'],
                    'attachment_ids': [attachment['id']],
                    'session_id': session_id,
                }
                with self.assertRaises(ValueError):
                    self.agent.start(request)

                self.assertEqual(self.agent.data['jobs'], [])
                self.assertEqual(self.service.get(self.project_id), before_project)
                self.assertEqual(self.service.get(self.other_project_id), before_other_project)
                self.assertIsNone(attachments.get(attachment['id'])['project_id'])
                self.thread_start.assert_not_called()

    def test_explicit_session_without_project_is_rejected_before_creating_book(self):
        selected = self.session(self.project_id, 'Explicit selection')
        project_ids_before = [item['id'] for item in self.service.list_projects()]
        request = {
            'operation_id': str(uuid4()),
            'text': 'Must not create a book',
            'session_id': selected['id'],
        }

        with self.assertRaises(ValueError):
            self.agent.start(request)

        self.assertEqual([item['id'] for item in self.service.list_projects()], project_ids_before)
        self.assertEqual(self.agent.data['jobs'], [])
        self.thread_start.assert_not_called()

    def test_explicit_selection_is_idempotent_and_keeps_history_isolated(self):
        selected = self.session(self.project_id, 'Selected, not the default title')
        other = self.session(self.project_id, 'Another session')
        self.message(self.project_id, selected['id'], 'author', 'Selected session history')
        self.message(self.project_id, selected['id'], 'assistant', 'Selected session reply')
        self.message(self.project_id, other['id'], 'author', 'Other session history')
        self.message(self.project_id, other['id'], 'assistant', 'Other session reply')
        other_messages_before = [
            item for item in self.service.get(self.project_id)['console_messages']
            if item['session_id'] == other['id']
        ]
        request = {
            'operation_id': str(uuid4()),
            'project_id': self.project_id,
            'text': 'A request for the selected session',
            'expected_revision': self.revision(),
            'session_id': selected['id'],
        }

        job = self.agent.start(request)
        self.assertEqual(job['session_id'], selected['id'])
        message_count = len(self.service.get(self.project_id)['console_messages'])

        repeated = self.agent.start(dict(request))
        self.assertEqual(repeated, job)
        self.assertEqual(len(self.service.get(self.project_id)['console_messages']), message_count)
        self.assertEqual(self.thread_start.call_count, 1)

        conflicting_request = dict(request, session_id=other['id'])
        with self.assertRaises(ValueError):
            self.agent.start(conflicting_request)
        self.assertEqual(len(self.service.get(self.project_id)['console_messages']), message_count)

        captured_requests = []

        def fake_request(*args, **kwargs):
            prepared, _ = self.agent._prepare_request(args[0], args[1], 'planner', None)
            captured_requests.append((args[1], prepared))
            return json.dumps({'reply': 'Fixture complete', 'actions': [], 'done': True})

        with patch.object(self.agent, '_request', side_effect=fake_request) as request_stub:
            self.agent._run(job['id'])
            request_stub.assert_called_once()

        sent_messages, prepared = captured_requests[0]
        conversation = [
            (item['role'], item['content'])
            for item in sent_messages
            if item.get('role') in ('user', 'assistant')
        ]
        envelope = json.loads(next(m['content'] for m in prepared if m['role'] == 'user' and 'reference_dialogue' in m['content']))
        dialogue = envelope['reference_dialogue']
        self.assertIn(dict(role='author', text='Selected session history'), dialogue)
        self.assertIn(dict(role='assistant', text='Selected session reply'), dialogue)
        self.assertNotIn(dict(role='author', text='Other session history'), dialogue)
        self.assertNotIn(dict(role='assistant', text='Other session reply'), dialogue)
        self.assertEqual(envelope['latest_original_author_request'], 'A request for the selected session')
        self.assertNotIn(('user', 'Other session history'), conversation)
        self.assertNotIn(('assistant', 'Other session reply'), conversation)

        persisted = NovelService(SQLiteRepository(self.database)).get(self.project_id)
        selected_authors = [
            item['text'] for item in persisted['console_messages']
            if item['session_id'] == selected['id'] and item['role'] == 'author'
        ]
        self.assertEqual(selected_authors, [
            'Selected session history',
            'A request for the selected session',
        ])
        other_messages_after = [
            item for item in persisted['console_messages']
            if item['session_id'] == other['id']
        ]
        self.assertEqual(other_messages_after, other_messages_before)
        self.assertEqual(self.agent.status(job['id'])['status'], 'completed')

    def test_omitting_session_id_keeps_legacy_default_selection(self):
        first = self.session(self.project_id, '自动创作对话')
        last = self.session(self.project_id, '自动创作对话')
        request = {
            'operation_id': str(uuid4()),
            'project_id': self.project_id,
            'text': 'Legacy request without explicit selection',
            'expected_revision': self.revision(),
        }

        job = self.agent.start(request)

        self.assertEqual(job['session_id'], last['id'])
        self.assertNotEqual(job['session_id'], first['id'])
        self.assertEqual(self.thread_start.call_count, 1)


if __name__ == '__main__':
    unittest.main()
