"""Phase-two fictional author lifecycle/range persistence, no external providers."""
from copy import deepcopy
from contextlib import closing
from pathlib import Path
from uuid import uuid4
import json
import sqlite3
import tempfile
import threading
import unittest
from http.client import HTTPConnection

from novel_writer.application.service import NovelService
from novel_writer.application.author_scope import preview,describe
from novel_writer.application import chapters
from novel_writer.application.backups import create_backup,restore_backup
from novel_writer.application.migrations import migrate
from novel_writer.application.skill_import import SkillLibrary
from novel_writer.domain.author_scope import active_locks,digest,project_state,validate_state
from novel_writer.storage.json_codec import document_from_dict,document_to_dict
from novel_writer.storage.sqlite_repository import SQLiteRepository,ConflictError


class AuthorScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='fiction-author-scope-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=self.root/'fiction.sqlite3';self.repo=SQLiteRepository(self.db)
        SkillLibrary(self.db);self.service=NovelService(self.repo)
        self.state=self.service.create(title='虚构范围锁书');self.pid=self.state['document']['project']['id']
        self.act('add_chapter',dict(title='虚构第一章'));self.cid=self.state['document']['chapters'][0]['id']
        self.body='前言😀e\u0301\r\n受保护的原文🧭。\n结尾  '
        self.act('save_chapter',dict(chapter_id=self.cid,content=self.body))

    def act(self,action,fields):
        self.state=self.service.execute(self.pid,action,fields,expected_revision=self.state['revision']);return self.state

    def control(self,action,**fields):
        return self.act(action,dict(operation_id=str(uuid4()),confirmed=True,**fields))

    def lock(self,start=None,end=None):
        body=self.state['document']['chapters'][0]['content']
        start=body.index('受保护') if start is None else start;end=start+len('受保护的原文🧭。') if end is None else end
        chapter=self.state['document']['chapters'][0]
        self.control('lock_body_range',chapter_id=self.cid,version_id=chapter['current_version_id'],body_sha256=digest(body),start=start,end=end,text_sha256=digest(body[start:end]))
        return list(active_locks(self.state).values())[-1]

    def unchanged(self,before,operation,error=ValueError):
        with self.assertRaises(error):operation()
        self.assertEqual(self.repo.get(self.pid),before)
        with closing(sqlite3.connect(self.db)) as db:self.assertEqual(db.execute('SELECT count(*) FROM project_snapshots WHERE project_id=?',(self.pid,)).fetchone()[0],before['revision'])

    def test_lifecycle_preview_confirmation_archive_trash_restore_and_reopen(self):
        before=self.db.read_bytes();impact=preview(self.state,'archive');self.assertFalse(impact['physical_deletion']);self.assertEqual(impact['chapters'],1);self.assertEqual(before,self.db.read_bytes())
        original=deepcopy(self.state['document']);lock=self.lock()
        for action,expected in [('archive_project','archived'),('trash_project','deleted'),('restore_project','archived'),('restore_project','active')]:
            before=deepcopy(self.state)
            self.unchanged(before,lambda:self.control(action,confirm_title='错误书名'))
            self.control(action,confirm_title='虚构范围锁书')
            self.assertEqual(project_state(self.state),expected);self.assertEqual(self.state['document'],original)
            self.assertEqual(active_locks(self.state)[lock['lock_id']],lock)
            self.assertEqual(self.repo.list_projects()[0]['author_state'],expected)
            self.assertEqual(NovelService(SQLiteRepository(self.db)).get(self.pid),self.state)
            if expected!='active':self.unchanged(deepcopy(self.state),lambda:self.act('save_chapter',dict(chapter_id=self.cid,content='禁止写入')))
        self.act('save_chapter',dict(chapter_id=self.cid,content=self.body+'恢复继续'))

    def test_lock_unicode_outside_save_rebases_version_and_survives_disk_reopen(self):
        lock=self.lock();before=deepcopy(self.state)
        self.act('save_chapter',dict(chapter_id=self.cid,content='新增😀\n'+self.body+'尾部'))
        current=active_locks(self.state)[lock['lock_id']]
        self.assertEqual((current['start'],current['end']),(lock['start']+4,lock['end']+4))
        self.assertNotEqual(current['version_id'],lock['version_id']);self.assertEqual(current['text_sha256'],lock['text_sha256'])
        self.assertEqual(self.state['author_scope_events'][:-1],before['author_scope_events']);validate_state(self.state)
        self.assertEqual(SQLiteRepository(self.db).get(self.pid),self.state)

    def test_overlapping_body_mutations_and_history_restore_are_atomic(self):
        initial_version=self.state['document']['chapters'][0]['current_version_id']
        self.act('save_chapter',dict(chapter_id=self.cid,content=self.body.replace('受保护','最新保护')))
        self.body=self.state['document']['chapters'][0]['content'];start=self.body.index('最新保护');self.lock(start,start+4)
        before=deepcopy(self.state)
        for body in (self.body.replace('最新保护','变化'),self.body[:start]+self.body[start+4:],self.body.replace('e\u0301','é').replace('最新保护','变化')):
            self.unchanged(before,lambda:self.act('save_chapter',dict(chapter_id=self.cid,content=body)))
        self.unchanged(before,lambda:self.act('restore_chapter',dict(chapter_id=self.cid,version_id=initial_version)))

    def test_safe_history_restore_adds_new_version_and_rebinds_lock(self):
        self.lock();version=self.state['document']['chapters'][0]['current_version_id']
        self.act('save_chapter',dict(chapter_id=self.cid,content=self.body+'追加'))
        old=self.state['document']['chapters'][0]['current_version_id'];count=len(self.state['document']['versions'])
        self.act('restore_chapter',dict(chapter_id=self.cid,version_id=version))
        self.assertEqual(self.state['document']['chapters'][0]['content'],self.body)
        self.assertEqual(len(self.state['document']['versions']),count+1)
        self.assertNotEqual(active_locks(self.state).popitem()[1]['version_id'],old)

    def test_repeated_protected_text_cannot_be_silently_relocated_to_another_occurrence(self):
        unit='abcLOCKxyz';self.body=unit+unit
        self.act('save_chapter',dict(chapter_id=self.cid,content=self.body));self.lock(0,len(unit));before=deepcopy(self.state)
        self.unchanged(before,lambda:self.act('save_chapter',dict(chapter_id=self.cid,content='abcEDITxyz'+unit)))
        self.act('save_chapter',dict(chapter_id=self.cid,content='前缀😀'+self.body))
        lock=next(iter(active_locks(self.state).values()));self.assertEqual((lock['start'],lock['end']),(3,3+len(unit)))

    def test_restored_legacy_archive_can_update_project_metadata_without_rewriting_event_origin(self):
        from novel_writer.application import versions
        document=document_from_dict(self.state['document']);document.project.status='archived'
        versions.record(document,'project',document.project,'虚构旧版已归档状态')
        self.state['document']=document_to_dict(document);self.state=self.repo.save(self.state,expected_revision=self.state['revision'])
        self.control('restore_project',confirm_title='虚构范围锁书')
        self.act('save_project',dict(summary='恢复后继续创作'))
        document=document_from_dict(self.state['document']);document.project.status='writing'
        versions.record(document,'project',document.project,'虚构恢复后进度元数据')
        self.state['document']=document_to_dict(document);self.state=self.repo.save(self.state,expected_revision=self.state['revision'])
        self.assertEqual(project_state(self.state),'active');self.assertEqual(SQLiteRepository(self.db).get(self.pid),self.state)

    def test_invalid_ranges_hash_stale_source_and_overlap_refuse_zero_write(self):
        chapter=self.state['document']['chapters'][0];base=dict(operation_id=str(uuid4()),confirmed=True,chapter_id=self.cid,version_id=chapter['current_version_id'],body_sha256=digest(self.body),start=0,end=2,text_sha256=digest(self.body[:2]))
        for patch in (dict(start=True),dict(start=-1),dict(end=len(self.body)+1),dict(end=0),dict(body_sha256='0'*64),dict(version_id=str(uuid4())),dict(text_sha256='0'*64),dict(extra=True),dict(confirmed=False)):
            self.unchanged(deepcopy(self.state),lambda:self.act('lock_body_range',dict(base,**patch)))
        lock=self.lock();self.unchanged(deepcopy(self.state),lambda:self.lock(lock['start'],lock['end']))

    def test_unlock_is_fresh_revision_bound_separate_and_not_replayed_permission(self):
        lock=self.lock();old=deepcopy(self.state);fields=dict(operation_id=str(uuid4()),confirmed=True,lock_id=lock['lock_id'],version_id=lock['version_id'])
        self.unchanged(old,lambda:self.act('unlock_body_range',dict(fields,confirmed=False)))
        self.act('save_chapter',dict(chapter_id=self.cid,content=self.body+'尾'))
        self.unchanged(deepcopy(self.state),lambda:self.act('unlock_body_range',fields))
        lock=active_locks(self.state)[lock['lock_id']];fields.update(version_id=lock['version_id'])
        self.act('unlock_body_range',fields)
        self.unchanged(deepcopy(self.state),lambda:self.act('unlock_body_range',fields))
        self.assertEqual(active_locks(self.state),{});self.lock()
        self.unchanged(deepcopy(self.state),lambda:self.act('save_chapter',dict(chapter_id=self.cid,content='不能继承旧解锁')))

    def test_atomic_adopter_rolls_back_body_and_receipt_together(self):
        self.lock();before=deepcopy(self.state)
        def adopt(state):
            document=document_from_dict(state['document']);chapters.save(document,dict(chapter_id=self.cid,content=self.body.replace('受保护','擅自替换')))
            state['document']=document_to_dict(document);state['writing_rules']='虚构采纳收据同时修改';return state,{'adopted':True}
        self.unchanged(before,lambda:self.repo.atomic(self.pid,adopt))
        def allowed(state):
            document=document_from_dict(state['document']);chapters.save(document,dict(chapter_id=self.cid,content=self.body+'明确采纳尾部'))
            state['document']=document_to_dict(document);return state,{'adopted':True}
        self.assertEqual(self.repo.atomic(self.pid,allowed),{'adopted':True});self.state=self.repo.get(self.pid);self.assertEqual(len(active_locks(self.state)),1)

    def test_raw_control_and_body_change_cannot_be_combined_or_history_rewritten(self):
        lock=self.lock();before=deepcopy(self.state)
        raw=deepcopy(before);raw['author_scope_events'][0]['data']['start']=0
        self.unchanged(before,lambda:self.repo.save(raw,expected_revision=before['revision']))
        raw=deepcopy(before);raw['author_scope_events'].append(dict(id=str(uuid4()),project_id=self.pid,operation_id=str(uuid4()),kind='unlock',data=dict(lock_id=lock['lock_id'],version_id=lock['version_id']),created_at=before['author_scope_events'][0]['created_at']));raw['worldbuilding']='混合修改'
        self.unchanged(before,lambda:self.repo.save(raw,expected_revision=before['revision']))

    def test_operation_identity_is_not_reused_across_books(self):
        operation=str(uuid4());fields=dict(operation_id=operation,confirmed=True,confirm_title='虚构范围锁书')
        self.act('archive_project',fields)
        other=self.service.create(title='虚构范围锁书');pid=other['document']['project']['id']
        with self.assertRaises(ConflictError):self.service.execute(pid,'archive_project',fields,expected_revision=other['revision'])
        self.assertEqual(self.repo.get(pid),other)

    def test_late_sql_failure_never_primes_uncommitted_cache_and_return_is_isolated(self):
        before=deepcopy(self.state)
        with closing(sqlite3.connect(self.db)) as db,db:
            db.execute("CREATE TRIGGER fictional_commit_failure AFTER INSERT ON project_snapshots WHEN NEW.revision="+str(before['revision']+1)+" BEGIN SELECT RAISE(ABORT,'fictional late disk failure'); END")
        self.unchanged(before,lambda:self.act('save_chapter',dict(chapter_id=self.cid,content=self.body+'不得提交')),sqlite3.Error)
        with closing(sqlite3.connect(self.db)) as db,db:db.execute('DROP TRIGGER fictional_commit_failure')
        self.act('save_chapter',dict(chapter_id=self.cid,content=self.body+'正常提交'))
        revision=self.state['revision'];self.state['document']['chapters'][0]['content']='返回值不能污染缓存'
        reopened=self.repo.get(self.pid);self.assertEqual(reopened['revision'],revision);self.assertEqual(reopened['document']['chapters'][0]['content'],self.body+'正常提交')

    def test_backup_restore_and_copy_preserve_active_locks_without_unlock_grant(self):
        lock=self.lock();self.act('save_chapter',dict(chapter_id=self.cid,content='外侧😀'+self.body));self.control('archive_project',confirm_title='虚构范围锁书')
        source_bytes=self.db.read_bytes();package=self.root/'fiction.nwbak';create_backup(self.db,package)
        recovered=restore_backup(package,self.root/'restored');restored=SQLiteRepository(recovered['database_path']).get(self.pid)
        self.assertEqual(restored,self.state);self.assertEqual(self.db.read_bytes(),source_bytes)
        target=self.root/'copied.sqlite3';SQLiteRepository(target);SkillLibrary(target)
        result=migrate(self.db,target,operation_id=str(uuid4()),project_ids=[self.pid]);newid=result['projects'][0]['new_id'];repo=SQLiteRepository(target);copied=repo.get(newid)
        self.assertEqual(project_state(copied),'archived');newlock=next(iter(active_locks(copied).values()))
        self.assertNotEqual(newlock['lock_id'],lock['lock_id']);self.assertNotEqual(newlock['chapter_id'],self.cid);self.assertEqual(newlock['text_sha256'],lock['text_sha256'])
        self.assertEqual(describe(copied)['unlock_permission'],describe(self.state)['unlock_permission'])
        service=NovelService(repo);copied=service.execute(newid,'restore_project',dict(operation_id=str(uuid4()),confirmed=True,confirm_title='虚构范围锁书'),expected_revision=copied['revision'])
        with self.assertRaises(ValueError):service.execute(newid,'save_chapter',dict(chapter_id=newlock['chapter_id'],content='复制不能隐式解锁'),expected_revision=copied['revision'])
        self.assertEqual(self.db.read_bytes(),source_bytes)


