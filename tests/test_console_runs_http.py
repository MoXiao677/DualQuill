from http.client import HTTPConnection
import json,tempfile,threading,unittest
from pathlib import Path
from uuid import uuid4

from novel_writer.application.creation_presets import CreationPresets
from novel_writer.ui.server import create_server
from test_book_ai import supplier


class ConsoleRunHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='console-run-http-');self.addCleanup(self.temp.cleanup);root=Path(self.temp.name)
        self.server=create_server(root/'fiction.sqlite3',port=0,provider_path=root/'fiction.dpapi',enable_model_generation=True)
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start();self.addCleanup(self.stop)
        code,state,_=self.request('POST','/api/projects',dict(title='运行HTTP'));self.pid=state['document']['project']['id'];self.base='/api/projects/'+self.pid+'/console'
        self.request('POST','/api/projects/'+self.pid+'/actions',dict(action='add_character',fields=dict(name='林舟'),expected_revision=state['revision']));state=self.server.service.get(self.pid)
        self.request('POST','/api/projects/'+self.pid+'/actions',dict(action='add_chapter',fields=dict(title='第一章'),expected_revision=state['revision']));state=self.server.service.get(self.pid)
        self.request('POST','/api/projects/'+self.pid+'/actions',dict(action='save_worldbuilding',fields=dict(content='港城有雾。'),expected_revision=state['revision']));state=self.server.service.get(self.pid)
        self.request('POST','/api/projects/'+self.pid+'/actions',dict(action='save_writing_rules',fields=dict(content='限知视角。'),expected_revision=state['revision']))
        self.chapter=self.server.service.get(self.pid)['document']['chapters'][0]['id']

    def stop(self):
        self.server.shutdown();self.server.server_close();self.thread.join(2)

    def request(self,method,path,payload=None,*,token=True):
        c=HTTPConnection('127.0.0.1',self.server.server_port,timeout=10);headers={'Content-Type':'application/json'}
        if token:headers['X-Novel-Token']=self.server.token
        try:c.request(method,path,json.dumps(payload) if payload is not None else None,headers);r=c.getresponse();return r.status,json.loads(r.read()),dict(r.getheaders())
        finally:c.close()

    def configure(self,wire):
        connection=self.server.providers.save_custom(id=str(uuid4()),name='虚构HTTP运行模型',base_url=wire['url'],protocol='openai-chat',model_id='fixture',api_key='http-run-private-key',allow_local=True)
        presets=CreationPresets(self.server.service)
        saved=presets.save(self.pid,dict(operation_id=str(uuid4()),preset_id=None,name='HTTP运行预设',settings=dict(steps=[dict(step='brainstorm',adapter_id='configured-http-v2',connection_id=connection['id'],model_id='fixture',temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=True)],style_id=None,style_prompt='',manuscript_language='zh-CN',budget=dict(max_external_calls=4,max_reserved_output_tokens=4096,risk_budget=2.0,allow_unknown_cost=True)),expected_revision=self.server.service.get(self.pid)['revision']))
        presets.choose(self.pid,dict(operation_id=str(uuid4()),version_id=saved['version_id'],confirmed=True,expected_revision=self.server.service.get(self.pid)['revision']))

    def test_run_routes_auth_idempotency_conflicts_and_capabilities(self):
        with supplier(output=json.dumps(dict(idea='不应发送'),ensure_ascii=False)) as wire:
            self.configure(wire)
            code,session,_=self.request('POST',self.base+'/sessions',dict(operation_id=str(uuid4()),title='运行会话'));self.assertEqual(code,201);sid=session['id']
            step=dict(id=str(uuid4()),type='idea',chapter_id=self.chapter,instruction='构思',status='planned',scene_order=None,selection_start=None,selection_end=None)
            self.assertEqual(self.request('POST',self.base+'/sessions/'+sid+'/plan',dict(steps=[step]))[0],200)
            revision=self.server.service.get(self.pid)['revision']
            self.assertEqual(self.request('POST',self.base+'/runs',dict(operation_id=str(uuid4()),session_id=sid,expected_revision=revision),token=False)[0],403)
            code,started,_=self.request('POST',self.base+'/runs',dict(operation_id=str(uuid4()),session_id=sid,expected_revision=revision));self.assertEqual(code,201,started);run_id=started['run']['id']
            self.assertEqual(self.request('GET',self.base+'/runs',token=False)[0],200);self.assertEqual(self.request('GET',self.base+'/runs/'+run_id,token=False)[1]['run']['id'],run_id)
            operation=str(uuid4());revision=self.server.service.get(self.pid)['revision']
            code,advanced,_=self.request('POST',self.base+'/runs/'+run_id+'/advance',dict(operation_id=operation,expected_revision=revision));self.assertEqual(code,200,advanced);self.assertEqual(advanced['steps'][0]['status'],'awaiting_confirmation')
            replay=self.request('POST',self.base+'/runs/'+run_id+'/advance',dict(operation_id=operation,expected_revision=revision));self.assertEqual(replay[0],200);self.assertEqual(replay[1]['steps'][0]['task_id'],advanced['steps'][0]['task_id'])
            self.assertEqual(self.request('POST',self.base+'/runs/'+run_id+'/advance',dict(operation_id=str(uuid4()),expected_revision=revision))[0],422)
            revision=self.server.service.get(self.pid)['revision'];self.assertEqual(self.request('POST',self.base+'/runs/'+run_id+'/pause',dict(operation_id=str(uuid4()),expected_revision=revision))[0],200)
            revision=self.server.service.get(self.pid)['revision'];self.assertEqual(self.request('POST',self.base+'/runs/'+run_id+'/resume',dict(operation_id=str(uuid4()),expected_revision=revision))[0],200)
            revision=self.server.service.get(self.pid)['revision'];current=advanced['steps'][0]['id']
            code,skipped,_=self.request('POST',self.base+'/runs/'+run_id+'/skip',dict(operation_id=str(uuid4()),expected_revision=revision,step_id=current));self.assertEqual(code,200,skipped);self.assertEqual(skipped['run']['status'],'completed');self.assertEqual(skipped['steps'][0]['status'],'skipped')
            self.assertEqual(self.request('POST',self.base+'/runs/'+run_id+'/cancel',dict(operation_id=str(uuid4()),expected_revision=revision))[0],422)
            self.assertEqual(self.request('GET',self.base+'/runs/not-a-run',token=False)[0],404)
            code,backups,_=self.request('GET','/api/backups/capabilities',token=False);self.assertEqual(code,200);self.assertIn(24,backups['backup_format_versions']);self.assertIn(24,backups['workspace_versions'])
            code,migrations,_=self.request('GET','/api/migrations/capabilities',token=False);self.assertEqual(code,200);self.assertIn('backup_v24',migrations['formats'])
            self.assertEqual(wire['calls'],[])


if __name__=='__main__':unittest.main()
