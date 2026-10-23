"""Fictional wire tests for persistent conversation and explicit formal planning."""
import json
from uuid import uuid4
from test_book_ai import BookAITests,supplier
from novel_writer.application.console import ConsoleCoordinator
from novel_writer.application.creative_dialogue import CreativeDialogue
from novel_writer.application.book_creation import seed
from novel_writer.domain.tasks import encode

class CreativeDialogueTests(BookAITests):
 def dialogue(self):
  console=ConsoleCoordinator(self.service,None,None,None);session=console.create(self.pid,dict(operation_id=str(uuid4()),title='虚构大纲对话'));return CreativeDialogue(console,self.ai),session['id']
 def plan_text(self,female=False,volumes=1):
  plan=encode(seed(self.service.get(self.pid),str(uuid4())));plan.update(title='灯塔之谜',creative_idea='海岛寻谜',main_plot='女主守护灯塔' if female else '主角守护灯塔',ending='灯塔重燃',characters=[dict(name='林月' if female else '林舟',role='女主' if female else '主角',personality='坚韧',background='海岛居民',goals=['守护灯塔'],notes='')],volumes=[dict(title='卷'+str(i+1),summary='寻找线索',chapters=[dict(title='灯火'+str(i+1),core_idea='发现线索',objective='推进谜团',story_time='第一夜')]) for i in range(volumes)])
  # A full-plan response must now provide the seven-step planning context.
  plan.update(genre='悬疑',readership='成年读者',target_words=60000,theme='守护与信任',core_conflict='主角守护灯塔与破坏者的冲突',worldbuilding='虚构海岛')
  return json.dumps(dict(reply='已改为女主，并扩成三卷。' if female else '这是第一版全书大纲。',plan=plan),ensure_ascii=False)
 def request(self,session,c,text,**changes):
  request=dict(operation_id=str(uuid4()),session_id=session,text=text,model_options=self.options(c),max_output_chars=50000,timeout_ms=2000);request.update(changes);return request
 def test_two_turn_outline_to_formal_preview_reopen_and_copy(self):
  from novel_writer.application.backups import create_backup,restore_backup
  from novel_writer.application.migrations import migrate
  from novel_writer.application.skill_import import SkillLibrary
  from novel_writer.application.service import NovelService
  from novel_writer.storage.sqlite_repository import SQLiteRepository
  dialogue,session=self.dialogue();before=self.service.get(self.pid)['document']
  with supplier(output=self.plan_text()) as first,supplier(output=self.plan_text(True,3)) as second:
   c=self.connection(first);request=self.request(session,c,'帮我写一份灯塔悬疑小说大纲');frozen=dialogue.prepare(self.pid,request);self.assertEqual(dialogue.prepare(self.pid,request)['task'],frozen['task']);done=self.run_task(frozen);self.assertEqual(done['status'],'succeeded',done['latest_candidate']);self.assertEqual(self.service.get(self.pid)['document'],before)
   c=self.connection(second,identifier=c['id']);next_turn=dialogue.prepare(self.pid,self.request(session,c,'主角改成女主，扩成三卷'));done=self.run_task(next_turn);self.assertEqual(done['status'],'succeeded',done['latest_candidate']);body=second['calls'][0]['body'];self.assertIn('这是第一版全书大纲',json.dumps(body,ensure_ascii=False));self.assertEqual(self.service.get(self.pid)['document'],before)
   accepted=self.accept(done);preview=self.manual.preview(self.pid,dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision'],version_id=accepted['version_id']));self.assertEqual(len(preview['preview']['impact']['chapter_creates']),3);self.assertEqual(self.service.get(self.pid)['document'],before)
   self.manual.decide(self.pid,dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision'],preview_id=preview['preview']['id'],decision='accepted',confirmed=True,create_entities=True,authorize_confirmed_metadata=False));state=self.service.get(self.pid);self.assertEqual(len(state['document']['chapters']),3);self.assertTrue(all(not c['content'] for c in state['document']['chapters']));self.assertEqual(len(dialogue.describe(self.pid,session)['turns']),4)
   reopened=NovelService(SQLiteRepository(self.db));self.assertEqual(reopened.get(self.pid),state)
   SkillLibrary(self.db);package=self.root/'dialogue.nwbak';self.assertEqual(create_backup(self.db,package)['backup_format_version'],51);restored=restore_backup(package,self.root/'dialogue-restore');self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid),state)
   target=self.root/'dialogue-copy.sqlite3';SQLiteRepository(target);SkillLibrary(target);result=migrate(package,target,operation_id=str(uuid4()),project_ids=[self.pid]);clone=NovelService(SQLiteRepository(target)).get(result['projects'][0]['new_id']);self.assertEqual(len(clone['book_ai_tasks']),2);self.assertTrue(all(ref['id'] in {t['id'] for t in clone['book_ai_tasks']} for m in clone['console_messages'] for ref in m['refs'] if ref['kind']=='task'))
   self.assertEqual(len(first['calls'])+len(second['calls']),2)
 def test_disabled_and_cancelled_turns_preserve_input_and_never_write_formal(self):
  dialogue,session=self.dialogue();before=self.service.get(self.pid)['document']
  with supplier(output=self.plan_text(),slow=True) as wire:
   c=self.connection(wire);request=self.request(session,c,'保留这条创作要求');self.ai.adapter.enabled=False
   with self.assertRaises(ValueError):dialogue.prepare(self.pid,request)
   self.assertEqual(dialogue.describe(self.pid,session)['turns'][0]['text'],request['text']);self.assertEqual(wire['calls'],[]);self.ai.adapter.enabled=True
   task=dialogue.prepare(self.pid,request)['task'];self.ai.start(self.pid,task['id'],dict(confirm_external=True,request_sha256=task['binding']['request_sha256']));self.assertTrue(wire['seen'].wait(2));self.ai.cancel(self.pid,task['id']);wire['release'].set();self.shared.wait_idle(4);self.assertEqual(self.ai.describe(self.pid,task['id'])['status'],'cancelled');self.assertEqual(self.service.get(self.pid)['document'],before);self.assertEqual(len(wire['calls']),1)
