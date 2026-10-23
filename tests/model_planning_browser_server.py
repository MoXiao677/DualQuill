"""Isolated fictional UI fixture. No real provider or author profile is read."""
import json
from pathlib import Path
import sys
import threading
from uuid import uuid4
from test_model_planning import model_wire
from novel_writer.ui.server import create_server

root=Path(sys.argv[1]).resolve();root.mkdir(parents=True,exist_ok=True)
server=create_server(root/'fiction.sqlite3',port=0,provider_path=root/'fiction.dpapi',offline=False,enable_model_generation=True)
state=server.service.create(title='正文规划浏览器虚构验收');pid=state['document']['project']['id']
state=server.service.execute(pid,'add_chapter',dict(title='虚构钥匙'),expected_revision=state['revision']);cid=state['document']['chapters'][0]['id']
body='😀林默交出旧钥匙。星灯熄灭。'
state=server.service.execute(pid,'save_chapter',dict(chapter_id=cid,title='虚构钥匙',content=body,status='draft'),expected_revision=state['revision'])
listing=server.full_book_planning.act(pid,'create_event',dict(operation_id=str(uuid4()),expected_revision=state['revision'],title='交出旧钥匙',planned_chapter_id=cid))
eid=listing['key_events'][0]['id'];quote='林默交出旧钥匙。'
output=json.dumps(dict(suggestions=[dict(reason='<img src=x onerror="window.modelInjected=true"> 虚构模型意见待核实',start=1,end=1+len(quote),quote=quote,
    actions=[dict(action='occur_event',values=dict(event_id=eid,occurrence_chapter_id=cid,body_reference=quote))])]),ensure_ascii=False)
with model_wire(output,stream=True,hold=True) as wire:
    c=server.providers.save_custom(id=str(uuid4()),name='正文规划虚构SSE',base_url=wire['url'],protocol='openai-chat',model_id='fiction-selected',api_key='fiction-body-key',allow_local=True)
    server.providers.manage(id=c['id'],action='stream_profile',confirmed=True,stream_mode='sse')
    worker=threading.Thread(target=server.serve_forever,kwargs=dict(poll_interval=.01),daemon=True);worker.start()
    print(json.dumps(dict(url=f'http://127.0.0.1:{server.server_port}',project_id=pid,chapter_id=cid,event_id=eid,connection_id=c['id'],body=body)),flush=True)
    try:
        for line in sys.stdin:
            command=line.strip()
            if command=='release':wire['release'].set()
            elif command=='hold':wire['release'].clear()
            elif command=='stop':break
            print(json.dumps(dict(command=command,calls=len(wire['calls']))),flush=True)
    finally:
        wire['release'].set();server.shutdown();server.server_close();worker.join(2)
