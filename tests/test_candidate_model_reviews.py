"""A model reviews actual upstream candidates without inventing saved prose."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from uuid import uuid4
from copy import deepcopy
import json,threading,time,unittest
import test_configured_tasks as fixtures
from test_s6b_workflows import node,template,TASK
from novel_writer.domain.connections import canonical_messages

@contextmanager
def candidate_wire(protocol='openai-chat',bad=None,stream=False):
    calls=[];candidate='\n未采纳候选🙂人物转身关门。';ready=threading.Event();release=threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));messages=canonical_messages(body,protocol);source=json.loads(messages[1]['content']);calls.append(dict(body=body,source=source,messages=messages))
            if 'sources' in source and source.get('input_origin')=='candidate':
                quote=dict(source_index=0,start=0,end=len(candidate),quote=candidate);finding=dict(category='consistency',statement='这是待核实的候选意见，不是保存正文事实。',assessment='model_opinion',evidence=[quote]);value=dict(overview='候选审核待核实',findings=[finding])
                if bad=='quote':quote['quote']='编造证据'
                elif bad=='utf16':quote['end']+=1
                elif bad=='source':quote['source_index']=1
                elif bad=='empty':finding['evidence']=[]
                elif bad=='proposals':value['proposals']=[]
                elif bad=='inference':finding['assessment']='causal_inference'
                content=json.dumps(value,ensure_ascii=False)
            else:content=candidate
            if stream:
                from test_sse_protocols import event,chat
                if protocol=='openai-chat':head=event(chat(content));tail=event(chat('', 'stop'))+b'data: [DONE]\r\n\r\n'
                elif protocol=='anthropic-messages':
                    head=event(dict(type='message_start',message=dict(id='fake',role='assistant',content=[])),'message_start')+event(dict(type='content_block_start',index=0,content_block=dict(type='text',text='')),'content_block_start')+event(dict(type='content_block_delta',index=0,delta=dict(type='text_delta',text=content)),'content_block_delta')
                    tail=event(dict(type='content_block_stop',index=0),'content_block_stop')+event(dict(type='message_delta',delta=dict(stop_reason='end_turn')),'message_delta')+event(dict(type='message_stop'),'message_stop')
                else:head=event(dict(candidates=[dict(index=0,content=dict(role='model',parts=[dict(text=content)]))]));tail=event(dict(candidates=[dict(index=0,finishReason='STOP')]))
                if bad=='truncated' and source.get('input_origin')=='candidate':tail=b''
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(head)+len(tail)+(1 if bad=='truncated' and source.get('input_origin')=='candidate' else 0)));self.end_headers()
                try:
                    for byte in head:self.wfile.write(bytes([byte]));self.wfile.flush()
                    if source.get('input_origin')=='candidate':ready.set();release.wait(4)
                    self.wfile.write(tail);self.wfile.flush()
                except OSError:pass
                return
            if protocol=='anthropic-messages':payload=dict(role='assistant',content=[dict(type='text',text=content)],stop_reason='end_turn')
            elif protocol=='gemini-content':payload=dict(candidates=[dict(content=dict(role='model',parts=[dict(text=content)]),finishReason='STOP')])
            else:payload=dict(choices=[dict(message=dict(role='assistant',content=content),finish_reason='stop')])
            data=json.dumps(payload,ensure_ascii=False).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True;t=threading.Thread(target=server.serve_forever,kwargs=dict(poll_interval=.01),daemon=True);t.start()
    try:yield dict(url='http://127.0.0.1:'+str(server.server_port)+'/v1',calls=calls,candidate=candidate,ready=ready,release=release)
    finally:release.set();server.shutdown();server.server_close();t.join(2)

class CandidateModelReviewTests(unittest.TestCase):
    setUp=fixtures.ConfiguredTaskTests.setUp
    save=fixtures.ConfiguredTaskTests.save
    def create(self,c):
        from novel_writer.application.workflows import WorkflowCoordinator
        self.flow=WorkflowCoordinator(self.service,self.engine);self.addCleanup(self.flow.close)
        nodes=[node('read','reference',params=dict(max_chars=20000)),node('write','model_rewrite',['read'],'read','writer',TASK),node('review','model_candidate_audit',['write'],'write','auditor',TASK),node('human','human',['review'],'review',params=dict(action='body')),node('apply','apply',['human'],'human',params=dict(action='body'))]
        version=self.flow.import_template(self.pid,dict(operation_id=str(uuid4()),template_id=None,template=template(nodes),expected_revision=self.service.get(self.pid)['revision']))
        roles=[dict(role=role,adapter_id='configured-http-v2',connection_id=c['id'],model_id=c['model_id'],temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=True,prompt_version='rewrite-1' if role=='writer' else 'review-json-1') for role in ('writer','auditor')]
        run=self.flow.create(self.pid,dict(operation_id=str(uuid4()),template_version_id=version['version_id'],chapter_id=self.cid,inputs=dict(instruction='先写候选再核对候选意见',query='',plan_text=''),roles=roles,limits=dict(max_external_calls=3,max_reserved_output_tokens=1536,max_node_attempts=64,max_retries=1,max_iterations=3,concurrency=1),execution_mode='step',network_mode='confirm_each',expected_revision=self.service.get(self.pid)['revision']));self.flow.control(self.pid,run['run_id'],'start');return run['run_id']
    def step(self,run):return self.flow.step(self.pid,run)
    def waiting(self,run):return next(v for v in reversed(self.flow.describe(self.pid,run)['attempts']) if v['status'] in ('waiting_request','waiting_human'))
    def confirm(self,run,a):return self.flow.confirm(self.pid,run,a['id'],dict(operation_id=str(uuid4()),decision='accepted',request_sha256=a.get('request_sha256'),diff_sha256=a.get('diff_sha256'),authorize_confirmed=False,confirm_inference=False,preserve_conflicts=False,expected_revision=self.service.get(self.pid)['revision']))
    def ready(self,run):
        self.step(run);self.step(run);a=self.waiting(run);self.confirm(run,a);self.engine.wait_idle(5);self.step(run);self.step(run);return self.waiting(run)
    def test_three_protocols_only_candidate_wire_typed_evidence_and_manual_body_gate(self):
        for protocol in ('openai-chat','anthropic-messages','gemini-content'):
            with self.subTest(protocol=protocol),candidate_wire(protocol) as wire:
                self.service.execute(self.pid,'save_chapter',dict(chapter_id=self.cid,content='已保存原正文_'+protocol),expected_revision=self.service.get(self.pid)['revision'])
                before=self.service.get(self.pid);run=self.create(self.save(wire['url'],protocol));a=self.ready(run);self.assertEqual(len(wire['calls']),1);task=self.engine.describe(self.pid,a['task_id'])['task'];self.assertEqual(task['frozen']['parameters']['binding']['prompt_version'],'candidate-review-json-1');self.assertEqual(task['frozen']['context_text'],'')
                self.confirm(run,a);self.engine.wait_idle(5);self.step(run);state=self.service.get(self.pid);self.assertEqual(self.engine.describe(self.pid,a['task_id'])['task']['status'],'succeeded',self.engine.describe(self.pid,a['task_id']));audit=state['workflow_audits'][-1];self.assertEqual(audit['output']['method'],'model_candidate_semantic_review_v1');ev=audit['output']['findings'][0]['evidence'][0];self.assertEqual(ev['source_kind'],'candidate');self.assertIsNone(ev['version_id']);self.assertEqual(ev['entity_id'],audit['upstream']['entity_id']);self.assertEqual(state['document'],before['document']);self.assertEqual(state['memories'],before.get('memories',[]));self.assertEqual(state['model_reports'],[]);self.assertEqual(wire['calls'][-1]['source']['sources'][0]['text'],wire['candidate']);self.assertNotIn(before['document']['chapters'][0]['content'],json.dumps(wire['calls'][-1]['source'],ensure_ascii=False));self.assertEqual(state['workspace_version'],35)
                self.step(run);human=self.waiting(run);self.assertEqual(human['node_kind'],'human');self.confirm(run,human);self.step(run);self.assertEqual(self.service.get(self.pid)['document']['chapters'][0]['content'],wire['candidate'])
    def test_invalid_outputs_have_response_but_no_audit_or_memory(self):
        for bad in ('quote','utf16','source','empty','proposals','inference'):
            with self.subTest(bad=bad),candidate_wire(bad=bad) as wire:
                run=self.create(self.save(wire['url']));a=self.ready(run);before=self.service.get(self.pid);self.confirm(run,a);self.engine.wait_idle(5);self.step(run);state=self.service.get(self.pid);self.assertEqual(self.engine.describe(self.pid,a['task_id'])['task']['status'],'failed');self.assertEqual(state['workflow_audits'],before['workflow_audits']);self.assertEqual(state['memories'],before.get('memories',[]));self.assertEqual(state['document'],before['document'])

    def test_v35_restore_and_two_copies_preserve_wire_and_map_real_producers(self):
        from novel_writer.application.backups import create_backup,restore_backup
        from novel_writer.application.migrations import migrate
        from novel_writer.application.skill_import import SkillLibrary
        from novel_writer.application.service import NovelService
        from novel_writer.storage.sqlite_repository import SQLiteRepository,validate_workspace
        with candidate_wire() as wire:
            run=self.create(self.save(wire['url']));a=self.ready(run);self.confirm(run,a);self.engine.wait_idle(5);self.step(run)
            state=self.service.get(self.pid);task=next(t for t in state['generation_tasks'] if t['id']==a['task_id']);params=task['frozen']['parameters'];source=wire['calls'][-1]['source']['sources'][0]
            for key,value in params['wire_source'].items():self.assertEqual(source[key],value)
            bad=deepcopy(state);bad['workspace_version']=34
            with self.assertRaises(ValueError):validate_workspace(bad)
            bad=deepcopy(state);next(t for t in bad['generation_tasks'] if t['id']==a['task_id'])['frozen']['parameters']['wire_source']['entity_id']=str(uuid4())
            with self.assertRaises(ValueError):validate_workspace(bad)
            db=self.root/'fiction.sqlite3';SkillLibrary(db);package=self.root/'candidate.nwbak';self.assertEqual(create_backup(db,package)['backup_format_version'],51)
            restored=restore_backup(package,self.root/'candidate-restored');self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid),state)
            for index in (1,2):
                target=self.root/f'candidate-copy-{index}.sqlite3';SQLiteRepository(target);SkillLibrary(target);copied=migrate(package,target,operation_id=str(uuid4()));clone=NovelService(SQLiteRepository(target)).get(copied['projects'][0]['new_id']);audit=clone['workflow_audits'][-1];mapped=next(t for t in clone['generation_tasks'] if t['id']==audit['task_id'])['frozen']['parameters']
                self.assertEqual(mapped['binding'],params['binding']);self.assertEqual(mapped['wire_source'],params['wire_source']);self.assertEqual(len(mapped['copy_mappings']),index);self.assertNotEqual(mapped['upstream']['entity_id'],params['upstream']['entity_id']);self.assertEqual(mapped['copy_mappings'][-1]['after']['entity_id'],audit['upstream']['entity_id']);self.assertEqual(audit['output']['findings'][0]['evidence'][0]['entity_id'],audit['upstream']['entity_id']);self.assertTrue(any(r['id']==audit['response_record_id'] for r in clone['model_results']))
                package=self.root/f'candidate-copy-{index}.nwbak';create_backup(target,package)
            self.assertEqual(len(wire['calls']),2)

    def test_saved_body_change_at_worker_send_boundary_prevents_audit_request(self):
        from unittest.mock import patch
        with candidate_wire() as wire:
            run=self.create(self.save(wire['url']));a=self.ready(run);original=self.engine.registry.validate_preparation
            def checked(task):
                original(task)
                if task.id==a['task_id'] and task.status=='running':
                    self.service.execute(self.pid,'save_chapter',dict(chapter_id=self.cid,content='作者在确认后、发送前保存了新正文'),expected_revision=self.service.get(self.pid)['revision'])
            with patch.object(self.engine.registry,'validate_preparation',side_effect=checked):self.confirm(run,a);self.engine.wait_idle(5)
            self.step(run);self.assertEqual(len(wire['calls']),1);state=self.service.get(self.pid);self.assertEqual(state['workflow_audits'],[]);self.assertEqual(self.engine.describe(self.pid,a['task_id'])['task']['status'],'failed')

    def test_sse_preview_completion_cancel_timeout_and_truncation(self):
        for protocol,outcome in [('openai-chat','success'),('anthropic-messages','success'),('gemini-content','success'),('openai-chat','cancel'),('openai-chat','timeout'),('openai-chat','truncated')]:
            with self.subTest(protocol=protocol,outcome=outcome),candidate_wire(protocol,bad=outcome,stream=True) as wire:
                c=self.save(wire['url'],protocol);self.providers.manage(id=c['id'],action='stream_profile',confirmed=True,stream_mode='sse');run=self.create(c);a=self.ready(run);before=self.service.get(self.pid);self.confirm(run,a);self.assertTrue(wire['ready'].wait(1.5));deadline=time.monotonic()+1
                while time.monotonic()<deadline:
                    view=self.engine.describe(self.pid,a['task_id'])
                    if view.get('stream_preview',{}).get('text'):break
                    time.sleep(.01)
                self.assertTrue(view.get('stream_preview',{}).get('temporary'));self.assertEqual(self.service.get(self.pid)['workflow_audits'],before['workflow_audits']);self.assertNotIn('stream_preview',json.dumps(self.service.get(self.pid)))
                if outcome=='cancel':self.flow.control(self.pid,run,'cancel')
                elif outcome=='timeout':time.sleep(2.1)
                wire['release'].set();self.engine.wait_idle(5)
                if outcome!='cancel':self.step(run)
                done=self.engine.describe(self.pid,a['task_id']);state=self.service.get(self.pid);self.assertNotIn('stream_preview',done);self.assertEqual(state['document'],before['document']);self.assertEqual(state['memories'],before.get('memories',[]));self.assertEqual(len(wire['calls']),2)
                if outcome=='success':self.assertEqual(done['task']['status'],'succeeded');self.assertEqual(len(state['workflow_audits']),len(before['workflow_audits'])+1)
                else:
                    self.assertEqual(done['task']['status'],'cancelled' if outcome=='cancel' else 'failed');self.assertEqual(state['workflow_audits'],before['workflow_audits'])

if __name__=='__main__':unittest.main()
