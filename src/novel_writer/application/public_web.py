"""Bounded public HTTP reads: pinned verified addresses, no cookies, keys or scripts."""
import re,threading,time,socket,http.client
from urllib.parse import urljoin,urlunsplit,quote
from html.parser import HTMLParser
from novel_writer.domain.public_search import public_url,Hop,FetchOutcome
from novel_writer.domain.tasks import require
from novel_writer.application.custom_protocols import connection_for
from novel_writer.application.task_protocol import TaskCancelled,TaskTimeout

class Extractor(HTMLParser):
 def __init__(self):super().__init__(convert_charrefs=True);self.stack=[];self.parts=[];self.title=[];self.description='';self.article=False;self.toc_links=0
 def handle_starttag(self,tag,attrs):
  attrs=dict(attrs);self.stack.append(tag)
  if tag in ('article','main') or attrs.get('itemprop')=='articleBody':self.article=True
  if tag=='a':self.toc_links+=1
  if tag=='meta' and (attrs.get('name','').lower()=='description' or attrs.get('property','').lower()=='og:description'):self.description=attrs.get('content','')
  if tag in ('p','br','div','li','section','article','main','h1','h2'):self.parts.append('\n')
  if tag in ('meta','link','br','img','input','hr','source','wbr','area','base','embed','param'):self.stack.pop()
 def handle_startendtag(self,tag,attrs):self.handle_starttag(tag,attrs)
 def handle_endtag(self,tag):
  if tag in self.stack:
   position=len(self.stack)-1-self.stack[::-1].index(tag);self.stack=self.stack[:position]
  if tag in ('p','div','li','section','article','main','h1','h2'):self.parts.append('\n')
 def handle_data(self,data):
  if 'title' in self.stack:self.title.append(data)
  if not any(v in self.stack for v in ('head','script','style','noscript','template','iframe','object','svg','nav','header','footer','form')):self.parts.append(data)
 def result(self):
  text='\n'.join(line.strip() for line in ''.join(self.parts).splitlines() if line.strip());title=''.join(self.title).strip()[:1000];kind='page_text'
  if not self.article and self.description and len(text)<1000:text=self.description;kind='description'
  elif not self.article and self.toc_links>=5 and len(text)<20000:kind='toc'
  return text,title,kind

def extract(raw,content_type):
 charset=re.search('charset=["\x27]?([a-zA-Z0-9_-]+)',content_type,re.I)
 if not charset:charset=re.search('<meta[^>]+charset=["\x27]?([a-zA-Z0-9_-]+)',raw[:8192].decode('latin1'),re.I)
 encoding=(charset.group(1) if charset else 'utf-8').lower();require(encoding in ('utf-8','utf8','utf-8-sig','utf-16','gb18030','gbk','gb2312','windows-1252','iso-8859-1'),'public_encoding_unsupported')
 try:document=raw.decode(encoding,errors='strict')
 except UnicodeError:raise ValueError('public_encoding_invalid') from None
 if content_type.split(';')[0].strip().lower()=='text/plain':text,title,kind=document,'','page_text'
 else:
  parser=Extractor();parser.feed(document);parser.close();text,title,kind=parser.result()
 require(text.strip() and not any(ord(c)<32 and c not in '\t\r\n' for c in text),'public_no_sample')
 gate=('请登录','登录后阅读','付费阅读','订阅后','验证码','captcha','checking your browser','access denied')
 if len(text)<1500 and any(v in text.lower() for v in gate):raise ValueError('public_access_denied')
 return text,title,kind,encoding

