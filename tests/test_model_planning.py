"""Fiction-only body-driven model planning; actual random-port loopback requests."""
from copy import deepcopy
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
import unittest
from uuid import uuid4

from test_body_planning import BodyPlanningTests
from test_book_ai import supplier
from novel_writer.application.model_planning import ModelPlanningCoordinator
from novel_writer.application.provider_connections import ProviderConnections
from novel_writer.application.tasks import TaskCoordinator
from novel_writer.application.task_protocol import AdapterRegistry
from test_sse_protocols import event, chat


@contextmanager
def model_wire(output, protocol='openai-chat', *, stream=False, hold=False, truncated=False):
    calls=[]; ready=threading.Event(); release=threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            raw=self.rfile.read(int(self.headers['Content-Length']))
            calls.append(dict(path=self.path, raw=raw.decode('utf-8'), body=json.loads(raw), headers=dict(self.headers)))
            if stream:
                if protocol=='openai-chat':
                    head=event(chat(output));tail=event(chat('', 'stop'))+b'data: [DONE]\r\n\r\n'
                elif protocol=='anthropic-messages':
                    head=event(dict(type='message_start',message=dict(id='fiction',role='assistant',content=[])),'message_start')+event(dict(type='content_block_start',index=0,content_block=dict(type='text',text='')),'content_block_start')+event(dict(type='content_block_delta',index=0,delta=dict(type='text_delta',text=output)),'content_block_delta')
                    tail=event(dict(type='content_block_stop',index=0),'content_block_stop')+event(dict(type='message_delta',delta=dict(stop_reason='end_turn')),'message_delta')+event(dict(type='message_stop'),'message_stop')
                else:
                    head=event(dict(candidates=[dict(index=0,content=dict(role='model',parts=[dict(text=output)]))]));tail=event(dict(candidates=[dict(index=0,finishReason='STOP')]))
                if truncated:tail=b''
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(head)+len(tail)));self.end_headers()
                try:
                    self.wfile.write(head);self.wfile.flush();ready.set()
                    if hold:release.wait(5)
                    self.wfile.write(tail);self.wfile.flush()
                except OSError:pass
            else:
                ready.set()
                if hold:release.wait(5)
                if protocol=='anthropic-messages':payload=dict(id='fiction',role='assistant',content=[dict(type='text',text=output)],stop_reason='end_turn',usage=dict(input_tokens=20,output_tokens=9))
                elif protocol=='gemini-content':payload=dict(candidates=[dict(content=dict(role='model',parts=[dict(text=output)]),finishReason='STOP')],usageMetadata=dict(promptTokenCount=20,candidatesTokenCount=9,totalTokenCount=29))
                else:payload=dict(choices=[dict(message=dict(role='assistant',content=output),finish_reason='stop')],usage=dict(prompt_tokens=20,completion_tokens=9,total_tokens=29))
                data=json.dumps(payload,ensure_ascii=False).encode('utf-8')
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers()
                try:self.wfile.write(data)
                except OSError:pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
    worker=threading.Thread(target=server.serve_forever,kwargs=dict(poll_interval=.01),daemon=True);worker.start()
    try:yield dict(url='http://127.0.0.1:'+str(server.server_port)+'/v1',calls=calls,ready=ready,release=release)
    finally:release.set();server.shutdown();server.server_close();worker.join(2)


