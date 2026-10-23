"""Configured providers use the original task/candidate/permission pipeline."""
from importlib import import_module
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4
from test_custom_providers import wire
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository
from novel_writer.application.provider_connections import ProviderConnections
from novel_writer.application.tasks import TaskCoordinator
from novel_writer.application.task_protocol import AdapterRegistry
from novel_writer.domain.tasks import digest

class ConfiguredTaskTests(unittest.TestCase):
    def setUp(self):
        self.api=import_module('novel_writer.application.custom_protocols')
        self.assertTrue(callable(getattr(self.api,'ConfiguredHttpAdapter',None)),'configured destination is not wired into the shared task registry')
        self.temp=tempfile.TemporaryDirectory(prefix='novel-configured-task-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.service=NovelService(SQLiteRepository(self.root/'fiction.sqlite3'))
        state=self.service.create(title='自建协议虚构小说');self.pid=state['document']['project']['id']
        state=self.service.execute(self.pid,'add_chapter',dict(title='虚构正文'),expected_revision=state['revision']);self.cid=state['document']['chapters'][0]['id']
        self.service.execute(self.pid,'save_chapter',dict(chapter_id=self.cid,content='作者保存的虚构原稿。'),expected_revision=state['revision'])
        self.providers=ProviderConnections(self.root/'fiction.dpapi');self.adapter=self.api.ConfiguredHttpAdapter(self.providers,enabled=True)
        registry=AdapterRegistry();registry.register('rewrite_chapter',self.adapter);registry.register('audit_chapter',self.adapter)
        self.engine=TaskCoordinator(self.service,registry);self.addCleanup(self.engine.close)
    def save(self,endpoint,protocol='openai-chat',identifier=None):
        return self.providers.save_custom(id=identifier or str(uuid4()),name='虚构配置',base_url=endpoint,protocol=protocol,model_id='fiction-model',api_key='fiction-configured-key',allow_local=True)
    def prepare(self,connection):
        state=self.service.get(self.pid);options=dict(chapter_id=self.cid,budget_chars=2000);preview=self.service.preview_context(self.pid,options)
        return self.engine.prepare(self.pid,dict(request_id=str(uuid4()),chapter_id=self.cid,task_type='rewrite_chapter',context_options=options,context_sha256=digest(preview['context_text']),parameters=dict(instruction='只准备虚构候选',max_output_chars=1000,timeout_ms=3000),expected_revision=state['revision'],model_options=dict(adapter_id='configured-http-v2',connection_id=connection['id'],model_id='fiction-model',temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=True,prompt_version='rewrite-1')))
    def test_native_protocols_produce_candidates_without_automatic_body_adoption(self):
        for protocol in ['openai-chat','anthropic-messages','gemini-content']:
            with self.subTest(protocol=protocol),wire(protocol) as (endpoint,calls):
                saved=self.save(endpoint,protocol);task=self.prepare(saved)['task'];binding=task['frozen']['parameters']['binding']
                self.assertEqual(calls,[]);self.assertEqual(binding['destination']['protocol'],protocol);self.assertEqual(binding['destination']['base_url'],endpoint)
                self.assertNotIn('fiction-configured-key',json.dumps(task));self.assertEqual(self.service.get(self.pid)['workspace_version'],9)
                with self.assertRaises(ValueError):self.engine.start(self.pid,task['id'],dict(confirm_external=True,request_sha256='0'*64))
                self.engine.start(self.pid,task['id'],dict(confirm_external=True,request_sha256=binding['request_sha256']));self.engine.wait_idle(6)
                result=self.engine.describe(self.pid,task['id']);self.assertEqual(result['task']['status'],'succeeded',result['task'].get('error_code'));self.assertEqual(len(calls),1)
                self.assertEqual(self.service.get(self.pid)['document']['chapters'][0]['content'],'作者保存的虚构原稿。')
    def test_replacing_url_under_same_saved_id_rejects_old_task_before_new_destination_call(self):
        with wire('openai-chat') as (first,old_calls),wire('openai-chat') as (second,new_calls):
            saved=self.save(first);task=self.prepare(saved)['task'];old_body=task['frozen']['parameters']['binding']['request_body'];binding=task['frozen']['parameters']['binding']
            self.save(second,identifier=saved['id'])
            with self.assertRaises(ValueError):self.engine.start(self.pid,task['id'],dict(confirm_external=True,request_sha256=binding['request_sha256']))
            self.assertEqual(old_calls,[]);self.assertEqual(new_calls,[]);self.assertEqual(self.engine.describe(self.pid,task['id'])['task']['frozen']['parameters']['binding']['request_body'],old_body)
            refreshed=self.prepare(saved)['task'];fresh=refreshed['frozen']['parameters']['binding'];self.assertNotEqual(fresh['request_sha256'],binding['request_sha256'])
            with self.assertRaises(ValueError):self.engine.start(self.pid,refreshed['id'],dict(confirm_external=True,request_sha256=binding['request_sha256']))
            self.assertEqual(new_calls,[])
    def test_configured_task_keeps_newer_creation_preferences_and_complete_copy(self):
        from novel_writer.application.creation_presets import CreationPresets
        from novel_writer.application.backups import create_backup,restore_backup
        from novel_writer.application.migrations import migrate
        from novel_writer.application.skill_import import SkillLibrary
        with wire('openai-chat') as (endpoint,calls):
            saved=self.save(endpoint);before=self.service.get(self.pid)
            CreationPresets(self.service).save(self.pid,dict(operation_id=str(uuid4()),preset_id=None,name='虚构组合',settings=dict(steps=[dict(step='rewrite',adapter_id='configured-http-v2',connection_id=saved['id'],model_id='fiction-model',temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=False)],style_id=None,style_prompt='作者文风',manuscript_language='zh-CN',budget=dict(max_external_calls=1,max_reserved_output_tokens=512,risk_budget=1.0,allow_unknown_cost=False)),expected_revision=before['revision']))
            task=self.prepare(saved)['task'];self.assertEqual(self.service.get(self.pid)['workspace_version'],10);self.assertEqual(len(self.service.get(self.pid)['creation_presets']),1)
            SkillLibrary(self.root/'fiction.sqlite3');package=self.root/'configured.nwbak';create_backup(self.root/'fiction.sqlite3',package)
            restored=restore_backup(package,self.root/'restored-configured');state=NovelService(SQLiteRepository(restored['database_path'])).get(self.pid);self.assertEqual(state['generation_tasks'][0],task)
            target=self.root/'configured-copy.sqlite3';SQLiteRepository(target);SkillLibrary(target);copied=migrate(package,target,operation_id=str(uuid4()));clone=NovelService(SQLiteRepository(target)).get(copied['projects'][0]['new_id'])
            self.assertEqual(clone['generation_tasks'][0]['frozen']['parameters']['binding']['destination'],task['frozen']['parameters']['binding']['destination']);self.assertEqual(calls,[])
    def test_mixed_native_protocol_comparison_freezes_identical_common_messages(self):
        from novel_writer.application.comparisons import ComparisonCoordinator
        with wire('openai-chat') as (first,left_calls),wire('gemini-content') as (second,right_calls):
            connections=[self.save(first),self.save(second,'gemini-content')];state=self.service.get(self.pid);options=dict(chapter_id=self.cid,budget_chars=2000,include_writing_rules=True);preview=self.service.preview_context(self.pid,options)
            profiles=[dict(adapter_id='configured-http-v2',connection_id=value['id'],model_id='fiction-model',temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=True,prompt_version='rewrite-1') for value in connections]
            engine=ComparisonCoordinator(self.service,self.engine);engine.create(self.pid,dict(experiment_id=str(uuid4()),title='跨原生协议虚构比较',chapter_id=self.cid,context_options=options,context_sha256=digest(preview['context_text']),instruction='同一保存原稿',rubric='作者自评',parameters=dict(max_output_chars=1000,timeout_ms=3000),profiles=profiles,expected_revision=state['revision']))
            state=self.service.get(self.pid);self.assertEqual(len(state['comparison_experiments']),1);self.assertEqual(len(state['generation_tasks']),2);self.assertEqual(state['workspace_version'],9);self.assertEqual(left_calls+right_calls,[])
    def test_configured_workflow_waits_for_fresh_exact_destination_confirmation(self):
        from novel_writer.application.workflows import WorkflowCoordinator
        with wire('gemini-content') as (endpoint,calls):
            connection=self.save(endpoint,'gemini-content');state=self.service.get(self.pid);engine=WorkflowCoordinator(self.service,self.engine);self.addCleanup(engine.close)
            spec=dict(workflow_format=1,interface_version=1,name='虚构配置角色流程',permissions=['read_saved_source','prepare_model_request'],nodes=[dict(id='read',kind='reference',parents=[],source=None,role=None,parameters=dict(max_chars=1000),when=None),dict(id='rewrite',kind='model_rewrite',parents=['read'],source='read',role='writer',parameters=dict(context_budget=2000,max_output_chars=1000,timeout_ms=3000),when=None)])
            version=engine.import_template(self.pid,dict(operation_id=str(uuid4()),template_id=None,template=spec,expected_revision=state['revision']));state=self.service.get(self.pid)
            run=engine.create(self.pid,dict(operation_id=str(uuid4()),template_version_id=version['version_id'],chapter_id=self.cid,inputs=dict(instruction='仅虚构候选',query='',plan_text=''),roles=[dict(role='writer',adapter_id='configured-http-v2',connection_id=connection['id'],model_id='fiction-model',temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=True,prompt_version='rewrite-1')],limits=dict(max_external_calls=1,max_reserved_output_tokens=512,max_node_attempts=10,max_retries=0,max_iterations=1,concurrency=1),execution_mode='step',network_mode='confirm_each',expected_revision=state['revision']))
            engine.control(self.pid,run['run_id'],'start');engine.step(self.pid,run['run_id']);engine.step(self.pid,run['run_id']);waiting=engine.describe(self.pid,run['run_id']);self.assertTrue(any(value['status']=='waiting_request' for value in waiting['attempts']));self.assertEqual(calls,[])

if __name__=='__main__':unittest.main()
