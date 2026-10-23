"""All existing C04 producers participate without a second manuscript writer."""
import json,unittest
from uuid import uuid4
from novel_writer.application.comparisons import ComparisonCoordinator
from test_chapter_writing import ChapterWritingTests as WritingFixture
from test_chapter_planning import ChapterPlanningTests as PlanningFixture
from test_book_ai import supplier

class WritingSourceTests(unittest.TestCase):
    def check_backup_copy(self,f,pid):
        from novel_writer.application.backups import create_backup,restore_backup
        from novel_writer.application.migrations import migrate
        from novel_writer.application.skill_import import SkillLibrary
        from novel_writer.application.service import NovelService
        from novel_writer.storage.sqlite_repository import SQLiteRepository
        from novel_writer.application.tasks import TaskCoordinator
        from novel_writer.application.task_protocol import AdapterRegistry
        original=f.service.get(pid);SkillLibrary(f.db);package=f.root/'source-comparison.nwbak';create_backup(f.db,package)
        restored=restore_backup(package,f.root/'source-restored');self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(pid),original)
        target=f.root/'source-copy.sqlite3';SQLiteRepository(target);SkillLibrary(target);result=migrate(package,target,operation_id=str(uuid4()));newpid=result['projects'][0]['new_id'];service=NovelService(SQLiteRepository(target));parent=TaskCoordinator(service,AdapterRegistry());self.addCleanup(parent.close);clone=service.get(newpid)
        self.assertEqual(len(clone['comparison_experiments']),1);self.assertEqual(len(clone['comparison_scores']),2);self.assertEqual(len(clone['comparison_choices']),len(original['comparison_choices']))
        e=clone['comparison_experiments'][0];arena=ComparisonCoordinator(service,parent);self.assertTrue(arena.blind(newpid,e['id'])['ready']);self.assertTrue(arena.blind(newpid,e['id'])['revealed']);self.assertTrue(all(c['submitted'] for c in arena.setup(newpid,e['id'])['configurations']))
    def execute(self,f,parent,pid,prepared,kind):
        arena=ComparisonCoordinator(f.service,parent);identifier=str(uuid4())
        arena.create(pid,dict(experiment_id=identifier,title='虚构同输入候选',task_kind=kind,task_ids=[v['task']['id'] for v in prepared],expected_revision=f.service.get(pid)['revision']))
        for c in arena.setup(pid,identifier)['configurations']:
            arena.execute(pid,identifier,c['configuration_id'],dict(confirm_external=True,request_sha256=c['request_sha256']));parent.wait_idle(6)
        view=arena.blind(pid,identifier)
        for c in view['candidates']:
            arena.score(pid,identifier,dict(operation_id=str(uuid4()),side=c['side'],rating=4 if c['status']=='succeeded' else None,outcome='scored' if c['status']=='succeeded' else 'unscorable',notes='虚构评分',expected_revision=f.service.get(pid)['revision']))
        arena.reveal(pid,identifier,dict(operation_id=str(uuid4()),expected_revision=f.service.get(pid)['revision']))
        return arena,identifier,view
    def test_draft_and_continuation_same_input_and_manual_adoption(self):
        for mode in ('draft','continue'):
            with self.subTest(mode=mode):
                f=WritingFixture();f.setUp();self.addCleanup(f.doCleanups)
                if mode=='continue':f.action('save_chapter',dict(chapter_id=f.cid,content='原文😀e\u0301\r\n'))
                with supplier(output='门外只有虚构潮声。') as wire:
                    conn=f.connection(wire);prepared=[f.prepare(conn,mode=mode) for _ in range(2)];before=f.service.get(f.pid)['document']
                    arena,identifier,view=self.execute(f,f.engine,f.pid,prepared,'chapter_writing');self.assertEqual({v['status'] for v in view['candidates']},{'succeeded'})
                    choice=arena.choose(f.pid,identifier,dict(operation_id=str(uuid4()),side='A',action='open_candidate',name='',expected_revision=f.service.get(f.pid)['revision']))
                    self.assertEqual(f.service.get(f.pid)['document'],before);done=f.engine.describe(f.pid,choice['task_id']);f.engine.adopt(f.pid,choice['task_id'],f.adoption(done));self.assertEqual(f.service.get(f.pid)['document']['chapters'][0]['content'],before['chapters'][0]['content']+'门外只有虚构潮声。');self.assertEqual(len(wire['calls']),2)
                    self.check_backup_copy(f,f.pid);self.assertEqual(len(wire['calls']),2)
    def test_brainstorm_and_outline_and_invalid_json_failure(self):
        for mode in ('brainstorm','outline','invalid'):
            with self.subTest(mode=mode):
                f=PlanningFixture();f.setUp();self.addCleanup(f.doCleanups)
                output=json.dumps(dict(idea='虚构候选IDEA'),ensure_ascii=False) if mode=='brainstorm' else json.dumps(dict(core_idea='虚构细纲',objective='敲门',story_time='清晨',character_ids=[f.chid],scenes=[dict(order=1,summary='门前停步',character_ids=[f.chid],location='灯塔',story_time='清晨')]),ensure_ascii=False)
                if mode=='invalid':output='不是有效JSON'
                with supplier(output=output) as wire:
                    conn=f.connection(wire);prepared=[f.prepare(conn,mode='brainstorm' if mode=='invalid' else mode) for _ in range(2)];before=f.service.get(f.pid)['document']
                    arena,identifier,view=self.execute(f,f.shared,f.pid,prepared,'chapter_planning');self.assertEqual(f.service.get(f.pid)['document'],before)
                    self.assertEqual({v['status'] for v in view['candidates']},{'failed' if mode=='invalid' else 'succeeded'})
                    if mode!='invalid':
                        choice=arena.choose(f.pid,identifier,dict(operation_id=str(uuid4()),side='B',action='open_candidate',name='',expected_revision=f.service.get(f.pid)['revision']))
                        f.accept(f.planning.describe(f.pid,choice['task_id']));self.assertEqual(f.service.get(f.pid)['document']['chapters'],before['chapters'])
                    self.assertEqual(len(wire['calls']),2)
                    self.check_backup_copy(f,f.pid);self.assertEqual(len(wire['calls']),2)

if __name__=='__main__':unittest.main()
