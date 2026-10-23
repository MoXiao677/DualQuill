"""Declared model protocols over the shared bounded/cancellable HTTP transport.

Primary contracts: ai.google.dev/api/generate-content and
platform.claude.com/docs/en/api/messages. No redirects or environment credentials.
"""
from datetime import datetime,timezone
import http.client
import ipaddress
import json
import re
import socket
import errno
import select
import ssl
import threading
import time
from urllib.parse import urlsplit,quote
from novel_writer.application.model_adapter import ChatHttpTransport,ChatCompletionsAdapter,empty_response
from novel_writer.domain.connections import validate_endpoint as checked_endpoint,request_payload as checked_payload
from novel_writer.domain.tasks import require

PROTOCOLS={
    'openai-chat':dict(name='Chat Completions compatible',native=False,search=False),
    'anthropic-messages':dict(name='Anthropic Messages',native=True,search=False),
    'gemini-content':dict(name='Google Gemini generateContent',native=True,search=True),
}

def validate_endpoint(value,*,allow_local=False):return checked_endpoint(value,allow_local=allow_local)

def connection_for(saved,timeout,*,token=None,_url_validator=None,_resolver=None,_connector=None):
    deadline=min(time.monotonic()+timeout,token.deadline) if token is not None else time.monotonic()+timeout
    def remaining():
        if token is not None:token.checkpoint()
        seconds=deadline-time.monotonic()
        if seconds<=0:raise TimeoutError('Destination deadline expired')
        return seconds
    parsed=(_url_validator or validate_endpoint)(saved['base_url'],allow_local=saved['allow_local'])
    port=parsed.port or (443 if parsed.scheme=='https' else 80)
    result=[];finished=threading.Event()
    def resolve():
        try:result.append((_resolver or socket.getaddrinfo)(parsed.hostname,port,type=socket.SOCK_STREAM))
        except OSError:result.append(None)
        finally:finished.set()
    threading.Thread(target=resolve,daemon=True).start()
    while not finished.wait(min(.02,remaining())):pass
    remaining()
    if not result[0]:raise OSError('Destination resolution unavailable')
    addresses=[entry[4][0] for entry in result[0]]
    explicit_local=parsed.hostname.lower() in ('localhost','127.0.0.1','::1')
    for address in addresses:
        ip=ipaddress.ip_address(address)
        require(ip.is_global or saved['allow_local'] and explicit_local and ip.is_loopback,'供应商域名解析到未经允许的地址')
    if _connector is not None:return _connector(parsed,tuple(result[0]),remaining,token)
    connection=http.client.HTTPConnection(parsed.hostname,port,timeout=remaining())
    def connect():
        transport=None;last_error=None
        # Every resolved address was checked above. Only TCP establishment may
        # advance to another address; HTTP request bytes have not been sent yet.
        for entry in result[0]:
            remaining();transport=socket.socket(entry[0],entry[1],entry[2]);connection.sock=transport
            try:
                transport.setblocking(False);code=transport.connect_ex(entry[4])
                if code not in (0,errno.EINPROGRESS,errno.EWOULDBLOCK,errno.EALREADY,10035,10036,10037):raise OSError(code,'Destination connect failed')
                while code:
                    _,writable,errors=select.select([], [transport], [transport],min(.02,remaining()))
                    if writable or errors:
                        code=transport.getsockopt(socket.SOL_SOCKET,socket.SO_ERROR)
                        if code:raise OSError(code,'Destination connect failed')
                        break
                remaining();last_error=None;break
            except OSError as error:
                transport.close();connection.sock=None;last_error=error
            except BaseException:
                transport.close();connection.sock=None;raise
        if last_error is not None:raise last_error
        try:
            remaining()
            if parsed.scheme=='https':
                transport=ssl.create_default_context().wrap_socket(transport,server_hostname=parsed.hostname,do_handshake_on_connect=False);connection.sock=transport
                while True:
                    remaining()
                    try:transport.do_handshake();break
                    except ssl.SSLWantReadError:select.select([transport],[],[],min(.02,remaining()))
                    except ssl.SSLWantWriteError:select.select([],[transport],[],min(.02,remaining()))
            transport.settimeout(remaining())
        except Exception:transport.close();connection.sock=None;raise
    connection.connect=connect
    return connection

