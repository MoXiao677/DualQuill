"""Fictional local recovery faults; never change disk capacity or Windows ACLs."""
import errno
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from http.client import HTTPConnection
import threading

from novel_writer.application.drafts import DiskDrafts, DraftError
from novel_writer.application.local_data import LocalDataSafety, LocalDataError


class MetadataReuseValidationTests(unittest.TestCase):
    def test_warm_type_metadata_never_reuses_author_value_validation(self):
        from novel_writer.application import projects, versions
        from novel_writer.domain.models import Chapter, DataValidationError, validate_document
        from novel_writer.storage.json_codec import document_from_dict
        document=document_from_dict(projects.create(dict(title='虚构类型元数据'))['document'])
        chapter=Chapter(project_id=document.project.id,number=1,title='虚构章',content='虚构正文')
        document.chapters.append(chapter)
        version=versions.record(document,'chapter',chapter,'虚构原版本')
        validate_document(document)
        chapter.number=False
        with self.assertRaises(DataValidationError):validate_document(document)
        chapter.number=1
        version.snapshot['content']=42
        with self.assertRaises(DataValidationError):validate_document(document)
        version.snapshot['content']='虚构正文'
        validate_document(document)


class DraftRecoveryFaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='author-stability-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = DiskDrafts(self.root / 'drafts')
        self.key = json.dumps(['fiction', 'writing', 'chapter', 'body'])

    def test_other_projects_are_not_reported_as_corrupt(self):
        self.store.save('fiction', self.key, 1, {'content': '虚构未保存正文'})
        self.assertEqual(self.store.list('another'), {'drafts': [], 'corrupt': []})

    def test_invalid_base_revision_is_not_restored(self):
        self.store.save('fiction', self.key, 1, {'content': '虚构未保存正文'})
        path = next(self.store.directory.glob('*.json'))
        value = json.loads(path.read_text(encoding='utf-8'))
        value['base_revision'] = False
        path.write_text(json.dumps(value), encoding='utf-8')
        listed = self.store.list('fiction')
        self.assertEqual(listed['drafts'], [])
        self.assertEqual(listed['corrupt'], [path.name])

    def test_draft_directory_permission_error_is_visible(self):
        with patch.object(Path, 'iterdir', side_effect=PermissionError('fictional-private-path')):
            with self.assertRaisesRegex(DraftError, '读取失败') as caught:
                self.store.list('fiction')
        self.assertNotIn('fictional-private-path', str(caught.exception))

    def test_disk_full_and_permission_failure_preserve_previous_draft(self):
        self.store.save('fiction', self.key, 1, {'content': '原恢复草稿'})
        for error in (OSError(errno.ENOSPC, 'fictional full'), PermissionError('fictional denied')):
            with self.subTest(error=type(error).__name__):
                with patch('novel_writer.application.drafts.os.replace', side_effect=error):
                    with self.assertRaisesRegex(DraftError, '保留输入'):
                        self.store.save('fiction', self.key, 2, {'content': '待重试输入'})
                self.assertEqual(self.store.list('fiction')['drafts'][0]['values']['content'], '原恢复草稿')
                self.assertEqual(list(self.store.directory.glob('.draft-*.tmp')), [])

    def test_unavailable_draft_partition_does_not_prevent_store_construction(self):
        with patch.object(Path, 'mkdir', side_effect=PermissionError('fictional denied')):
            store = DiskDrafts(self.root / 'unavailable')
            with self.assertRaisesRegex(DraftError, '保留输入'):
                store.save('fiction', self.key, 1, {'content': '窗口仍有输入'})

    def test_invalid_unicode_is_not_hydrated_or_allowed_to_break_http(self):
        self.store.save('fiction',self.key,1,{'content':'虚构正常'})
        path=next(self.store.directory.glob('*.json'))
        value=json.loads(path.read_text(encoding='utf-8'))
        value['values']['content']='\ud800'
        path.write_text(json.dumps(value,ensure_ascii=True),encoding='utf-8')
        self.assertEqual(self.store.list('fiction')['drafts'],[])
        with self.assertRaises(DraftError):
            self.store.save('fiction',self.key,1,{'content':'\ud800'})

    def test_unreadable_file_is_reported_separately_and_kept(self):
        self.store.save('fiction',self.key,1,{'content':'虚构正常'})
        path=next(self.store.directory.glob('*.json'))
        with patch.object(Path,'read_text',side_effect=PermissionError('fictional denied file')):
            listed=self.store.list('fiction')
        self.assertEqual(listed,dict(drafts=[],corrupt=[],unreadable=1))
        self.assertTrue(path.exists())

    def test_deep_unknown_json_is_reported_without_losing_or_deleting_it(self):
        bad=self.store.directory/('a'*64+'.json')
        bad.write_text('['*2000+'0'+']'*2000,encoding='utf-8')
        listed=self.store.list('fiction')
        self.assertEqual(listed,dict(drafts=[],corrupt=[bad.name]))
        safety=LocalDataSafety(self.store,self.root/'fiction.sqlite3',offline=True,models_enabled=False)
        preview=safety.preview()
        self.assertEqual(preview['candidates'],[])
        self.assertEqual(preview['report']['recovery_drafts']['preserved'],1)
        self.assertTrue(bad.exists())