class AuthorScopeHttpTests(unittest.TestCase):
    def test_preview_no_write_token_origin_confirmation_and_static_asset(self):
        from novel_writer.ui.server import create_server
        with tempfile.TemporaryDirectory(prefix='fiction-scope-http-') as directory:
            root=Path(directory);server=create_server(root/'fiction.sqlite3',port=0,offline=True,provider_path=root/'unused.dpapi',drafts_path=root/'drafts')
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                state=server.service.create(title='虚构HTTP整书');pid=state['document']['project']['id'];db=server.service.repository.path
                def request(method,path,value=None,token=True,origin=None):
                    connection=HTTPConnection('127.0.0.1',server.server_port,timeout=10);headers={'Content-Type':'application/json'}
                    if token:headers['X-Novel-Token']=server.token
                    if origin:headers['Origin']=origin
                    connection.request(method,path,None if value is None else json.dumps(value).encode(),headers);response=connection.getresponse();code=response.status;body=response.read();connection.close();return code,body
                before=db.read_bytes();base='/api/projects/'+pid
                self.assertEqual(request('GET',base+'/author-scope/preview/archive')[0],200);self.assertEqual(db.read_bytes(),before)
                self.assertEqual(request('GET','/author_scope.js')[0],200)
                payload=dict(action='archive_project',expected_revision=state['revision'],fields=dict(operation_id=str(uuid4()),confirmed=True,confirm_title='虚构HTTP整书'))
                self.assertEqual(request('POST',base+'/actions',payload,token=False)[0],403)
                self.assertEqual(request('POST',base+'/actions',payload,origin='https://invalid.example')[0],403);self.assertEqual(db.read_bytes(),before)
                self.assertEqual(request('POST',base+'/actions',payload)[0],200)
                self.assertEqual(request('POST',base+'/actions',payload)[0],409)
                self.assertEqual(json.loads(request('GET',base+'/author-scope')[1])['project_state'],'archived')
            finally:server.shutdown();server.server_close();thread.join()


