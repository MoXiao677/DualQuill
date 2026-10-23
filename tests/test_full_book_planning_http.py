"""V26 全书规划 HTTP 入口、静态资产、令牌与错误边界。"""
from http.client import HTTPConnection
import json,sys,tempfile,threading,unittest
from pathlib import Path
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from novel_writer.ui.server import create_server


class FullBookPlanningHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='c07-http-');self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);self.server=create_server(root/'fiction.sqlite3',port=0,provider_path=root/'fake.dpapi',offline=True)
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start();self.addCleanup(self.stop)
        state=self.server.service.create(title='HTTP全书规划虚构测试');self.pid=state['document']['project']['id']
        state=self.server.service.execute(self.pid,'add_chapter',dict(title='第一章'),expected_revision=state['revision']);self.c1=state['document']['chapters'][0]['id']
        state=self.server.service.execute(self.pid,'add_character',dict(name='林默'),expected_revision=state['revision']);self.character=state['document']['characters'][0]['id']
        self.base=f'/api/projects/{self.pid}/full-book-planning'
    def stop(self):self.server.shutdown();self.server.server_close();self.thread.join(2)
    def request(self,method,path,payload=None,token=True,parse=True):
        connection=HTTPConnection('127.0.0.1',self.server.server_port,timeout=10);headers={'Content-Type':'application/json'}
        if token:headers['X-Novel-Token']=self.server.token
        try:
            connection.request(method,path,json.dumps(payload) if payload is not None else None,headers)
            response=connection.getresponse();body=response.read()
            return response.status,(json.loads(body) if parse and body else body)
        finally:connection.close()
    def revision(self):return self.server.service.get(self.pid)['revision']
    def action(self,action,**payload):return self.request('POST',self.base+'/actions',dict(action=action,operation_id=str(uuid4()),expected_revision=payload.pop('expected_revision',self.revision()),**payload))

    def test_read_static_assets_capabilities_and_ai_boundary(self):
        code,listing=self.request('GET',self.base);self.assertEqual(code,200)
        self.assertEqual(listing['ai_completion']['status'],'native_model_session_disabled')
        self.assertFalse(listing['model_planning']['enabled'])
        self.assertIn('create_arc',listing['actions']);self.assertIn('occur_stage',listing['actions'])
        self.assertIn('章节确认不会自动改变规划状态',listing['deviation']['occurrence_policy'])
        code,script=self.request('GET','/full_book_planning.js',parse=False);self.assertEqual(code,200);text=script.decode('utf8')
        for value in ('renderFullBookPlanning','bindFullBookPlanning','正文引用','显式记录发生','计划位置','实际发生','AI 补全','章节确认不会自动'):
            self.assertIn(value,text)
        app=self.request('GET','/app.js',parse=False)[1].decode('utf8');self.assertIn("from './full_book_planning.js'",app)
        backups=self.request('GET','/api/backups/capabilities')[1];self.assertIn(26,backups['workspace_versions']);self.assertIn(27,backups['workspace_versions']);self.assertIn(26,backups['backup_format_versions']);self.assertIn(27,backups['backup_format_versions'])
        migrations=self.request('GET','/api/migrations/capabilities')[1];self.assertIn('backup_v26',migrations['formats'])
        security=(ROOT/'desktop/security.cjs').read_text(encoding='utf8');self.assertIn("'/full_book_planning.js':'full_book_planning.js'",security)

    def test_write_token_revision_not_found_conflict_and_validation(self):
        self.assertEqual(self.request('POST',self.base+'/actions',dict(action='create_arc',operation_id=str(uuid4()),expected_revision=self.revision(),character_id=self.character,title='x'),token=False)[0],403)
        operation=str(uuid4());payload=dict(action='create_arc',operation_id=operation,expected_revision=self.revision(),character_id=self.character,title='弧光')
        code,created=self.request('POST',self.base+'/actions',payload);self.assertEqual(code,200);arc=created['character_arcs'][0]['id']
        self.assertEqual(self.request('POST',self.base+'/actions',payload)[0],200)
        self.assertEqual(self.request('POST',self.base+'/actions',dict(payload,operation_id=str(uuid4()),expected_revision=1))[0],409)
        self.assertEqual(self.request('POST',self.base+'/actions',dict(action='update_arc',operation_id=str(uuid4()),expected_revision=created['revision'],arc_id=str(uuid4()),title='x'))[0],404)
        self.assertEqual(self.request('POST',self.base+'/actions',dict(action='unknown',operation_id=str(uuid4()),expected_revision=created['revision']))[0],404)
        self.assertEqual(self.request('POST',self.base+'/actions',dict(action='update_arc',operation_id=str(uuid4()),expected_revision=created['revision'],arc_id=arc,title='x',unknown=True))[0],422)
        self.assertEqual(self.request('POST',self.base+'/actions',dict(action='occur_stage',operation_id=str(uuid4()),expected_revision=created['revision'],stage_id=arc,occurrence_chapter_id=self.c1))[0],422)
        self.assertEqual(self.request('GET',self.base.replace(self.pid,str(uuid4())))[0],404)
        other=self.server.service.create(title='另一本书');other_id=other['document']['project']['id']
        other=self.server.service.execute(other_id,'add_character',dict(name='甲'),expected_revision=other['revision'])
        other_character=other['document']['characters'][0]['id']
        self.assertEqual(self.request('POST',f'/api/projects/{other_id}/full-book-planning/actions',dict(action='create_arc',operation_id=operation,expected_revision=other['revision'],character_id=other_character,title='跨书'))[0],409)

    def test_stage_occurrence_requires_body_and_reports_archived_chapter(self):
        code,created=self.action('create_arc',character_id=self.character,title='弧光');arc=created['character_arcs'][0]['id']
        code,created=self.action('create_stage',arc_id=arc,title='阶段',planned_chapter_id=self.c1);stage=created['character_arc_stages'][0]['id']
        self.assertEqual(self.action('occur_stage',stage_id=stage,occurrence_chapter_id=self.c1,body_reference='') [0],422)
        state=self.server.service.execute(self.pid,'archive_chapter',dict(chapter_id=self.c1,confirmed=True),expected_revision=self.revision())
        self.assertEqual(self.action('occur_stage',stage_id=stage,occurrence_chapter_id=self.c1,body_reference='正文') [0],422)
        code,listing=self.request('GET',self.base);self.assertEqual(code,200)
        self.assertTrue(any(value['entity_id']==stage and value['state']=='archived' for value in listing['deviation']['references']))


if __name__=='__main__':unittest.main()
