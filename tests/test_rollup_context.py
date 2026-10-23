"""Saved deterministic rollup context, frozen legacy bytes and V32 copies."""
from copy import deepcopy
from uuid import uuid4
import json,unittest
import test_s3b_rollups as fixture
from novel_writer.application.tasks import TaskCoordinator,context_options
from novel_writer.application.task_protocol import AdapterRegistry
from novel_writer.domain.tasks import encode,parse,FrozenInput,Dependency,digest,capture_dependency,dependency_equal
from novel_writer.storage.sqlite_repository import SQLiteRepository,validate_workspace
from novel_writer.application.service import NovelService


class RollupContextTests(unittest.TestCase):
    setUp=fixture.MemoryRollupTests.setUp
    save=fixture.MemoryRollupTests.save
    memory=fixture.MemoryRollupTests.memory

    def rollup(self,scope='book',chapter='p1-c2',volume=None):
        result=self.service.save_memory_rollup('p1',dict(scope=scope,scope_volume_number=volume,through_chapter_id=chapter,operation_id=str(uuid4()),expected_revision=self.service.get('p1')['revision']))
        self.state=self.service.get('p1');return result['rollup']

    def report(self,chapter='p1-c3',**changes):
        return self.service.preview_context('p1',dict(chapter_id=chapter,include_memory_rollups=True,budget_chars=20000,**changes))

    def prepare(self,options):
        engine=TaskCoordinator(self.service,AdapterRegistry());self.addCleanup(engine.close)
        report=self.service.preview_context('p1',options)
        return engine.prepare('p1',dict(request_id=str(uuid4()),chapter_id=options['chapter_id'],task_type='rewrite_chapter',context_options=options,context_sha256=digest(report['context_text']),parameters=dict(instruction='虚构改写',max_output_chars=1000,timeout_ms=1000),expected_revision=report['revision']))['task']

    def test_default_zero_write_and_old_frozen_encoding_exact(self):
        self.memory('前章','ROLLUP_UNIQUE','p1-c1');self.rollup()
        before=self.db.read_bytes();report=self.service.preview_context('p1',dict(chapter_id='p1-c3'))
        self.assertNotIn('ROLLUP_UNIQUE',report['context_text']);self.assertFalse(any(s['kind']=='memory_rollup' for s in report['sources']));self.assertEqual(self.db.read_bytes(),before)
        options=context_options(dict(chapter_id='p1-c3'));self.assertNotIn('include_memory_rollups',encode(options));self.assertEqual(encode(options),encode(context_options(dict(chapter_id='p1-c3',include_memory_rollups=False))))
        task=self.prepare(dict(chapter_id='p1-c3'));old=deepcopy(task['frozen']);self.assertNotIn('include_memory_rollups',old['context_options'])
        self.assertEqual(encode(FrozenInput.from_dict(old)),old);raw=self.db.read_bytes();state=NovelService(SQLiteRepository(self.db)).get('p1');self.assertEqual(state['generation_tasks'][-1]['frozen'],old);self.assertEqual(self.db.read_bytes(),raw);self.assertLess(state['workspace_version'],32)

    def test_previous_through_current_and_no_future_prose_in_report(self):
        self.memory('前章','PAST_ONLY','p1-c1');self.memory('当前','CURRENT_SECRET','p1-c3');self.memory('未来','FUTURE_SECRET','p1-c4')
        past=self.rollup(chapter='p1-c2');current=self.rollup(scope='chapter',chapter='p1-c3');future=self.rollup(scope='chapter',chapter='p1-c4')
        before=self.db.read_bytes();report=self.report(include_memories=True);self.assertEqual(self.db.read_bytes(),before)
        self.assertIn('PAST_ONLY',report['context_text']);self.assertNotIn('CURRENT_SECRET',report['context_text']);self.assertNotIn('FUTURE_SECRET',json.dumps(report,ensure_ascii=False))
        reasons={s['entity_id']:s['reason'] for s in report['sources'] if s['kind']=='memory_rollup'};self.assertEqual(reasons[current['id']],'rollup_current');self.assertEqual(reasons[future['id']],'rollup_future')
        through=self.report(scope='through_current');self.assertIn('CURRENT_SECRET',through['context_text']);self.assertNotIn('FUTURE_SECRET',json.dumps(through,ensure_ascii=False))

    def test_latest_available_volume_and_duplicate_sources_once(self):
        first=self.memory('唯一甲','UNIQUE_ONE','p1-c1');second=self.memory('唯一乙','UNIQUE_TWO','p1-c2')
        older=self.rollup(chapter='p1-c1');newer=self.rollup(chapter='p1-c2');self.rollup(scope='volume',chapter='p1-c2',volume=1);self.rollup(scope='chapter',chapter='p1-c1');other=self.rollup(scope='volume',chapter='p1-c11',volume=2)
        report=self.report(include_memories=True);self.assertEqual(report['context_text'].count('UNIQUE_ONE'),1);self.assertEqual(report['context_text'].count('UNIQUE_TWO'),1)
        reasons={s['entity_id']:s['reason'] for s in report['sources']};self.assertEqual(reasons[older['id']],'rollup_superseded');self.assertEqual(reasons[first['id']],'memory_covered_by_rollup');self.assertEqual(reasons[other['id']],'rollup_future')
        report=self.report(chapter='p1-c12');self.assertEqual(next(s for s in report['sources'] if s['entity_id']==newer['id'])['included'],True)

    def test_whole_fact_budget_does_not_clip_or_cover_rejected_sources(self):
        self.memory('很长记忆','LONG_FACT_'+('甲'*500),'p1-c1');self.rollup()
        options=dict(chapter_id='p1-c3',include_memory_rollups=True,budget_chars=128)
        report=self.service.preview_context('p1',options);row=next(s for s in report['sources'] if s['kind']=='memory_rollup');self.assertFalse(row['included']);self.assertEqual(row['reason'],'rollup_budget');self.assertFalse(row['truncated']);self.assertEqual(row['source']['omitted'][0]['reason'],'budget');self.assertNotIn('LONG_FACT',report['context_text']);self.assertLessEqual(report['used_chars'],128)

    def test_stale_conflict_hidden_are_reported_and_raw_conflicts_excluded(self):
        m=self.memory('事实','ORIGINAL_FACT','p1-c1');r=self.rollup();self.memory('事实','CONFLICT_FACT','p1-c1')
        report=self.report(include_memories=True);row=next(s for s in report['sources'] if s['entity_id']==r['id']);self.assertEqual(row['reason'],'rollup_conflict');self.assertNotIn('ORIGINAL_FACT',report['context_text']);self.assertNotIn('CONFLICT_FACT',report['context_text'])
        self.save('archive_memory',memory_id=self.state['memories'][-1]['id']);self.save('save_chapter',chapter_id='p1-c1',content='来源已变')
        self.assertEqual(next(s for s in self.report()['sources'] if s['entity_id']==r['id'])['reason'],'rollup_stale')
        self.save('archive_chapter',chapter_id='p1-c2',confirmed=True)
        self.assertEqual(next(s for s in self.report()['sources'] if s['entity_id']==r['id'])['reason'],'rollup_hidden')

    def test_selected_search_memory_obeys_same_current_conflict_rules_only_when_enabled(self):
        self.memory('当前','SEARCH_CURRENT_SECRET','p1-c3');self.memory('冲突','SEARCH_CONFLICT_FIRST','p1-c1');self.memory('冲突','SEARCH_CONFLICT_SECOND','p1-c1')
        selections=[self.service.search_local('p1',dict(query=marker,chapter_id='p1-c3',scopes=['memories'],whole_book=True))['hits'][0]['selection'] for marker in ('SEARCH_CURRENT_SECRET','SEARCH_CONFLICT_FIRST')]
        options=dict(chapter_id='p1-c3',include_memory_rollups=True,include_search_results=True,search_selections=selections,budget_chars=20000)
        before=self.db.read_bytes();report=self.service.preview_context('p1',options);rows=[s for s in report['sources'] if s['kind']=='search_result'];self.assertEqual([s['reason'] for s in rows],['memory_current','memory_conflict']);self.assertTrue(all(not s['included'] for s in rows));self.assertNotIn('SEARCH_CURRENT_SECRET',json.dumps(report,ensure_ascii=False));self.assertNotIn('SEARCH_CONFLICT_FIRST',json.dumps(report,ensure_ascii=False));self.assertEqual(self.db.read_bytes(),before)
        through=self.service.preview_context('p1',dict(options,scope='through_current'));self.assertIn('SEARCH_CURRENT_SECRET',through['context_text']);self.assertNotIn('SEARCH_CONFLICT_FIRST',through['context_text'])
        legacy=self.service.preview_context('p1',dict(options,include_memory_rollups=False));self.assertIn('SEARCH_CURRENT_SECRET',legacy['context_text']);self.assertIn('SEARCH_CONFLICT_FIRST',legacy['context_text'])

    def test_new_mode_without_rollup_rechecks_conflicts_before_start_and_adoption(self):
        from novel_writer.application.task_protocol import LocalProtocolAdapter
        for stage in ('start','adopt'):
            with self.subTest(stage=stage):
                # A separate fixture database avoids carrying conflicts between stages.
                if stage=='adopt':
                    self.db=self.root/'adopt-isolated.sqlite3';self.db.write_bytes(bytes.fromhex(fixture.FROZEN['database_hex']));self.service=NovelService(SQLiteRepository(self.db));self.state=self.service.get('p1')
                self.memory('同一事实','BEFORE_CONFLICT','p1-c1');registry=AdapterRegistry();registry.register('rewrite_chapter',LocalProtocolAdapter(delay_seconds=0));engine=TaskCoordinator(self.service,registry);self.addCleanup(engine.close)
                task=self.prepare(dict(chapter_id='p1-c3',include_memory_rollups=True,include_memories=True,budget_chars=20000));old=deepcopy(task['frozen']);self.assertFalse(any(d['kind']=='memory_rollup' for d in old['dependencies']))
                if stage=='adopt':engine.start('p1',task['id']);engine.wait_idle(3);task=engine.describe('p1',task['id'])['task'];self.assertEqual(task['status'],'succeeded')
                self.state=self.service.get('p1');self.memory('同一事实','AFTER_CONFLICT','p1-c1');before=self.db.read_bytes()
                with self.assertRaises(ValueError):
                    if stage=='start':engine.start('p1',task['id'])
                    else:engine.adopt('p1',task['id'],dict(candidate_id=task['candidate_id'],adoption_id=str(uuid4()),expected_revision=self.service.get('p1')['revision'],authorize_confirmed=False))
                self.assertEqual(self.db.read_bytes(),before);actual=next(t for t in self.service.get('p1')['generation_tasks'] if t['id']==task['id']);self.assertEqual(actual['frozen'],old);self.assertEqual(actual['status'],'pending' if stage=='start' else 'succeeded')

    def test_new_search_context_survives_only_lifecycle_revision_changes(self):
        from novel_writer.application.task_protocol import LocalProtocolAdapter
        self.memory('前章','SEARCH_SAFE_FACT','p1-c1')
        selected=self.service.search_local('p1',dict(query='SEARCH_SAFE_FACT',chapter_id='p1-c3',scopes=['memories'],whole_book=True))['hits'][0]['selection']
        task=self.prepare(dict(chapter_id='p1-c3',include_memory_rollups=True,include_search_results=True,search_selections=[selected],budget_chars=20000));registry=AdapterRegistry();registry.register('rewrite_chapter',LocalProtocolAdapter(delay_seconds=0));engine=TaskCoordinator(self.service,registry);self.addCleanup(engine.close)
        self.assertEqual(task['frozen']['context_text'].count('SEARCH_SAFE_FACT'),1);engine.start('p1',task['id']);engine.wait_idle(3);self.assertEqual(engine.describe('p1',task['id'])['task']['status'],'succeeded')

    def test_frozen_rollup_dependency_v32_restore_copy_and_rebuild_invalidates(self):
        from novel_writer.application.backups import create_backup,restore_backup
        from novel_writer.application.migrations import migrate
        from novel_writer.application.skill_import import SkillLibrary
        self.memory('事实','FROZEN_FACT','p1-c1');rollup=self.rollup();task=self.prepare(dict(chapter_id='p1-c3',include_memory_rollups=True));state=self.service.get('p1');self.assertEqual(state['workspace_version'],32)
        dep=next(d for d in task['frozen']['dependencies'] if d['kind']=='memory_rollup');self.assertEqual(dep['version_id'],state['memory_rollup_history'][-1]['id']);self.assertEqual(dep['source_sha256'],capture_dependency(state,'memory_rollup',rollup['id']).source_sha256)
        old=deepcopy(task['frozen']);bad=deepcopy(state);bad['workspace_version']=31
        with self.assertRaises(ValueError):validate_workspace(bad)
        SkillLibrary(self.db);package=self.root/'context.nwbak';self.assertEqual(create_backup(self.db,package)['backup_format_version'],51);restored=restore_backup(package,self.root/'restored-context');self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get('p1')['generation_tasks'][-1]['frozen'],old)
        target=self.root/'copy-context.sqlite3';SQLiteRepository(target);SkillLibrary(target);result=migrate(package,target,operation_id=str(uuid4()));pid=result['projects'][0]['new_id'];clone=NovelService(SQLiteRepository(target)).get(pid);copied=clone['generation_tasks'][-1]['frozen'];d=next(d for d in copied['dependencies'] if d['kind']=='memory_rollup');self.assertEqual(d['entity_id'],clone['memory_rollups'][0]['id']);self.assertEqual(d['version_id'],clone['memory_rollup_history'][0]['id']);self.assertNotEqual(d['entity_id'],dep['entity_id']);self.assertIn('FROZEN_FACT',copied['context_text'])
        self.service.rebuild_memory_rollup('p1',rollup['id'],dict(operation_id=str(uuid4()),expected_revision=state['revision'],expected_rollup_revision=1));actual=capture_dependency(self.service.get('p1'),'memory_rollup',rollup['id']);self.assertFalse(dependency_equal(parse(Dependency,dep),actual));self.assertEqual(self.service.get('p1')['generation_tasks'][-1]['frozen'],old)


