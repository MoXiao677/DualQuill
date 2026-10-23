"""Saved-outline creative workflow against a local HTTP supplier."""
import json
import unittest
from http.server import BaseHTTPRequestHandler
from uuid import uuid4
import test_s6b_workflows as legacy
from test_s6b_workflows import node, TASK


class CreativeWorkflowTests(unittest.TestCase):
    setUp = legacy.WorkflowTests.setUp
    view = legacy.WorkflowTests.view
    start = legacy.WorkflowTests.start
    step = legacy.WorkflowTests.step
    confirm = legacy.WorkflowTests.confirm

    def create_chain(self, count=2):
        self.f.save('save_chapter', chapter_id=self.f.cid, content='')
        self.f.save('save_chapter_outline', chapter_id=self.f.cid, core_idea='守塔人捡信', objective='找到寄信者',
                    scenes=[dict(order=1, summary='守塔人在潮水中找到信', character_ids=[], location='灯塔', story_time='第1天')])
        owner = self
        self.wire = []; self.bad = False; self.bad_audit = False
        class Supplier(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.wire.append(body)
                if '对checks逐项审阅' in body['messages'][0]['content']:
                    text = '{}' if owner.bad_audit else json.dumps(dict(overview='待作者核实', findings=[]))
                else:
                    text = '' if owner.bad else '守塔人捡起信。候选' + str(len(owner.wire))
                data = json.dumps(dict(id='creative-fixture', model='fixture', choices=[dict(message=dict(role='assistant', content=text), finish_reason='stop')])).encode()
                self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
        self.f.remote.RequestHandlerClass = Supplier
        nodes = [node('outline', 'outline_source'),
                 node('drafts', 'generate_candidates', ['outline'], 'outline', 'writer', dict(**TASK, count=count)),
                 node('audits', 'audit', ['drafts'], 'drafts', 'auditor', TASK),
                 node('author', 'await_author', ['audits'], 'audits', params=dict(action='body')),
                 node('adopt', 'adopt', ['author'], 'author', params=dict(action='body'))]
        spec = dict(workflow_format=1, interface_version=1, name='保存章纲初稿链', nodes=nodes,
                    permissions=['read_saved_source', 'prepare_model_request', 'human_approval', 'apply_approved_change'])
        version = self.engine.import_template(self.pid, dict(operation_id=str(uuid4()), template_id=None, template=spec, expected_revision=self.service.get(self.pid)['revision']))
        writer = dict(role='writer', adapter_id='chat-completions-http-v1', connection_id='gg', model_id='author-selected-model', temperature=.3, max_tokens=512, budget_limit=1., allow_unknown_cost=True, prompt_version='rewrite-1')
        return self.engine.create(self.pid, dict(operation_id=str(uuid4()), template_version_id=version['version_id'], chapter_id=self.f.cid,
                    inputs=dict(instruction='依据章纲创作，检查人物与时间线及规则冲突', query='', plan_text=''),
                    roles=[writer, dict(writer, role='auditor', prompt_version='review-json-1')],
                    limits=dict(max_external_calls=10, max_reserved_output_tokens=5120, max_node_attempts=64, max_retries=1, max_iterations=3, concurrency=1),
                    execution_mode='step', network_mode='confirm_each', expected_revision=self.service.get(self.pid)['revision']))

    def advance(self, run):
        for _ in range(35):
            view = self.step(run)
            if view['status'] == 'failed': return view
            pending = next((a for a in view['attempts'] if a['status'] == 'waiting_request'), None)
            if pending:
                self.confirm(run, pending); self.f.engine.wait_idle(5)
            if any(a['status'] == 'waiting_human' for a in view['attempts']): return view
        self.fail('workflow did not stop')

    def test_saved_outline_candidates_audit_author_choice_and_version_history(self):
        run = self.create_chain(); self.start(run); view = self.advance(run)
        human = next(a for a in view['attempts'] if a['status'] == 'waiting_human')
        self.assertEqual(len(human['candidates']), 2)
        self.assertEqual(len(self.wire), 4)
        self.assertEqual(self.service.get(self.pid)['document']['chapters'][0]['content'], '')
        chosen = human['candidates'][1]['candidate_id']
        view = self.engine.select_candidate(self.pid, run['run_id'], human['id'], dict(candidate_id=chosen, expected_revision=view['revision']))
        human = next(a for a in view['attempts'] if a['id'] == human['id'])
        self.confirm(run, human); self.step(run); self.step(run)
        state = self.service.get(self.pid)
        self.assertEqual(state['document']['chapters'][0]['content'], human['review']['after'])
        self.assertTrue(state['document']['chapters'][0]['content'].endswith('2'))
        self.assertEqual(state['adoption_receipts'][0]['candidate_id'], chosen)
        self.assertTrue(any(v['entity_type'] == 'chapter' and v['snapshot']['content'] == human['review']['after'] for v in state['document']['versions']))
        self.assertEqual(self.view(run)['status'], 'completed')

    def test_restart_keeps_author_wait_and_completed_requests_are_not_repeated(self):
        run = self.create_chain(); self.start(run); self.advance(run)
        original = self.view(run); old = self.engine
        self.engine = self.api.WorkflowCoordinator(self.service, self.f.engine); self.addCleanup(self.engine.close)
        self.assertTrue(self.view(run)['requires_recovery'])
        self.engine.control(self.pid, run['run_id'], 'recover'); self.step(run)
        current = self.view(run)
        self.assertEqual([a['id'] for a in original['attempts']], [a['id'] for a in current['attempts']])
        self.assertTrue(any(a['status'] == 'waiting_human' for a in current['attempts']))
        self.assertEqual(len(self.wire), 4)
        self.assertFalse(self.service.get(self.pid)['adoption_receipts'])
        old.close()

    def test_candidate_generation_failure_is_persisted(self):
        run = self.create_chain(); self.bad = True; self.start(run); view = self.advance(run)
        self.assertEqual(view['status'], 'failed')
        self.assertTrue(any(a['status'] == 'failed' and a['error_code'] for a in view['attempts']))
        self.assertFalse(self.service.get(self.pid)['adoption_receipts'])

    def test_author_rejection_never_writes_body(self):
        run = self.create_chain(); self.start(run); view = self.advance(run)
        human = next(a for a in view['attempts'] if a['status'] == 'waiting_human')
        self.confirm(run, human, decision='rejected'); self.step(run); self.step(run)
        state = self.service.get(self.pid)
        self.assertEqual(state['document']['chapters'][0]['content'], '')
        self.assertFalse(state['adoption_receipts'])

    def test_invalid_audit_fails_without_author_gate(self):
        run = self.create_chain(); self.bad_audit = True; self.start(run); view = self.advance(run)
        self.assertEqual(view['status'], 'failed')
        self.assertFalse(any(a['status'] == 'waiting_human' for a in view['attempts']))
        self.assertFalse(self.service.get(self.pid)['adoption_receipts'])


    def test_audit_wire_contains_frozen_character_and_rule_context(self):
        self.f.save('add_character', name='守塔人', personality='谨慎', notes='不会游泳')
        run = self.create_chain(); self.start(run); self.advance(run)
        audits = [json.loads(w['messages'][1]['content']) for w in self.wire if '对checks逐项审阅' in w['messages'][0]['content']]
        self.assertEqual(len(audits), 2)
        for wire in audits:
            self.assertIn('character_consistency', wire['checks'])
            self.assertIn('rule_conflict', wire['checks'])
            candidate = next(s for s in wire['sources'] if s['kind'] == 'candidate')
            self.assertIn('不会游泳', candidate['context'])

    def test_backup_restore_and_copy_preserve_waiting_selection(self):
        from novel_writer.application.backups import create_backup, restore_backup
        from novel_writer.application.migrations import migrate
        from novel_writer.storage.sqlite_repository import SQLiteRepository
        from novel_writer.application.service import NovelService
        from novel_writer.application.skill_import import SkillLibrary
        run = self.create_chain(); self.start(run); view = self.advance(run)
        human = next(a for a in view['attempts'] if a['status'] == 'waiting_human')
        self.engine.select_candidate(self.pid, run['run_id'], human['id'], dict(candidate_id=human['candidates'][1]['candidate_id'], expected_revision=view['revision']))
        from novel_writer.storage.backup_validation import validate_database
        validate_database(self.f.db)
        package = self.f.root/'creative.nwbak'; create_backup(self.f.db, package)
        restored = restore_backup(package, self.f.root/'restored')
        self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid), self.service.get(self.pid))
        copied = self.f.root/'copied.sqlite3'; SQLiteRepository(copied); SkillLibrary(copied)
        result = migrate(package, copied, operation_id=str(uuid4()))
        pid = result['projects'][0]['new_id']
        service = NovelService(SQLiteRepository(copied))
        state = service.get(pid)
        self.assertFalse(state['adoption_receipts'])
        self.assertTrue(any(e['status'] == 'waiting_human' and e['snapshot'] for e in state['workflow_node_events']))

    def test_changed_outline_blocks_pending_request_but_preserves_history(self):
        run = self.create_chain(); self.start(run); self.step(run); self.step(run)
        pending = next(a for a in self.view(run)['attempts'] if a['status'] == 'waiting_request')
        self.f.save('save_chapter_outline', chapter_id=self.f.cid, core_idea='作者修改后的章纲')
        with self.assertRaisesRegex(ValueError, '章纲|来源'):
            self.confirm(run, pending)
        self.assertFalse(self.wire)
        self.assertFalse(self.service.get(self.pid)['adoption_receipts'])


    def test_mid_generation_restart_resumes_without_repeating_finished_candidate(self):
        run = self.create_chain(); self.start(run); self.step(run); self.step(run)
        first = next(a for a in self.view(run)['attempts'] if a['status'] == 'waiting_request')
        self.confirm(run, first); self.f.engine.wait_idle(5); self.step(run)
        old = self.engine
        self.engine = self.api.WorkflowCoordinator(self.service, self.f.engine); self.addCleanup(self.engine.close)
        self.engine.control(self.pid, run['run_id'], 'recover'); self.advance(run)
        current = self.view(run)
        self.assertEqual(next(a for a in current['attempts'] if a['id'] == first['id'])['status'], 'succeeded')
        self.assertEqual(len(self.wire), 4)
        self.assertEqual(sum(a['node_id'] == first['node_id'] for a in current['attempts']), 1)
        old.close()

    def test_copy_transform_remaps_outline_selection_and_revalidates(self):
        from novel_writer.application.migrations import _transform
        from novel_writer.storage.sqlite_repository import validate_workspace
        from uuid import uuid5, NAMESPACE_URL
        run = self.create_chain(); self.start(run); view = self.advance(run)
        human = next(a for a in view['attempts'] if a['status'] == 'waiting_human')
        self.engine.select_candidate(self.pid, run['run_id'], human['id'], dict(candidate_id=human['candidates'][1]['candidate_id'], expected_revision=view['revision']))
        state = self.service.get(self.pid)
        copied = _transform(state, lambda project, kind, identifier: str(uuid5(NAMESPACE_URL, project+'/'+kind+'/'+identifier)))
        validate_workspace(copied)
        self.assertNotEqual(copied['document']['project']['id'], self.pid)
        self.assertFalse(copied['adoption_receipts'])

    def test_accepting_without_explicit_choice_and_foreign_choice_are_rejected(self):
        run = self.create_chain(); self.start(run); view = self.advance(run)
        human = next(a for a in view['attempts'] if a['status'] == 'waiting_human')
        with self.assertRaisesRegex(ValueError, '先明确选择'):
            self.confirm(run, human)
        with self.assertRaisesRegex(ValueError, '不属于'):
            self.engine.select_candidate(self.pid, run['run_id'], human['id'], dict(candidate_id=str(uuid4()), expected_revision=view['revision']))
        self.assertFalse(self.service.get(self.pid)['adoption_receipts'])
