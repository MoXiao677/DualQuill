"""仅浏览器验收内部构造供应商替身；产品没有此endpoint或测试模式。"""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
from test_s5c_models import ModelTests
from novel_writer.ui.server import create_server
parser=argparse.ArgumentParser();parser.add_argument('--enabled',action='store_true');parser.add_argument('--trace',type=Path,required=True);args=parser.parse_args()
fixture=ModelTests('test_real_wire_completion_usage_and_atomic_candidate_adoption_once');fixture.setUp();fixture.mode='auto';fixture.save('add_chapter',title='远方');other=fixture.service.get(fixture.pid)['document']['chapters'][-1]['id'];fixture.save('save_chapter',chapter_id=other,content='另一侧实际保存的港口正文，包含远方来信。')
class Calls(list):
    def save(self):args.trace.write_text(json.dumps(dict(count=len(self),paths=[c['path'] for c in self])),encoding='utf8')
    def append(self,value):super().append(value);self.save()
fixture.calls=Calls();fixture.calls.save()
server=create_server(fixture.db,port=0,provider_path=fixture.path,enable_model_generation=args.enabled,model_adapter=fixture.adapter)
try:
    print('http://127.0.0.1:'+str(server.server_address[1]),flush=True);server.serve_forever(poll_interval=.02)
finally:server.server_close();fixture.doCleanups()
