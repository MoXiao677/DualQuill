import unittest
from http.client import HTTPConnection
from uuid import uuid4
import test_console_runs_http as fixture


class ControlledConsoleHttpTests(unittest.TestCase):
    setUp=fixture.ConsoleRunHttpTests.setUp
    stop=fixture.ConsoleRunHttpTests.stop
    request=fixture.ConsoleRunHttpTests.request

    def test_usage_module_is_served_from_the_static_allowlist(self):
        connection=HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        try:
            connection.request('GET','/console_usage.js');response=connection.getresponse();body=response.read()
            self.assertEqual(response.status,200);self.assertIn('javascript',response.getheader('Content-Type'));self.assertIn(b'renderActualUsage',body)
        finally:connection.close()

    def test_preview_schema_auth_continuation_and_v36_capabilities(self):
        status,session,_=self.request('POST',self.base+'/sessions',dict(operation_id=str(uuid4()),title='虚构只读编排'))
        self.assertEqual(status,201);sid=session['id'];base=self.base+'/sessions/'+sid
        proposal=dict(steps=[dict(tool=tool,arguments=dict(chapter_id=self.chapter,instruction='只读虚构资料')) for tool in ('chapter.inspect','context.preview')])
        before=self.server.service.get(self.pid)
        self.assertEqual(self.request('POST',base+'/proposal-preview',dict(proposal=proposal),token=False)[0],403)
        code,preview,_=self.request('POST',base+'/proposal-preview',dict(proposal=proposal));self.assertEqual(code,200,preview)
        self.assertEqual(self.server.service.get(self.pid),before)
        bad=dict(steps=[dict(tool='exec',arguments=dict(command='whoami'))])
        code,error,_=self.request('POST',base+'/proposal-preview',dict(proposal=bad));self.assertEqual(code,422);self.assertIn('未注册',str(error))
        self.assertEqual(self.request('POST',base+'/plan',dict(steps=preview['steps']))[0],200)
        code,started,_=self.request('POST',self.base+'/runs',dict(operation_id=str(uuid4()),session_id=sid,expected_revision=self.server.service.get(self.pid)['revision']));self.assertEqual(code,201)
        url=self.base+'/runs/'+started['run']['id']+'/advance';request=dict(operation_id=str(uuid4()),expected_revision=started['revision'],allow_readonly=['chapter.inspect','context.preview'])
        code,advanced,_=self.request('POST',url,request);self.assertEqual(code,200,advanced);self.assertEqual(advanced['run']['status'],'completed')
        self.assertTrue(all(v['result'] for v in advanced['steps']));self.assertEqual(advanced['run']['usage']['external_attempts'],0)
        before=self.server.service.get(self.pid);self.assertEqual(self.request('POST',url,request)[0],200);self.assertEqual(self.server.service.get(self.pid),before)
        code,detail,_=self.request('GET',base);self.assertEqual(code,200);self.assertEqual(len(detail['tools']),8)
        code,caps,_=self.request('GET','/api/backups/capabilities');self.assertEqual(code,200);self.assertIn(36,caps['workspace_versions'])
        code,caps,_=self.request('GET','/api/migrations/capabilities');self.assertEqual(code,200);self.assertIn('backup_v36',caps['formats'])


if __name__=='__main__':unittest.main()
