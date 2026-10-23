"""G-drive-only fictional fixture; deliberately contains no real credentials."""
import json
import os
from pathlib import Path
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

WORKSPACE = Path(__file__).resolve().parents[1]
TASK = WORKSPACE.parent
ROOT = Path(os.environ.get('FINAL_UI_SOURCE_ROOT', str(WORKSPACE))).resolve()
if ROOT not in (WORKSPACE, TASK.parent / 'baseline'):
    raise ValueError('Source must be this workspace or the shared read-only baseline')
sys.path.insert(0, str(ROOT / 'src'))
from novel_writer.ui.server import create_server


def isolated(value):
    result = Path(value).resolve()
    if not result.is_relative_to(TASK / 'temporary') or result.drive.lower() != 'g:':
        raise ValueError('All runtime directories must be under this task temporary on G:')
    result.mkdir(parents=True, exist_ok=True)
    return result


fixture = isolated(sys.argv[1])
for variable in ('TEMP', 'TMP'):
    isolated(os.environ[variable])
assert os.environ.get('PYTHONDONTWRITEBYTECODE') == '1'
calls = []


class FictionSupplier(BaseHTTPRequestHandler):
    def do_POST(self):
        calls.append({'path': self.path, 'unexpected': True})
        self.send_response(400)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"error":"This UI-only fixture never authorizes a model request"}')

    def log_message(self, *_):
        pass


def bind(factory):
    for _ in range(10):
        server = factory()
        if server.server_address[1] != 8765:
            return server
        server.server_close()
    raise RuntimeError('Failed to choose a non-8765 random loopback port')


supplier = bind(lambda: ThreadingHTTPServer(('127.0.0.1', 0), FictionSupplier))
supplier_thread = threading.Thread(target=supplier.serve_forever, daemon=True)
supplier_thread.start()
server = bind(lambda: create_server(
    fixture / 'fiction.sqlite3', port=0, provider_path=fixture / 'fiction.dpapi',
    drafts_path=fixture / 'drafts', offline=False, enable_model_generation=True))
state = server.service.create(title='虚构四尺寸验收：星灯与旧钥匙')
pid = state['document']['project']['id']
chapter_ids = []
body = '😀林默交出旧钥匙。星灯熄灭。\n第二段保留全角标点与组合字符 e\u0301。\n'
for title, text in [('第一章：风雨中的长街、灯塔与守塔人', body), ('第二章：未授权来源', '虚构后续章；不可自动扩大审核范围。')]:
    state = server.service.execute(pid, 'add_chapter', {'title': title}, expected_revision=state['revision'])
    cid = state['document']['chapters'][-1]['id']
    chapter_ids.append(cid)
    state = server.service.execute(pid, 'save_chapter', dict(chapter_id=cid, title=title, content=text, status='draft'), expected_revision=state['revision'])
state = server.service.execute(pid, 'save_writing_rules', {'content': '虚构规则：已保存正文才是来源；人物意见始终待核实。'}, expected_revision=state['revision'])
server.full_book_planning.act(pid, 'create_event', dict(operation_id=str(uuid4()), expected_revision=state['revision'], title='虚构事件：交出旧钥匙', planned_chapter_id=chapter_ids[0]))
connection = server.providers.save_custom(id=str(uuid4()), name='虚构UI专用连接（禁止实际模型调用）', base_url=f'http://127.0.0.1:{supplier.server_port}/v1', protocol='openai-chat', model_id='fiction-ui-only', api_key='fiction-ui-key-no-real-secret', allow_local=True)
worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02}, daemon=True)
worker.start()
print(json.dumps(dict(url=f'http://127.0.0.1:{server.server_port}', project_id=pid, chapter_id=chapter_ids[0], chapter_ids=chapter_ids, connection_id=connection['id'], body=body, database=str(fixture / 'fiction.sqlite3'), supplier_port=supplier.server_port)), flush=True)
try:
    for line in sys.stdin:
        command = line.strip()
        if command == 'stop':
            break
        print(json.dumps({'command': command, 'provider_calls': len(calls), 'calls': calls, 'real_paid_calls': 0}), flush=True)
finally:
    server.shutdown()
    server.server_close()
    supplier.shutdown()
    supplier.server_close()
    worker.join(2)
    supplier_thread.join(2)
