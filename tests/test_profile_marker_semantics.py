"""Profile generation marker is independent of package and workspace versions."""
from contextlib import closing
import hashlib,json,sqlite3,tempfile,unittest
from pathlib import Path
from novel_writer.ui.desktop import start_profile,VERSION
from novel_writer.domain.models import DataValidationError

class ProfileMarkerSemanticsTests(unittest.TestCase):
 def test_same_generation_does_not_upgrade_storage_or_rewrite_rows(self):
  with tempfile.TemporaryDirectory(prefix='fiction-marker-') as t:
   p=Path(t);db=p/'library/novels.sqlite3';db.parent.mkdir();
   with closing(sqlite3.connect(db)) as c,c:
    c.execute('CREATE TABLE original(body TEXT)');c.execute("INSERT INTO original VALUES ('fictional V48 workspace, storage v1')");c.execute('PRAGMA user_version=1')
   (p/'desktop-state.json').write_text(json.dumps({'version':VERSION}),encoding='utf-8');before=db.read_bytes()
   class Server:
    class Providers:pass
    providers=Providers()
   start_profile(p,server_factory=lambda *a,**k:Server())
   self.assertEqual(db.read_bytes(),before);self.assertFalse((p/'upgrade-backups').exists())
 def test_future_profile_marker_rejects_before_factory_or_database_write(self):
  with tempfile.TemporaryDirectory(prefix='fiction-marker-') as t:
   p=Path(t);marker=p/'desktop-state.json';marker.write_text('{"version":"99.0.0"}',encoding='utf-8');before=marker.read_bytes()
   def forbidden(*a,**k):self.fail('factory must not run')
   with self.assertRaisesRegex(ValueError,'Newer desktop profile'):start_profile(p,server_factory=forbidden)
   self.assertEqual(marker.read_bytes(),before);self.assertFalse((p/'library').exists())
 def test_same_marker_future_sqlite_schema_rejected_without_source_mutation(self):
  with tempfile.TemporaryDirectory(prefix='fiction-marker-') as t:
   p=Path(t);db=p/'library/novels.sqlite3';db.parent.mkdir()
   with closing(sqlite3.connect(db)) as c,c:c.execute('PRAGMA user_version=99')
   marker=p/'desktop-state.json';marker.write_text(json.dumps({'version':VERSION}),encoding='utf-8');before=db.read_bytes();m=marker.read_bytes()
   with self.assertRaises(DataValidationError):start_profile(p)
   self.assertEqual(db.read_bytes(),before);self.assertEqual(marker.read_bytes(),m)
