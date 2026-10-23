"""S2-B包与真实磁盘恢复：只使用本测试拥有的虚构临时目录。"""
from contextlib import closing
import hashlib
from importlib import import_module, util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests/fixtures'))
from s2_a_samples import build_dataset, create_fixture_database
from s2_b_samples import build_runtime_dataset
from novel_writer.storage.sqlite_repository import SQLiteRepository
from novel_writer.application.service import NovelService


def rows(path):
    with closing(sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True)) as connection:
        return {name: connection.execute('SELECT * FROM ' + name + ' ORDER BY 1,2').fetchall()
                for name in ('projects', 'project_snapshots', 'skills')}


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(util.find_spec('novel_writer.application.backups'), '缺少正式完整备份/独立恢复业务')
        self.module = import_module('novel_writer.application.backups')
        self.temp = tempfile.TemporaryDirectory(prefix='novel-s2-b-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'fictional.sqlite3'
        create_fixture_database(self.source, build_runtime_dataset())
        self.archive = self.root / 'complete.nwbak'
        self.target = self.root / 'restored'

    def test_roundtrip_preserves_every_sql_cell_and_hash(self):
        before = self.source.read_bytes()
        manifest = self.module.create_backup(self.source, self.archive)
        with zipfile.ZipFile(self.archive) as package:
            self.assertEqual(set(package.namelist()), {'manifest.json', 'snapshot.sqlite3', 'drafts.json'})
            self.assertEqual(json.loads(package.read('manifest.json')), manifest)
            snapshot = package.read('snapshot.sqlite3')
        self.assertEqual(manifest['entries'][0]['bytes'], len(snapshot))
        self.assertEqual(manifest['entries'][0]['sha256'], hashlib.sha256(snapshot).hexdigest())
        self.assertEqual(manifest['database']['schema_sha256'], 'babc3a8d5fe36b6cca4af8b639db17529f5d3d6e2b2711a9623e31f281948bf2')
        restored = self.module.restore_backup(self.archive, self.target)
        database = Path(restored['database_path'])
        self.assertEqual(rows(database), rows(self.source))
        self.assertEqual(self.source.read_bytes(), before)
        again = self.module.create_backup(database, self.root / 'again.nwbak')
        self.assertEqual(again['counts'], manifest['counts'])
        self.assertNotEqual(again['backup_id'], manifest['backup_id'])

    def test_legacy_backup_without_drafts_still_restores(self):
        self.module.create_backup(self.source, self.archive)
        with zipfile.ZipFile(self.archive) as package:
            manifest = json.loads(package.read('manifest.json'))
            snapshot = package.read('snapshot.sqlite3')
        manifest['backup_format_version'] = manifest['database']['workspace_version']
        manifest['exclusions'].append('in_memory_drafts')
        manifest['entries'] = manifest['entries'][:1]
        legacy = self.root / 'legacy-v1.nwbak'
        with zipfile.ZipFile(legacy, 'w', compression=zipfile.ZIP_DEFLATED) as package:
            package.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False))
            package.writestr('snapshot.sqlite3', snapshot)
        restored = self.module.restore_backup(legacy, self.target)
        self.assertTrue(restored['verified'])
        self.assertEqual(rows(Path(restored['database_path'])), rows(self.source))
        self.assertFalse((self.target / 'drafts').exists())

    def test_restored_database_can_edit_save_restore_and_reopen(self):
        self.module.create_backup(self.source, self.archive)
        database = Path(self.module.restore_backup(self.archive, self.target)['database_path'])
        service = NovelService(SQLiteRepository(database))
        state = service.get('s2-a-project-one')
        chapter = state['document']['chapters'][0]
        state = service.execute(state['document']['project']['id'], 'save_chapter',
                                {'chapter_id': chapter['id'], 'title': chapter['title'], 'content': '\n独立恢复后编辑。\n',
                                 'status': 'draft', 'authorize_confirmed': True}, expected_revision=state['revision'])
        reopened = NovelService(SQLiteRepository(database)).get('s2-a-project-one')
        self.assertEqual(reopened, state)
        self.assertEqual(reopened['document']['chapters'][0]['content'], '\n独立恢复后编辑。\n')
        self.assertEqual(SQLiteRepository(self.source).get('s2-a-project-one')['revision'], 3)

    def test_existing_targets_are_never_overwritten(self):
        self.module.create_backup(self.source, self.archive)
        original = self.archive.read_bytes()
        with self.assertRaises(self.module.BackupError):
            self.module.create_backup(self.source, self.archive)
        self.assertEqual(self.archive.read_bytes(), original)
        self.target.mkdir()
        sentinel = self.target / 'keep.txt'
        sentinel.write_bytes(b'fictional-existing-directory')
        with self.assertRaises(self.module.BackupError):
            self.module.restore_backup(self.archive, self.target)
        self.assertEqual(sentinel.read_bytes(), b'fictional-existing-directory')
        self.assertEqual(list(self.target.iterdir()), [sentinel])

    def test_missing_source_is_not_initialized(self):
        missing = self.root / 'missing.sqlite3'
        with self.assertRaises(self.module.BackupError):
            self.module.create_backup(missing, self.archive)
        self.assertFalse(missing.exists())
        self.assertFalse(self.archive.exists())

    def test_write_failure_leaves_no_package_or_temporary_data(self):
        before = rows(self.source)
        with patch.object(self.module, '_write_all', side_effect=OSError('fictional disk failure')):
            with self.assertRaises(self.module.BackupError):
                self.module.create_backup(self.source, self.archive)
        self.assertEqual(rows(self.source), before)
        self.assertEqual(list(self.root.iterdir()), [self.source])

    def test_restore_insert_failure_rolls_back_and_cleans_stage(self):
        self.module.create_backup(self.source, self.archive)
        with patch.object(self.module, '_insert_row', side_effect=sqlite3.OperationalError('fictional SQL failure')):
            with self.assertRaises(self.module.BackupError):
                self.module.restore_backup(self.archive, self.target)
        self.assertFalse(self.target.exists())
        self.assertEqual(set(path.name for path in self.root.iterdir()), {'fictional.sqlite3', 'complete.nwbak'})

    def test_credentials_and_neighbor_files_are_never_read(self):
        (self.root / 'providers.dpapi').write_bytes(b'fictional-credential-must-not-export')
        (self.root / '.env').write_bytes(b'fictional-environment-must-not-export')
        with patch('novel_writer.application.provider_connections.ProviderConnections', side_effect=AssertionError('must not read credentials')):
            self.module.create_backup(self.source, self.archive)
            self.module.restore_backup(self.archive, self.target)
        with zipfile.ZipFile(self.archive) as package:
            text = package.read('manifest.json') + package.read('snapshot.sqlite3')
            self.assertNotIn(b'fictional-credential-must-not-export', text)
            self.assertNotIn(b'fictional-environment-must-not-export', text)

    def alter_package(self, mutate=None, *, snapshot=None, extra=None):
        self.module.create_backup(self.source, self.archive)
        with zipfile.ZipFile(self.archive) as package:
            manifest = json.loads(package.read('manifest.json'))
            data = package.read('snapshot.sqlite3') if snapshot is None else snapshot
            drafts = package.read('drafts.json')
        if snapshot is not None:
            manifest['entries'][0].update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        if mutate:
            mutate(manifest)
        changed = self.root / 'damaged.nwbak'
        with zipfile.ZipFile(changed, 'w', compression=zipfile.ZIP_DEFLATED) as package:
            package.writestr('manifest.json', json.dumps(manifest))
            package.writestr('snapshot.sqlite3', data)
            package.writestr('drafts.json', drafts)
            if extra:
                package.writestr(*extra)
        return changed

    def assert_refused(self, archive):
        with self.assertRaises(self.module.BackupError):
            self.module.restore_backup(archive, self.target)
        self.assertFalse(self.target.exists())
        self.assertFalse(any(path.name.startswith('.novel-backup-') for path in self.root.iterdir()))

    def test_bad_checksum_is_refused(self):
        self.assert_refused(self.alter_package(lambda value: value['entries'][0].update(sha256='0'*64)))

    def test_future_backup_version_is_refused(self):
        self.assert_refused(self.alter_package(lambda value: value.update(backup_format_version=52)))

    def test_unknown_format_is_refused(self):
        self.assert_refused(self.alter_package(lambda value: value.update(format='unknown')))

    def test_corrupt_sqlite_with_recalculated_hash_is_refused(self):
        self.assert_refused(self.alter_package(snapshot=b'not a SQLite database'))

    def test_missing_or_truncated_package_is_refused(self):
        missing = self.root / 'missing.nwbak'
        self.assert_refused(missing)
        self.module.create_backup(self.source, self.archive)
        broken = self.root / 'truncated.nwbak'
        broken.write_bytes(self.archive.read_bytes()[:-22])
        self.assert_refused(broken)

    def test_malicious_path_is_not_extracted(self):
        self.assert_refused(self.alter_package(extra=('../outside.txt', b'bad')))
        self.assertFalse((self.root.parent / 'outside.txt').exists())

    def test_resource_limit_refuses_package_without_partial_target(self):
        self.module.create_backup(self.source, self.archive)
        with self.assertRaises(self.module.BackupError):
            self.module.restore_backup(self.archive, self.target, limits=self.module.Limits(snapshot_bytes=64))
        self.assertFalse(self.target.exists())

    def test_no_space_refuses_without_success_file(self):
        with patch.object(self.module.shutil, 'disk_usage', return_value=(100, 100, 0)):
            with self.assertRaises(self.module.BackupError):
                self.module.create_backup(self.source, self.archive)
        self.assertFalse(self.archive.exists())

    def test_publish_race_preserves_other_process_target(self):
        self.module.create_backup(self.source, self.archive)
        original = self.module._publish
        def rival(stage, destination):
            Path(destination).mkdir()
            (Path(destination) / 'rival.txt').write_bytes(b'rival')
            return original(stage, destination)
        with patch.object(self.module, '_publish', side_effect=rival):
            with self.assertRaises(self.module.BackupError):
                self.module.restore_backup(self.archive, self.target)
        self.assertEqual((self.target / 'rival.txt').read_bytes(), b'rival')
        self.assertEqual(list(self.target.iterdir()), [self.target / 'rival.txt'])

    def test_cancel_and_deadline_leave_no_output(self):
        for options in ({'cancel': lambda: True}, {'limits': self.module.Limits(seconds=0)}):
            with self.subTest(options=options), self.assertRaises(self.module.BackupError):
                self.module.create_backup(self.source, self.archive, **options)
            self.assertFalse(self.archive.exists())

    def test_wal_committed_data_is_captured_and_uncommitted_data_excluded(self):
        with closing(sqlite3.connect(self.source)) as writer:
            self.assertEqual(writer.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
            writer.execute('PRAGMA wal_autocheckpoint=0')
            repository = SQLiteRepository(self.source)
            state = repository.get('s2-a-project-one')
            state['worldbuilding'] = 'WAL已提交虚构内容'
            repository.save(state, expected_revision=3)
            writer.execute('BEGIN IMMEDIATE')
            writer.execute("UPDATE projects SET title='未提交虚构标题' WHERE id='s2-a-project-one'")
            self.module.create_backup(self.source, self.archive)
            database = self.module.restore_backup(self.archive, self.target)['database_path']
            restored = SQLiteRepository(database).get('s2-a-project-one')
            self.assertEqual(restored['revision'], 4)
            self.assertEqual(restored['worldbuilding'], 'WAL已提交虚构内容')
            self.assertNotEqual(restored['document']['project']['title'], '未提交虚构标题')
            writer.rollback()

    def test_concurrent_commit_produces_one_complete_state_and_frozen_manifest(self):
        from novel_writer.application.skill_import import SkillLibrary
        SkillLibrary(self.source).import_files([{'path':'SKILL.md','content':'# 虚构并发样本\n'+'a'*600000}])
        changed = False
        def progress(stage, done, total):
            nonlocal changed
            if not changed and done < total:
                changed = True
                state = SQLiteRepository(self.source).get('s2-a-project-one')
                state['worldbuilding'] = '并发提交虚构世界观'
                SQLiteRepository(self.source).save(state, expected_revision=3)
        manifest = self.module.create_backup(self.source,self.archive,progress=progress)
        self.assertTrue(changed, '必须实际在分步采集期间完成源写入')
        database = self.module.restore_backup(self.archive,self.target)['database_path']
        restored = SQLiteRepository(database).get('s2-a-project-one')
        self.assertIn(restored['revision'], (3,4))
        if restored['revision']==4:
            self.assertEqual(restored['worldbuilding'],'并发提交虚构世界观')
        self.assertEqual(next(item for item in manifest['counts']['projects'] if item['project_id']=='s2-a-project-one')['revision'],restored['revision'])

    def test_fsync_failure_preserves_source_and_no_success_package(self):
        before=rows(self.source)
        with patch.object(self.module,'_fsync_file',side_effect=OSError('fictional-private-error')):
            with self.assertRaises(self.module.BackupError) as caught:
                self.module.create_backup(self.source,self.archive)
        self.assertNotIn('fictional-private-error',str(caught.exception))
        self.assertFalse(self.archive.exists());self.assertEqual(rows(self.source),before)

    def test_mid_transaction_failure_removes_all_partial_rows(self):
        self.module.create_backup(self.source,self.archive)
        insert=self.module._insert_row
        inserted=[]
        def fail(connection,table,row):
            if len(inserted)==4:
                raise sqlite3.OperationalError('fictional mid transaction')
            insert(connection,table,row);inserted.append(table)
        with patch.object(self.module,'_insert_row',side_effect=fail):
            with self.assertRaises(self.module.BackupError):
                self.module.restore_backup(self.archive,self.target)
        self.assertEqual(len(inserted),4);self.assertFalse(self.target.exists())
        self.assertFalse(any(path.name.startswith('.novel-backup-') for path in self.root.iterdir()))

    def test_short_zip_write_does_not_publish_truncated_output(self):
        original=zipfile._ZipWriteFile.write
        def short(stream,data):
            return original(stream,data[:-1])
        with patch.object(zipfile._ZipWriteFile,'write',short):
            with self.assertRaises(self.module.BackupError):
                self.module.create_backup(self.source,self.archive)
        self.assertFalse(self.archive.exists())

    def test_duplicate_members_missing_member_and_symlink_are_refused(self):
        self.module.create_backup(self.source,self.archive)
        with zipfile.ZipFile(self.archive) as package:
            manifest=package.read('manifest.json');snapshot=package.read('snapshot.sqlite3');drafts=package.read('drafts.json')
        for mode in ('duplicate','missing','symlink','many'):
            with self.subTest(mode=mode):
                bad=self.root/(mode+'.nwbak')
                with zipfile.ZipFile(bad,'w') as package:
                    package.writestr('manifest.json',manifest)
                    if mode!='missing':
                        item=zipfile.ZipInfo('snapshot.sqlite3')
                        if mode=='symlink':
                            item.create_system=3;item.external_attr=(0o120777<<16)
                        package.writestr(item,snapshot)
                    if mode!='missing':package.writestr('drafts.json',drafts)
                    if mode=='duplicate':
                        import warnings
                        with warnings.catch_warnings():
                            warnings.simplefilter('ignore');package.writestr('manifest.json',manifest)
                    if mode=='many':
                        for index in range(10):
                            package.writestr('extra'+str(index),b'')
                self.assert_refused(bad)

    def test_json_duplicate_keys_and_boolean_version_are_refused(self):
        self.module.create_backup(self.source,self.archive)
        with zipfile.ZipFile(self.archive) as package:
            text=package.read('manifest.json').decode();snapshot=package.read('snapshot.sqlite3');drafts=package.read('drafts.json')
        import re as _re
        for text_value in (_re.sub(r'"backup_format_version":\s*[0-9]+','"backup_format_version": true',text,count=1),
                           text.replace('{','{"format":"duplicate",',1)):
            bad=self.root/('json-'+str(len(text_value))+'.nwbak')
            with zipfile.ZipFile(bad,'w') as package:
                package.writestr('manifest.json',text_value);package.writestr('snapshot.sqlite3',snapshot);package.writestr('drafts.json',drafts)
            self.assert_refused(bad)

    def test_sqlite_integrity_error_with_valid_header_and_rehashed_package_is_refused(self):
        with closing(sqlite3.connect(self.source)) as connection:
            page=connection.execute("SELECT rootpage FROM sqlite_master WHERE name='projects'").fetchone()[0]
            page_size=connection.execute('PRAGMA page_size').fetchone()[0]
        broken=bytearray(self.source.read_bytes())
        broken[(page-1)*page_size+3:(page-1)*page_size+5]=b'\xff\xff'
        package=self.alter_package(snapshot=bytes(broken))
        with self.assertRaises(self.module.BackupError) as caught:
            self.module.restore_backup(package,self.target)
        self.assertIn('integrity',str(caught.exception));self.assertFalse(self.target.exists())

    def test_high_compression_legitimate_history_is_accepted(self):
        large=build_runtime_dataset()
        for row in large['projects']+large['project_snapshots']:
            row['payload']['worldbuilding']='重复虚构设定。'*20000
        source=self.root/'compressed.sqlite3'
        create_fixture_database(source,large)
        self.module.create_backup(source,self.archive)
        self.assertLess(self.archive.stat().st_size,source.stat().st_size//20)
        restored=self.module.restore_backup(self.archive,self.target)['database_path']
        self.assertEqual(rows(restored),rows(source))


if __name__ == '__main__':
    unittest.main()
