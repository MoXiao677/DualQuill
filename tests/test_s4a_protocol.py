"""唯一adapter协议边界：typed冻结输入、取消、结果归属。"""
from dataclasses import FrozenInstanceError,replace
from importlib import util,import_module
import hashlib,json,sys,threading,time,unittest
from pathlib import Path
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))

def frozen_raw():
    from novel_writer.domain.memory import fingerprint
    target=dict(chapter_id='p1-c5',version_id=None,title='第五章',text='旧正文',status='draft',number=5,
        source_sha256=fingerprint(dict(number=5,title='第五章',content='旧正文',status='draft')))
    options=dict(chapter_id='p1-c5',scope='previous',budget_chars=6000,include_current_plan=False,
        include_book_outline=False,include_characters=False,character_ids=[],include_worldbuilding=False,
        include_writing_rules=False,include_memories=False,memory_ids=[],include_search_results=False,search_selections=[])
    dependency=dict(project_id='p1',kind='chapter',entity_id='p1-c5',version_id=None,source_sha256=target['source_sha256'],
        source_revision=1,chapter_id='p1-c5',position_number=5,references=[],use='target',scope='book',file_path=None,memory_fresh=None)
    text='已保存上下文'
    return dict(project_id='p1',chapter_id='p1-c5',source_revision=1,target=target,context_text=text,
        context_sha256=hashlib.sha256(text.encode()).hexdigest(),context_options=options,dependencies=[dependency],
        parameters=dict(instruction='整章重写',max_output_chars=10000,timeout_ms=1000),skill_snapshots=[])

class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(util.find_spec('novel_writer.application.task_protocol'),'缺少共享registry/adapter协议')
        self.p=import_module('novel_writer.application.task_protocol');self.d=import_module('novel_writer.domain.tasks')
    def call(self):
        return self.p.AdapterCall(task_id=str(uuid4()),attempt_id=str(uuid4()),capability='rewrite_chapter',input=self.d.FrozenInput.from_dict(frozen_raw()))
    def test_input_is_deeply_immutable_and_detached_from_raw_workspace(self):
        raw=frozen_raw();value=self.d.FrozenInput.from_dict(raw);raw['target']['text']='外部改写'
        self.assertEqual(value.target.text,'旧正文')
        with self.assertRaises(FrozenInstanceError):value.target.text='篡改'
        self.assertIsInstance(value.dependencies,tuple)
        with self.assertRaises(ValueError):self.d.FrozenInput.from_dict(dict(frozen_raw(),validated=True))
    def test_registry_default_unavailable_unknown_capability_and_forged_input_rejected(self):
        registry=self.p.AdapterRegistry();call=self.call();token=self.p.CancellationToken(threading.Event(),time.monotonic()+1)
        with self.assertRaises(ValueError):registry.execute(call,token)
        registry.register('rewrite_chapter',self.p.LocalProtocolAdapter())
        with self.assertRaises(ValueError):registry.register('arbitrary_url',self.p.LocalProtocolAdapter())
        with self.assertRaises(ValueError):registry.execute({'input':frozen_raw(),'validated':True},token)
    def test_same_registry_protocol_success_cancel_timeout_and_wrong_result(self):
        registry=self.p.AdapterRegistry();registry.register('rewrite_chapter',self.p.LocalProtocolAdapter(delay_seconds=0))
        call=self.call();result=registry.execute(call,self.p.CancellationToken(threading.Event(),time.monotonic()+1))
        self.assertEqual(result.task_id,call.task_id);self.assertIn('本地协议验证',result.output_text)
        event=threading.Event();event.set()
        with self.assertRaises(self.p.TaskCancelled):registry.execute(call,self.p.CancellationToken(event,time.monotonic()+1))
        with self.assertRaises(self.p.TaskTimeout):registry.execute(call,self.p.CancellationToken(threading.Event(),time.monotonic()-1))
        class Wrong:
            adapter_id='local-protocol-demo-v1'
            def run(this,request,token):return self.p.AdapterResult(task_id='wrong',attempt_id=request.attempt_id,capability=request.capability,output_text='bad',complete=True)
        other=self.p.AdapterRegistry();other.register('rewrite_chapter',Wrong())
        with self.assertRaises(ValueError):other.execute(call,self.p.CancellationToken(threading.Event(),time.monotonic()+1))
    def test_incomplete_or_dict_result_never_passes_registry(self):
        outer=self
        for output in ('dict','partial'):
            class Bad:
                adapter_id='local-protocol-demo-v1'
                def run(this,call,token):
                    return {'text':'fake'} if output=='dict' else outer.p.AdapterResult(task_id=call.task_id,attempt_id=call.attempt_id,capability=call.capability,output_text='partial',complete=False)
            registry=self.p.AdapterRegistry();registry.register('rewrite_chapter',Bad())
            with self.subTest(output=output),self.assertRaises(ValueError):registry.execute(self.call(),self.p.CancellationToken(threading.Event(),time.monotonic()+1))

    def test_direct_construction_and_bypassed_corruption_are_validated_before_adapter(self):
        good=self.d.FrozenInput.from_dict(frozen_raw());self.assertEqual(replace(good,source_revision=1),good)
        with self.assertRaises(ValueError):replace(good,dependencies=list(good.dependencies))
        with self.assertRaises(ValueError):replace(good.target,number=True)
        with self.assertRaises(ValueError):self.p.AdapterCall(task_id='bad',attempt_id=str(uuid4()),capability='rewrite_chapter',input=good)
        called=[];outer=self
        class Spy:
            adapter_id='local-protocol-demo-v1'
            def run(this,call,token):called.append(True);return outer.p.AdapterResult(task_id=call.task_id,attempt_id=call.attempt_id,capability=call.capability,output_text='valid',complete=True)
        registry=self.p.AdapterRegistry();registry.register('rewrite_chapter',Spy());call=self.call()
        object.__setattr__(call.input.target,'number',False)
        with self.assertRaises(ValueError):registry.execute(call,self.p.CancellationToken(threading.Event(),time.monotonic()+1))
        self.assertEqual(called,[])
        call=self.call();object.__setattr__(call,'attempt_id','invalid-attempt')
        with self.assertRaises(ValueError):registry.execute(call,self.p.CancellationToken(threading.Event(),time.monotonic()+1))
        self.assertEqual(called,[])

if __name__=='__main__':unittest.main()
