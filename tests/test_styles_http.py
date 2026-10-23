import base64,json,unittest
from uuid import uuid4
from test_book_ai_http import BookAIHttpTests
from test_book_ai import supplier
from test_styles import FEATURES,output

class StyleHttpTests(BookAIHttpTests):
 def test_material_and_manual_card_have_token_boundary_and_no_model_requirement(self):
  payload=dict(operation_id=str(uuid4()),kind='article',name='fiction.txt',encoding='auto',origin='虚构文章',data_base64=base64.b64encode('原文保持。'.encode()).decode());url='/api/projects/'+self.pid+'/styles'
  self.assertEqual(self.request('POST',url+'/import-source',payload,token=False)[0],403);code,source=self.request('POST',url+'/import-source',payload);self.assertEqual(code,201,source);code,detail=self.request('GET',url+'/sources/'+source['id']);self.assertEqual(code,200);self.assertEqual(detail['text'],'原文保持。');self.assertTrue(detail['readonly']);card=dict(operation_id=str(uuid4()),style_id=None,name='手动风格卡',prompt='直接描写动作。',card=FEATURES,analysis_id=None,confirmed=True);code,saved=self.request('POST',url+'/save-card',card);self.assertEqual(code,201,saved);self.assertEqual(self.request('POST',url+'/choose',dict(operation_id=str(uuid4()),chapter_id=None,version_id=saved['id'],confirmed=True))[0],200);self.assertEqual(self.server.service.get(self.pid)['document']['chapters'],[])
 def test_style_analysis_request_is_separate_and_unknown_options_cannot_grant_tools(self):
  with supplier(output=output(0,5)) as wire:
   base='/api/projects/'+self.pid+'/styles';payload=dict(operation_id=str(uuid4()),kind='article',name='tiny.txt',encoding='utf-8',origin='虚构资料',data_base64=base64.b64encode('虚构文章。'.encode()).decode());source=self.request('POST',base+'/import-source',payload)[1];connection=self.server.providers.save_custom(id=str(uuid4()),name='style HTTP',base_url=wire['url'],protocol='openai-chat',model_id='fiction',api_key='fiction-style-http-key',allow_local=True);request=dict(operation_id=str(uuid4()),source_id=source['id'],start=0,end=5,chunk_chars=2000,model_options=dict(adapter_id='configured-http-v2',connection_id=connection['id'],model_id='fiction',temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=True,prompt_version='rewrite-1'),max_calls=1,max_output_tokens=512);bad=json.loads(json.dumps(request));bad['model_options']['tool_url']='http://bad.example';self.assertEqual(self.request('POST',base+'/create-analysis',bad)[0],422);code,analysis=self.request('POST',base+'/create-analysis',request);self.assertEqual(code,201,analysis);code,prepared=self.request('POST',base+'/prepare-next',dict(operation_id=str(uuid4()),analysis_id=analysis['id']));self.assertEqual(code,201,prepared);self.assertEqual(len(wire['calls']),0);task=prepared['request'];self.assertEqual(self.request('POST',base+'/requests/'+task['id']+'/execute',dict(confirm_external=True,request_sha256=task['request_sha256']))[0],200);self.server.task_coordinator.wait_idle(5);view=self.request('GET',base+'/analyses/'+analysis['id'])[1];self.assertEqual(view['covered_chars'],5);self.assertEqual(len(wire['calls']),1)

for _name in list(BookAIHttpTests.__dict__):
 if _name.startswith('test_') and _name not in StyleHttpTests.__dict__:setattr(StyleHttpTests,_name,None)
if __name__=='__main__':unittest.main()
