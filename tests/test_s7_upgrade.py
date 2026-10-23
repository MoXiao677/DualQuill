import importlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing

class DesktopUpgradeTests(unittest.TestCase):
    def test_explicit_restored_database_can_open_with_independent_profile_and_snapshot(self):
        module=importlib.import_module('novel_writer.ui.desktop')
        with tempfile.TemporaryDirectory(prefix='novel-restored-profile-') as temp:
            root=Path(temp);profile=root/'isolated';database=root/'restored.sqlite3'
            with closing(sqlite3.connect(database)) as db,db:db.execute('CREATE TABLE original (body TEXT)');db.execute('INSERT INTO original VALUES (?)',('恢复原文',))
            seen=[]
            class Server:
                class Providers:pass
                providers=Providers()
            def factory(path,**options):seen.append((path,options));return Server()
            module.start_profile(profile,database=database,server_factory=factory)
            self.assertEqual(seen[0][0],database.resolve());self.assertEqual(seen[0][1]['provider_path'],profile.resolve()/'providers.dpapi')
            self.assertEqual(len(list((profile/'upgrade-backups').glob('*.sqlite3'))),1)
            with self.assertRaisesRegex(ValueError,'absolute'):module.start_profile(profile,database=Path('relative.sqlite3'),server_factory=factory)
    def test_upgrade_snapshot_and_failed_initialization_restore_original_rows(self):
        module=importlib.import_module('novel_writer.ui.desktop')
        self.assertTrue(hasattr(module,'start_profile'),'upgrade snapshot and rollback are missing')
        with tempfile.TemporaryDirectory(prefix='novel-s7-upgrade-') as temp:
            profile=Path(temp);database=profile/'library'/'novels.sqlite3';database.parent.mkdir()
            with closing(sqlite3.connect(database)) as db, db:
                db.execute('CREATE TABLE original (body TEXT)');db.execute('INSERT INTO original VALUES (?)',('虚构原文与历史',))
            def failing(path,**kwargs):
                with closing(sqlite3.connect(path)) as db, db:db.execute('UPDATE original SET body=?',('不应保留的升级中间态',))
                raise RuntimeError('injected startup failure')
            with self.assertRaisesRegex(RuntimeError,'injected'):
                module.start_profile(profile,server_factory=failing)
            with closing(sqlite3.connect(database)) as db:self.assertEqual(db.execute('SELECT body FROM original').fetchall(),[('虚构原文与历史',)])
            snapshots=list((profile/'upgrade-backups').glob('*.sqlite3'));self.assertEqual(len(snapshots),1)
            with closing(sqlite3.connect(snapshots[0])) as db:self.assertEqual(db.execute('SELECT body FROM original').fetchall(),[('虚构原文与历史',)])
            self.assertFalse((profile/'desktop-state.json').exists())

if __name__=='__main__':unittest.main()
