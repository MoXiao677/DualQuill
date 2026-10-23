import base64
import unittest
from uuid import uuid4
from tests import test_chapter_lifecycle_http as fixture

class ChapterTrashHTTPTests(unittest.TestCase):
    setUp=fixture.LifecycleHttpTests.setUp
    stop=fixture.LifecycleHttpTests.stop
    request=fixture.LifecycleHttpTests.request
    def action(self,name,fields,revision=None):
        return self.request('POST',self.base+'/actions',dict(action=name,fields=fields,expected_revision=self.server.service.get(self.pid)['revision'] if revision is None else revision))
    def test_auto_import_move_and_conflict(self):
        payload=dict(filename='自动.txt',encoding='auto',content_base64=base64.b64encode('第1章 中文\n严格正文\n'.encode('gb18030')).decode())
        code,preview,_=self.request('POST',self.base+'/import/preview',payload)
        self.assertEqual(code,200);self.assertEqual(preview['encoding'],'gb18030')
        code,state,_=self.request('POST',self.base+'/import/commit',{**payload,'items':preview['items'],'preview_sha256':preview['preview_sha256'],'confirmed':True,'expected_revision':preview['workspace_revision']})
        self.assertEqual(code,200);imported=state['document']['chapters'][-1]['id']
        self.action('save_book_outline',dict(volumes=[dict(number=1,title='一',summary='',chapter_ids=[self.cid]),dict(number=2,title='二',summary='',chapter_ids=[imported])]))
        rev=self.server.service.get(self.pid)['revision'];fields=dict(chapter_id=self.cid,target_volume_number=2,target_index=0,confirmed=True)
        code,state,_=self.action('move_chapter_to_volume',fields,rev)
        self.assertEqual(code,200);self.assertEqual(state['document']['book_outline']['volumes'][1]['chapter_ids'],[self.cid,imported])
        self.assertEqual(self.action('move_chapter_to_volume',fields,rev)[0],409)
        self.assertEqual(self.action('move_chapter_to_volume',fields)[0],422)
        for raw in (b'\x81',b'\xef\xbb\xbf\xff'):
            self.assertEqual(self.request('POST',self.base+'/import/preview',{**payload,'content_base64':base64.b64encode(raw).decode()})[0],422)
    def test_trash_confirmations_exclusions_restore(self):
        self.action('save_chapter',dict(chapter_id=self.cid,content='保留正文'))
        self.action('save_book_outline',dict(volumes=[dict(number=1,title='原卷',summary='',chapter_ids=[self.cid])]))
        code,preview,_=self.request('GET',self.base+'/chapters/'+self.cid+'/trash-preview')
        self.assertEqual(code,200);self.assertGreater(preview['reference_count'],0)
        self.assertEqual(self.request('POST',self.base+'/actions',dict(action='trash_chapter',fields={},expected_revision=preview['revision']),token=False)[0],403)
        fields=dict(chapter_id=self.cid,operation_id=str(uuid4()),confirm_title='第一章',acknowledge_references=True,confirmed=True)
        for patch in ({'confirm_title':'错标题'},{'acknowledge_references':False},{'operation_id':None}):
            self.assertEqual(self.action('trash_chapter',{**fields,**patch})[0],422)
        code,state,_=self.action('trash_chapter',fields);self.assertEqual(code,200)
        self.assertEqual(self.request('GET',self.base+'/trash')[1]['chapters'][0]['chapter_id'],self.cid)
        self.assertEqual(self.request('GET',self.base+'/export?scope=book&format=txt',raw=True)[1],b'')
        self.assertEqual(state['document']['chapters'][0]['content'],'保留正文')
        self.assertEqual(self.action('archive_chapter',dict(chapter_id=self.cid,confirmed=True))[0],422)
        code,state,_=self.action('restore_trashed_chapter',dict(chapter_id=self.cid,operation_id=str(uuid4()),confirmed=True))
        self.assertEqual(code,200);self.assertEqual(state['document']['book_outline']['volumes'][0]['chapter_ids'],[self.cid])
        self.assertEqual(self.request('GET',self.base+'/trash')[1]['chapters'],[])
