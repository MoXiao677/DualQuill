"""Preamble preservation and bounded compact commits use real temporary HTTP/SQLite."""
import base64,hashlib,json
from copy import deepcopy
from http.client import HTTPConnection
import unittest
import test_chapter_lifecycle_http as fixtures
from novel_writer.application.migration_text import detect,preview
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository

class MigrationPreservationTests(unittest.TestCase):
 setUp=fixtures.LifecycleHttpTests.setUp
 stop=fixtures.LifecycleHttpTests.stop
 def request(self,method,path,payload=None,*,token=True,raw=False):
  c=HTTPConnection('127.0.0.1',self.server.server_port,timeout=60);headers={'Content-Type':'application/json'}
  if token:headers['X-Novel-Token']=self.server.token
  try:
   c.request(method,path,json.dumps(payload,ensure_ascii=False).encode('utf-8') if payload is not None else None,headers);r=c.getresponse();data=r.read();status=r.status;response_headers=dict(r.getheaders())
  finally:c.close()
  return status,(data if raw else json.loads(data)),response_headers
 def commit(self,raw,encoding='auto'):
  body=dict(filename='虚构导入.txt',content_base64=base64.b64encode(raw).decode(),encoding=encoding)
  code,value,_=self.request('POST',self.base+'/import/preview',body);self.assertEqual(code,200,value)
  items=[{k:v[k] for k in ('index','title','start','content_start','end','chars')} for v in value['items']]
  request=dict(body,expected_revision=self.server.service.get(self.pid)['revision'],items=items,preview_sha256=value['preview_sha256'],confirmed=True)
  return value,request
 def test_utf8_and_gb18030_preamble_survive_full_http_commit_and_reopen(self):
  text='  前言含空格。\r\n第二行。\r\n第1章 开始\r\n  正文\r\n'
  for encoding in ('utf-8','gb18030'):
   with self.subTest(encoding=encoding):
    value,request=self.commit(text.encode(encoding));self.assertEqual(value['preamble_chars'],len(text[:text.index('第1章')]))
    self.assertEqual(value['items'][0]['content'],text[:text.index('第1章')]);self.assertEqual(value['items'][0]['content_start'],0)
    code,state,_=self.request('POST',self.base+'/import/commit',request);self.assertEqual(code,200,state)
    reopened=NovelService(SQLiteRepository(self.server.service.repository.path)).get(self.pid);self.assertEqual([v['content'] for v in reopened['document']['chapters'][-2:]],[text[:text.index('第1章')],'  正文\r\n'])
 def test_old_preview_and_altered_compact_range_are_rejected_atomically(self):
  raw='前言\r\n第1章 开始\n正文\n'.encode();value,request=self.commit(raw);before=self.server.service.get(self.pid)
  old_ranges=[(v['start'],v['content_start'],v['end']) for v in value['items'][1:]]
  legacy=dict(source=hashlib.sha256(raw).hexdigest(),encoding='utf-8',ranges=old_ranges)
  bad=deepcopy(request);bad['preview_sha256']=hashlib.sha256(json.dumps(legacy,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
  self.assertEqual(self.request('POST',self.base+'/import/commit',bad)[0],422)
  bad=deepcopy(request);bad['items'][0]['end']-=1;self.assertEqual(self.request('POST',self.base+'/import/commit',bad)[0],422);self.assertEqual(self.server.service.get(self.pid),before)
  plain='  无标题全篇\r\n```\r\n第1章 代码里的标题\r\n```\r\n尾行';items,preamble=detect(plain,'虚构.md');self.assertEqual(preamble,'');self.assertEqual(len(items),1);self.assertEqual(items[0]['content'],plain)
 def test_large_supported_gb18030_file_commits_compact_mapping_below_http_limit(self):
  bodies=['海'*11500+'\r\n' for _ in range(200)];text=''.join('第'+str(i+1)+'章 虚构\r\n'+v for i,v in enumerate(bodies));raw=text.encode('gb18030');self.assertGreater(len(raw),4_500_000);self.assertLess(len(raw),5*1024*1024)
  value,request=self.commit(raw);self.assertEqual(len(value['items']),200)
  old=dict(request,items=value['items']);self.assertGreater(len(json.dumps(old,ensure_ascii=False).encode()),12*1024*1024)
  self.assertLess(len(json.dumps(request,ensure_ascii=False).encode()),12*1024*1024)
  code,state,_=self.request('POST',self.base+'/import/commit',request);self.assertEqual(code,200,str(state)[:300]);reopened=NovelService(SQLiteRepository(self.server.service.repository.path)).get(self.pid);self.assertEqual([v['content'] for v in reopened['document']['chapters'][1:]],bodies)
