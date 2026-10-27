import hashlib
import json
import tempfile
import threading
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from novel_writer.application.chat_agent import ChatAgent
from novel_writer.application.console import ConsoleCoordinator
from novel_writer.application.service import NovelService
from novel_writer.application.skill_import import SkillLibrary
from novel_writer.storage.sqlite_repository import SQLiteRepository


class FakeProviders:
    def __init__(self):
        self.protocol = 'openai-chat'
        self.key_reads = 0

    def status(self):
        return {key: dict(id=key, name=key, enabled=True, model_id='fixture-model',
                          key_configured=True) for key in ('writer', 'reviewer')}

    def generation_connection(self, *args, **kwargs):
        self.key_reads += 1
        return dict(protocol=self.protocol, api_key='fixture-only-key',
                    base_url='https://fixture.invalid/v1', allow_local=False)


class FakeHTTP:
    def __init__(self, captured):
        self.captured = captured

    def request(self, method, path, body, headers):
        self.captured.append(json.loads(body))

    def getresponse(self):
        data = dict(status='completed', output=[dict(type='message', content=[dict(type='output_text', text='fixture reply')])],
                    choices=[dict(finish_reason='stop', message=dict(content='fixture reply'))],
                    stop_reason='end_turn', content=[dict(type='text', text='fixture reply')],
                    candidates=[dict(finishReason='STOP', content=dict(parts=[dict(text='fixture reply')]))])
        payload = json.dumps(data).encode()
        return SimpleNamespace(status=200, length=len(payload), read=lambda limit: payload[:limit])

    def close(self):
        pass


class ChatSkillContextTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='chat-skills-')
        self.addCleanup(temporary.cleanup)
        self.database = Path(temporary.name) / 'fixture.sqlite3'
        self.service = NovelService(SQLiteRepository(self.database))
        self.project = self.service.create(title='Skill fixture')['document']['project']['id']
        self.providers = FakeProviders()
        self.server = SimpleNamespace(service=self.service, database_path=str(self.database),
                                      offline=False, providers=self.providers,
                                      console=ConsoleCoordinator(self.service, None, None, None))
        self.library = SkillLibrary(self.database)
        self.skill = self.import_skill('PRIMARY_SENTINEL', 'REFERENCE_SENTINEL')
        self.agent = ChatAgent(self.server)
        self.addCleanup(self.agent.close)
        proxy = SimpleNamespace(RLock=threading.RLock, Event=threading.Event,
                                Thread=lambda **kwargs: SimpleNamespace(start=lambda: None, join=lambda timeout=None: None))
        patched = patch('novel_writer.application.chat_agent.threading', proxy)
        patched.start()
        self.addCleanup(patched.stop)
        self.captured = []
        transport = patch('novel_writer.application.chat_agent.connection_for',
                          side_effect=lambda *args, **kwargs: FakeHTTP(self.captured))
        self.transport = transport.start()
        self.addCleanup(transport.stop)

    def import_skill(self, primary, reference):
        return self.library.import_files([dict(path='guide/SKILL.md', content=primary),
                                          dict(path='guide/references/style.md', content=reference)])

    def start(self):
        result = self.agent.start(dict(operation_id=str(uuid4()), project_id=self.project,
                                       expected_revision=self.service.get(self.project)['revision'],
                                       text='Write according to my current instructions'))
        return self.agent._job(result['id'])

    def send(self, job, **kwargs):
        messages = [dict(role='system', content='Trusted fixture task'),
                    dict(role='user', content='Explicit author instruction')]
        original = deepcopy(messages)
        self.assertEqual(self.agent._request(job, messages, **kwargs), 'fixture reply')
        self.assertEqual(messages, original)
        return json.dumps(self.captured[-1], ensure_ascii=False)

    def test_all_four_wire_shapes_include_complete_files(self):
        job = self.start()
        for protocol, mode in [('openai-chat', 'responses'), ('openai-chat', 'chat'),
                               ('anthropic-messages', 'auto'), ('gemini-content', 'auto')]:
            with self.subTest(protocol=protocol, mode=mode):
                self.providers.protocol = protocol
                job['wire_mode'] = mode
                body = self.send(job)
                self.assertIn('PRIMARY_SENTINEL', body)
                self.assertIn('REFERENCE_SENTINEL', body)
                self.assertIn('guide/references/style.md', body)
        self.assertEqual(len(job['skill_usage']), 4)
        for ordinal, usage in enumerate(job['skill_usage'], 1):
            self.assertEqual(usage['call_ordinal'], ordinal)
            self.assertEqual(usage['connection_id'], 'writer')
            self.assertEqual(usage['model_id'], 'fixture-model')
            self.assertEqual(usage['status'], 'response_received')

    def test_selection_disable_validation_and_legacy_configuration(self):
        settings = self.agent.settings()
        self.assertEqual(settings['skill_ids'], [self.skill['id']])
        self.assertEqual(settings['skill_mode'], 'all-imported')
        self.assertEqual(settings['available_skills'][0]['id'], self.skill['id'])
        for invalid in ([str(uuid4())], 'wrong', [None], [self.skill['id'], self.skill['id']]):
            before = deepcopy(self.agent.data)
            with self.assertRaises(ValueError):
                self.agent.configure(dict(skill_ids=invalid))
            self.assertEqual(self.agent.data, before)
        self.agent.configure(dict(skill_ids=[self.skill['id']]))
        self.agent.configure(dict(connection_id='writer', wire_mode='chat'))
        self.agent.configure(dict(reviewer_connection_id='reviewer'))
        self.assertEqual(self.agent.settings()['skill_ids'], [self.skill['id']])
        self.agent.configure(dict(skill_ids=[]))
        job = self.start()
        body = self.send(job)
        self.assertNotIn('PRIMARY_SENTINEL', body)
        self.assertNotIn('REFERENCE_SENTINEL', body)
        self.assertEqual(job['skills_manifest'], [])

    def test_frozen_snapshot_hashes_public_redaction_and_reviewer_usage(self):
        job = self.start()
        self.import_skill('LATER_PRIMARY', 'LATER_REFERENCE')
        self.agent.configure(dict(skill_ids=[]))
        body = self.send(job, connection_override=self.providers.status()['reviewer'])
        self.assertIn('PRIMARY_SENTINEL', body)
        self.assertIn('REFERENCE_SENTINEL', body)
        self.assertNotIn('LATER_PRIMARY', body)
        public = self.agent._public(job)
        serialized = json.dumps(public)
        self.assertNotIn('PRIMARY_SENTINEL', serialized)
        self.assertNotIn('REFERENCE_SENTINEL', serialized)
        self.assertNotIn('fixture-only-key', serialized)
        manifest = public['skills_manifest'][0]
        self.assertEqual(manifest['id'], self.skill['id'])
        self.assertEqual(len(manifest['sha256']), 64)
        for saved, trace in zip(self.skill['files'], manifest['files']):
            self.assertEqual(trace, dict(path=saved['path'], chars=len(saved['content']),
                                        sha256=hashlib.sha256(saved['content'].encode()).hexdigest()))
        self.assertEqual(public['skill_usage'][0]['connection_id'], 'reviewer')

    def test_oversize_start_has_no_novel_mutation_or_key_access(self):
        self.import_skill('x' * 360001, 'oversize reference')
        before = self.service.get(self.project)
        with self.assertRaisesRegex(ValueError, '360000'):
            self.start()
        self.assertEqual(self.service.get(self.project), before)
        self.assertEqual(self.agent.data['jobs'], [])
        self.assertEqual(self.providers.key_reads, 0)
        self.transport.assert_not_called()

    def test_combined_request_overflow_rejects_before_key_access(self):
        job = self.start()
        with self.assertRaisesRegex(ValueError, '360000'):
            self.agent._request(job, [dict(role='user', content='x' * 359990)])
        self.assertEqual(self.providers.key_reads, 0)
        self.transport.assert_not_called()

    def test_legacy_job_lazy_freeze_only_on_explicit_request(self):
        job = self.start()
        job.pop('skills_snapshot', None)
        job.pop('skills_manifest', None)
        self.agent._public(job)
        self.assertNotIn('skills_snapshot', job)
        self.assertEqual(self.providers.key_reads, 0)
        self.assertIn('REFERENCE_SENTINEL', self.send(job))
        self.assertIn('skills_snapshot', job)


if __name__ == '__main__':
    unittest.main()
