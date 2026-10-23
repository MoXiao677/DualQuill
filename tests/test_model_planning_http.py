"""Actual loopback HTTP, session token/error codes and model-to-review flow."""
import json
import unittest
from uuid import uuid4
import test_full_book_planning_http as http_helpers
import test_model_planning as model_helpers


class ModelPlanningHTTPTests(unittest.TestCase):
    stop=http_helpers.FullBookPlanningHTTPTests.stop
    request=http_helpers.FullBookPlanningHTTPTests.request
    revision=http_helpers.FullBookPlanningHTTPTests.revision

    def setUp(self):
        http_helpers.FullBookPlanningHTTPTests.setUp(self)
        self.server.service.execute(self.pid,'save_chapter',dict(chapter_id=self.c1,title='虚构正文',content='😀林默交出旧钥匙。',status='draft'),expected_revision=self.revision())
        self.server.providers.offline=False;self.server.model_planning.adapter.enabled=True;self.server.model_generation_enabled=True
        self.base=f'/api/projects/{self.pid}/model-planning'

    def source(self):return dict(chapter_id=self.c1,character_ids=[self.character],instruction='只核对虚构正文',context_budget_chars=100000)

    def prepared(self,wire):
        c=self.server.providers.save_custom(id=str(uuid4()),name='HTTP虚构模型',base_url=wire['url'],protocol='openai-chat',model_id='fiction-selected',api_key='fiction-body-key',allow_local=True)
        code,preview=self.request('POST',self.base+'/preview',self.source());self.assertEqual(code,200)
        payload=dict(operation_id=str(uuid4()),expected_revision=preview['revision'],source_options=self.source(),source_sha256=preview['source_sha256'],
            model_options=dict(adapter_id='configured-http-v2',connection_id=c['id'],model_id='fiction-selected',temperature=.3,max_tokens=512,budget_limit=1.,allow_unknown_cost=True,prompt_version='rewrite-1'),
            budget=dict(max_external_calls=10,max_reserved_output_tokens=81920),max_output_chars=20000,timeout_ms=2000)
        code,prepared=self.request('POST',self.base+'/prepare',payload);self.assertEqual(code,200,prepared)
        self.assertEqual(self.request('POST',self.base+'/prepare',payload)[1]['task'],prepared['task'])
        return prepared

    def confirm(self,prepared):
        t=prepared['task'];return dict(confirm_external=True,request_sha256=t['binding']['request_sha256'],budget_sha256=t['budget_sha256'],expected_revision=prepared['revision'])

    def test_actual_http_source_freeze_execute_single_transfer_then_independent_accept(self):
        quote='林默交出旧钥匙。';output=json.dumps(dict(suggestions=[dict(reason='虚构建议待核实',start=1,end=1+len(quote),quote=quote,actions=[dict(action='create_event',values=dict(title='交出钥匙',planned_chapter_id=self.c1))])]),ensure_ascii=False)
        with model_helpers.model_wire(output) as wire:
            prepared=self.prepared(wire);t=prepared['task'];self.assertEqual(wire['calls'],[])
            code,_=self.request('POST',self.base+'/'+t['id']+'/execute',self.confirm(prepared));self.assertEqual(code,200)
            self.server.task_coordinator.wait_idle(5)
            code,view=self.request('GET',self.base+'/'+t['id']);self.assertEqual(code,200);self.assertEqual(view['status'],'succeeded')
            self.assertEqual(self.server.service.get(self.pid)['key_events'],[])
            c=view['candidates'][0];selection=dict(candidate_id=c['id'],candidate_sha256=c['data_sha256'],suggestion_index=0)
            code,preview=self.request('POST',self.base+'/transfer-preview',selection);self.assertEqual(code,200)
            code,link=self.request('POST',self.base+'/propose',dict(operation_id=str(uuid4()),expected_revision=preview['revision'],**selection,transfer_token=preview['transfer_token'],confirmed=True));self.assertEqual(code,200)
            self.assertEqual(self.server.service.get(self.pid)['key_events'],[])
            body=f'/api/projects/{self.pid}/body-planning';code,impact=self.request('POST',body+'/preview',dict(proposal_id=link['proposal_id']));self.assertEqual(code,200)
            code,receipt=self.request('POST',body+'/decide',dict(operation_id=str(uuid4()),expected_revision=self.revision(),proposal_id=link['proposal_id'],decision='accepted',preview_sha256=impact['preview_sha256']));self.assertEqual(code,200,receipt)
            self.assertEqual(self.server.service.get(self.pid)['key_events'][0]['title'],'交出钥匙')
            self.assertEqual(len(wire['calls']),1)
            self.assertEqual(wire['calls'][0]['raw'],t['binding']['request_body'])

    def test_token_not_found_cross_book_and_strict_fields_have_zero_state_changes(self):
        before=self.server.service.get(self.pid)
        self.assertEqual(self.request('POST',self.base+'/preview',self.source(),token=False)[0],403)
        self.assertEqual(self.request('POST',self.base+'/preview',dict(self.source(),unknown=True))[0],422)
        self.assertEqual(self.request('GET',self.base+'/'+str(uuid4()))[0],404)
        other=self.server.service.create(title='另一本虚构书')['document']['project']['id']
        with model_helpers.model_wire('{}') as wire:
            prepared=self.prepared(wire);t=prepared['task'];saved=self.server.service.get(self.pid)
            self.assertEqual(self.request('GET',self.base.replace(self.pid,other)+'/'+t['id'])[0],404)
            self.assertEqual(self.request('POST',self.base+'/'+t['id']+'/execute',dict(self.confirm(prepared),expected_revision=1))[0],409)
            self.assertEqual(self.request('POST',self.base+'/'+t['id']+'/execute',dict(self.confirm(prepared),budget_sha256='0'*64))[0],422)
            self.assertEqual(self.request('POST',self.base+'/'+t['id']+'/execute',dict(self.confirm(prepared),unknown=True))[0],422)
            self.assertEqual(saved,self.server.service.get(self.pid));self.assertEqual(wire['calls'],[])
        self.assertEqual(before['document'],self.server.service.get(self.pid)['document'])

    def test_disabled_session_and_static_security_mapping_are_honest(self):
        self.server.model_planning.adapter.enabled=False;self.server.model_generation_enabled=False
        code,listing=self.request('GET',f'/api/projects/{self.pid}/full-book-planning')
        self.assertEqual(code,200);self.assertEqual(listing['ai_completion']['status'],'native_model_session_disabled')
        self.assertFalse(listing['model_planning']['enabled'])
        code,script=self.request('GET','/model_planning.js',parse=False);self.assertEqual(code,200)
        self.assertIn('budget_sha256',script.decode('utf-8'))
        from pathlib import Path
        security=(Path(__file__).resolve().parents[1]/'desktop/security.cjs').read_text(encoding='utf-8')
        self.assertIn("'/model_planning.js':'model_planning.js'",security)


if __name__=='__main__':unittest.main()
