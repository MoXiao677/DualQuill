"""端到端包级语义反例与零数量往返，不使用作者数据库。"""
from contextlib import closing
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT/'tests/fixtures'))
from s2_a_samples import create_fixture_database
from s2_b_samples import build_runtime_dataset
from novel_writer.application.backups import BackupError, create_backup, preflight_backup, restore_backup
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository


def sql_rows(path):
    with closing(sqlite3.connect(path)) as connection:
        return {table:connection.execute('SELECT * FROM '+table+' ORDER BY 1,2').fetchall()
                for table in ('projects','project_snapshots','skills')}


class BackupPackageCases(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='novel-s2-b-package-cases-')
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.dataset=build_runtime_dataset()

    def package_for(self,dataset,number,mutation=None):
        source=self.root/('source-'+str(number)+'.sqlite3')
        # 从合法manifest只替换snapshot并重算hash，验证不是只靠摘要识别坏数据。
        if not hasattr(self,'manifest'):
            original=self.root/'valid.sqlite3';create_fixture_database(original,self.dataset)
            archive=self.root/'valid.nwbak';create_backup(original,archive)
            with zipfile.ZipFile(archive) as package:self.manifest=json.loads(package.read('manifest.json'));self.drafts=package.read('drafts.json')
        create_fixture_database(source,dataset)
        if mutation:
            with closing(sqlite3.connect(source)) as connection,connection:mutation(connection)
        data=source.read_bytes();manifest=deepcopy(self.manifest)
        manifest['entries'][0].update(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
        archive=self.root/('bad-'+str(number)+'.nwbak')
        with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as package:
            package.writestr('manifest.json',json.dumps(manifest));package.writestr('snapshot.sqlite3',data);package.writestr('drafts.json',self.drafts)
        return archive

    def rejected(self,package,number):
        target=self.root/('target-'+str(number));before=package.read_bytes()
        for operation in (lambda:preflight_backup(package),lambda:restore_backup(package,target)):
            with self.assertRaises(BackupError):operation()
        self.assertFalse(target.exists());self.assertEqual(before,package.read_bytes())
        self.assertFalse(list(self.root.glob('.novel-backup-*')))

    def test_rehashed_invalid_current_history_and_version_references_are_refused(self):
        changes=[
            lambda s:s['ideas'].update(missing='虚构非法IDEA引用'),
            lambda s:s['document']['chapters'][0].update(current_version_id='missing-version'),
            lambda s:s['document']['book_outline']['volumes'][0]['chapter_ids'].append('missing-chapter'),
            lambda s:s['document']['chapter_outlines'][0].update(chapter_id='missing-chapter'),
            lambda s:s['document']['characters'][0]['relationships'][0].update(target_character_id='missing-character'),
        ]
        for index,change in enumerate(changes):
            with self.subTest(index=index):
                dataset=deepcopy(self.dataset)
                for row in dataset['projects']+dataset['project_snapshots']:change(row['payload'])
                self.rejected(self.package_for(dataset,index),index)
        dataset=deepcopy(self.dataset)
        for row in dataset['projects']+dataset['project_snapshots']:
            for version in row['payload']['document']['versions']:
                if version['entity_type']=='book_outline':version['snapshot']['volumes'][0]['chapter_ids'].append('missing-only-in-history')
        self.rejected(self.package_for(dataset,99),99)

    def test_rehashed_unknown_schema_workspace_and_document_versions_are_refused(self):
        for index,(key,value) in enumerate((('workspace_version',2),('workspace_version',True),('document',2))):
            dataset=deepcopy(self.dataset)
            for row in dataset['projects']+dataset['project_snapshots']:
                if key=='document':row['payload']['document']['schema_version']=value
                else:row['payload'][key]=value
            self.rejected(self.package_for(dataset,index),index)
        for index,sql in enumerate(('PRAGMA user_version=2','CREATE TABLE unknown_business(x)',
                                    'DROP TRIGGER snapshots_no_update'),10):
            self.rejected(self.package_for(self.dataset,index,lambda c:c.execute(sql)),index)

    def test_sql_foreign_key_violation_is_refused_before_any_target_write(self):
        def orphan(connection):
            connection.execute('PRAGMA foreign_keys=OFF')
            connection.execute("INSERT INTO project_snapshots SELECT 'missing-project',revision,payload,saved_at FROM project_snapshots LIMIT 1")
        self.rejected(self.package_for(self.dataset,1,orphan),1)

    def test_empty_library_skills_only_and_project_without_outline_roundtrip(self):
        for index,kind in enumerate(('empty','skills-only','no-outline')):
            with self.subTest(kind=kind):
                source=self.root/(kind+'.sqlite3')
                dataset=deepcopy(self.dataset);dataset['projects']=[];dataset['project_snapshots']=[]
                if kind!='skills-only':dataset['skills']=[]
                create_fixture_database(source,dataset)
                if kind=='no-outline':NovelService(SQLiteRepository(source)).create(title='虚构无大纲小说')
                expected=sql_rows(source);archive=self.root/(kind+'.nwbak')
                manifest=create_backup(source,archive)
                result=restore_backup(archive,self.root/('restore-'+kind))
                self.assertEqual(sql_rows(result['database_path']),expected)
                again=create_backup(result['database_path'],self.root/(kind+'-again.nwbak'))
                self.assertEqual(manifest['counts'],again['counts'])


if __name__=='__main__':unittest.main()
