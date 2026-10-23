"""C05 independent chapter rollups; immutable legacy fixtures and no model calls."""
from copy import deepcopy
from uuid import uuid4
import unittest
import test_s3b_rollups as fixture
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository,validate_workspace,ConflictError

class ChapterRollupTests(unittest.TestCase):
    setUp=fixture.MemoryRollupTests.setUp
    save=fixture.MemoryRollupTests.save
    memory=fixture.MemoryRollupTests.memory
    preview=fixture.MemoryRollupTests.preview
    def fields(self,chapter='p1-c2'):
        return dict(scope='chapter',scope_volume_number=None,through_chapter_id=chapter)
    def create(self,**changes):
        request=dict(self.fields(),operation_id=str(uuid4()),expected_revision=self.service.get('p1')['revision']);request.update(changes)
        return self.service.save_memory_rollup('p1',request)
    def rebuild(self,rollup):
        return self.service.rebuild_memory_rollup('p1',rollup['id'],dict(operation_id=str(uuid4()),expected_revision=self.service.get('p1')['revision'],expected_rollup_revision=rollup['revision']))['rollup']
    def test_exact_effective_position_read_only_and_no_other_or_future_chapters(self):
        self.memory('前章','前章不能混入','p1-c1');target=self.memory('本章','本章逐字\r\n😀','p1-c2');self.memory('未来','不能泄露','p1-c3')
        effective=self.memory('更晚来源','本章实际来源','p1-c1',source_kind='idea',source_id='p1-c2')
        self.memory('来源在未来','即使声明本章也不能泄露','p1-c2',source_kind='idea',source_id='p1-c3');self.memory('未确认','不能进入','p1-c2',confirmed=False);self.memory('已归档','不能进入','p1-c2',active=False)
        before=self.db.read_bytes();preview=self.preview(**self.fields());self.assertEqual(self.db.read_bytes(),before)
        self.assertEqual(set(preview['source_memory_ids']),{target['id'],effective['id']});self.assertTrue(all(s['position_chapter_id']=='p1-c2' for s in preview['sources']))
        self.assertNotIn('前章不能混入',preview['text']);self.assertNotIn('不能泄露',preview['text']);self.assertIn('本章逐字\r\n😀',preview['text'])
        self.assertNotEqual(self.service.get('p1')['workspace_version'],31)
    def test_v23_records_and_raw_snapshots_unchanged_when_first_chapter_write_upgrades(self):
        self.memory('本章','事实','p1-c2');old=self.service.save_memory_rollup('p1',dict(scope='book',scope_volume_number=None,through_chapter_id='p1-c5',operation_id=str(uuid4()),expected_revision=self.state['revision']))['rollup']
        state=self.service.get('p1');self.assertEqual(state['workspace_version'],23);history=deepcopy(state['memory_rollup_history']);raw=fixture.rows(self.db)['project_snapshots']
        new=self.create()['rollup'];state=self.service.get('p1');self.assertEqual(state['workspace_version'],31)
        self.assertEqual(state['memory_rollups'][0],old);self.assertEqual(state['memory_rollup_history'][:len(history)],history)
        current=fixture.rows(self.db)['project_snapshots'];self.assertEqual(len(current),len(raw)+1);self.assertTrue(all(row in current for row in raw))
        self.assertNotIn('chapter_source',old);self.assertEqual(new['chapter_source']['entity_id'],'p1-c2');self.assertEqual(NovelService(SQLiteRepository(self.db)).get('p1'),state)
        bad=deepcopy(state);bad['workspace_version']=30
        with self.assertRaises(ValueError):validate_workspace(bad)
        bad=deepcopy(state);bad['memory_rollups'][-1]['chapter_source']['source_sha256']='0'*64
        with self.assertRaises(ValueError):validate_workspace(bad)
    def test_body_change_marks_even_empty_rollup_stale_and_rebuild_keeps_history(self):
        rollup=self.create()['rollup'];self.assertEqual(rollup['sources'],[]);history=deepcopy(self.service.get('p1')['memory_rollup_history']);self.state=self.service.get('p1')
        self.save('save_chapter',chapter_id='p1-c3',content='非本章修改不误报');self.assertFalse(self.service.memory_rollups('p1')['rollups'][0]['stale'])
        self.save('save_chapter',chapter_id='p1-c2',content='本章新正文');self.assertTrue(self.service.memory_rollups('p1')['rollups'][0]['stale'])
        updated=self.rebuild(rollup);self.assertEqual(updated['revision'],2);self.assertFalse(self.service.memory_rollups('p1')['rollups'][0]['stale']);self.assertEqual(self.service.get('p1')['memory_rollup_history'][:1],history)
    def test_conflicts_idempotency_revision_and_invalid_scope_are_atomic(self):
        one=self.memory('同题','甲','p1-c2');two=self.memory('同题','乙','p1-c2');self.assertFalse(self.preview(**self.fields())['can_save']);before=self.db.read_bytes()
        with self.assertRaises(ValueError):self.create()
        self.assertEqual(self.db.read_bytes(),before);self.save('archive_memory',memory_id=two['id']);request=dict(self.fields(),operation_id=str(uuid4()),expected_revision=self.state['revision'])
        saved=self.service.save_memory_rollup('p1',request);state=self.service.get('p1');self.assertTrue(self.service.save_memory_rollup('p1',request)['idempotent']);self.assertEqual(self.service.get('p1'),state)
        with self.assertRaises(ValueError):self.service.save_memory_rollup('p1',dict(request,through_chapter_id='p1-c3'))
        with self.assertRaises(ConflictError):self.service.rebuild_memory_rollup('p1',saved['rollup']['id'],dict(operation_id=str(uuid4()),expected_revision=state['revision']-1,expected_rollup_revision=1))
        for fields in (dict(self.fields(),scope_volume_number=1),self.fields('missing'),dict(self.fields(),scope='unknown')):
            with self.assertRaises(ValueError):self.preview(**fields)
        self.assertEqual(self.service.get('p1'),state)
    def test_v31_backup_restore_copy_maps_chapter_and_source_versions(self):
        from novel_writer.application.backups import create_backup,restore_backup
        from novel_writer.application.migrations import migrate
        from novel_writer.application.skill_import import SkillLibrary
        self.save('save_chapter',chapter_id='p1-c2',content='待汇总章节正文😀');self.memory('本章','事实😀','p1-c2');rollup=self.create()['rollup'];state=self.service.get('p1');package=self.root/'chapter.nwbak'
        self.assertEqual(create_backup(self.db,package)['backup_format_version'],51);restored=restore_backup(package,self.root/'restored-chapter');self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get('p1'),state)
        target=self.root/'copy-chapter.sqlite3';SQLiteRepository(target);SkillLibrary(target);result=migrate(package,target,operation_id=str(uuid4()));service=NovelService(SQLiteRepository(target));clone=service.get(result['projects'][0]['new_id']);copied=clone['memory_rollups'][0]
        self.assertNotEqual(copied['through_chapter_id'],rollup['through_chapter_id']);self.assertEqual(copied['chapter_source']['chapter_id'],copied['through_chapter_id']);self.assertEqual(copied['chapter_source']['project_id'],clone['document']['project']['id']);self.assertNotEqual(copied['chapter_source']['version_id'],rollup['chapter_source']['version_id']);self.assertEqual(copied['chapter_source']['source_sha256'],rollup['chapter_source']['source_sha256']);self.assertFalse(service.memory_rollups(clone['document']['project']['id'])['rollups'][0]['stale'])
    def test_archived_and_trashed_target_block_preview_and_rebuild_until_restored(self):
        state=self.service.create(title='本章归档测试');pid=state['document']['project']['id'];state=self.service.execute(pid,'add_chapter',dict(title='目标章'),expected_revision=state['revision']);cid=state['document']['chapters'][0]['id'];fields=dict(scope='chapter',scope_volume_number=None,through_chapter_id=cid)
        rollup=self.service.save_memory_rollup(pid,dict(fields,operation_id=str(uuid4()),expected_revision=state['revision']))['rollup'];state=self.service.get(pid)
        state=self.service.execute(pid,'archive_chapter',dict(chapter_id=cid,confirmed=True),expected_revision=state['revision']);view=self.service.memory_rollups(pid)['rollups'][0];self.assertTrue(view['stale']);self.assertFalse(view['available'])
        with self.assertRaises(ValueError):self.service.preview_memory_rollup(pid,fields)
        with self.assertRaises(ValueError):self.service.rebuild_memory_rollup(pid,rollup['id'],dict(operation_id=str(uuid4()),expected_revision=state['revision'],expected_rollup_revision=1))
        state=self.service.execute(pid,'unarchive_chapter',dict(chapter_id=cid,confirmed=True),expected_revision=state['revision']);self.assertTrue(self.service.memory_rollups(pid)['rollups'][0]['available']);self.assertTrue(self.service.preview_memory_rollup(pid,fields)['can_save'])

    def test_legacy_v1_restored_non_uuid_chapters_archive_trash_restore_and_reject_orphans(self):
        from novel_writer.application.backups import create_backup,restore_backup
        package=self.root/'legacy-v1.nwbak';self.assertEqual(create_backup(self.db,package)['backup_format_version'],51)
        restored=restore_backup(package,self.root/'legacy-v1-restored');service=NovelService(SQLiteRepository(restored['database_path']));state=service.get('p1');chapter=next(c for c in state['document']['chapters'] if c['id']=='p1-c2');original=deepcopy(chapter)
        def action(name,fields):
            nonlocal state
            state=service.execute('p1',name,fields,expected_revision=state['revision'])
        action('archive_chapter',dict(chapter_id='p1-c2',confirmed=True));self.assertEqual(state['chapter_lifecycle_events'][-1]['chapter_id'],'p1-c2')
        action('unarchive_chapter',dict(chapter_id='p1-c2',confirmed=True))
        action('trash_chapter',dict(chapter_id='p1-c2',operation_id=str(uuid4()),confirm_title=chapter['title'],acknowledge_references=True,confirmed=True));self.assertEqual(state['chapter_trash_events'][-1]['chapter_id'],'p1-c2')
        action('restore_trashed_chapter',dict(chapter_id='p1-c2',operation_id=str(uuid4()),confirmed=True));self.assertEqual(next(c for c in state['document']['chapters'] if c['id']=='p1-c2'),original)
        self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get('p1'),state)
        for key in ('chapter_lifecycle_events','chapter_trash_events'):
            tampered=deepcopy(state);tampered[key][-1]['chapter_id']='another-book-chapter'
            with self.assertRaises(ValueError):validate_workspace(tampered)
            tampered=deepcopy(state);tampered[key][-1]['operation_id']='not-an-operation-uuid'
            with self.assertRaises(ValueError):validate_workspace(tampered)

