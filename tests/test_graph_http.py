"""C10 authenticated HTTP surface uses only fictional loopback suppliers."""
from copy import deepcopy
from uuid import uuid4
import unittest
import test_chapter_writing_http as fixtures
from test_graph_extraction import graph_wire


class GraphHTTPTests(unittest.TestCase):
    setUp = fixtures.ChapterWritingHttpTests.setUp
    stop = fixtures.ChapterWritingHttpTests.stop
    request = fixtures.ChapterWritingHttpTests.request

    def test_authenticated_prepare_execute_review_source_paths_rebuild_and_crossbook(self):
        base = self.base + '/knowledge/'
        with graph_wire() as wire:
            state = self.server.service.get(self.pid)
            self.server.service.execute(self.pid, 'save_chapter', dict(chapter_id=self.cid, content='阿岚🙂到达灯塔，灯塔属于守塔会。'), expected_revision=state['revision'])
            state = self.server.service.get(self.pid)
            connection = self.server.providers.save_custom(id=str(uuid4()), name='图谱HTTP虚构模型', base_url=wire['url'], protocol='openai-chat', model_id='fixture', api_key='fiction-graph-http-key', allow_local=True)
            request = dict(request_id=str(uuid4()), chapter_id=self.cid, selected_chapter_ids=[self.cid],
                expected_revision=state['revision'], instruction='仅引用保存正文', max_output_chars=20000, timeout_ms=3000,
                model_options=dict(adapter_id='configured-http-v2', connection_id=connection['id'], model_id='fixture', temperature=.3, max_tokens=2048, budget_limit=1.0, allow_unknown_cost=True, prompt_version='graph-extract-json-1'))
            self.assertEqual(self.request('POST', base+'extract-prepare', request, token=False)[0], 403)
            self.assertEqual(self.request('POST', base+'extract-prepare', dict(request, fixture_output='bad'))[0], 422)
            self.assertEqual(self.server.service.get(self.pid), state)
            code, prepared = self.request('POST', base+'extract-prepare', request)
            self.assertEqual(code, 200, prepared)
            task = prepared['task']
            self.assertEqual(wire['calls'], [])
            permission = dict(confirm_external=True, request_sha256=task['frozen']['parameters']['binding']['request_sha256'])
            route = self.base + '/tasks/' + task['id']
            self.assertEqual(self.request('POST', route+'/execute', dict(permission, request_sha256='0'*64))[0], 422)
            self.assertEqual(self.request('POST', route+'/execute', permission)[0], 202)
            self.server.task_coordinator.wait_idle(5)
            result = self.request('GET', route)[1]
            self.assertEqual(result['task']['status'], 'succeeded', result['task'])
            self.assertEqual(len(result['graph_extractions']), 1)
            code, listing = self.request('POST', base+'extract-list', dict(chapter_id=self.cid))
            self.assertEqual(code, 200, listing)
            p = listing['extractions'][0]
            e = p['output']['nodes'][0]['evidence'][0]
            source = dict(project_id=self.pid, kind='chapter', entity_id=e['entity_id'], chapter_id=e['chapter_id'], version_id=e['version_id'], workspace_revision=e['source_revision'], source_sha256=e['source_sha256'])
            self.assertEqual(self.request('POST', base+'source', dict(source=source))[1]['value']['content'], e['quote'])
            accept = dict(operation_id=str(uuid4()), expected_revision=listing['revision'], extraction_id=p['id'], decision='accepted', confirm_inference=False)
            self.assertEqual(self.request('POST', base+'extract-decide', accept)[0], 422)
            accept['confirm_inference'] = True
            code, receipt = self.request('POST', base+'extract-decide', accept)
            self.assertEqual(code, 200, receipt)
            self.assertEqual(self.request('POST', base+'extract-decide', accept), (200, receipt))
            a, _, goal = receipt['node_ids']
            code, found = self.request('POST', base+'paths', dict(from_id=a, to_id=goal, chapter_id=self.cid))
            self.assertEqual(code, 200, found)
            self.assertEqual(len(found['paths']), 1)
            for path, payload in [('paths', dict(from_id=a, to_id='other-book')), ('extract-list', dict(chapter_id='other-book')), ('rebuild-index', dict(expected_revision=-1))]:
                self.assertEqual(self.request('POST', base+path, payload)[0], 422)
            before = self.server.service.get(self.pid)
            rebuilt = self.request('POST', base+'rebuild-index', dict(expected_revision=before['revision']))
            self.assertEqual(rebuilt[0], 200, rebuilt)
            self.assertEqual(self.server.service.get(self.pid), before)
            foreign = self.server.service.create(title='同名的另一部虚构书')['document']['project']['id']
            foreign_request = dict(accept, operation_id=str(uuid4()), expected_revision=self.server.service.get(foreign)['revision'])
            self.assertEqual(self.request('POST', '/api/projects/'+foreign+'/knowledge/extract-decide', foreign_request)[0], 422)
            self.assertEqual(self.request('POST', '/api/projects/missing/knowledge/extract-list', {})[0], 404)
            self.assertEqual(len(wire['calls']), 1)


if __name__ == '__main__':
    unittest.main()