class PublicReader:
 def __init__(self,*,_resolver=None,_connector=None):self._resolver,self._connector=_resolver,_connector
 def read(self,url,token):
  original=url;current=url;last_contacted='';hops=[];raw=b'';text='';encoding=None;title='';kind='unavailable';status=None;error=None
  for number in range(5):
   connection=None;stop=threading.Event();active=[None];watcher=None;verified=[]
   try:
    token.checkpoint();parsed=public_url(current);host=parsed.hostname.encode('idna').decode();port=parsed.port or (443 if parsed.scheme=='https' else 80);authority=('['+host+']' if ':' in host else host)+((':'+str(parsed.port)) if parsed.port else '');current=urlunsplit((parsed.scheme,authority,quote(parsed.path or '/',safe="/:@!$&'()*+,;=-._~%"),quote(parsed.query,safe="=&;%:+,/?@!$'()*-._~"),''));parsed=public_url(current)
    def observe_resolver(hostname,port,**kwargs):
     entries=(self._resolver or socket.getaddrinfo)(hostname,port,**kwargs)
     import ipaddress
     if all(ipaddress.ip_address(entry[4][0]).is_global for entry in entries):verified.extend(dict.fromkeys(entry[4][0] for entry in entries))
     return entries
    connection=connection_for(dict(base_url=current,allow_local=False),min(20,max(.001,token.deadline-time.monotonic())),token=token,_url_validator=public_url,_resolver=observe_resolver,_connector=self._connector)
    def abort():
     while not stop.wait(.02):
      if token.event.is_set() or time.monotonic()>=token.deadline:
       transport=connection.sock or active[0]
       if transport is not None:
        try:transport.shutdown(socket.SHUT_RDWR)
        except OSError:pass
       return
    watcher=threading.Thread(target=abort,daemon=True);watcher.start();connection.connect();active[0]=connection.sock;token.checkpoint();target=urlunsplit(('', '',parsed.path or '/',parsed.query,''));authority=('['+host+']' if ':' in host else host)+((':'+str(parsed.port)) if parsed.port else '');connection.request('GET',target,headers={'Host':authority,'Accept':'text/html,text/plain,application/xhtml+xml','Accept-Encoding':'identity','User-Agent':'AI-Novel-Writer/0.3 public sample reader','Connection':'close'});response=connection.getresponse();status=response.status;last_contacted=current;location=response.getheader('Location');hops.append(Hop(url=current,addresses=tuple(verified),status=status,location=location[:4096] if location else None,error_code=None))
    if status in (301,302,303,307,308):
     require(location is not None and len(location)<=2048,'public_redirect_invalid');require(number<4,'public_redirect_limit');current=urljoin(current,location);continue
    length=response.getheader('Content-Length')
    if length is not None:require(length.isdigit() and int(length)<=1048576,'public_page_too_large')
    while True:
     token.checkpoint();piece=response.read1(min(4096,1048577-len(raw)))
     if not piece:break
     raw+=piece;require(len(raw)<=1048576,'public_page_too_large')
    token.checkpoint();require(response.length in (None,0),'public_page_incomplete');require(status==200,'public_access_denied' if status in (401,403,407,429,451) else 'public_http_error');require(response.getheader('Content-Encoding','identity').lower() in ('','identity'),'public_encoding_unsupported');content_type=response.getheader('Content-Type','');require(content_type.split(';')[0].strip().lower() in ('text/html','text/plain','application/xhtml+xml'),'public_content_type_unsupported');text,title,kind,encoding=extract(raw,content_type);return FetchOutcome(original_url=original,final_url=last_contacted,hops=tuple(hops),http_status=status,raw=raw,text=text,encoding=encoding,title=title,sample_type=kind,complete=True,error_code=None)
   except TaskCancelled:error='cancelled'
   except TaskTimeout:error='timeout'
   except ValueError as failure:error=str(failure) if str(failure).startswith('public_') else 'public_address_blocked'
   except (OSError,TimeoutError,http.client.HTTPException):error='cancelled' if token.event.is_set() else 'timeout' if time.monotonic()>=token.deadline else 'public_transport_failed'
   finally:
    stop.set()
    if connection:connection.close()
    if watcher:watcher.join()
   if error:
    if not hops or hops[-1].url!=current:hops.append(Hop(url=current,addresses=(),status=None,location=None,error_code=error))
    break
  return FetchOutcome(original_url=original,final_url=last_contacted,hops=tuple(hops),http_status=status,raw=raw,text=text,encoding=encoding,title=title,sample_type=kind,complete=False,error_code=error or 'public_redirect_limit')
