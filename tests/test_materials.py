"""V25 本地资料、追加版本、字面索引与显式检索边界。"""
import base64,json,sys,tempfile,unittest
from pathlib import Path
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from novel_writer.application.backups import create_backup,restore_backup
from novel_writer.application.full_book_planning import FullBookPlanning
from novel_writer.application.materials import Materials
from novel_writer.application.migrations import migrate
from novel_writer.application.service import NovelService
from novel_writer.domain.materials import CHUNK_CHARS,CHUNK_OVERLAP,chunk_ranges,index_status
from novel_writer.storage.sqlite_repository import ConflictError,SQLiteRepository
from novel_writer.application.skill_import import SkillLibrary


class MaterialsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='novel-materials-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=self.root/'fiction.sqlite3';self.service=NovelService(SQLiteRepository(self.db))
        state=self.service.create(title='资料业务虚构测试');self.pid=state['document']['project']['id']
        state=self.service.execute(self.pid,'add_chapter',dict(title='第一章'),expected_revision=state['revision'])
        self.chapter=state['document']['chapters'][0]['id'];self.materials=Materials(self.service)

    def revision(self):return self.service.get(self.pid)['revision']
    def create(self,text='资料 KEYWORD 正文',**values):
        request=dict(operation_id=str(uuid4()),expected_revision=self.revision(),title='资料',format='txt',tags=[],text=text)
        request.update(values);return self.materials.create(self.pid,request)
    def rebuild(self,material_id):
        return self.materials.rebuild(self.pid,material_id,dict(operation_id=str(uuid4()),expected_revision=self.revision()))

    def test_create_paste_and_base64_utf8_bom_and_limits(self):
        created=self.create('第一行\n第二行 KEYWORD',title=' 资料标题 ',tags=[' 参考 ','参考','新标签'])
        material=created['material'];self.assertEqual(material['title'],'资料标题');self.assertEqual(material['tags'],('参考','新标签'))
        self.assertEqual(material['index_status'],'missing');self.assertEqual(material['version_count'],1)
        detail=self.materials.describe(self.pid,material['id']);self.assertEqual(detail['versions'][0]['version_number'],1)
        self.assertEqual(self.materials.version(self.pid,material['id'],detail['versions'][0]['id'])['text'],'第一行\n第二行 KEYWORD')
        payload=base64.b64encode('\ufeff带BOM的Markdown\n第二行'.encode('utf8')).decode()
        uploaded=self.materials.create(self.pid,dict(operation_id=str(uuid4()),expected_revision=self.revision(),title='上传',format='md',tags=[],data_base64=payload))
        version=self.materials.version(self.pid,uploaded['material']['id'],uploaded['material']['current_version_id'])
        self.assertEqual(version['text'],'带BOM的Markdown\n第二行')
        for request,message in (
            (dict(title='双来源',format='txt',tags=[],text='x',data_base64=payload),'text_source'),
            (dict(title='二进制',format='txt',tags=[],data_base64=base64.b64encode(b'abc\x00def').decode()),'invalid'),
            (dict(title='控制字符',format='txt',tags=[],text='bad\x01text'),'invalid'),
            (dict(title='格式',format='pdf',tags=[],text='x'),'format'),
            (dict(title='超长',format='txt',tags=[],text='x'*4_000_001),'invalid')):
            with self.subTest(title=request['title']):
                with self.assertRaises(ValueError):
                    self.materials.create(self.pid,dict(operation_id=str(uuid4()),expected_revision=self.revision(),**request))

    def test_versions_are_append_only_and_old_text_remains_readable(self):
        created=self.create('第一版 KEYWORD');material=created['material'];first=created['material']['current_version_id']
        updated=self.materials.update(self.pid,material['id'],dict(operation_id=str(uuid4()),expected_revision=created['revision'],
            title='资料 v2',format='md',tags=['新版'],note='追加第二版',text='第二版 KEYWORD'))
        self.assertEqual(updated['material']['version_count'],2);self.assertEqual(updated['material']['index_status'],'missing')
        versions=updated['versions'];self.assertEqual([v['version_number'] for v in versions],[1,2]);self.assertEqual(versions[1]['previous_version_id'],first)
        self.assertEqual(self.materials.version(self.pid,material['id'],first)['text'],'第一版 KEYWORD')
        stored=self.service.get(self.pid);self.assertEqual([v['version_number'] for v in stored['material_versions']], [1,2])
        self.assertEqual(stored['material_versions'][0]['text'],'第一版 KEYWORD')

    def test_archive_restore_and_refusal_to_change_archived(self):
        created=self.create('归档 KEYWORD');material=created['material'];self.rebuild(material['id'])
        archived=self.materials.archive(self.pid,material['id'],dict(operation_id=str(uuid4()),expected_revision=self.revision()))
        self.assertTrue(archived['material']['archived'])
        with self.assertRaises(ValueError):
            self.materials.update(self.pid,material['id'],dict(operation_id=str(uuid4()),expected_revision=self.revision(),title='改',format='txt',tags=[],text='改'))
        with self.assertRaises(ValueError):
            self.materials.rebuild(self.pid,material['id'],dict(operation_id=str(uuid4()),expected_revision=self.revision()))
        restored=self.materials.restore(self.pid,material['id'],dict(operation_id=str(uuid4()),expected_revision=self.revision()))
        self.assertFalse(restored['material']['archived'])
        listing=self.materials.listing(self.pid);self.assertEqual([value['archived'] for value in listing['materials']],[False])

    def test_operation_id_is_idempotent_and_revision_conflicts_are_explicit(self):
        identity=str(uuid4());revision=self.revision();request=dict(operation_id=identity,expected_revision=revision,title='幂等',format='txt',tags=[],text='幂等 KEYWORD')
        first=self.materials.create(self.pid,request);state=self.service.get(self.pid)
        replay=self.materials.create(self.pid,request);self.assertEqual(replay['revision'],first['revision'])
        self.assertEqual(len(self.service.get(self.pid)['materials']),1);self.assertEqual(self.service.get(self.pid)['revision'],state['revision'])
        with self.assertRaises(ValueError):
            self.materials.create(self.pid,dict(request,text='不同正文'))
        with self.assertRaises(ConflictError):
            self.materials.create(self.pid,dict(request,operation_id=str(uuid4()),expected_revision=revision-1))
        update_identity=str(uuid4());updated=self.materials.update(self.pid,first['material']['id'],dict(operation_id=update_identity,expected_revision=first['revision'],title='幂等',format='txt',tags=[],note='v2',text='第二版'))
        replay_update=self.materials.update(self.pid,first['material']['id'],dict(operation_id=update_identity,expected_revision=first['revision'],title='幂等',format='txt',tags=[],note='v2',text='第二版'))
        self.assertEqual(replay_update['material']['version_count'],2);self.assertEqual(updated['material']['version_count'],2)

    def test_chunk_ranges_are_deterministic_and_stale_state_requires_rebuild(self):
        text='甲'*2000;created=self.create(text);material=created['material']
        self.assertEqual(list(chunk_ranges(2000)),[(0,800),(680,1480),(1360,2000)])
        first=self.rebuild(material['id']);ranges=[(c['start'],c['end'],c['text_sha256']) for c in first['chunks']]
        second=self.rebuild(material['id']);self.assertEqual([(c['start'],c['end'],c['text_sha256']) for c in second['chunks']],ranges)
        self.assertEqual(first['material']['index_status'],'current');self.assertEqual(CHUNK_CHARS,800);self.assertEqual(CHUNK_OVERLAP,120)
        updated=self.materials.update(self.pid,material['id'],dict(operation_id=str(uuid4()),expected_revision=self.revision(),title='资料',format='txt',tags=[],text='新'+text))
        self.assertEqual(updated['material']['index_status'],'stale');self.assertEqual(len(updated['versions']),2)
        rebuilt=self.rebuild(material['id']);self.assertEqual(rebuilt['material']['index_status'],'current');self.assertEqual(len(rebuilt['versions']),2)
        self.assertEqual(len(self.service.get(self.pid)['material_versions']),2)

    def test_rebuild_all_skips_archived_without_touching_versions(self):
        first=self.create('一 KEYWORD');second=self.create('二 KEYWORD');self.rebuild(first['material']['id'])
        self.materials.archive(self.pid,second['material']['id'],dict(operation_id=str(uuid4()),expected_revision=self.revision()))
        identity=str(uuid4());request=dict(operation_id=identity,expected_revision=self.revision())
        result=self.materials.rebuild_all(self.pid,request)
        self.assertEqual(result['rebuilt_material_ids'],[first['material']['id']])
        self.assertEqual(result['skipped_archived_material_ids'],[second['material']['id']])
        self.assertEqual(len(self.service.get(self.pid)['material_versions']),2)
        replay=self.materials.rebuild_all(self.pid,request)
        self.assertEqual(replay['rebuilt_material_ids'],[first['material']['id']]);self.assertNotIn(second['material']['id'],replay['rebuilt_material_ids'])

    def test_literal_search_requires_explicit_material_and_returns_ranges(self):
        text='前缀 '+'甲'*300+' KEYWORD '+'乙'*300;created=self.create(text);material=created['material'];self.rebuild(material['id'])
        result=self.service.search_local(self.pid,dict(query='KEYWORD',chapter_id=self.chapter,scopes=['materials'],material_ids=[material['id']]))
        self.assertEqual(len(result['hits']),1);hit=result['hits'][0]
        self.assertEqual(hit['kind'],'material');self.assertEqual(hit['entity_id'],material['id']);self.assertEqual(hit['version_number'],1)
        offset=text.index('KEYWORD');self.assertEqual(hit['start'],offset);self.assertEqual(hit['end'],offset+len('KEYWORD'));self.assertEqual(hit['chunk_ordinal'],0)
        self.assertIn('KEYWORD',hit['snippet']);self.assertEqual(hit['selection']['source_sha256'],hit['text_sha256'])
        self.assertTrue(any('不是语义检索' in warning for warning in result['warnings']))
        with self.assertRaises(ValueError):
            self.service.search_local(self.pid,dict(query='KEYWORD',chapter_id=self.chapter,scopes=['materials']))
        with self.assertRaises(ValueError):
            self.service.search_local(self.pid,dict(query='KEYWORD',chapter_id=self.chapter,scopes=['body'],material_ids=[material['id']]))
        other=NovelService(SQLiteRepository(self.root/'other.sqlite3')).create(title='另一本')['document']['project']['id']
        with self.assertRaises(ValueError):
            self.service.search_local(self.pid,dict(query='KEYWORD',chapter_id=self.chapter,scopes=['materials'],material_ids=[other]))

    def test_archived_and_stale_material_cannot_enter_context(self):
        created=self.create('上下文 KEYWORD');material=created['material'];self.rebuild(material['id'])
        hit=self.service.search_local(self.pid,dict(query='KEYWORD',chapter_id=self.chapter,scopes=['materials'],material_ids=[material['id']]))['hits'][0]
        fresh=self.service.preview_context(self.pid,dict(chapter_id=self.chapter,include_search_results=True,search_selections=[hit['selection']],budget_chars=20000))
        self.assertIn('上下文 KEYWORD',fresh['context_text']);self.assertTrue(any(source['reason']=='selected_material' for source in fresh['sources']))
        self.materials.update(self.pid,material['id'],dict(operation_id=str(uuid4()),expected_revision=self.revision(),title='资料',format='txt',tags=[],text='新正文'))
        stale=self.service.preview_context(self.pid,dict(chapter_id=self.chapter,include_search_results=True,search_selections=[hit['selection']],budget_chars=20000))
        self.assertNotIn('上下文 KEYWORD',stale['context_text']);self.assertTrue(any(source['reason']=='material_index_stale' for source in stale['sources']))
        self.rebuild(material['id'])
        self.materials.archive(self.pid,material['id'],dict(operation_id=str(uuid4()),expected_revision=self.revision()))
        archived=self.service.preview_context(self.pid,dict(chapter_id=self.chapter,include_search_results=True,search_selections=[hit['selection']],budget_chars=20000))
        self.assertNotIn('新正文',archived['context_text']);self.assertTrue(any(source['reason']=='material_archived' for source in archived['sources']))

    def test_v26_backup_restore_and_copy_keep_versions_and_map_ids(self):
        created=self.create('备份 KEYWORD');material=created['material'];self.rebuild(material['id'])
        state=self.service.execute(self.pid,'add_character',dict(name='备份人物'),expected_revision=self.revision())
        FullBookPlanning(self.service).create_arc(self.pid,dict(operation_id=str(uuid4()),expected_revision=state['revision'],character_id=state['document']['characters'][0]['id'],title='备份弧光'))
        source=self.service.get(self.pid);SkillLibrary(self.db);package=self.root/'materials.nwbak'
        manifest=create_backup(self.db,package);self.assertEqual(manifest['backup_format_version'],51)
        restored=restore_backup(package,self.root/'restored');clone=NovelService(SQLiteRepository(restored['database_path'])).get(self.pid)
        self.assertEqual(clone,source);self.assertEqual(clone['material_versions'][0]['text'],'备份 KEYWORD')
        target=self.root/'copy.sqlite3';SQLiteRepository(target);SkillLibrary(target)
        copied=migrate(package,target,operation_id=str(uuid4()));mapped=NovelService(SQLiteRepository(target)).get(copied['projects'][0]['new_id'])
        self.assertEqual(len(mapped['materials']),1);self.assertNotEqual(mapped['materials'][0]['id'],material['id'])
        self.assertEqual(mapped['material_versions'][0]['text'],'备份 KEYWORD');self.assertEqual(mapped['material_versions'][0]['material_id'],mapped['materials'][0]['id'])
        self.assertEqual(mapped['material_chunks'][0]['start'],0);self.assertEqual(mapped['material_operations'][0]['request_sha256'],source['material_operations'][0]['request_sha256'])
        self.assertNotEqual(mapped['material_operations'][0]['operation_id'],source['material_operations'][0]['operation_id'])
        self.assertFalse(mapped['materials'][0]['archived'])
        self.assertEqual(index_status(mapped,mapped['materials'][0]),'current')


if __name__=='__main__':unittest.main()
