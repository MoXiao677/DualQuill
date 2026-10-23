"""C08 fixed fictional Unicode relevance and exact provenance regressions."""
from copy import deepcopy
import unittest
from uuid import uuid4
import test_materials as fixture
from novel_writer.application.lexical_rank import normalized_spans,rank
from novel_writer.domain.tasks import digest
from novel_writer.application.materials import Materials
from novel_writer.application.tasks import TaskCoordinator
from novel_writer.application.task_protocol import AdapterRegistry,LocalProtocolAdapter
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository
from unittest.mock import patch
import threading


class HybridTests(unittest.TestCase):
    setUp=fixture.MaterialsTests.setUp
    revision=fixture.MaterialsTests.revision
    create=fixture.MaterialsTests.create
    rebuild=fixture.MaterialsTests.rebuild
    def hybrid(self,query,ids,**options):
        return self.service.search_local(self.pid,dict(query=query,chapter_id=self.chapter,
            scopes=['materials'],material_ids=ids,mode='hybrid',**options))

    def test_unicode_rank_fixed_samples_and_original_offsets(self):
        documents=[dict(text='普通村庄的日常。'),dict(text='龙舟竞渡，古城河道。'),dict(text='古城的城墙很高。')]
        hits=rank('古城 龙舟',documents)
        self.assertEqual(hits[0]['document']['text'],documents[1]['text'])
        self.assertEqual(rank('不存在的麒麟',documents),[])
        raw='序😀 ＣＡＦＥ\u0301 Straße';normalized,spans=normalized_spans(raw)
        self.assertIn('café strasse',normalized)
        hit=rank('CAFÉ',[dict(text=raw)])[0]
        self.assertEqual(raw[hit['start']:hit['end']],'ＣＡＦＥ\u0301')
        self.assertEqual(normalized_spans('가')[0],'가')
        self.assertTrue(rank('古城 龙舟',[dict(text='river古城龙舟')]))
        self.assertEqual(rank('不存在',[dict(text='😀 CAFÉ Straße 𠀀')]),[])
        self.assertEqual(rank('',documents),[])

    def test_hybrid_material_excerpts_are_exact_and_revalidated(self):
        material=self.create('甲'*900+'龙舟竞渡与古城河道。'+'乙'*500)['material'];self.rebuild(material['id'])
        report=self.hybrid('古城 龙舟',[material['id']]);self.assertTrue(report['hits'])
        hit=report['hits'][0];selection=hit['selection'];excerpt=selection['excerpt']
        original=self.materials.version(self.pid,material['id'],selection['version_id'])['text']
        self.assertEqual(digest(original[excerpt['start']:excerpt['end']]),excerpt['sha256'])
        self.assertFalse(hit['explanation']['semantic']);self.assertFalse(report['model_request_sent'])
        preview=self.service.preview_context(self.pid,dict(chapter_id=self.chapter,include_search_results=True,search_selections=[selection]))
        self.assertIn('龙舟竞渡',preview['context_text']);self.assertNotIn('甲'*850,preview['context_text'])
        bad=deepcopy(selection);bad['excerpt']['sha256']='0'*64
        with self.assertRaises(ValueError):self.service.preview_context(self.pid,dict(chapter_id=self.chapter,include_search_results=True,search_selections=[bad]))

    def test_incremental_reuses_only_identical_windows_and_cancel_rolls_back(self):
        original='甲'*2000;material=self.create(original)['material'];first=self.rebuild(material['id'])
        self.materials.update(self.pid,material['id'],dict(operation_id=str(uuid4()),expected_revision=self.revision(),title='资料',format='txt',tags=[],text=original[:1700]+'乙'+original[1701:]))
        updated=self.rebuild(material['id'])
        self.assertEqual(updated['index_update']['reused_chunks'],2)
        self.assertEqual(updated['index_update']['rebuilt_chunks'],1)
        self.assertEqual(first['chunks'][0]['id'],updated['chunks'][0]['id'])
        before=self.db.read_bytes()
        with self.assertRaisesRegex(ValueError,'cancelled'):
            self.materials.rebuild(self.pid,material['id'],dict(operation_id=str(uuid4()),expected_revision=self.revision()),cancelled=lambda:True)
        self.assertEqual(self.db.read_bytes(),before)

    def update(self,material,text):
        return self.materials.update(self.pid,material['id'],dict(operation_id=str(uuid4()),expected_revision=self.revision(),title='资料',format='txt',tags=[],text=text))

    def engine(self):
        registry=AdapterRegistry();registry.register('rewrite_chapter',LocalProtocolAdapter(delay_seconds=0))
        engine=TaskCoordinator(self.service,registry);self.addCleanup(engine.close);return engine

    def prepare(self,engine,selection):
        options=dict(chapter_id=self.chapter,include_search_results=True,search_selections=[selection],budget_chars=20000)
        report=self.service.preview_context(self.pid,options)
        return engine.prepare(self.pid,dict(request_id=str(uuid4()),chapter_id=self.chapter,task_type='rewrite_chapter',context_options=options,
            context_sha256=digest(report['context_text']),parameters=dict(instruction='虚构测试',max_output_chars=1000,timeout_ms=1000),expected_revision=report['revision']))['task']

    def test_no_hits_limit_determinism_and_unmodified_literal_mode(self):
        material=self.create('古城城墙。\n'+'龙舟竞渡。'*400)['material'];self.rebuild(material['id'])
        request=dict(query='古城 龙舟',chapter_id=self.chapter,scopes=['materials'],material_ids=[material['id']])
        self.assertEqual(self.service.search_local(self.pid,request)['hits'],[])
        self.assertEqual(self.hybrid('完全不相干的麒麟',[material['id']])['hits'],[])
        first=self.hybrid('龙舟',[material['id']],limit=1);self.assertEqual(first,self.hybrid('龙舟',[material['id']],limit=1))
        self.assertTrue(first['limited']);self.assertEqual(len(first['hits']),1)
        self.assertFalse(first['capabilities']['embeddings']);self.assertFalse(first['capabilities']['remote_embeddings'])

    def test_stale_archived_missing_and_crossbook_materials_never_enter_context(self):
        material=self.create('龙舟 古城')['material']
        with self.assertRaises(ValueError):self.hybrid('龙舟',[material['id']])
        self.rebuild(material['id']);selected=self.hybrid('龙舟',[material['id']])['hits'][0]['selection']
        self.update(material,'资料变化了')
        with self.assertRaises(ValueError):self.hybrid('龙舟',[material['id']])
        result=self.service.preview_context(self.pid,dict(chapter_id=self.chapter,include_search_results=True,search_selections=[selected]))
        self.assertNotIn('龙舟',result['context_text']);self.assertTrue(any(s['reason']=='material_index_stale' for s in result['sources']))
        self.rebuild(material['id']);self.materials.archive(self.pid,material['id'],dict(operation_id=str(uuid4()),expected_revision=self.revision()))
        with self.assertRaises(ValueError):self.hybrid('龙舟',[material['id']])
        other=self.service.create(title='另一本虚构小说')['document']['project']['id']
        with self.assertRaises(KeyError):self.materials.describe(other,material['id'])
        bad=dict(selected,project_id=other)
        with self.assertRaises(ValueError):self.service.preview_context(self.pid,dict(chapter_id=self.chapter,include_search_results=True,search_selections=[bad]))

    def test_budget_reports_consumed_exact_range_hash(self):
        material=self.create('龙舟'*400)['material'];self.rebuild(material['id'])
        selected=self.hybrid('龙舟',[material['id']])['hits'][0]['selection']
        result=self.service.preview_context(self.pid,dict(chapter_id=self.chapter,include_search_results=True,search_selections=[selected],budget_chars=128))
        source=next(s for s in result['sources'] if s['kind']=='search_result')
        self.assertTrue(source['truncated']);self.assertEqual(len(result['context_text']),128)
        self.assertEqual(source['included_range'],dict(start=0,end=128,sha256=digest(result['context_text'])))

    def test_tag_suggestions_have_exact_version_ranges_and_zero_writes(self):
        material=self.create('# 古城龙舟\n古城龙舟\n古城龙舟\nCAFÉ Café café')['material'];before=self.db.read_bytes()
        result=self.materials.suggest_tags(self.pid,material['id'],{})
        self.assertEqual(result['suggestions'][0]['tag'],'古城龙舟');self.assertEqual(self.db.read_bytes(),before)
        text=self.materials.version(self.pid,material['id'],material['current_version_id'])['text']
        for item in result['suggestions']:
            self.assertEqual(text[item['start']:item['end']],item['evidence']);self.assertEqual(item['sha256'],digest(item['evidence']))
            self.assertEqual(item['version_id'],material['current_version_id'])
        self.assertTrue(result['requires_manual_save']);self.assertFalse(result['model_request_sent'])
        empty=self.create('#    \n单次')['material']
        self.assertEqual(self.materials.suggest_tags(self.pid,empty['id'],{})['suggestions'],[])

    def test_incremental_scope_shift_and_unrelated_material_are_explicit(self):
        original=''.join(chr(0x4e00+i) for i in range(2000))
        material=self.create(original)['material'];other=self.create('其他资料独立不变')['material']
        self.rebuild(material['id']);self.rebuild(other['id']);unchanged=deepcopy(self.materials.describe(self.pid,other['id'])['chunks'])
        self.update(material,'Ω'+original[1:])
        changed=self.rebuild(material['id']);self.assertEqual(changed['index_update']['changed_ranges'],[dict(start=0,end=800)])
        self.assertEqual(self.materials.describe(self.pid,other['id'])['chunks'],unchanged)
        self.update(material,'丙'+'Ω'+original[1:])
        shifted=self.rebuild(material['id']);self.assertEqual(shifted['index_update']['rebuilt_chunks'],3)
        self.assertEqual(shifted['index_update']['reused_chunks'],0)
        self.assertEqual(self.materials.describe(self.pid,other['id'])['chunks'],unchanged)

    def test_index_job_detects_source_change_before_worker_transaction(self):
        material=self.create('古城龙舟 原资料')['material'];entered=threading.Event();resume=threading.Event();rebuild=self.materials.rebuild
        def paused(*args,**kwargs):
            entered.set();resume.wait(3);return rebuild(*args,**kwargs)
        jobs=self.materials.index_jobs;self.addCleanup(jobs.close)
        with patch.object(self.materials,'rebuild',side_effect=paused):
            job=jobs.start(self.pid,material['id'],dict(operation_id=str(uuid4()),expected_revision=self.revision()));self.assertTrue(entered.wait(3))
            self.update(material,'新资料不能被旧索引任务覆盖');before=self.db.read_bytes();resume.set()
            jobs.jobs[job['id']]['thread'].join(3)
        self.assertEqual(jobs.status(self.pid,job['id'])['status'],'conflict');self.assertEqual(self.db.read_bytes(),before)
        self.assertEqual(self.materials.describe(self.pid,material['id'])['material']['index_status'],'missing')

    def test_send_and_adopt_recheck_material_versions_without_rollups(self):
        for stage in ('send','adopt'):
            with self.subTest(stage=stage):
                material=self.create('龙舟仍是原资料 '+stage)['material'];self.rebuild(material['id'])
                selected=self.hybrid('龙舟',[material['id']])['hits'][0]['selection'];engine=self.engine();task=self.prepare(engine,selected)
                self.assertEqual(self.service.get(self.pid)['workspace_version'],44)
                self.assertFalse(task['frozen']['context_options'].get('include_memory_rollups',False))
                if stage=='adopt':
                    engine.start(self.pid,task['id']);engine.wait_idle(3);task=engine.describe(self.pid,task['id'])['task'];self.assertEqual(task['status'],'succeeded')
                self.update(material,'此版本不能沿用旧检索许可');before=self.db.read_bytes()
                with self.assertRaises(ValueError):
                    if stage=='send':engine.start(self.pid,task['id'])
                    else:engine.adopt(self.pid,task['id'],dict(candidate_id=task['candidate_id'],adoption_id=str(uuid4()),expected_revision=self.revision(),authorize_confirmed=False))
                self.assertEqual(self.db.read_bytes(),before)

    def test_index_jobs_cancel_transaction_idempotence_and_reopen(self):
        material=self.create('古城龙舟'*500)['material'];before=self.db.read_bytes();entered=threading.Event();resume=threading.Event()
        build=self.materials._build
        def paused(*args,**kwargs):
            original=kwargs['cancelled'];count=0
            def cancelled():
                nonlocal count
                count+=1
                if count==2:entered.set();resume.wait(3)
                return original()
            kwargs['cancelled']=cancelled
            return build(*args,**kwargs)
        request=dict(operation_id=str(uuid4()),expected_revision=self.revision());jobs=self.materials.index_jobs;self.addCleanup(jobs.close)
        with patch.object(self.materials,'_build',side_effect=paused):
            job=jobs.start(self.pid,material['id'],request);self.assertTrue(entered.wait(3));self.assertEqual(jobs.start(self.pid,material['id'],request)['id'],job['id'])
            self.assertEqual(jobs.cancel(self.pid,job['id'])['status'],'cancelling');resume.set();jobs.close()
        self.assertEqual(jobs.status(self.pid,job['id'])['status'],'cancelled');self.assertEqual(self.db.read_bytes(),before)
        reopened=Materials(NovelService(SQLiteRepository(self.db)))
        with self.assertRaises(KeyError):reopened.index_jobs.status(self.pid,job['id'])
        request=dict(operation_id=str(uuid4()),expected_revision=self.revision());first=self.materials.rebuild(self.pid,material['id'],request);raw=self.db.read_bytes()
        self.materials.rebuild(self.pid,material['id'],request);self.assertEqual(self.db.read_bytes(),raw)
        after=Materials(NovelService(SQLiteRepository(self.db))).describe(self.pid,material['id']);self.assertEqual(first['chunks'],after['chunks'])
        reopened=Materials(NovelService(SQLiteRepository(self.db)));replayed=reopened.index_jobs.start(self.pid,material['id'],request)
        self.assertEqual(replayed['status'],'succeeded');self.assertTrue(replayed['result']['replayed']);self.assertEqual(self.db.read_bytes(),raw)

    def test_v36_restore_copy_preserve_excerpt_and_do_not_inherit_permission(self):
        from novel_writer.application.backups import create_backup,restore_backup
        from novel_writer.application.migrations import migrate
        from novel_writer.application.skill_import import SkillLibrary
        material=self.create('恢复复制中的古城龙舟')['material'];self.rebuild(material['id'])
        selected=self.hybrid('古城 龙舟',[material['id']])['hits'][0]['selection'];engine=self.engine();task=self.prepare(engine,selected)
        source=self.service.get(self.pid);SkillLibrary(self.db);package=self.root/'hybrid.nwbak'
        manifest=create_backup(self.db,package);self.assertEqual(manifest['backup_format_version'],51)
        restored=restore_backup(package,self.root/'restored');clone=NovelService(SQLiteRepository(restored['database_path']));self.assertEqual(clone.get(self.pid),source)
        target=self.root/'copy.sqlite3';SQLiteRepository(target);SkillLibrary(target);copied=migrate(package,target,operation_id=str(uuid4()));newpid=copied['projects'][0]['new_id'];copy_service=NovelService(SQLiteRepository(target));mapped=copy_service.get(newpid)
        frozen=mapped['generation_tasks'][-1]['frozen'];selection=frozen['context_options']['search_selections'][0]
        self.assertEqual(selection['excerpt'],selected['excerpt']);self.assertEqual(selection['entity_id'],mapped['materials'][0]['id']);self.assertEqual(selection['version_id'],mapped['material_versions'][0]['id'])
        self.assertEqual(frozen['context_text'],task['frozen']['context_text'])
        self.assertNotEqual(frozen['context_options']['retrieval_owner'],task['frozen']['context_options']['retrieval_owner'])
        for service,pid in ((clone,self.pid),(copy_service,newpid)):
            registry=AdapterRegistry();registry.register('rewrite_chapter',LocalProtocolAdapter(delay_seconds=0));reopened=TaskCoordinator(service,registry);self.addCleanup(reopened.close)
            with self.assertRaisesRegex(ValueError,'许可不继承'):reopened.start(pid,service.get(pid)['generation_tasks'][-1]['id'])

    def test_old_v1_through_v35_reads_search_and_listing_are_zero_write(self):
        """35 format baselines with a saved chapter and empty newer collections.

        Nonempty historical frozen values are separately exercised by the
        retained V1/V15/V26/V32/V35 backup/writing/candidate regressions.
        """
        from importlib import import_module
        from novel_writer.application.chapter_lifecycle import upgrade
        full=upgrade(deepcopy(self.service.get(self.pid)));thresholds={}
        modules=[(3,'tasks','COLLECTIONS'),(4,'review','REVIEW_COLLECTIONS'),(5,'knowledge','KNOWLEDGE_COLLECTIONS'),
            (6,'model_contract','MODEL_COLLECTIONS'),(7,'experiments','EXPERIMENT_COLLECTIONS'),(8,'workflows','WORKFLOW_COLLECTIONS'),
            (10,'creation_presets','CREATION_COLLECTIONS'),(11,'book_creation','COLLECTIONS'),(12,'book_ai','COLLECTIONS'),
            (13,'styles','COLLECTIONS'),(14,'public_search','COLLECTIONS'),(15,'style_trials','COLLECTIONS'),
            (16,'chapter_writing','COLLECTIONS'),(17,'chapter_planning','COLLECTIONS'),(18,'scene_expansion','COLLECTIONS'),
            (19,'chapter_lifecycle','COLLECTIONS'),(20,'console','COLLECTIONS'),(23,'memory_rollups','COLLECTIONS'),
            (24,'console','RUN_COLLECTIONS'),(25,'materials','COLLECTIONS'),(26,'full_book_planning','COLLECTIONS'),(27,'chapter_trash','COLLECTIONS')]
        for version,module,name in modules:
            thresholds.update({key:version for key in getattr(import_module('novel_writer.domain.'+module),name)})
        thresholds.update(memories=2,memory_history=2,scoped_rules=21,scoped_rule_history=22)
        for version in range(1,36):
            with self.subTest(workspace_version=version):
                state={key:deepcopy(value) for key,value in full.items() if thresholds.get(key,1)<=version};state['workspace_version']=version
                db=self.root/f'legacy-v{version}.sqlite3';repository=SQLiteRepository(db);saved=repository.create(state);service=NovelService(repository);before=db.read_bytes()
                self.assertEqual(service.get(self.pid),saved)
                self.assertEqual(service.search_local(self.pid,dict(query='绝不命中的虚构文本',chapter_id=self.chapter,mode='hybrid'))['hits'],[])
                service.preview_context(self.pid,dict(chapter_id=self.chapter));Materials(service).listing(self.pid)
                self.assertEqual(db.read_bytes(),before);self.assertEqual(service.get(self.pid)['workspace_version'],version)

    def test_composed_workflow_context_clears_old_retrieval_permission(self):
        from dataclasses import replace
        from novel_writer.application.tasks import context_options
        from novel_writer.domain.tasks import parse,ContextOptions,encode
        material=self.create('古城龙舟 工作流资料')['material'];self.rebuild(material['id'])
        selected=self.hybrid('古城 龙舟',[material['id']])['hits'][0]['selection'];task=self.prepare(self.engine(),selected)
        options=parse(ContextOptions,task['frozen']['context_options'])
        # Existing workflow auditing clears selected sources before composing a
        # new preparation. A historical process owner is never a new permission.
        clean=replace(options,include_search_results=False,search_selections=())
        self.assertIsNone(context_options(encode(clean)).retrieval_owner)
        self.assertEqual(parse(ContextOptions,task['frozen']['context_options']).retrieval_owner,options.retrieval_owner)
        with self.assertRaises(ValueError):context_options(dict(chapter_id=self.chapter,retrieval_owner={'forged':True}))


