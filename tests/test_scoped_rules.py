import importlib,tempfile,unittest
from importlib import util
from pathlib import Path
from uuid import uuid4
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository
from novel_writer.application.provider_connections import ProviderConnections
from novel_writer.application.tasks import TaskCoordinator
from novel_writer.application.task_protocol import AdapterRegistry
from novel_writer.application.chapter_writing import ChapterWriting

class ScopedRuleTests(unittest.TestCase):
 def setUp(self):
  self.assertIsNotNone(util.find_spec('novel_writer.application.scoped_rules'),'scoped rule engine is missing')
  self.temp=tempfile.TemporaryDirectory(prefix='novel-rules-');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.db=self.root/'fiction.sqlite3';self.service=NovelService(SQLiteRepository(self.db));self.pid=self.service.create(title='作用域规则')['document']['project']['id']
  self.action('add_chapter',dict(title='第一章'));state=self.service.get(self.pid);self.cid=state['document']['chapters'][0]['id'];self.action('save_book_outline',dict(theme='',premise='',main_plot='',ending='',volumes=[dict(number=1,title='卷一',summary='',chapter_ids=[self.cid])]))
  self.providers=ProviderConnections(self.root/'providers.dpapi');self.shared=TaskCoordinator(self.service,AdapterRegistry());self.addCleanup(self.shared.close);self.writing=ChapterWriting(self.shared,self.providers)
  self.api=importlib.import_module('novel_writer.application.scoped_rules');self.rules=self.api.RuleCoordinator(self.service)
 def action(self,name,fields):return self.service.execute(self.pid,name,fields,expected_revision=self.service.get(self.pid)['revision'])
 def save(self,scope,kind,text,scope_id=None,enabled=True):
  return self.rules.save(self.pid,dict(operation_id=str(uuid4()),rule_id=None,scope=scope,scope_id=scope_id if scope_id is not None else (self.pid if scope=='book' else self.cid if scope=='chapter' else '1' if scope=='volume' else None),kind=kind,text=text,enabled=enabled))
 def preview(self):
  return self.writing.preview(self.pid,dict(chapter_id=self.cid,mode='draft',context_options=dict(chapter_id=self.cid,budget_chars=20000),instruction='写作',target_chars=300,required_literals=[],forbidden_literals=[]))
 def test_priority_resolution_and_chapter_scope_first(self):
  self.save('global','guidance','全局指引');self.save('book','guidance','书级指引');self.save('volume','guidance','卷级指引');self.save('chapter','guidance','章级指引')
  resolved=self.rules.resolve(self.pid,self.cid);self.assertEqual([v['scope'] for v in resolved['rules']],[ 'chapter','volume','book','global']);self.assertEqual([v['text'] for v in resolved['rules']],['章级指引','卷级指引','书级指引','全局指引']);self.assertEqual(resolved['conflicts'],[])
 def test_conflict_blocks_prepare_and_disabling_one_resolves(self):
  a=self.save('book','required','必须出现的门');b=self.save('chapter','forbidden','必须出现的门');resolved=self.rules.resolve(self.pid,self.cid);self.assertEqual(len(resolved['conflicts']),1);self.assertEqual(set(resolved['conflicts'][0]['rule_ids']),{a['id'],b['id']})
  with self.assertRaises(ValueError):self.preview()
  self.rules.set_enabled(self.pid,dict(rule_id=b['id'],enabled=False));resolved=self.rules.resolve(self.pid,self.cid);self.assertEqual(resolved['conflicts'],[]);self.preview()
 def test_legacy_book_writing_rules_remain_effective_and_context_has_source(self):
  self.action('save_writing_rules',dict(content='旧书级规则不可丢'));rule=self.save('chapter','required','章级必写');preview=self.preview();self.assertIn('旧书级规则不可丢',preview['context']['context_text']);self.assertIn('章级必写',preview['context']['context_text'])
  self.assertIn('legacy',preview['context']['context_text']);self.assertIn(rule['id'],preview['context']['context_text']);self.assertIn('章级必写',preview['writing']['required_literals']);self.assertIn('旧书级规则不可丢',[v['text'] for v in preview['context']['rules']])
 def test_disable_archive_and_unknown_scope(self):
  rule=self.save('book','guidance','可停用');self.rules.set_enabled(self.pid,dict(rule_id=rule['id'],enabled=False));self.assertEqual(self.rules.resolve(self.pid,self.cid)['rules'],[v for v in self.rules.resolve(self.pid,self.cid)['rules'] if v['id']!=rule['id']])
  self.rules.archive(self.pid,dict(rule_id=rule['id'],archived=True));self.assertNotIn(rule['id'],[v['id'] for v in self.rules.resolve(self.pid,self.cid)['rules']])
  with self.assertRaises(ValueError):self.rules.save(self.pid,dict(operation_id=str(uuid4()),rule_id=None,scope='chapter',scope_id='bogus',kind='guidance',text='x',enabled=True))
  with self.assertRaises(ValueError):self.rules.save(self.pid,dict(operation_id=str(uuid4()),rule_id=None,scope='unknown',scope_id='x',kind='guidance',text='x',enabled=True))
 def test_v22_backup_copy_keeps_rules_history_and_sources(self):
  from novel_writer.application.backups import create_backup,restore_backup
  from novel_writer.application.migrations import migrate
  from novel_writer.application.skill_import import SkillLibrary
  rule=self.save('chapter','guidance','复制保留规则');self.action('save_writing_rules',dict(content='旧规则'));state=self.service.get(self.pid);self.assertEqual(state['workspace_version'],22);self.assertEqual(state['scoped_rule_history'][0]['operation'],'create')
  SkillLibrary(self.db);package=self.root/'rules.nwbak';self.assertEqual(create_backup(self.db,package)['backup_format_version'],51);restored=restore_backup(package,self.root/'restored');self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid),state)
  target=self.root/'copy'/'copy.sqlite3';target.parent.mkdir();SQLiteRepository(target);SkillLibrary(target);copied=migrate(package,target,operation_id=str(uuid4()));clone=NovelService(SQLiteRepository(target)).get(copied['projects'][0]['new_id']);self.assertEqual(len(clone['scoped_rules']),1);self.assertEqual(clone['scoped_rules'][0]['text'],'复制保留规则');self.assertEqual(clone['writing_rules'],'旧规则')
if __name__=='__main__':unittest.main()