class LocalDataSafetyTests(unittest.TestCase):
    def setUp(self):
        DraftRecoveryFaultTests.setUp(self)
        self.database = self.root / 'fiction.sqlite3'
        self.database.write_bytes(b'fictional database untouched')
        self.safety = LocalDataSafety(self.store, self.database, offline=True, models_enabled=False)
        self.store.save('fiction', self.key, 1, {'content': 'private-author-body-marker'})
        self.valid = next(self.store.directory.glob('*.json'))
        self.corrupt = self.store.directory / ('a' * 64 + '.json')
        self.corrupt.write_text('{private-corrupt-body-marker', encoding='utf-8')
        self.unknown = self.store.directory / 'unknown-private-title.txt'
        self.unknown.write_text('private-unknown-marker', encoding='utf-8')

    def cleanup(self, preview, selected=None, **changes):
        fields = dict(preview_token=preview['preview_token'],
                      selected=[item['id'] for item in preview['candidates']] if selected is None else selected,
                      confirmation='清理损坏草稿')
        fields.update(changes)
        return self.safety.cleanup(**fields)

    def test_preview_is_redacted_and_zero_write_and_cleanup_is_selective(self):
        before = {path.name: path.read_bytes() for path in self.store.directory.iterdir()}
        preview = self.safety.preview()
        self.assertEqual(preview['report']['recovery_drafts'], dict(valid=1, corrupt=1, preserved=1, bytes=self.valid.stat().st_size+self.corrupt.stat().st_size))
        serialized = json.dumps(preview)
        for private in ('private-', self.root.name, self.valid.name, self.corrupt.name, self.key, 'fiction.sqlite3'):
            self.assertNotIn(private, serialized)
        self.assertEqual({path.name: path.read_bytes() for path in self.store.directory.iterdir()}, before)
        outcome = self.cleanup(preview)
        self.assertTrue(outcome['completed'])
        self.assertEqual(outcome['removed_count'], 1)
        self.assertFalse(self.corrupt.exists())
        self.assertEqual(self.valid.read_bytes(), before[self.valid.name])
        self.assertEqual(self.unknown.read_bytes(), before[self.unknown.name])
        self.assertEqual(self.database.read_bytes(), b'fictional database untouched')
        with self.assertRaisesRegex(LocalDataError, '过期'):
            self.cleanup(preview)

    def test_stale_preview_refuses_every_selected_item_before_first_delete(self):
        another = self.store.directory / ('b' * 64 + '.json')
        another.write_text('{broken', encoding='utf-8')
        preview = self.safety.preview()
        self.corrupt.write_text('{changed', encoding='utf-8')
        with self.assertRaisesRegex(LocalDataError, '未清理'):
            self.cleanup(preview)
        self.assertTrue(another.exists())
        self.assertTrue(self.corrupt.exists())

    def test_expiry_confirmation_unknown_selection_and_paths_refuse_zero_delete(self):
        preview = self.safety.preview()
        for fields in (dict(confirmation='yes'), dict(selected=['../fiction.sqlite3']),
                       dict(selected=[]), dict(preview_token='not-issued')):
            with self.subTest(fields=fields), self.assertRaises(LocalDataError):
                self.cleanup(preview, **fields)
        with patch('novel_writer.application.local_data.time.monotonic', return_value=10**15):
            with self.assertRaisesRegex(LocalDataError, '过期'):
                self.cleanup(preview)
        self.assertTrue(self.corrupt.exists())

    def test_directory_replacement_after_preview_is_refused(self):
        preview = self.safety.preview()
        held = self.root / 'held'
        self.store.directory.rename(held)
        self.store.directory.mkdir()
        (self.store.directory / self.corrupt.name).write_text('{replacement', encoding='utf-8')
        with self.assertRaisesRegex(LocalDataError, '未清理'):
            self.cleanup(preview)
        self.assertTrue((held / self.corrupt.name).exists())
        self.assertTrue(self.corrupt.exists())

    def test_partial_permission_failure_reports_actual_progress_and_is_retryable(self):
        another = self.store.directory / ('b' * 64 + '.json')
        another.write_text('{broken', encoding='utf-8')
        preview = self.safety.preview()
        original = Path.unlink
        def denied(path, *args, **kwargs):
            if path.name == another.name:
                raise PermissionError('private-denied-path')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'unlink', denied):
            outcome = self.cleanup(preview)
        self.assertFalse(outcome['completed'])
        self.assertEqual((outcome['removed_count'], outcome['remaining_count']), (1, 1))
        self.assertNotIn('private-denied-path', json.dumps(outcome))
        self.assertTrue(another.exists())
        self.assertTrue(self.cleanup(self.safety.preview())['completed'])

    def test_hardlinked_corrupt_record_is_preserved(self):
        import os
        os.link(self.corrupt, self.root / 'held-corrupt.json')
        preview = self.safety.preview()
        self.assertEqual(preview['candidates'], [])
        self.assertEqual(preview['report']['recovery_drafts']['preserved'], 2)
        self.assertTrue(self.corrupt.exists())

    def test_future_draft_version_and_unknown_json_are_not_cleanup_candidates(self):
        value = json.loads(self.valid.read_text(encoding='utf-8'))
        value['version'] = 2
        self.valid.write_text(json.dumps(value), encoding='utf-8')
        unknown_json = self.store.directory/('b'*64+'.json')
        unknown_json.write_text('{"unknown":"keep"}', encoding='utf-8')
        preview = self.safety.preview()
        self.assertEqual(len(preview['candidates']),1)
        self.assertEqual(preview['report']['recovery_drafts']['preserved'],3)
        self.cleanup(preview)
        self.assertTrue(self.valid.exists())
        self.assertTrue(unknown_json.exists())