class ChapterRollupHTTPTests(unittest.TestCase):
    setUp=fixture.MemoryRollupHTTPTests.setUp
    stop=fixture.MemoryRollupHTTPTests.stop
    request=fixture.MemoryRollupHTTPTests.request
    def test_chapter_routes_v31_capabilities_no_preview_write_and_explicit_save(self):
        fields=dict(scope='chapter',scope_volume_number=None,through_chapter_id='p1-c2');before=self.db.read_bytes();original=self.request('GET','/api/projects/p1')[1]['document']
        self.assertEqual(self.request('POST','/api/projects/p1/rollups/preview',fields,token=False)[0],403)
        code,preview=self.request('POST','/api/projects/p1/rollups/preview',fields);self.assertEqual(code,200,preview);self.assertEqual(self.db.read_bytes(),before)
        code,saved=self.request('POST','/api/projects/p1/rollups',dict(fields,operation_id=str(uuid4()),expected_revision=preview['revision']));self.assertEqual(code,201,saved);self.assertEqual(saved['rollup']['scope'],'chapter')
        code,state=self.request('GET','/api/projects/p1');self.assertEqual(state['workspace_version'],31);self.assertEqual(state['document'],original)
        code,capabilities=self.request('GET','/api/backups/capabilities');self.assertIn(31,capabilities['workspace_versions']);self.assertIn(31,capabilities['backup_format_versions'])
        self.assertEqual(self.request('POST','/api/projects/p1/rollups/preview',dict(fields,through_chapter_id='p2-c1'))[0],422)
