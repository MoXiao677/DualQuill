"""C05 local incremental queues and conservative automatic factual context."""
from copy import deepcopy
import json,unittest
from uuid import uuid4
import test_s3b_rollups as fixture
from novel_writer.application.incremental_memory import policy,impact,upgrade
from novel_writer.application.service import NovelService
from novel_writer.application.tasks import context_options,TaskCoordinator
from novel_writer.application.task_protocol import AdapterRegistry,LocalProtocolAdapter
from novel_writer.domain.tasks import encode,digest
from novel_writer.storage.sqlite_repository import SQLiteRepository,validate_workspace,ConflictError
from novel_writer.application.backups import create_backup,restore_backup
from novel_writer.application.migrations import migrate


class IncrementalMemoryTests(unittest.TestCase):
    setUp=fixture.MemoryRollupTests.setUp
    save=fixture.MemoryRollupTests.save
    memory=fixture.MemoryRollupTests.memory

    def configure(self,**values):
        request=dict(action='policy',operation_id=str(uuid4()),expected_revision=self.service.get('p1')['revision'],policy={**dict(track_updates=True,auto_select=True),**values})
        result=self.service.change_memory_automation('p1',request);self.state=self.service.get('p1');return request,result

    def report(self,**values):
        return self.service.preview_context('p1',{**dict(chapter_id='p1-c3',include_automatic_memories=True,budget_chars=20000),**values})

    def test_default_disabled_read_zero_write_and_legacy_encoding(self):
        self.memory('旧事实','SAFE_OLD_FACT');before=self.db.read_bytes()
        self.assertEqual(self.service.memory_automation('p1')['policy'],dict(track_updates=False,auto_select=False))
        self.assertNotIn('SAFE_OLD_FACT',self.report()['context_text']);self.assertEqual(self.db.read_bytes(),before)
        self.assertNotIn('include_automatic_memories',encode(context_options(dict(chapter_id='p1-c3'))))
        self.save('save_chapter',chapter_id='p1-c1',content='正文修订')
        self.assertFalse(self.state.get('memory_automation_events'))  # V50 记忆刷新只建空集合、不写自动化事件

    def test_opt_in_persists_without_external_grant_and_policy_replay(self):
        request,result=self.configure();self.assertEqual(self.state['workspace_version'],42)
        self.assertFalse(result['external_execution_authorized']);before=self.db.read_bytes()
        self.assertTrue(self.service.change_memory_automation('p1',request)['idempotent']);self.assertEqual(self.db.read_bytes(),before)
        reopened=NovelService(SQLiteRepository(self.db));self.assertTrue(reopened.memory_automation('p1')['policy']['auto_select'])
        with self.assertRaises(ValueError):self.service.change_memory_automation('p1',dict(request,confirm_external=True))
        with self.assertRaises(ValueError):self.service.change_memory_automation('p1',dict(request,policy=dict(track_updates=False,auto_select=True)))
        self.assertEqual(self.db.read_bytes(),before)

    def test_exact_incremental_scope_and_unrelated_saves(self):
        first=self.memory('第一事实','FIRST_FACT');second=self.memory('第二事实','SECOND_FACT','p1-c2')
        rollup=self.service.save_memory_rollup('p1',dict(scope='chapter',scope_volume_number=None,through_chapter_id='p1-c1',operation_id=str(uuid4()),expected_revision=self.state['revision']))['rollup']
        self.state=self.service.get('p1');self.configure();self.save('save_chapter',chapter_id='p1-c1',content='新版第一章')
        queue=self.service.memory_automation('p1')['queue'];self.assertEqual(len(queue),1)
        self.assertEqual(queue[0]['chapter_ids'],['p1-c1']);self.assertEqual(queue[0]['memory_ids'],[first['id']]);self.assertEqual(queue[0]['rollup_ids'],[rollup['id']]);self.assertNotIn(second['id'],queue[0]['memory_ids'])
        self.save('save_idea',chapter_id='p1-c2',content='这只是未发生规划')
        self.assertEqual(len(self.service.memory_automation('p1')['queue']),1)
        self.assertTrue(self.service.memory_records('p1')[0]['outdated'])

    def test_archive_restore_and_reorder_are_deterministic_impacts(self):
        self.memory('事实','PAST_FACT');self.configure()
        self.save('archive_chapter',chapter_id='p1-c1',confirmed=True)
        self.assertEqual(self.service.memory_automation('p1')['queue'][-1]['chapter_ids'],['p1-c1'])
        self.assertNotIn('PAST_FACT',self.report()['context_text'])
        self.save('unarchive_chapter',chapter_id='p1-c1',confirmed=True)
        self.assertEqual(len(self.service.memory_automation('p1')['queue']),2)
        before=deepcopy(self.state);after=deepcopy(before)
        a,b=after['document']['chapters'][:2];a['number'],b['number']=b['number'],a['number']
        self.assertEqual(impact(before,after)['chapter_ids'],['p1-c1','p1-c2'])
        self.save('move_chapter',chapter_id='p1-c2',direction='up',confirmed=True)
        self.assertEqual(self.service.memory_automation('p1')['queue'][-1]['chapter_ids'],['p1-c1','p1-c2'])

    def test_future_current_planning_unconfirmed_conflict_and_stale_exclusions(self):
        safe=self.memory('安全','SAFE_FACT');self.memory('当前','CURRENT_SECRET','p1-c3');self.memory('将来','FUTURE_SECRET','p1-c4')
        self.memory('计划','PLAN_SECRET',source_kind='idea');self.memory('未核实','UNCONFIRMED_SECRET',confirmed=False)
        self.memory('冲突','CONFLICT_A');self.memory('冲突','CONFLICT_B')
        stale=self.memory('旧来源','STALE_SECRET','p1-c2');self.save('save_chapter',chapter_id='p1-c2',content='来源已改')
        self.configure();report=self.report();self.assertIn('SAFE_FACT',report['context_text'])
        for marker in ('CURRENT_SECRET','FUTURE_SECRET','PLAN_SECRET','UNCONFIRMED_SECRET','CONFLICT_A','CONFLICT_B','STALE_SECRET'):self.assertNotIn(marker,json.dumps(report,ensure_ascii=False))
        reasons={s['reason'] for s in report['sources']};self.assertTrue({'memory_current','memory_future','memory_planning_source','memory_unconfirmed','memory_conflict','memory_outdated'}<=reasons)
        self.assertIn('CURRENT_SECRET',self.report(scope='through_current')['context_text'])

    def test_budget_excludes_whole_memory_and_reports_reason(self):
        self.memory('长事实','LONG_SECRET'+'甲'*500);self.configure();report=self.report(budget_chars=128)
        row=next(s for s in report['sources'] if s['kind']=='memory')
        self.assertEqual(row['reason'],'automatic_budget');self.assertFalse(row['included']);self.assertFalse(row['truncated']);self.assertNotIn('LONG_SECRET',report['context_text'])
        selection=self.service.search_local('p1',dict(query='LONG_SECRET',chapter_id='p1-c3',scopes=['memories'],whole_book=True))['hits'][0]['selection']
        combined=self.report(budget_chars=128,include_search_results=True,search_selections=[selection])
        self.assertNotIn('LONG_SECRET',combined['context_text']);self.assertTrue(all(not s['truncated'] for s in combined['sources'] if s['kind'] in ('memory','search_result')))

    def test_cancel_reopen_idempotency_reopen_disk_and_history_guard(self):
        self.configure();self.save('save_chapter',chapter_id='p1-c1',content='影响队列')
        job=self.service.memory_automation('p1')['queue'][0]['id']
        for action,status in (('cancel','cancelled'),('reopen','pending'),('resolve','reviewed'),('reopen','pending')):
            request=dict(action=action,job_id=job,operation_id=str(uuid4()),expected_revision=self.service.get('p1')['revision'])
            self.service.change_memory_automation('p1',request);before=self.db.read_bytes()
            self.assertTrue(self.service.change_memory_automation('p1',request)['idempotent']);self.assertEqual(self.db.read_bytes(),before)
            self.service=NovelService(SQLiteRepository(self.db));self.assertEqual(self.service.memory_automation('p1')['queue'][0]['status'],status)
        state=self.service.get('p1');state['memory_automation_events'][0]['policy']['auto_select']=False
        with self.assertRaises(ValueError):self.service.repository.save(state,expected_revision=state['revision'])
        self.assertEqual(self.db.read_bytes(),before)

    def test_automatic_frozen_context_rechecks_before_send(self):
        self.memory('事实','FROZEN_SAFE');self.configure()
        registry=AdapterRegistry();registry.register('rewrite_chapter',LocalProtocolAdapter(delay_seconds=0))
        engine=TaskCoordinator(self.service,registry);self.addCleanup(engine.close)
        options=dict(chapter_id='p1-c3',include_automatic_memories=True,budget_chars=20000)
        report=self.service.preview_context('p1',options)
        task=engine.prepare('p1',dict(request_id=str(uuid4()),chapter_id='p1-c3',task_type='rewrite_chapter',context_options=options,context_sha256=digest(report['context_text']),parameters=dict(instruction='虚构测试',max_output_chars=1000,timeout_ms=1000),expected_revision=report['revision']))['task']
        self.assertTrue(task['frozen']['context_options']['include_automatic_memories']);self.assertIn('FROZEN_SAFE',task['frozen']['context_text'])
        self.configure(auto_select=False)
        with self.assertRaises(ValueError):engine.start('p1',task['id'])
        self.assertEqual(engine.describe('p1',task['id'])['task']['status'],'pending')

    def test_v36_backup_restore_copy_policy_disabled_and_history_preserved(self):
        self.memory('虚构事实','COPY_FACT');self.configure();self.save('save_chapter',chapter_id='p1-c1',content='复制前新正文')
        job=self.service.memory_automation('p1')['queue'][0]['id']
        self.service.change_memory_automation('p1',dict(action='cancel',operation_id=str(uuid4()),expected_revision=self.state['revision'],job_id=job))
        archive=self.root/'backup.zip';create_backup(self.db,archive);restored=restore_backup(archive,self.root/'restored')
        self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).memory_automation('p1')['queue'][0]['status'],'cancelled')
        copied_db=self.root/'copied.sqlite3';copied_db.write_bytes(bytes.fromhex(fixture.FROZEN['database_hex']));result=migrate(archive,copied_db,operation_id=str(uuid4()));target=NovelService(SQLiteRepository(copied_db));pid=next(p['new_id'] for p in result['projects'] if p['old_id']=='p1')
        copied=target.get(pid);self.assertEqual(policy(copied),dict(track_updates=False,auto_select=False));self.assertEqual(len(copied['memory_automation_events']),len(self.service.get('p1')['memory_automation_events']))
        self.assertFalse(target.memory_automation(pid)['external_execution_authorized']);validate_workspace(copied)

    def test_new_memory_impacts_existing_empty_rollup_and_same_body_new_version(self):
        rollup=self.service.save_memory_rollup('p1',dict(scope='book',scope_volume_number=None,through_chapter_id='p1-c2',operation_id=str(uuid4()),expected_revision=self.state['revision']))['rollup']
        self.state=self.service.get('p1');self.configure();self.memory('新事实','NEW_FACT')
        self.assertEqual(self.service.memory_automation('p1')['queue'][-1]['rollup_ids'],[rollup['id']])
        before=self.state['document']['chapters'][0]['content'];self.save('save_chapter',chapter_id='p1-c1',content=before)
        self.assertEqual(self.service.memory_automation('p1')['queue'][-1]['chapter_ids'],['p1-c1'])

    def test_conflict_marks_both_memories_and_failed_save_does_not_enqueue(self):
        first=self.memory('同题事实','FIRST_VERSION');self.configure();self.memory('同题事实','SECOND_VERSION')
        self.assertEqual(set(self.service.memory_automation('p1')['queue'][-1]['memory_ids']),{first['id'],self.state['memories'][-1]['id']})
        before=self.db.read_bytes();count=len(self.service.memory_automation('p1')['queue'])
        with self.assertRaises(ConflictError):self.service.execute('p1','save_chapter',dict(chapter_id='p1-c1',content='不应保存'),expected_revision=self.state['revision']-1)
        self.assertEqual(self.db.read_bytes(),before);self.assertEqual(len(self.service.memory_automation('p1')['queue']),count)

    def test_combined_rollups_and_search_do_not_reintroduce_planning(self):
        self.memory('计划','PLAN_ONLY_SECRET',source_kind='idea')
        self.service.save_memory_rollup('p1',dict(scope='book',scope_volume_number=None,through_chapter_id='p1-c2',operation_id=str(uuid4()),expected_revision=self.state['revision']))
        self.state=self.service.get('p1');self.configure()
        selection=self.service.search_local('p1',dict(query='PLAN_ONLY_SECRET',chapter_id='p1-c3',scopes=['memories'],whole_book=True))['hits'][0]['selection']
        report=self.report(include_memory_rollups=True,include_search_results=True,search_selections=[selection])
        self.assertNotIn('PLAN_ONLY_SECRET',json.dumps(report,ensure_ascii=False))

    def test_v1_through_v35_read_only_matrix_with_exact_old_rows(self):
        from importlib import import_module
        from novel_writer.application.projects import create
        base=create(dict(title='虚构旧版兼容书'));upgrade(base)
        groups={2:{'memories','memory_history'},19:{'chapter_lifecycle_events'},21:{'scoped_rules'},22:{'scoped_rule_history'},36:{'rule_task_bindings'},41:{'deep_review_actions'},42:{'memory_automation_events'}}
        modules={3:('tasks','COLLECTIONS'),4:('review','REVIEW_COLLECTIONS'),5:('knowledge','KNOWLEDGE_COLLECTIONS'),6:('model_contract','MODEL_COLLECTIONS'),7:('experiments','EXPERIMENT_COLLECTIONS'),8:('workflows','WORKFLOW_COLLECTIONS'),10:('creation_presets','CREATION_COLLECTIONS'),11:('book_creation','COLLECTIONS'),12:('book_ai','COLLECTIONS'),13:('styles','COLLECTIONS'),14:('public_search','COLLECTIONS'),15:('style_trials','COLLECTIONS'),16:('chapter_writing','COLLECTIONS'),17:('chapter_planning','COLLECTIONS'),18:('scene_expansion','COLLECTIONS'),20:('console','COLLECTIONS'),23:('memory_rollups','COLLECTIONS'),24:('console','RUN_COLLECTIONS'),25:('materials','COLLECTIONS'),26:('full_book_planning','COLLECTIONS'),27:('chapter_trash','COLLECTIONS')}
        for version,(module,attribute) in modules.items():groups[version]=set(getattr(import_module('novel_writer.domain.'+module),attribute))
        for version in range(1,36):
            with self.subTest(version=version):
                old=deepcopy(base);old['workspace_version']=version
                for introduced,names in groups.items():
                    if introduced>version:
                        for name in names:old.pop(name,None)
                db=self.root/('v'+str(version)+'.sqlite3');repo=SQLiteRepository(db);saved=repo.create(old)
                before=db.read_bytes();service=NovelService(SQLiteRepository(db));pid=saved['document']['project']['id']
                self.assertEqual(service.get(pid),saved);self.assertEqual(service.memory_automation(pid)['queue'],[])
                self.assertEqual(policy(service.get(pid)),dict(track_updates=False,auto_select=False));self.assertEqual(db.read_bytes(),before)

    def test_all_accepted_model_evidence_is_affected_and_story_position_guarded(self):
        from novel_writer.application.incremental_memory import automatic_candidates
        memory=self.memory('多源事实','MULTI_SOURCE_SECRET','p1-c2');self.configure()
        before=deepcopy(self.state);edit=before['memory_history'][-1]
        before['model_proposal_receipts']=[dict(decision='accepted',memory_id=memory['id'],memory_version_id=edit['id'],saved_revision=memory['source']['workspace_revision']+1,proposal_id='fiction-proposal')]
        before['model_memory_proposals']=[dict(id='fiction-proposal',draft=dict(evidence=[dict(chapter_id='p1-c1'),dict(chapter_id='p1-c2')]))]
        after=deepcopy(before);after['document']['chapters'][0]['content']='副引文来源也改变'
        self.assertIn(memory['id'],impact(before,after)['memory_ids'])
        after=deepcopy(before);a=next(c for c in after['document']['chapters'] if c['id']=='p1-c1');b=next(c for c in after['document']['chapters'] if c['id']=='p1-c11');a['number'],b['number']=b['number'],a['number']
        chapter=next(c for c in after['document']['chapters'] if c['id']=='p1-c3')
        row=next(v for v in automatic_candidates(after,chapter,'previous') if v[0]['id']==memory['id'])
        self.assertEqual(row[1],'memory_future')
        self.assertEqual(row[2],11)

    def test_automatic_context_can_execute_locally_but_new_conflict_blocks_adoption(self):
        self.memory('同一事实','BEFORE_AUTO_CONFLICT');self.configure()
        registry=AdapterRegistry();registry.register('rewrite_chapter',LocalProtocolAdapter(delay_seconds=0))
        engine=TaskCoordinator(self.service,registry);self.addCleanup(engine.close)
        options=dict(chapter_id='p1-c3',include_automatic_memories=True,budget_chars=20000);report=self.service.preview_context('p1',options)
        task=engine.prepare('p1',dict(request_id=str(uuid4()),chapter_id='p1-c3',task_type='rewrite_chapter',context_options=options,context_sha256=digest(report['context_text']),parameters=dict(instruction='虚构本地传输',max_output_chars=1000,timeout_ms=1000),expected_revision=report['revision']))['task']
        engine.start('p1',task['id']);engine.wait_idle(3);done=engine.describe('p1',task['id'])['task'];self.assertEqual(done['status'],'succeeded')
        self.state=self.service.get('p1');self.memory('同一事实','AFTER_AUTO_CONFLICT');before=self.db.read_bytes()
        with self.assertRaises(ValueError):engine.adopt('p1',task['id'],dict(candidate_id=done['candidate_id'],adoption_id=str(uuid4()),expected_revision=self.state['revision'],authorize_confirmed=False))
        self.assertEqual(self.db.read_bytes(),before)


