"""Own-directory fictional fixture for the dedicated workflow browser check."""
import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
from test_c14_workflows import DedicatedWorkflowTests
from novel_writer.ui.server import create_server

parser=argparse.ArgumentParser()
parser.add_argument('--trace',type=Path,required=True)
args=parser.parse_args()
fixture=DedicatedWorkflowTests('test_serial_dedicated_chain_consumes_real_typed_candidates_and_human_diff')
fixture.setUp();fixture.setup_supplier();fixture.f.save('save_chapter',chapter_id=fixture.f.cid,content='')
class Calls(list):
    def save(self):args.trace.write_text(json.dumps(dict(loopback_calls=len(self),real_provider_calls=0)),encoding='utf-8')
    def append(self,value):super().append(value);self.save()
fixture.wire=Calls();fixture.wire.save()
server=create_server(fixture.f.db,port=0,provider_path=fixture.f.path,enable_model_generation=True,model_adapter=fixture.f.adapter)
try:
    print('http://127.0.0.1:'+str(server.server_address[1]),flush=True)
    server.serve_forever(poll_interval=.02)
finally:
    server.server_close();fixture.doCleanups()
