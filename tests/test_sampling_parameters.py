"""Sampling is frozen, versioned, and actually sent to fictional loopback servers."""
import json,threading,time
import unittest
from types import SimpleNamespace
from uuid import uuid4
from test_custom_providers import CustomProviderTests,wire
from test_creation_presets import CreationPresetTests
from novel_writer.domain.sampling import canonical
from novel_writer.domain.tasks import encode,parse
from novel_writer.domain.creation_presets import StepBinding
from novel_writer.application.task_protocol import CancellationToken
from novel_writer.application.custom_protocols import request_payload,ConfiguredHttpTransport,normalized

class SamplingTaskLimitsTests(unittest.TestCase):
 from test_configured_tasks import ConfiguredTaskTests as _fixture
 setUp=_fixture.setUp
 save=_fixture.save
 prepare=_fixture.prepare
 def test_start_validation_does_not_consume_interval_before_the_actual_wire(self):
  with wire('openai-chat') as (url,calls):
   connection=self.save(url);self.providers.manage(id=connection['id'],action='limits',confirmed=True,min_interval_ms=60000,requests_per_minute=10)
   first=self.prepare(connection)['task'];b=first['frozen']['parameters']['binding'];self.engine.start(self.pid,first['id'],dict(confirm_external=True,request_sha256=b['request_sha256']));self.engine.wait_idle(5)
   self.assertEqual(self.engine.describe(self.pid,first['id'])['task']['status'],'succeeded');self.assertEqual(len(calls),1)
   second=self.prepare(connection)['task'];b=second['frozen']['parameters']['binding'];self.engine.start(self.pid,second['id'],dict(confirm_external=True,request_sha256=b['request_sha256']));self.engine.wait_idle(5)
   self.assertEqual(self.engine.describe(self.pid,second['id'])['task']['status'],'failed');self.assertEqual(len(calls),1)

class SamplingWireTests(CustomProviderTests):
 def test_declared_sampling_reaches_all_three_native_bodies(self):
  for protocol in ('openai-chat','anthropic-messages','gemini-content'):
   with self.subTest(protocol=protocol),wire(protocol) as (url,calls):
    c=self.save(url,protocol,allow_local=True);sampling=dict(top_p=.82,seed=None if protocol=='anthropic-messages' else 17,stop=['结束','END'])
    options=dict(connection_id=c['id'],model_id='fiction-model',temperature=.3,max_tokens=512,sampling=sampling)
    with self.assertRaises(ValueError):self.providers.validate_sampling(options)
    self.providers.manage(id=c['id'],action='sampling_support',confirmed=True,parameters=['top_p','stop']+([] if protocol=='anthropic-messages' else ['seed']))
    self.providers.validate_sampling(options)
    with self.assertRaises(ValueError):self.providers.validate_sampling(dict(options,model_id='other-model'))
    destination=self.providers.destination(c['id'],'fiction-model');saved=self.providers.generation_connection(c['id'],'fiction-model',enabled=True,confirmed=True,destination=destination)
    payload=request_payload(protocol,[dict(role='user',content='虚构')],options)
    response=ConfiguredHttpTransport().send(SimpleNamespace(request_body=json.dumps(payload)),saved,CancellationToken(threading.Event(),time.monotonic()+3),1000)
    self.assertTrue(response.complete);self.assertEqual(len(calls),1);body=calls[0]['body'];target=body.get('generationConfig',body)
    self.assertEqual(target['topP' if protocol=='gemini-content' else 'top_p'],.82)
    self.assertEqual(target['stopSequences' if protocol=='gemini-content' else 'stop_sequences' if protocol=='anthropic-messages' else 'stop'],['结束','END'])
    if protocol=='anthropic-messages':self.assertNotIn('temperature',body);self.assertNotIn('seed',body)
    else:self.assertEqual(target['seed'],17)
    self.providers.manage(id=c['id'],action='disable',confirmed=True)
    with self.assertRaises(ValueError):self.providers.validate_sampling(options)
    with self.assertRaises(ValueError):self.providers.generation_connection(c['id'],'fiction-model',enabled=True,confirmed=True,destination=destination)
    self.assertEqual(len(calls),1)
 def test_validation_legacy_encoding_and_native_stop(self):
  for changes in [dict(top_p=10**1000),dict(top_p=float('nan')),dict(top_p=True),dict(seed=True),dict(seed=2**31),dict(stop=['']),dict(stop=['x']*5)]:
   with self.subTest(changes=changes),self.assertRaises(ValueError):canonical(dict(top_p=.5,seed=None,stop=[],**{})|changes)
  old=dict(step='draft',adapter_id='configured-http-v2',connection_id=str(uuid4()),model_id='fiction-model',temperature=.3,max_tokens=512,budget_limit=1.,allow_unknown_cost=True)
  self.assertEqual(encode(parse(StepBinding,old)),old)
  with self.assertRaises(ValueError):parse(StepBinding,dict(old,sampling=None))
  native=normalized(dict(role='assistant',content=[dict(type='text',text='done')],stop_reason='stop_sequence',usage={}), 'anthropic-messages')
  self.assertEqual(native['choices'][0]['finish_reason'],'stop')

class SamplingPersistenceTests(CreationPresetTests):
 def test_v28_reopen_backup_restore_copy_and_portable_format(self):
  from novel_writer.application.backups import create_backup,restore_backup
  from novel_writer.application.migrations import migrate
  from novel_writer.application.skill_import import SkillLibrary
  from novel_writer.application.service import NovelService
  from novel_writer.storage.sqlite_repository import SQLiteRepository
  settings=self.settings();settings['steps'][0]['sampling']=dict(top_p=.8,seed=19,stop=['END'])
  first=self.save(settings=settings);state=self.service.get(self.pid);self.assertEqual(state['workspace_version'],28)
  public=self.engine.export(self.pid,first['version_id']);self.assertEqual(public['creation_preset_format'],2)
  with self.assertRaises(ValueError):self.engine.import_preset(self.other,dict(operation_id=str(uuid4()),preset=dict(public,creation_preset_format=1),expected_revision=self.service.get(self.other)['revision']))
  self.assertEqual(NovelService(SQLiteRepository(self.db)).get(self.pid),state)
  SkillLibrary(self.db);package=self.db.parent/'sampling.nwbak';self.assertEqual(create_backup(self.db,package)['backup_format_version'],51)
  restored=restore_backup(package,self.db.parent/'restored-sampling');self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid),state)
  target=self.db.parent/'sampling-copy.sqlite3';SQLiteRepository(target);SkillLibrary(target);result=migrate(package,target,operation_id=str(uuid4()),project_ids=[self.pid]);clone=NovelService(SQLiteRepository(target)).get(result['projects'][0]['new_id'])
  self.assertEqual(clone['creation_presets'][0]['settings'],settings)
