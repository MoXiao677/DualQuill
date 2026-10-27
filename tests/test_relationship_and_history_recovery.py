import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from novel_writer.application.chat_agent import ChatAgent
from novel_writer.storage import json_codec, sqlite_repository


class RelationshipRecoveryTests(unittest.TestCase):
    def test_invalid_relationship_retries_before_any_business_write(self):
        agent = object.__new__(ChatAgent)
        agent.lock = threading.RLock()
        agent._save = lambda: None
        chapter = dict(id='chapter-fixture', number=1, content='Fictional chapter')
        identifier = str(uuid4())
        state = dict(document=dict(chapters=[chapter], characters=[dict(id=identifier)]), worldbuilding='')
        agent._review_guard = lambda job: state
        agent._matching_review_receipt = lambda *args: dict(status='passed', passed=True)
        agent._progress = lambda *args: None
        agent.events = {'fixture': SimpleNamespace(wait=lambda delay: False)}
        job = dict(id='fixture', reviews=[], stage='')
        writes, requests = [], []

        def request(*args, **kwargs):
            self.assertFalse(writes)
            requests.append(kwargs['purpose'])
            self.assertLessEqual(len(requests), 2)
            characters = [dict(relationships=[dict(target='Unresolved name', relation='friend')])] if len(requests) == 1 else []
            return json.dumps(dict(summary='Fictional summary', characters=characters))

        agent._request = request
        agent._action = lambda job, tool, args: writes.append(tool)
        agent._maintain_reviewed_chapter(job, chapter)
        self.assertEqual(requests, ['maintenance', 'maintenance'])
        self.assertEqual(writes, ['save_memory'])

    def test_canonical_relationships_and_invalid_targets(self):
        identifier = str(uuid4())
        state = dict(document=dict(characters=[dict(id=identifier)]))
        for value in ({}, dict(relationships=[]), dict(relationships=[dict(target_character_id=identifier, relation='ally', description='Existing fact')])):
            ChatAgent._validate_character_relationships(state, value)
        for row in (dict(target=identifier, relation='ally'), dict(target_character_id=str(uuid4()), relation='ally'), dict(target_character_id=identifier, relation=''), dict(target_character_id=identifier, relation='ally', description=1)):
            with self.subTest(row=row), self.assertRaises(ValueError):
                ChatAgent._validate_character_relationships(state, dict(relationships=[row]))


class HistoryIsolationTests(unittest.TestCase):
    def test_slow_project_does_not_block_another_project(self):
        repository = object.__new__(sqlite_repository.SQLiteRepository)
        repository._history_cache = {}
        repository._history_locks = {}
        repository._history_lock = threading.RLock()
        entered, release, completed = threading.Event(), threading.Event(), threading.Event()

        def read(connection, project, current, cached, **kwargs):
            if project == 'slow':
                entered.set()
                release.wait(5)
            return {}, None, {}

        def fast():
            repository._history(None, 'fast', None)
            completed.set()

        with patch.object(sqlite_repository, '_read_project_history', side_effect=read):
            slow = threading.Thread(target=lambda: repository._history(None, 'slow', None))
            slow.start()
            self.assertTrue(entered.wait(1))
            other = threading.Thread(target=fast)
            other.start()
            try:
                self.assertTrue(completed.wait(1), 'Unrelated project blocked by history validation')
            finally:
                release.set()
                slow.join()
                other.join()

    def test_escaped_prose_does_not_search_each_escape_in_python(self):
        text = json.dumps(dict(body='Fictional "quoted" \\path ' * 10000))
        original = json_codec._STRING_SPECIAL
        with patch.object(json_codec, '_STRING_SPECIAL', wraps=original) as scanner:
            self.assertEqual(json_codec.strict_json_loads(text), json.loads(text))
            self.assertLess(scanner.search.call_count, 100)
