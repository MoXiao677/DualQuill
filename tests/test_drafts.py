from http.client import HTTPConnection
import json,tempfile,threading,unittest,zipfile
from pathlib import Path
from uuid import uuid4
from novel_writer.ui.server import create_server
from novel_writer.application.drafts import DiskDrafts,DraftError,filter_sensitive_fields
from novel_writer.application.backups import create_backup,restore_backup
from novel_writer.application.migrations import migrate
from novel_writer.application.skill_import import SkillLibrary
from novel_writer.storage.sqlite_repository import SQLiteRepository
from novel_writer.application.service import NovelService

class DraftTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='novel-drafts-');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.db=self.root/'library'/'novels.sqlite3';self.db.parent.mkdir();self.drafts=self.root/'drafts'
  self.server=create_server(self.db,port=0,provider_path=self.root/'fiction.dpapi',drafts_path=self.drafts);self.thread=self.start(self.server);self.pid=NovelService(SQLiteRepository(self.db)).create(title='草稿虚构小说')['document']['project']['id'];self.cid=self.action('add_chapter',dict(title='第一章'))['document']['chapters'][0]['id'];self.key=json.dumps([self.pid,'writing',self.cid,'body'],ensure_ascii=False)
 def start(self,server):thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start();self.addCleanup(lambda:(server.shutdown(),server.server_close(),thread.join(2)));return thread
 def stop(self,server):server.shutdown();server.server_close()
 def request(self,method,path,payload=None,*,token=True,port=None):
  client=HTTPConnection('127.0.0.1',port or self.server.server_port,timeout=10);headers={'Content-Type':'application/json'}
  if token:headers['X-Novel-Token']=self.server.token
  try:client.request(method,path,json.dumps(payload) if payload is not None else None,headers);response=client.getresponse();return response.status,json.loads(response.read())
  finally:client.close()
 def action(self,name,fields):
  service=NovelService(SQLiteRepository(self.db));state=service.get(self.pid);return service.execute(self.pid,name,fields,expected_revision=state['revision'])
 def save(self,key=None,base=None,values=None,position=None):
  state=NovelService(SQLiteRepository(self.db)).get(self.pid)
  return self.request('POST','/api/projects/'+self.pid+'/drafts',dict(document_key=key or self.key,base_revision=state['revision'] if base is None else base,values=values or {'title':'第一章','content':'未保存😀\n草稿'},position=position or {'top':12,'cursor':3,'end':5,'editorTop':7}))
 def test_restart_keeps_draft_and_save_or_discard_clears_only_that_draft(self):
  code,saved=self.save();self.assertEqual(code,200,saved);self.assertEqual(saved['values']['content'],'未保存😀\n草稿');self.assertEqual(saved['position']['cursor'],3)
  code,listed=self.request('GET','/api/projects/'+self.pid+'/drafts');self.assertEqual(code,200,listed);self.assertEqual(len(listed['drafts']),1);self.assertEqual(listed['corrupt'],[])
  self.stop(self.server);self.server=create_server(self.db,port=0,provider_path=self.root/'fiction.dpapi',drafts_path=self.drafts);self.start(self.server)
  code,listed=self.request('GET','/api/projects/'+self.pid+'/drafts');self.assertEqual(code,200,listed);self.assertEqual(json.loads(listed['drafts'][0]['document_key']),json.loads(self.key));self.assertEqual(listed['drafts'][0]['values']['content'],'未保存😀\n草稿')
  code,cleared=self.request('POST','/api/projects/'+self.pid+'/drafts/clear',dict(document_key=self.key));self.assertEqual(code,200,cleared);self.assertTrue(cleared['cleared'])
  self.assertEqual(self.request('GET','/api/projects/'+self.pid+'/drafts')[1]['drafts'],[]);self.assertFalse(any(self.drafts.glob('*.json')))
 def test_stale_draft_requires_explicit_rebase_and_never_writes_body(self):
  self.save(base=NovelService(SQLiteRepository(self.db)).get(self.pid)['revision']);saved=self.action('save_chapter',dict(chapter_id=self.cid,content='正式已保存正文。'))
  draft=self.request('GET','/api/projects/'+self.pid+'/drafts')[1]['drafts'][0];self.assertEqual(draft['base_revision'],saved['revision']-1);self.assertEqual(NovelService(SQLiteRepository(self.db)).get(self.pid)['document']['chapters'][0]['content'],'正式已保存正文。')
  code,rebased=self.save(base=saved['revision'],values=draft['values']);self.assertEqual(code,200,rebased);self.assertEqual(rebased['base_revision'],saved['revision']);self.assertEqual(NovelService(SQLiteRepository(self.db)).get(self.pid)['document']['chapters'][0]['content'],'正式已保存正文。')
 def test_corrupt_file_is_reported_and_ignored_without_deleting_other_drafts(self):
  self.save();bad=self.drafts/'broken-draft.json';bad.write_text('{broken',encoding='utf-8');valid_file=next(self.drafts.glob('*.json'))
  code,listed=self.request('GET','/api/projects/'+self.pid+'/drafts');self.assertEqual(code,200,listed);self.assertEqual(len(listed['drafts']),1);self.assertIn('broken-draft.json',listed['corrupt']);self.assertTrue(bad.exists());self.assertTrue(valid_file.exists())
  other=json.dumps([self.pid,'writing',self.cid,'idea'],ensure_ascii=False);code,saved=self.save(key=other,values={'content':'另一个草稿'});self.assertEqual(code,200);self.assertEqual(len(self.request('GET','/api/projects/'+self.pid+'/drafts')[1]['drafts']),2)
 def test_projects_are_isolated_and_settings_or_non_document_keys_are_rejected(self):
  self.save();other=NovelService(SQLiteRepository(self.db)).create(title='另一本书')['document']['project']['id'];self.assertEqual(self.request('GET','/api/projects/'+other+'/drafts')[1]['drafts'],[])
  self.assertEqual(self.request('POST','/api/projects/'+other+'/drafts',dict(document_key=self.key,base_revision=1,values={'content':'x'},position={}))[0],422)
  settings=json.dumps([self.pid,'settings','',''],ensure_ascii=False);self.assertEqual(self.request('POST','/api/projects/'+self.pid+'/drafts',dict(document_key=settings,base_revision=1,values={'api_key':'secret'},position={}))[0],422)
  self.assertEqual(len(self.request('GET','/api/projects/'+self.pid+'/drafts')[1]['drafts']),1)
 def test_draft_api_is_token_bound_and_workspace_version_is_unchanged(self):
  before=NovelService(SQLiteRepository(self.db)).get(self.pid);self.assertEqual(self.request('POST','/api/projects/'+self.pid+'/drafts',dict(document_key=self.key,base_revision=before['revision'],values={'content':'x'},position={}),token=False)[0],403);self.save();after=NovelService(SQLiteRepository(self.db)).get(self.pid);self.assertEqual(after['workspace_version'],before['workspace_version']);self.assertEqual(after['revision'],before['revision'])
 def test_backup_and_copy_migrate_redacted_drafts_with_mapped_ids(self):
  self.save(values={'content':'fictional unsaved body','chapter_id':self.cid,'API_KEY':'fictional-secret','authorToken':'fictional-token'})
  unknown=json.dumps([self.pid,'writing','missing-chapter','body'],ensure_ascii=False,separators=(',',':'))
  DiskDrafts(self.drafts).save(self.pid,unknown,1,{'content':'unmapped draft'})
  SkillLibrary(self.db);package=self.root/'drafts.nwbak';manifest=create_backup(self.db,package,drafts_path=self.drafts)
  self.assertEqual(manifest['backup_format_version'],51)
  with zipfile.ZipFile(package) as archive:
   self.assertEqual(set(archive.namelist()),{'manifest.json','snapshot.sqlite3','drafts.json'})
   records=json.loads(archive.read('drafts.json'))['drafts']
   self.assertEqual(len(records),2)
   included=next(item for item in records if json.loads(item['document_key'])[2]==self.cid)
   self.assertEqual(included['base_revision'],2)
   self.assertEqual(included['values'],{'content':'fictional unsaved body','chapter_id':self.cid})
   self.assertTrue(included['sensitive_fields_required'])
   archive_text=archive.read('drafts.json').decode('utf-8')
   self.assertNotIn('fictional-secret',archive_text);self.assertNotIn('fictional-token',archive_text)
  restored=self.root/'restored';restore_result=restore_backup(package,restored)
  restored_drafts=DiskDrafts(restored/'drafts').list(self.pid)['drafts']
  self.assertEqual(len(restored_drafts),1)
  self.assertEqual([{'document_key':json.loads(d['document_key']),'reason':d['reason']} for d in restore_result['drafts_dropped']],[{'document_key':json.loads(unknown),'reason':'missing_mapping'}])  # 归一化比较，避免 json 分隔符空格差异
  restored_item=next(item for item in restored_drafts if json.loads(item['document_key'])[2]==self.cid)
  self.assertEqual(restored_item['base_revision'],2);self.assertTrue(restored_item['sensitive_fields_required'])  # 恢复同一库快照，草稿基于的 revision 不变
  self.assertNotIn('API_KEY',restored_item['values']);self.assertNotIn('authorToken',restored_item['values'])
  target=self.root/'copied'/'copied.sqlite3';target.parent.mkdir();SQLiteRepository(target);SkillLibrary(target)
  copied=migrate(self.db,target,operation_id=str(uuid4()),drafts_path=self.drafts,target_drafts_path=target.parent/'drafts')
  self.assertEqual(len(copied['drafts_migrated']),1)
  self.assertEqual(copied['drafts_dropped'][0]['reason'],'missing_mapping')
  target_project=copied['projects'][0]['new_id'];target_chapter=next(item['new_id'] for item in copied['id_map'] if item['old_project_id']==self.pid and item['kind']=='chapter' and item['old_id']==self.cid)
  target_drafts=DiskDrafts(target.parent/'drafts').list(target_project)['drafts']
  self.assertEqual(len(target_drafts),1)
  copied_item=target_drafts[0]
  self.assertEqual(json.loads(copied_item['document_key']),[target_project,'writing',target_chapter,'body'])
  self.assertEqual(copied_item['values']['chapter_id'],target_chapter);self.assertEqual(copied_item['base_revision'],2)
  self.assertTrue(copied_item['sensitive_fields_required'])
 def test_same_library_copy_with_drafts_can_retry_without_source_identity_conflict(self):
  self.save(values={'content':'unsaved original','api_key':'fictional-secret'})
  op=str(uuid4())
  options=dict(operation_id=op,project_ids=[self.pid],drafts_path=self.drafts,target_drafts_path=self.drafts)
  first=migrate(self.db,self.db,**options)
  second=migrate(self.db,self.db,**options)
  self.assertEqual(second['state'],'already_present')
  self.assertEqual(second['projects'],first['projects'])
  self.assertEqual(len(DiskDrafts(self.drafts).list_all()['drafts']),2)
 def test_restore_receipt_supports_many_drafts(self):
  from novel_writer.application.backup_identity import prepare_operation,operation_status,target_for
  store=DiskDrafts(self.drafts)
  for index in range(70):
   store.save(self.pid,json.dumps([self.pid,'writing','missing-'+str(index),'body']),1,{'content':'unmapped'})
  self.save(values={'content':'valid','PASSWORD':'fictional-secret'})
  package=self.root/'many-drafts.nwbak';create_backup(self.db,package,drafts_path=self.drafts)
  identity=str(uuid4());prepare_operation(self.db,identity,package)
  restore_backup(package,target_for(self.db,identity))
  status=operation_status(self.db,identity)
  self.assertEqual(status['state'],'completed');self.assertEqual(len(status['drafts_dropped']),70)
  self.assertTrue(status['sensitive_fields_required'])
 def test_sensitive_filter_matches_all_keywords_case_insensitively_without_mutation(self):
  fields=['API_KEY','ApiKey','authorToken','SeCrEt','Password','PASSWD','Authorization','credential','Bearer','PRIVATE_KEY']
  record={'values':dict(content='keep',**{field:'fictional-'+field for field in fields})}
  filtered=filter_sensitive_fields(record)
  self.assertEqual(filtered['values'],{'content':'keep'});self.assertTrue(filtered['sensitive_fields_required'])
  self.assertEqual(len(record['values']),11)
if __name__=='__main__':unittest.main()
