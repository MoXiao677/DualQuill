"""Explicit native contracts, exercised against rejecting loopback providers only."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json,threading,unittest
from uuid import uuid4
import test_configured_tasks as fixtures
from novel_writer.domain.sampling import canonical

@contextmanager
def strict_wire(protocol):
 calls=[]
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def do_POST(self):
   body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append(body)
   target=body.get('generationConfig',body)
   valid='temperature' not in target and (protocol!='openai-chat' or 'max_completion_tokens' in body and 'max_tokens' not in body)
   if protocol=='openai-chat':payload=dict(id='fiction',choices=[dict(message=dict(role='assistant',content='严格原生候选'),finish_reason='stop')])
   elif protocol=='anthropic-messages':payload=dict(id='fiction',role='assistant',content=[dict(type='text',text='严格原生候选')],stop_reason='end_turn')
   else:payload=dict(candidates=[dict(content=dict(role='model',parts=[dict(text='严格原生候选')]),finishReason='STOP')])
   raw=json.dumps(payload if valid else dict(error='unsupported native fields'),ensure_ascii=False).encode()
   self.send_response(200 if valid else 400);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
 try:yield 'http://127.0.0.1:'+str(server.server_port)+'/v1',calls
 finally:server.shutdown();server.server_close();worker.join(2)

class NativeRequestProfileTests(unittest.TestCase):
 setUp=fixtures.ConfiguredTaskTests.setUp
 save=fixtures.ConfiguredTaskTests.save
 prepare=fixtures.ConfiguredTaskTests.prepare
 def profile(self,c,protocol):
  return self.providers.manage(id=c['id'],action='request_profile',confirmed=True,temperature_mode='omit',chat_token_field='max_completion_tokens' if protocol=='openai-chat' else 'max_tokens')
 def test_strict_three_protocol_tasks_freeze_and_send_exact_profile(self):
  for protocol in ('openai-chat','anthropic-messages','gemini-content'):
   with self.subTest(protocol=protocol),strict_wire(protocol) as (url,calls):
    c=self.save(url,protocol);self.profile(c,protocol);task=self.prepare(c)['task'];binding=task['frozen']['parameters']['binding'];body=json.loads(binding['request_body']);target=body.get('generationConfig',body)
    self.assertNotIn('temperature',target);self.assertEqual(binding['sampling']['temperature_mode'],'omit');self.assertEqual(calls,[])
    if protocol=='openai-chat':self.assertEqual(body['max_completion_tokens'],512);self.assertNotIn('max_tokens',body)
    self.assertEqual(self.service.get(self.pid)['workspace_version'],29)
    self.engine.start(self.pid,task['id'],dict(confirm_external=True,request_sha256=binding['request_sha256']));self.engine.wait_idle(5)
    self.assertEqual(self.engine.describe(self.pid,task['id'])['task']['status'],'succeeded');self.assertEqual(calls,[body]);self.assertEqual(self.service.get(self.pid)['document']['chapters'][0]['content'],'作者保存的虚构原稿。')
 def test_changed_profile_invalidates_old_permission_without_rewriting_frozen_bytes(self):
  with strict_wire('openai-chat') as (url,calls):
   c=self.save(url);old=self.prepare(c)['task'];b=old['frozen']['parameters']['binding'];self.profile(c,'openai-chat')
   with self.assertRaises(ValueError):self.engine.start(self.pid,old['id'],dict(confirm_external=True,request_sha256=b['request_sha256']))
   self.assertEqual(self.engine.describe(self.pid,old['id'])['task']['frozen']['parameters']['binding'],b);self.assertEqual(calls,[])
   with self.assertRaises(ValueError):self.providers.validate_sampling(dict(connection_id=c['id'],model_id='other-model'))
   fresh=self.prepare(c)['task'];self.assertNotEqual(fresh['frozen']['parameters']['binding']['request_sha256'],b['request_sha256'])
 def test_explicit_sampling_is_preserved_and_requires_support_declaration(self):
  from novel_writer.domain.connections import request_payload
  for protocol in ('openai-chat','anthropic-messages','gemini-content'):
   with self.subTest(protocol=protocol),strict_wire(protocol) as (url,calls):
    c=self.save(url,protocol);self.profile(c,protocol);options=dict(connection_id=c['id'],model_id='fiction-model',temperature=.7,max_tokens=512,sampling=dict(top_p=.999,seed=None,stop=['END']))
    with self.assertRaises(ValueError):self.providers.validate_sampling(options)
    self.providers.manage(id=c['id'],action='sampling_support',confirmed=True,parameters=['top_p','stop']);self.providers.validate_sampling(options)
    body=request_payload(protocol,[dict(role='user',content='虚构')],options);target=body.get('generationConfig',body)
    self.assertEqual(target['topP' if protocol=='gemini-content' else 'top_p'],.999);self.assertNotIn('temperature',target);self.assertEqual(calls,[])
    with self.assertRaises(ValueError):self.providers.validate_sampling(dict(options,sampling=dict(top_p=None,seed=None,stop=[],temperature_mode='configured')))
 def test_profile_v29_reopen_backup_restore_copy_and_legacy_encoding(self):
  from novel_writer.application.backups import create_backup,restore_backup
  from novel_writer.application.migrations import migrate
  from novel_writer.application.skill_import import SkillLibrary
  from novel_writer.application.service import NovelService
  from novel_writer.storage.sqlite_repository import SQLiteRepository,validate_workspace
  from copy import deepcopy
  with strict_wire('openai-chat') as (url,calls):
   c=self.save(url);self.profile(c,'openai-chat');task=self.prepare(c)['task'];state=self.service.get(self.pid)
   self.assertEqual(NovelService(SQLiteRepository(self.root/'fiction.sqlite3')).get(self.pid),state)
   old=deepcopy(state);old['workspace_version']=28
   with self.assertRaises(ValueError):validate_workspace(old)
   SkillLibrary(self.root/'fiction.sqlite3');package=self.root/'native.nwbak';self.assertEqual(create_backup(self.root/'fiction.sqlite3',package)['backup_format_version'],51)
   restored=restore_backup(package,self.root/'restored-native');self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid),state)
   target=self.root/'copy-native.sqlite3';SQLiteRepository(target);SkillLibrary(target);copied=migrate(package,target,operation_id=str(uuid4()));clone=NovelService(SQLiteRepository(target)).get(copied['projects'][0]['new_id']);self.assertEqual(clone['generation_tasks'][0]['frozen']['parameters']['binding']['request_body'],task['frozen']['parameters']['binding']['request_body']);self.assertEqual(calls,[])
  legacy=dict(top_p=.8,seed=None,stop=[]);self.assertEqual(canonical(legacy),legacy)
 def test_non_chat_token_field_and_invalid_profiles_are_rejected(self):
  c=self.save('http://127.0.0.1:9/v1','anthropic-messages')
  with self.assertRaises(ValueError):self.profile(c,'openai-chat')
  for changes in [dict(temperature_mode=None,chat_token_field='max_tokens'),dict(temperature_mode='omit',chat_token_field='both')]:
   with self.assertRaises(ValueError):self.providers.manage(id=c['id'],action='request_profile',confirmed=True,**changes)
 def test_messages_checks_temperature_range_only_when_transmitted(self):
  from novel_writer.domain.connections import request_payload
  options=dict(model_id='fiction-model',temperature=1.7,max_tokens=512)
  with self.assertRaises(ValueError):request_payload('anthropic-messages',[dict(role='user',content='虚构')],options)
  for value in [dict(top_p=None,seed=None,stop=[],temperature_mode='omit'),dict(top_p=.999,seed=None,stop=[])]:
   body=request_payload('anthropic-messages',[dict(role='user',content='虚构')],dict(options,sampling=value));self.assertNotIn('temperature',body)
 def test_comparison_profiles_match_effective_native_child_bindings(self):
  from novel_writer.application.comparisons import ComparisonCoordinator
  from novel_writer.domain.tasks import digest
  with strict_wire('openai-chat') as (left,_),strict_wire('gemini-content') as (right,_):
   connections=[self.save(left),self.save(right,'gemini-content')]
   for c,protocol in zip(connections,('openai-chat','gemini-content')):self.profile(c,protocol)
   state=self.service.get(self.pid);context=dict(chapter_id=self.cid,budget_chars=2000,include_writing_rules=True);preview=self.service.preview_context(self.pid,context)
   profiles=[dict(adapter_id='configured-http-v2',connection_id=c['id'],model_id='fiction-model',temperature=.3,max_tokens=512,budget_limit=1.,allow_unknown_cost=True,prompt_version='rewrite-1') for c in connections]
   ComparisonCoordinator(self.service,self.engine).create(self.pid,dict(experiment_id=str(uuid4()),title='原生配置比较',chapter_id=self.cid,context_options=context,context_sha256=digest(preview['context_text']),instruction='虚构',rubric='作者自评',parameters=dict(max_output_chars=1000,timeout_ms=3000),profiles=profiles,expected_revision=state['revision']))
   state=self.service.get(self.pid);self.assertEqual(state['workspace_version'],29)
   for p,t in zip(state['comparison_experiments'][0]['profiles'],state['generation_tasks']):self.assertEqual(p['sampling'],t['frozen']['parameters']['binding']['sampling'])

class NativePresetTests(unittest.TestCase):
 import test_creation_presets as _fixtures
 setUp=_fixtures.CreationPresetTests.setUp
 settings=_fixtures.CreationPresetTests.settings
 save=_fixtures.CreationPresetTests.save
 def test_native_preset_requires_share_format_three_and_roundtrips(self):
  from copy import deepcopy
  values=self.settings();native=dict(top_p=None,seed=None,stop=[],temperature_mode='omit',chat_token_field='max_completion_tokens');values['steps'][0]['sampling']=native
  created=self.save(settings=values);public=self.engine.export(self.pid,created['version_id']);self.assertEqual(public['creation_preset_format'],3);self.assertEqual(self.service.get(self.pid)['workspace_version'],29)
  for format in (1,2):
   old=deepcopy(public);old['creation_preset_format']=format
   with self.assertRaises(ValueError):self.engine.import_preset(self.other,dict(operation_id=str(uuid4()),preset=old,expected_revision=self.service.get(self.other)['revision']))
  self.engine.import_preset(self.other,dict(operation_id=str(uuid4()),preset=public,expected_revision=self.service.get(self.other)['revision']));self.assertEqual(self.service.get(self.other)['creation_presets'][0]['settings']['steps'][0]['sampling'],native)
