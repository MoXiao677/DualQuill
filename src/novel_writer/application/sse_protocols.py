"""Bounded SSE framing and explicit, single-response text protocol machines."""
import codecs,json
from novel_writer.storage.json_codec import strict_json_loads

class StreamFailure(ValueError):pass

class StreamDecoder:
    def __init__(self,protocol,limit,secret,publish):
        self.protocol,self.limit,self.secret,self.publish=protocol,limit,secret,publish
        self.decoder=codecs.getincrementaldecoder('utf-8')('strict')
        self.line='';self.data=[];self.event='';self.cr=False;self.first=True;self.size=0
        self.text='';self.done=False;self.stopped=False;self.started=False;self.block=None;self.next_block=0
        self.identifier=None;self.model=None;self.usage={};self.reason=None
    def fail(self,code):
        self.publish('');raise StreamFailure(code)
    def check(self,ok,code='invalid_stream_structure'):
        if not ok:self.fail(code)
    def feed(self,chunk):
        self.size+=len(chunk)
        self.check(self.size<=1024*1024,'response_too_large')
        try:value=self.decoder.decode(chunk)
        except UnicodeError:self.fail('invalid_utf8')
        for char in value:
            if self.first:
                self.first=False
                if char=='\ufeff':continue
            if self.cr:
                self.cr=False
                if char=='\n':continue
            if char in '\r\n':
                self._line();self.cr=char=='\r'
            else:self.line+=char
    def _line(self):
        line=self.line;self.line=''
        if not line:
            if self.data:self._event('\n'.join(self.data),self.event)
            self.data=[];self.event='';return
        if line.startswith(':'):return
        key,sep,value=line.partition(':')
        if sep and value.startswith(' '):value=value[1:]
        if key=='data':self.data.append(value)
        elif key=='event':self.event=value
    def _secrets(self,value):
        if isinstance(value,str):self.check(not self.secret or self.secret not in value,'credential_echo_redacted')
        elif isinstance(value,list):
            for v in value:self._secrets(v)
        elif isinstance(value,dict):
            for k,v in value.items():self._secrets(k);self._secrets(v)
    def _append(self,value):
        self.check(type(value) is str)
        self.text+=value
        self.check(len(self.text)<=self.limit,'output_too_long')
        self._secrets(self.text)
        withheld=0
        if self.secret:
            for length in range(1,min(len(self.secret)-1,len(self.text))+1):
                if self.text.endswith(self.secret[:length]):withheld=length
        self.publish(self.text[:-withheld] if withheld else self.text)
    def _usage(self,value,mapping):
        self.check(type(value) is dict)
        for source,target in mapping.items():
            if source in value:
                count=value[source];self.check(count is None or type(count) is int and count>=0)
                self.usage[target]=count
    def _identity(self,value,id_key='id',model_key='model'):
        for key,attr in ((id_key,'identifier'),(model_key,'model')):
            v=value.get(key)
            if v is not None:
                self.check(type(v) is str and len(v)<=300)
                old=getattr(self,attr);self.check(old is None or old==v);setattr(self,attr,v)
    def _event(self,data,event):
        self.check(not self.done,'stream_after_termination')
        if self.protocol=='openai-chat' and data=='[DONE]':
            self.check(self.stopped,'noncomplete_finish_reason');self.done=True;return
        try:value=strict_json_loads(data)
        except (ValueError,UnicodeError):self.fail('invalid_stream_json')
        self.check(type(value) is dict);self._secrets(value)
        self.check('error' not in value and event!='error','provider_stream_error')
        if self.protocol=='openai-chat':self._chat(value)
        elif self.protocol=='anthropic-messages':self._messages(value,event)
        elif self.protocol=='gemini-content':self._gemini(value)
        else:self.fail('unsupported_stream_protocol')
    def _chat(self,v):
        self._identity(v);choices=v.get('choices');self.check(type(choices) is list and len(choices)<=1)
        if 'usage' in v and v['usage'] is not None:self._usage(v['usage'],dict(prompt_tokens='prompt_tokens',completion_tokens='completion_tokens',total_tokens='total_tokens'))
        if not choices:return
        self.check(not self.stopped)
        c=choices[0];self.check(type(c) is dict and c.get('index',0)==0)
        d=c.get('delta');self.check(type(d) is dict)
        self.check(not any(d.get(k) for k in ('tool_calls','function_call','refusal')),'tool_output_rejected')
        self.check(d.get('role','assistant')=='assistant')
        if d.get('content') is not None:self._append(d['content'])
        reason=c.get('finish_reason')
        if reason is not None:
            self.check(reason=='stop','noncomplete_finish_reason');self.stopped=True;self.reason='stop'
    def _messages(self,v,event):
        kind=v.get('type');self.check(type(kind) is str and (not event or event==kind))
        if kind=='ping':return
        if kind=='message_start':
            self.check(not self.started);m=v.get('message');self.check(type(m) is dict and m.get('role')=='assistant' and m.get('content')==[] and m.get('stop_reason') is None)
            self.started=True;self._identity(m)
            if 'usage' in m:self._usage(m['usage'],dict(input_tokens='prompt_tokens',output_tokens='completion_tokens'))
            return
        self.check(self.started)
        if kind=='content_block_start':
            self.check(self.block is None and not self.stopped and v.get('index')==self.next_block)
            b=v.get('content_block');self.check(type(b) is dict and b.get('type') in ('text','thinking','redacted_thinking'),'tool_output_rejected')
            self.block=(v['index'],b['type'])
            if b['type']=='text':self._append(b.get('text',''))
            elif b['type']=='redacted_thinking':self.check(type(b.get('data')) is str)
        elif kind=='content_block_delta':
            self.check(self.block is not None and v.get('index')==self.block[0])
            d=v.get('delta');self.check(type(d) is dict)
            if self.block[1]=='text':self.check(d.get('type')=='text_delta');self._append(d.get('text'))
            elif self.block[1]=='thinking':self.check(d.get('type') in ('thinking_delta','signature_delta'))
            else:self.fail('invalid_stream_structure')
        elif kind=='content_block_stop':
            self.check(self.block is not None and v.get('index')==self.block[0]);self.block=None;self.next_block+=1
        elif kind=='message_delta':
            self.check(self.block is None and not self.stopped)
            d=v.get('delta');self.check(type(d) is dict and d.get('stop_reason') in ('end_turn','stop_sequence'),'noncomplete_finish_reason')
            self.stopped=True;self.reason='stop'
            if 'usage' in v:self._usage(v['usage'],dict(output_tokens='completion_tokens',input_tokens='prompt_tokens'))
        elif kind=='message_stop':self.check(self.stopped and self.block is None);self.done=True
        else:self.fail('invalid_stream_structure')
    def _gemini(self,v):
        self._identity(v,'responseId','modelVersion')
        self.check(not v.get('promptFeedback',{}).get('blockReason'),'provider_stream_blocked')
        if 'usageMetadata' in v:self._usage(v['usageMetadata'],dict(promptTokenCount='prompt_tokens',candidatesTokenCount='completion_tokens',totalTokenCount='total_tokens'))
        if not v.get('candidates'):
            # Some compatible streams send usage separately after the STOP.
            # A usage frame cannot complete a stream without completed text.
            self.check(self.stopped and 'usageMetadata' in v and v.get('candidates',[])==[])
            self.done=True;return
        candidates=v.get('candidates');self.check(type(candidates) is list and len(candidates)==1)
        c=candidates[0];self.check(type(c) is dict and c.get('index',0)==0 and not self.stopped)
        content=c.get('content',{});self.check(type(content) is dict and content.get('role','model')=='model')
        parts=content.get('parts',[]);self.check(type(parts) is list)
        for part in parts:
            self.check(type(part) is dict and type(part.get('text')) is str and type(part.get('thought',False)) is bool and not any(k in part for k in ('functionCall','executableCode','codeExecutionResult','inlineData','fileData')),'tool_output_rejected')
            if not part.get('thought',False):self._append(part['text'])
        reason=c.get('finishReason')
        if reason is not None:self.check(reason=='STOP','noncomplete_finish_reason');self.stopped=True;self.reason='stop'
    def finish(self):
        try:self.decoder.decode(b'',final=True)
        except UnicodeError:self.fail('invalid_utf8')
        self.check(not self.line and not self.data,'response_truncated')
        self.check(self.stopped and (self.done or self.protocol=='gemini-content'),'response_truncated')
        self.check(bool(self.text.strip()),'empty_output')
        # Messages has no native total; Gemini totals may include reasoning and
        # other billed tokens, so prompt+candidate is not a truthful replacement.
        if 'total_tokens' not in self.usage and self.protocol=='anthropic-messages':
            p,c=self.usage.get('prompt_tokens'),self.usage.get('completion_tokens')
            if type(p) is int and type(c) is int:self.usage['total_tokens']=p+c
        return dict(id=self.identifier,model=self.model,choices=[dict(message=dict(role='assistant',content=self.text),finish_reason='stop')],usage=self.usage)
