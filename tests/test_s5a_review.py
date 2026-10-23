from contextlib import closing
from importlib import util,import_module
from copy import deepcopy
import json,sqlite3,sys,tempfile,time,unittest
from pathlib import Path
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository
from novel_writer.application.tasks import TaskCoordinator
from novel_writer.application.task_protocol import AdapterRegistry
from novel_writer.domain.tasks import digest
from test_s5a_rules import request_rules,FROZEN

def rows(path):
    with closing(sqlite3.connect(path)) as db:return {t:[list(r) for r in db.execute('SELECT * FROM '+t+' ORDER BY 1,2')] for t in ('projects','project_snapshots','skills')}

class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(util.find_spec('novel_writer.application.reviews'),'缺少持久审核/处理/提案闭环')
        self.api=import_module('novel_writer.application.reviews');self.rules=import_module('novel_writer.application.review_rules')
        self.temp=tempfile.TemporaryDirectory(prefix='novel-s5a-review-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=self.root/'fictional.sqlite3';self.db.write_bytes(bytes.fromhex(FROZEN['v3']['database_hex']))
        self.service=NovelService(SQLiteRepository(self.db));registry=AdapterRegistry();registry.register('audit_chapter',self.rules.OfflineAuditAdapter());self.engine=TaskCoordinator(self.service,registry);self.addCleanup(self.engine.close)
        self.save('save_chapter',chapter_id='p1-c5',content='禁用词。\n\n灯塔照亮港口潮水，船员静静等待远方的来信。')
        self.save('save_chapter',chapter_id='p1-c6',content='灯塔照亮港口潮水，船员静静等待远方的来信。')
    def save(self,action,**fields):
        state=self.service.get('p1');return self.service.execute('p1',action,fields,expected_revision=state['revision'])
    def analyze(self,previous=None,context_options=None):
        state=self.service.get('p1');options=context_options or dict(chapter_id='p1-c5',budget_chars=4000)
        preview=self.service.preview_context('p1',options);params=request_rules();params['previous_report_id']=previous
        prepared=self.engine.prepare('p1',dict(request_id=str(uuid4()),chapter_id='p1-c5',task_type='audit_chapter',context_options=options,context_sha256=digest(preview['context_text']),parameters=params,expected_revision=state['revision']))
        identifier=prepared['task']['id'];self.engine.start('p1',identifier);self.engine.wait_idle(5)
        view=self.engine.describe('p1',identifier);self.assertEqual(view['task']['status'],'succeeded',view)
        self.assertFalse(view['candidates']);self.assertEqual(len(view['reports']),1)
        return self.engine.review_report('p1',view['reports'][0]['id'])
    def accept(self,proposal,identity=None,**changes):
        request=dict(decision_id=identity or str(uuid4()),proposal_id=proposal['id'],decision='accepted',expected_revision=self.service.get('p1')['revision'],confirmed=True,preserve_conflicts=True)
        request.update(changes);return self.engine.decide_proposal('p1',proposal['report_id'],request),request
    def test_analysis_persists_report_evidence_proposals_and_never_becomes_body_candidate(self):
        before=self.service.get('p1')['document'];view=self.analyze();after=self.service.get('p1')
        self.assertGreaterEqual(after['workspace_version'],4);self.assertEqual(after['document'],before)
        self.assertTrue(any(i['finding']['rule_id']=='forbidden_literal' for i in view['issues']))
        self.assertTrue(any(i['finding']['rule_id']=='duplicate_exact' for i in view['issues']))
        task_id=view['report']['task_id'];before_rows=rows(self.db)
        with self.assertRaises(ValueError):self.engine.adopt('p1',task_id,dict(candidate_id=None,adoption_id=str(uuid4()),expected_revision=after['revision'],authorize_confirmed=True))
        self.assertEqual(rows(self.db),before_rows);self.assertFalse(view['outdated'])
    def test_false_positive_whitelist_is_effective_and_reopen_and_revoke_are_append_only(self):
        view=self.analyze();issue=next(i for i in view['issues'] if i['finding']['rule_id']=='duplicate_exact')
        request=dict(operation_id=str(uuid4()),issue_id=issue['id'],kind='false_positive',reason='作者明确允许回环',whitelist=True,expected_revision=self.service.get('p1')['revision'])
        self.engine.review_issue('p1',view['report']['id'],request)
        snapshot=rows(self.db);self.engine.review_issue('p1',view['report']['id'],request);self.assertEqual(rows(self.db),snapshot)
        second=self.analyze(previous=view['report']['id']);self.assertFalse(any(i['finding']['rule_id']=='duplicate_exact' for i in second['issues']))
        waiver=self.service.get('p1')['rule_waivers'][0]
        self.engine.review_issue('p1',view['report']['id'],dict(operation_id=str(uuid4()),issue_id=issue['id'],kind='revoke_waiver',reason='重新启用检查',whitelist=False,waiver_id=waiver['id'],expected_revision=self.service.get('p1')['revision']))
        third=self.analyze(previous=second['report']['id']);self.assertTrue(any(i['finding']['rule_id']=='duplicate_exact' for i in third['issues']))
        self.assertEqual(self.service.get('p1')['review_issues'][:len(view['issues'])],[{k:v for k,v in i.items() if k!='status'} for i in view['issues']])
    def test_accept_is_idempotent_retains_conflicting_memory_and_creates_traceable_source(self):
        view=self.analyze();proposal=next(p for p in view['proposals'] if p['proposal']['kind']=='chapter_summary' and p['proposal']['position_chapter_id']=='p1-c5')
        before=self.service.get('p1');receipt,request=self.accept(proposal)
        after=self.service.get('p1');self.assertEqual(len(after['memories']),len(before['memories'])+1)
        self.assertEqual(after['memories'][:len(before['memories'])],before['memories']);self.assertEqual(after['memory_history'][:len(before['memory_history'])],before['memory_history'])
        new=next(m for m in after['memories'] if m['id']==receipt['memory_id']);self.assertEqual(new['text'],proposal['proposal']['text']);self.assertTrue(new['confirmed']);self.assertEqual(new['source']['entity_id'],proposal['proposal']['evidence']['entity_id'])
        state_rows=rows(self.db);self.assertEqual(self.engine.decide_proposal('p1',view['report']['id'],request),receipt);self.assertEqual(rows(self.db),state_rows)
    def test_outdated_source_rejects_accept_but_unrelated_save_does_not(self):
        view=self.analyze();proposal=view['proposals'][0]
        self.save('save_chapter',chapter_id='p1-c20',content='未选后续章变化');self.assertFalse(self.engine.review_report('p1',view['report']['id'])['outdated'])
        self.save('save_chapter',chapter_id='p1-c5',content='来源已变化')
        self.assertTrue(self.engine.review_report('p1',view['report']['id'])['outdated']);before=rows(self.db)
        with self.assertRaises(ValueError):self.accept(proposal)
        self.assertEqual(rows(self.db),before)
    def test_reject_and_accept_failure_rollback_preserve_all_rows(self):
        view=self.analyze();proposal=view['proposals'][0];state=self.service.get('p1');before=rows(self.db)
        with closing(sqlite3.connect(self.db)) as db,db:db.execute("CREATE TRIGGER fail_review BEFORE INSERT ON project_snapshots WHEN NEW.project_id='p1' AND NEW.revision="+str(state['revision']+1)+" BEGIN SELECT RAISE(ABORT,'fictional full'); END")
        with self.assertRaises((ValueError,sqlite3.Error)):self.accept(proposal)
        self.assertEqual(rows(self.db),before)
        with closing(sqlite3.connect(self.db)) as db,db:db.execute('DROP TRIGGER fail_review')
        receipt,_=self.accept(proposal,decision='rejected');self.assertEqual(receipt['decision'],'rejected');self.assertIsNone(receipt['memory_id'])
    def test_v4_roundtrip_copy_and_old_v1_v2_v3_remain_original(self):
        from novel_writer.application.backups import create_backup,restore_backup
        from novel_writer.application.migrations import migrate
        view=self.analyze();self.accept(view['proposals'][0]);package=self.root/'review.nwbak';manifest=create_backup(self.db,package);self.assertGreaterEqual(manifest['backup_format_version'],51)
        restored=Path(restore_backup(package,self.root/'restored')['database_path']);self.assertEqual(rows(restored),rows(self.db))
        target=self.root/'target.sqlite3';target.write_bytes(bytes.fromhex(FROZEN['v3']['database_hex']));result=migrate(package,target,operation_id=str(uuid4()));project=next(p['new_id'] for p in result['projects'] if p['old_id']=='p1')
        copy=NovelService(SQLiteRepository(target)).get(project);self.assertEqual(len(copy['review_reports']),1);self.assertNotEqual(copy['review_reports'][0]['id'],view['report']['id']);self.assertEqual(copy['memory_proposals'][0]['proposal']['text'],self.service.get('p1')['memory_proposals'][0]['proposal']['text'])
        for version,frozen in (('v1',FROZEN['legacy']['v1']),('v2',FROZEN['legacy']['v2']),('v3',FROZEN['v3'])):
            source=self.root/(version+'.sqlite3');source.write_bytes(bytes.fromhex(frozen['database_hex']));original=source.read_bytes();NovelService(SQLiteRepository(source)).get('p1');self.assertEqual(source.read_bytes(),original)
            oldpack=self.root/(version+'.nwbak');oldpack.write_bytes(bytes.fromhex(frozen['package_hex']));oldrestored=Path(restore_backup(oldpack,self.root/(version+'-restored'))['database_path']);self.assertEqual(rows(oldrestored),frozen['rows'])

    def test_recheck_changed_unchanged_and_whitelisted_are_not_one_click_resolution(self):
        original=self.analyze();issue=next(i for i in original['issues'] if i['finding']['rule_id']=='forbidden_literal')
        self.analyze(previous=original['report']['id'])
        unchanged=self.engine.review_report('p1',original['report']['id'])
        check=next(r for r in unchanged['rechecks'] if r['issue_id']==issue['id']);self.assertEqual(check['status'],'still_found');self.assertFalse(check['source_changed'])
        self.engine.review_issue('p1',original['report']['id'],dict(operation_id=str(uuid4()),issue_id=issue['id'],kind='false_positive',reason='明确误报对照',whitelist=True,expected_revision=self.service.get('p1')['revision']))
        self.analyze(previous=original['report']['id'])
        waived=self.engine.review_report('p1',original['report']['id']);check=next(r for r in waived['rechecks'] if r['issue_id']==issue['id']);self.assertEqual(check['status'],'unverified');self.assertIn('白名单',check['reason'])
        waiver=self.service.get('p1')['rule_waivers'][0]
        self.engine.review_issue('p1',original['report']['id'],dict(operation_id=str(uuid4()),issue_id=issue['id'],kind='revoke_waiver',reason='取消白名单后验证真实修正',whitelist=False,waiver_id=waiver['id'],expected_revision=self.service.get('p1')['revision']))
        self.save('save_chapter',chapter_id='p1-c5',content='作者改后的新正文，没有被禁止的字面串。')
        revised=self.analyze(previous=original['report']['id']);view=self.engine.review_report('p1',original['report']['id']);check=next(r for r in view['rechecks'] if r['issue_id']==issue['id'])
        self.assertEqual(check['status'],'not_found');self.assertTrue(check['source_changed']);self.assertEqual(check['new_report_id'],revised['report']['id']);self.assertTrue(check['source_changes'])
        self.assertNotIn('resolved',json.dumps(check));self.assertEqual(next(i for i in view['issues'] if i['id']==issue['id'])['status'],'false_positive')

    def test_confirmed_memory_global_skill_and_whitelist_snapshot_copy_preserve_composite_graph(self):
        from novel_writer.storage.skills_repository import SkillsRepository
        from novel_writer.application.backups import create_backup
        from novel_writer.application.migrations import migrate
        memory=self.service.get('p1')['memories'][0];self.save('review_memory',memory_id=memory['id'],confirmed=True)
        skill=dict(id='s5-global',name='明确全局参考',description='本测试',imported_at='2020-01-01T00:00:00+00:00',primary_path='SKILL.md',files=[dict(path='SKILL.md',content='S5 global reference literal p1-c5 must stay')]);SkillsRepository(self.db).add(skill)
        def options():
            hit=self.service.search_local('p1',dict(query='S5 global',chapter_id='p1-c5',scopes=['skills'],skill_ids=[skill['id']]))['hits'][0]
            return dict(chapter_id='p1-c5',budget_chars=4000,include_memories=True,include_search_results=True,search_selections=[hit['selection']])
        first=self.analyze(context_options=options());issue=next(i for i in first['issues'] if i['finding']['rule_id']=='duplicate_exact')
        self.engine.review_issue('p1',first['report']['id'],dict(operation_id=str(uuid4()),issue_id=issue['id'],kind='false_positive',reason='组合白名单',whitelist=True,expected_revision=self.service.get('p1')['revision']))
        second=self.analyze(previous=first['report']['id'],context_options=options());self.accept(second['proposals'][0])
        original=self.service.get('p1');task=next(t for t in original['generation_tasks'] if t['id']==second['report']['task_id'])
        self.assertEqual({d['kind'] for d in task['frozen']['dependencies']} & {'memory','skill'},{'memory','skill'});self.assertTrue(task['frozen']['parameters']['waivers'])
        package=self.root/'composite.nwbak';create_backup(self.db,package)
        target=self.root/'composite-target.sqlite3';target.write_bytes(bytes.fromhex(FROZEN['v3']['database_hex']));other=deepcopy(skill);other['files'][0]['content']='目标不同资料';SkillsRepository(target).add(other)
        result=migrate(package,target,operation_id=str(uuid4()));project=next(p['new_id'] for p in result['projects'] if p['old_id']=='p1');copied=NovelService(SQLiteRepository(target)).get(project)
        mapping={(m['kind'],m['old_id']):m['new_id'] for m in result['id_map'] if m['old_project_id']=='p1'}
        fresh=next(t for t in copied['generation_tasks'] if t['id']==mapping['task',task['id']])
        self.assertEqual(fresh['frozen']['context_text'],task['frozen']['context_text']);self.assertIn('p1-c5',fresh['frozen']['context_text'])
        self.assertEqual(fresh['frozen']['parameters']['previous_report_id'],mapping['review_report',first['report']['id']])
        self.assertEqual(fresh['frozen']['parameters']['waivers'][0]['id'],copied['rule_waivers'][0]['id'])
        self.assertEqual(copied['proposal_receipts'][0]['memory_id'],mapping['memory',original['proposal_receipts'][0]['memory_id']])
        self.assertEqual(next(d['entity_id'] for d in fresh['frozen']['dependencies'] if d['kind']=='skill'),next(s['new_id'] for s in result['skills'] if s['old_id']==skill['id']))

if __name__=='__main__':unittest.main()
