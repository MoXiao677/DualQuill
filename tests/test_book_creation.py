from contextlib import closing
from copy import deepcopy
from importlib import import_module,util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from uuid import uuid4
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository

class BookCreationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(util.find_spec('novel_writer.application.book_creation'),'persistent from-zero planning is missing')
        self.api=import_module('novel_writer.application.book_creation');self.temp=tempfile.TemporaryDirectory(prefix='novel-f1-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=self.root/'fiction.sqlite3';self.service=NovelService(SQLiteRepository(self.db));self.pid=self.service.create(title='虚构零起点')['document']['project']['id'];self.engine=self.api.BookCreation(self.service)
    def call(self,method,**fields):return getattr(self.engine,method)(self.pid,dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision'],**fields))
    def selected(self):return self.engine.describe(self.pid)['selected']
    def seed(self):
        self.call('start',name='虚构方案A')
        fields={'idea':dict(title='雾港虚构故事',creative_idea='送信人寻找失踪灯塔'),'audience':dict(genre='悬疑',readership='成年读者'),'scope':dict(target_words=60000,manuscript_language='en'),'conflict':dict(theme='信任',core_conflict='旧信和新谎言'),'world':dict(worldbuilding='虚构港城',characters=[dict(name='林舟',role='送信人'),dict(name='阿岚',role='守塔人')]),'plot':dict(main_plot='循信寻找灯塔',subplots=['重建友谊'],ending='灯塔归还港城'),'structure':dict(volumes=[dict(title='旧信',summary='追寻',chapters=[dict(title='第一封信',core_idea='遇见委托'),dict(title='暗港',core_idea='调查')]),dict(title='灯塔',summary='揭示',chapters=[dict(title='旧塔',core_idea='查证'),dict(title='归港',core_idea='选择')])])}
        for step,values in fields.items():self.call('save_step',base_version_id=self.selected()['id'],step=step,fields=values,mark='complete',next_step=step)
        return self.selected()
    def preview(self,version=None):return self.call('preview',version_id=(version or self.selected())['id'])
    def decide(self,preview,decision='accepted',**changes):
        fields=dict(preview_id=preview['preview']['id'],decision=decision,confirmed=decision=='accepted',create_entities=decision=='accepted',authorize_confirmed_metadata=False);fields.update(changes);return self.call('decide',**fields)
    def test_from_zero_seven_steps_create_two_volumes_stable_chapters_once_and_no_facts(self):
        version=self.seed();before=self.service.get(self.pid);self.assertEqual(before['document']['chapters'],[]);self.assertIsNone(before['document']['book_outline']);self.assertEqual(before['worldbuilding'],'')
        preview=self.preview();self.assertEqual(len(preview['preview']['impact']['chapter_creates']),4);self.assertEqual(preview['preview']['impact']['conflicts'],[])
        request=dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision'],preview_id=preview['preview']['id'],decision='accepted',confirmed=True,create_entities=True,authorize_confirmed_metadata=False)
        result=self.engine.decide(self.pid,request);self.assertEqual(self.engine.decide(self.pid,request),result)
        state=self.service.get(self.pid);self.assertEqual(state['workspace_version'],11);self.assertEqual(len(state['document']['book_outline']['volumes']),2);self.assertEqual(len(state['document']['chapters']),4);self.assertEqual(len(state['document']['chapter_outlines']),4);self.assertEqual(len(state['document']['characters']),2);self.assertEqual(state['document']['project']['language'],'en');self.assertTrue(all(c['content']=='' for c in state['document']['chapters']));self.assertEqual(state['memories'],[])
        ids=[c['id'] for v in version['data']['volumes'] for c in v['chapters']];self.assertEqual(ids,[c['id'] for c in state['document']['chapters']]);self.assertEqual(len(state['book_creation_decisions']),1)
        reopened=self.api.BookCreation(NovelService(SQLiteRepository(self.db))).describe(self.pid);self.assertEqual(reopened['selected']['data'],version['data'])
    def test_branch_locks_require_explicit_unlock_and_rejection_keeps_formal_plan(self):
        first=self.seed();self.decide(self.preview());formal=deepcopy(self.service.get(self.pid)['document']);lock=self.call('set_lock',version_id=first['id'],field='ending',locked=True,current_lock_id=None,confirmed=True)
        self.call('fork',version_id=first['id'],name='虚构方案B');fork=self.selected();before=self.service.get(self.pid)
        with self.assertRaises(ValueError):self.call('save_step',base_version_id=fork['id'],step='plot',fields=dict(ending='另一结局'),mark='save',next_step='plot')
        self.assertEqual(self.service.get(self.pid),before)
        with self.assertRaises(ValueError):self.call('set_lock',version_id=first['id'],field='ending',locked=False,current_lock_id=lock['id'],confirmed=False)
        with self.assertRaises(ValueError):self.service.execute(self.pid,'save_book_outline',dict(ending='绕过锁'),expected_revision=before['revision'])
        self.call('set_lock',version_id=first['id'],field='ending',locked=False,current_lock_id=lock['id'],confirmed=True)
        self.call('save_step',base_version_id=fork['id'],step='plot',fields=dict(ending='另一结局'),mark='complete',next_step='structure');second=self.selected();self.assertEqual(second['derived_from_version_id'],None)
        self.decide(self.preview(),'rejected');self.assertEqual(self.service.get(self.pid)['document'],formal)
        self.call('choose',version_id=first['id']);self.assertEqual(self.selected()['id'],first['id']);self.call('choose',version_id=second['id']);self.assertEqual(self.selected()['data']['ending'],'另一结局')
        self.assertEqual(next(v for v in self.engine.describe(self.pid)['versions'] if v['id']==first['id'])['data']['ending'],'灯塔归还港城')
    def test_source_changes_invalidate_preview_and_existing_body_versions_survive_apply(self):
        self.seed();self.decide(self.preview());state=self.service.get(self.pid);chapter=state['document']['chapters'][0]['id'];self.service.execute(self.pid,'save_chapter',dict(chapter_id=chapter,content='虚构作者正文，必须保留。'),expected_revision=state['revision'])
        self.call('save_step',base_version_id=self.selected()['id'],step='plot',fields=dict(ending='新版规划结局'),mark='save',next_step='plot');preview=self.preview();state=self.service.get(self.pid);self.service.execute(self.pid,'save_chapter',dict(chapter_id=chapter,content='虚构作者更新正文。'),expected_revision=state['revision'])
        with self.assertRaises(ValueError):self.decide(preview)
        # Changing the plot now invalidates downstream structure. Explicitly
        # review it before formal adoption; all original body assertions remain.
        self.assertIn('structure',self.engine.describe(self.pid)['stale_steps'])
        with self.assertRaises(ValueError):self.decide(self.preview())
        self.call('save_step',base_version_id=self.selected()['id'],step='structure',fields={},mark='complete',next_step='structure')
        before=self.service.get(self.pid)['document'];self.decide(self.preview());after=self.service.get(self.pid)['document'];self.assertEqual(after['chapters'][0]['content'],'虚构作者更新正文。');self.assertEqual(after['versions'][:len(before['versions'])],before['versions'])
        pending=self.preview();new=self.api.BookCreation(self.service)
        with self.assertRaises(ValueError):new.decide(self.pid,dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision'],preview_id=pending['preview']['id'],decision='accepted',confirmed=True,create_entities=True,authorize_confirmed_metadata=False))
    def test_v11_backup_copy_and_frozen_v10_read_keep_all_original_rows(self):
        from novel_writer.application.backups import create_backup,restore_backup
        from novel_writer.application.migrations import migrate
        from novel_writer.application.skill_import import SkillLibrary
        self.seed();self.call('set_lock',version_id=self.selected()['id'],field='characters',locked=True,current_lock_id=None,confirmed=True);self.decide(self.preview());SkillLibrary(self.db);package=self.root/'plan.nwbak';self.assertEqual(create_backup(self.db,package)['backup_format_version'],51);restored=restore_backup(package,self.root/'restored');clone_service=NovelService(SQLiteRepository(restored['database_path']));self.assertEqual(clone_service.get(self.pid),self.service.get(self.pid))
        target=self.root/'copy.sqlite3';SQLiteRepository(target);SkillLibrary(target);copied=migrate(package,target,operation_id=str(uuid4()));state=NovelService(SQLiteRepository(target)).get(copied['projects'][0]['new_id']);self.assertEqual(len(state['document']['chapters']),4);self.assertEqual(len(state['book_creation_versions']),8);self.assertNotEqual(state['book_creation_versions'][0]['id'],self.service.get(self.pid)['book_creation_versions'][0]['id'])
        frozen=json.loads((Path(__file__).parent/'fixtures/f1_legacy_v10.json').read_text(encoding='utf-8'));old=self.root/'old.sqlite3';old.write_bytes(bytes.fromhex(frozen['database_hex']));before=old.read_bytes();service=NovelService(SQLiteRepository(old));engine=self.api.BookCreation(service)
        for book in service.list_projects():engine.describe(book['id'])
        self.assertEqual(old.read_bytes(),before)
    def test_lock_cannot_be_bypassed_by_another_atomic_planning_entry(self):
        from novel_writer.application import book_outlines
        from novel_writer.storage.json_codec import document_from_dict,document_to_dict
        version=self.seed();self.decide(self.preview());self.call('set_lock',version_id=version['id'],field='ending',locked=True,current_lock_id=None,confirmed=True);before=self.service.get(self.pid)
        def alternate(state):
            document=document_from_dict(state['document']);book_outlines.save(document,dict(ending='另一个入口不准绕过锁'));state['document']=document_to_dict(document);return state,True
        with self.assertRaises(ValueError):self.service.repository.atomic(self.pid,alternate)
        self.assertEqual(self.service.get(self.pid),before)
    def test_skip_return_and_cancel_are_persistent_and_confirmed_metadata_needs_permission(self):
        self.call('start',name='可跳过方案');self.call('save_step',base_version_id=self.selected()['id'],step='idea',fields=dict(creative_idea='保留的未完成创意'),mark='skip',next_step='audience');version=self.selected();self.assertIn('idea',version['skipped_steps']);self.assertEqual(self.api.BookCreation(self.service).describe(self.pid)['selected']['data']['creative_idea'],'保留的未完成创意');before=self.service.get(self.pid)['document'];self.decide(self.preview(),'cancelled');self.assertEqual(self.service.get(self.pid)['document'],before)
        self.seed();self.decide(self.preview());state=self.service.get(self.pid);chapter=state['document']['chapters'][0]['id'];self.service.execute(self.pid,'save_chapter',dict(chapter_id=chapter,content='已确认的虚构正文',status='confirmed',authorize_confirmed=True),expected_revision=state['revision']);data=deepcopy(self.selected()['data']['volumes']);data[0]['chapters'][0]['title']='已确认章的新规划标题';self.call('save_step',base_version_id=self.selected()['id'],step='structure',fields=dict(volumes=data),mark='save',next_step='structure');preview=self.preview();self.assertTrue(preview['preview']['impact']['requires_confirmed_metadata'])
        with self.assertRaises(ValueError):self.decide(preview)
        self.decide(preview,authorize_confirmed_metadata=True);self.assertEqual(self.service.get(self.pid)['document']['chapters'][0]['content'],'已确认的虚构正文')

if __name__=='__main__':unittest.main()
