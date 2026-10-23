"""Legacy producers and bounded workflows share one process admission domain."""
import threading
import unittest
from types import SimpleNamespace
from novel_writer.application.tasks import TaskCoordinator

class SharedExecutionAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tasks=TaskCoordinator(SimpleNamespace(repository=object()),None)

    def test_existing_producer_blocks_all_workflow_and_ordinary_tasks(self):
        self.assertTrue(self.tasks.slot.acquire(blocking=False))
        for group,limit in ((None,1),('workflow-a',2),('workflow-b',3)):
            with self.assertRaises(ValueError):self.tasks._claim_execution('pending',group,limit)
        self.tasks.slot.release()
        self.tasks._claim_execution('ordinary',None,1)
        self.assertFalse(self.tasks.slot.acquire(blocking=False))
        self.tasks._release_execution('ordinary')
        self.assertTrue(self.tasks.slot.acquire(blocking=False))
        self.tasks.slot.release()

    def test_bounded_workflow_blocks_other_producers_groups_and_lower_limits(self):
        self.tasks._claim_execution('one','workflow-a',2)
        self.tasks._claim_execution('two','workflow-a',2)
        self.assertFalse(self.tasks.slot.acquire(blocking=False))
        for task,group,limit in (('third','workflow-a',3),('foreign','workflow-b',3),('ordinary',None,1)):
            with self.assertRaises(ValueError):self.tasks._claim_execution(task,group,limit)
        self.tasks._release_execution('one')
        self.assertFalse(self.tasks.slot.acquire(blocking=False))
        self.tasks._release_execution('two')
        self.assertTrue(self.tasks.slot.acquire(blocking=False))
        self.tasks.slot.release()

    def test_blocking_legacy_waiter_is_woken_by_workflow_completion(self):
        self.tasks._claim_execution('running','workflow-a',2)
        acquired=threading.Event()
        def wait():
            if self.tasks.slot.acquire(timeout=1):
                acquired.set()
                self.tasks.slot.release()
        worker=threading.Thread(target=wait)
        worker.start()
        self.assertFalse(acquired.is_set())
        self.tasks._release_execution('running')
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertTrue(acquired.is_set())
