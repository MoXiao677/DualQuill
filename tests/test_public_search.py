import json,base64,threading,time,http.client,socket,unittest
from contextlib import contextmanager,closing
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from importlib import import_module,util
from uuid import uuid4
from test_styles import StyleTests

@contextmanager
def search_wire(*,grounded=True,slow=False,metadata_changes=None):
 calls=[];seen=threading.Event();release=threading.Event()
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def do_POST(self):
   body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append(body);seen.set()
   if slow:release.wait(3)
   text='虚构雾港，作者林某。另有未核实裸链接 http://invented.example/story。';metadata=dict(webSearchQueries=['虚构雾港 虚构平台'],searchEntryPoint=dict(renderedContent='<div>Google Search <a href="https://www.google.com/search?q=fiction">fiction</a></div>'),groundingChunks=[dict(web=dict(uri='http://search.example/redirect',title='虚构雾港 - 虚构平台')),dict(web=dict(uri='http://127.0.0.1/private',title='私网来源不能读取'))],groundingSupports=[dict(segment=dict(partIndex=0,startIndex=0,endIndex=len('虚构雾港'.encode()),text='虚构雾港'),groundingChunkIndices=[0],confidenceScores=[.9])])
   if body.get('tools'):
    query=json.loads(body['contents'][-1]['parts'][0]['text'])
    if '简介' in query['title']:metadata['groundingChunks'][0]['web']=dict(uri='http://book.example/intro',title='虚构雾港 - 作品简介')
   else:
    from test_styles import FEATURES
    block=json.loads(body['contents'][-1]['parts'][0]['text']);text=json.dumps(dict(prompt='围绕单一人物，以具体动作推进。',card=FEATURES,evidence=[dict(**block['range'],feature='viewpoint')]),ensure_ascii=False)
   candidate=dict(content=dict(role='model',parts=[dict(text=text)]),finishReason='STOP')
   if grounded and body.get('tools'):
    metadata['groundingSupports'][0]['groundingChunkIndices']=[0,1]
    if metadata_changes:metadata.update(metadata_changes)
    candidate['groundingMetadata']=metadata
   payload=dict(candidates=[candidate],usageMetadata=dict(promptTokenCount=50,candidatesTokenCount=30,totalTokenCount=80),responseId='fiction-search',modelVersion='fiction-search-model');raw=json.dumps(payload,ensure_ascii=False).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers()
   try:self.wfile.write(raw)
   except OSError:pass
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True;thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
 try:yield dict(url='http://127.0.0.1:'+str(server.server_port)+'/v1',calls=calls,seen=seen,release=release)
 finally:release.set();server.shutdown();server.server_close();thread.join(2)

@contextmanager
def pages():
 calls=[]
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def do_GET(self):
   calls.append(dict(host=self.headers.get('Host'),path=self.path,headers=dict(self.headers)))
   if self.path=='/redirect':self.send_response(302);self.send_header('Location','http://book.example/chapter');self.send_header('Content-Length','0');self.end_headers();return
   if self.path=='/private-hop':self.send_response(302);self.send_header('Location','http://private.example/secret');self.send_header('Content-Length','0');self.end_headers();return
   if self.path=='/loop':self.send_response(302);self.send_header('Location','/loop');self.send_header('Content-Length','0');self.end_headers();return
   if self.path=='/large':self.send_response(200);self.send_header('Content-Type','text/plain');self.send_header('Content-Length','1048577');self.end_headers();return
   status=403 if self.path=='/denied' else 200
   html='<html><head><title>虚构雾港 第一章</title></head><body><nav>导航不能当正文</nav><article><p>虚构公开段落。'+('船灯照着空港，信使等着回音。'*40)+'</p></article><script>never execute or send credentials</script></body></html>'
   if self.path=='/intro':html='<html><head><title>虚构雾港</title><meta name="description" content="这只是作品简介。"></head><body>作品介绍：这只是作品简介。</body></html>'
   if self.path=='/denied':html='<html><body>请登录后付费阅读</body></html>'
   raw=html.encode();self.send_response(status);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.end_headers()
   try:
    if self.path=='/slow':self.wfile.write(raw[:10]);self.wfile.flush();time.sleep(1);self.wfile.write(raw[10:])
    else:self.wfile.write(raw)
   except OSError:pass
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True;thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
 try:yield server.server_port,calls
 finally:server.shutdown();server.server_close();thread.join(2)

