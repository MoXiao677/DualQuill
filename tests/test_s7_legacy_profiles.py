"""New desktop startup coverage using frozen pre-existing fictional V1-V7 oracles."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from novel_writer.ui.desktop import start_profile

FIXTURES=Path(__file__).resolve().parent/'fixtures'

def raw_rows(path):
    with closing(sqlite3.connect(path)) as db:
        tables=[row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {table:sorted(db.execute('SELECT * FROM '+table).fetchall()) for table in tables}

class DesktopLegacyProfilesTests(unittest.TestCase):
    def test_frozen_v1_through_v7_profiles_open_and_snapshot_without_rewriting_any_raw_row(self):
        specifications=[('s3b_legacy_v1.json',None),('s4a_legacy.json','v2'),('s5a_legacy.json','v3'),('s5b_legacy.json','v4'),('s5c_legacy.json','v5'),('s6a_legacy.json','v6'),('s6b_legacy.json','v7')]
        for version,(name,key) in enumerate(specifications,1):
            with self.subTest(version=version),tempfile.TemporaryDirectory(prefix='novel-s7-v'+str(version)+'-') as temp:
                oracle=json.loads((FIXTURES/name).read_text(encoding='utf-8'));oracle=oracle[key] if key else oracle
                profile=Path(temp);database=profile/'library'/'novels.sqlite3';database.parent.mkdir();database.write_bytes(bytes.fromhex(oracle['database_hex']))
                original=raw_rows(database);digest=hashlib.sha256(database.read_bytes()).hexdigest()
                server=start_profile(profile)
                try:
                    projects=server.service.list_projects();self.assertTrue(projects)
                    for project in projects:server.service.get(project['id'])
                finally:server.server_close()
                self.assertEqual(raw_rows(database),original);self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(),digest)
                snapshots=list((profile/'upgrade-backups').glob('*.sqlite3'));self.assertEqual(len(snapshots),1);self.assertEqual(raw_rows(snapshots[0]),original)
                server=start_profile(profile);server.server_close();self.assertEqual(len(list((profile/'upgrade-backups').glob('*.sqlite3'))),1)

if __name__=='__main__':unittest.main()
