"""The dedicated summary route retains authentication and shared review gates."""
from uuid import uuid4
import unittest
import test_chapter_writing_http as fixtures
from test_semantic_summaries import summary_wire

class SummaryHttpTests(unittest.TestCase):
    setUp=fixtures.ChapterWritingHttpTests.setUp
    stop=fixtures.ChapterWritingHttpTests.stop
    request=fixtures.ChapterWritingHttpTests.request

    def test_summary_route_auth_strict_prepare_execute_and_manual_accept(self):
        with summary_wire() as wire:
            code,state=self.request('POST',self.base+'/actions',dict(action='save_chapter',fields=dict(chapter_id=self.cid,content='本章🙂只读来源。'),expected_revision=self.request('GET',self.base)[1]['revision']))
            self.assertEqual(code,200,state)
            c=self.server.providers.save_custom(id=str(uuid4()),name='虚构摘要HTTP',base_url=wire['url'],protocol='openai-chat',model_id='fiction-model',api_key='fiction-summary-http-key',allow_local=True)
            payload=dict(request_id=str(uuid4()),chapter_id=self.cid,expected_revision=state['revision'],instruction='只摘要已保存本章',max_output_chars=10000,timeout_ms=3000,model_options=dict(adapter_id='configured-http-v2',connection_id=c['id'],model_id=c['model_id'],temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=True,prompt_version='chapter-summary-json-1'))
            route=self.base+'/model-summaries/prepare'
            self.assertEqual(self.request('POST',route,payload,token=False)[0],403)
            self.assertEqual(self.request('POST',route,dict(payload,source='伪造来源'))[0],422)
            self.assertEqual(self.request('GET',self.base)[1],state)
            code,result=self.request('POST',route,payload);self.assertEqual(code,201,result);task=result['task'];self.assertEqual(wire['calls'],[])
            task_route=self.base+'/tasks/'+task['id'];permission=dict(confirm_external=True,request_sha256=task['frozen']['parameters']['binding']['request_sha256'])
            self.assertEqual(self.request('POST',task_route+'/execute',dict(permission,request_sha256='0'*64))[0],422)
            self.assertEqual(wire['calls'],[]);self.assertEqual(self.request('POST',task_route+'/execute',permission)[0],202);self.server.task_coordinator.wait_idle(5)
            done=self.request('GET',task_route)[1];self.assertEqual(done['task']['status'],'succeeded',done);self.assertEqual(done['candidates'],[])
            report_route=self.base+'/model-reviews/'+done['model_reports'][0]['id'];detail=self.request('GET',report_route)[1];p=detail['proposals'][0]
            self.assertEqual(self.request('GET',self.base)[1]['memories'],[])
            decision=dict(decision_id=str(uuid4()),proposal_id=p['id'],decision='accepted',expected_revision=detail['revision'],confirm_inference=False,preserve_conflicts=True)
            self.assertEqual(self.request('POST',report_route+'/proposal',decision)[0],422)
            decision['confirm_inference']=True;code,receipt=self.request('POST',report_route+'/proposal',decision);self.assertEqual(code,200,receipt);self.assertEqual(self.request('POST',report_route+'/proposal',decision),(200,receipt))
            after=self.request('GET',self.base)[1];self.assertEqual(after['document'],state['document']);self.assertEqual(len(after['memories']),1);self.assertEqual(after.get('memory_rollups',[]),[]);self.assertEqual(len(wire['calls']),1)

if __name__=='__main__':unittest.main()
