"""V27 lifecycle contracts, including preservation and real repository reopen."""
from copy import deepcopy
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from tests import test_chapter_lifecycle as fixture
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository, ConflictError


class ChapterTrashTests(unittest.TestCase):
    setUp = fixture.LifecycleTests.setUp
    action = fixture.LifecycleTests.action

    def volumes(self):
        self.action('save_book_outline',dict(volumes=[
            dict(number=1,title='卷一',summary='',chapter_ids=[self.c1,self.c2]),
            dict(number=2,title='卷二',summary='',chapter_ids=[self.c3])]))

    def trash(self,chapter=None,**overrides):
        values=dict(chapter_id=chapter or self.c2,operation_id=str(uuid4()),
                    confirm_title='第二章',acknowledge_references=True,confirmed=True)
        values.update(overrides)
        return self.action('trash_chapter',values)

    def test_cross_volume_reopen_preserves_payload_and_rejects_invalid_moves(self):
        self.volumes();before=self.service.get(self.pid)
        fields=dict(chapter_id=self.c2,target_volume_number=2,target_index=0,confirmed=True)
        moved=self.action('move_chapter_to_volume',fields)
        self.assertEqual([v['chapter_ids'] for v in moved['document']['book_outline']['volumes']],[[self.c1],[self.c2,self.c3]])
        self.assertEqual([c['id'] for c in sorted(moved['document']['chapters'],key=lambda c:c['number'])],[self.c1,self.c2,self.c3])
        for key in ('versions','chapter_outlines'):
            self.assertEqual(moved['document'][key],before['document'][key])
        self.assertEqual(moved['ideas'],before['ideas'])
        self.assertEqual(NovelService(SQLiteRepository(self.root/'fiction.sqlite3')).get(self.pid),moved)
        with self.assertRaises(ConflictError):self.action('move_chapter_to_volume',fields,revision=before['revision'])
        for patch in ({},{'chapter_id':str(uuid4())},{'target_volume_number':99},{'target_index':9},{'confirmed':False}):
            with self.assertRaises(ValueError):self.action('move_chapter_to_volume',{**fields,**patch})
        self.action('archive_chapter',dict(chapter_id=self.c2,confirmed=True))
        with self.assertRaises(ValueError):self.action('move_chapter_to_volume',{**fields,'target_volume_number':1})

    def test_trash_confirmations_idempotency_references_and_restore_original_location(self):
        self.volumes();before=self.service.get(self.pid)
        preview=self.service.trash_preview(self.pid,self.c2)
        self.assertTrue(preview['can_trash']);self.assertGreater(preview['reference_count'],0)
        self.assertEqual(preview['revision'],before['revision'])
        self.assertEqual(self.service.get(self.pid),before)
        for patch in ({'confirm_title':' 第二章'},{'acknowledge_references':False},{'operation_id':'invalid'},{'confirmed':False}):
            with self.assertRaises(ValueError):self.trash(**patch)
        op=str(uuid4());fields=dict(chapter_id=self.c2,operation_id=op,confirm_title='第二章',acknowledge_references=True,confirmed=True)
        with self.assertRaises(ValueError):self.service.execute(self.pid,'trash_chapter',fields,expected_revision=None)
        state=self.action('trash_chapter',fields)
        event=state['chapter_trash_events'][0]
        self.assertEqual((event['original_volume_number'],event['original_position'],event['original_number']),(1,1,2))
        self.assertEqual(self.action('trash_chapter',fields,revision=before['revision']),state)
        with self.assertRaises(ValueError):self.action('trash_chapter',{**fields,'chapter_id':self.c1})
        for key in ('versions','chapter_outlines','chapters'):
            if key=='chapters':
                self.assertEqual({c['id']:c['content'] for c in state['document'][key]},{c['id']:c['content'] for c in before['document'][key]})
            else:self.assertEqual(state['document'][key],before['document'][key])
        self.assertEqual(state['ideas'],before['ideas'])
        self.assertEqual(len(self.service.trash_listing(self.pid)['chapters']),1)
        restored=self.action('restore_trashed_chapter',dict(chapter_id=self.c2,operation_id=str(uuid4()),confirmed=True))
        self.assertEqual([v['chapter_ids'] for v in restored['document']['book_outline']['volumes']],[[self.c1,self.c2],[self.c3]])
        self.assertEqual(restored['chapter_trash_events'][1]['trash_event_id'],event['id'])
        self.assertEqual(self.service.trash_listing(self.pid)['chapters'],[])

    def test_hidden_excluded_from_context_export_tasks_and_c07_new_refs(self):
        from novel_writer.application.migration_text import export_text
        from novel_writer.application.full_book_planning import FullBookPlanning
        planning=FullBookPlanning(self.service)
        request=dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision'],title='旧引用事件',summary='',planned_order=1,planned_chapter_id=self.c2)
        planning.act(self.pid,'create_event',request)
        self.trash()
        state=self.service.get(self.pid)
        self.assertNotIn('正文2',export_text(state,'book','txt'))
        with self.assertRaises(ValueError):export_text(state,'chapter','txt',self.c2)
        with self.assertRaises(ValueError):self.service.preview_context(self.pid,dict(chapter_id=self.c2))
        context=self.service.preview_context(self.pid,dict(chapter_id=self.c3,scope='through_current'))
        self.assertNotIn('正文2',context['context_text'])
        with self.assertRaises(ValueError):self.action('move_chapter_to_volume',dict(chapter_id=self.c2,target_volume_number=1,target_index=0,confirmed=True))
        report=planning.listing(self.pid)
        self.assertTrue(next(c for c in report['chapters'] if c['id']==self.c2)['hidden'])
        self.assertTrue(any(d['reason'] in ('blocked','missing') for d in report['deviation']['deviations']))
        request.update(operation_id=str(uuid4()),expected_revision=state['revision'],title='禁止新引用')
        with self.assertRaises(ValueError):planning.act(self.pid,'create_event',request)

    def test_backup_v27_restore_copy_maps_history_and_preserves_readonly_v26(self):
        from novel_writer.application.backups import create_backup,restore_backup
        from novel_writer.application.migrations import migrate
        from novel_writer.application.skill_import import SkillLibrary
        from novel_writer.application.full_book_planning import FullBookPlanning
        old=self.service.get(self.pid)
        FullBookPlanning(self.service).listing(self.pid)
        self.assertEqual(self.service.get(self.pid),old)
        self.trash();state=self.service.get(self.pid)
        SkillLibrary(self.root/'fiction.sqlite3')
        package=self.root/'v27.nwbak'
        self.assertEqual(create_backup(self.root/'fiction.sqlite3',package)['backup_format_version'],51)
        restored=restore_backup(package,self.root/'restored-v27')
        self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid),state)
        target=self.root/'copy-v27.sqlite3';SQLiteRepository(target);SkillLibrary(target)
        result=migrate(package,target,operation_id=str(uuid4()))
        clone=NovelService(SQLiteRepository(target)).get(result['projects'][0]['new_id'])
        event=clone['chapter_trash_events'][0]
        self.assertNotEqual(event['id'],state['chapter_trash_events'][0]['id'])
        self.assertNotEqual(event['chapter_id'],self.c2)
        self.assertEqual(event['project_id'],clone['document']['project']['id'])
        self.assertEqual(event['request_sha256'],state['chapter_trash_events'][0]['request_sha256'])
        service=NovelService(SQLiteRepository(target))
        restored=service.execute(event['project_id'],'restore_trashed_chapter',dict(chapter_id=event['chapter_id'],operation_id=str(uuid4()),confirmed=True),expected_revision=clone['revision'])
        self.assertEqual(restored['document']['chapters'][1]['content'],state['document']['chapters'][1]['content'])


if __name__=='__main__':unittest.main()
