from pathlib import Path
from copy import deepcopy
from importlib import util,import_module
from uuid import uuid4
from unittest.mock import patch
import sys,json,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
import test_s5c_models as fixture
from test_s5a_review import rows
from novel_writer.domain.tasks import digest
from novel_writer.application.provider_connections import PROVIDERS

class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(util.find_spec('novel_writer.application.comparisons'),'缺少同题比较/盲评实验服务')
        self.api=import_module('novel_writer.application.comparisons');self.f=fixture.ModelTests('test_real_wire_completion_usage_and_atomic_candidate_adoption_once');self.f.setUp();self.addCleanup(self.f.doCleanups);self.f.providers.save(id='catie',base_url=PROVIDERS['catie']['base_url'],model_id='second-configured-model',api_key=fixture.FAKE_KEY);self.service=self.f.service;self.engine=self.api.ComparisonCoordinator(self.service,self.f.engine);self.pid=self.f.pid
    def create(self,*,return_request=False,**changes):
        state=self.service.get(self.pid);options=dict(chapter_id=self.f.cid,budget_chars=4000,include_writing_rules=True);preview=self.service.preview_context(self.pid,options);common=dict(adapter_id='chat-completions-http-v1',temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=True,prompt_version='rewrite-1')
        request=dict(experiment_id=str(uuid4()),title='虚构同题比较',chapter_id=self.f.cid,context_options=options,context_sha256=digest(preview['context_text']),instruction='按保存原稿给出候选',rubric='叙事连贯、明确评价要求；不代表真实质量排名',parameters=dict(max_output_chars=10000,timeout_ms=2000),profiles=[dict(common,connection_id='gg',model_id='author-selected-model'),dict(common,connection_id='catie',model_id='second-configured-model')],expected_revision=state['revision']);request.update(changes);return (None,request) if return_request else (self.engine.create(self.pid,request),request)
    def execute(self,identifier):
        setup=self.engine.setup(self.pid,identifier)
        for c in setup['configurations']:
            self.engine.execute(self.pid,identifier,c['configuration_id'],dict(confirm_external=True,request_sha256=c['request_sha256']));self.f.engine.wait_idle(5)
        return self.engine.blind(self.pid,identifier)
    def score(self,identifier,side,value=3):return self.engine.score(self.pid,identifier,dict(operation_id=str(uuid4()),side=side,rating=value,outcome='scored' if value is not None else 'unscorable',notes='虚构作者盲评分，非真实质量结论' if value is not None else '无可评分结果，失败单列',expected_revision=self.service.get(self.pid)['revision']))
    def reveal(self,identifier):return self.engine.reveal(self.pid,identifier,dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision']))
    def test_two_tasks_freeze_same_revision_original_context_rules_and_evaluation_without_credentials(self):
        with patch.object(self.f.providers,'_load',side_effect=AssertionError('准备比较不能读凭据')):created,request=self.create()
        identifier=created['experiment_id'];state=self.service.get(self.pid);self.assertEqual(state['workspace_version'],7);tasks=state['generation_tasks'];self.assertEqual(len(tasks),2);a,b=[t['frozen'] for t in tasks]
        for name in ('source_revision','target','context_text','context_options','dependencies'):self.assertEqual(a[name],b[name],name)
        pa=dict(a['parameters']);pb=dict(b['parameters']);pa.pop('binding');pb.pop('binding');self.assertEqual(pa,pb);self.assertIn(request['rubric'],pa['instruction']);self.assertTrue(any(d['kind']=='writing_rules' for d in a['dependencies']));self.assertEqual(self.f.calls,[])
        saved=rows(self.f.db);self.assertEqual(self.engine.create(self.pid,request),created);self.assertEqual(rows(self.f.db),saved)
        self.execute(identifier);self.assertEqual(len(self.f.calls),2);self.assertEqual(self.f.calls[0]['body']['messages'],self.f.calls[1]['body']['messages']);self.assertNotEqual(self.f.calls[0]['body']['model'],self.f.calls[1]['body']['model'])
    def test_blind_scores_reveal_reopen_winner_only_opens_candidate_and_preset(self):
        created,_=self.create();identifier=created['experiment_id'];self.assertFalse(self.engine.blind(self.pid,identifier)['ready']);blind=self.execute(identifier);self.assertTrue(blind['ready']);self.assertEqual({c['side'] for c in blind['candidates']},{'A','B'});raw=json.dumps(blind)
        for t in self.service.get(self.pid)['generation_tasks']:
            self.assertNotIn(t['id'],raw);self.assertNotIn(t['frozen']['parameters']['binding']['model_id'],raw);self.assertNotIn(t['frozen']['parameters']['binding']['connection_id'],raw)
        with self.assertRaises(ValueError):self.reveal(identifier)
        self.score(identifier,'A',4)
        with self.assertRaises(ValueError):self.reveal(identifier)
        self.score(identifier,'B',2);revealed=self.reveal(identifier);self.assertEqual(len(revealed['identities']),2);before=self.service.get(self.pid);request=dict(operation_id=str(uuid4()),side='A',action='open_candidate',name='',expected_revision=before['revision']);choice=self.engine.choose(self.pid,identifier,request);self.assertIn('task_id',choice);after=self.service.get(self.pid);self.assertEqual(after['document'],before['document']);saved=rows(self.f.db);self.assertEqual(self.engine.choose(self.pid,identifier,request),choice);self.assertEqual(rows(self.f.db),saved)
        preset=self.engine.choose(self.pid,identifier,dict(operation_id=str(uuid4()),side='A',action='save_preset',name='作者选择配置',expected_revision=after['revision']));self.assertIsNotNone(preset['preset_id']);self.assertEqual(self.service.get(self.pid)['document'],before['document']);reopened=self.api.ComparisonCoordinator(self.service,self.f.engine).blind(self.pid,identifier);self.assertTrue(reopened['revealed']);self.assertEqual(len(reopened['scores']),2)
    def test_disabled_no_implicit_send_independent_failure_and_unknown_usage(self):
        self.f.adapter.enabled=False;created,_=self.create();setup=self.engine.setup(self.pid,created['experiment_id']);c=setup['configurations'][0]
        with self.assertRaises(ValueError):self.engine.execute(self.pid,created['experiment_id'],c['configuration_id'],dict(confirm_external=True,request_sha256=c['request_sha256']))
        self.assertEqual(self.f.calls,[]);self.f.adapter.enabled=True
        for c,mode in zip(setup['configurations'],('429','unknown_usage')):
            self.f.mode=mode;self.engine.execute(self.pid,created['experiment_id'],c['configuration_id'],dict(confirm_external=True,request_sha256=c['request_sha256']));self.f.engine.wait_idle(5)
        blind=self.engine.blind(self.pid,created['experiment_id']);self.assertEqual({c['status'] for c in blind['candidates']},{'failed','succeeded'});self.assertTrue(all(c['cost'] is None for c in blind['candidates']));self.assertTrue(all(c['elapsed_seconds']>=0 for c in blind['candidates']));self.assertEqual(len(self.f.calls),2)
        for c in blind['candidates']:self.score(created['experiment_id'],c['side'],None if c['status']=='failed' else 4)
        self.reveal(created['experiment_id']);failed=next(c for c in blind['candidates'] if c['status']=='failed')
        with self.assertRaises(ValueError):self.engine.choose(self.pid,created['experiment_id'],dict(operation_id=str(uuid4()),side=failed['side'],action='open_candidate',name='',expected_revision=self.service.get(self.pid)['revision']))
    def test_pending_scores_and_early_reveal_rejected_by_service_and_persistent_boundary(self):
        from novel_writer.domain.models import utc_now
        created,_=self.create();identifier=created['experiment_id'];before=rows(self.f.db)
        for side in ('A','B'):
            with self.assertRaises(ValueError):self.score(identifier,side)
        with self.assertRaises(ValueError):self.reveal(identifier)
        self.assertEqual(rows(self.f.db),before);bad=deepcopy(self.service.get(self.pid));bad['comparison_scores'].append(dict(id=str(uuid4()),project_id=self.pid,experiment_id=identifier,side='A',rating=3,outcome='scored',candidate_id=str(uuid4()),result_sha256='0'*64,terminal_status='succeeded',notes='伪造提前评分',created_at=utc_now()))
        with self.assertRaises(ValueError):self.service.repository.save(bad,expected_revision=bad['revision'])
        self.assertEqual(rows(self.f.db),before)
    def test_failed_side_is_not_a_zero_point_numeric_loser(self):
        created,_=self.create();identifier=created['experiment_id'];setup=self.engine.setup(self.pid,identifier)
        for c,mode in zip(setup['configurations'],('429','success')):
            self.f.mode=mode;self.engine.execute(self.pid,identifier,c['configuration_id'],dict(confirm_external=True,request_sha256=c['request_sha256']));self.f.engine.wait_idle(5)
        failed=next(c for c in self.engine.blind(self.pid,identifier)['candidates'] if c['status']=='failed');before=rows(self.f.db)
        with self.assertRaises(ValueError):self.engine.score(self.pid,identifier,dict(operation_id=str(uuid4()),side=failed['side'],rating=0,notes='不能伪装为零分败者',expected_revision=self.service.get(self.pid)['revision']))
        self.assertEqual(rows(self.f.db),before)
    def test_failed_second_child_rolls_back_entire_experiment_and_both_task_ids(self):
        before=rows(self.f.db);created,request=self.create();self.assertTrue(created)
        # 另一个全新身份的第二配置无效，不能残留第一个孩子或实验。
        state=self.service.get(self.pid);request['experiment_id']=str(uuid4());request['expected_revision']=state['revision'];request['profiles'][1]['adapter_id']='unregistered-adapter';before=rows(self.f.db)
        with self.assertRaises(ValueError):self.engine.create(self.pid,request)
        self.assertEqual(rows(self.f.db),before)
    def test_v7_backup_restore_copy_all_experiment_links_and_actual_v6_unchanged(self):
        from novel_writer.application.backups import create_backup,restore_backup
        from novel_writer.application.migrations import migrate
        from novel_writer.storage.sqlite_repository import SQLiteRepository
        from novel_writer.application.skill_import import SkillLibrary
        from novel_writer.application.service import NovelService
        from novel_writer.application.extensions import import_template
        from test_s6a_extensions import SPEC
        created,_=self.create();identifier=created['experiment_id'];self.execute(identifier);self.score(identifier,'A');self.score(identifier,'B');self.reveal(identifier);self.engine.choose(self.pid,identifier,dict(operation_id=str(uuid4()),side='B',action='save_preset',name='虚构胜者',expected_revision=self.service.get(self.pid)['revision']));template=import_template(self.service,self.pid,dict(operation_id=str(uuid4()),template_id=None,template=SPEC,expected_revision=self.service.get(self.pid)['revision']));package=self.f.root/'comparison.nwbak';manifest=create_backup(self.f.db,package);self.assertEqual(manifest['backup_format_version'],51);restored=Path(restore_backup(package,self.f.root/'restored-v7')['database_path']);self.assertEqual(rows(restored),rows(self.f.db));target=self.f.root/'comparison-copy.sqlite3';SQLiteRepository(target);SkillLibrary(target);result=migrate(package,target,operation_id=str(uuid4()));pid=result['projects'][0]['new_id'];copy=NovelService(SQLiteRepository(target)).get(pid);self.assertEqual(len(copy['comparison_experiments']),1);self.assertEqual(len(copy['comparison_scores']),2);self.assertEqual(len(copy['comparison_reveals']),1);self.assertEqual(len(copy['generation_presets']),1);self.assertEqual(copy['extension_templates'][0]['template'],SPEC);self.assertNotEqual(copy['extension_templates'][0]['id'],template['version_id']);self.assertNotEqual(copy['comparison_experiments'][0]['id'],identifier);self.assertEqual(len(self.f.calls),2)
        frozen=json.loads((ROOT/'tests/fixtures/s6a_legacy.json').read_text(encoding='utf8'))['v6'];old=self.f.root/'old-v6.sqlite3';old.write_bytes(bytes.fromhex(frozen['database_hex']));data=old.read_bytes();NovelService(SQLiteRepository(old)).get(frozen['project_id']);self.assertEqual(old.read_bytes(),data);oldpackage=self.f.root/'old-v6.nwbak';oldpackage.write_bytes(bytes.fromhex(frozen['package_hex']));oldrestored=Path(restore_backup(oldpackage,self.f.root/'restored-v6')['database_path']);self.assertEqual(rows(oldrestored),frozen['rows'])

if __name__=='__main__':unittest.main()
