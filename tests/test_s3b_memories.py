"""新记忆契约及真实冻结V1数据；raw SQL/original bytes是独立期望。"""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3,sys,tempfile,unittest
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository,ConflictError,validate_workspace
from novel_writer.application.backups import create_backup,restore_backup,preflight_backup,BackupError
from novel_writer.application.migrations import migrate
FROZEN=json.loads((ROOT/'tests/fixtures/s3b_legacy_v1.json').read_text(encoding='utf8'))

def rows(path):
    with closing(sqlite3.connect(path)) as db:
        return {t:[list(r) for r in db.execute('SELECT * FROM '+t+' ORDER BY 1,2')] for t in ('projects','project_snapshots','skills')}

class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='novel-s3b-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=self.root/'fictional.sqlite3';self.db.write_bytes(bytes.fromhex(FROZEN['database_hex']))
        self.service=NovelService(SQLiteRepository(self.db));self.state=self.service.get('p1')
    def save(self,action,**fields):
        self.state=self.service.execute('p1',action,fields,expected_revision=self.state['revision']);return self.state
    def memory(self,**changes):
        data=dict(kind='chapter_summary',title='第五章摘要',text='人工确认港口线索',position_chapter_id='p1-c5',
            character_id=None,volume_number=None,confirmed=True,active=True,source={'kind':'chapter','entity_id':'p1-c5'})
        data.update(changes);self.save('save_memory',**data);return self.state['memories'][-1]
    def status(self):
        self.assertTrue(callable(getattr(self.service,'memory_records',None)),'缺少记忆读取/新鲜度入口')
        return self.service.memory_records('p1')
    def test_typed_memory_and_append_only_edit_archive_history_survive_reopen(self):
        memory=self.memory();identifier=memory['id'];self.assertEqual(self.state['workspace_version'],2)
        self.assertEqual(memory['revision'],1);first=deepcopy(self.state['memory_history'])
        self.save('save_memory',memory_id=identifier,text='作者纠正的摘要')
        self.save('archive_memory',memory_id=identifier)
        reopened=NovelService(SQLiteRepository(self.db)).get('p1')
        self.assertEqual(reopened,self.state);self.assertEqual(reopened['memory_history'][:1],first)
        self.assertEqual([h['revision'] for h in reopened['memory_history']],[1,2,3])
        self.assertFalse(reopened['memories'][0]['active']);self.assertEqual(reopened['memories'][0]['id'],identifier)
        self.assertEqual(reopened['memories'][0]['source'],memory['source'])
    def test_confirmed_freshness_independent_self_and_unrelated_saves_do_not_expire(self):
        self.save('save_chapter',chapter_id='p1-c5',content='来源第一版');m=self.memory()
        self.assertFalse(self.status()[0]['outdated'])
        self.save('save_chapter',chapter_id='p1-c3',content='无关章更新');self.assertFalse(self.status()[0]['outdated'])
        old_version=m['source']['version_id']
        self.save('save_chapter',chapter_id='p1-c5',content='来源第二版')
        status=self.status()[0];self.assertTrue(status['outdated']);self.assertTrue(status['confirmed'])
        self.save('save_memory',memory_id=m['id'],text='作者纠正但未复核来源');self.assertTrue(self.status()[0]['outdated'])
        self.save('review_memory',memory_id=m['id'],confirmed=True);self.assertFalse(self.status()[0]['outdated'])
        self.save('restore_chapter',chapter_id='p1-c5',version_id=old_version)
        self.assertTrue(self.status()[0]['outdated']);self.assertEqual(len(self.state['memory_history']),3)
    def test_workspace_source_uses_field_fingerprint_not_global_revision(self):
        m=self.memory(source={'kind':'worldbuilding','entity_id':'p1'})
        self.assertIsNone(m['source']['version_id']);rev=m['source']['workspace_revision']
        self.assertFalse(self.status()[0]['outdated'])
        self.save('save_writing_rules',content='无关规则');self.assertFalse(self.status()[0]['outdated'])
        self.save('save_worldbuilding',content='来源字段已改');self.assertTrue(self.status()[0]['outdated'])
        self.assertEqual(self.state['memories'][0]['source']['workspace_revision'],rev)
    def test_invalid_cross_book_source_position_and_stale_revision_do_not_write(self):
        for change in ({'source':{'kind':'chapter','entity_id':'p2-c1'}},{'position_chapter_id':'p2-c1'},
                       {'source':{'kind':'chapter','entity_id':'missing'}},{'kind':'unknown'},{'confirmed':'yes'}):
            before=rows(self.db)
            with self.subTest(change=change),self.assertRaises(ValueError):self.memory(**change)
            self.assertEqual(rows(self.db),before)
        self.memory();before=rows(self.db)
        with self.assertRaises(ConflictError):self.service.execute('p1','archive_memory',{'memory_id':self.state['memories'][0]['id']},expected_revision=1)
        self.assertEqual(rows(self.db),before)
    def test_unknown_future_and_missing_v2_fields_stay_strict(self):
        v1=deepcopy(self.state);v1['memories']=[]
        with self.assertRaises(ValueError):validate_workspace(v1)
        for state in (dict(self.state,workspace_version=2),dict(self.state,workspace_version=9),dict(self.state,unknown=True)):
            with self.assertRaises(ValueError):validate_workspace(state)
    def test_memory_source_and_history_tampering_rejected(self):
        self.memory();before=rows(self.db)
        for mutate in ('history','source'):
            bad=deepcopy(self.state)
            if mutate=='history':bad['memory_history'][0]['snapshot']['text']='篡改旧记录'
            else:bad['memories'][0]['source']['source_sha256']='0'*64
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):SQLiteRepository(self.db).save(bad,expected_revision=self.state['revision'])
            self.assertEqual(rows(self.db),before)
    def test_v2_backup_restore_and_copy_preserve_all_memory_history_and_sources(self):
        m=self.memory();self.save('save_memory',memory_id=m['id'],text='第二次纠正')
        package=self.root/'new.nwbak';manifest=create_backup(self.db,package)
        self.assertEqual(manifest['backup_format_version'],51);self.assertEqual(manifest['database']['workspace_version'],2)
        restored=Path(restore_backup(package,self.root/'restored')['database_path']);self.assertEqual(rows(restored),rows(self.db))
        target=self.root/'target.sqlite3';target.write_bytes(bytes.fromhex(FROZEN['database_hex']))
        result=migrate(package,target,operation_id=str(uuid4()));new=next(p['new_id'] for p in result['projects'] if p['old_id']=='p1')
        copied=NovelService(SQLiteRepository(target)).get(new);mapping={(i['kind'],i['old_id']):i['new_id'] for i in result['id_map'] if i['old_project_id']=='p1'}
        for old,fresh in zip(self.state['memories'],copied['memories']):
            self.assertEqual(fresh['id'],mapping['memory',old['id']]);self.assertEqual(fresh['text'],old['text'])
            self.assertEqual(fresh['position_chapter_id'],mapping['chapter',old['position_chapter_id']])
            self.assertEqual(fresh['source']['entity_id'],mapping['chapter',old['source']['entity_id']])
            self.assertEqual(fresh['source']['source_sha256'],old['source']['source_sha256'])
            self.assertEqual(fresh['created_at'],old['created_at']);self.assertEqual(fresh['updated_at'],old['updated_at'])
        self.assertEqual(len(copied['memory_history']),2)
        self.assertFalse(NovelService(SQLiteRepository(target)).memory_records(new)[0]['outdated'])

    def test_batch_new_history_rejects_invalid_early_snapshot_before_any_rows_change(self):
        from novel_writer.application.memories import save
        fields=dict(kind='event',title='第一版',text='原始人工记录',position_chapter_id='p1-c5',confirmed=True,
            source={'kind':'chapter','entity_id':'p1-c5'})
        draft=save(self.state,'save_memory',fields)
        draft=save(draft,'save_memory',dict(memory_id=draft['memories'][0]['id'],text='第二版合法当前值'))
        draft['memory_history'][0]['snapshot']['position_chapter_id']='missing'
        before=rows(self.db)
        with self.assertRaises(ValueError):SQLiteRepository(self.db).save(draft,expected_revision=1)
        self.assertEqual(rows(self.db),before)

class LegacyMemoryCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='novel-s3b-old-');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def test_frozen_v1_sqlite_and_package_preserve_raw_rows_and_old_profile(self):
        for label,frozen in (('full',FROZEN),('optional',FROZEN['optional_v1'])):
            with self.subTest(label=label):
                source=self.root/(label+'.sqlite3');source.write_bytes(bytes.fromhex(frozen['database_hex']));original=source.read_bytes()
                repo=SQLiteRepository(source);identifier=frozen['rows']['projects'][0][0];current=repo.get(identifier)
                self.assertEqual(current['revision'],frozen['rows']['projects'][0][2]);self.assertEqual(current['document']['project']['language'],'zh-CN')
                self.assertEqual(source.read_bytes(),original);self.assertEqual(rows(source),frozen['rows'])
                package=self.root/(label+'.nwbak');package.write_bytes(bytes.fromhex(frozen['package_hex']))
                report=preflight_backup(package)['manifest'];self.assertEqual(report['backup_format_version'],1)
                restored=Path(restore_backup(package,self.root/(label+'-restored'))['database_path']);self.assertEqual(rows(restored),frozen['rows'])
                again=create_backup(source,self.root/(label+'-again.nwbak'));self.assertEqual(again['backup_format_version'],51)
                self.assertEqual(again['counts'],report['counts']);self.assertEqual(again['database'],report['database'])
    def test_old_no_change_save_does_not_upgrade_or_create_version_time(self):
        source=self.root/'old.sqlite3';source.write_bytes(bytes.fromhex(FROZEN['optional_v1']['database_hex']));original=source.read_bytes()
        service=NovelService(SQLiteRepository(source));state=service.get('s2-a-project-one')
        same=service.execute('s2-a-project-one','save_project',{'title':state['document']['project']['title']},expected_revision=state['revision'])
        self.assertEqual(same['revision'],state['revision']);self.assertEqual(source.read_bytes(),original)
        self.assertEqual(rows(source),FROZEN['optional_v1']['rows'])
    def test_old_sqlite_migration_and_both_json_imports_are_actual_entries(self):
        frozen=FROZEN['optional_v1'];source=self.root/'old.sqlite3';source.write_bytes(bytes.fromhex(frozen['database_hex']))
        target=self.root/'target.sqlite3';target.write_bytes(bytes.fromhex(FROZEN['database_hex']))
        for kind,source_path in [('sqlite',source)]+[(key,self.root/(key+'.json')) for key in ('workspace_raw','novel_raw')]:
            if kind!='sqlite':source_path.write_text(frozen[kind],encoding='utf8')
            result=migrate(source_path,target,operation_id=str(uuid4()))
            old_id='s2-a-project-one';new_id=next(p['new_id'] for p in result['projects'] if p['old_id']==old_id)
            state=NovelService(SQLiteRepository(target)).get(new_id)
            self.assertEqual(state['document']['project']['language'],'zh-CN')
            self.assertEqual(state['document']['project']['created_at'],'2020-10-14T00:00:00+00:00')
            self.assertEqual(len(state['document']['versions']),len(json.loads(frozen['workspace_raw'])['document']['versions']))
            self.assertEqual(state['revision'],3 if kind=='sqlite' else 1)
            if kind!='sqlite':self.assertIn('project_snapshots',result['missing_scopes'])
        minimal=self.root/'minimal.json';minimal.write_text(FROZEN['minimal_novel_raw'],encoding='utf8')
        result=migrate(minimal,target,operation_id=str(uuid4()));self.assertTrue(result['normalizations'])
        self.assertEqual(rows(source),frozen['rows'])

    def test_raw_legacy_optional_collection_is_normalized_in_both_copy_passes(self):
        source=self.root/'collection.sqlite3';source.write_bytes(bytes.fromhex(FROZEN['database_hex']))
        with closing(sqlite3.connect(source)) as db,db:
            trigger=db.execute("SELECT sql FROM sqlite_master WHERE name='snapshots_no_update'").fetchone()[0]
            db.execute('DROP TRIGGER snapshots_no_update')
            for table in ('projects','project_snapshots'):
                for row in db.execute('SELECT rowid,payload FROM '+table).fetchall():
                    state=json.loads(row[1]);state['document']['characters'][1].pop('relationships')
                    db.execute('UPDATE '+table+' SET payload=? WHERE rowid=?',(json.dumps(state,ensure_ascii=False),row[0]))
            db.execute(trigger)
        before=source.read_bytes();raw=rows(source)
        package=self.root/'collection.nwbak';create_backup(source,package)
        target=self.root/'target.sqlite3';target.write_bytes(bytes.fromhex(FROZEN['database_hex']))
        for input_path in (source,package):
            with self.subTest(source=input_path.name):
                result=migrate(input_path,target,operation_id=str(uuid4()))
                identifier=next(p['new_id'] for p in result['projects'] if p['old_id']=='p1')
                state=NovelService(SQLiteRepository(target)).get(identifier)
                self.assertEqual(state['document']['characters'][1]['relationships'],[])
                self.assertEqual(state['document']['chapters'][0]['content'],json.loads(raw['projects'][0][3])['document']['chapters'][0]['content'])
        self.assertEqual(source.read_bytes(),before);self.assertEqual(rows(source),raw)

if __name__=='__main__':unittest.main()
