"""Isolated fictional graph browser fixture. All paths must be task-local."""
import json
import os
from pathlib import Path
from uuid import uuid4
from novel_writer.ui.server import create_server
from test_graph_extraction import graph_wire

root = Path(os.environ['NOVEL_WRITER_ARTIFACTS']).resolve()
root.mkdir(parents=True, exist_ok=True)
with graph_wire() as wire:
    server = create_server(root/'browser-fiction.sqlite3', port=0, provider_path=root/'browser-fiction.dpapi', enable_model_generation=True)
    service = server.service
    state = service.create(title='C10虚构图谱交互')
    pid = state['document']['project']['id']
    state = service.execute(pid, 'add_chapter', dict(title='灯塔'), expected_revision=state['revision'])
    cid = state['document']['chapters'][0]['id']
    state = service.execute(pid, 'save_chapter', dict(chapter_id=cid, content='\n阿岚🙂到达灯塔，灯塔属于守塔会。<img src=x onerror="window.graphInjected=true">'), expected_revision=state['revision'])
    state = service.execute(pid, 'add_chapter', dict(title='未来章'), expected_revision=state['revision'])
    state = service.execute(pid, 'save_chapter', dict(chapter_id=state['document']['chapters'][-1]['id'], content='未来章秘密，不得发送。'), expected_revision=state['revision'])
    connection = server.providers.save_custom(id=str(uuid4()), name='虚构图谱本地替身', base_url=wire['url'], protocol='openai-chat', model_id='fiction-model', api_key='fiction-browser-graph-key', allow_local=True)
    print(json.dumps(dict(url='http://127.0.0.1:'+str(server.server_port), pid=pid, cid=cid, connection=connection['id']), ensure_ascii=False), flush=True)
    try:
        server.serve_forever(poll_interval=.02)
    finally:
        server.server_close()
        (root/'wire-calls.json').write_text(json.dumps(wire['calls'], ensure_ascii=False, indent=2), encoding='utf8')