class ModelPlanningTests(unittest.TestCase):
    revision = BodyPlanningTests.revision
    save = BodyPlanningTests.save
    request = BodyPlanningTests.request
    event = BodyPlanningTests.event
    act = BodyPlanningTests.act
    preview = BodyPlanningTests.preview
    decision = BodyPlanningTests.decision
    engine = BodyPlanningTests.engine

    def setUp(self):
        BodyPlanningTests.setUp(self)
        self.save(content='😀林默交出旧钥匙。星灯熄灭。')
        self.eid = self.event(planned_chapter_id=self.c2)
        self.shared = TaskCoordinator(self.service, AdapterRegistry()); self.addCleanup(self.shared.close)
        self.providers = ProviderConnections(self.root/'fiction.dpapi')
        self.ai = ModelPlanningCoordinator(self.shared, self.providers, enabled=True)

    def payload(self):
        quote = '林默交出旧钥匙。'
        return dict(suggestions=[dict(reason='正文显示交出钥匙，待作者核实', start=1, end=1+len(quote), quote=quote,
            actions=[dict(action='occur_event', values=dict(event_id=self.eid, occurrence_chapter_id=self.c1, body_reference=quote))])])

    def connection(self, wire, protocol='openai-chat', stream=False):
        c = self.providers.save_custom(id=str(uuid4()), name='正文规划虚构供应商', base_url=wire['url'],
            protocol=protocol, model_id='fiction-selected', api_key='fiction-body-key', allow_local=True)
        if stream: self.providers.manage(id=c['id'], action='stream_profile', confirmed=True, stream_mode='sse')
        return c

    def prepare(self, connection, **changes):
        options = dict(chapter_id=self.c1, character_ids=[self.character], instruction='核对虚构正文', context_budget_chars=100000)
        source = self.ai.preview(self.pid, options)
        request = self.request(source_options=options, source_sha256=source['source_sha256'], model_options=dict(
            adapter_id='configured-http-v2', connection_id=connection['id'], model_id='fiction-selected', temperature=.3,
            max_tokens=512, budget_limit=1.0, allow_unknown_cost=True, prompt_version='rewrite-1'),
            budget=dict(max_external_calls=10, max_reserved_output_tokens=81920), max_output_chars=20000, timeout_ms=2000)
        request.update(changes)
        return self.ai.prepare(self.pid, request)

    def start(self, prepared, **changes):
        task = prepared['task']
        confirmation = dict(confirm_external=True, request_sha256=task['binding']['request_sha256'],
            budget_sha256=task['budget_sha256'], expected_revision=prepared['revision'])
        confirmation.update(changes)
        return self.ai.start(self.pid, task['id'], confirmation)

    def run_task(self, prepared):
        self.start(prepared); self.shared.wait_idle(5)
        return self.ai.describe(self.pid, prepared['task']['id'])

    def transfer(self, view, index=0):
        c = view['candidates'][0]
        selection = dict(candidate_id=c['id'], candidate_sha256=c['data_sha256'], suggestion_index=index)
        preview = self.ai.preview_transfer(self.pid, selection)
        request = dict(operation_id=str(uuid4()), expected_revision=preview['revision'], **selection,
                       transfer_token=preview['transfer_token'], confirmed=True)
        link = self.ai.propose(self.pid, request)
        self.assertEqual(link, self.ai.propose(self.pid, request))
        return next(p for p in self.service.get(self.pid)['body_planning_proposals'] if p['id'] == link['proposal_id'])

    def test_real_three_json_protocols_candidate_transfer_and_separate_acceptance(self):
        for protocol in ('openai-chat', 'anthropic-messages', 'gemini-content'):
            with self.subTest(protocol=protocol), supplier(protocol, json.dumps(self.payload(), ensure_ascii=False)) as wire:
                connection = self.connection(wire, protocol)
                formal = deepcopy(self.service.get(self.pid)['document'])
                prepared = self.prepare(connection)
                self.assertEqual(wire['calls'], [])
                with self.assertRaises(ValueError): self.start(prepared, budget_sha256='0'*64)
                view = self.run_task(prepared)
                self.assertEqual(view['status'], 'succeeded', view)
                self.assertEqual(len(wire['calls']), 1)
                self.assertEqual(wire['calls'][0]['body'], json.loads(prepared['task']['binding']['request_body']))
                self.assertEqual(self.service.get(self.pid)['key_events'][0]['status'], 'planned')
                p = self.transfer(view)
                self.assertEqual(self.service.get(self.pid)['key_events'][0]['status'], 'planned')
                impact = self.preview(p)
                self.assertFalse(impact['quality_verified'])
                self.decision(p, preview_sha256=impact['preview_sha256'])
                self.assertEqual(self.service.get(self.pid)['key_events'][0]['status'], 'occurred')
                self.assertEqual(formal, self.service.get(self.pid)['document'])
                self.assertNotIn('fiction-body-key', json.dumps(view))
                self.act('reopen_event', event_id=self.eid)

    def test_three_sse_protocols_transient_preview_exact_wire_and_termination(self):
        for protocol in ('openai-chat','anthropic-messages','gemini-content'):
            output=json.dumps(self.payload(),ensure_ascii=False)
            with self.subTest(protocol=protocol),model_wire(output,protocol,stream=True,hold=True) as wire:
                prepared=self.prepare(self.connection(wire,protocol,stream=True));task=prepared['task']
                self.start(prepared);self.assertTrue(wire['ready'].wait(2))
                deadline=time.monotonic()+2;view={}
                while time.monotonic()<deadline:
                    view=self.ai.describe(self.pid,task['id'])
                    if view.get('stream_preview',{}).get('text')==output:break
                    time.sleep(.01)
                self.assertEqual(view['stream_preview'],dict(text=output,chars=len(output),temporary=True))
                self.assertEqual(view['candidates'],[])
                self.assertNotIn('stream_preview',json.dumps(self.service.get(self.pid)))
                self.assertEqual(wire['calls'][0]['raw'],task['binding']['request_body'])
                self.assertEqual(wire['calls'][0]['headers']['Accept'],'text/event-stream')
                expected='/v1/models/fiction-selected:streamGenerateContent?alt=sse' if protocol=='gemini-content' else '/v1/messages' if protocol=='anthropic-messages' else '/v1/chat/completions'
                self.assertEqual(wire['calls'][0]['path'],expected)
                wire['release'].set();self.shared.wait_idle(5);done=self.ai.describe(self.pid,task['id'])
                self.assertEqual(done['status'],'succeeded',done);self.assertNotIn('stream_preview',done)
                self.assertEqual(done['candidates'][0]['raw_text'],output)

    def test_invalid_json_citations_unknown_actions_and_tool_like_output_never_propose(self):
        invalid=['not JSON',json.dumps(dict(suggestions=[])),json.dumps(dict(tool_calls=[dict(name='save_chapter')]))]
        for change in [dict(start=True),dict(quote='伪造引文'),dict(actions=[dict(action='set_lock',values={})]),dict(actions=[dict(action='occur_event',values=dict(event_id=self.eid,occurrence_chapter_id=self.c2,body_reference='林默交出旧钥匙。'))])]:
            payload=self.payload();payload['suggestions'][0].update(change);invalid.append(json.dumps(payload,ensure_ascii=False))
        for output in invalid:
            with self.subTest(output=output),model_wire(output) as wire:
                formal=deepcopy(self.service.get(self.pid)['document']);view=self.run_task(self.prepare(self.connection(wire)))
                self.assertEqual(view['status'],'failed');self.assertEqual(view['candidates'],[])
                self.assertEqual(self.service.get(self.pid)['body_planning_proposals'],[])
                self.assertEqual(formal,self.service.get(self.pid)['document'])
                self.assertEqual(len(wire['calls']),1)

    def test_cancel_timeout_truncation_and_late_completion_no_candidates_or_replay(self):
        for mode in ('cancel','timeout','truncated'):
            with self.subTest(mode=mode),model_wire(json.dumps(self.payload(),ensure_ascii=False),stream=True,hold=mode!='truncated',truncated=mode=='truncated') as wire:
                prepared=self.prepare(self.connection(wire,stream=True),timeout_ms=200 if mode=='timeout' else 2000)
                self.start(prepared);self.assertTrue(wire['ready'].wait(2))
                if mode=='cancel':self.ai.cancel(self.pid,prepared['task']['id'],{})
                if mode=='timeout':time.sleep(.3)
                wire['release'].set();self.shared.wait_idle(5);view=self.ai.describe(self.pid,prepared['task']['id'])
                self.assertEqual(view['status'],'cancelled' if mode=='cancel' else 'failed',view)
                self.assertEqual(view['candidates'],[]);self.assertNotIn('stream_preview',view)
                with self.assertRaises(ValueError):self.start(prepared)
                self.assertEqual(len(wire['calls']),1)

    def test_source_configuration_revision_and_shared_slot_guards_before_send(self):
        with model_wire(json.dumps(self.payload(),ensure_ascii=False)) as wire:
            c=self.connection(wire);prepared=self.prepare(c)
            self.shared.slot.acquire()
            try:
                with self.assertRaisesRegex(ValueError,'busy'):self.start(prepared)
            finally:self.shared.slot.release()
            self.save(content='正文更新。')
            with self.assertRaises(ValueError):self.start(prepared,expected_revision=self.revision())
            prepared=self.prepare(c)
            self.providers.manage(id=c['id'],action='disable',confirmed=True)
            with self.assertRaises(ValueError):self.start(prepared)
            self.assertEqual(wire['calls'],[])

    def test_scoped_rule_change_before_accept_and_transfer_requires_fresh_nonce(self):
        from novel_writer.application.scoped_rules import RuleCoordinator
        with model_wire(json.dumps(self.payload(),ensure_ascii=False)) as wire:
            view=self.run_task(self.prepare(self.connection(wire)));c=view['candidates'][0]
            selection=dict(candidate_id=c['id'],candidate_sha256=c['data_sha256'],suggestion_index=0)
            preview=self.ai.preview_transfer(self.pid,selection)
            other=ModelPlanningCoordinator(TaskCoordinator(self.service,AdapterRegistry()),self.providers,enabled=True)
            self.addCleanup(other.parent.close)
            with self.assertRaises(ValueError):other.propose(self.pid,self.request(**selection,transfer_token=preview['transfer_token'],confirmed=True))
            self.service._model_planning=self.ai
            p=self.transfer(view);impact=self.preview(p)
            RuleCoordinator(self.service).save(self.pid,dict(operation_id=str(uuid4()),rule_id=None,scope='chapter',scope_id=self.c1,kind='guidance',text='新增虚构规则',enabled=True))
            before=self.service.get(self.pid)
            with self.assertRaises(ValueError):self.decision(p,preview_sha256=impact['preview_sha256'])
            self.assertEqual(before,self.service.get(self.pid))

    def test_budget_reservations_cancel_not_refunded_and_preparation_identity(self):
        budget=dict(max_external_calls=1,max_reserved_output_tokens=512)
        with model_wire(json.dumps(self.payload(),ensure_ascii=False),hold=True) as wire:
            c=self.connection(wire);prepared=self.prepare(c,budget=budget);self.start(prepared)
            self.assertTrue(wire['ready'].wait(2));self.ai.cancel(self.pid,prepared['task']['id'],{})
            wire['release'].set();self.shared.wait_idle(5)
            next_task=self.prepare(c,budget=budget)
            with self.assertRaisesRegex(ValueError,'budget_exceeded'):self.start(next_task)
            self.assertEqual(len(wire['calls']),1)

    def test_backup_restore_double_copy_preserve_raw_and_never_inherit_permissions(self):
        from novel_writer.application.backups import create_backup,restore_backup
        from novel_writer.application.migrations import migrate
        from novel_writer.application.skill_import import SkillLibrary
        from novel_writer.application.service import NovelService
        from novel_writer.storage.sqlite_repository import SQLiteRepository
        with model_wire(json.dumps(self.payload(),ensure_ascii=False)) as wire:
            view=self.run_task(self.prepare(self.connection(wire)));p=self.transfer(view)
            self.preview(p);original=self.service.get(self.pid);SkillLibrary(self.db)
            package=self.root/'model.nwbak';self.assertEqual(create_backup(self.db,package)['backup_format_version'],51)
            restored=restore_backup(package,self.root/'restored-model');service=NovelService(SQLiteRepository(restored['database_path']))
            self.assertEqual(original,service.get(self.pid))
            parent=TaskCoordinator(service,AdapterRegistry());self.addCleanup(parent.close)
            reopened=ModelPlanningCoordinator(parent,self.providers,enabled=True)
            with self.assertRaises(ValueError):reopened.start(self.pid,view['task']['id'],dict(confirm_external=True,request_sha256=view['task']['binding']['request_sha256'],budget_sha256=view['task']['budget_sha256'],expected_revision=self.revision()))
            from novel_writer.application.body_planning import BodyPlanning
            with self.assertRaises(ValueError):BodyPlanning(service).decide(self.pid,self.request(proposal_id=p['id'],decision='accepted',preview_sha256='0'*64))
            BodyPlanning(service).preview(self.pid,dict(proposal_id=p['id']))
            source=package
            for index in range(2):
                target=self.root/f'copy-model-{index}.sqlite3';SQLiteRepository(target);SkillLibrary(target)
                result=migrate(source,target,operation_id=str(uuid4()));clone=NovelService(SQLiteRepository(target)).get(result['projects'][0]['new_id'])
                t=clone['model_planning_tasks'][0]
                self.assertEqual(t['binding'],original['model_planning_tasks'][0]['binding'])
                self.assertEqual(t['original_source_json'],original['model_planning_tasks'][0]['original_source_json'])
                self.assertEqual(clone['model_planning_results'][0]['response'],original['model_planning_results'][0]['response'])
                self.assertEqual(clone['model_planning_candidates'][0]['raw_text'],original['model_planning_candidates'][0]['raw_text'])
                self.assertEqual(clone['model_planning_links'][0]['proposal_id'],clone['body_planning_proposals'][0]['id'])
                copied=NovelService(SQLiteRepository(target));shared=TaskCoordinator(copied,AdapterRegistry());self.addCleanup(shared.close)
                ai=ModelPlanningCoordinator(shared,self.providers,enabled=True)
                self.assertNotEqual(t['owner_id'],shared.owner_id)
                with self.assertRaises(ValueError):ai.start(clone['document']['project']['id'],t['id'],dict(confirm_external=True,
                    request_sha256=t['binding']['request_sha256'],budget_sha256=t['budget_sha256'],expected_revision=clone['revision']))
                source=self.root/f'copy-model-{index}.nwbak';create_backup(target,source)
            self.assertEqual(len(wire['calls']),1)

    def test_accepted_and_f1_histories_survive_copy_without_rewriting_wire_provenance(self):
        from novel_writer.application.backups import create_backup
        from novel_writer.application.migrations import migrate
        from novel_writer.application.skill_import import SkillLibrary
        from novel_writer.application.service import NovelService
        from novel_writer.storage.sqlite_repository import SQLiteRepository
        # Existing outline field, through the same saved-body F1 proposal/receipt mechanics.
        state=self.service.get(self.pid)
        self.service.execute(self.pid,'save_book_outline',dict(premise='原前提',theme='原主题',main_plot='原主线',ending='原结局',volumes=[]),expected_revision=state['revision'])
        outline=self.service.get(self.pid)['document']['book_outline'];payload=self.payload()
        payload['suggestions'][0]['actions']=[dict(action='prepare_plan',values=dict(target_kind='book_outline',target_id=outline['id'],field='ending',new_text='新的虚构结局',reason='正文驱动反馈待核实',source=dict(kind='chapter',entity_id=self.c1)))]
        with model_wire(json.dumps(payload,ensure_ascii=False)) as wire:
            view=self.run_task(self.prepare(self.connection(wire)));self.assertEqual(view['status'],'succeeded',view)
            proposal=self.transfer(view);impact=self.preview(proposal);self.decision(proposal,preview_sha256=impact['preview_sha256'])
            saved=self.service.get(self.pid);self.assertEqual(saved['document']['book_outline']['ending'],'新的虚构结局')
            self.assertEqual(len(saved['planning_proposals']),1);self.assertEqual(len(saved['planning_receipts']),1)
            SkillLibrary(self.db);package=self.root/'accepted-model.nwbak';create_backup(self.db,package)
            for index in range(2):
                target=self.root/f'accepted-copy-{index}.sqlite3';SQLiteRepository(target);SkillLibrary(target)
                result=migrate(package,target,operation_id=str(uuid4()));clone=NovelService(SQLiteRepository(target)).get(result['projects'][0]['new_id'])
                self.assertEqual(clone['model_planning_tasks'][0]['binding'],saved['model_planning_tasks'][0]['binding'])
                self.assertEqual(clone['document']['book_outline']['ending'],'新的虚构结局')
                self.assertEqual(clone['body_planning_receipts'][0]['decision'],'accepted')
                package=self.root/f'accepted-copy-{index}.nwbak';create_backup(target,package)

    def test_all_source_mutations_invalidate_saved_model_proposals_before_acceptance(self):
        from novel_writer.application.scoped_rules import RuleCoordinator
        from novel_writer.application.body_planning import BodyPlanning
        for mode in ('character','plan','lock','character_archive','chapter_archive','rules','body','configuration'):
            with self.subTest(mode=mode),model_wire(json.dumps(self.payload(),ensure_ascii=False)) as wire:
                c=self.connection(wire);view=self.run_task(self.prepare(c));self.assertEqual(view['status'],'succeeded',view)
                p=self.transfer(view);impact=self.preview(p);engine=BodyPlanning(self.service)
                if mode=='character':self.service.execute(self.pid,'save_character',dict(character_id=self.character,name='林默',notes='人物设定更新'),expected_revision=self.revision())
                elif mode=='plan':self.act('update_event',event_id=self.eid,title='更新的事件标题')
                elif mode=='lock':engine.set_lock(self.pid,self.request(target_kind='event',target_id=self.eid,locked=True,reason='新锁'))
                elif mode=='character_archive':engine.lifecycle(self.pid,self.request(kind='character',entity_id=self.character,archived=True,confirm=True))
                elif mode=='chapter_archive':self.service.execute(self.pid,'archive_chapter',dict(chapter_id=self.c1,confirmed=True),expected_revision=self.revision())
                elif mode=='rules':RuleCoordinator(self.service).save(self.pid,dict(operation_id=str(uuid4()),rule_id=None,scope='chapter',scope_id=self.c1,kind='guidance',text='新的虚构规则',enabled=True))
                elif mode=='body':self.save(content='已改写的正文。')
                else:self.providers.manage(id=c['id'],action='disable',confirmed=True)
                before=self.service.get(self.pid)
                with self.assertRaises(ValueError):self.decision(p,preview_sha256=impact['preview_sha256'])
                self.assertEqual(before,self.service.get(self.pid))
                # Rejection remains available even for stale sources.
                self.decision(p,'rejected')
                if mode=='lock':engine.set_lock(self.pid,self.request(target_kind='event',target_id=self.eid,locked=False,reason='作者明确解锁'))
                elif mode=='character_archive':engine.lifecycle(self.pid,self.request(kind='character',entity_id=self.character,archived=False,confirm=True))
                elif mode=='chapter_archive':self.service.execute(self.pid,'unarchive_chapter',dict(chapter_id=self.c1,confirmed=True),expected_revision=self.revision())
                elif mode=='body':self.save(content='😀林默交出旧钥匙。星灯熄灭。')

    def test_source_change_while_response_in_flight_and_reopen_pending_never_reuse_send(self):
        from novel_writer.application.service import NovelService
        from novel_writer.storage.sqlite_repository import SQLiteRepository
        with model_wire(json.dumps(self.payload(),ensure_ascii=False),hold=True) as wire:
            c=self.connection(wire);pending=self.prepare(c)
            service=NovelService(SQLiteRepository(self.db));shared=TaskCoordinator(service,AdapterRegistry());self.addCleanup(shared.close)
            reopened=ModelPlanningCoordinator(shared,self.providers,enabled=True)
            self.assertEqual(reopened.describe(self.pid,pending['task']['id'])['display_status'],'interrupted')
            with self.assertRaises(ValueError):reopened.start(self.pid,pending['task']['id'],dict(confirm_external=True,request_sha256=pending['task']['binding']['request_sha256'],budget_sha256=pending['task']['budget_sha256'],expected_revision=pending['revision']))
            self.start(pending);self.assertTrue(wire['ready'].wait(2));self.act('update_event',event_id=self.eid,title='模型发送后作者修改计划')
            wire['release'].set();self.shared.wait_idle(5);view=self.ai.describe(self.pid,pending['task']['id'])
            self.assertEqual(view['status'],'failed');self.assertEqual(view['candidates'],[]);self.assertEqual(len(wire['calls']),1)

    def test_multiple_suggestions_only_explicit_selected_item_transfers_and_failed_transfer_rolls_back(self):
        payload=self.payload();second=deepcopy(payload['suggestions'][0]);second['actions']=[dict(action='update_event',values=dict(event_id=self.eid,title='另一个建议'))];payload['suggestions'].append(second)
        with model_wire(json.dumps(payload,ensure_ascii=False)) as wire:
            view=self.run_task(self.prepare(self.connection(wire)));c=view['candidates'][0]
            selection=dict(candidate_id=c['id'],candidate_sha256=c['data_sha256'],suggestion_index=1)
            preview=self.ai.preview_transfer(self.pid,selection);before=self.service.get(self.pid)
            with self.assertRaises(ValueError):self.ai.propose(self.pid,self.request(**selection,confirmed=True,transfer_token='forged'))
            self.assertEqual(before,self.service.get(self.pid))
            from unittest.mock import patch
            with patch('novel_writer.application.model_planning.ModelPlanningLink',side_effect=ValueError('injected link failure')):
                with self.assertRaisesRegex(ValueError,'injected link failure'):
                    self.ai.propose(self.pid,self.request(**selection,confirmed=True,transfer_token=preview['transfer_token']))
            self.assertEqual(before,self.service.get(self.pid))
            proposal=self.transfer(view,1);state=self.service.get(self.pid)
            self.assertEqual(len(state['model_planning_links']),1);self.assertEqual(state['model_planning_links'][0]['suggestion_index'],1)
            self.assertEqual(proposal['actions'],second['actions']);self.assertEqual(state['key_events'][0]['title'],'旧钥匙出现')

    def test_source_is_read_only_budgeted_and_sends_only_resolved_rules_text(self):
        from novel_writer.application.scoped_rules import RuleCoordinator
        from novel_writer.application.model_planning import build_source
        rules=RuleCoordinator(self.service)
        rules.save(self.pid,dict(operation_id=str(uuid4()),rule_id=None,scope='chapter',scope_id=self.c1,kind='guidance',text='本章有效虚构规则',enabled=True))
        rules.save(self.pid,dict(operation_id=str(uuid4()),rule_id=None,scope='chapter',scope_id=self.c2,kind='guidance',text='另一章不发送的规则',enabled=True))
        before=self.service.get(self.pid);options=dict(chapter_id=self.c1,character_ids=[self.character],instruction='核对',context_budget_chars=100000)
        source=self.ai.preview(self.pid,options);self.assertEqual(before,self.service.get(self.pid))
        self.assertIn('本章有效虚构规则',source['context_text']);self.assertNotIn('另一章不发送的规则',source['context_text'])
        with self.assertRaises(ValueError):build_source(before,dict(options,context_budget_chars=1024))
        with self.assertRaises(ValueError):build_source(before,dict(options,character_ids=[{}]))

    def test_persisted_model_histories_reject_tamper_and_v37_downgrade(self):
        from novel_writer.storage.sqlite_repository import validate_workspace
        with model_wire(json.dumps(self.payload(),ensure_ascii=False)) as wire:
            view=self.run_task(self.prepare(self.connection(wire)));self.transfer(view);state=self.service.get(self.pid)
            downgraded=deepcopy(state);downgraded['workspace_version']=36
            with self.assertRaises(ValueError):validate_workspace(downgraded)
            for mutate in (lambda s:s['model_planning_tasks'][0].update(budget_sha256='0'*64),
                lambda s:s['model_planning_candidates'][0].update(raw_text='forged'),
                lambda s:s['model_planning_links'][0].update(suggestion_index=True)):
                changed=deepcopy(state);mutate(changed)
                with self.assertRaises(ValueError):validate_workspace(changed)
            def remove_history(current):
                current['model_planning_candidates'].clear();return current,True
            with self.assertRaises(ValueError):self.service.repository.atomic(self.pid,remove_history)
            self.assertEqual(state,self.service.get(self.pid))


if __name__ == '__main__': unittest.main()
