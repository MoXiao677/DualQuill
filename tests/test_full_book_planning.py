"""V26 全书弧光、关键事件、章节依赖、进度偏差与备份复制。"""
import tempfile,unittest
from pathlib import Path
from uuid import uuid4
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from novel_writer.application.backups import create_backup,restore_backup
from novel_writer.application.full_book_planning import FullBookPlanning
from novel_writer.application.materials import Materials
from novel_writer.application.migrations import migrate
from novel_writer.application.service import NovelService
from novel_writer.application.skill_import import SkillLibrary
from novel_writer.domain.full_book_planning import deviation_report
from novel_writer.storage.sqlite_repository import ConflictError,SQLiteRepository


class FullBookPlanningTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='novel-c07-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=self.root/'fiction.sqlite3'
        self.service=NovelService(SQLiteRepository(self.db));self.planning=FullBookPlanning(self.service)
        state=self.service.create(title='全书规划虚构测试');self.pid=state['document']['project']['id']
        state=self.service.execute(self.pid,'add_chapter',dict(title='第一章'),expected_revision=state['revision'])
        self.c1=state['document']['chapters'][0]['id']
        state=self.service.execute(self.pid,'add_chapter',dict(title='第二章'),expected_revision=state['revision'])
        self.c2=next(value['id'] for value in state['document']['chapters'] if value['id']!=self.c1)
        state=self.service.execute(self.pid,'add_chapter',dict(title='第三章'),expected_revision=state['revision'])
        self.c3=next(value['id'] for value in state['document']['chapters'] if value['id'] not in (self.c1,self.c2))
        state=self.service.execute(self.pid,'add_character',dict(name='林默'),expected_revision=state['revision'])
        self.character=state['document']['characters'][0]['id']

    def revision(self):return self.service.get(self.pid)['revision']
    def act(self,action,**payload):
        request=dict(operation_id=str(uuid4()),expected_revision=payload.pop('expected_revision',self.revision()),**payload)
        return self.planning.act(self.pid,action,request)
    def arc(self,title='觉醒',summary=''):
        return self.act('create_arc',character_id=self.character,title=title,summary=summary)['character_arcs'][-1]['id']
    def stage(self,arc,title='第一次选择',planned='__default__'):
        if planned=='__default__':planned=self.c1
        return self.act('create_stage',arc_id=arc,title=title,summary='',planned_chapter_id=planned)['character_arcs'][-1]['stages'][-1]['id']
    def event(self,title='旧钥匙出现',**values):
        return self.act('create_event',title=title,summary='',**values)['key_events'][-1]['id']
    def dependency(self,predecessor,successor,kind='setup',**values):
        return self.act('create_dependency',predecessor_chapter_id=predecessor,successor_chapter_id=successor,kind=kind,**values)['chapter_dependencies'][-1]['id']
    def confirm(self,chapter):
        return self.service.execute(self.pid,'save_chapter',dict(chapter_id=chapter,title='章节',content='正文',status='confirmed',authorize_confirmed=True),expected_revision=self.revision())
    def archive_chapter(self,chapter):
        return self.service.execute(self.pid,'archive_chapter',dict(chapter_id=chapter,confirmed=True),expected_revision=self.revision())

    def test_arcs_stages_updates_and_explicit_transitions(self):
        arc=self.arc('觉醒','从旁观到承担')
        self.act('create_stage',arc_id=arc,title='第一次选择',summary='',planned_chapter_id=self.c1)
        self.act('create_stage',arc_id=arc,title='代价',summary='',planned_chapter_id=self.c2)
        listing=self.planning.listing(self.pid)
        self.assertEqual(listing['revision'],self.revision());self.assertEqual(listing['character_arcs'][0]['stage_count'],2)
        self.assertEqual([value['ordinal'] for value in listing['character_arcs'][0]['stages']],[1,2])
        first,second=[value['id'] for value in listing['character_arcs'][0]['stages']]
        self.act('update_arc',arc_id=arc,title='觉醒 II',summary='修改后的说明')
        self.act('update_stage',stage_id=second,title='代价 II',summary='阶段说明',planned_chapter_id=self.c3)
        occurred=self.act('occur_stage',stage_id=first,occurrence_chapter_id=self.c2,body_reference='第二章第2节末段')
        stage=next(value for value in occurred['character_arc_stages'] if value['id']==first)
        self.assertEqual((stage['status'],stage['occurred_chapter_id'],stage['body_reference']),('occurred',self.c2,'第二章第2节末段'))
        with self.assertRaises(ValueError):self.act('occur_stage',stage_id=first,occurrence_chapter_id=self.c1,body_reference='重复')
        dropped=self.act('drop_stage',stage_id=second)
        stage=next(value for value in dropped['character_arc_stages'] if value['id']==second)
        self.assertEqual(stage['status'],'dropped')
        reopened=self.act('reopen_stage',stage_id=second)
        stage=next(value for value in reopened['character_arc_stages'] if value['id']==second)
        self.assertEqual((stage['status'],stage['occurred_chapter_id'],stage['body_reference']),('planned',None,''))
        self.act('occur_stage',stage_id=second,occurrence_chapter_id=self.c1,body_reference='第一章')
        reopened=self.act('reopen_stage',stage_id=second)
        stage=next(value for value in reopened['character_arc_stages'] if value['id']==second)
        self.assertEqual((stage['status'],stage['occurred_chapter_id'],stage['body_reference']),('planned',None,''))
        archived=self.act('archive_arc',arc_id=arc)
        self.assertTrue(next(value for value in archived['character_arcs'] if value['id']==arc)['archived'])
        with self.assertRaises(ValueError):self.act('create_stage',arc_id=arc,title='归档后新增',summary='',planned_chapter_id=self.c1)
        with self.assertRaises(ValueError):self.act('update_arc',arc_id=arc,title='归档后修改')
        restored=self.act('restore_arc',arc_id=arc)
        self.assertFalse(next(value for value in restored['character_arcs'] if value['id']==arc)['archived'])

    def test_events_planned_order_and_occurrence(self):
        first=self.event('事件甲')
        second=self.event('事件乙')
        third=self.event('事件丙',planned_order=5)
        listing=self.planning.listing(self.pid)
        self.assertEqual([value['planned_order'] for value in listing['key_events']],[1,2,5])
        self.assertEqual([value['id'] for value in listing['key_events']],[first,second,third])
        arc=self.arc()
        self.act('update_event',event_id=first,title='事件甲改',summary='说明',character_id=self.character,arc_id=arc,planned_chapter_id=self.c2,planned_order=3)
        occurred=self.act('occur_event',event_id=second,occurrence_chapter_id=self.c1,body_reference='第一章开头')
        event=next(value for value in occurred['key_events'] if value['id']==second)
        self.assertEqual((event['status'],event['occurred_chapter_id'],event['body_reference']),('occurred',self.c1,'第一章开头'))
        dropped=self.act('drop_event',event_id=third)
        self.assertEqual(next(value for value in dropped['key_events'] if value['id']==third)['status'],'dropped')
        reopened=self.act('reopen_event',event_id=second)
        event=next(value for value in reopened['key_events'] if value['id']==second)
        self.assertEqual((event['status'],event['occurred_chapter_id'],event['body_reference']),('planned',None,''))
        listing=self.planning.listing(self.pid)
        self.assertEqual(next(value for value in listing['key_events'] if value['id']==first)['planned_order'],3)

    def test_chapter_confirmation_never_occurs_and_reports_all_reasons(self):
        arc=self.arc()
        missing=self.stage(arc,'应发生但未记录',self.c1)
        late=self.stage(arc,'晚发生',self.c1)
        early=self.stage(arc,'早发生',self.c3)
        unplanned=self.stage(arc,'无计划',None)
        event=self.event('应发生事件',planned_chapter_id=self.c1,character_id=self.character,arc_id=arc)
        self.confirm(self.c1)
        listing=self.planning.listing(self.pid)
        self.assertEqual(next(value for value in listing['character_arc_stages'] if value['id']==missing)['status'],'planned')
        self.assertEqual(next(value for value in listing['key_events'] if value['id']==event)['status'],'planned')
        reasons=listing['deviation']['deviations_by_reason']
        self.assertGreaterEqual(reasons['missing'],2)
        self.act('occur_stage',stage_id=late,occurrence_chapter_id=self.c3,body_reference='第三章')
        self.act('occur_stage',stage_id=early,occurrence_chapter_id=self.c1,body_reference='第一章')
        self.act('occur_stage',stage_id=unplanned,occurrence_chapter_id=self.c2,body_reference='第二章')
        listing=self.planning.listing(self.pid)
        reasons=listing['deviation']['deviations_by_reason']
        self.assertEqual((reasons['late'],reasons['early'],reasons['unplanned']),(1,1,1))
        self.assertEqual(reasons['missing'],2)
        positions={value['entity_id']:value for value in listing['deviation']['positions']}
        self.assertEqual((positions[late]['planned_chapter_number'],positions[late]['actual_chapter_number']),(1,3))
        self.assertEqual((positions[early]['planned_chapter_number'],positions[early]['actual_chapter_number']),(3,1))
        self.assertIsNone(positions[unplanned]['planned_chapter_number'])
        self.assertEqual(listing['deviation']['latest_confirmed_chapter_number'],1)

    def test_archived_and_missing_references_are_reported(self):
        arc=self.arc()
        stage=self.stage(arc,'归档阻塞',self.c2)
        dependency=self.dependency(self.c1,self.c2)
        self.archive_chapter(self.c2)
        listing=self.planning.listing(self.pid)
        states={value['entity_id']:value['state'] for value in listing['deviation']['references']}
        self.assertEqual(states[stage],'archived');self.assertEqual(states[dependency],'archived')
        blocked={value['entity_id'] for value in listing['deviation']['deviations'] if value['reason']=='blocked'}
        self.assertIn(stage,blocked);self.assertIn(dependency,blocked)
        broken=self.service.get(self.pid)
        broken['character_arc_stages'][0]['planned_chapter_id']=str(uuid4())
        missing={value['entity_id']:value['state'] for value in deviation_report(broken)['references']}
        self.assertEqual(missing[stage],'missing')

    def test_dependency_validation_lifecycle_and_early_confirmation(self):
        dependency=self.dependency(self.c1,self.c2,'setup',note='先埋后收')
        with self.assertRaises(ValueError):self.dependency(self.c1,self.c2,'setup')
        with self.assertRaises(ValueError):self.dependency(self.c1,self.c1,'setup')
        with self.assertRaises(KeyError):self.dependency(str(uuid4()),self.c2,'setup')
        other=NovelService(SQLiteRepository(self.root/'other.sqlite3')).create(title='另一本')
        foreign=other['document']['chapters'][0]['id'] if other['document']['chapters'] else str(uuid4())
        with self.assertRaises(KeyError):self.dependency(foreign,self.c2,'setup')
        disabled=self.act('set_dependency_enabled',dependency_id=dependency,enabled=False)
        self.assertEqual(disabled['deviation']['dependency_counts']['disabled'],1)
        self.confirm(self.c2)
        listing=self.planning.listing(self.pid)
        self.assertFalse(any(value['entity_id']==dependency and value['reason']=='blocked' for value in listing['deviation']['deviations']))
        self.act('set_dependency_enabled',dependency_id=dependency,enabled=True)
        listing=self.planning.listing(self.pid)
        self.assertTrue(any(value['entity_id']==dependency and value['reason']=='blocked' for value in listing['deviation']['deviations']))
        archived=self.act('archive_dependency',dependency_id=dependency)
        self.assertTrue(next(value for value in archived['chapter_dependencies'] if value['id']==dependency)['archived'])
        self.assertEqual(archived['deviation']['dependency_counts']['archived'],1)
        restored=self.act('restore_dependency',dependency_id=dependency)
        self.assertFalse(next(value for value in restored['chapter_dependencies'] if value['id']==dependency)['archived'])

    def test_idempotency_conflicts_and_archived_chapter_rejection(self):
        operation=str(uuid4());request=dict(operation_id=operation,expected_revision=self.revision(),character_id=self.character,title='幂等弧光')
        first=self.planning.create_arc(self.pid,request);second=self.planning.create_arc(self.pid,request)
        self.assertEqual(first,second);self.assertEqual(len(self.service.get(self.pid)['character_arcs']),1)
        with self.assertRaises(ValueError):self.planning.create_arc(self.pid,dict(request,title='不同请求'))
        with self.assertRaises(ConflictError):self.planning.create_arc(self.pid,dict(operation_id=str(uuid4()),expected_revision=1,character_id=self.character,title='旧保存编号'))
        other=self.service.create(title='第二本')
        other_id=other['document']['project']['id']
        other_state=self.service.execute(other_id,'add_character',dict(name='甲'),expected_revision=other['revision'])
        other_character=other_state['document']['characters'][0]['id']
        with self.assertRaises(ConflictError):self.planning.create_arc(other_id,dict(operation_id=operation,expected_revision=other_state['revision'],character_id=other_character,title='跨书身份'))
        self.archive_chapter(self.c1)
        with self.assertRaises(ValueError):self.act('create_stage',arc_id=self.service.get(self.pid)['character_arcs'][0]['id'],title='归档章节',summary='',planned_chapter_id=self.c1)
        with self.assertRaises(KeyError):self.planning.act(self.pid,'unknown_action',dict(operation_id=str(uuid4()),expected_revision=self.revision()))

    def test_v25_upgrade_preserves_materials_and_v26_backup_copy(self):
        created=Materials(self.service).create(self.pid,dict(operation_id=str(uuid4()),expected_revision=self.revision(),title='资料',format='txt',tags=[],text='原文 KEYWORD'))
        before=self.service.get(self.pid);self.assertEqual(before['workspace_version'],25)
        listing=self.planning.listing(self.pid);self.assertEqual(listing['ai_completion']['status'],'unavailable')
        arc=self.arc('备份弧光');self.assertEqual(self.service.get(self.pid)['workspace_version'],26)
        for name in ('materials','material_versions','material_chunks','material_operations'):
            self.assertEqual(self.service.get(self.pid)[name],before[name])
        stage=self.stage(arc,'备份阶段',self.c1)
        self.act('occur_stage',stage_id=stage,occurrence_chapter_id=self.c1,body_reference='备份正文引用')
        source=self.service.get(self.pid);SkillLibrary(self.db)
        package=self.root/'v26.nwbak';manifest=create_backup(self.db,package)
        self.assertEqual(manifest['backup_format_version'],51);self.assertEqual(manifest['database']['workspace_version'],26)
        restored=restore_backup(package,self.root/'restored')
        clone=NovelService(SQLiteRepository(restored['database_path'])).get(self.pid)
        self.assertEqual(clone,source);self.assertEqual(clone['character_arc_stages'][0]['body_reference'],'备份正文引用')
        target=self.root/'copy.sqlite3';SQLiteRepository(target);SkillLibrary(target)
        copied=migrate(package,target,operation_id=str(uuid4()));mapped=NovelService(SQLiteRepository(target)).get(copied['projects'][0]['new_id'])
        self.assertEqual((len(mapped['character_arcs']),len(mapped['character_arc_stages'])),(1,1))
        self.assertNotEqual(mapped['character_arcs'][0]['id'],source['character_arcs'][0]['id'])
        self.assertEqual(mapped['character_arc_stages'][0]['arc_id'],mapped['character_arcs'][0]['id'])
        self.assertEqual(mapped['character_arc_stages'][0]['planned_chapter_id'],next(value['id'] for value in mapped['document']['chapters'] if value['number']==1))
        self.assertEqual(len(mapped['full_book_planning_operations']),len(source['full_book_planning_operations']))
        for old,new in zip(source['full_book_planning_operations'],mapped['full_book_planning_operations']):
            self.assertEqual(old['request_sha256'],new['request_sha256']);self.assertNotEqual(old['operation_id'],new['operation_id'])
        self.assertEqual(mapped['workspace_version'],26)


if __name__=='__main__':unittest.main()
