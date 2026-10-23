"""C05 deterministic layered memory rollups, conflicts and V23 persistence."""
from contextlib import closing
from copy import deepcopy
import http.client,json,sqlite3,sys,tempfile,threading,unittest
from pathlib import Path
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from novel_writer.application.backups import create_backup,restore_backup
from novel_writer.application.migrations import migrate
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import ConflictError,SQLiteRepository,validate_workspace
from novel_writer.ui.server import create_server
FROZEN=json.loads((ROOT/'tests/fixtures/s3b_legacy_v1.json').read_text(encoding='utf8'))


def rows(path):
    with closing(sqlite3.connect(path)) as db:
        return {t:[list(r) for r in db.execute('SELECT * FROM '+t+' ORDER BY 1,2')] for t in ('projects','project_snapshots','skills')}


class MemoryRollupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='novel-c05-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=self.root/'fictional.sqlite3';self.db.write_bytes(bytes.fromhex(FROZEN['database_hex']))
        self.service=NovelService(SQLiteRepository(self.db));self.state=self.service.get('p1')

    def save(self,action,**fields):
        self.state=self.service.execute('p1',action,fields,expected_revision=self.state['revision']);return self.state

    def memory(self,title,text,position='p1-c1',source_kind='chapter',source_id=None,**changes):
        data=dict(kind='event',title=title,text=text,position_chapter_id=position,confirmed=True,active=True,
            source={'kind':source_kind,'entity_id':source_id or position})
        data.update(changes);self.save('save_memory',**data);return self.state['memories'][-1]

    def preview(self,**request):
        return self.service.preview_memory_rollup('p1',request)

    def test_preview_is_deterministic_zero_write_and_filters_scope_position_and_freshness(self):
        first=self.memory('甲','第一章事实','p1-c1')
        second=self.memory('乙','第二章事实','p1-c2')
        self.memory('卷二未来','第十一章事实','p1-c11',volume_number=2)
        self.memory('未确认','不进入汇总','p1-c1',confirmed=False)
        self.memory('已归档','不进入汇总','p1-c1',active=False)
        effective=self.memory('来源更晚','来源在第三章','p1-c1',source_kind='idea',source_id='p1-c3')
        outdated=self.memory('来源会过期','先记录后改正文','p1-c4')
        self.save('save_chapter',chapter_id='p1-c4',content='来源正文已经变化')
        before=self.db.read_bytes()
        request=dict(scope='volume',scope_volume_number=1,through_chapter_id='p1-c5')
        one=self.preview(**request);two=self.preview(**request)
        self.assertEqual(one,two);self.assertEqual(self.db.read_bytes(),before)
        self.assertEqual(one['source_memory_ids'],[first['id'],second['id'],effective['id']])
        self.assertNotIn(outdated['id'],one['source_memory_ids']);self.assertNotIn(effective['id'],self.preview(scope='volume',scope_volume_number=1,through_chapter_id='p1-c2')['source_memory_ids'])
        self.assertEqual(one['text'],one['title']+'\n\n### 甲\n来源记忆：'+first['id']+' · 第1版\n第一章事实\n\n### 乙\n来源记忆：'+second['id']+' · 第1版\n第二章事实\n\n### 来源更晚\n来源记忆：'+effective['id']+' · 第1版\n来源在第三章')
        self.assertFalse(one['can_save'] is False);self.assertIsNone(one['existing']);self.assertEqual(one['revision'],self.state['revision'])

    def test_save_rebuild_idempotency_stale_after_add_edit_source_and_archive(self):
        first=self.memory('甲','事实一','p1-c1')
        second=self.memory('乙','事实二','p1-c2')
        request=dict(scope='volume',scope_volume_number=1,through_chapter_id='p1-c5')
        preview=self.preview(**request);operation=str(uuid4())
        saved=self.service.save_memory_rollup('p1',dict(request,operation_id=operation,expected_revision=preview['revision']))
        self.assertFalse(saved['idempotent']);identifier=saved['rollup']['id']
        self.state=self.service.get('p1');self.assertEqual(self.state['workspace_version'],23)
        self.assertEqual(len(self.state['memory_rollup_history']),1);self.assertFalse(self.service.memory_rollups('p1')['rollups'][0]['stale'])
        retry=self.service.save_memory_rollup('p1',dict(request,operation_id=operation,expected_revision=preview['revision']))
        self.assertTrue(retry['idempotent']);self.assertEqual(self.service.get('p1')['revision'],self.state['revision'])
        self.memory('丙','第三条事实','p1-c3');self.state=self.service.get('p1')
        self.assertTrue(self.service.memory_rollups('p1')['rollups'][0]['stale'])
        with self.assertRaises(ConflictError):self.service.rebuild_memory_rollup('p1',identifier,dict(operation_id=str(uuid4()),expected_revision=self.state['revision'],expected_rollup_revision=2))
        rebuilt=self.service.rebuild_memory_rollup('p1',identifier,dict(operation_id=str(uuid4()),expected_revision=self.state['revision'],expected_rollup_revision=1))
        self.assertEqual(rebuilt['rollup']['revision'],2);self.state=self.service.get('p1');self.assertFalse(self.service.memory_rollups('p1')['rollups'][0]['stale'])
        self.save('save_memory',memory_id=first['id'],text='事实一已纠正');self.assertTrue(self.service.memory_rollups('p1')['rollups'][0]['stale'])
        self.state=self.service.get('p1');self.service.rebuild_memory_rollup('p1',identifier,dict(operation_id=str(uuid4()),expected_revision=self.state['revision'],expected_rollup_revision=2));self.state=self.service.get('p1')
        self.save('save_chapter',chapter_id='p1-c2',content='第二章来源已改');self.assertTrue(self.service.memory_rollups('p1')['rollups'][0]['stale'])
        self.save('archive_memory',memory_id=second['id']);self.assertTrue(self.service.memory_rollups('p1')['rollups'][0]['stale'])

    def test_conflicts_are_derived_block_save_and_disappear_after_archive(self):
        first=self.memory('同一事件','港口在雨夜关闭','p1-c2',volume_number=1,character_id='p1-char1')
        second=self.memory('同一事件','港口在清晨关闭','p1-c2',volume_number=1,character_id='p1-char1')
        self.memory('不同标题','允许共存','p1-c2',volume_number=1,character_id='p1-char1')
        conflicts=self.service.memory_rollups('p1')['conflicts'];self.assertEqual(len(conflicts),1)
        self.assertEqual(set(conflicts[0]['memory_ids']),{first['id'],second['id']})
        preview=self.preview(scope='volume',scope_volume_number=1,through_chapter_id='p1-c5');self.assertEqual(len(preview['conflicts']),1);self.assertFalse(preview['can_save'])
        before=self.db.read_bytes()
        with self.assertRaises(ValueError):self.service.save_memory_rollup('p1',dict(scope='volume',scope_volume_number=1,through_chapter_id='p1-c5',operation_id=str(uuid4()),expected_revision=self.state['revision']))
        self.assertEqual(self.db.read_bytes(),before);self.assertEqual({item['text'] for item in self.service.memory_rollups('p1')['conflicts'][0]['texts']},{'港口在雨夜关闭','港口在清晨关闭'})
        self.save('archive_memory',memory_id=second['id']);self.assertEqual(self.service.memory_rollups('p1')['conflicts'],[])
        result=self.service.save_memory_rollup('p1',dict(scope='volume',scope_volume_number=1,through_chapter_id='p1-c5',operation_id=str(uuid4()),expected_revision=self.state['revision']))
        self.assertIn(first['id'],{source['memory_id'] for source in result['rollup']['sources']})

    def test_v23_tamper_reopen_and_backup_restore_copy_remap_ids(self):
        first=self.memory('甲','事实一','p1-c1');self.memory('乙','事实二','p1-c2')
        request=dict(scope='book',scope_volume_number=None,through_chapter_id='p1-c5');preview=self.preview(**request)
        saved=self.service.save_memory_rollup('p1',dict(request,operation_id=str(uuid4()),expected_revision=preview['revision']))
        state=self.service.get('p1');identifier=saved['rollup']['id']
        self.assertEqual(NovelService(SQLiteRepository(self.db)).get('p1'),state)
        before=self.db.read_bytes();tampered=deepcopy(state);tampered['memory_rollups'][0]['text']+='篡改'
        with self.assertRaises(ValueError):SQLiteRepository(self.db).save(tampered,expected_revision=state['revision'])
        self.assertEqual(self.db.read_bytes(),before)
        tampered=deepcopy(state);tampered['memory_rollups'][0]['sources'][0]['text']='伪造'
        with self.assertRaises(ValueError):validate_workspace(tampered)
        package=self.root/'c05.nwbak';manifest=create_backup(self.db,package);self.assertEqual(manifest['backup_format_version'],51)
        restored=Path(restore_backup(package,self.root/'restored')['database_path']);self.assertEqual(NovelService(SQLiteRepository(restored)).get('p1'),state)
        target=self.root/'target.sqlite3';target.write_bytes(bytes.fromhex(FROZEN['database_hex']))
        result=migrate(package,target,operation_id=str(uuid4()));new=next(p['new_id'] for p in result['projects'] if p['old_id']=='p1')
        copied=NovelService(SQLiteRepository(target)).get(new);mapping={(item['kind'],item['old_id']):item['new_id'] for item in result['id_map'] if item['old_project_id']=='p1'}
        rollup=copied['memory_rollups'][0]
        self.assertEqual(rollup['id'],mapping['memory_rollup',identifier]);self.assertEqual(rollup['sources'][0]['memory_id'],mapping['memory',first['id']])
        self.assertIn(mapping['memory',first['id']],rollup['text']);self.assertNotIn(first['id'],rollup['text'])
        self.assertEqual(rollup['through_chapter_id'],mapping['chapter','p1-c5']);self.assertEqual(copied['memory_rollup_history'][0]['rollup_id'],rollup['id'])
        self.assertEqual(copied['memory_rollup_history'][0]['snapshot']['text'],rollup['text'])
        self.assertEqual(copied['memory_rollup_history'][0]['operation_id'],state['memory_rollup_history'][0]['operation_id'])
        self.assertFalse(NovelService(SQLiteRepository(target)).memory_rollups(new)['rollups'][0]['stale'])


class MemoryRollupHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='novel-c05-http-');self.addCleanup(self.temp.cleanup)
        self.db=Path(self.temp.name)/'fictional.sqlite3';self.db.write_bytes(bytes.fromhex(FROZEN['database_hex']))
        self.server=create_server(self.db,port=0,offline=True);self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True)
        self.thread.start();self.addCleanup(self.stop)
    def stop(self):self.server.shutdown();self.thread.join(3);self.server.server_close()
    def request(self,method,path,data=None,token=True):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_address[1],timeout=20)
        headers={'Content-Type':'application/json'}
        if token:headers['X-Novel-Token']=self.server.token
        try:
            conn.request(method,path,json.dumps(data) if data is not None else None,headers);response=conn.getresponse();body=response.read();return response.status,json.loads(body) if body else None
        finally:conn.close()
    def test_preview_is_read_only_save_rebuild_and_conflicts_are_real_routes(self):
        code,capabilities=self.request('GET','/api/backups/capabilities');self.assertEqual(code,200);self.assertIn(23,capabilities['backup_format_versions']);self.assertIn(23,capabilities['workspace_versions'])
        code,migrations=self.request('GET','/api/migrations/capabilities');self.assertEqual(code,200);self.assertIn('backup_v23',migrations['formats'])
        self.assertEqual(self.request('POST','/api/projects/p1/rollups/preview',dict(scope='book',scope_volume_number=None,through_chapter_id='p1-c5'),token=False)[0],403)
        before=self.db.read_bytes();code,preview=self.request('POST','/api/projects/p1/rollups/preview',dict(scope='book',scope_volume_number=None,through_chapter_id='p1-c5'))
        self.assertEqual(code,200,preview);self.assertEqual(self.db.read_bytes(),before);self.assertEqual(preview['source_memory_ids'],[])
        fields=dict(kind='event',title='事件',text='HTTP 汇总事实',position_chapter_id='p1-c2',confirmed=True,source={'kind':'chapter','entity_id':'p1-c2'})
        self.assertEqual(self.request('POST','/api/projects/p1/actions',dict(action='save_memory',fields=fields,expected_revision=1))[0],200)
        code,preview=self.request('POST','/api/projects/p1/rollups/preview',dict(scope='book',scope_volume_number=None,through_chapter_id='p1-c5'));self.assertEqual(code,200)
        operation=str(uuid4());code,saved=self.request('POST','/api/projects/p1/rollups',dict(scope='book',scope_volume_number=None,through_chapter_id='p1-c5',operation_id=operation,expected_revision=preview['revision']))
        self.assertEqual(code,201,saved);identifier=saved['rollup']['id'];self.assertFalse(saved['idempotent'])
        code,retry=self.request('POST','/api/projects/p1/rollups',dict(scope='book',scope_volume_number=None,through_chapter_id='p1-c5',operation_id=operation,expected_revision=preview['revision']))
        self.assertEqual(code,201);self.assertTrue(retry['idempotent'])
        code,listing=self.request('GET','/api/projects/p1/rollups');self.assertEqual(code,200);self.assertFalse(listing['rollups'][0]['stale']);self.assertEqual(listing['conflicts'],[])
        state=self.request('GET','/api/projects/p1')[1];code,rebuilt=self.request('POST',f'/api/projects/p1/rollups/{identifier}/rebuild',dict(operation_id=str(uuid4()),expected_revision=state['revision'],expected_rollup_revision=1))
        self.assertEqual(code,200,rebuilt);self.assertEqual(rebuilt['rollup']['revision'],2)
        self.assertEqual(self.request('POST','/api/projects/p1/rollups',dict(scope='book',scope_volume_number=None,through_chapter_id='p1-c5'))[0],422)
    def test_conflict_route_and_memory_page_assets(self):
        base=dict(kind='event',position_chapter_id='p1-c2',confirmed=True,source={'kind':'chapter','entity_id':'p1-c2'})
        self.request('POST','/api/projects/p1/actions',dict(action='save_memory',fields=dict(base,title='同题',text='版本甲'),expected_revision=1))
        self.request('POST','/api/projects/p1/actions',dict(action='save_memory',fields=dict(base,title='同题',text='版本乙'),expected_revision=2))
        code,data=self.request('GET','/api/projects/p1/rollups/conflicts');self.assertEqual(code,200);self.assertEqual(len(data['conflicts']),1);self.assertEqual(len(data['conflicts'][0]['memory_ids']),2)
        views=(ROOT/'src/novel_writer/ui/static/views.js').read_text(encoding='utf8');app=(ROOT/'src/novel_writer/ui/static/app.js').read_text(encoding='utf8')
        for marker in ('preview-memory-rollup','save-memory-rollup','data-memory-jump','来源已变化'):self.assertIn(marker,views)
        for marker in ('previewMemoryRollup','saveMemoryRollup','rebuildMemoryRollup'):self.assertIn(marker,app)


if __name__=='__main__':unittest.main()
