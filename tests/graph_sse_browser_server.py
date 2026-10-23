"""Fictional graph SSE browser fixture; every writable path is explicit and local."""
import json
import os
from pathlib import Path
import threading
import time
from uuid import uuid4
from novel_writer.ui.server import create_server
from graph_sse_fixture import graph_sse_wire

root = Path(os.environ['NOVEL_WRITER_ARTIFACTS']).resolve()
root.mkdir(parents=True, exist_ok=True)
protocol = os.environ['GRAPH_SSE_PROTOCOL']
outcome = os.environ.get('GRAPH_SSE_OUTCOME', 'success')
with graph_sse_wire(protocol) as wire:
    server = create_server(root/'browser-fiction.sqlite3', port=0, provider_path=root/'browser-fiction.dpapi', enable_model_generation=True)
    service = server.service
    state = service.create(title='C10阶段二流式图谱')
    pid = state['document']['project']['id']
    state = service.execute(pid, 'add_chapter', dict(title='灯塔'), expected_revision=state['revision'])
    cid = state['document']['chapters'][0]['id']
    body = '\n阿岚🙂到达灯塔。<img src=x onerror="window.graphInjected=true">'
    state = service.execute(pid, 'save_chapter', dict(chapter_id=cid, content=body), expected_revision=state['revision'])
    state = service.execute(pid, 'add_chapter', dict(title='未来章'), expected_revision=state['revision'])
    state = service.execute(pid, 'save_chapter', dict(chapter_id=state['document']['chapters'][-1]['id'], content='未来章秘密，不得外发。'), expected_revision=state['revision'])
    connection = server.providers.save_custom(id=str(uuid4()), name='图谱专用SSE虚构连接', base_url=wire['url'], protocol=protocol, model_id='fiction-graph-sse', api_key='fiction-browser-graph-sse-key', allow_local=True)
    server.providers.manage(id=connection['id'], action='stream_profile', confirmed=True, stream_mode='sse')
    def release_tail():
        deadline = time.monotonic()+60
        while time.monotonic()<deadline:
            if (root/'release-tail.flag').exists():
                wire['release'].set()
                return
            time.sleep(.02)
    threading.Thread(target=release_tail, daemon=True).start()
    print(json.dumps(dict(url='http://127.0.0.1:'+str(server.server_port),pid=pid,cid=cid,connection=connection['id'],body=body,protocol=protocol,outcome=outcome),ensure_ascii=False),flush=True)
    try:
        server.serve_forever(poll_interval=.02)
    finally:
        server.server_close()
