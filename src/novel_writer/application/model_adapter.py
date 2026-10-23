"""实际Chat Completions HTTP传输；无自动重试。内部loopback注入仅供测试构造。"""
from dataclasses import replace
from urllib.parse import urlsplit
import http.client,io,json,select,socket,ssl,threading,time
from novel_writer.domain.model_contract import *
from novel_writer.domain.tasks import require

class ModelExecutionFailure(RuntimeError):
    def __init__(self,response):self.response=response;super().__init__(response.error_code or 'model_response_failed')

class CancellableReadSocket:
    """Keep header/body reads interruptible on Windows, including before headers.

    A shutdown from another thread does not reliably wake a blocking recv there.
    The request has already been sent before this read-only proxy is installed.
    """
    def __init__(self,transport,token):
        self.transport=transport;self.token=token;transport.setblocking(False)
    def __getattr__(self,name):return getattr(self.transport,name)
    def recv_into(self,buffer):
        while True:
            self.token.checkpoint()
            try:return self.transport.recv_into(buffer)
            except (BlockingIOError,ssl.SSLWantReadError):read,write=[self.transport],[]
            except ssl.SSLWantWriteError:read,write=[],[self.transport]
            select.select(read,write,[],min(.02,max(0,self.token.deadline-time.monotonic())))
    def makefile(self,mode='r',buffering=None,**kwargs):
        require(mode=='rb','HTTP response must use binary reads')
        self.transport._io_refs+=1
        raw=socket.SocketIO(self,mode)
        return raw if buffering==0 else io.BufferedReader(raw,io.DEFAULT_BUFFER_SIZE if buffering in (None,-1) else buffering)

def empty_response(**changes):
    value=dict(http_status=None,response_id=None,reported_model=None,finish_reason=None,usage=Usage(prompt_tokens=None,completion_tokens=None,total_tokens=None),output_text='',raw_response='',raw_truncated=False,redacted=False,complete=False,error_code=None);value.update(changes);return ProviderResponse(**value)