import test_chapter_writing as writing_fixture

class RollupWritingTests(unittest.TestCase):
    setUp=writing_fixture.ChapterWritingTests.setUp
    action=writing_fixture.ChapterWritingTests.action
    connection=writing_fixture.ChapterWritingTests.connection
    options=writing_fixture.ChapterWritingTests.options
    prepare=writing_fixture.ChapterWritingTests.prepare
    run_task=writing_fixture.ChapterWritingTests.run_task

    def test_actual_search_selection_remains_frozen_across_prepare_and_execution(self):
        first=self.cid;state=self.action('add_chapter',dict(title='写作当前章'));self.cid=state['document']['chapters'][-1]['id']
        self.action('save_memory',dict(kind='event',title='可用事实',text='SAFE_SELECTED_WIRE_FACT',position_chapter_id=first,confirmed=True,active=True,source=dict(kind='chapter',entity_id=first)))
        selected=self.service.search_local(self.pid,dict(query='SAFE_SELECTED_WIRE_FACT',chapter_id=self.cid,scopes=['memories'],whole_book=True))['hits'][0]['selection']
        options=self.options(context_options=dict(chapter_id=self.cid,budget_chars=20000,include_memory_rollups=True,include_memories=False,include_search_results=True,search_selections=[selected]))
        with writing_fixture.supplier(output='门外有人。') as wire:
            prepared=self.prepare(self.connection(wire),options=options);old=deepcopy(prepared['task']['frozen']);self.assertFalse(any(d['kind']=='memory_rollup' for d in old['dependencies']));self.assertEqual(old['context_text'].count('SAFE_SELECTED_WIRE_FACT'),1)
            done=self.run_task(prepared);self.assertEqual(done['task']['status'],'succeeded');self.assertEqual(len(wire['calls']),1);self.assertEqual(done['task']['frozen'],old);self.assertIn('SAFE_SELECTED_WIRE_FACT',json.dumps(wire['calls'][0]['body'],ensure_ascii=False))

    def test_real_frozen_wire_excludes_current_future_and_rebuild_rejects_old_permission(self):
        first=self.cid;ids=[first]
        for number in range(2,5):
            state=self.action('add_chapter',dict(title='虚构第'+str(number)+'章'));ids.append(state['document']['chapters'][-1]['id'])
        self.cid=ids[2]
        for chapter,text in ((first,'WIRE_PAST_FACT'),(ids[2],'WIRE_CURRENT_SECRET'),(ids[3],'WIRE_FUTURE_SECRET')):
            self.action('save_memory',dict(kind='event',title='已确认事实',text=text,position_chapter_id=chapter,confirmed=True,active=True,source=dict(kind='chapter',entity_id=chapter)))
        rollups=[]
        for chapter in (first,ids[2],ids[3]):
            state=self.service.get(self.pid);rollups.append(self.service.save_memory_rollup(self.pid,dict(scope='chapter',scope_volume_number=None,through_chapter_id=chapter,operation_id=str(uuid4()),expected_revision=state['revision']))['rollup'])
        opts=self.options(context_options=dict(chapter_id=self.cid,budget_chars=20000,include_memory_rollups=True))
        with writing_fixture.supplier(output='门外来了一个人。') as wire:
            connection=self.connection(wire);prepared=self.prepare(connection,options=opts);frozen=deepcopy(prepared['task']['frozen']);binding=frozen['parameters']['binding']
            self.assertIn('WIRE_PAST_FACT',binding['request_body']);self.assertNotIn('WIRE_CURRENT_SECRET',binding['request_body']);self.assertNotIn('WIRE_FUTURE_SECRET',binding['request_body']);self.assertEqual(wire['calls'],[])
            state=self.service.get(self.pid);self.service.rebuild_memory_rollup(self.pid,rollups[0]['id'],dict(operation_id=str(uuid4()),expected_revision=state['revision'],expected_rollup_revision=1))
            with self.assertRaises(ValueError):self.engine.start(self.pid,prepared['task']['id'],dict(confirm_external=True,request_sha256=binding['request_sha256']))
            self.assertEqual(wire['calls'],[]);self.assertEqual(self.service.get(self.pid)['generation_tasks'][-1]['frozen'],frozen)
            done=self.run_task(self.prepare(connection,options=opts));self.assertEqual(done['task']['status'],'succeeded');self.assertEqual(len(wire['calls']),1);actual=json.dumps(wire['calls'][0]['body'],ensure_ascii=False);self.assertIn('WIRE_PAST_FACT',actual);self.assertNotIn('WIRE_CURRENT_SECRET',actual);self.assertNotIn('WIRE_FUTURE_SECRET',actual)
