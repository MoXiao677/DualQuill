"""V28 explicit sampling options; absent fields preserve legacy frozen bytes."""
from dataclasses import dataclass
import math

@dataclass(frozen=True,kw_only=True)
class Sampling:
    top_p:float|None
    seed:int|None
    stop:tuple[str,...]
    temperature_mode:str='configured'
    chat_token_field:str='max_tokens'
    def __post_init__(self):
        from novel_writer.domain.tasks import check_types,require
        check_types(type(self),self)
        require(self.top_p is None or math.isfinite(self.top_p) and 0<=self.top_p<=1,'top_p 必须为 0 至 1 的有限数字')
        require(self.seed is None or -(2**31)<=self.seed<2**31,'seed 必须为有符号 32 位整数')
        require(len(self.stop)<=4 and all(0<len(s)<=200 and '\x00' not in s for s in self.stop),'stop 最多四项，每项非空且不超过 200 字符')
        require(self.temperature_mode in ('configured','omit'),'温度模式非法')
        require(self.chat_token_field in ('max_tokens','max_completion_tokens'),'Chat 输出令牌字段非法')
        require(self.top_p is not None or self.seed is not None or bool(self.stop) or self.temperature_mode!='configured' or self.chat_token_field!='max_tokens','未选择采样参数时请省略 sampling')

def canonical(value):
    from novel_writer.domain.tasks import parse,encode,require
    require(type(value) is dict and {'top_p','seed','stop'}<=set(value)<={'top_p','seed','stop','temperature_mode','chat_token_field'},'采样字段缺失或未知')
    value=dict(value)
    if value['top_p'] is not None:
        require(type(value['top_p']) in (int,float) and 0<=value['top_p']<=1,'top_p 必须为0至1的有限数字');value['top_p']=float(value['top_p'])
    return encode(parse(Sampling,value))

def kwargs(options):
    from novel_writer.domain.tasks import parse
    return {'sampling':parse(Sampling,options['sampling'])} if options.get('sampling') is not None else {}

def requested(value):
    if value is None:return set()
    value=canonical(value)
    return {name for name in ('top_p','seed','stop') if value[name] is not None and value[name]!=[]}

def apply(payload,protocol,options):
    from novel_writer.domain.tasks import require
    if options.get('sampling') is None:return payload
    value=canonical(options['sampling'])
    require(protocol=='openai-chat' or value.get('chat_token_field','max_tokens')=='max_tokens','只有 Chat 协议可选择输出令牌字段')
    require(protocol!='anthropic-messages' or value['seed'] is None,'Messages 原生协议未支持 seed，不能静默忽略')
    target=payload['generationConfig'] if protocol=='gemini-content' else payload
    if value.get('temperature_mode')=='omit':target.pop('temperature',None)
    if protocol=='openai-chat' and value.get('chat_token_field')=='max_completion_tokens' and 'max_tokens' in payload:
        payload['max_completion_tokens']=payload.pop('max_tokens')
    names={'top_p':'topP','seed':'seed','stop':'stopSequences'} if protocol=='gemini-content' else {'top_p':'top_p','seed':'seed','stop':'stop_sequences' if protocol=='anthropic-messages' else 'stop'}
    for name in requested(value):target[names[name]]=value[name]
    if protocol=='anthropic-messages' and value['top_p'] is not None:payload.pop('temperature',None)
    return payload

def validate_body(body,protocol,value):
    if value is None:return
    import json
    from novel_writer.domain.tasks import encode,require
    payload=json.loads(body);options={'sampling':encode(value)}
    expected=apply({'generationConfig':{}},protocol,options)
    actual=payload.get('generationConfig',{}) if protocol=='gemini-content' else payload
    target=expected.get('generationConfig',{}) if protocol=='gemini-content' else expected
    names=('topP','seed','stopSequences') if protocol=='gemini-content' else ('top_p','seed','stop_sequences' if protocol=='anthropic-messages' else 'stop')
    require(all(actual.get(key)==target.get(key) and (key in actual)==(key in target) for key in names),'采样参数与冻结原生请求不一致')
    require(protocol!='anthropic-messages' or value.top_p is None or 'temperature' not in payload,'Messages top_p 模式不能同时发送温度')
    require(value.temperature_mode!='omit' or 'temperature' not in actual,'供应商默认温度模式不能发送 temperature')
    require(protocol=='openai-chat' or value.chat_token_field=='max_tokens','非 Chat 协议不能选择 Chat token 字段')
    if protocol=='openai-chat' and value.chat_token_field=='max_completion_tokens':
        require('max_completion_tokens' in payload and 'max_tokens' not in payload,'Chat 输出令牌字段与冻结配置不一致')

def contains(value):
    if isinstance(value,dict):return value.get('sampling') is not None or any(contains(v) for v in value.values() if isinstance(v,(dict,list,tuple)))
    if isinstance(value,(list,tuple)):return any(contains(v) for v in value)
    return False

def contains_native(value):
    if isinstance(value,dict):
        selected=value.get('sampling')
        return isinstance(selected,dict) and bool({'temperature_mode','chat_token_field'}&set(selected)) or any(contains_native(v) for v in value.values() if isinstance(v,(dict,list,tuple)))
    if isinstance(value,(list,tuple)):return any(contains_native(v) for v in value)
    return False

