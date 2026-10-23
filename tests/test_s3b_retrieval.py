"""字面检索与上下文二次校验的独立期望。"""
import json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository
from novel_writer.storage.skills_repository import SkillsRepository
FROZEN=json.loads((ROOT/'tests/fixtures/s3b_legacy_v1.json').read_text(encoding='utf8'))

class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='novel-s3b-search-');self.addCleanup(self.temp.cleanup)
        self.db=Path(self.temp.name)/'fictional.sqlite3';self.db.write_bytes(bytes.fromhex(FROZEN['database_hex']))
        self.service=NovelService(SQLiteRepository(self.db));self.state=self.service.get('p1')
    def search(self,query,**options):
        self.assertTrue(callable(getattr(self.service,'search_local',None)),'缺少真实字面检索入口')
        return self.service.search_local('p1',dict(query=query,chapter_id='p1-c5',**options))
    def save(self,action,**fields):
        self.state=self.service.execute('p1',action,fields,expected_revision=self.state['revision'])
    def memory(self,text,**options):
        fields=dict(kind='event',title='人工记忆',text=text,position_chapter_id='p1-c5',confirmed=True,
            source={'kind':'chapter','entity_id':'p1-c5'});fields.update(options);self.save('save_memory',**fields)
        return self.state['memories'][-1]
    def test_literal_hits_no_hits_story_position_and_book_isolation(self):
        result=self.search('BODY_p1',scopes=['body'])
        self.assertEqual([r['locator']['chapter_id'] for r in result['hits']],['p1-c1','p1-c2','p1-c3','p1-c4','p1-c5'])
        self.assertEqual(self.search('无此字面文本')['hits'],[])
        self.assertEqual(self.search('FUTURE_CHAPTER_20',scopes=['body'])['hits'],[])
        self.assertEqual(len(self.search('FUTURE_CHAPTER_20',scopes=['body'],whole_book=True)['hits']),1)
        self.assertEqual(self.search('BODY_p2',scopes=['body'],whole_book=True)['hits'],[])
        self.assertEqual(result,self.search('BODY_p1',scopes=['body']))
    def test_unlocated_and_global_skills_require_explicit_scope_and_selection(self):
        self.assertEqual(self.search('FUTURE_WORLD')['hits'],[])
        self.assertEqual(len(self.search('FUTURE_WORLD',scopes=['worldbuilding'])['hits']),1)
        repo=SkillsRepository(self.db);repo.add(dict(id='global-skill',name='全局技能',description='仅本测试',imported_at='2020-01-01T00:00:00+00:00',
            primary_path='SKILL.md',files=[dict(path='SKILL.md',content='全局资料 KEYWORD_SKILL')]))
        self.assertEqual(self.search('KEYWORD_SKILL')['hits'],[])
        with self.assertRaises(ValueError):self.search('KEYWORD_SKILL',scopes=['skills'])
        result=self.search('KEYWORD_SKILL',scopes=['skills'],skill_ids=['global-skill'])
        hit=result['hits'][0];self.assertEqual(hit['selection']['scope'],'global');self.assertEqual(len(hit['selection']['source_sha256']),64)
        self.assertEqual(hit['locator']['view'],'skills')
    def test_confirmed_memory_filter_freshness_archive_position_and_budget(self):
        good=self.memory('MEMORY_ALLOWED '*80)
        self.memory('UNCONFIRMED',confirmed=False);self.memory('FUTURE_MEMORY',position_chapter_id='p1-c20')
        result=self.service.preview_context('p1',dict(chapter_id='p1-c5',include_memories=True,budget_chars=128))
        self.assertEqual(len(result['context_text']),128);self.assertIn('MEMORY_ALLOWED',result['context_text'])
        for marker in ('UNCONFIRMED','FUTURE_MEMORY'):self.assertNotIn(marker,json.dumps(result))
        self.save('save_chapter',chapter_id='p1-c5',content='来源已变化')
        stale=self.service.preview_context('p1',dict(chapter_id='p1-c5',include_memories=True))
        self.assertNotIn('MEMORY_ALLOWED',stale['context_text']);self.assertTrue(any(s['reason']=='memory_outdated' for s in stale['sources']))
        self.save('review_memory',memory_id=good['id'],confirmed=True);self.save('archive_memory',memory_id=good['id'])
        archived=self.service.preview_context('p1',dict(chapter_id='p1-c5',include_memories=True))
        self.assertNotIn('MEMORY_ALLOWED',archived['context_text'])
    def test_search_selection_is_reloaded_and_cannot_reuse_future_crossbook_or_stale(self):
        selected=self.search('BODY_p1_4',scopes=['body'])['hits'][0]['selection']
        fresh=self.service.preview_context('p1',dict(chapter_id='p1-c5',include_search_results=True,search_selections=[selected]))
        self.assertTrue(any(s['kind']=='search_result' and s['included'] for s in fresh['sources']))
        self.save('save_chapter',chapter_id='p1-c4',content='NEW_PRIVATE_BODY')
        stale=self.service.preview_context('p1',dict(chapter_id='p1-c5',include_search_results=True,search_selections=[selected]))
        self.assertTrue(any(s['reason']=='stale_search' for s in stale['sources']))
        self.assertFalse(any(s['kind']=='search_result' and s['included'] for s in stale['sources']))
        future=self.search('FUTURE_CHAPTER_20',scopes=['body'],whole_book=True)['hits'][0]['selection']
        result=self.service.preview_context('p1',dict(chapter_id='p1-c5',include_search_results=True,search_selections=[future]))
        self.assertNotIn('FUTURE_CHAPTER_20',json.dumps(result))
        bad=dict(selected,project_id='p2')
        with self.assertRaises(ValueError):self.service.preview_context('p1',dict(chapter_id='p1-c5',include_search_results=True,search_selections=[bad]))
    def test_search_memory_is_not_automatically_a_confirmed_fact(self):
        self.memory('未确认的检索记录',confirmed=False)
        hit=self.search('未确认的检索记录',scopes=['memories'])['hits'][0]
        self.assertFalse(hit['confirmed'])
        result=self.service.preview_context('p1',dict(chapter_id='p1-c5',include_search_results=True,search_selections=[hit['selection']]))
        self.assertNotIn('未确认的检索记录',result['context_text'])

    def test_future_source_cannot_be_hidden_by_earlier_declared_memory_position(self):
        self.save('save_chapter_outline',chapter_id='p1-c20',objective='未来章计划')
        outline=next(o for o in self.state['document']['chapter_outlines'] if o['chapter_id']=='p1-c20')
        for kind,identifier in (('chapter','p1-c20'),('chapter_outline',outline['id']),('idea','p1-c20')):
            with self.subTest(kind=kind):
                memory=self.memory('FUTURE_SOURCE_FACT_'+kind,position_chapter_id='p1-c1',source={'kind':kind,'entity_id':identifier})
                direct=self.service.preview_context('p1',dict(chapter_id='p1-c5',include_memories=True,memory_ids=[memory['id']]))
                self.assertNotIn('FUTURE_SOURCE_FACT',json.dumps(direct))
                self.assertEqual(self.search('FUTURE_SOURCE_FACT_'+kind,scopes=['memories'])['hits'],[])
                selected=self.search('FUTURE_SOURCE_FACT_'+kind,scopes=['memories'],whole_book=True)['hits'][0]['selection']
                result=self.service.preview_context('p1',dict(chapter_id='p1-c5',include_search_results=True,search_selections=[selected]))
                self.assertNotIn('FUTURE_SOURCE_FACT',json.dumps(result))

if __name__=='__main__':unittest.main()