def request_payload(protocol,messages,options,*,search=False):return checked_payload(protocol,messages,options,search=search)

def request_spec(saved):
    protocol=saved['protocol'];require(protocol in PROTOCOLS,'未实现的模型协议')
    parsed=validate_endpoint(saved['base_url'],allow_local=saved['allow_local'])
    headers={'Content-Type':'application/json','Accept':'application/json','User-Agent':'AI-Novel-Writer/0.3'}
    key=saved['api_key'];suffix='/chat/completions'
    if protocol=='openai-chat':
        if key:headers['Authorization']='Bearer '+key
    elif protocol=='anthropic-messages':
        if key:headers['x-api-key']=key
        headers['anthropic-version']='2023-06-01';suffix='/messages'
    else:
        if key:headers['x-goog-api-key']=key
        suffix='/models/'+quote(saved['model_id'].removeprefix('models/'),safe='')+':generateContent'
    if saved.get('stream_mode')=='sse':
        headers['Accept']='text/event-stream'
        if protocol=='gemini-content':suffix=suffix.replace(':generateContent',':streamGenerateContent')+'?alt=sse'
    return parsed,parsed.path.rstrip('/')+suffix,headers

def normalized(payload,protocol):
    require(type(payload) is dict,'供应商响应不是对象')
    if protocol=='openai-chat':return payload
    if protocol=='anthropic-messages':
        require(payload.get('role')=='assistant' and type(payload.get('content')) is list,'Messages响应非法')
        parts=payload['content']
        # Thinking is protocol metadata, never assistant prose or a tool permit.
        # Unknown block types still fail closed; additive fields on known blocks
        # do not invalidate an otherwise usable text response.
        for part in parts:
            require(type(part) is dict,'Messages内容块非法')
            kind=part.get('type')
            require(kind in ('text','thinking','redacted_thinking'),'不接受工具或未知内容块')
            if kind=='text':require(type(part.get('text')) is str,'Messages文本块非法')
            elif kind=='thinking':require(type(part.get('thinking')) is str and type(part.get('signature')) is str,'Messages思考块非法')
            else:require(type(part.get('data')) is str,'Messages隐藏思考块非法')
        usage=payload.get('usage');require(usage is None or type(usage) is dict,'Messages用量格式非法');usage=usage or {};prompt=usage.get('input_tokens');completion=usage.get('output_tokens');total=prompt+completion if type(prompt) is int and type(completion) is int else None
        return dict(id=payload.get('id'),model=payload.get('model'),choices=[dict(message=dict(role='assistant',content=''.join(part['text'] for part in parts if part['type']=='text')),finish_reason='stop' if payload.get('stop_reason') in ('end_turn','stop_sequence') else str(payload.get('stop_reason')))],usage=dict(prompt_tokens=prompt,completion_tokens=completion,total_tokens=total))
    feedback=payload.get('promptFeedback',{});require(type(feedback) is dict and not feedback.get('blockReason'),'Gemini输入被供应商阻止')
    candidates=payload.get('candidates');require(type(candidates) is list and len(candidates)==1,'Gemini响应候选数量非法')
    candidate=candidates[0];require(type(candidate) is dict and type(candidate.get('content')) is dict and candidate['content'].get('role','model')=='model','Gemini候选内容格式非法');parts=candidate['content'].get('parts');require(type(parts) is list and all(type(part) is dict and 'text' in part and type(part['text']) is str and type(part.get('thought',False)) is bool and not any(key in part for key in ('functionCall','executableCode','codeExecutionResult','inlineData','fileData')) for part in parts),'不接受工具或非文本输出')
    usage=payload.get('usageMetadata');require(usage is None or type(usage) is dict,'Gemini用量格式非法');usage=usage or {};return dict(id=payload.get('responseId'),model=payload.get('modelVersion'),choices=[dict(message=dict(role='assistant',content=''.join(part['text'] for part in parts if not part.get('thought'))),finish_reason='stop' if candidate.get('finishReason')=='STOP' else str(candidate.get('finishReason')))],usage=dict(prompt_tokens=usage.get('promptTokenCount'),completion_tokens=usage.get('candidatesTokenCount'),total_tokens=usage.get('totalTokenCount')))