class IncrementalMemoryHTTPTests(unittest.TestCase):
    setUp=fixture.MemoryRollupHTTPTests.setUp
    stop=fixture.MemoryRollupHTTPTests.stop
    request=fixture.MemoryRollupHTTPTests.request

    def test_routes_auth_revisions_idempotence_and_capabilities(self):
        route='/api/projects/p1/memory-automation'
        before=self.db.read_bytes();self.assertEqual(self.request('GET',route)[0],200);self.assertEqual(self.db.read_bytes(),before)
        request=dict(action='policy',operation_id=str(uuid4()),expected_revision=1,policy=dict(track_updates=True,auto_select=True))
        self.assertEqual(self.request('POST',route,request,token=False)[0],403);self.assertEqual(self.db.read_bytes(),before)
        self.assertEqual(self.request('POST',route,dict(request,confirm_external=True))[0],422)
        code,result=self.request('POST',route,request);self.assertEqual(code,200,result);self.assertFalse(result['external_execution_authorized'])
        self.assertTrue(self.request('POST',route,request)[1]['idempotent'])
        self.assertEqual(self.request('POST',route,dict(request,operation_id=str(uuid4())))[0],409)
        self.assertEqual(self.request('GET','/api/projects/missing/memory-automation')[0],404)
        self.assertIn(42,self.request('GET','/api/backups/capabilities')[1]['workspace_versions'])
        self.assertIn('backup_v42',self.request('GET','/api/migrations/capabilities')[1]['formats'])