class SceneRangeLockTests(unittest.TestCase):
    # Reuse the existing real loopback supplier setup, never a remote provider.
    import test_scene_expansion as fixtures
    setUp=fixtures.SceneExpansionTests.setUp
    action=fixtures.SceneExpansionTests.action
    connection=fixtures.SceneExpansionTests.connection
    options=fixtures.SceneExpansionTests.options
    source=fixtures.SceneExpansionTests.source
    prepare=fixtures.SceneExpansionTests.prepare
    execute=fixtures.SceneExpansionTests.execute
    review=fixtures.SceneExpansionTests.review
    accept=fixtures.SceneExpansionTests.accept

    def lock(self):
        chapter=self.service.get(self.pid)['document']['chapters'][0];start=self.original.index('门外');end=start+len('门外有雾。')
        self.action('lock_body_range',dict(operation_id=str(uuid4()),confirmed=True,chapter_id=self.cid,version_id=chapter['current_version_id'],body_sha256=digest(self.original),start=start,end=end,text_sha256=digest(self.original[start:end])))
        return start,end

    def test_exact_selection_ai_overlap_rejected_without_body_receipt_or_history_write(self):
        start,end=self.lock()
        with self.fixtures.supplier(output='门外的原文被改写。') as wire:
            done=self.execute(self.prepare(self.connection(wire),source=self.source('selection',scene_order=None,selection_start=start,selection_end=end)));review=self.review(done);before=self.service.get(self.pid)
            with self.assertRaisesRegex(ValueError,'locked_body_range_changed'):self.accept(done,review)
            self.assertEqual(self.service.get(self.pid),before);self.assertEqual(len(wire['calls']),1)

    def test_exact_ai_append_outside_lock_is_adopted_and_version_rebased(self):
        self.lock()
        with self.fixtures.supplier(output='作者明确采纳的新尾声。') as wire:
            done=self.execute(self.prepare(self.connection(wire)));review=self.review(done);self.accept(done,review)
            state=self.service.get(self.pid);self.assertEqual(state['document']['chapters'][0]['content'],self.original+'作者明确采纳的新尾声。')
            self.assertEqual(next(iter(active_locks(state).values()))['version_id'],state['document']['chapters'][0]['current_version_id']);self.assertEqual(len(wire['calls']),1)

    def test_archived_book_blocks_prepared_model_dispatch_before_loopback_wire(self):
        with self.fixtures.supplier(output='不会发送的虚构输出。') as wire:
            prepared=self.prepare(self.connection(wire));title=self.service.get(self.pid)['document']['project']['title']
            self.action('archive_project',dict(operation_id=str(uuid4()),confirmed=True,confirm_title=title));before=self.service.get(self.pid)
            with self.assertRaises(ValueError):self.execute(prepared)
            self.assertEqual(wire['calls'],[]);self.assertEqual(self.service.get(self.pid),before)


