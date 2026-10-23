"""Only this test harness maps verified synthetic public addresses to a loopback wire."""
import argparse,json,os,sys,threading
from pathlib import Path
from contextlib import ExitStack
from uuid import uuid4
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src'),str(Path(__file__).parent)]
from test_public_search import SearchTests,search_wire,pages
from novel_writer.ui.server import create_server
from novel_writer.application.creation_presets import CreationPresets
parser=argparse.ArgumentParser();parser.add_argument('--trace',type=Path,required=True);args=parser.parse_args();fixture=SearchTests('test_wire_grounding_builds_only_cited_sources_and_preserves_utf8_byte_supports');fixture.setUp();stack=ExitStack();wire=stack.enter_context(search_wire());port,page_calls=stack.enter_context(pages());saved=fixture.connection(wire,'gemini-content');server=create_server(fixture.db,port=0,provider_path=fixture.providers.path,enable_model_generation=True);reader,verified=fixture.reader(port);server.public_search.reader=reader;presets=CreationPresets(server.service);profiles=[dict(step=step,**{key:value for key,value in fixture.options(saved).items() if key!='prompt_version'}) for step in ('search','style_analysis')];version=presets.save(fixture.pid,dict(operation_id=str(uuid4()),preset_id=None,name='虚构搜索与文风分析',settings=dict(steps=profiles,style_id=None,style_prompt='',manuscript_language='zh-CN',budget=dict(max_external_calls=4,max_reserved_output_tokens=4096,risk_budget=2.0,allow_unknown_cost=True)),expected_revision=server.service.get(fixture.pid)['revision']));presets.choose(fixture.pid,dict(operation_id=str(uuid4()),version_id=version['version_id'],confirmed=True,expected_revision=server.service.get(fixture.pid)['revision']));stop=threading.Event()
def trace():
 while not stop.wait(.03):
  payload=dict(query_calls=sum(bool(v.get('tools')) for v in wire['calls']),style_calls=sum(not v.get('tools') for v in wire['calls']),pages=page_calls,verified_hosts=[v[0] for v in verified]);temporary=args.trace.with_suffix('.tmp');temporary.write_text(json.dumps(payload),encoding='utf-8');os.replace(temporary,args.trace)
worker=threading.Thread(target=trace,daemon=True);worker.start()
try:print('http://127.0.0.1:'+str(server.server_port),flush=True);server.serve_forever(poll_interval=.02)
finally:stop.set();worker.join(1);server.server_close();stack.close();fixture.doCleanups()
