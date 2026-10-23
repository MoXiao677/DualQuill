import json,unittest
from uuid import uuid4
from test_styles_http import StyleHttpTests
from test_book_ai_http import BookAIHttpTests
from test_book_ai import supplier
from test_style_trials import TrialTests
from test_styles import FEATURES

class TrialHttpTests(StyleHttpTests):
 def options(self,connection):return dict(adapter_id='configured-http-v2',connection_id=connection['id'],model_id='fiction-trial',temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=True,prompt_version='rewrite-1')
 def seed(self):return TrialTests.seed_options(self)
 def test_single_trial_has_explicit_request_permission_and_never_uses_chapter_adoption(self):
  base='/api/projects/'+self.pid+'/style-trials';seed=self.seed();code,preview=self.request('POST',base+'/preview',seed);self.assertEqual(code,200,preview)
  with supplier(output='HTTP试写短段。') as wire:
   connection=self.server.providers.save_custom(id=str(uuid4()),name='虚构试写',base_url=wire['url'],protocol='openai-chat',model_id='fiction-trial',api_key='fiction-trial-http-key',allow_local=True);body=dict(operation_id=str(uuid4()),seed_options=seed,seed_sha256=preview['seed']['seed_sha256'],style_mode='baseline',style_version_id=None,model_options=self.options(connection),max_calls=1,max_output_tokens=512,timeout_ms=2000,retry_of=None);self.assertEqual(self.request('POST',base+'/prepare',body,token=False)[0],403);code,prepared=self.request('POST',base+'/prepare',body);self.assertEqual(code,201,prepared);self.assertEqual(wire['calls'],[]);task=prepared['task'];self.assertEqual(self.request('POST',base+'/'+task['id']+'/execute',dict(confirm_external=True,request_sha256='0'*64))[0],422);self.assertEqual(wire['calls'],[]);self.assertEqual(self.request('POST',base+'/'+task['id']+'/execute',dict(confirm_external=True,request_sha256=task['request_sha256']))[0],200);self.server.task_coordinator.wait_idle(4);done=self.request('GET',base+'/'+task['id'])[1];self.assertIsNotNone(done['candidate']);self.assertEqual(self.server.service.get(self.pid)['document']['chapters'],[]);self.assertEqual(self.request('POST','/api/projects/'+self.pid+'/tasks/'+task['id']+'/adopt',dict(candidate_id=done['candidate']['id'],adoption_id=str(uuid4()),expected_revision=self.server.service.get(self.pid)['revision'],authorize_confirmed=False))[0],422)
 def test_arena_trials_hide_bindings_from_workspace_lists_and_direct_detail_until_reveal(self):
  base='/api/projects/'+self.pid+'/style-trials';seed=self.seed();code,preview=self.request('POST',base+'/preview',seed);self.assertEqual(code,200,preview)
  with supplier(output='盲评短段。') as wire:
   c=self.server.providers.save_custom(id=str(uuid4()),name='虚构盲评',base_url=wire['url'],protocol='openai-chat',model_id='fiction-trial',api_key='fiction-trial-http-key',allow_local=True);profile=dict(style_mode='baseline',style_version_id=None,model_options=self.options(c));payload=dict(experiment_id=str(uuid4()),title='试写盲评',seed_options=seed,seed_sha256=preview['seed']['seed_sha256'],profiles=[profile,profile],max_calls=2,max_output_tokens=1024,timeout_ms=2000);code,created=self.request('POST',base+'/compare',payload);self.assertEqual(code,201,created);state=self.server.service.get(self.pid);task=state['style_trial_tasks'][0];self.assertEqual(self.request('GET',base+'/'+task['id'])[0],422);workspace=self.request('GET','/api/projects/'+self.pid)[1];self.assertEqual(workspace['style_trial_tasks'],[]);listing=self.request('GET',base)[1];self.assertEqual(listing['tasks'],[]);self.assertEqual(self.request('POST',base+'/'+task['id']+'/execute',dict(confirm_external=True,request_sha256=task['request_sha256']))[0],422);self.assertNotIn(task['request_sha256'],json.dumps(workspace));self.assertEqual(wire['calls'],[])

for parent in (StyleHttpTests,BookAIHttpTests):
 for name in parent.__dict__:
  if name.startswith('test_') and name not in TrialHttpTests.__dict__:setattr(TrialHttpTests,name,None)
if __name__=='__main__':unittest.main()