import test_s3b_retrieval as memory_fixture


class HybridMemoryTests(unittest.TestCase):
    setUp=memory_fixture.RetrievalTests.setUp
    save=memory_fixture.RetrievalTests.save
    memory=memory_fixture.RetrievalTests.memory

    def search(self,query,**changes):
        return self.service.search_local('p1',dict(query=query,chapter_id='p1-c5',scopes=['memories'],mode='hybrid',**changes))

    def test_future_archived_unconfirmed_outdated_and_conflicting_memory_exclusions(self):
        good=self.memory('古城龙舟 清晰事实',title='允许事实')
        self.memory('古城龙舟 未确认',confirmed=False,title='未确认')
        future=self.memory('古城龙舟 未来事实',position_chapter_id='p1-c20',title='未来事实')
        archived=self.memory('古城龙舟 归档事实',title='归档事实');self.save('archive_memory',memory_id=archived['id'])
        conflict1=self.memory('古城龙舟 蓝色旗帜',title='冲突旗帜');conflict2=self.memory('古城龙舟 红色旗帜',title='冲突旗帜')
        hits=self.search('古城 龙舟')['hits'];self.assertEqual([h['entity_id'] for h in hits],[good['id']])
        whole=self.search('古城 龙舟',whole_book=True);selected=next(h['selection'] for h in whole['hits'] if h['entity_id']==future['id'])
        result=self.service.preview_context('p1',dict(chapter_id='p1-c5',include_search_results=True,search_selections=[selected],scope='through_current'))
        self.assertNotIn('未来事实',result['context_text'])
        self.save('save_chapter',chapter_id='p1-c5',content='使本章来源过期')
        self.assertEqual(self.search('古城 龙舟')['hits'],[])

    def test_hidden_chapters_crossbook_and_current_scope_excluded(self):
        current=self.memory('古城龙舟 当前事实',title='当前事实')
        past=self.memory('古城龙舟 前章事实',position_chapter_id='p1-c1',source={'kind':'chapter','entity_id':'p1-c1'},title='前章事实')
        hits=self.search('古城 龙舟')['hits'];selected=next(h['selection'] for h in hits if h['entity_id']==current['id'])
        result=self.service.preview_context('p1',dict(chapter_id='p1-c5',include_search_results=True,search_selections=[selected]))
        self.assertNotIn('当前事实',result['context_text']);self.assertTrue(any(s['reason']=='memory_current' for s in result['sources']))
        result=self.service.preview_context('p1',dict(chapter_id='p1-c5',scope='through_current',include_search_results=True,search_selections=[selected]))
        self.assertIn('当前事实',result['context_text'])
        self.save('archive_chapter',chapter_id='p1-c1',confirmed=True)
        self.assertNotIn(past['id'],[h['entity_id'] for h in self.search('古城 龙舟')['hits']])
        foreign=self.service.search_local('p1',dict(query='BODY_p2',chapter_id='p1-c5',scopes=['body'],mode='hybrid',whole_book=True))
        self.assertNotIn('BODY_p2',str([h['snippet'] for h in foreign['hits']]))
        self.assertTrue(all(h['selection']['project_id']=='p1' for h in foreign['hits']))

    def test_future_source_overrides_declared_earlier_memory_position(self):
        self.memory('古城龙舟 未来出处',position_chapter_id='p1-c1',source={'kind':'chapter','entity_id':'p1-c20'},title='未来出处')
        self.assertEqual(self.search('古城 龙舟')['hits'],[])


if __name__=='__main__':unittest.main()