class SearchTests(StyleTests):
 def setUp(self):
  super().setUp();self.assertIsNotNone(util.find_spec('novel_writer.application.public_search'),'grounded public-search workflow is missing');self.search_api=import_module('novel_writer.application.public_search');self.reader_api=import_module('novel_writer.application.public_web');self.search=self.search_api.SearchCoordinator(self.shared,self.providers,self.styles,enabled=True)
 def query(self,connection,**changes):
  request=dict(operation_id=str(uuid4()),title='虚构雾港',platform='虚构平台',author='林某',model_options=self.options(connection),max_calls=2,max_output_tokens=2048);request.update(changes);return self.search.prepare(self.pid,request)
 def run_query(self,prepared):
  query=prepared['query'];self.search.start(self.pid,query['id'],dict(confirm_external=True,request_sha256=query['request_sha256']));self.shared.wait_idle(5);return self.search.describe(self.pid,query['id'])
 def reader(self,port,*,private=False):
  verified=[]
  def resolver(host,port,**kwargs):return [(socket.AF_INET,socket.SOCK_STREAM,6,'',('10.1.2.3' if private and host=='private.example' else '8.8.8.8',port))]
  def connector(parsed,addresses,remaining,token):verified.append((parsed.hostname,addresses));return http.client.HTTPConnection('127.0.0.1',port,timeout=remaining())
  return self.reader_api.PublicReader(_resolver=resolver,_connector=connector),verified
 def test_prepare_uses_native_tool_only_for_search_configuration_and_never_sends_book_text(self):
  with search_wire() as wire:
   connection=self.connection(wire,'gemini-content');prepared=self.query(connection);body=json.loads(prepared['request_body']);self.assertEqual(body['tools'],[dict(google_search={})]);self.assertEqual(wire['calls'],[]);self.assertNotIn(self.pid,prepared['request_body']);self.assertNotIn('fiction-book-private-key',prepared['request_body']);self.assertIn('虚构雾港',prepared['request_body'])
   with self.assertRaises(ValueError):self.search.start(self.pid,prepared['query']['id'],dict(confirm_external=True,request_sha256='0'*64))
   other=self.connection(wire,'openai-chat')
   with self.assertRaises(ValueError):self.query(other)
 def test_wire_grounding_builds_only_cited_sources_and_preserves_utf8_byte_supports(self):
  with search_wire() as wire:
   result=self.run_query(self.query(self.connection(wire,'gemini-content')));self.assertEqual(result['status'],'succeeded');self.assertEqual(len(result['sources']),1);self.assertEqual(result['sources'][0]['url'],'http://search.example/redirect');self.assertEqual(result['sources'][0]['supports'][0]['end_byte'],12);self.assertNotIn('invented.example',json.dumps(result['sources']));self.assertEqual(len(wire['calls']),1);self.assertIn('groundingMetadata',result['raw_response'])
 def test_identity_read_preview_fixed_public_ips_and_imported_excerpt_feed_style_material(self):
  with search_wire() as wire,pages() as (port,calls):
   done=self.run_query(self.query(self.connection(wire,'gemini-content')));source=done['sources'][0];reader,verified=self.reader(port);self.search.reader=reader;identity=self.search.choose_identity(self.pid,dict(operation_id=str(uuid4()),query_id=done['query']['id'],source_id=source['id'],confirmed=True));prepared=self.search.prepare_read(self.pid,dict(operation_id=str(uuid4()),identity_id=identity['id']));self.assertEqual(calls,[]);self.search.start_read(self.pid,prepared['read']['id'],dict(confirmed=True,request_sha256=prepared['read']['request_sha256']));self.shared.wait_idle(5);page=self.search.read_detail(self.pid,prepared['read']['id']);self.assertEqual(page['status'],'succeeded');self.assertEqual(page['page']['original_url'],source['url']);self.assertEqual(page['page']['final_url'],'http://book.example/chapter');self.assertNotIn('never execute',page['text']);self.assertEqual(len(verified),2);self.assertEqual(calls[0]['host'],'search.example');self.assertNotIn('Authorization',calls[-1]['headers']);saved=self.search.import_sample(self.pid,dict(operation_id=str(uuid4()),page_id=page['page']['id'],start=0,end=len(page['text']),sample_type='prose_excerpt',confirmed=True));material=self.styles.source(self.pid,saved['source_id']);self.assertEqual(material['text'],page['text']);self.assertEqual(material['kind'],'article');self.assertEqual(self.service.get(self.pid)['document']['chapters'],[])
 def test_public_reader_rejects_private_dns_on_every_hop_and_never_uses_model_local_permission(self):
  for url in ['file:///x','http://user:secret@book.example/x','http://127.0.0.1/x','http://169.254.169.254/metadata','http://[::1]/x']:
   with self.subTest(url=url),self.assertRaises(ValueError):self.reader_api.public_url(url)
  with pages() as (port,calls):
   reader,verified=self.reader(port,private=True);token=self.search_api.CancellationToken(threading.Event(),time.monotonic()+3);result=reader.read('http://book.example/private-hop',token);self.assertFalse(result.complete);self.assertEqual(result.error_code,'public_address_blocked');self.assertEqual(len(calls),1);self.assertEqual(len(verified),1)
 def test_intro_denial_missing_grounding_cancel_and_call_budget_are_explicit(self):
  with search_wire(grounded=False) as wire:
   done=self.run_query(self.query(self.connection(wire,'gemini-content'),max_calls=1));self.assertEqual(done['status'],'failed');self.assertEqual(done['sources'],[])
   with self.assertRaises(ValueError):self.run_query(self.query(dict(id=done['query']['configuration']['connection_id']),max_calls=1))
  with pages() as (port,calls):
   reader,_=self.reader(port);token=self.search_api.CancellationToken(threading.Event(),time.monotonic()+3);intro=reader.read('http://book.example/intro',token);self.assertTrue(intro.complete);self.assertEqual(intro.sample_type,'description');denied=reader.read('http://book.example/denied',token);self.assertFalse(denied.complete);self.assertEqual(denied.error_code,'public_access_denied')
  with search_wire(slow=True) as wire:
   prepared=self.query(self.connection(wire,'gemini-content'));query=prepared['query'];self.search.start(self.pid,query['id'],dict(confirm_external=True,request_sha256=query['request_sha256']));self.assertTrue(wire['seen'].wait(2));self.search.cancel(self.pid,query['id']);wire['release'].set();self.shared.wait_idle(4);done=self.search.describe(self.pid,query['id']);self.assertEqual(done['status'],'cancelled');self.assertEqual(done['sources'],[]);self.assertEqual(len(wire['calls']),1)
 def test_dns_rebinding_redirect_and_response_limits_are_checked_before_each_new_connection(self):
  with pages() as (port,calls):
   reader,verified=self.reader(port);counter=[]
   def changing(host,port,**kwargs):counter.append(host);return [(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8' if len(counter)==1 else '10.0.0.1',port))]
   reader._resolver=changing;result=reader.read('http://book.example/redirect',self.search_api.CancellationToken(threading.Event(),time.monotonic()+3));self.assertFalse(result.complete);self.assertEqual(result.error_code,'public_address_blocked');self.assertEqual(counter,['book.example','book.example']);self.assertEqual(len(verified),1);self.assertEqual(len(calls),1)
   reader,_=self.reader(port);large=reader.read('http://book.example/large',self.search_api.CancellationToken(threading.Event(),time.monotonic()+3));self.assertEqual(large.error_code,'public_page_too_large');loop=reader.read('http://book.example/loop',self.search_api.CancellationToken(threading.Event(),time.monotonic()+3));self.assertEqual(loop.error_code,'public_redirect_limit');self.assertEqual(len(loop.hops),5)
 def test_full_backup_copy_keeps_query_grounding_raw_pages_identity_and_style_provenance(self):
  from novel_writer.application.backups import create_backup,restore_backup
  from novel_writer.application.migrations import migrate
  from novel_writer.application.skill_import import SkillLibrary
  from novel_writer.application.service import NovelService
  from novel_writer.storage.sqlite_repository import SQLiteRepository
  self.source('V13虚构原资料。');before=self.db.read_bytes();NovelService(SQLiteRepository(self.db)).get(self.pid);self.assertEqual(self.db.read_bytes(),before)
  with closing(__import__('sqlite3').connect(self.db)) as db:old=db.execute('SELECT project_id,revision,payload,saved_at FROM project_snapshots ORDER BY project_id,revision').fetchall()
  with search_wire() as wire,pages() as (port,calls):
   done=self.run_query(self.query(self.connection(wire,'gemini-content')));source=done['sources'][0];self.search.reader=self.reader(port)[0];identity=self.search.choose_identity(self.pid,dict(operation_id=str(uuid4()),query_id=done['query']['id'],source_id=source['id'],confirmed=True));read=self.search.prepare_read(self.pid,dict(operation_id=str(uuid4()),identity_id=identity['id']))['read'];self.search.start_read(self.pid,read['id'],dict(confirmed=True,request_sha256=read['request_sha256']));self.shared.wait_idle(5);page=self.search.read_detail(self.pid,read['id']);imported=self.search.import_sample(self.pid,dict(operation_id=str(uuid4()),page_id=page['page']['id'],start=0,end=len(page['text']),sample_type='page_text',confirmed=True));pending=self.search.prepare_read(self.pid,dict(operation_id=str(uuid4()),identity_id=identity['id']))['read'];SkillLibrary(self.db);package=self.root/'web.nwbak';self.assertEqual(create_backup(self.db,package)['backup_format_version'],51);restored=restore_backup(package,self.root/'web-restored');self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid),self.service.get(self.pid));target=self.root/'web-copy.sqlite3';SQLiteRepository(target);SkillLibrary(target);result=migrate(package,target,operation_id=str(uuid4()));clone=NovelService(SQLiteRepository(target)).get(result['projects'][0]['new_id']);self.assertEqual(clone['web_imports'][0]['source_id'],clone['style_sources'][-1]['id']);self.assertEqual(clone['web_pages'][0]['raw_sha256'],page['page']['raw_sha256']);self.assertEqual(clone['web_sources'][0]['url'],source['url']);self.assertEqual(len(wire['calls']),1);self.assertEqual(len(calls),2)
  with closing(__import__('sqlite3').connect(self.db)) as db:self.assertEqual(db.execute('SELECT project_id,revision,payload,saved_at FROM project_snapshots ORDER BY project_id,revision').fetchall()[:len(old)],old)
 def test_malformed_grounding_is_a_persistent_failure_with_raw_response_not_a_stuck_worker(self):
  for changes in [dict(searchEntryPoint=None),dict(groundingSupports=[dict(segment=None,groundingChunkIndices=[0])])]:
   with self.subTest(changes=changes),search_wire(metadata_changes=changes) as wire:
    done=self.run_query(self.query(self.connection(wire,'gemini-content')));self.assertEqual(done['status'],'failed');self.assertEqual(done['sources'],[]);self.assertIn('groundingMetadata',done['raw_response']);self.assertEqual(len(wire['calls']),1)
 def test_cancellation_stops_an_actual_public_response_read(self):
  with pages() as (port,calls):
   reader,_=self.reader(port);event=threading.Event();token=self.search_api.CancellationToken(event,time.monotonic()+3);result=[];worker=threading.Thread(target=lambda:result.append(reader.read('http://book.example/slow',token)));worker.start();deadline=time.monotonic()+2
   while not calls and time.monotonic()<deadline:time.sleep(.01)
   self.assertTrue(calls);event.set();worker.join(2);self.assertFalse(worker.is_alive());self.assertFalse(result[0].complete);self.assertEqual(result[0].error_code,'cancelled')
 def test_original_unicode_fragment_uri_is_preserved_but_wire_and_final_url_are_exact(self):
  with pages() as (port,calls):
   reader,_=self.reader(port);result=reader.read('http://book.example/章节#section',self.search_api.CancellationToken(threading.Event(),time.monotonic()+3));self.assertTrue(result.complete);self.assertEqual(result.original_url,'http://book.example/章节#section');self.assertEqual(result.final_url,'http://book.example/%E7%AB%A0%E8%8A%82');self.assertEqual(calls[0]['path'],'/%E7%AB%A0%E8%8A%82')
 def test_persisted_source_must_match_the_original_grounding_not_an_added_bare_url(self):
  from novel_writer.storage.content_blobs import validate_refs
  with search_wire() as wire:
   self.run_query(self.query(self.connection(wire,'gemini-content')));state=self.service.get(self.pid);state['web_sources'][0]['url']='http://invented.example/story'
   with closing(__import__('sqlite3').connect(self.db)) as db:
    with self.assertRaisesRegex(ValueError,'search.raw_provenance_mismatch'):validate_refs(db,state)

for _class in (StyleTests,import_module('test_book_ai').BookAITests):
 for _name in _class.__dict__:
  if _name.startswith('test_') and _name not in SearchTests.__dict__:setattr(SearchTests,_name,None)
if __name__=='__main__':unittest.main()
