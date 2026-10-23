"""S2-C：独立虚构库，全历史逆映射、事务、Skills及旧格式。"""
from contextlib import closing
from copy import deepcopy
from importlib import import_module, util
import json
import os
from pathlib import Path
import sqlite3
import sys
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests/fixtures'))
from s2_a_samples import create_fixture_database, transform_fixture_ids, TABLE_COLUMNS
from s2_b_samples import build_runtime_dataset
from novel_writer.application.backups import BackupError, create_backup
from novel_writer.storage.backup_validation import validate_database
from novel_writer.storage.sqlite_repository import SQLiteRepository


def dataset(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True)) as db:
        result = {'fixture_version': 1}
        for table, columns in TABLE_COLUMNS.items():
            result[table] = []
            for values in db.execute('SELECT '+','.join(columns)+' FROM '+table+' ORDER BY 1,2'):
                row = dict(zip(columns, values))
                for key in ('payload', 'files_json'):
                    if key in row:
                        row[key] = json.loads(row[key])
                result[table].append(row)
        return result


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(util.find_spec('novel_writer.application.migrations'), 'S2-C实际迁移业务尚缺失')
        self.m = import_module('novel_writer.application.migrations')
        self.temp = tempfile.TemporaryDirectory(prefix='novel-s2-c-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root/'source.sqlite3'
        self.target = self.root/'target.sqlite3'
        self.original = build_runtime_dataset()
        create_fixture_database(self.source, self.original)
        empty = {'projects': [], 'project_snapshots': [], 'skills': []}
        create_fixture_database(self.target, empty)
        self.op = str(uuid4())

    def migrate(self, source=None, **kwargs):
        return self.m.migrate(source or self.source, self.target, operation_id=self.op, **kwargs)

    def test_complete_library_inverse_mapping_preserves_every_field_and_source(self):
        before = self.source.read_bytes()
        result = self.migrate()
        self.assertTrue(result['verified'])
        self.assertEqual(result['state'], 'completed')
        copied = dataset(self.target)
        reverse = {(entry['new_project_id'], entry['kind'], entry['new_id']): entry['old_id']
                   for entry in result['id_map']}
        restored = transform_fixture_ids(copied, lambda p,k,i: reverse[(p,k,i)])
        # SQL记录无列表顺序；按逆映射后的原主键核对，领域内各列表仍逐项严格比较。
        for table,key in (('projects','id'),('project_snapshots','project_id')):
            restored[table].sort(key=lambda row:(row[key],row.get('revision',0)))
        self.assertEqual(restored, dataset(self.source))
        self.assertEqual(before, self.source.read_bytes())
        self.assertEqual(len(result['projects']), 2)
        self.assertEqual(len(copied['project_snapshots']), 6)
        self.assertEqual(len({e['new_id'] for e in result['id_map']}), len(result['id_map']))
        validate_database(self.target)

    def test_history_only_ids_are_mapped_once_and_text_is_untouched(self):
        data = deepcopy(self.original)
        for row in data['projects'] + data['project_snapshots']:
            state = row['payload']
            if state['revision'] > 1:
                doc = state['document']
                doc['chapters'] = doc['chapters'][:1]
                doc['book_outline']['volumes'] = doc['book_outline']['volumes'][:1]
                state['ideas'].pop('shared-chapter-2')
        other = self.root/'history.sqlite3'
        create_fixture_database(other, data)
        result = self.migrate(other)
        entry = next(e for e in result['id_map'] if e['old_project_id']=='s2-a-project-one' and e['old_id']=='shared-chapter-2')
        early = dataset(self.target)['project_snapshots']
        early = next(r for r in early if r['project_id']==entry['new_project_id'] and r['revision']==1)['payload']
        self.assertEqual(early['document']['book_outline']['volumes'][1]['chapter_ids'], [entry['new_id']])
        self.assertIn('shared-chapter-1', early['document']['chapters'][0]['content'])

    def test_existing_projects_unchanged_and_copied_edits_are_isolated(self):
        self.target.unlink()
        create_fixture_database(self.target, self.original)
        before = dataset(self.target)
        result = self.migrate(project_ids=['s2-a-project-one'])
        repo = SQLiteRepository(self.target)
        new = result['projects'][0]['new_id']
        state = repo.get(new)
        state['worldbuilding'] = '复制后独立编辑'
        repo.save(state, expected_revision=3)
        after = dataset(self.target)
        for table, key in (('projects','id'), ('project_snapshots','project_id')):
            self.assertEqual([r for r in after[table] if r[key] != new], before[table])
        self.assertEqual(dataset(self.source), before)
        self.assertEqual(repo.get(new)['revision'], 4)

    def test_skills_same_id_exact_reuse_conflict_remap_and_no_name_dedup(self):
        data = deepcopy(self.original)
        data['projects'] = []; data['project_snapshots'] = []
        data['skills'] = data['skills'][:2]
        data['skills'][1]['description'] = '相同ID不同元信息'
        self.target.unlink(); create_fixture_database(self.target, data)
        before = dataset(self.target)['skills']
        result = self.migrate()
        actions = {s['old_id']:s for s in result['skills']}
        self.assertEqual(actions['s2-a-skill-1']['action'], 'reused')
        self.assertEqual(actions['s2-a-skill-2']['action'], 'remapped')
        self.assertEqual(actions['s2-a-skill-3']['action'], 'inserted')
        final = dataset(self.target)['skills']
        self.assertEqual(len(final), 4)
        self.assertEqual([s for s in final if s['id'] in {x['id'] for x in before}], before)

    def test_every_insert_failure_rolls_back_all_tables(self):
        original_insert = self.m._insert_row
        for fail_table in TABLE_COLUMNS:
            with self.subTest(table=fail_table):
                before = dataset(self.target)
                def failing(db, table, row):
                    if table == fail_table:
                        raise sqlite3.OperationalError('fictional disk full')
                    return original_insert(db, table, row)
                with patch.object(self.m, '_insert_row', side_effect=failing):
                    with self.assertRaises(BackupError): self.migrate()
                self.assertEqual(dataset(self.target), before)
                self.assertEqual(self.m.migration_status(self.target, self.op)['state'], 'not_applied')
        self.assertEqual(self.migrate()['state'], 'completed')

    def test_precommit_failure_and_cancel_roll_back(self):
        before = dataset(self.target)
        with patch.object(self.m, '_before_commit', side_effect=OSError('fictional fsync')):
            with self.assertRaises(BackupError): self.migrate()
        self.assertEqual(dataset(self.target), before)
        with self.assertRaises(BackupError): self.migrate(cancel=lambda: True)
        self.assertEqual(dataset(self.target), before)

    def test_conflicts_are_rechecked_after_preflight_before_locked_insert(self):
        real = self.m._lock_target
        def race(db, check):
            with closing(sqlite3.connect(self.target)) as other, other:
                other.execute("UPDATE skills SET description='race' WHERE id='s2-a-skill-1'")
            return real(db, check)
        data = {'projects': [], 'project_snapshots': [], 'skills': self.original['skills'][:1]}
        self.target.unlink(); create_fixture_database(self.target, data)
        with patch.object(self.m, '_lock_target', side_effect=race): result = self.migrate()
        self.assertEqual(result['skills'][0]['action'], 'remapped')
        self.assertEqual(next(s for s in dataset(self.target)['skills'] if s['id']=='s2-a-skill-1')['description'], 'race')

    def test_lock_prevents_other_writer_until_atomic_commit(self):
        real = self.m._before_commit
        observations = []
        def probe(db, check):
            with closing(sqlite3.connect(self.target, timeout=.01)) as other:
                try: other.execute('BEGIN IMMEDIATE')
                except sqlite3.OperationalError: observations.append('locked')
            return real(db, check)
        with patch.object(self.m, '_before_commit', side_effect=probe): self.migrate()
        self.assertEqual(observations, ['locked'])

    def test_retry_and_restart_status_are_verified_without_duplicate_import(self):
        result = self.migrate()
        before = dataset(self.target)
        again = self.migrate()
        self.assertEqual(again['state'], 'already_present')
        self.assertEqual(again['id_map'], result['id_map'])
        self.assertEqual(dataset(self.target), before)
        self.assertEqual(self.m.migration_status(self.target, self.op)['state'], 'already_present')
        repo = SQLiteRepository(self.target)
        state = repo.get(result['projects'][0]['new_id']); state['worldbuilding'] += 'edited'
        repo.save(state, expected_revision=state['revision'])
        with self.assertRaises(BackupError): self.migrate()
        with self.assertRaises(BackupError): self.m.migration_status(self.target, self.op)

    def test_identity_rejects_different_input_and_selection_even_after_rollback(self):
        with patch.object(self.m, '_before_commit', side_effect=OSError('stop')):
            with self.assertRaises(BackupError): self.migrate()
        with self.assertRaises(BackupError): self.migrate(project_ids=['s2-a-project-one'])
        self.assertEqual(len(dataset(self.target)['projects']), 0)

    def test_copy_in_same_database_keeps_source_and_retries_same_selection(self):
        self.target = self.source
        before = dataset(self.source)
        result = self.migrate(project_ids=['s2-a-project-one'])
        self.assertEqual(len(dataset(self.source)['projects']), 3)
        self.assertEqual(self.migrate(project_ids=['s2-a-project-one'])['state'], 'already_present')
        self.assertTrue(all(s['action']=='reused' for s in result['skills']))
        old_ids = {r['id'] for r in before['projects']}
        self.assertEqual([r for r in dataset(self.source)['projects'] if r['id'] in old_ids], before['projects'])

    def test_package_and_sqlite_identified_by_content(self):
        package = self.root/'wrong.json'
        create_backup(self.source, package)
        result = self.migrate(package)
        self.assertEqual(result['source_format'], 'backup_v51')
        self.assertEqual(result['missing_scopes'], [])

    def test_wal_commits_are_included(self):
        with closing(sqlite3.connect(self.source)) as holder:
            holder.execute('PRAGMA journal_mode=WAL'); holder.execute('PRAGMA wal_autocheckpoint=0')
            state = SQLiteRepository(self.source).get('s2-a-project-one')
            state['worldbuilding'] = 'WAL已提交'; SQLiteRepository(self.source).save(state, expected_revision=3)
            result = self.migrate()
        new = next(p['new_id'] for p in result['projects'] if p['old_id']=='s2-a-project-one')
        self.assertEqual(SQLiteRepository(self.target).get(new)['worldbuilding'], 'WAL已提交')

    def test_legacy_workspace_reports_lost_scope_and_keeps_available_versions(self):
        state = deepcopy(self.original['projects'][0]['payload'])
        source = self.root/'workspace.bin'; source.write_text(json.dumps(state,ensure_ascii=False),encoding='utf8')
        result = self.migrate(source)
        self.assertEqual(result['source_format'], 'workspace_json_v1')
        self.assertIn('project_snapshots', result['missing_scopes']); self.assertIn('skills', result['missing_scopes'])
        new = SQLiteRepository(self.target).get(result['projects'][0]['new_id'])
        self.assertEqual(new['revision'], 1)
        self.assertEqual(len(new['document']['versions']), len(state['document']['versions']))
        self.assertEqual(new['worldbuilding'], state['worldbuilding'])
        self.assertEqual(result['original_revision'], 3)
        self.assertEqual(self.migrate(source)['state'], 'already_present')

    def test_legacy_novel_defaults_are_deterministic_and_reported(self):
        source = self.root/'novel.json'
        source.write_text(json.dumps({'schema_version':1,'project':{'title':'虚构旧小说'}}),encoding='utf8')
        result = self.migrate(source)
        self.assertEqual(result['source_format'], 'novel_json_v1')
        self.assertTrue(result['normalizations'])
        for scope in ('ideas','worldbuilding','writing_rules','project_snapshots','skills'):
            self.assertIn(scope, result['missing_scopes'])
        self.assertEqual(self.migrate(source)['state'], 'already_present')

    def test_legacy_future_duplicate_unknown_invalid_references_rejected(self):
        invalid = [b'{"schema_version":1,"schema_version":1}', b'{"schema_version":2}',
                   b'{"workspace_version":2}', b'{"schema_version":1,"project":{"title":"x"},"unknown":1}',
                   b'{"schema_version":1,"project":{"title":"x"},"chapters":null}']
        for index, content in enumerate(invalid):
            source = self.root/f'invalid-{index}'; source.write_bytes(content)
            with self.subTest(index=index):
                with self.assertRaises(BackupError): self.migrate(source)
                self.assertEqual(len(dataset(self.target)['projects']), 0)

    def test_missing_or_invalid_existing_target_is_never_created_or_repaired(self):
        self.target.unlink()
        with self.assertRaises(BackupError): self.migrate()
        self.assertFalse(self.target.exists())
        self.target.write_bytes(b'fictional sentinel')
        with self.assertRaises(BackupError): self.migrate()
        self.assertEqual(self.target.read_bytes(), b'fictional sentinel')

    def test_invalid_source_history_and_schema_are_rejected_before_target_change(self):
        with closing(sqlite3.connect(self.source)) as db, db:
            db.execute('DROP TRIGGER snapshots_no_update')
        before = dataset(self.target)
        with self.assertRaises(BackupError): self.migrate()
        self.assertEqual(dataset(self.target), before)

    def test_contract_zero_project_empty_and_skills_only_are_truthful(self):
        for include_skills in (False, True):
            with self.subTest(skills=include_skills):
                source = self.root/('skills-only.sqlite3' if include_skills else 'empty.sqlite3')
                create_fixture_database(source,{'projects':[],'project_snapshots':[],
                    'skills':self.original['skills'] if include_skills else []})
                identity = str(uuid4())
                result = self.m.migrate(source,self.target,operation_id=identity)
                self.assertEqual(result['projects'],[])
                self.assertEqual(len(dataset(self.target)['projects']),0)
                self.assertEqual(result['no_data_change'],not include_skills)
                self.assertEqual(self.m.migrate(source,self.target,operation_id=identity)['state'],'already_present')

    def test_contract_same_package_new_request_reuses_complete_import(self):
        archive = self.root/'same.nwbak'; create_backup(self.source,archive)
        first = self.migrate(archive)
        self.op = str(uuid4())
        second = self.migrate(archive)
        self.assertEqual(second['state'],'already_present')
        self.assertEqual(second['id_map'],first['id_map'])
        self.assertEqual(len(dataset(self.target)['projects']),2)

    def test_contract_receipt_failure_and_corruption_never_write_or_guess(self):
        before = dataset(self.target)
        with patch.object(self.m,'_save',side_effect=OSError('fictional receipt full')):
            with self.assertRaises(BackupError): self.migrate()
        self.assertEqual(dataset(self.target),before)
        result = self.migrate()
        self.m._receipt_path(self.target.resolve(),self.op).write_text('{}',encoding='utf8')
        with self.assertRaises(BackupError): self.migrate()
        self.assertEqual(len(dataset(self.target)['projects']),len(result['projects']))

    def test_contract_preview_keeps_target_unchanged_and_binds_commit_plan(self):
        before = dataset(self.target)
        preview = self.migrate(preview=True)
        self.assertEqual(preview['state'],'ready'); self.assertFalse(preview['verified'])
        self.assertEqual(dataset(self.target),before)
        self.assertEqual(self.m.migration_status(self.target,self.op)['state'],'not_applied')
        done = self.migrate()
        self.assertEqual(done['id_map'],preview['id_map'])

    def test_contract_explicit_skills_scope_does_not_invent_project_ownership(self):
        result = self.migrate(project_ids=['s2-a-project-one'],skills_mode='selected',skill_ids=['s2-a-skill-2'])
        self.assertEqual(len(result['projects']),1)
        self.assertEqual([s['old_id'] for s in result['skills']],['s2-a-skill-2'])
        self.assertEqual(result['skills_scope'],'selected')
        self.assertEqual(result['excluded_project_ids'],['s2-a-project-two'])
        self.assertEqual(result['excluded_skill_ids'],['s2-a-skill-1','s2-a-skill-3'])
        self.assertEqual(len(dataset(self.target)['skills']),1)

    def test_real_process_kill_before_and_after_commit_is_recoverable(self):
        # 只杀本测试创建的子进程，不按端口、历史PID或进程名定位。
        source_bytes = self.source.read_bytes()
        source_rows = dataset(self.source)
        for window in ('before','after'):
            with self.subTest(window=window):
                target = self.root/f'kill-{window}.sqlite3'
                create_fixture_database(target,{'projects':[],'project_snapshots':[],'skills':[]})
                marker = self.root/f'{window}.ready'; identity = str(uuid4())
                code = '''
from pathlib import Path
import json,os,sys,time
from unittest.mock import patch
sys.path.insert(0,sys.argv[6])
from novel_writer.application import migrations as m
def stop(*args,**kwargs):
    marker = Path(sys.argv[4])
    pending = marker.with_suffix('.pending')
    ready = dict(pid=os.getpid(),operation_id=sys.argv[3],window=sys.argv[5],
                 module=str(Path(m.__file__).resolve()),pythonpath='PYTHONPATH' in os.environ)
    with pending.open('x',encoding='utf8') as stream:
        json.dump(ready,stream)
        stream.flush(); os.fsync(stream.fileno())
    os.replace(pending,marker)
    print(json.dumps(ready),flush=True)
    time.sleep(40)
with patch.object(m,'_before_commit' if sys.argv[5]=='before' else 'migration_status',side_effect=stop):
    m.migrate(sys.argv[1],sys.argv[2],operation_id=sys.argv[3])
'''
                environment = {key:os.environ[key] for key in
                    ('PATH','SystemRoot','WINDIR','COMSPEC','USERPROFILE','LOCALAPPDATA',
                     'APPDATA','TEMP','TMP','PATHEXT') if key in os.environ}
                output = error = b''
                ready = None
                killed_at_window = False
                child = subprocess.Popen([sys.executable,'-B','-X','utf8','-c',code,str(self.source),str(target),identity,str(marker),window,str(ROOT/'src')],
                    cwd=ROOT,env=environment,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                try:
                    deadline = time.monotonic()+15
                    while not marker.exists() and child.poll() is None and time.monotonic()<deadline: time.sleep(.03)
                    self.assertTrue(marker.exists(),'子进程未到指定事务窗口')
                    ready = json.loads(marker.read_text(encoding='utf8'))
                    self.assertEqual((ready['pid'],ready['operation_id'],ready['window']),
                                     (child.pid,identity,window))
                    self.assertEqual(Path(ready['module']),ROOT/'src/novel_writer/application/migrations.py')
                    self.assertFalse(ready['pythonpath'])
                    self.assertIsNone(child.poll(),'子进程必须仍停在真实事务窗口')
                    child.kill(); output,error = child.communicate(timeout=10)
                    killed_at_window = True
                    self.assertNotEqual(child.returncode,0)
                    status = self.m.migration_status(target,identity)
                    self.assertEqual(status['state'],'not_applied' if window=='before' else 'already_present')
                    self.assertEqual(len(dataset(target)['projects']),0 if window=='before' else 2)
                    if window=='before':
                        self.assertEqual(dataset(target),{'fixture_version':1,'projects':[],
                                                         'project_snapshots':[],'skills':[]})
                    committed = dataset(target)
                    retried = self.m.migrate(self.source,target,operation_id=identity)
                    self.assertTrue(retried['verified']); self.assertEqual(len(dataset(target)['projects']),2)
                    if window=='after':
                        self.assertEqual(dataset(target),committed)
                    copied = dataset(target)
                    reverse = {(entry['new_project_id'],entry['kind'],entry['new_id']):entry['old_id']
                               for entry in retried['id_map']}
                    restored = transform_fixture_ids(copied,lambda p,k,i:reverse[(p,k,i)])
                    for table,key in (('projects','id'),('project_snapshots','project_id')):
                        restored[table].sort(key=lambda row:(row[key],row.get('revision',0)))
                    self.assertEqual(restored,source_rows)
                    self.assertEqual(self.source.read_bytes(),source_bytes)
                finally:
                    try:
                        if child.poll() is None: child.kill()
                        output,error = child.communicate(timeout=10)
                    finally:
                        child.stdout.close(); child.stderr.close()
                        probe = dict(window=window,pid=child.pid,returncode=child.returncode,
                            ready=ready,killed_at_window=killed_at_window,
                            stdout=output.decode('utf8',errors='replace'),
                            stderr=error.decode('utf8',errors='replace'),
                            stdout_closed=child.stdout.closed,stderr_closed=child.stderr.closed)
                        print('migration-worker '+json.dumps(probe,ensure_ascii=False),flush=True)
                        artifacts = os.environ.get('NOVEL_WRITER_ARTIFACTS')
                        if artifacts:
                            with (Path(artifacts)/'migration-crash-probes.jsonl').open('a',encoding='utf8') as stream:
                                stream.write(json.dumps(probe,ensure_ascii=False)+'\n')


if __name__ == '__main__': unittest.main()
