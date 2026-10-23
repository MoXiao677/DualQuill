"""Fictional loopback wire validates exact excerpts through writing/adoption."""
import unittest
from uuid import uuid4
import test_chapter_writing as fixture
from novel_writer.application.materials import Materials


class HybridWritingTests(unittest.TestCase):
    setUp=fixture.ChapterWritingTests.setUp
    action=fixture.ChapterWritingTests.action
    connection=fixture.ChapterWritingTests.connection
    options=fixture.ChapterWritingTests.options
    prepare=fixture.ChapterWritingTests.prepare
    run_task=fixture.ChapterWritingTests.run_task
    adoption=fixture.ChapterWritingTests.adoption

    def selected(self):
        self.materials=Materials(self.service)
        material=self.materials.create(self.pid,dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision'],title='虚构引文',format='txt',tags=[],text='WIRE_EXCERPT_SAFE '+'甲'*1000+'WIRE_EXCLUDED_SECRET'))['material']
        self.materials.rebuild(self.pid,material['id'],dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision']))
        selection=self.service.search_local(self.pid,dict(query='WIRE_EXCERPT_SAFE',chapter_id=self.cid,scopes=['materials'],material_ids=[material['id']],mode='hybrid'))['hits'][0]['selection']
        return material,selection

    def changed(self,material):
        self.materials.update(self.pid,material['id'],dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision'],title='虚构引文',format='txt',tags=[],text='来源已变化'))

    def test_exact_excerpt_reaches_actual_fake_wire_and_lifecycle_does_not_stale_it(self):
        material,selection=self.selected();options=self.options(context_options=dict(chapter_id=self.cid,budget_chars=20000,include_search_results=True,search_selections=[selection]))
        with fixture.supplier(output='门外有人。') as wire:
            prepared=self.prepare(self.connection(wire),options=options);binding=prepared['task']['frozen']['parameters']['binding']
            self.assertIn('WIRE_EXCERPT_SAFE',binding['request_body']);self.assertNotIn('WIRE_EXCLUDED_SECRET',binding['request_body']);self.assertEqual(wire['calls'],[])
            done=self.run_task(prepared);self.assertEqual(done['task']['status'],'succeeded');self.assertEqual(len(wire['calls']),1)
            self.assertIn('WIRE_EXCERPT_SAFE',str(wire['calls'][0]['body']));self.assertNotIn('WIRE_EXCLUDED_SECRET',str(wire['calls'][0]['body']))
            request=self.adoption(done);self.engine.adopt(self.pid,done['task']['id'],request)
            chapter=self.service.get(self.pid)['document']['chapters'][0];self.assertEqual(chapter['content'],'门外有人。')

    def test_changed_material_blocks_send_and_adoption_before_external_or_formal_write(self):
        for stage in ('send','adopt'):
            with self.subTest(stage=stage):
                material,selection=self.selected();options=self.options(context_options=dict(chapter_id=self.cid,budget_chars=20000,include_search_results=True,search_selections=[selection]))
                with fixture.supplier(output='门外有人。') as wire:
                    prepared=self.prepare(self.connection(wire),options=options);task=prepared['task'];request=None
                    if stage=='adopt':
                        done=self.run_task(prepared);task=done['task'];request=self.adoption(done)
                    self.changed(material);before=self.db.read_bytes()
                    with self.assertRaises(ValueError):
                        if stage=='send':self.run_task(prepared)
                        else:
                            request['expected_revision']=self.service.get(self.pid)['revision'];self.engine.adopt(self.pid,task['id'],request)
                    self.assertEqual(self.db.read_bytes(),before);self.assertEqual(len(wire['calls']),0 if stage=='send' else 1)

if __name__=='__main__':unittest.main()
