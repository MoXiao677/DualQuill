import unittest
from uuid import uuid4
from test_styles_http import StyleHttpTests
from test_public_search import search_wire

class SearchHttpTests(StyleHttpTests):
 def test_search_prepare_and_execute_are_distinct_token_bound_and_query_only(self):
  with search_wire() as wire:
   base='/api/projects/'+self.pid+'/public-search';connection=self.server.providers.save_custom(id=str(uuid4()),name='虚构搜索',base_url=wire['url'],protocol='gemini-content',model_id='fiction',api_key='fiction-grounding-http-key',allow_local=True);payload=dict(operation_id=str(uuid4()),title='虚构雾港',platform='虚构平台',author='林某',model_options=dict(adapter_id='configured-http-v2',connection_id=connection['id'],model_id='fiction',temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=True,prompt_version='rewrite-1'),max_calls=2,max_output_tokens=1024);self.assertEqual(self.request('POST',base+'/prepare',payload,token=False)[0],403);code,prepared=self.request('POST',base+'/prepare',payload);self.assertEqual(code,201,prepared);self.assertEqual(wire['calls'],[]);query=prepared['query'];self.assertEqual(self.request('POST',base+'/queries/'+query['id']+'/execute',dict(confirm_external=True,request_sha256=query['request_sha256']))[0],200);self.server.task_coordinator.wait_idle(5);done=self.request('GET',base+'/queries/'+query['id'])[1];self.assertEqual(len(done['sources']),1);self.assertEqual(len(wire['calls']),1);identity=dict(operation_id=str(uuid4()),query_id=query['id'],source_id=done['sources'][0]['id'],confirmed=False);self.assertEqual(self.request('POST',base+'/choose-identity',identity)[0],422);identity['confirmed']=True;code,selected=self.request('POST',base+'/choose-identity',identity);self.assertEqual(code,201);self.assertEqual(self.request('POST',base+'/prepare-read',dict(operation_id=str(uuid4()),identity_id=selected['id'],url='http://127.0.0.1/attack'))[0],422)
 def test_public_reader_and_search_widget_do_not_inherit_arbitrary_tool_fields(self):
  base='/api/projects/'+self.pid+'/public-search';self.assertEqual(self.request('POST',base+'/prepare-read',dict(operation_id=str(uuid4()),url='file:///secret'))[0],422);self.assertEqual(self.request('GET',base+'/reads/missing')[0],404)

for parent in (StyleHttpTests,__import__('test_book_ai_http').BookAIHttpTests):
 for name in parent.__dict__:
  if name.startswith('test_') and name not in SearchHttpTests.__dict__:setattr(SearchHttpTests,name,None)
if __name__=='__main__':unittest.main()
