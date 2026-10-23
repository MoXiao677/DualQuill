"""Content addressed immutable bytes, stored once outside project snapshots."""
import base64,hashlib,sqlite3
from novel_writer.domain.tasks import require
MAX_BYTES=8*1024**2
DDL='CREATE TABLE content_blobs (sha256 TEXT PRIMARY KEY NOT NULL, data_base64 TEXT NOT NULL)'
TRIGGERS={
 'blobs_no_update':"CREATE TRIGGER blobs_no_update BEFORE UPDATE ON content_blobs BEGIN SELECT RAISE(ABORT, '内容不可改写'); END",
 'blobs_no_delete':"CREATE TRIGGER blobs_no_delete BEFORE DELETE ON content_blobs BEGIN SELECT RAISE(ABORT, '内容不可删除'); END",
 'blobs_no_replace':"CREATE TRIGGER blobs_no_replace BEFORE INSERT ON content_blobs WHEN EXISTS (SELECT 1 FROM content_blobs WHERE sha256=NEW.sha256) BEGIN SELECT RAISE(ABORT, '内容不可替换'); END"}
def present(db):return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='content_blobs'").fetchone() is not None
def ensure(db):
 if present(db):return
 db.execute(DDL)
 for ddl in TRIGGERS.values():db.execute(ddl)
 db.execute('PRAGMA user_version=2')
def decode(value,sha):
 require(type(value) is str and len(value)<=((MAX_BYTES+2)//3)*4,'styles.source_limit')
 try:raw=base64.b64decode(value,validate=True)
 except (ValueError,TypeError):raise ValueError('styles.invalid_bytes') from None
 require(0<len(raw)<=MAX_BYTES and base64.b64encode(raw).decode()==value and hashlib.sha256(raw).hexdigest()==sha,'styles.invalid_hash');return raw
def insert(db,data):
 require(type(data) is bytes and 0<len(data)<=MAX_BYTES,'styles.source_limit');ensure(db);sha=hashlib.sha256(data).hexdigest();value=base64.b64encode(data).decode();old=db.execute('SELECT data_base64 FROM content_blobs WHERE sha256=?',(sha,)).fetchone()
 if old:require(old[0]==value,'styles.invalid_hash')
 else:db.execute('INSERT INTO content_blobs VALUES (?,?)',(sha,value))
 return sha
def read(db,sha):
 require(present(db),'styles.missing_blob');row=db.execute('SELECT data_base64 FROM content_blobs WHERE sha256=?',(sha,)).fetchone();require(row is not None,'styles.missing_blob');return decode(row[0],sha)
def validate_refs(db,state):
 from novel_writer.domain.styles import blob_refs
 refs=blob_refs(state)
 if state['workspace_version']>=14:
  from novel_writer.domain.public_search import blob_refs as web_refs
  refs|=web_refs(state)
 if state['workspace_version']>=15:
  from novel_writer.domain.style_trials import blob_refs as trial_refs
  refs|=trial_refs(state)
 for sha in refs:read(db,sha)
 for source in state.get('style_sources',[]):
  raw=read(db,source['blob_sha256'])
  try:text=raw.decode(source['encoding'],errors='strict')
  except UnicodeError:raise ValueError('styles.invalid_encoding') from None
  require(len(raw)==source['byte_count'] and len(text)==source['char_count'] and hashlib.sha256(text.encode()).hexdigest()==source['text_sha256'],'styles.invalid_source')
 if state['workspace_version']>=14:validate_web_refs(db,state)
 if state['workspace_version']>=15:validate_trial_refs(db,state)

def validate_web_refs(db,state):
 from novel_writer.application.public_search import grounded_sources
 from novel_writer.domain.tasks import parse,encode
 from novel_writer.domain.model_contract import ProviderResponse
 from novel_writer.storage.json_codec import strict_json_loads
 for result in state['web_results']:
  response=parse(ProviderResponse,strict_json_loads(read(db,result['response_sha256'])));sources=[v for v in state['web_sources'] if v['result_id']==result['id']]
  if result['error_code'] is not None:require(not sources,'search.raw_provenance_mismatch');continue
  require(response.complete,'search.raw_provenance_mismatch');raw=read(db,result['raw_sha256']).decode('utf-8');queries,entry,actual=grounded_sources(raw);require(result['queries']==list(queries) and result['search_entry_sha256']==hashlib.sha256(entry.encode()).hexdigest() and len(sources)==len(actual),'search.raw_provenance_mismatch');expected={v['chunk_index']:v for v in actual}
  for source in sources:
   original=expected.get(source['chunk_index']);require(original is not None and source['title']==original['title'] and source['url']==original['url'] and source['supports']==[encode(v) for v in original['supports']],'search.raw_provenance_mismatch')
 for page in state['web_pages']:
  if page['text_sha256'] is not None:require(len(read(db,page['text_sha256']).decode('utf-8'))==page['char_count'],'search.raw_provenance_mismatch')
 pages={v['id']:v for v in state['web_pages']};sources={v['id']:v for v in state['style_sources']}
 for imported in state['web_imports']:
  page=pages[imported['page_id']];source=sources[imported['source_id']];actual=read(db,source['blob_sha256']).decode(source['encoding']);expected=read(db,page['text_sha256']).decode('utf-8')[imported['start']:imported['end']];require(actual==expected,'search.raw_provenance_mismatch')


def validate_trial_refs(db,state):
 from novel_writer.domain.style_trials import trial_body
 from novel_writer.domain.tasks import parse,encode
 from novel_writer.domain.model_contract import ProviderResponse
 from novel_writer.storage.json_codec import strict_json_loads
 for task in state['style_trial_tasks']:require(read(db,task['body_sha256']).decode('utf-8')==trial_body(task),'trial.raw_provenance_mismatch')
 for result in state['style_trial_results']:
  response=parse(ProviderResponse,strict_json_loads(read(db,result['response_sha256'])));require(result['usage']==encode(response.usage) and result['reported_model']==response.reported_model,'trial.raw_provenance_mismatch')
  for candidate in state['style_trial_candidates']:
   if candidate['result_id']==result['id']:require(response.complete and candidate['output_text']==response.output_text,'trial.raw_provenance_mismatch')