class WholeChapterRangeLockTests(unittest.TestCase):
    import test_s4a_tasks as fixtures
    setUp=fixtures.TaskTests.setUp
    close=fixtures.TaskTests.close
    coordinator=fixtures.TaskTests.coordinator
    prepare=fixtures.TaskTests.prepare
    wait=fixtures.TaskTests.wait
    succeed=fixtures.TaskTests.succeed
    adopt=fixtures.TaskTests.adopt
    save=fixtures.TaskTests.save

    def test_whole_chapter_candidate_cannot_replace_protected_body(self):
        from novel_writer.application.task_protocol import AdapterResult
        class LocalReplacement:
            adapter_id='local-protocol-demo-v1'
            def run(self,call,token):return AdapterResult(task_id=call.task_id,attempt_id=call.attempt_id,capability=call.capability,output_text='整章替换不能绕过保护',complete=True)
        self.engine=self.coordinator(LocalReplacement())
        state=self.service.get('p1');chapter=next(v for v in state['document']['chapters'] if v['id']=='p1-c5');body=chapter['content']
        self.save('lock_body_range',operation_id=str(uuid4()),confirmed=True,chapter_id=chapter['id'],version_id=chapter['current_version_id'],body_sha256=digest(body),start=0,end=len(body),text_sha256=digest(body))
        done=self.succeed();before=self.service.get('p1')
        with self.assertRaisesRegex(ValueError,'locked_body_range_changed'):self.adopt(done)
        self.assertEqual(self.service.get('p1'),before)


class LocalEditRangeLockTests(unittest.TestCase):
    import test_s5b_knowledge as fixtures
    setUp=fixtures.KnowledgeTests.setUp
    cmd=fixtures.KnowledgeTests.cmd
    save=fixtures.KnowledgeTests.save
    duplicate=fixtures.KnowledgeTests.duplicate
    edit=fixtures.KnowledgeTests.edit

    def test_duplicate_exact_adoption_cannot_delete_locked_span(self):
        proposal=self.edit();state=self.service.get('p1');chapter=next(v for v in state['document']['chapters'] if v['id']==proposal['chapter_id']);start,end=proposal['start'],proposal['end']
        self.save('lock_body_range',operation_id=str(uuid4()),confirmed=True,chapter_id=chapter['id'],version_id=chapter['current_version_id'],body_sha256=digest(chapter['content']),start=start,end=end,text_sha256=digest(chapter['content'][start:end]))
        before=self.service.get('p1')
        with self.assertRaisesRegex(ValueError,'locked_body_range_changed'):self.cmd('decide_edit',proposal_id=proposal['id'],proposal_revision=proposal['revision'],decision='accepted',authorize_confirmed=True)
        self.assertEqual(self.service.get('p1'),before)


if __name__=='__main__':unittest.main()
