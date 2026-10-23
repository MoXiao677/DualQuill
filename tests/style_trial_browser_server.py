"""Synthetic existing style library and loopback prose provider for hidden author UI."""
import argparse,json,os,sys,threading
from pathlib import Path
from contextlib import ExitStack
from uuid import uuid4
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src'),str(Path(__file__).parent)]
from test_style_trials import TrialTests
from test_book_ai import supplier
from novel_writer.ui.server import create_server
from novel_writer.application.creation_presets import CreationPresets
parser=argparse.ArgumentParser();parser.add_argument('--trace',type=Path,required=True);args=parser.parse_args();fixture=TrialTests('test_empty_book_trial_freezes_own_seed_and_style_without_raw_material_or_fake_chapter');fixture.setUp();stack=ExitStack();wire=stack.enter_context(supplier(output='门环很冷。他抬起手，又停了一息。'));connection=fixture.connection(wire);fixture.source('不应外发的原始样本文字MARKER。'*100);left=fixture.card('克制版本','使用克制的具体动作。');right=fixture.card('舒缓版本','使用舒缓的景物描写。');fixture.styles.choose(fixture.pid,dict(operation_id=str(uuid4()),chapter_id=None,version_id=right['id'],confirmed=True));server=create_server(fixture.db,port=0,provider_path=fixture.providers.path,enable_model_generation=True);presets=CreationPresets(server.service);step=dict(step='style_trial',**{k:v for k,v in fixture.options(connection).items() if k!='prompt_version'});made=presets.save(fixture.pid,dict(operation_id=str(uuid4()),preset_id=None,name='试写专用配置',settings=dict(steps=[step],style_id=right['id'],style_prompt='不应隐式外发的预设提示MARKER。',manuscript_language='zh-CN',budget=dict(max_external_calls=4,max_reserved_output_tokens=4096,risk_budget=2.0,allow_unknown_cost=True)),expected_revision=server.service.get(fixture.pid)['revision']));presets.choose(fixture.pid,dict(operation_id=str(uuid4()),version_id=made['version_id'],confirmed=True,expected_revision=server.service.get(fixture.pid)['revision']));stop=threading.Event()
def trace():
 while not stop.wait(.03):
  value=dict(calls=wire['calls'],left=left['id'],right=right['id']);temporary=args.trace.with_suffix('.tmp');temporary.write_text(json.dumps(value),encoding='utf-8');os.replace(temporary,args.trace)
worker=threading.Thread(target=trace,daemon=True);worker.start()
try:print('http://127.0.0.1:'+str(server.server_port),flush=True);server.serve_forever(poll_interval=.02)
finally:stop.set();worker.join(1);server.server_close();stack.close();fixture.doCleanups()
