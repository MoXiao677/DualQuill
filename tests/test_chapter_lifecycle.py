import base64,importlib,json,tempfile,unittest
from importlib import util
from pathlib import Path
from uuid import uuid4
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository,ConflictError
from novel_writer.application.provider_connections import ProviderConnections
from novel_writer.application.tasks import TaskCoordinator
from novel_writer.application.task_protocol import AdapterRegistry
from novel_writer.application.chapter_writing import ChapterWriting

class LifecycleTests(unittest.TestCase):
 def setUp(self):
  self.assertIsNotNone(util.find_spec('novel_writer.application.chapter_lifecycle'),'chapter lifecycle module is missing')
  self.assertIsNotNone(util.find_spec('novel_writer.application.migration_text'),'TXT/MD migration module is missing')
  self.temp=tempfile.TemporaryDirectory(prefix='novel-lifecycle-');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.service=NovelService(SQLiteRepository(self.root/'fiction.sqlite3'));self.pid=self.service.create(title='章节生命周期')['document']['project']['id']
  for title in ('第一章','第二章','第三章'):self.action('add_chapter',dict(title=title))
  state=self.service.get(self.pid);self.chapters=state['document']['chapters']
  for index,chapter in enumerate(self.chapters):self.action('save_chapter',dict(chapter_id=chapter['id'],content=f'正文{index+1}😀\r\n尾行{index+1}'))
  self.c1,self.c2,self.c3=[v['id'] for v in self.chapters]
  self.action('save_book_outline',dict(theme='测试',premise='',main_plot='',ending='',volumes=[dict(number=1,title='卷一',summary='',chapter_ids=[self.c1,self.c2,self.c3])]))
  self.action('save_idea',dict(chapter_id=self.c2,content='第二章IDEA'))
  self.action('save_chapter_outline',dict(chapter_id=self.c2,core_idea='第二章细纲',objective='',story_time='',character_ids=[],scenes=[]))
  self.providers=ProviderConnections(self.root/'providers.dpapi');self.shared=TaskCoordinator(self.service,AdapterRegistry());self.addCleanup(self.shared.close);self.writing=ChapterWriting(self.shared,self.providers)
 def action(self,name,fields,revision=None):
  state=self.service.get(self.pid);return self.service.execute(self.pid,name,fields,expected_revision=state['revision'] if revision is None else revision)
 def lifecycle(self):return importlib.import_module('novel_writer.application.chapter_lifecycle')
 def migration(self):return importlib.import_module('novel_writer.application.migration_text')
 def test_reorder_swaps_explicit_neighbor_and_preserves_content_versions_idea_outline(self):
  before=self.service.get(self.pid);doc=before['document'];bodies={c['id']:c['content'] for c in doc['chapters']};versions=list(doc['versions']);ideas=dict(before['ideas'])
  state=self.action('move_chapter',dict(chapter_id=self.c3,direction='up',confirmed=True));ordered=sorted(state['document']['chapters'],key=lambda c:c['number']);self.assertEqual([c['id'] for c in ordered],[self.c1,self.c3,self.c2]);self.assertEqual([c['number'] for c in ordered],[1,2,3]);self.assertEqual({c['id']:c['content'] for c in state['document']['chapters']},bodies);self.assertEqual(state['document']['versions'],versions);self.assertEqual(state['ideas'],ideas);self.assertEqual(state['document']['chapter_outlines'],doc['chapter_outlines'])
  volume=state['document']['book_outline']['volumes'][0];self.assertEqual(volume['chapter_ids'],[self.c1,self.c3,self.c2])
  with self.assertRaises(ConflictError):self.action('move_chapter',dict(chapter_id=self.c3,direction='down',confirmed=True),revision=before['revision'])
  with self.assertRaises(ValueError):self.action('move_chapter',dict(chapter_id=self.c1,direction='up',confirmed=True))
  with self.assertRaises(ValueError):self.action('move_chapter',dict(chapter_id=self.c1,direction='down',confirmed=False))
 def test_archive_hides_from_new_tasks_but_keeps_all_content_and_restore_reverses(self):
  before=self.service.get(self.pid);versions=list(before['document']['versions']);outlines=list(before['document']['chapter_outlines']);idea=before['ideas'][self.c2]
  state=self.action('archive_chapter',dict(chapter_id=self.c2,confirmed=True));self.assertTrue(self.lifecycle().is_archived(state,self.c2));self.assertFalse(self.lifecycle().is_archived(state,self.c1));self.assertEqual(state['document']['versions'],versions);self.assertEqual(state['document']['chapter_outlines'],outlines);self.assertEqual(state['ideas'][self.c2],idea);self.assertEqual(len(state.get('generation_tasks',[])),len(before.get('generation_tasks',[])))
  options=dict(chapter_id=self.c2,mode='continue',context_options=dict(chapter_id=self.c2,budget_chars=6000),instruction='不应准备',target_chars=200,required_literals=[],forbidden_literals=[])
  with self.assertRaises(ValueError):self.writing.preview(self.pid,options)
  restored=self.action('unarchive_chapter',dict(chapter_id=self.c2,confirmed=True));self.assertFalse(self.lifecycle().is_archived(restored,self.c2));self.writing.preview(self.pid,options)
 def test_import_preview_detects_headings_and_commit_appends_exact_body_bytes(self):
  state=self.service.get(self.pid);existing=list(state['document']['chapters']);text='前言\r\n第1章 开端\r\n第一段😀\r\n第2节 转折\nSecond body\nChapter 3 Final\nEnd\n## Markdown 四\nMD body\n';raw=text.encode('utf-8')
  preview=self.migration().preview(self.pid,raw,'utf-8',self.service.get(self.pid))
  self.assertEqual([v['title'] for v in preview['items']],['前言（标题前原文）','开端','转折','Chapter 3 Final','Markdown 四']);self.assertEqual([v['chars'] for v in preview['items']],[len('前言\r\n'),len('第一段😀\r\n'),len('Second body\n'),len('End\n'),len('MD body\n')]);self.assertEqual(preview['items'][1]['content_start'],text.index('第一段'))
  items=list(preview['items']);items[0]['title']='作者改过的第一章';state=self.action('import_chapters',dict(filename='导入.txt',content_base64=base64.b64encode(raw).decode(),encoding='utf-8',items=items,preview_sha256=preview['preview_sha256'],confirmed=True));chapters=state['document']['chapters'];self.assertEqual(chapters[:3],existing);added=chapters[3:];self.assertEqual([v['title'] for v in added],['作者改过的第一章','开端','转折','Chapter 3 Final','Markdown 四']);self.assertEqual([v['content'] for v in added],['前言\r\n','第一段😀\r\n','Second body\n','End\n','MD body\n']);self.assertEqual(len(state['document']['book_outline']['volumes']),2);self.assertEqual(state['document']['book_outline']['volumes'][-1]['chapter_ids'],[v['id'] for v in added])
 def test_import_encoding_and_limits_are_explicit(self):
  gb='第1章 中文\n正文\n'.encode('gb18030');state=self.service.get(self.pid)
  automatic=self.migration().preview(self.pid,gb,'auto',state);self.assertEqual(automatic['encoding'],'gb18030');self.assertEqual(automatic['requested_encoding'],'auto')
  preview=self.migration().preview(self.pid,gb,'gb18030',state);self.assertEqual(preview['items'][0]['title'],'中文');self.assertEqual(preview['items'][0]['content'],'正文\n')
  with self.assertRaises(ValueError):self.migration().preview(self.pid,b'bad\xff\xfe','utf-8',state)
  with self.assertRaises(ValueError):self.migration().preview(self.pid,b'x'*(5*1024*1024+1),'utf-8',state)
  with self.assertRaises(ValueError):self.migration().preview(self.pid,b'abc','utf-8',state,filename='a.pdf')
  imported=self.action('import_chapters',dict(filename='a.txt',content_base64=base64.b64encode(gb).decode(),encoding='auto',items=preview['items'],preview_sha256=preview['preview_sha256'],confirmed=True));self.assertEqual(imported['document']['chapters'][-1]['content'],'正文\n')
  for invalid in (b'\x81',b'\xff\xfeabc',b'\xef\xbb\xbf\xff',b'a\x00b'):
   with self.assertRaises(ValueError):self.migration().preview(self.pid,invalid,'auto',state)
  bom=self.migration().preview(self.pid,b'\xef\xbb\xbf'+b'hello','auto',state);self.assertEqual(bom['encoding'],'utf-8-sig');self.assertEqual(bom['items'][0]['content'],'hello')
 def test_export_txt_and_markdown_roundtrip_titles_and_bodies(self):
  state=self.service.get(self.pid);txt=self.migration().export_text(state,'book','txt');md=self.migration().export_text(state,'book','md');self.assertIn('第1章',txt);self.assertIn('## 第1章',md)
  for text,encoding in ((txt,'utf-8'),(md,'utf-8')):
   preview=self.migration().preview(self.pid,text.encode(encoding),encoding,state);self.assertEqual(len(preview['items']),3)
   self.assertEqual([v['title'] for v in preview['items']],[v['title'] for v in state['document']['chapters']])
   self.assertEqual([v['content'].rstrip('\n') for v in preview['items']],[v['content'].rstrip('\n') for v in state['document']['chapters']])
 def test_export_scope_and_safe_filename(self):
  state=self.service.get(self.pid);result=self.migration().export_payload(state,'volume','md',volume_number=1);self.assertTrue(result['filename'].endswith('.md'));self.assertNotIn('/',result['filename']);self.assertIn('卷一',result['text']);chapter=self.migration().export_payload(state,'chapter','txt',chapter_id=self.c2);self.assertEqual(chapter['text'].count('正文2😀'),1)
 def test_v19_backup_restore_copy_preserve_lifecycle_and_imported_chapters(self):
  from novel_writer.application.backups import create_backup,restore_backup
  from novel_writer.application.migrations import migrate
  from novel_writer.application.skill_import import SkillLibrary
  self.action('archive_chapter',dict(chapter_id=self.c2,confirmed=True));raw='第1章 导入备份\n正文备份😀\n'.encode();preview=self.migration().preview(self.pid,raw,'utf-8',self.service.get(self.pid));self.action('import_chapters',dict(filename='备份.txt',content_base64=base64.b64encode(raw).decode(),encoding='utf-8',items=preview['items'],preview_sha256=preview['preview_sha256'],confirmed=True));state=self.service.get(self.pid);self.assertEqual(state['workspace_version'],19)
  SkillLibrary(self.root/'fiction.sqlite3');package=self.root/'lifecycle.nwbak';self.assertEqual(create_backup(self.root/'fiction.sqlite3',package)['backup_format_version'],51);restored=restore_backup(package,self.root/'restored');self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid),state)
  target=self.root/'copy'/'copy.sqlite3';target.parent.mkdir();SQLiteRepository(target);SkillLibrary(target);copied=migrate(package,target,operation_id=str(uuid4()));clone=NovelService(SQLiteRepository(target)).get(copied['projects'][0]['new_id']);self.assertEqual(len(clone['chapter_lifecycle_events']),1);self.assertTrue(self.lifecycle().is_archived(clone,clone['document']['chapters'][1]['id']));self.assertEqual(clone['document']['chapters'][-1]['content'],'正文备份😀\n');self.assertEqual(len(clone['document']['chapters']),4)
if __name__=='__main__':unittest.main()
