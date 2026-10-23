"""S3首批独立期望：保存/引用/历史/保真与只读预算预览。"""
from contextlib import closing
from copy import deepcopy
from importlib import util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'tests/fixtures'))
from s3_planning import create_planning_database
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository,ConflictError

class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='novel-s3-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.path=self.root/'fictional.sqlite3';create_planning_database(self.path)
        self.service=NovelService(SQLiteRepository(self.path));self.state=self.service.get('p1')
    def save(self,action,**fields):
        self.state=self.service.execute('p1',action,fields,expected_revision=self.state['revision']);return self.state
    def preview(self,**options):
        self.assertTrue(callable(getattr(self.service,'preview_context',None)),'缺少真实只读上下文入口')
        return self.service.preview_context('p1',dict(chapter_id='p1-c5',**options))
    def test_volume_assignments_and_unshown_fields_survive_partial_save(self):
        original=self.state['document']['book_outline'];volumes=deepcopy(original['volumes'])
        volumes[0]['title']='改卷名';volumes[0]['chapter_ids'].remove('p1-c10');volumes[1]['chapter_ids'].append('p1-c10')
        self.save('save_book_outline',volumes=volumes)
        self.save('save_book_outline',theme='只改主题')
        current=NovelService(SQLiteRepository(self.path)).get('p1')['document']['book_outline']
        self.assertEqual(current['volumes'],volumes);self.assertEqual(current['key_events'],original['key_events'])
        self.assertEqual(current['ending'],original['ending']);self.assertEqual(current['id'],original['id'])
        self.assertEqual([c['number'] for c in self.state['document']['chapters']],list(range(1,21)))
        self.assertEqual(len(self.state['document']['versions']),2)
    def test_scene_goals_relationships_survive_reopen_and_text_only_save(self):
        detail=self.state['document']['chapter_outlines'][0];scenes=deepcopy(detail['scenes'])
        scenes[0].update(summary='调查信封的目的',order=3,character_ids=['p1-char1','p1-char3'])
        self.save('save_chapter_outline',chapter_id='p1-c5',scenes=scenes,character_ids=['p1-char3'])
        self.save('save_chapter_outline',chapter_id='p1-c5',objective='仅改章节目标')
        relations=[dict(target_character_id='p1-char3',relation='盟友',description='\n原文  \n')]
        self.save('save_character',character_id='p1-char1',goals=['调查','\n保留空格  '],relationships=relations)
        self.save('save_character',character_id='p1-char1',name='人物改名')
        current=NovelService(SQLiteRepository(self.path)).get('p1')
        self.assertEqual(current['document']['chapter_outlines'][0]['scenes'],scenes)
        self.assertEqual(current['document']['chapter_outlines'][0]['character_ids'],['p1-char3'])
        char=current['document']['characters'][0];self.assertEqual(char['goals'],['调查','\n保留空格  ']);self.assertEqual(char['relationships'],relations)
        self.assertEqual(current['document']['versions'][:2],self.state['document']['versions'][:2])
    def test_invalid_and_cross_book_references_and_types_leave_all_rows_unchanged(self):
        for action,fields in [
            ('save_book_outline',{'volumes':[dict(number=1,title='卷',summary='',chapter_ids=['p2-c1'])]}),
            ('save_book_outline',{'volumes':[dict(number=1,title='卷',summary='',chapter_ids=['missing'])]}),
            ('save_book_outline',{'volumes':[dict(number=True,title='卷',summary='',chapter_ids=[])]}),
            ('save_chapter_outline',{'chapter_id':'p1-c5','scenes':[dict(order=1,summary='场景',character_ids=['p2-char1'],location='',story_time='')]}),
            ('save_character',{'character_id':'p1-char1','relationships':[dict(target_character_id='p2-char1',relation='错书',description='')]}),
            ('save_character',{'character_id':'p1-char1','goals':'不是列表'})]:
            with self.subTest(action=action,fields=fields):
                before=self.path.read_bytes()
                with self.assertRaises(ValueError):self.save(action,**fields)
                self.assertEqual(self.path.read_bytes(),before)
    def test_planning_stale_revision_cannot_overwrite_and_history_is_prefix(self):
        prior=self.state['document']['versions'];old=self.state['revision']
        self.save('save_character',character_id='p1-char1',goals=['新目标'])
        with self.assertRaises(ConflictError):self.service.execute('p1','save_book_outline',{'volumes':[]},expected_revision=old)
        self.assertEqual(self.service.get('p1'),self.state);self.assertEqual(self.state['document']['versions'][:-1],prior)
    def test_plans_roundtrip_existing_backup_restore_and_migration(self):
        from novel_writer.application.backups import create_backup,restore_backup
        from novel_writer.application.migrations import migrate
        self.save('save_character',character_id='p1-char1',goals=['新增目标'])
        package=self.root/'plan.nwbak';create_backup(self.path,package)
        restored=Path(restore_backup(package,self.root/'restored')['database_path'])
        self.assertEqual(NovelService(SQLiteRepository(restored)).get('p1'),self.state)
        target=self.root/'target.sqlite3';create_planning_database(target)
        result=migrate(package,target,operation_id=str(uuid4()))
        new_id=next(p['new_id'] for p in result['projects'] if p['old_id']=='p1')
        copy=NovelService(SQLiteRepository(target)).get(new_id)
        self.assertEqual(copy['document']['book_outline']['volumes'][0]['title'],'卷1')
        self.assertEqual(copy['document']['characters'][0]['goals'],['新增目标'])
        self.assertNotEqual(copy['document']['chapters'][0]['id'],'p1-c1')
    def test_default_preview_is_readonly_saved_past_only_and_no_unlocated_spoilers(self):
        before=self.path.read_bytes();result=self.preview()
        self.assertEqual(result['revision'],1);self.assertEqual(self.path.read_bytes(),before)
        body=result['context_text'];self.assertIn('BODY_p1_4',body);self.assertNotIn('BODY_p1_5',body)
        for marker in ('BODY_p2','FUTURE_','PRIVATE_METADATA'):self.assertNotIn(marker,json.dumps(result,ensure_ascii=False))
        # C13 deliberately makes effective rules mandatory, including legacy book guidance.
        self.assertIn('私人规则',body)
        self.assertTrue(any(s['kind']=='rule' and s['reason']=='resolved_rule' for s in result['sources']))
        self.assertTrue(any(s['reason']=='future_chapter' for s in result['sources']))
        self.assertTrue(all(s['revision']==1 for s in result['sources']))
        self.assertFalse(result['model_request_sent'])
    def test_current_plan_and_unlocated_sources_require_separate_explicit_options(self):
        plain=self.preview();self.assertNotIn('本章场景一',plain['context_text'])
        selected=self.preview(include_current_plan=True,include_characters=True,character_ids=['p1-char1'],
            include_book_outline=True,include_worldbuilding=True,scope='through_current')
        body=selected['context_text'];self.assertIn('本章场景一',body);self.assertIn('FUTURE_ENDING',body)
        self.assertIn('FUTURE_CHARACTER',body);self.assertIn('FUTURE_WORLD',body);self.assertIn('BODY_p1_5',body)
        self.assertNotIn('FUTURE_CHAPTER_20',json.dumps(selected,ensure_ascii=False))
        self.assertTrue(selected['warnings']);self.assertTrue(any(s['kind']=='chapter_plan' and s['included'] for s in selected['sources']))
    def test_budget_truncation_sources_and_versions_are_explainable(self):
        self.save('save_chapter',chapter_id='p1-c4',content='A🙂'*300)
        result=self.preview(budget_chars=128)
        self.assertEqual(len(result['context_text']),128);self.assertEqual(result['used_chars'],128)
        self.assertEqual(sum(s['included_chars'] for s in result['sources']),128)
        self.assertTrue(any(s['truncated'] for s in result['sources']))
        source=next(s for s in result['sources'] if s['kind']=='chapter_body' and s['entity_id']=='p1-c4')
        self.assertEqual(source['version_id'],self.state['document']['chapters'][3]['current_version_id'])
        self.assertIn('字符',result['budget_unit']);self.assertNotIn('token_count',result)
    def test_preview_rejects_crossbook_unknown_options_and_invalid_budget(self):
        self.assertTrue(callable(getattr(self.service,'preview_context',None)))
        before=self.path.read_bytes()
        for options in ({'chapter_id':'p2-c1'},{'chapter_id':'missing'},{'budget_chars':True},{'budget_chars':0},
                        {'scope':'all_future'},{'include_characters':True,'character_ids':['p2-char1']},{'api_key':'fake'}):
            with self.subTest(options=options),self.assertRaises(ValueError):
                self.service.preview_context('p1',dict(chapter_id='p1-c5',**{k:v for k,v in options.items() if k!='chapter_id'}) if 'chapter_id' not in options else options)
        self.assertEqual(self.path.read_bytes(),before)

    def test_workspace_sources_and_idea_only_do_not_borrow_unrelated_entity_versions(self):
        self.save('save_project',title='新版项目资料')
        self.save('save_chapter',chapter_id='p1-c6',content='第六章已保存正文')
        result=self.service.preview_context('p1',dict(chapter_id='p1-c6',include_current_plan=True,
            include_worldbuilding=True,include_writing_rules=True))
        for source in result['sources']:
            if source['kind'] in ('worldbuilding','writing_rules','chapter_plan'):
                self.assertIsNone(source['version_id'])
                self.assertEqual(source['revision'],self.state['revision'])

if __name__=='__main__':unittest.main()
