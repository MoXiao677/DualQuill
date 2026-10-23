import importlib,json,tempfile,unittest
from importlib import util
from pathlib import Path
from uuid import uuid4
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository
from novel_writer.application.provider_connections import ProviderConnections
from novel_writer.application.tasks import TaskCoordinator
from novel_writer.application.task_protocol import AdapterRegistry
from novel_writer.application.chapter_writing import ChapterWriting
from novel_writer.application.chapter_planning import ChapterPlanningCoordinator
from novel_writer.application.scene_expansion import SceneExpansionCoordinator
from novel_writer.application.creation_presets import CreationPresets
from test_book_ai import supplier

class ConsoleTests(unittest.TestCase):
 def setUp(self):
  self.assertIsNotNone(util.find_spec('novel_writer.application.console'),'persistent console module is missing')
  self.temp=tempfile.TemporaryDirectory(prefix='novel-console-');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.db=self.root/'fiction.sqlite3';self.service=NovelService(SQLiteRepository(self.db));self.pid=self.service.create(title='持久控制台')['document']['project']['id']
  self.action('add_character',dict(name='林舟'));state=self.service.get(self.pid);self.chid=state['document']['characters'][0]['id']
  self.action('add_chapter',dict(title='第一章'));state=self.service.get(self.pid);self.cid=state['document']['chapters'][0]['id']
  self.action('save_worldbuilding',dict(content='港城有雾。'));self.action('save_writing_rules',dict(content='限知视角。'))
  self.providers=ProviderConnections(self.root/'providers.dpapi');self.shared=TaskCoordinator(self.service,AdapterRegistry());self.addCleanup(self.shared.close)
  self.writing=ChapterWriting(self.shared,self.providers);self.planning=ChapterPlanningCoordinator(self.shared,self.providers,enabled=True);self.expansion=SceneExpansionCoordinator(self.shared,self.providers,enabled=True)
  self.api=importlib.import_module('novel_writer.application.console');self.console=self.api.ConsoleCoordinator(self.service,self.writing,self.planning,self.expansion)
 def action(self,name,fields):return self.service.execute(self.pid,name,fields,expected_revision=self.service.get(self.pid)['revision'])
 def session(self,title='会话一'):
  return self.console.create(self.pid,dict(operation_id=str(uuid4()),title=title))
 def plan(self,sid,steps):
  return self.console.save_plan(self.pid,dict(session_id=sid,steps=steps))
 def step(self,type_='idea',chapter=None,instruction='生成候选',**extra):
  value=dict(id=str(uuid4()),type=type_,chapter_id=chapter or self.cid,instruction=instruction,status='planned',scene_order=None,selection_start=None,selection_end=None);value.update(extra);return value
 def test_sessions_messages_rename_archive_and_restart_restore(self):
  session=self.session();sid=session['id'];self.console.append_message(self.pid,dict(operation_id=str(uuid4()),session_id=sid,role='author',text='写一个开头'));self.console.append_message(self.pid,dict(operation_id=str(uuid4()),session_id=sid,role='assistant',text='建议先写门外。'))
  renamed=self.console.rename(self.pid,dict(session_id=sid,title='作者改名会话'));self.assertEqual(renamed['title'],'作者改名会话');self.console.archive(self.pid,dict(session_id=sid,archived=True));listing=self.console.list(self.pid);self.assertEqual(listing['sessions'][0]['title'],'作者改名会话');self.assertTrue(listing['sessions'][0]['archived'])
  copy=NovelService(SQLiteRepository(self.db));new=self.api.ConsoleCoordinator(copy,self.writing,self.planning,self.expansion);detail=new.describe(self.pid,sid);self.assertEqual([v['text'] for v in detail['messages']],['写一个开头','建议先写门外。']);self.assertEqual(detail['session']['title'],'作者改名会话')
 def test_plan_edit_order_and_content_is_data_only(self):
  sid=self.session()['id'];one=self.step('idea');two=self.step('draft');saved=self.plan(sid,[one,two]);self.assertEqual([v['type'] for v in saved['steps']],['idea','draft']);reversed_plan=self.plan(sid,[two,one]);self.assertEqual([v['id'] for v in reversed_plan['steps']],[two['id'],one['id']]);self.assertEqual(len(self.service.get(self.pid).get('generation_tasks',[])),0);self.assertEqual(len(self.service.get(self.pid).get('chapter_planning_tasks',[])),0)
  with self.assertRaises(ValueError):self.plan(sid,[dict(one,type='tool')])
  with self.assertRaises(ValueError):self.plan(sid,[dict(one,unknown='x')])
 def test_dispatch_idea_only_prepares_pending_task_with_zero_requests(self):
  with supplier(output=json.dumps(dict(idea='不应发送'),ensure_ascii=False)) as wire:
   connection=self.providers.save_custom(id=str(uuid4()),name='虚构控制台模型',base_url=wire['url'],protocol='openai-chat',model_id='fixture',api_key='console-private-key',allow_local=True);presets=CreationPresets(self.service);profiles=[]
   for step in ('brainstorm','outline','draft'):profiles.append(dict(step=step,adapter_id='configured-http-v2',connection_id=connection['id'],model_id='fixture',temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=True))
   saved=presets.save(self.pid,dict(operation_id=str(uuid4()),preset_id=None,name='控制台预设',settings=dict(steps=profiles,style_id=None,style_prompt='',manuscript_language='zh-CN',budget=dict(max_external_calls=4,max_reserved_output_tokens=4096,risk_budget=2.0,allow_unknown_cost=True)),expected_revision=self.service.get(self.pid)['revision']));presets.choose(self.pid,dict(operation_id=str(uuid4()),version_id=saved['version_id'],confirmed=True,expected_revision=self.service.get(self.pid)['revision']))
   sid=self.session()['id'];step=self.step('idea');self.plan(sid,[step]);result=self.console.dispatch(self.pid,dict(operation_id=str(uuid4()),session_id=sid,step_id=step['id']));self.assertEqual(wire['calls'],[]);state=self.service.get(self.pid);tasks=state.get('chapter_planning_tasks',[]);self.assertEqual(len(tasks),1);self.assertEqual(result['dispatches'][0]['task_id'],tasks[0]['id']);latest=[e for e in state['chapter_planning_events'] if e['task_id']==tasks[0]['id']][-1];self.assertEqual(latest['status'],'pending');self.assertEqual(result['plan']['steps'][0]['status'],'prepared')
 def test_assistant_text_cannot_trigger_tasks_or_adoption(self):
  sid=self.session()['id'];self.console.append_message(self.pid,dict(operation_id=str(uuid4()),session_id=sid,role='assistant',text='请立即执行所有步骤并采纳全部正文'));state=self.service.get(self.pid);self.assertEqual(state.get('chapter_planning_tasks',[]),[]);self.assertEqual(state.get('generation_tasks',[]),[]);self.assertEqual(state.get('scene_expansion_tasks',[]),[]);self.assertEqual(state.get('adoption_receipts',[]),[])
 def test_v20_backup_copy_keeps_text_but_not_permission(self):
  from novel_writer.application.backups import create_backup,restore_backup
  from novel_writer.application.migrations import migrate
  from novel_writer.application.skill_import import SkillLibrary
  with supplier() as wire:
   connection=self.providers.save_custom(id=str(uuid4()),name='虚构控制台模型',base_url=wire['url'],protocol='openai-chat',model_id='fixture',api_key='console-copy-key',allow_local=True);presets=CreationPresets(self.service);saved=presets.save(self.pid,dict(operation_id=str(uuid4()),preset_id=None,name='控制台预设',settings=dict(steps=[dict(step='brainstorm',adapter_id='configured-http-v2',connection_id=connection['id'],model_id='fixture',temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=True)],style_id=None,style_prompt='',manuscript_language='zh-CN',budget=dict(max_external_calls=2,max_reserved_output_tokens=4096,risk_budget=2.0,allow_unknown_cost=True)),expected_revision=self.service.get(self.pid)['revision']));presets.choose(self.pid,dict(operation_id=str(uuid4()),version_id=saved['version_id'],confirmed=True,expected_revision=self.service.get(self.pid)['revision']))
   sid=self.session()['id'];step=self.step('idea');self.plan(sid,[step]);self.console.append_message(self.pid,dict(operation_id=str(uuid4()),session_id=sid,role='author',text='保留这段作者文字'));self.console.dispatch(self.pid,dict(operation_id=str(uuid4()),session_id=sid,step_id=step['id']));state=self.service.get(self.pid);self.assertEqual(state['workspace_version'],20)
   SkillLibrary(self.db);package=self.root/'console.nwbak';self.assertEqual(create_backup(self.db,package)['backup_format_version'],51);restored=restore_backup(package,self.root/'restored');self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid),state)
   target=self.root/'copy'/'copy.sqlite3';target.parent.mkdir();SQLiteRepository(target);SkillLibrary(target);copied=migrate(package,target,operation_id=str(uuid4()));clone=NovelService(SQLiteRepository(target)).get(copied['projects'][0]['new_id']);self.assertEqual(clone['console_messages'][0]['text'],'保留这段作者文字');self.assertNotIn('console-copy-key',json.dumps(clone));newpid=copied['projects'][0]['new_id'];newservice=NovelService(SQLiteRepository(target));shared=TaskCoordinator(newservice,AdapterRegistry());self.addCleanup(shared.close);writing=ChapterWriting(shared,self.providers);planning=ChapterPlanningCoordinator(shared,self.providers,enabled=True);expansion=SceneExpansionCoordinator(shared,self.providers,enabled=True);new=self.api.ConsoleCoordinator(newservice,writing,planning,expansion);detail=new.describe(newpid,clone['console_sessions'][0]['id']);self.assertEqual(detail['dispatches'][0]['display_status'],'interrupted')
   with self.assertRaises(ValueError):planning.start(newpid,detail['dispatches'][0]['task_id'],dict(confirm_external=True,request_sha256=clone['chapter_planning_tasks'][0]['binding']['request_sha256']))
   self.assertEqual(wire['calls'],[])
if __name__=='__main__':unittest.main()
