"""Credential-free destination snapshots and pure model-protocol request shapes."""
from dataclasses import dataclass
from hashlib import sha256
import ipaddress,json,re
from urllib.parse import urlsplit
from uuid import UUID
from novel_writer.domain.models import DataValidationError

from novel_writer.domain.sampling import apply as sampling_payload

PROTOCOL_NAMES=('openai-chat','anthropic-messages','gemini-content')
def require(ok,message):
    if not ok:raise DataValidationError(message)

def validate_endpoint(value,*,allow_local=False):
    require(type(value) is str and 0<len(value)<=500 and type(allow_local) is bool,'供应商地址或范围非法')
    require(not any(ord(char)<33 for char in value) and not any(char in value for char in ('\\','%','?','#')),'地址不能包含空白、转义、查询或片段')
    parsed=urlsplit(value)
    require(parsed.scheme in ('https','http') and parsed.hostname and parsed.username is None and parsed.password is None,'供应商须是明确的HTTPS地址；本机HTTP需单独允许')
    require(not parsed.query and not parsed.fragment and '..' not in parsed.path.split('/') and (parsed.port is None or 1<=parsed.port<=65535),'供应商地址范围非法')
    host=parsed.hostname.lower()
    try:address=ipaddress.ip_address(host)
    except ValueError:
        require(re.fullmatch('[a-zA-Z0-9.-]+',host) is not None,'供应商域名非法');local=host=='localhost'
    else:
        local=address.is_loopback;require(address.is_global or local and allow_local,'不允许私网、链路本地或元数据地址')
    require(not local or allow_local,'本机模型必须明确允许')
    require(parsed.scheme=='https' or local and allow_local,'公开供应商必须使用HTTPS')
    return parsed

@dataclass(frozen=True,kw_only=True)
class ConnectionDestination:
    connection_id:str
    revision:str
    protocol:str
    base_url:str
    allow_local:bool
    sha256:str
    stream_mode:str='json'
    def __post_init__(self):
        for name in ('connection_id','revision','protocol','base_url','sha256'):require(type(getattr(self,name)) is str,'供应商快照类型非法')
        require(type(self.allow_local) is bool and self.protocol in PROTOCOL_NAMES,'供应商协议/范围非法')
        for value in (self.connection_id,self.revision):
            try:require(str(UUID(value))==value,'供应商快照身份非法')
            except ValueError:raise DataValidationError('供应商快照身份非法') from None
        validate_endpoint(self.base_url,allow_local=self.allow_local)
        fields={name:getattr(self,name) for name in ('connection_id','revision','protocol','base_url','allow_local')}
        require(self.stream_mode in ('json','sse'),'流式配置非法')
        if self.stream_mode=='sse':fields['stream_mode']='sse'
        require(self.sha256==sha256(json.dumps(fields,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest(),'供应商去向快照校验失败')

def request_payload(protocol,messages,options,*,search=False):
    require(protocol in PROTOCOL_NAMES and type(messages) is list and all(type(m) is dict and set(m)=={'role','content'} and m['role'] in ('system','user','assistant') and type(m['content']) is str for m in messages),'模型消息契约非法')
    require(type(search) is bool and (not search or protocol=='gemini-content'),'所选协议没有已实现的搜索工具')
    stream=options.get('destination',{}).get('stream_mode','json')=='sse'
    require(not search or not stream,'公开搜索暂不支持SSE；请使用JSON连接')
    if protocol=='openai-chat':return sampling_payload(dict(model=options['model_id'],messages=messages,temperature=options['temperature'],max_tokens=options['max_tokens'],stream=stream),protocol,options)
    system='\n\n'.join(m['content'] for m in messages if m['role']=='system')
    if protocol=='anthropic-messages':
        sampling=options.get('sampling') or {}
        require(sampling.get('temperature_mode')=='omit' or sampling.get('top_p') is not None or 0<=options['temperature']<=1,'Messages协议温度范围为0至1')
        body=dict(model=options['model_id'],system=system,messages=[m for m in messages if m['role']!='system'],temperature=options['temperature'],max_tokens=options['max_tokens'])
        if stream:body['stream']=True
        return sampling_payload(body,protocol,options)
    payload=dict(systemInstruction=dict(parts=[dict(text=system)]),contents=[dict(role='model' if m['role']=='assistant' else 'user',parts=[dict(text=m['content'])]) for m in messages if m['role']!='system'],generationConfig=dict(temperature=options['temperature'],maxOutputTokens=options['max_tokens']))
    if search:payload['tools']=[dict(google_search={})]
    return sampling_payload(payload,protocol,options)

def canonical_messages(body,protocol):
    if protocol=='openai-chat':return body['messages']
    if protocol=='anthropic-messages':return [dict(role='system',content=body['system']),*body['messages']]
    return [dict(role='system',content=''.join(p['text'] for p in body['systemInstruction']['parts'])),*[dict(role='assistant' if c['role']=='model' else 'user',content=''.join(p['text'] for p in c['parts'])) for c in body['contents']]]
