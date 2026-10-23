import json,tempfile,unittest
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository,validate_workspace
from novel_writer.application.scoped_rules import RuleCoordinator,upgrade

class ScopedRuleImportHistoryTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='rules-import-');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.db=self.root/'fiction.sqlite3';self.service=NovelService(SQLiteRepository(self.db));self.pid=self.service.create(title='规则导入')['document']['project']['id']
  self.action('add_chapter',dict(title='第一章'));state=self.service.get(self.pid);self.cid=state['document']['chapters'][0]['id'];self.action('save_book_outline',dict(theme='',premise='',main_plot='',ending='',volumes=[dict(number=1,title='卷一',summary='',chapter_ids=[self.cid])]))
  self.rules=RuleCoordinator(self.service)
 def action(self,name,fields):return self.service.execute(self.pid,name,fields,expected_revision=self.service.get(self.pid)['revision'])
 def save(self,scope,kind,text,scope_id=None,enabled=True):
  return self.rules.save(self.pid,dict(operation_id=str(uuid4()),rule_id=None,scope=scope,scope_id=scope_id if scope_id is not None else (self.pid if scope=='book' else self.cid if scope=='chapter' else '1' if scope=='volume' else None),kind=kind,text=text,enabled=enabled))
 def import_request(self,rows,operation_id=None,fmt='json'):
  content=json.dumps(rows,ensure_ascii=False) if fmt=='json' else rows
  preview=self.rules.preview_import(self.pid,dict(format=fmt,content=content))
  return dict(operation_id=operation_id or str(uuid4()),format=fmt,content=content,preview_sha256=preview['preview_sha256']),preview
 def test_json_preview_reports_row_errors_and_rejects_all_or_nothing(self):
  rows=[dict(scope='global',scope_id=None,kind='guidance',text='有效指引',enabled=True),dict(scope='book',scope_id=self.pid,kind='unknown',text='坏类型',enabled=True),dict(scope='chapter',scope_id='missing',kind='required',text='坏目标',enabled=True)]
  request,preview=self.import_request(rows);self.assertEqual(preview['count'],3);self.assertFalse(preview['can_confirm']);self.assertEqual([v['row'] for v in preview['rows'] if v['status']=='error'],[2,3]);self.assertEqual([v['field'] for v in preview['rows'][1]['errors']],['kind']);self.assertEqual([v['field'] for v in preview['rows'][2]['errors']],['scope_id'])
  before=self.service.get(self.pid);self.assertRaises(ValueError,self.rules.import_rules,self.pid,request);after=self.service.get(self.pid);self.assertEqual(after['revision'],before['revision']);self.assertEqual(after.get('scoped_rules',[]),[])
 def test_import_is_atomic_and_operation_id_is_idempotent(self):
  rows=[dict(scope='global',scope_id=None,kind='guidance',text='全局指引',enabled=True),dict(scope='book',scope_id=self.pid,kind='required',text='本书必写',enabled=True)]
  request,preview=self.import_request(rows);self.assertTrue(preview['can_confirm']);result=self.rules.import_rules(self.pid,request);self.assertEqual(result['created'],2);state=self.service.get(self.pid);self.assertEqual(state['workspace_version'],22);self.assertEqual(len(state['scoped_rules']),2);self.assertEqual([v['operation'] for v in state['scoped_rule_history']],['import','import']);self.assertEqual([v['source'] for v in state['scoped_rule_history']],['import','import'])
  revision=state['revision'];replay=self.rules.import_rules(self.pid,request);self.assertTrue(replay['idempotent']);self.assertEqual(replay['created'],0);self.assertEqual(self.service.get(self.pid)['revision'],revision)
  invalid=[dict(scope='global',scope_id=None,kind='guidance',text='不会写入',enabled=True),dict(scope='global',scope_id=None,kind='guidance',text='',enabled=True)]
  bad,_=self.import_request(invalid);self.assertRaises(ValueError,self.rules.import_rules,self.pid,bad);self.assertEqual(len(self.service.get(self.pid)['scoped_rules']),2)
 def test_replaying_import_after_rules_were_deleted_is_rejected(self):
  rows=[dict(scope='global',scope_id=None,kind='guidance',text='删除后不可重放',enabled=True),dict(scope='book',scope_id=self.pid,kind='required',text='历史仍保留',enabled=True)]
  request,_=self.import_request(rows);created=self.rules.import_rules(self.pid,request)['rules']
  for rule in created:self.rules.delete(self.pid,dict(rule_id=rule['id']))
  before=self.service.get(self.pid);self.assertEqual(before['scoped_rules'],[])
  with self.assertRaisesRegex(ValueError,'规则已被删除'):
   self.rules.import_rules(self.pid,request)
  after=self.service.get(self.pid);self.assertEqual(after['scoped_rules'],[]);self.assertEqual(after['revision'],before['revision']);self.assertEqual([v['operation'] for v in after['scoped_rule_history']],['import','import','delete','delete'])
 def test_conflict_preview_blocks_import_and_reports_rows(self):
  rows=[dict(scope='book',scope_id=self.pid,kind='required',text='同一句话',enabled=True),dict(scope='chapter',scope_id=self.cid,kind='forbidden',text='同一句话',enabled=True)]
  request,preview=self.import_request(rows);self.assertFalse(preview['can_confirm']);self.assertEqual(len(preview['conflicts']),1);self.assertEqual(preview['conflicts'][0]['rows'],[1,2]);self.assertTrue(preview['conflicts'][0]['blocks_import']);self.assertRaises(ValueError,self.rules.import_rules,self.pid,request);self.assertEqual(self.service.get(self.pid).get('scoped_rules',[]),[])
  existing=self.save('book','forbidden','已有禁写');request,preview=self.import_request([dict(scope='global',scope_id=None,kind='required',text='已有禁写',enabled=True)]);self.assertFalse(preview['can_confirm']);self.assertEqual(preview['conflicts'][0]['rows'],[1]);self.assertIn(existing['id'],preview['conflicts'][0]['rule_ids'])
 def test_imported_rules_keep_chapter_volume_book_global_precedence_without_tasks(self):
  rows=[dict(scope='global',scope_id=None,kind='guidance',text='导入全局',enabled=True),dict(scope='book',scope_id=self.pid,kind='guidance',text='导入本书',enabled=True),dict(scope='volume',scope_id='1',kind='guidance',text='导入分卷',enabled=True),dict(scope='chapter',scope_id=self.cid,kind='guidance',text='导入章节',enabled=True)]
  request,preview=self.import_request(rows);self.assertTrue(preview['can_confirm']);self.rules.import_rules(self.pid,request);resolved=self.rules.resolve(self.pid,self.cid);self.assertEqual([v['text'] for v in resolved['rules']],['导入章节','导入分卷','导入本书','导入全局']);state=self.service.get(self.pid);self.assertEqual(state['generation_tasks'],[]);self.assertEqual(state['document']['chapters'][0]['content'],'')
 def test_history_is_append_only_for_updates_toggles_archive_and_delete(self):
  rule=self.save('chapter','guidance','初始文本');second=self.save('book','guidance','待删除')
  updated=self.rules.save(self.pid,dict(operation_id=str(uuid4()),rule_id=rule['id'],scope='chapter',scope_id=self.cid,kind='guidance',text='修改文本',enabled=True));self.rules.set_enabled(self.pid,dict(rule_id=rule['id'],enabled=False));self.rules.set_enabled(self.pid,dict(rule_id=rule['id'],enabled=True));self.rules.archive(self.pid,dict(rule_id=rule['id'],archived=True));self.rules.archive(self.pid,dict(rule_id=rule['id'],archived=False));self.rules.delete(self.pid,dict(rule_id=second['id']))
  state=self.service.get(self.pid);self.assertEqual([v['operation'] for v in state['scoped_rule_history']],[ 'create','create','update','disable','enable','archive','unarchive','delete'])
  entry=next(v for v in state['scoped_rule_history'] if v['operation']=='update');self.assertEqual(entry['before']['text'],'初始文本');self.assertEqual(entry['after']['text'],'修改文本');self.assertEqual(entry['after']['version'],2)
  history=self.rules.history(self.pid,second['id']);self.assertEqual([v['operation'] for v in history['history']],['create','delete']);self.assertIsNone(history['history'][-1]['after']);self.assertIn(second['id'],self.rules.list(self.pid)['deleted_rule_ids'])
  tampered=deepcopy(state);tampered['scoped_rule_history'][0]['created_at']='2026-01-01T00:00:00+00:00';self.assertRaises(ValueError,self.service.repository.save,tampered,expected_revision=state['revision'])
 def test_csv_import_and_limits(self):
  content='scope,scope_id,kind,text,enabled\nglobal,,guidance,"含,逗号",true\n';preview=self.rules.preview_import(self.pid,dict(format='csv',content=content));self.assertTrue(preview['can_confirm']);result=self.rules.import_rules(self.pid,dict(operation_id=str(uuid4()),format='csv',content=content,preview_sha256=preview['preview_sha256']));self.assertEqual(result['created'],1);self.assertEqual(self.service.get(self.pid)['scoped_rules'][0]['text'],'含,逗号')
  self.assertRaises(ValueError,self.rules.preview_import,self.pid,dict(format='json',content='x'*(512*1024+1)))
  rows=[dict(scope='global',scope_id=None,kind='guidance',text='上限',enabled=True)]*501;self.assertRaises(ValueError,self.rules.preview_import,self.pid,dict(format='json',content=json.dumps(rows)))
 def test_v22_backup_restore_copy_maps_rule_and_history_ids(self):
  from novel_writer.application.backups import create_backup,restore_backup
  from novel_writer.application.migrations import migrate
  from novel_writer.application.skill_import import SkillLibrary
  chapter_rule=self.save('chapter','guidance','章节规则');book_rule=self.save('book','guidance','书级规则');self.rules.save(self.pid,dict(operation_id=str(uuid4()),rule_id=book_rule['id'],scope='book',scope_id=self.pid,kind='guidance',text='书级修改',enabled=True));self.rules.delete(self.pid,dict(rule_id=chapter_rule['id']))
  state=self.service.get(self.pid);self.assertEqual(state['workspace_version'],22);SkillLibrary(self.db);package=self.root/'rules.nwbak';self.assertEqual(create_backup(self.db,package)['backup_format_version'],51);restored=restore_backup(package,self.root/'restored');self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid),state)
  target=self.root/'copy'/'copy.sqlite3';target.parent.mkdir();SQLiteRepository(target);SkillLibrary(target);copied=migrate(package,target,operation_id=str(uuid4()));clone=NovelService(SQLiteRepository(target)).get(copied['projects'][0]['new_id']);self.assertEqual(len(clone['scoped_rule_history']),4);new_chapter=clone['document']['chapters'][0]['id'];self.assertEqual(clone['scoped_rule_history'][0]['rule_id'],clone['scoped_rule_history'][3]['rule_id']);self.assertEqual(clone['scoped_rule_history'][0]['after']['scope_id'],new_chapter);self.assertEqual(clone['scoped_rule_history'][3]['before']['scope_id'],new_chapter);self.assertNotEqual(clone['scoped_rule_history'][0]['rule_id'],chapter_rule['id']);self.assertNotIn(clone['scoped_rule_history'][3]['rule_id'],[v['id'] for v in clone['scoped_rules']]);self.assertEqual(clone['scoped_rule_history'][2]['after']['scope_id'],clone['document']['project']['id'])
 def test_v21_read_remains_valid_and_upgrade_does_not_fabricate_history(self):
  self.save('book','guidance','V21兼容');state=deepcopy(self.service.get(self.pid));state['workspace_version']=21;state.pop('scoped_rule_history');validate_workspace(state);upgrade(state);self.assertEqual(state['workspace_version'],22);self.assertEqual(state['scoped_rule_history'],[])
 def test_v21_backup_restore_and_copy_remain_compatible(self):
  import sqlite3
  from novel_writer.application.backups import create_backup,restore_backup
  from novel_writer.application.migrations import migrate
  from novel_writer.application.skill_import import SkillLibrary
  from novel_writer.domain.models import utc_now
  from novel_writer.storage.backup_validation import create_schema
  self.save('chapter','guidance','V21旧规则');state=deepcopy(self.service.get(self.pid));state['workspace_version']=21;state.pop('scoped_rule_history');state['revision']=1
  legacy=self.root/'v21.sqlite3';connection=sqlite3.connect(legacy);create_schema(connection);now=utc_now();payload=json.dumps(state,ensure_ascii=False);connection.execute('INSERT INTO projects VALUES (?,?,?,?,?)',(self.pid,state['document']['project']['title'],1,payload,now));connection.execute('INSERT INTO project_snapshots VALUES (?,?,?,?)',(self.pid,1,payload,now));connection.commit();connection.close()
  package=self.root/'v21.nwbak';self.assertEqual(create_backup(legacy,package)['backup_format_version'],51);restored=restore_backup(package,self.root/'v21-restored');self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid),state)
  target=self.root/'v21-copy'/'copy.sqlite3';target.parent.mkdir();SQLiteRepository(target);SkillLibrary(target);copied=migrate(package,target,operation_id=str(uuid4()));clone=NovelService(SQLiteRepository(target)).get(copied['projects'][0]['new_id']);self.assertEqual(clone['workspace_version'],21);self.assertEqual(len(clone['scoped_rules']),1);self.assertNotIn('scoped_rule_history',clone);self.assertEqual(clone['scoped_rules'][0]['scope_id'],clone['document']['chapters'][0]['id'])
 def test_ui_asset_exposes_import_and_history_controls(self):
  text=(Path(__file__).resolve().parents[1]/'src'/'novel_writer'/'ui'/'static'/'rules_scope.js').read_text(encoding='utf-8')
  for token in ('rule-import-preview','rule-import-commit','data-rule-history','class="rule-history"','rule-import-file'):self.assertIn(token,text)
if __name__=='__main__':unittest.main()
