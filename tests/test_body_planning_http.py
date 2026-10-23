"""Real random-loopback HTTP checks; offline provider boundary, no real keys."""
import json
from uuid import uuid4
import unittest
import test_full_book_planning_http as helpers


class BodyPlanningHTTPTests(unittest.TestCase):
    setUp = helpers.FullBookPlanningHTTPTests.setUp
    stop = helpers.FullBookPlanningHTTPTests.stop
    request = helpers.FullBookPlanningHTTPTests.request
    revision = helpers.FullBookPlanningHTTPTests.revision
    action = helpers.FullBookPlanningHTTPTests.action

    def saved(self):
        self.server.service.execute(self.pid,'save_chapter',dict(chapter_id=self.c1,title='虚构正文',content='林默交出旧钥匙。',status='draft'),expected_revision=self.revision())

    def path(self,action): return f'/api/projects/{self.pid}/body-planning/{action}'

    def values(self,**kwargs): return dict(operation_id=str(uuid4()),expected_revision=self.revision(),**kwargs)

    def proposal_values(self):
        return self.values(chapter_id=self.c1,start=0,end=len('林默交出旧钥匙。'),quote='林默交出旧钥匙。',
                           reason='虚构正文驱动计划',origin='author',actions=[dict(action='create_event',values=dict(title='提案事件',planned_chapter_id=self.c1))])

    def test_real_http_prepare_preview_accept_replay_and_get_listing(self):
        self.saved(); before=self.server.service.get(self.pid)
        request=self.proposal_values();code,p=self.request('POST',self.path('prepare'),request);self.assertEqual(code,200)
        self.assertEqual(self.server.service.get(self.pid)['key_events'],[])
        code,preview=self.request('POST',self.path('preview'),dict(proposal_id=p['id']));self.assertEqual(code,200)
        decision=self.values(proposal_id=p['id'],decision='accepted',preview_sha256=preview['preview_sha256'])
        code,receipt=self.request('POST',self.path('decide'),decision);self.assertEqual(code,200)
        self.assertEqual(self.request('POST',self.path('decide'),decision),(200,receipt))
        code,listing=self.request('GET',self.base);self.assertEqual(code,200)
        self.assertEqual(listing['body_planning']['proposals'][0]['receipt']['decision'],'accepted')
        self.assertEqual(listing['key_events'][0]['title'],'提案事件')
        self.assertEqual(before['document'],self.server.service.get(self.pid)['document'])

    def test_token_unknown_fields_crossbook_unknown_proposal_and_stale_preview(self):
        self.saved(); before=self.server.service.get(self.pid);request=self.proposal_values()
        self.assertEqual(self.request('POST',self.path('prepare'),request,token=False)[0],403)
        self.assertEqual(before,self.server.service.get(self.pid))
        self.assertEqual(self.request('POST',self.path('prepare'),dict(request,unknown=True))[0],422)
        self.assertEqual(self.request('POST',self.path('prepare'),dict(request,quote='不在正文中'))[0],422)
        self.assertEqual(self.request('POST',self.path('preview'),dict(proposal_id=str(uuid4())))[0],404)
        code,p=self.request('POST',self.path('prepare'),request);self.assertEqual(code,200)
        code,v=self.request('POST',self.path('preview'),dict(proposal_id=p['id']));self.assertEqual(code,200)
        code,other=self.request('POST',self.path('prepare'),self.proposal_values());self.assertEqual(code,200)
        before=self.server.service.get(self.pid)
        self.assertEqual(self.request('POST',self.path('decide'),self.values(proposal_id=p['id'],decision='accepted',preview_sha256=v['preview_sha256']))[0],409)
        self.assertEqual(before,self.server.service.get(self.pid))
        otherbook=self.server.service.create(title='另一虚构书')['document']['project']['id']
        self.assertEqual(self.request('POST',self.path('preview').replace(self.pid,otherbook),dict(proposal_id=p['id']))[0],404)

    def test_http_completion_and_reject_have_zero_formal_changes(self):
        self.saved();before=self.server.service.get(self.pid)
        code,context=self.request('POST',self.path('completion'),dict(chapter_id=self.c1,start=0,end=len('林默交出旧钥匙。'),quote='林默交出旧钥匙。'))
        self.assertEqual(code,200);self.assertFalse(context['model_request_sent'])
        self.assertEqual(before,self.server.service.get(self.pid))
        code,p=self.request('POST',self.path('prepare'),self.proposal_values());self.assertEqual(code,200)
        code,r=self.request('POST',self.path('decide'),self.values(proposal_id=p['id'],decision='rejected'));self.assertEqual(code,200)
        after=self.server.service.get(self.pid)
        self.assertEqual(before['document'],after['document']);self.assertEqual(after['key_events'],[])


if __name__=='__main__':unittest.main()
