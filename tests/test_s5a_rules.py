"""可解释离线规则的独立正反例，非语义模型。"""
from importlib import util,import_module
import json,sys,tempfile,threading,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository
from novel_writer.application.task_protocol import CancellationToken
FROZEN=json.loads((ROOT/'tests/fixtures/s5a_legacy.json').read_text(encoding='utf8'))

def request_rules(**changes):
    rules=dict(version='offline-audit-1',forbidden_literals=['禁用词'],required_literals=[],normalization='whitespace',near_threshold=.85,minimum_fragment_chars=12,check_timeline=True)
    rules.update(changes)
    return dict(instruction='离线规则验收',max_output_chars=10000,timeout_ms=5000,rules=rules,selected_chapter_ids=['p1-c5','p1-c6'],previous_report_id=None)

class OfflineRuleTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(util.find_spec('novel_writer.application.review_rules'),'缺少真实离线审核规则')
        self.mod=import_module('novel_writer.application.review_rules');self.temp=tempfile.TemporaryDirectory(prefix='novel-s5a-rules-');self.addCleanup(self.temp.cleanup)
        self.db=Path(self.temp.name)/'fictional.sqlite3';self.db.write_bytes(bytes.fromhex(FROZEN['v3']['database_hex']));self.service=NovelService(SQLiteRepository(self.db))
    def save(self,action,**values):
        s=self.service.get('p1');self.service.execute('p1',action,values,expected_revision=s['revision'])
    def analyze(self,**changes):
        state=self.service.get('p1');parameters=self.mod.prepare_parameters(state,request_rules(**changes))
        return parameters,self.mod.analyze(parameters,CancellationToken(threading.Event(),time.monotonic()+5))
    def test_literal_rules_and_normal_control_keep_exact_original_evidence(self):
        self.save('save_chapter',chapter_id='p1-c5',content='\n作者写下禁用词，作为明确规则反例。  ')
        p,result=self.analyze(required_literals=['必须出现'])
        self.assertTrue(any(i.rule_id=='forbidden_literal' for i in result.issues));self.assertTrue(any(i.rule_id=='missing_literal' for i in result.issues))
        evidence=next(i.evidence[0] for i in result.issues if i.rule_id=='forbidden_literal')
        source=next(s for s in p.sources if s.entity_id==evidence.entity_id and s.kind==evidence.source_kind)
        self.assertEqual(source.text[evidence.start:evidence.end],evidence.quote);self.assertEqual(evidence.quote,'禁用词')
        self.save('save_chapter',chapter_id='p1-c5',content='合法文本，必须出现。')
        _,normal=self.analyze(required_literals=['必须出现'])
        self.assertFalse(any(i.rule_id in ('forbidden_literal','missing_literal') and i.evidence[0].entity_id=='p1-c5' for i in normal.issues))
    def test_exact_and_basic_near_comparison_has_two_sides_threshold_and_no_match(self):
        a='灯塔照亮港口的潮水，船员静静等待远方来信。'
        self.save('save_chapter',chapter_id='p1-c5',content=a+'\n\n远方山谷传来互不相干的回声。')
        self.save('save_chapter',chapter_id='p1-c6',content=a)
        _,exact=self.analyze();hit=next(i for i in exact.issues if i.rule_id=='duplicate_exact')
        self.assertEqual({e.entity_id for e in hit.evidence},{'p1-c5','p1-c6'});self.assertEqual(len(hit.evidence),2)
        self.save('save_chapter',chapter_id='p1-c6',content='灯塔照亮港口的潮水，船员默默等待远方来信。')
        _,near=self.analyze();self.assertTrue(any(i.rule_id=='duplicate_near' and i.score>=.85 for i in near.issues))
        self.save('save_chapter',chapter_id='p1-c6',content='完全不同主题的量子计算研究说明。')
        _,normal=self.analyze();self.assertFalse(any(i.rule_id.startswith('duplicate_') for i in normal.issues))
    def test_explicit_timeline_conflict_and_excerpt_proposals_do_not_invent_facts(self):
        state=self.service.get('p1');scenes=state['document']['chapter_outlines'][0]['scenes'];scenes[0]['story_time']='第3天';scenes[1]['story_time']='第1天'
        self.save('save_chapter_outline',chapter_id='p1-c5',scenes=scenes)
        parameters,result=self.analyze();issue=next(i for i in result.issues if i.rule_id=='timeline_order');self.assertEqual(len(issue.evidence),2)
        for proposal in result.proposals:
            source=next(s for s in parameters.sources if s.kind==proposal.evidence.source_kind and s.entity_id==proposal.evidence.entity_id)
            self.assertEqual(proposal.text,source.text[proposal.evidence.start:proposal.evidence.end])
        scenes[0]['story_time']='第1天';scenes[1]['story_time']='第3天';self.save('save_chapter_outline',chapter_id='p1-c5',scenes=scenes)
        _,normal=self.analyze();self.assertFalse(any(i.rule_id=='timeline_order' for i in normal.issues))

    def test_repeated_time_is_located_to_exact_scene_and_planning_never_becomes_fact_proposal(self):
        state=self.service.get('p1');scenes=state['document']['chapter_outlines'][0]['scenes'];scenes[0]['story_time']='第3天';scenes[1]['story_time']='第1天'
        self.save('save_chapter_outline',chapter_id='p1-c5',story_time='第3天',core_idea='另处引用剧情时间：第1天',scenes=scenes)
        parameters,result=self.analyze();issue=next(i for i in result.issues if i.rule_id=='timeline_order');source=next(s for s in parameters.sources if s.kind=='chapter_outline')
        with self.subTest(contract='exact_field_location'):
            self.assertGreater(issue.evidence[0].start,source.text.index('场景1'))
            self.assertGreater(issue.evidence[1].start,source.text.index('场景2'))
        with self.subTest(contract='plans_not_facts'):self.assertTrue(all(p.kind=='chapter_summary' and p.evidence.source_kind=='chapter' for p in result.proposals))

if __name__=='__main__':unittest.main()
