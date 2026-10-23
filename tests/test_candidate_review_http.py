"""Missing and cross-project workflow identities are expected HTTP misses."""
from uuid import uuid4
import unittest
import test_chapter_writing_http as fixtures
from test_s6b_workflows import node,template

class CandidateWorkflowHttpTests(unittest.TestCase):
    setUp=fixtures.ChapterWritingHttpTests.setUp
    stop=fixtures.ChapterWritingHttpTests.stop
    request=fixtures.ChapterWritingHttpTests.request
    def test_missing_and_cross_project_run_and_template_are_404_without_writes(self):
        engine=self.server.workflows;state=self.request('GET',self.base)[1]
        version=engine.import_template(self.pid,dict(operation_id=str(uuid4()),template_id=None,template=template([node('read','reference',params=dict(max_chars=20000))]),expected_revision=state['revision']))
        run=engine.create(self.pid,dict(operation_id=str(uuid4()),template_version_id=version['version_id'],chapter_id=self.cid,inputs=dict(instruction='',query='',plan_text=''),roles=[],limits=dict(max_external_calls=2,max_reserved_output_tokens=1024,max_node_attempts=64,max_retries=1,max_iterations=3,concurrency=1),execution_mode='step',network_mode='disabled',expected_revision=self.request('GET',self.base)[1]['revision']))
        code,other=self.request('POST','/api/projects',dict(title='另一虚构HTTP书'));self.assertEqual(code,201);other_base='/api/projects/'+other['document']['project']['id'];before=self.request('GET',self.base)[1]
        self.assertEqual(self.request('GET',self.base+'/workflows/runs/'+run['run_id'])[0],200)
        for base,identity in ((other_base,run['run_id']),(self.base,str(uuid4()))):
            self.assertEqual(self.request('GET',base+'/workflows/runs/'+identity)[0],404)
            self.assertEqual(self.request('POST',base+'/workflows/runs/'+identity+'/step',{})[0],404)
        self.assertEqual(self.request('GET',other_base+'/workflows/templates/'+version['version_id']+'/export')[0],404)
        self.assertEqual(self.request('GET',self.base+'/workflows/templates/'+str(uuid4())+'/export')[0],404)
        self.assertEqual(self.request('GET',self.base)[1],before);self.assertEqual(self.request('GET',other_base)[1],other)
