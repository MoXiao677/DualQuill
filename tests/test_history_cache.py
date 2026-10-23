"""A validation cache must never turn disk tampering or rollback into trusted data."""
import os,sqlite3,tempfile,unittest
from contextlib import closing
from pathlib import Path
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository,ConflictError

class HistoryCacheTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='novel-history-cache-');self.addCleanup(self.temp.cleanup);self.path=Path(self.temp.name)/'fiction.sqlite3';self.repo=SQLiteRepository(self.path);self.service=NovelService(self.repo);self.state=self.service.create(title='虚构缓存回归');self.pid=self.state['document']['project']['id'];self.state=self.service.execute(self.pid,'add_chapter',dict(title='第一章'),expected_revision=self.state['revision']);self.cid=self.state['document']['chapters'][0]['id'];self.repo.get(self.pid)
 def test_cached_reads_are_isolated_and_second_instance_updates_are_visible(self):
  returned=self.repo.get(self.pid);returned['document']['project']['title']='不能泄入缓存';self.assertEqual(self.repo.get(self.pid)['document']['project']['title'],'虚构缓存回归')
  other=NovelService(SQLiteRepository(self.path));other.execute(self.pid,'save_chapter',dict(chapter_id=self.cid,content='来自另一实例'),expected_revision=self.state['revision']);self.assertEqual(self.repo.get(self.pid)['document']['chapters'][0]['content'],'来自另一实例')
  with self.assertRaises(ConflictError):self.repo.save(self.state,expected_revision=self.state['revision'])
 def test_committed_feature_containers_match_disk_for_atomic_and_save(self):
  from uuid import uuid4
  from novel_writer.application.materials import Materials
  from novel_writer.storage.json_codec import strict_json_loads
  Materials(self.service).create(self.pid,dict(operation_id=str(uuid4()),expected_revision=self.state['revision'],title='虚构资料',format='txt',tags=['港湾'],text='虚构正文'))
  warm=self.repo.get(self.pid)
  self.assertIs(type(warm['materials'][0]['tags']),list)
  self.assertEqual(warm,SQLiteRepository(self.path).get(self.pid))
  warm['materials'][0]['tags']=tuple(warm['materials'][0]['tags'])
  saved=self.repo.save(warm,expected_revision=warm['revision'])
  self.assertIs(type(saved['materials'][0]['tags']),list)
  def operation(state):
   state['materials'][0]['tags']=tuple(state['materials'][0]['tags'])
   return state,None
  committed=self.repo.atomic(self.pid,operation,return_workspace=True)
  self.assertIs(type(committed['materials'][0]['tags']),list)
  with closing(sqlite3.connect(self.path)) as db:
   raw=strict_json_loads(db.execute('SELECT payload FROM projects WHERE id=?',(self.pid,)).fetchone()[0])
  self.assertEqual(committed,raw)
  self.assertEqual(committed,self.repo.get(self.pid))
  self.assertEqual(committed,SQLiteRepository(self.path).get(self.pid))
  committed['materials'][0]['tags'].append('不能泄入缓存')
  self.assertEqual(self.repo.get(self.pid),raw)
 def test_rollback_does_not_seed_a_trusted_future_snapshot(self):
  before=self.repo.get(self.pid)
  def fail(state):
   state['document']['project']['title']='未提交';raise ValueError('deliberate rollback')
  with self.assertRaises(ValueError):self.repo.atomic(self.pid,fail)
  self.assertEqual(self.repo.get(self.pid),before)
 def test_old_snapshot_same_size_restored_mtime_is_still_checked(self):
  before=self.path.stat()
  with closing(sqlite3.connect(self.path)) as db, db:
   db.execute('DROP TRIGGER snapshots_no_update');raw=db.execute('SELECT payload FROM project_snapshots WHERE revision=1').fetchone()[0];db.execute('UPDATE project_snapshots SET payload=? WHERE revision=1',('!'+raw[1:],))
  os.utime(self.path,ns=(before.st_atime_ns,before.st_mtime_ns))
  with self.assertRaises(ValueError):self.repo.get(self.pid)
 def test_current_metadata_and_deleted_snapshot_cannot_reuse_cached_prefix(self):
  with closing(sqlite3.connect(self.path)) as db, db:db.execute('UPDATE projects SET title=? WHERE id=?',('错误标题',self.pid))
  with self.assertRaises(ValueError):self.repo.get(self.pid)
  with closing(sqlite3.connect(self.path)) as db, db:
   db.execute('UPDATE projects SET title=? WHERE id=?',('虚构缓存回归',self.pid));db.execute('DROP TRIGGER snapshots_no_delete');db.execute('DELETE FROM project_snapshots WHERE revision=1')
  with self.assertRaises(ValueError):self.repo.get(self.pid)
