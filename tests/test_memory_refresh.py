import unittest
from uuid import uuid4
from copy import deepcopy
import test_s3b_rollups as fixture
from novel_writer.application.memory_refresh import MemoryRefresh

class MemoryRefreshTests(unittest.TestCase):
    setUp=fixture.MemoryRollupTests.setUp
    save=fixture.MemoryRollupTests.save
    memory=fixture.MemoryRollupTests.memory

    def engine(self): return MemoryRefresh(self.service)
    def change(self, **fields):
        result=self.engine().change('p1',dict(operation_id=str(uuid4()),expected_revision=self.service.get('p1')['revision'],**fields))
        self.state=self.service.get('p1');return result
    def setup_job(self,kind='event'):
        memory=self.memory('事实','旧事实',kind=kind)
        self.save('save_chapter',chapter_id='p1-c1',content='新事实正文')
        return memory,self.engine().listing('p1')['queue'][-1]

    def test_save_queues_exact_dependencies_and_default_does_not_execute(self):
        first=self.memory('一','旧一');second=self.memory('二','旧二','p1-c2')
        self.save('save_chapter',chapter_id='p1-c1',content='新一')
        listing=self.engine().listing('p1');self.assertFalse(listing['auto_refresh'])
        self.assertEqual(listing['queue'][-1]['memory_ids'],[first['id']])
        self.assertNotIn(second['id'],listing['queue'][-1]['memory_ids'])
        self.assertEqual(self.state['memories'][0]['text'],'旧一')
        self.assertEqual(listing['queue'][-1]['status'],'pending')

    def test_confirm_refresh_updates_content_preserves_history_and_provenance(self):
        memory,job=self.setup_job();old=deepcopy(self.state['memory_history'])
        result=self.change(action='refresh',job_id=job['id'],memory_texts={memory['id']:'作者核对的新事实'})
        self.assertEqual(result['status'],'succeeded')
        self.assertEqual(self.state['memories'][0]['text'],'作者核对的新事实')
        self.assertEqual(self.state['memory_history'][:len(old)],old)
        self.assertFalse(self.service.memory_records('p1')[0]['outdated'])
        attempt=self.state['memory_refresh_events'][-1]
        self.assertEqual(attempt['sources'][0]['chapter_id'],'p1-c1')
        self.assertEqual(attempt['sources'][0]['workspace_revision'],job['revision'])

    def test_failure_is_visible_retryable_and_atomic(self):
        memory,job=self.setup_job();old=deepcopy(self.state['memories'])
        result=self.change(action='refresh',job_id=job['id'],memory_texts={})
        self.assertEqual(result['status'],'failed');self.assertTrue(result['error'])
        self.assertEqual(self.state['memories'],old)
        self.assertEqual(self.engine().listing('p1')['queue'][-1]['status'],'failed')
        self.assertEqual(self.change(action='refresh',job_id=job['id'],memory_texts={memory['id']:'重试成功'})['status'],'succeeded')

    def test_unrelated_chapter_save_does_not_queue(self):
        self.memory('一','旧一');self.save('save_chapter',chapter_id='p1-c2',content='只改无关章')
        self.assertEqual(self.engine().listing('p1')['queue'],[])

    def test_rollups_refresh_in_same_transaction_and_history_kept(self):
        memory=self.memory('事实','旧事实')
        for scope,volume in [('chapter',None),('volume',1),('book',None)]:
            self.service.save_memory_rollup('p1',dict(scope=scope,scope_volume_number=volume,through_chapter_id='p1-c1',operation_id=str(uuid4()),expected_revision=self.service.get('p1')['revision']))
        self.state=self.service.get('p1');old=deepcopy(self.state['memory_rollup_history'])
        self.save('save_chapter',chapter_id='p1-c1',content='新事实正文')
        job=self.engine().listing('p1')['queue'][-1];self.assertEqual(len(job['rollup_ids']),3)
        self.assertEqual(self.change(action='refresh',job_id=job['id'],memory_texts={memory['id']:'新事实'})['status'],'succeeded')
        self.assertEqual(self.state['memory_rollup_history'][:len(old)],old)
        for rollup in self.service.memory_rollups('p1')['rollups']:
            self.assertIn('新事实',rollup['text']);self.assertFalse(rollup['stale'])

    def test_explicit_auto_refresh_only_local_chapter_extract_and_can_disable(self):
        memory=self.memory('章节原文摘录','旧摘录',kind='chapter_summary')
        self.change(action='policy',auto_refresh=True)
        self.save('save_chapter',chapter_id='p1-c1',content='当前正文原文')
        self.assertEqual(self.state['memories'][0]['text'],'当前正文原文')
        self.assertEqual(self.engine().listing('p1')['queue'][-1]['status'],'succeeded')
        self.change(action='policy',auto_refresh=False)
        self.save('save_chapter',chapter_id='p1-c1',content='再次变化')
        self.assertEqual(self.state['memories'][0]['text'],'当前正文原文')
        self.assertEqual(self.engine().listing('p1')['queue'][-1]['status'],'pending')