class ChatHttpTransport:
    def capture_response(self,safe_text):
        """Trusted specializations may retain bounded, already-redacted wire provenance."""
        pass
    def __init__(self,*,endpoint_override=None):
        if endpoint_override is not None:
            parsed=urlsplit(endpoint_override);require(parsed.scheme=='http' and parsed.hostname=='127.0.0.1' and parsed.username is None and parsed.password is None and not parsed.query and not parsed.fragment,'内部供应商替身仅允许loopback HTTP')
        self._endpoint_override=endpoint_override

    def request_spec(self,binding,saved):
        url=urlsplit(self._endpoint_override or saved['base_url'])
        return url,url.path.rstrip('/')+'/chat/completions',{'Authorization':'Bearer '+saved['api_key'],'Content-Type':'application/json','Accept':'application/json','User-Agent':'AI-Novel-Writer/0.3'}

    def connection(self,url,token,saved):
        connection_type=http.client.HTTPConnection if self._endpoint_override else http.client.HTTPSConnection
        return connection_type(url.hostname,url.port,timeout=max(.1,token.deadline-time.monotonic()))

    def normalize_response(self,payload,saved):return payload

    def send(self,binding,saved,token,max_output_chars):
        from novel_writer.application.task_protocol import TaskCancelled,TaskTimeout
        token.checkpoint();secret=saved['api_key'];url,path,headers=self.request_spec(binding,saved)
        connection=self.connection(url,token,saved);stop=threading.Event();raw=b'';status=None;error=None;active_socket=[None]
        stream=None;stream_payload=None;stream_wire_text=None
        if saved.get('stream_mode')=='sse':
            from novel_writer.application.sse_protocols import StreamDecoder,StreamFailure
            stream=StreamDecoder(saved['protocol'],max_output_chars,secret,token.publish)
        def abort():
            while not stop.wait(.02):
                if token.event.is_set() or time.monotonic()>=token.deadline:
                    sock=connection.sock or active_socket[0]
                    if sock is not None:
                        try:sock.shutdown(socket.SHUT_RDWR)
                        except OSError:pass
                    return
        watcher=threading.Thread(target=abort,daemon=True);watcher.start()
        try:
            token.checkpoint();connection.connect();active_socket[0]=connection.sock;token.checkpoint()
            connection.request('POST',path,body=binding.request_body.encode('utf8'),headers=headers)
            connection.sock=CancellableReadSocket(connection.sock,token);active_socket[0]=connection.sock
            response=connection.getresponse();status=response.status
            if stream is not None:
                if status!=200:error='provider_http_'+str(status)
                elif response.getheader('Content-Type','').split(';')[0].strip().lower()!='text/event-stream':error='invalid_content_type'
            while True:
                if error is not None:break
                token.checkpoint();chunk=response.read1(4096)
                if not chunk:break
                raw+=chunk
                if len(raw)>1024*1024:error='response_too_large';break
                if stream is not None:stream.feed(chunk)
            if error is None and response.length not in (None,0):error='response_truncated'
            if error is None and status!=200:error='provider_http_'+str(status)
            if error is None and stream is None and response.getheader('Content-Type','').split(';')[0].strip().lower()!='application/json':error='invalid_content_type'
            if error is None and stream is not None:stream_payload=stream.finish()
            token.checkpoint()
        except TaskCancelled:error='cancelled'
        except TaskTimeout:error='timeout'
        except (ValueError,TypeError,KeyError,AttributeError) as failure:
            if stream is None:raise
            error=str(failure) if isinstance(failure,StreamFailure) else 'invalid_stream_structure'
        except (OSError,TimeoutError,http.client.HTTPException):
            error='cancelled' if token.event.is_set() else 'timeout' if time.monotonic()>=token.deadline else 'transport_or_truncated'
        finally:
            stop.set()
            try:connection.close()
            finally:watcher.join()
        if stream is not None:
            if error is None:
                stream_wire_text=raw.decode('utf8',errors='strict')
                if secret and secret in stream_wire_text:error='credential_echo_redacted'
            if error is not None:
                if token._publish is not None:token._publish('')
                return empty_response(http_status=status,error_code=error,redacted=error=='credential_echo_redacted',raw_response='[SSE rejected: '+error+']')
            raw=json.dumps(stream_payload,ensure_ascii=False,separators=(',',':')).encode('utf8')
        try:decoded=raw.decode('utf8',errors='strict')
        except UnicodeError:decoded=raw.decode('utf8',errors='replace');error=error or 'invalid_utf8'
        redacted=bool(secret) and secret in decoded;safe=decoded.replace(secret,'[redacted]') if secret else decoded;payload=None
        try:
            from novel_writer.storage.json_codec import strict_json_loads
            payload=strict_json_loads(decoded)
            if secret and secret in json.dumps(payload,ensure_ascii=False):
                redacted=True
                def clean(value):
                    if isinstance(value,str):return value.replace(secret,'[redacted]')
                    if isinstance(value,list):return [clean(v) for v in value]
                    if isinstance(value,dict):return {clean(k):clean(v) for k,v in value.items()}
                    return value
                payload=clean(payload);safe=json.dumps(payload,ensure_ascii=False,separators=(',',':'))
        except (ValueError,UnicodeError):error=error or 'invalid_json'
        if redacted:error='credential_echo_redacted'
        output='';finish=None;identifier=None;reported=None;usage=Usage(prompt_tokens=None,completion_tokens=None,total_tokens=None)
        if payload is not None and error is None:
            try:
                if stream is None:payload=self.normalize_response(payload,saved)
                require(type(payload) is dict,'响应不是对象');choices=payload.get('choices');require(type(choices) is list and len(choices)==1,'响应候选数量不符')
                choice=choices[0];require(type(choice) is dict,'响应候选非法');message=choice.get('message');require(type(message) is dict and message.get('role')=='assistant','响应不是assistant文本');output=message.get('content');require(type(output) is str,'响应正文不是文本')
                finish=choice.get('finish_reason');require(type(finish) is str and len(finish)<=100,'终止原因缺失/非法')
                if message.get('tool_calls') or message.get('function_call') or message.get('refusal'):error='tool_output_rejected'
                elif finish!='stop':error='noncomplete_finish_reason'
                elif not output.strip():error='empty_output'
                elif len(output)>max_output_chars:error='output_too_long'
                identifier=payload.get('id');reported=payload.get('model')
                require(identifier is None or (type(identifier) is str and len(identifier)<=300),'响应ID非法');require(reported is None or (type(reported) is str and len(reported)<=300),'响应模型非法')
                value=payload.get('usage')
                if value is not None:
                    require(type(value) is dict,'响应用量非法');counts={}
                    for name in ('prompt_tokens','completion_tokens','total_tokens'):
                        count=value.get(name);require(count is None or (type(count) is int and count>=0),'用量必须为实际非负整数或未知');counts[name]=count
                    usage=Usage(**counts)
            except (ValueError,KeyError,TypeError):error='invalid_response_structure';output=output if type(output) is str else '';finish=finish if type(finish) is str else None;identifier=None;reported=None
        self.capture_response(safe)
        if stream_wire_text is not None:safe=stream_wire_text
        return ProviderResponse(http_status=status,response_id=identifier,reported_model=reported,finish_reason=finish,usage=usage,output_text=output[:max_output_chars],raw_response=safe[:65536],raw_truncated=len(safe)>65536,redacted=redacted,complete=error is None,error_code=error)