class ConfiguredHttpTransport(ChatHttpTransport):
    def request_spec(self,binding,saved):return request_spec(saved)
    def connection(self,url,token,saved):return connection_for(saved,max(.001,token.deadline-time.monotonic()),token=token)
    def normalize_response(self,payload,saved):return normalized(payload,saved['protocol'])
    def send(self,binding,saved,token,max_output_chars):
        from novel_writer.application.task_protocol import TaskTimeout
        try:return super().send(binding,saved,token,max_output_chars)
        except TaskTimeout:return empty_response(error_code='timeout')
        except (ValueError,OSError):return empty_response(error_code='invalid_destination_or_transport')

class ConfiguredHttpAdapter(ChatCompletionsAdapter):
    adapter_id='configured-http-v2'
    def __init__(self,providers,*,enabled=False,transport=None):super().__init__(providers,enabled=enabled,transport=transport or ConfiguredHttpTransport())
    def freeze_destination(self,options):return self.providers.destination(options['connection_id'],options['model_id'],allow_model_override=options['prompt_version'] in ('chapter-draft-1','chapter-continue-1'))
    def validate_start(self,binding,confirmation):
        from novel_writer.domain.model_contract import ConfiguredModelBinding
        super().validate_start(binding,confirmation);require(type(binding) is ConfiguredModelBinding,'配置模型须有正式去向快照')
        self.saved_connection(binding,True,reserve=False)
    def saved_connection(self,binding,confirmed,*,reserve=True):
        from novel_writer.domain.tasks import encode
        return self.providers.generation_connection(binding.connection_id,binding.model_id,enabled=self.enabled,confirmed=confirmed,destination=encode(binding.destination),reserve=reserve,allow_model_override=binding.prompt_version in ('chapter-draft-1','chapter-continue-1'))

def list_models(saved):
    result=dict(ok=False,models=[],http_status=None,tested_at=datetime.now(timezone.utc).isoformat(),selected_model_available=False)
    connection=None
    try:
        parsed,_,headers=request_spec(saved);connection=connection_for(saved,15)
        connection.request('GET',parsed.path.rstrip('/')+'/models',headers=headers);response=connection.getresponse();result['http_status']=response.status
        raw=response.read(1024*1024+1)
        require(response.status==200 and len(raw)<=1024*1024 and response.getheader('Content-Type','').split(';')[0]=='application/json','模型目录响应不符')
        payload=json.loads(raw);entries=payload.get('models' if saved['protocol']=='gemini-content' else 'data');require(type(entries) is list and len(entries)<=2000,'模型目录格式不符')
        names=[]
        for entry in entries:
            name=entry.get('name' if saved['protocol']=='gemini-content' else 'id') if type(entry) is dict else None
            require(type(name) is str and 0<len(name)<=200 and all(ord(c)>=32 for c in name),'模型目录编号非法')
            if not saved['api_key'] or saved['api_key'] not in name:names.append(name.removeprefix('models/') if saved['protocol']=='gemini-content' else name)
        result.update(ok=True,models=list(dict.fromkeys(names)),selected_model_available=saved['model_id'].removeprefix('models/') in names,message='模型列表连接通过；尚未验证文本生成')
    except (ValueError,OSError,http.client.HTTPException,UnicodeError):result['message']={401:'凭据无效或已过期，请补配后重新检查',403:'该连接没有模型列表访问权限',404:'供应商没有兼容的模型列表入口，可手工填写模型编号',429:'供应商限流，请稍后明确重试；不会自动重试'}.get(result.get('http_status'),'模型列表不可用、响应不符或地址范围受限；没有执行生成')
    finally:
        if connection is not None:connection.close()
    return result
