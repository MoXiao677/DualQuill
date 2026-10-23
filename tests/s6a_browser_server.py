"""S6-A内部虚构供应商与临时DPAPI；不增加产品测试开关。"""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
from test_s5c_models import ModelTests,FAKE_KEY
from novel_writer.application.provider_connections import PROVIDERS
from novel_writer.ui.server import create_server
parser=argparse.ArgumentParser();parser.add_argument('--enabled',action='store_true');parser.add_argument('--trace',type=Path,required=True);args=parser.parse_args()
fixture=ModelTests('test_real_wire_completion_usage_and_atomic_candidate_adoption_once');fixture.setUp();fixture.mode='comparison';fixture.providers.save(id='catie',base_url=PROVIDERS['catie']['base_url'],model_id='second-configured-model',api_key=FAKE_KEY);fixture.save('save_writing_rules',content='共同写作规则：叙事清晰，不重复堆叠。')
class Calls(list):
    def save(self):args.trace.write_text(json.dumps(dict(count=len(self),paths=[c['path'] for c in self])),encoding='utf8')
    def append(self,value):super().append(value);self.save()
fixture.calls=Calls();fixture.calls.save();server=create_server(fixture.db,port=0,provider_path=fixture.path,enable_model_generation=args.enabled,model_adapter=fixture.adapter)
try:print('http://127.0.0.1:'+str(server.server_address[1]),flush=True);server.serve_forever(poll_interval=.02)
finally:server.server_close();fixture.doCleanups()