class ChatCompletionsAdapter:
    adapter_id='chat-completions-http-v1'
    capabilities=('rewrite_chapter','audit_chapter','draft_chapter','continue_chapter')
    def __init__(self,providers,*,enabled=False,transport=None):self.providers,self.enabled,self.transport=providers,enabled,transport or ChatHttpTransport()
    def validate_start(self,binding,confirmation):
        require(self.enabled and not self.providers.offline,'真实模型生成关闭；需明确启动启用且非离线维护')
        require(type(confirmation) is dict and set(confirmation)=={'confirm_external','request_sha256'} and confirmation['confirm_external'] is True and confirmation['request_sha256']==binding.request_sha256,'执行前须明确单次确认确切外发内容/预算与未知费用')
    def validate_preparation(self,task):
        self.providers.assert_prepared(task.frozen.parameters.binding.connection_id,task.created_at)
    def validate_options(self,options):
        self.providers.validate_sampling(options)
    def authorize(self,call):
        permit=call.permission;b=call.input.parameters.binding
        require(self.enabled and not self.providers.offline,'真实模型生成关闭；需明确启动启用且非离线维护')
        require(type(permit) is ExecutionPermit and permit.confirmed and (permit.task_id,permit.attempt_id,permit.request_sha256)==(call.task_id,call.attempt_id,b.request_sha256),'没有绑定本次确切外发请求的单次确认')
    def saved_connection(self,binding,confirmed):
        return self.providers.generation_connection(binding.connection_id,binding.model_id,enabled=self.enabled,confirmed=confirmed)
    def run(self,call,token):
        from novel_writer.application.task_protocol import AdapterResult
        self.authorize(call);token.checkpoint();b=call.input.parameters.binding
        try:saved=self.saved_connection(b,call.permission.confirmed)
        except (ValueError,OSError):raise ModelExecutionFailure(empty_response(error_code='connection_unavailable_or_changed')) from None
        token.checkpoint();response=self.transport.send(b,saved,token,call.input.parameters.max_output_chars)
        if not response.complete:raise ModelExecutionFailure(response)
        analysis=None;candidate_analysis=None;graph_output=None
        if b.prompt_version=='graph-extract-json-1':
            from novel_writer.domain.graph_extraction import verify
            try:graph_output=verify(response.output_text,call.input.parameters)
            except (ValueError,TypeError,KeyError):raise ModelExecutionFailure(replace(response,complete=False,error_code='invalid_graph_or_evidence')) from None
        elif b.prompt_version=='candidate-review-json-1':
            from novel_writer.domain.candidate_reviews import verify
            try:candidate_analysis=verify(response.output_text,call.input.parameters)
            except (ValueError,TypeError,KeyError):raise ModelExecutionFailure(replace(response,complete=False,error_code='invalid_candidate_analysis_or_evidence')) from None
        elif b.prompt_version in ('workflow-idea-json-1','workflow-outline-json-1'):
            from novel_writer.domain.workflow_stages import typed_result
            try:typed_result(call.input,response.output_text)
            except (ValueError,TypeError,KeyError):raise ModelExecutionFailure(replace(response,complete=False,error_code='invalid_workflow_typed_plan')) from None
        elif call.capability=='audit_chapter':
            try:analysis=verify_audit(response.output_text,call.input.parameters)
            except (ValueError,TypeError,KeyError):raise ModelExecutionFailure(replace(response,complete=False,error_code='invalid_model_analysis_or_evidence')) from None
        return AdapterResult(task_id=call.task_id,attempt_id=call.attempt_id,capability=call.capability,output_text=response.output_text,complete=True,model_response=response,model_analysis=analysis,candidate_audit_output=candidate_analysis,graph_output=graph_output)
