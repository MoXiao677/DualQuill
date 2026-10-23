import sys,unittest
from pathlib import Path
from uuid import uuid4
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src'),str(Path(__file__).resolve().parent)]
import test_s5a_http as base

class KnowledgeHTTPTests(unittest.TestCase):
    setUp=base.ReviewHTTPTests.setUp
    stop=base.ReviewHTTPTests.stop
    request=base.ReviewHTTPTests.request
    def test_visible_graph_mutation_query_and_read_only_merge_preview(self):
        state=self.server.service.get('p1');v=dict(operation_id=str(uuid4()),expected_revision=state['revision'],kind='location',label='灯塔',aliases=['旧塔'],memory_ids=[],position_chapter_id='p1-c5',source=dict(kind='chapter',entity_id='p1-c5'),confirmed=True)
        code,n=self.request('POST','/api/projects/p1/knowledge/save_node',v);self.assertEqual(code,200,n);code,view=self.request('POST','/api/projects/p1/knowledge/query',dict(query='旧塔'));self.assertEqual(code,200,view);self.assertEqual(view['nodes'][0]['id'],n['id']);before=self.db.read_bytes();self.assertEqual(self.request('GET','/api/projects/p1/knowledge')[0],200);self.assertEqual(self.db.read_bytes(),before)
    def test_token_unknown_crossbook_and_arbitrary_replacement_fields_rejected(self):
        self.assertEqual(self.request('POST','/api/projects/p1/knowledge/save_node',{},token=False)[0],403);before=self.db.read_bytes()
        for path,data in [('save_node',dict(fixture_output='fake')),('prepare_edit',dict(issue_id='other-book',side=0,mode='delete',replacement='',reason='x',operation_id=str(uuid4()),expected_revision=self.server.service.get('p1')['revision']))]:
            self.assertEqual(self.request('POST','/api/projects/p1/knowledge/'+path,data)[0],422);self.assertEqual(self.db.read_bytes(),before)
    def test_nonversioned_source_can_show_original_saved_revision_without_mutation(self):
        s=self.server.service.get('p1');self.server.service.execute('p1','save_worldbuilding',dict(content='旧港口设定'),expected_revision=s['revision']);s=self.server.service.get('p1')
        v=dict(operation_id=str(uuid4()),expected_revision=s['revision'],kind='setting',label='港口',aliases=[],memory_ids=[],position_chapter_id='p1-c5',source=dict(kind='worldbuilding',entity_id='p1'),confirmed=True)
        code,node=self.request('POST','/api/projects/p1/knowledge/save_node',v);self.assertEqual(code,200,node);s=self.server.service.get('p1');self.server.service.execute('p1','save_worldbuilding',dict(content='新港口设定'),expected_revision=s['revision']);before=self.db.read_bytes()
        code,source=self.request('POST','/api/projects/p1/knowledge/source',dict(source=node['source']));self.assertEqual(code,200,source);self.assertEqual(source['value'],'旧港口设定');self.assertTrue(source['outdated']);self.assertEqual(self.db.read_bytes(),before)

if __name__=='__main__':unittest.main()
