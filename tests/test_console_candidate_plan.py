import unittest
from uuid import uuid4
import test_book_ai as book
import test_creative_dialogue as dialogue_fixture


class ConsoleCandidatePlanTests(unittest.TestCase):
    setUp=book.BookAITests.setUp
    connection=book.BookAITests.connection
    options=book.BookAITests.options
    run_task=book.BookAITests.run_task
    dialogue=dialogue_fixture.CreativeDialogueTests.dialogue
    plan_text=dialogue_fixture.CreativeDialogueTests.plan_text
    request=dialogue_fixture.CreativeDialogueTests.request

    def test_candidate_link_is_explicit_and_copies_with_identity_not_permission(self):
        from novel_writer.application.backups import create_backup
        from novel_writer.application.migrations import migrate
        from novel_writer.application.skill_import import SkillLibrary
        from novel_writer.application.service import NovelService
        from novel_writer.storage.sqlite_repository import SQLiteRepository
        from novel_writer.application.console import ConsoleCoordinator
        service=self.service
        service.execute(self.pid,'add_chapter',dict(title='虚构章节'),expected_revision=service.get(self.pid)['revision']);cid=service.get(self.pid)['document']['chapters'][0]['id']
        api,sid=self.dialogue();console=api.console
        with book.supplier(output=self.plan_text()) as wire:
            done=self.run_task(api.prepare(self.pid,self.request(sid,self.connection(wire),'虚构灯塔大纲')))
            candidate=done['latest_candidate']['id'];before=service.get(self.pid)
            suggestion=console.candidate_plan(self.pid,dict(session_id=sid,candidate_id=candidate,chapter_id=cid))
            self.assertEqual(service.get(self.pid),before);self.assertEqual(suggestion['candidate_id'],candidate)
            other=console.create(self.pid,dict(operation_id=str(uuid4()),title='另一个会话'))['id']
            with self.assertRaisesRegex(ValueError,'当前会话'):console.candidate_plan(self.pid,dict(session_id=other,candidate_id=candidate,chapter_id=cid))
            plan=console.describe(self.pid,sid)['plan']
            console.save_plan(self.pid,dict(session_id=sid,steps=suggestion['steps'],expected_plan_revision=plan['revision'],candidate_id=candidate))
            self.assertEqual(service.get(self.pid)['document'],before['document']);self.assertEqual(len(wire['calls']),1)
            view=api.describe(self.pid,sid);self.assertEqual(len(view['turns']),2)
            usage=view['usage'];self.assertEqual(usage['reported_subtotals']['total_tokens'],29);self.assertIsNone(usage['actual_cost'])
            SkillLibrary(self.db);package=self.root/'candidate-plan.nwbak';create_backup(self.db,package)
            target=self.root/'clone.sqlite3';SQLiteRepository(target);SkillLibrary(target)
            result=migrate(package,target,operation_id=str(uuid4()));copy=NovelService(SQLiteRepository(target));pid=result['projects'][0]['new_id'];clone=copy.get(pid)
            refs=[r['id'] for m in clone['console_messages'] for r in m['refs'] if r['kind']=='candidate']
            self.assertEqual(refs,[clone['book_ai_candidates'][0]['id']]);self.assertNotEqual(refs[0],candidate)
            reopened=ConsoleCoordinator(copy,None,None,None);detail=reopened.describe(pid,clone['console_sessions'][0]['id'])
            self.assertEqual(len(detail['plan']['steps']),3);self.assertEqual(copy.get(pid),clone);self.assertEqual(len(wire['calls']),1)


if __name__=='__main__':unittest.main()