class IncrementalMemoryPaidGateTests(unittest.TestCase):
    from test_chapter_writing_http import ChapterWritingHttpTests as _Fixture
    setUp=_Fixture.setUp
    stop=_Fixture.stop
    request=_Fixture.request

    def test_policy_never_sends_summary_or_accepts_model_proposal(self):
        from test_semantic_summaries import summary_wire
        with summary_wire() as wire:
            state=self.request('GET',self.base)[1]
            code,state=self.request('POST',self.base+'/actions',dict(action='save_chapter',fields=dict(chapter_id=self.cid,content='虚构作者🙂正文。'),expected_revision=state['revision']))
            self.assertEqual(code,200)
            code,enabled=self.request('POST',self.base+'/memory-automation',dict(action='policy',operation_id=str(uuid4()),expected_revision=state['revision'],policy=dict(track_updates=True,auto_select=True)))
            self.assertEqual(code,200);self.assertEqual(wire['calls'],[])
            connection=self.server.providers.save_custom(id=str(uuid4()),name='虚构增量摘要',base_url=wire['url'],protocol='openai-chat',model_id='fiction-c05',api_key='fiction-c05-key',allow_local=True)
            payload=dict(request_id=str(uuid4()),chapter_id=self.cid,expected_revision=enabled['revision'],instruction='只摘要唯一已保存正文',max_output_chars=10000,timeout_ms=3000,model_options=dict(adapter_id='configured-http-v2',connection_id=connection['id'],model_id=connection['model_id'],temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=True,prompt_version='chapter-summary-json-1'))
            code,result=self.request('POST',self.base+'/model-summaries/prepare',payload);self.assertEqual(code,201,result);task=result['task'];route=self.base+'/tasks/'+task['id']
            self.assertEqual(wire['calls'],[]);self.assertEqual(self.request('POST',route+'/execute',{})[0],422)
            self.assertEqual(self.request('POST',route+'/execute',dict(confirm_external=True,request_sha256='0'*64))[0],422);self.assertEqual(wire['calls'],[])
            permission=dict(confirm_external=True,request_sha256=task['frozen']['parameters']['binding']['request_sha256'])
            self.assertEqual(self.request('POST',route+'/execute',permission)[0],202);self.server.task_coordinator.wait_idle(5)
            done=self.request('GET',route)[1];self.assertEqual(done['task']['status'],'succeeded',done);self.assertEqual(len(wire['calls']),1)
            self.assertEqual(self.request('GET',self.base)[1]['memories'],[])
            detail=self.request('GET',self.base+'/model-reviews/'+done['model_reports'][0]['id'])[1]
            self.assertEqual(len(detail['proposals']),1)



if __name__=='__main__':unittest.main()
