from pathlib import Path
from importlib import util,import_module
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from contextlib import closing
from unittest.mock import patch
from uuid import uuid4
import json,sys,tempfile,threading,time,unittest,sqlite3,zipfile
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository
from novel_writer.application.provider_connections import ProviderConnections,PROVIDERS
from novel_writer.application.skill_import import SkillLibrary
from novel_writer.application.tasks import TaskCoordinator
from novel_writer.application.task_protocol import AdapterRegistry
from novel_writer.domain.tasks import digest
from test_s5a_rules import request_rules
from test_s5a_review import rows
FAKE_KEY='fictional-s5c-private-sentinel'
PARAGRAPH='灯塔照亮港口潮水，船员静静等待远方的来信。'

class ModelTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(util.find_spec('novel_writer.application.model_adapter'),'缺少实际HTTP模型适配与有出处输出')
        self.api=import_module('novel_writer.application.model_adapter');self.temp=tempfile.TemporaryDirectory(prefix='novel-s5c-');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.db=self.root/'fictional.sqlite3';self.service=NovelService(SQLiteRepository(self.db));s=self.service.create(title='虚构港口');self.pid=s['document']['project']['id']
        self.save('add_chapter',title='灯塔');self.cid=self.service.get(self.pid)['document']['chapters'][0]['id'];self.save('save_chapter',chapter_id=self.cid,content=PARAGRAPH);self.save('save_book_outline',ending='原结局')
        self.library=SkillLibrary(self.db)
        self.path=self.root/'fictional.dpapi';self.providers=ProviderConnections(self.path);self.providers.save(id='gg',base_url=PROVIDERS['gg']['base_url'],model_id='author-selected-model',api_key=FAKE_KEY)
        self.mode='success';self.calls=[];self.request_seen=threading.Event();owner=self
        class Supplier(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                raw=self.rfile.read(int(self.headers['Content-Length']));body=json.loads(raw);owner.calls.append(dict(path=self.path,authorized=self.headers.get('Authorization')=='Bearer '+FAKE_KEY,body=body));owner.request_seen.set()
                mode=owner.mode;content='模型返回的完整候选。';status=200;finish='stop';usage=dict(prompt_tokens=17,completion_tokens=9,total_tokens=26);quote=PARAGRAPH
                if mode=='comparison' and body['model']=='fictional-failure-model':mode='429'
                if mode=='auto' and '只返回JSON对象' in body['messages'][0]['content']:
                    source_values=json.loads(body['messages'][1]['content'])['sources'];mode='bridge' if len(source_values)==2 else 'analysis';quote=source_values[0]['text']
                if mode=='analysis':content=json.dumps(dict(overview='模型审核意见，待核实',findings=[dict(category='consistency',statement='模型认为可能存在动机跳跃',assessment='model_opinion',evidence=[dict(source_index=0,start=0,end=len(quote),quote=quote)])],proposals=[dict(kind='chapter_summary',title='模型概括',text='船员在灯塔附近等候来信。',assessment='model_summary',evidence=[dict(source_index=0,start=0,end=len(quote),quote=quote)])]),ensure_ascii=False)
                if mode=='bridge':
                    sources=json.loads(body['messages'][1]['content'])['sources'];content=json.dumps(dict(overview='模型重复桥段建议，待核实',findings=[],proposals=[],bridges=[dict(statement='模型认为两段可衔接，尚未核实',assessment='model_opinion',side=1,replacement='作者可核对的合并衔接建议。',evidence=[dict(source_index=i,start=0,end=len(s['text']),quote=s['text']) for i,s in enumerate(sources)])]),ensure_ascii=False)
                if mode=='analysis_multi':
                    sources=json.loads(body['messages'][1]['content'])['sources'];content=json.dumps(dict(overview='多出处模型摘要待核实',findings=[],proposals=[dict(kind='chapter_summary',title='两处引文',text='作者需要核实的跨章摘要。',assessment='model_summary',evidence=[dict(source_index=i,start=0,end=len(s['text']),quote=s['text']) for i,s in enumerate(sources)])]),ensure_ascii=False)
                if mode=='bad_quote':
                    content=json.dumps(dict(overview='无效引文',findings=[],proposals=[dict(kind='event',title='伪造',text='发生了未保存的事',assessment='model_inference',evidence=[dict(source_index=0,start=0,end=3,quote='伪造文')])]),ensure_ascii=False)
                if mode=='tools':finish='tool_calls'
                if mode=='length':finish='length'
                if mode=='unknown_usage':usage=None
                if mode in ('401','429'):status=int(mode)
                if mode=='slow':time.sleep(.8)
                if mode=='too_long':content='长'*200001
                if mode=='credential_echo':content='供应商意外回显 '+FAKE_KEY
                payload=dict(id='fictional-response',model='supplier-reported-alias',choices=[dict(index=0,message=dict(role='assistant',content=content),finish_reason=finish)],usage=usage)
                if mode=='tools':payload['choices'][0]['message']['tool_calls']=[dict(type='function',function=dict(name='delete_files',arguments='{}'))]
                data=json.dumps(payload,ensure_ascii=False).encode('utf8')
                if mode=='bad_json':data=b'{broken'
                if mode in ('401','429'):data=json.dumps(dict(error=FAKE_KEY)).encode()
                self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)+(20 if mode=='truncated' else 0)));self.end_headers()
                try:self.wfile.write(data);self.wfile.flush()
                except (BrokenPipeError,ConnectionResetError,OSError):pass
                self.close_connection=True
        self.remote=ThreadingHTTPServer(('127.0.0.1',0),Supplier);self.remote.daemon_threads=True;self.thread=threading.Thread(target=self.remote.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start();self.addCleanup(self.stop_remote)
        self.adapter=self.api.ChatCompletionsAdapter(self.providers,enabled=True,transport=self.api.ChatHttpTransport(endpoint_override='http://127.0.0.1:'+str(self.remote.server_address[1])+'/v1'))
        registry=AdapterRegistry();registry.register('rewrite_chapter',self.adapter);registry.register('audit_chapter',self.adapter);self.engine=TaskCoordinator(self.service,registry);self.addCleanup(self.engine.close)
    def stop_remote(self):self.remote.shutdown();self.thread.join(2);self.remote.server_close()
    def save(self,action,**values):return self.service.execute(self.pid,action,values,expected_revision=self.service.get(self.pid)['revision'])
    def prepare(self,analysis=False,**changes):
        state=self.service.get(self.pid);options=dict(chapter_id=self.cid,budget_chars=4000);preview=self.service.preview_context(self.pid,options)
        params=request_rules() if analysis else dict(instruction='根据保存正文给出候选，不执行任何工具',max_output_chars=10000,timeout_ms=2000)
        if analysis:params['selected_chapter_ids']=[self.cid]
        binding=dict(adapter_id='chat-completions-http-v1',connection_id='gg',model_id='author-selected-model',temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=True,prompt_version='review-json-1' if analysis else 'rewrite-1')
        request=dict(request_id=str(uuid4()),chapter_id=self.cid,task_type='audit_chapter' if analysis else 'rewrite_chapter',context_options=options,context_sha256=digest(preview['context_text']),parameters=params,model_options=binding,expected_revision=state['revision']);request.update(changes)
        return self.engine.prepare(self.pid,request)
    def run_task(self,prepared,**changes):
        task=prepared['task'];binding=task['frozen']['parameters']['binding'];confirm=dict(confirm_external=True,request_sha256=binding['request_sha256']);confirm.update(changes);self.engine.start(self.pid,task['id'],confirmation=confirm);self.engine.wait_idle(5);return self.engine.describe(self.pid,task['id'])
    def test_prepare_freezes_outbound_connection_model_limits_prompt_without_reading_credentials_or_sending(self):
        with patch.object(self.providers,'_load',side_effect=AssertionError('准备不能读凭据')):prepared=self.prepare()
        self.assertEqual(self.calls,[]);task=prepared['task'];binding=task['frozen']['parameters']['binding'];body=json.loads(binding['request_body']);self.assertEqual(body['model'],'author-selected-model');self.assertEqual(body['max_tokens'],512);self.assertFalse(body['stream']);self.assertEqual(binding['request_sha256'],digest(binding['request_body']));self.assertIn(PARAGRAPH,binding['request_body']);self.assertNotIn(FAKE_KEY,json.dumps(task));self.assertEqual(self.service.get(self.pid)['workspace_version'],6)
        for confirm in (None,dict(confirm_external=False,request_sha256=binding['request_sha256']),dict(confirm_external=True,request_sha256='0'*64)):
            with self.assertRaises(ValueError):self.engine.start(self.pid,task['id'],confirmation=confirm)
        self.assertEqual(self.calls,[])
    def test_real_wire_completion_usage_and_atomic_candidate_adoption_once(self):
        p=self.prepare();view=self.run_task(p);self.assertEqual(view['task']['status'],'succeeded',view);self.assertEqual(len(self.calls),1);self.assertEqual(self.calls[0]['path'],'/v1/chat/completions');self.assertTrue(self.calls[0]['authorized']);self.assertEqual(self.calls[0]['body'],json.loads(p['task']['frozen']['parameters']['binding']['request_body']));candidate=view['candidates'][0];self.assertEqual(candidate['provenance'],'model_http_candidate');self.assertEqual(candidate['token_count'],26);self.assertIsNone(candidate['cost'])
        request=dict(candidate_id=candidate['id'],adoption_id=str(uuid4()),expected_revision=view['revision'],authorize_confirmed=False);receipt=self.engine.adopt(self.pid,view['task']['id'],request);saved=rows(self.db);self.assertEqual(self.engine.adopt(self.pid,view['task']['id'],request),receipt);self.assertEqual(rows(self.db),saved)
    def test_unknown_usage_is_unknown_and_not_estimated_from_text(self):
        self.mode='unknown_usage';view=self.run_task(self.prepare());self.assertEqual(view['task']['status'],'succeeded');self.assertIsNone(view['candidates'][0]['token_count']);self.assertIsNone(view['model_results'][0]['response']['usage']['total_tokens'])
    def test_no_implicit_external_retry_and_http_parse_partial_tool_failures_are_not_candidates(self):
        for mode in ('401','429','bad_json','length','tools','truncated','too_long','credential_echo'):
            with self.subTest(mode=mode):
                self.mode=mode;before=len(self.calls);view=self.run_task(self.prepare());self.assertEqual(view['task']['status'],'failed',view);self.assertFalse(view['candidates']);self.assertEqual(len(self.calls),before+1);self.assertEqual(len(view['model_results']),1);self.assertFalse(view['model_results'][0]['response']['complete']);self.assertNotIn(FAKE_KEY,json.dumps(self.service.get(self.pid)))
    def test_timeout_cancel_and_late_response_cannot_complete_or_write_body(self):
        self.mode='slow';p=self.prepare(parameters=dict(instruction='超时',max_output_chars=10000,timeout_ms=120));view=self.run_task(p);self.assertEqual(view['task']['status'],'failed');self.assertFalse(view['candidates'])
        self.request_seen.clear();p=self.prepare();before=self.service.get(self.pid)['document'];binding=p['task']['frozen']['parameters']['binding'];self.engine.start(self.pid,p['task']['id'],confirmation=dict(confirm_external=True,request_sha256=binding['request_sha256']));self.assertTrue(self.request_seen.wait(1));self.engine.cancel(self.pid,p['task']['id']);self.engine.wait_idle(2);view=self.engine.describe(self.pid,p['task']['id']);self.assertEqual(view['task']['status'],'cancelled');self.assertFalse(view['candidates']);self.assertEqual(self.service.get(self.pid)['document'],before)
    def test_budget_url_key_model_switch_and_disabled_adapter_do_not_send(self):
        for key,value in [('allow_unknown_cost',False),('budget_limit',0.0),('endpoint','https://untrusted.example'),('api_key','not-accepted')]:
            p=self.prepare()['task']['frozen']['parameters']['binding'];options={k:p[k] for k in ('adapter_id','connection_id','model_id','temperature','max_tokens','budget_limit','allow_unknown_cost','prompt_version')};options[key]=value
            with self.assertRaises(ValueError):self.prepare(model_options=options)
        p=self.prepare();self.adapter.enabled=False
        with self.assertRaises(ValueError):self.run_task(p)
        self.assertEqual(self.calls,[]);self.adapter.enabled=True;self.providers.save(id='gg',base_url=PROVIDERS['gg']['base_url'],model_id='changed-model',api_key='')
        with self.assertRaisesRegex(ValueError,'过期'):self.run_task(p)
        self.assertEqual(self.calls,[]);self.assertEqual(self.engine.describe(self.pid,p['task']['id'])['task']['status'],'pending')
    def test_model_analysis_evidence_unverified_proposal_and_explicit_memory_accept_not_body_adoption(self):
        self.mode='analysis';view=self.run_task(self.prepare(analysis=True));self.assertEqual(view['task']['status'],'succeeded',view);self.assertFalse(view['candidates']);report=self.engine.model_review(self.pid,view['model_reports'][0]['id']);self.assertEqual(report['output']['findings'][0]['assessment'],'model_opinion');proposal=report['proposals'][0];self.assertEqual(proposal['draft']['evidence'][0]['quote'],PARAGRAPH);self.assertIsNone(proposal['receipt']);before=self.service.get(self.pid)
        request=dict(decision_id=str(uuid4()),proposal_id=proposal['id'],decision='accepted',expected_revision=before['revision'],confirm_inference=False,preserve_conflicts=True)
        with self.assertRaises(ValueError):self.engine.decide_model_proposal(self.pid,report['report']['id'],request)
        request['confirm_inference']=True;receipt=self.engine.decide_model_proposal(self.pid,report['report']['id'],request);after=self.service.get(self.pid);self.assertEqual(after['document'],before['document']);self.assertEqual(len(after['memories']),len(before['memories'])+1);saved=rows(self.db);self.assertEqual(self.engine.decide_model_proposal(self.pid,report['report']['id'],request),receipt);self.assertEqual(rows(self.db),saved)
    def test_bad_quote_or_changed_source_never_becomes_accepted_memory(self):
        self.mode='bad_quote';view=self.run_task(self.prepare(analysis=True));self.assertEqual(view['task']['status'],'failed');self.assertFalse(view['model_reports'])
        self.mode='analysis';view=self.run_task(self.prepare(analysis=True));report=self.engine.model_review(self.pid,view['model_reports'][0]['id']);self.save('save_chapter',chapter_id=self.cid,content='作者改动来源');before=rows(self.db)
        with self.assertRaises(ValueError):self.engine.decide_model_proposal(self.pid,report['report']['id'],dict(decision_id=str(uuid4()),proposal_id=report['proposals'][0]['id'],decision='accepted',expected_revision=self.service.get(self.pid)['revision'],confirm_inference=True,preserve_conflicts=True))
        self.assertEqual(rows(self.db),before)
    def test_complete_backup_copy_preserve_raw_candidate_usage_evidence_and_no_credentials(self):
        from novel_writer.application.backups import create_backup,restore_backup
        from novel_writer.application.migrations import migrate
        self.mode='analysis';self.run_task(self.prepare(analysis=True));package=self.root/'models.nwbak';manifest=create_backup(self.db,package);self.assertEqual(manifest['backup_format_version'],51);restored=Path(restore_backup(package,self.root/'restore')['database_path']);self.assertEqual(rows(restored),rows(self.db));self.assertNotIn(FAKE_KEY,json.dumps(rows(restored)))
        target=self.root/'copy.sqlite3';SQLiteRepository(target);SkillLibrary(target);copied=migrate(package,target,operation_id=str(uuid4()));pid=copied['projects'][0]['new_id'];s=NovelService(SQLiteRepository(target)).get(pid);self.assertEqual(s['model_results'][0]['response']['raw_response'],self.service.get(self.pid)['model_results'][0]['response']['raw_response']);self.assertEqual(len(s['model_reports']),1);self.assertNotEqual(s['model_reports'][0]['id'],self.service.get(self.pid)['model_reports'][0]['id']);self.assertEqual(len(self.calls),1)
    def test_actual_old_v5_rows_and_graph_history_remain_unchanged(self):
        from novel_writer.application.backups import restore_backup
        from novel_writer.application.knowledge import command
        frozen=json.loads((ROOT/'tests/fixtures/s5c_legacy.json').read_text(encoding='utf8'))['v5'];old=self.root/'old-v5.sqlite3';old.write_bytes(bytes.fromhex(frozen['database_hex']));before=old.read_bytes();service=NovelService(SQLiteRepository(old));s=service.get('p1');self.assertEqual(s['workspace_version'],5);self.assertEqual(old.read_bytes(),before)
        package=self.root/'old-v5.nwbak';package.write_bytes(bytes.fromhex(frozen['package_hex']));restored=Path(restore_backup(package,self.root/'old-v5-restored')['database_path']);self.assertEqual(rows(restored),frozen['rows'])
        self.run_task(self.prepare());s=self.service.get(self.pid);command(self.service,self.pid,'save_node',dict(operation_id=str(uuid4()),expected_revision=s['revision'],kind='location',label='灯塔',aliases=[],memory_ids=[],position_chapter_id=self.cid,source=dict(kind='chapter',entity_id=self.cid),confirmed=True));self.assertEqual(self.service.get(self.pid)['workspace_version'],6)
    def test_model_bridge_requires_explicit_handoff_then_uses_existing_local_edit_adoption(self):
        from novel_writer.application.knowledge import command
        self.save('add_chapter',title='远方');other=self.service.get(self.pid)['document']['chapters'][-1]['id'];self.save('save_chapter',chapter_id=other,content='另一侧实际保存的正文，仍有港口和远方来信。');params=request_rules();params['selected_chapter_ids']=[self.cid,other];self.mode='bridge';view=self.run_task(self.prepare(analysis=True,parameters=params));self.assertEqual(view['task']['status'],'succeeded',view);self.assertFalse(view['candidates']);report=self.engine.model_review(self.pid,view['model_reports'][0]['id']);bridge=report['bridges'][0];before=self.service.get(self.pid);request=dict(decision_id=str(uuid4()),proposal_id=bridge['id'],decision='accepted',expected_revision=before['revision'],confirm_inference=True,preserve_conflicts=True);receipt=self.engine.decide_model_proposal(self.pid,report['report']['id'],request);pending=self.service.get(self.pid);self.assertEqual(pending['document'],before['document']);self.assertEqual(len(pending['local_edit_proposals']),1);proposal=pending['local_edit_proposals'][0];self.assertEqual(proposal['model_proposal_id'],bridge['id']);self.assertEqual(receipt['local_proposal_id'],proposal['id']);self.assertEqual(proposal['chapter_id'],other)
        result=command(self.service,self.pid,'decide_edit',dict(operation_id=str(uuid4()),expected_revision=pending['revision'],proposal_id=proposal['id'],proposal_revision=1,decision='accepted',authorize_confirmed=False));self.assertIsNotNone(result['version_after']);self.assertEqual(self.service.get(self.pid)['memories'],before['memories'])
    def test_composite_memory_skill_graph_bridge_receipts_and_model_body_candidate_copy(self):
        from novel_writer.application.knowledge import command
        from novel_writer.storage.skills_repository import SkillsRepository
        from novel_writer.application.backups import create_backup,restore_backup
        from novel_writer.application.migrations import migrate
        self.save('add_chapter',title='第二侧');other=self.service.get(self.pid)['document']['chapters'][-1]['id'];self.save('save_chapter',chapter_id=other,content='第二侧实际正文，供作者判断桥段关联。')
        self.save('save_memory',kind='chapter_summary',title='作者已确认',text='literal '+self.cid,position_chapter_id=self.cid,source=dict(kind='chapter',entity_id=self.cid),confirmed=True);memory=self.service.get(self.pid)['memories'][0]
        skill=dict(id='s5c-global',name='全局参考',description='虚构资料',imported_at='2020-01-01T00:00:00+00:00',primary_path='SKILL.md',files=[dict(path='SKILL.md',content='C global literal '+self.cid)]);SkillsRepository(self.db).add(skill)
        state=self.service.get(self.pid);command(self.service,self.pid,'save_node',dict(operation_id=str(uuid4()),expected_revision=state['revision'],kind='foreshadow',label='人工伏笔',aliases=[],memory_ids=[memory['id']],position_chapter_id=self.cid,source=dict(kind='chapter',entity_id=self.cid),confirmed=True))
        def options():
            hit=self.service.search_local(self.pid,dict(query='C global',chapter_id=self.cid,scopes=['skills'],skill_ids=[skill['id']]))['hits'][0]
            return dict(chapter_id=self.cid,scope='through_current',budget_chars=4000,include_memories=True,memory_ids=[memory['id']],include_search_results=True,search_selections=[hit['selection']])
        def prepared(analysis):
            ctx=options();preview=self.service.preview_context(self.pid,ctx);changes=dict(context_options=ctx,context_sha256=digest(preview['context_text']))
            if analysis:params=request_rules();params['selected_chapter_ids']=[self.cid,other];changes['parameters']=params
            return self.prepare(analysis=analysis,**changes)
        self.mode='bridge';view=self.run_task(prepared(True));report=self.engine.model_review(self.pid,view['model_reports'][0]['id']);p=report['bridges'][0];receipt=self.engine.decide_model_proposal(self.pid,report['report']['id'],dict(decision_id=str(uuid4()),proposal_id=p['id'],decision='accepted',expected_revision=report['revision'],confirm_inference=True,preserve_conflicts=True));local=receipt['local_proposal_id']
        command(self.service,self.pid,'revise_edit',dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision'],proposal_id=local,mode='rewrite',replacement='作者修改 literal '+self.cid,reason='实际人工修订'))
        command(self.service,self.pid,'decide_edit',dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision'],proposal_id=local,proposal_revision=2,decision='accepted',authorize_confirmed=False))
        view=self.run_task(prepared(True));report=self.engine.model_review(self.pid,view['model_reports'][0]['id']);self.engine.decide_model_proposal(self.pid,report['report']['id'],dict(decision_id=str(uuid4()),proposal_id=report['bridges'][0]['id'],decision='rejected',expected_revision=report['revision'],confirm_inference=False,preserve_conflicts=False))
        self.mode='success';candidate_view=self.run_task(prepared(False));self.assertEqual(candidate_view['task']['status'],'succeeded');original=self.service.get(self.pid);package=self.root/'composite.nwbak';create_backup(self.db,package);restored=Path(restore_backup(package,self.root/'composite-restored')['database_path']);self.assertEqual(rows(restored),rows(self.db))
        target=self.root/'composite-target.sqlite3';SQLiteRepository(target);target_skills=SkillsRepository(target);different=json.loads(json.dumps(skill));different['files'][0]['content']='目标不同资料';target_skills.add(different);result=migrate(package,target,operation_id=str(uuid4()));pid=result['projects'][0]['new_id'];copy=NovelService(SQLiteRepository(target)).get(pid)
        self.assertEqual(len(copy['model_bridge_proposals']),2);self.assertEqual({r['decision'] for r in copy['model_proposal_receipts']},{'accepted','rejected'});self.assertEqual(len(copy['local_edit_proposals']),2);self.assertEqual(copy['generation_candidates'][0]['provenance'],'model_http_candidate');self.assertNotEqual(copy['generation_candidates'][0]['response_record_id'],original['generation_candidates'][0]['response_record_id'])
        model=next(t for t in copy['generation_tasks'] if t['task_type']=='rewrite_chapter');self.assertIn(self.cid,model['frozen']['parameters']['binding']['request_body']);self.assertNotEqual(model['chapter_id'],self.cid);self.assertEqual({d['kind'] for d in model['frozen']['dependencies']} & {'memory','skill'},{'memory','skill'});self.assertEqual(len(self.calls),3)
    def test_accepted_multisource_model_memory_expires_when_nonprimary_quote_changes(self):
        from novel_writer.domain.tasks import capture_dependency
        self.save('add_chapter',title='主出处');other=self.service.get(self.pid)['document']['chapters'][-1]['id'];self.save('save_chapter',chapter_id=other,content='主出处已保存的另一段正文。');params=request_rules();params['selected_chapter_ids']=[self.cid,other];self.mode='analysis_multi';view=self.run_task(self.prepare(analysis=True,parameters=params));self.assertEqual(view['task']['status'],'succeeded',view);report=self.engine.model_review(self.pid,view['model_reports'][0]['id']);p=report['proposals'][0];receipt=self.engine.decide_model_proposal(self.pid,report['report']['id'],dict(decision_id=str(uuid4()),proposal_id=p['id'],decision='accepted',expected_revision=report['revision'],confirm_inference=True,preserve_conflicts=True));state=self.service.get(self.pid);memory=next(m for m in state['memories'] if m['id']==receipt['memory_id']);self.assertEqual(memory['source']['entity_id'],other);self.assertFalse(self.service.memory_records(self.pid)[0]['outdated'])
        self.save('save_chapter',chapter_id=self.cid,content='非主出处被作者改动');before=rows(self.db);records=self.service.memory_records(self.pid);self.assertTrue(records[0]['confirmed']);self.assertTrue(records[0]['outdated'],'不能仅跟随主出处而把多引文模型记忆当新鲜事实');self.assertFalse(capture_dependency(self.service.get(self.pid),'memory',memory['id']).memory_fresh);self.assertEqual(rows(self.db),before)

if __name__=='__main__':unittest.main()