class LocalDataHttpTests(unittest.TestCase):
    def setUp(self):
        from novel_writer.ui.server import create_server
        self.temp = tempfile.TemporaryDirectory(prefix='author-local-http-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.server = create_server(self.root/'fiction.sqlite3', port=0, offline=True,
                                    provider_path=self.root/'never-configured.dpapi')
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval':.01}, daemon=True)
        self.thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), self.thread.join(2)))
        self.corrupt = self.server.drafts.directory/('a'*64+'.json')
        self.corrupt.write_text('{fictional-private-content', encoding='utf-8')

    def request(self, path, payload, *, token=True, origin=None):
        client = HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        headers = {'Content-Type':'application/json'}
        if token:headers['X-Novel-Token'] = self.server.token
        if origin:headers['Origin'] = origin
        try:
            client.request('POST',path,json.dumps(payload),headers)
            response=client.getresponse()
            return response.status,json.loads(response.read())
        finally:
            client.close()

    def test_token_origin_field_guards_and_actual_selective_cleanup(self):
        base = '/api/settings/local-data/'
        self.assertEqual(self.request(base+'preview',{},token=False)[0],403)
        self.assertEqual(self.request(base+'preview',{},origin='https://outside.invalid')[0],403)
        self.assertEqual(self.request(base+'preview',{'path':str(self.root)})[0],422)
        code, preview = self.request(base+'preview',{})
        self.assertEqual(code,200)
        self.assertTrue(preview['report']['offline'])
        self.assertFalse(preview['report']['model_generation_enabled'])
        self.assertNotIn('fictional-private-content',json.dumps(preview))
        self.assertNotIn(str(self.root),json.dumps(preview))
        fields = dict(preview_token=preview['preview_token'],selected=[preview['candidates'][0]['id']],confirmation='清理损坏草稿')
        self.assertEqual(self.request(base+'cleanup',fields,token=False)[0],403)
        self.assertTrue(self.corrupt.exists())
        code, result = self.request(base+'cleanup',fields)
        self.assertEqual(code,200)
        self.assertEqual(result['removed_count'],1)
        self.assertFalse(self.corrupt.exists())
        self.assertEqual(self.request(base+'cleanup',fields)[0],422)
        self.assertFalse((self.root/'never-configured.dpapi').exists())

    def test_permission_failure_is_safe_retryable_http_error(self):
        with patch.object(Path,'iterdir',side_effect=PermissionError('private-test-path')):
            code, result = self.request('/api/settings/local-data/preview',{})
        self.assertEqual(code,422)
        self.assertNotIn('private-test-path',json.dumps(result))
        self.assertEqual(self.request('/api/settings/local-data/preview',{})[0],200)

    def test_offline_author_lifecycle_backup_restore_and_continue(self):
        from uuid import uuid4
        from novel_writer.application.backups import create_backup, restore_backup
        from novel_writer.application.service import NovelService
        from novel_writer.storage.sqlite_repository import SQLiteRepository
        code, state = self.request('/api/projects',dict(title='虚构离线完整作者流程'))
        self.assertEqual(code,201)
        project = state['document']['project']['id']
        def action(name, fields, expected=200):
            nonlocal state
            code, result = self.request('/api/projects/'+project+'/actions',dict(action=name,fields=fields,expected_revision=state['revision']))
            self.assertEqual(code,expected,result)
            if code==200:state=result
            return result
        action('add_chapter',dict(title='虚构第一章'))
        first=state['document']['chapters'][0]['id']
        action('save_chapter',dict(chapter_id=first,content='虚构已确认原稿😀\n',status='confirmed'))
        before=json.loads(json.dumps(state))
        action('save_chapter',dict(chapter_id=first,content='未经确认不应保存'),422)
        self.assertEqual(self.server.service.get(project),before)
        action('add_chapter',dict(title='虚构第二章'))
        second=state['document']['chapters'][1]['id']
        action('save_chapter',dict(chapter_id=second,content='第二章离线正文'))
        action('save_book_outline',dict(volumes=[dict(number=1,title='卷一',summary='',chapter_ids=[first]),dict(number=2,title='卷二',summary='',chapter_ids=[second])]))
        action('move_chapter_to_volume',dict(chapter_id=first,target_volume_number=2,target_index=0,confirmed=True))
        history_before=json.loads(json.dumps(state['document']['versions']))
        action('trash_chapter',dict(chapter_id=second,operation_id=str(uuid4()),confirm_title='虚构第二章',acknowledge_references=True,confirmed=True))
        self.assertEqual(state['document']['versions'],history_before)
        action('restore_trashed_chapter',dict(chapter_id=second,operation_id=str(uuid4()),confirmed=True))
        self.assertEqual(state['document']['book_outline']['volumes'][1]['chapter_ids'],[first,second])
        client=HTTPConnection('127.0.0.1',self.server.server_port,timeout=10)
        try:
            client.request('GET','/api/projects/'+project+'/export/book/txt')
            response=client.getresponse();self.assertEqual(response.status,200)
            exported=response.read().decode('utf-8')
            self.assertIn('虚构已确认原稿😀\n',exported)
            self.assertIn('第二章离线正文',exported)
        finally:client.close()
        package=self.root/'fiction.nwbak'
        create_backup(self.server.database_path,package)
        restored=restore_backup(package,self.root/'restored')
        service=NovelService(SQLiteRepository(restored['database_path']))
        recovered=service.get(project)
        self.assertEqual(recovered,state)
        recovered=service.execute(project,'save_chapter',dict(chapter_id=second,content='恢复后继续离线写作'),expected_revision=recovered['revision'])
        self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(project),recovered)
        self.assertEqual(self.server.service.get(project),state)
        self.assertEqual(recovered['document']['versions'][:-1],history_before)
        self.assertFalse((self.root/'never-configured.dpapi').exists())

    def test_new_browser_asset_and_desktop_route_are_available(self):
        client = HTTPConnection('127.0.0.1',self.server.server_port,timeout=10)
        try:
            client.request('GET','/local_data.js')
            response=client.getresponse()
            self.assertEqual(response.status,200)
            self.assertIn(b'renderLocalData',response.read())
        finally:
            client.close()


if __name__ == '__main__':
    unittest.main()
