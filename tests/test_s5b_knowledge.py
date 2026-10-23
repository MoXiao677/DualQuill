from importlib import util,import_module
from pathlib import Path
from copy import deepcopy
from uuid import uuid4
import json,sys,tempfile,unittest,sqlite3
from contextlib import closing
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository
from test_s5a_review import rows
FROZEN=json.loads((ROOT/'tests/fixtures/s5b_legacy.json').read_text(encoding='utf8'))

class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(util.find_spec('novel_writer.application.knowledge'),'S5-B缺少图谱/规划/局部修改服务')
        self.api=import_module('novel_writer.application.knowledge');self.temp=tempfile.TemporaryDirectory(prefix='novel-s5b-');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.db=self.root/'fictional.sqlite3';self.db.write_bytes(bytes.fromhex(FROZEN['v4']['database_hex']));self.service=NovelService(SQLiteRepository(self.db))
    def cmd(self,action,**values):
        values.setdefault('operation_id',str(uuid4()));values.setdefault('expected_revision',self.service.get('p1')['revision']);return self.api.command(self.service,'p1',action,values)
    def node(self,label='灯塔',**changes):
        values=dict(kind='location',label=label,aliases=[],memory_ids=[],position_chapter_id='p1-c5',source=dict(kind='chapter',entity_id='p1-c5'),confirmed=True);values.update(changes);return self.cmd('save_node',**values)
    def edge(self,a,b):return self.cmd('save_edge',from_id=a['id'],to_id=b['id'],relation='通往',position_chapter_id='p1-c5',source=dict(kind='chapter',entity_id='p1-c5'),confirmed=True)
    def save(self,action,**values):return self.service.execute('p1',action,values,expected_revision=self.service.get('p1')['revision'])
    def test_alias_search_adjacency_chain_position_source_and_crossbook(self):
        a=self.node(aliases=['旧塔']);b=self.node('港口');c=self.node('航路');self.edge(a,b);self.edge(b,c)
        view=self.api.view(self.service,'p1',dict(query='旧塔',chapter_id='p1-c5'));self.assertEqual([n['id'] for n in view['nodes']],[a['id']])
        chain=self.api.view(self.service,'p1',dict(root_id=a['id'],depth=2,chapter_id='p1-c5'));self.assertEqual(set(n['id'] for n in chain['nodes']),{a['id'],b['id'],c['id']});self.assertEqual(len(chain['edges']),2)
        self.assertFalse(self.api.view(self.service,'p1',dict(chapter_id='p1-c4'))['nodes'])
        before=rows(self.db)
        with self.assertRaises(ValueError):self.edge(a,dict(id='other-book-node'))
        self.assertEqual(rows(self.db),before)
        self.save('save_chapter',chapter_id='p1-c5',content='作者更改来源');view=self.api.view(self.service,'p1',{});self.assertTrue(all(n['outdated'] for n in view['nodes']));self.assertTrue(all(n['confirmed'] for n in view['nodes']))
    def test_planned_node_never_enters_confirmed_facts_and_effective_position_is_maximum(self):
        outline=self.service.get('p1')['document']['chapter_outlines'][0];n=self.node('计划事件',kind='event',source=dict(kind='chapter_outline',entity_id=outline['id']),position_chapter_id='p1-c1')
        self.assertEqual(n['basis'],'plan');view=self.api.view(self.service,'p1',dict(ready_only=True));self.assertFalse(view['nodes'])
    def test_merge_preview_memory_links_restore_and_conflict_retains_later_edits(self):
        memory=self.service.get('p1')['memories'][0]['id'];a=self.node('旧塔',memory_ids=[memory]);b=self.node('灯塔');c=self.node('港口');self.edge(a,c)
        before=self.service.get('p1');preview=self.api.merge_preview(self.service,'p1',dict(source_id=a['id'],target_id=b['id']));self.assertEqual(len(preview['edges']),1);self.assertEqual(preview['memory_ids'],[memory]);self.assertEqual(self.service.get('p1'),before)
        op=str(uuid4());request=dict(source_id=a['id'],target_id=b['id'],operation_id=op,expected_revision=before['revision']);merge=self.cmd('merge',**request);after=rows(self.db);self.assertEqual(self.cmd('merge',**request),merge);self.assertEqual(rows(self.db),after)
        self.assertIn('旧塔',next(n for n in self.api.view(self.service,'p1',{})['nodes'] if n['id']==b['id'])['aliases'])
        self.cmd('restore_merge',merge_id=merge['id']);view=self.api.view(self.service,'p1',{});self.assertEqual({n['id'] for n in view['nodes']},{a['id'],b['id'],c['id']})
        second=self.cmd('merge',source_id=a['id'],target_id=b['id']);self.node('灯塔（新编辑）',node_id=b['id']);snapshot=rows(self.db)
        with self.assertRaises(ValueError):self.cmd('restore_merge',merge_id=second['id'])
        self.assertEqual(rows(self.db),snapshot)
    def plan(self,**changes):
        s=self.service.get('p1');target=s['document']['book_outline'];v=dict(target_kind='book_outline',target_id=target['id'],field='ending',new_text='作者根据已保存正文调整的结局。',source=dict(kind='chapter',entity_id='p1-c5'),reason='手动反馈');v.update(changes);return self.cmd('prepare_plan',**v)
    def test_planning_diff_locks_one_field_accept_replay_and_history(self):
        proposal=self.plan();before=self.service.get('p1');self.assertEqual(proposal['old_text'],before['document']['book_outline']['ending']);self.assertTrue(proposal['impact']['later_chapter_ids']);self.assertIn('foreshadow_node_ids',proposal['impact'])
        self.cmd('set_plan_lock',target_kind='book_outline',target_id=proposal['target_id'],field='ending',locked=True,reason='结局锁')
        with self.assertRaises(ValueError):self.cmd('decide_plan',proposal_id=proposal['id'],decision='accepted')
        self.cmd('set_plan_lock',target_kind='book_outline',target_id=proposal['target_id'],field='ending',locked=False,reason='作者解除')
        op=str(uuid4());v=dict(proposal_id=proposal['id'],decision='accepted',operation_id=op,expected_revision=self.service.get('p1')['revision']);receipt=self.cmd('decide_plan',**v);after=self.service.get('p1');expected=deepcopy(before['document']['book_outline']);expected['ending']=proposal['new_text'];expected['updated_at']=after['document']['versions'][-1]['snapshot']['updated_at'];self.assertNotEqual(expected['updated_at'],before['document']['book_outline']['updated_at']);self.assertEqual(after['document']['book_outline'],expected);self.assertEqual(len(after['document']['versions']),len(before['document']['versions'])+1);saved=rows(self.db);self.assertEqual(self.cmd('decide_plan',**v),receipt);self.assertEqual(rows(self.db),saved)
        with self.assertRaises(ValueError):self.cmd('decide_plan',proposal_id=proposal['id'],decision='rejected')
    def test_plan_lock_applies_to_manual_save_and_source_staleness_and_reject(self):
        p=self.plan();self.cmd('set_plan_lock',target_kind='book_outline',target_id=p['target_id'],field='ending',locked=True,reason='固定')
        before=rows(self.db)
        with self.assertRaises(ValueError):self.save('save_book_outline',ending='手动绕过')
        self.assertEqual(rows(self.db),before);self.save('save_chapter',chapter_id='p1-c5',content='来源改变')
        with self.assertRaises(ValueError):self.cmd('decide_plan',proposal_id=p['id'],decision='accepted')
        r=self.cmd('decide_plan',proposal_id=p['id'],decision='rejected');self.assertEqual(r['decision'],'rejected')
    def duplicate(self):return next(i for i in self.service.get('p1')['review_issues'] if i['finding']['rule_id']=='duplicate_exact')
    def edit(self,**changes):
        v=dict(issue_id=self.duplicate()['id'],side=1,mode='delete',replacement='',reason='作者删除重复段');v.update(changes);return self.cmd('prepare_edit',**v)
    def test_local_duplicate_edit_exact_span_revision_authorization_and_once(self):
        p=self.edit();before=self.service.get('p1');chapter=next(c for c in before['document']['chapters'] if c['id']==p['chapter_id']);self.assertEqual(p['before_text'],chapter['content']);self.assertEqual(p['after_text'],p['before_text'][:p['start']]+p['before_text'][p['end']:]);self.assertEqual(len(p['evidence']),2)
        changed=self.cmd('revise_edit',proposal_id=p['id'],replacement='作者合并后的衔接段',mode='merge',reason='合并');self.assertEqual(changed['revision'],2);self.assertEqual(changed['before_text'],p['before_text'])
        op=str(uuid4());v=dict(proposal_id=p['id'],proposal_revision=2,decision='accepted',authorize_confirmed=False,operation_id=op,expected_revision=self.service.get('p1')['revision']);receipt=self.cmd('decide_edit',**v);saved=rows(self.db);self.assertEqual(self.cmd('decide_edit',**v),receipt);self.assertEqual(rows(self.db),saved);after=self.service.get('p1');new=next(c for c in after['document']['chapters'] if c['id']==p['chapter_id']);self.assertEqual(new['content'],changed['after_text']);self.assertEqual(len(after['document']['versions']),len(before['document']['versions'])+1);self.assertEqual(after['memories'],before['memories'])
    def test_local_edit_stale_cancel_nochange_and_rollback(self):
        p=self.edit();before=self.service.get('p1');chapter_id=p['chapter_id'];self.save('save_chapter',chapter_id=chapter_id,content='后续手动编辑');snapshot=rows(self.db)
        with self.assertRaises(ValueError):self.cmd('decide_edit',proposal_id=p['id'],proposal_revision=1,decision='accepted',authorize_confirmed=True)
        self.assertEqual(rows(self.db),snapshot);self.cmd('decide_edit',proposal_id=p['id'],proposal_revision=1,decision='cancelled',authorize_confirmed=False)
        snapshot=rows(self.db)
        with self.assertRaises(ValueError):self.edit(replacement='stale')
        self.assertEqual(rows(self.db),snapshot)
    def test_v5_backup_copy_all_histories_and_v1_to_v4_original_rows(self):
        from novel_writer.application.backups import create_backup,restore_backup
        from novel_writer.application.migrations import migrate
        a=self.node('旧p1-c5',aliases=['p1-c5']);b=self.node('新塔');self.edge(a,b);m=self.cmd('merge',source_id=a['id'],target_id=b['id']);self.cmd('restore_merge',merge_id=m['id']);p=self.plan();self.cmd('decide_plan',proposal_id=p['id'],decision='accepted');e=self.edit();self.cmd('decide_edit',proposal_id=e['id'],proposal_revision=1,decision='rejected',authorize_confirmed=False)
        package=self.root/'v5.nwbak';manifest=create_backup(self.db,package);self.assertEqual(manifest['backup_format_version'],51);restored=Path(restore_backup(package,self.root/'restored')['database_path']);self.assertEqual(rows(restored),rows(self.db));target=self.root/'copy.sqlite3';target.write_bytes(bytes.fromhex(FROZEN['v4']['database_hex']));result=migrate(package,target,operation_id=str(uuid4()));pid=next(p['new_id'] for p in result['projects'] if p['old_id']=='p1');copy=NovelService(SQLiteRepository(target)).get(pid);self.assertEqual(copy['workspace_version'],5);self.assertEqual(copy['knowledge_nodes'][0]['label'],'旧p1-c5');self.assertNotEqual(copy['knowledge_nodes'][0]['id'],a['id']);self.assertEqual(copy['knowledge_nodes'][0]['aliases'],['p1-c5']);self.assertEqual(len(copy['graph_restores']),1)
        versions=[FROZEN['legacy']['legacy']['v1'],FROZEN['legacy']['legacy']['v2'],FROZEN['legacy']['v3'],FROZEN['v4']]
        for index,f in enumerate(versions,1):
            db=self.root/('old'+str(index)+'.sqlite3');db.write_bytes(bytes.fromhex(f['database_hex']));data=db.read_bytes();NovelService(SQLiteRepository(db)).get('p1');self.assertEqual(db.read_bytes(),data);pack=self.root/('old'+str(index)+'.nwbak');pack.write_bytes(bytes.fromhex(f['package_hex']));old=Path(restore_backup(pack,self.root/('restored'+str(index)))['database_path']);self.assertEqual(rows(old),f['rows'])
    def test_strict_schema_and_immutable_history_reject_tamper(self):
        from novel_writer.storage.sqlite_repository import validate_workspace
        n=self.node();s=self.service.get('p1');self.assertEqual(s['workspace_version'],5);bad=deepcopy(s);bad['knowledge_nodes'][0]['confirmed']=1
        with self.assertRaises(ValueError):validate_workspace(bad)
        bad=deepcopy(s);bad['knowledge_nodes'][0]['label']='覆写历史'
        with self.assertRaises(ValueError):self.service.repository.save(bad,expected_revision=s['revision'])
    def test_forged_accepted_plan_cannot_bypass_source_guard_on_repository_path(self):
        from novel_writer.storage.json_codec import document_from_dict,document_to_dict
        from novel_writer.application import book_outlines
        from novel_writer.domain.models import utc_now
        p=self.plan();self.save('save_chapter',chapter_id='p1-c5',content='来源改动后不能复用旧提案');s=self.service.get('p1');bad=deepcopy(s);doc=document_from_dict(bad['document']);book_outlines.save(doc,dict(ending=p['new_text']));bad['document']=document_to_dict(doc);bad['planning_receipts'].append(dict(id=str(uuid4()),project_id='p1',proposal_id=p['id'],decision='accepted',version_before=p['target']['version_id'],version_after=bad['document']['versions'][-1]['id'],saved_revision=s['revision']+1,created_at=utc_now()));before=rows(self.db)
        bad['revision']=s['revision']+1
        from novel_writer.storage.sqlite_repository import validate_workspace
        validate_workspace(bad)  # 结构/收据版本有效，必须由历史中的实际来源守卫拒绝。
        with self.assertRaises(ValueError):self.service.repository.save(bad,expected_revision=s['revision'])
        self.assertEqual(rows(self.db),before)
    def test_confirmed_local_authorization_noop_failure_rollback_and_retry(self):
        from novel_writer.application.tasks import TaskCoordinator
        from novel_writer.application.task_protocol import AdapterRegistry
        from novel_writer.application.review_rules import OfflineAuditAdapter
        from test_s5a_review import ReviewTests
        self.save('save_chapter',chapter_id='p1-c6',status='confirmed');registry=AdapterRegistry();registry.register('audit_chapter',OfflineAuditAdapter());self.engine=TaskCoordinator(self.service,registry);self.addCleanup(self.engine.close);review=ReviewTests.analyze(self);issue=next(i for i in review['issues'] if i['finding']['rule_id']=='duplicate_exact')
        ev=issue['finding']['evidence'][1];snapshot=rows(self.db)
        with self.assertRaises(ValueError):self.cmd('prepare_edit',issue_id=issue['id'],side=1,mode='rewrite',replacement=ev['quote'],reason='原样不写版本')
        self.assertEqual(rows(self.db),snapshot);p=self.cmd('prepare_edit',issue_id=issue['id'],side=1,mode='rewrite',replacement='作者的新衔接',reason='授权修订')
        with self.assertRaises(ValueError):self.cmd('decide_edit',proposal_id=p['id'],proposal_revision=1,decision='accepted',authorize_confirmed=False)
        revision=self.service.get('p1')['revision'];before=rows(self.db)
        with closing(sqlite3.connect(self.db)) as db,db:db.execute("CREATE TRIGGER fail_s5b BEFORE INSERT ON project_snapshots WHEN NEW.project_id='p1' AND NEW.revision="+str(revision+1)+" BEGIN SELECT RAISE(ABORT,'fictional full'); END")
        request=dict(operation_id=str(uuid4()),expected_revision=revision,proposal_id=p['id'],proposal_revision=1,decision='accepted',authorize_confirmed=True)
        with self.assertRaises(sqlite3.Error):self.cmd('decide_edit',**request)
        self.assertEqual(rows(self.db),before)
        with closing(sqlite3.connect(self.db)) as db,db:db.execute('DROP TRIGGER fail_s5b')
        receipt=self.cmd('decide_edit',**request);saved=rows(self.db);self.assertEqual(self.cmd('decide_edit',**request),receipt);self.assertEqual(rows(self.db),saved)

if __name__=='__main__':unittest.main()
