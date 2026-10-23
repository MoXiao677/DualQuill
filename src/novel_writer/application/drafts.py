"""Local unsaved-input drafts outside the workspace database and backup package."""
from hashlib import sha256
import json,os,re,tempfile,threading
from pathlib import Path
from datetime import datetime,timezone
from functools import wraps

ALLOWED_VIEWS={'writing','project','outline','world','rules','characters','memory'}
PANES={'body','idea','outline'}
MAX_DRAFT_BYTES=1024*1024
MAX_FILES=10000
SENSITIVE_FIELD_PATTERN=re.compile(r"api_key|apikey|token|secret|password|passwd|authorization|credential|bearer|private_key",re.IGNORECASE)

class DraftError(ValueError):pass

def _now():return datetime.now(timezone.utc).isoformat(timespec='microseconds')

def _key(value,project):
 if type(value) is not str:raise DraftError('草稿文档键无效')
 if len(value)>500:raise DraftError('草稿文档键过长')
 try:value.encode('utf-8')
 except UnicodeError:raise DraftError('草稿文档键包含无效字符') from None
 try:parsed=json.loads(value)
 except (ValueError,TypeError):raise DraftError('草稿文档键无效')
 if type(parsed) is not list or len(parsed)!=4 or any(type(v) is not str for v in parsed):raise DraftError('草稿文档键无效')
 if parsed[0]!=project or parsed[1] not in ALLOWED_VIEWS:raise DraftError('草稿不属于当前小说的允许文档')
 view=parsed[1]
 if view=='writing':
  if not parsed[2] or parsed[3] not in PANES:raise DraftError('正文草稿须带章节与正文/IDEA/细纲分区')
 elif view=='characters':
  if not parsed[2] or parsed[3]:raise DraftError('人物草稿须带人物编号')
 elif view=='memory':
  if not parsed[2] or parsed[3]:raise DraftError('记忆草稿须带记忆编号')
 else:
  if parsed[2] or parsed[3]:raise DraftError('该文档不能保存草稿')
 return parsed

def _values(value):
 if type(value) is not dict or len(value)>200:raise DraftError('草稿字段无效或超限')
 result={}
 for key,item in value.items():
  if type(key) is not str or not 0<len(key)<=100:raise DraftError('草稿字段名无效')
  if type(item) in (str,bool,int):result[key]=item
  elif type(item) is list and len(item)<=100 and all(type(v) is str and len(v)<=1000 for v in item):result[key]=list(item)
  else:raise DraftError('草稿字段值类型无效')
 try:json.dumps(result,ensure_ascii=False).encode('utf-8')
 except UnicodeError:raise DraftError('草稿字段包含无效字符，请保留输入后核对') from None
 return result

def _position(value):
 if value is None:return {}
 if type(value) is not dict or set(value)-{'top','left','cursor','end','editorTop'}:raise DraftError('草稿位置无效')
 result={}
 for key,item in value.items():
  if type(item) is not int or not 0<=item<=10**9:raise DraftError('草稿位置无效')
  result[key]=item
 return result

def _filename(project,key):return sha256((project+'\0'+key).encode('utf-8')).hexdigest()+'.json'

def filter_sensitive_fields(draft):
 """Return a copy without values for fields whose names can carry credentials."""
 result=dict(draft)
 values=dict(result.get('values',{}))
 removed=[key for key in values if SENSITIVE_FIELD_PATTERN.search(key)]
 for key in removed:values.pop(key)
 result['values']=values
 if removed or result.get('sensitive_fields_required') is True:result['sensitive_fields_required']=True
 else:result.pop('sensitive_fields_required',None)
 return result

def draft_entity_references(record):
 parsed=json.loads(record['document_key'])
 refs=[]
 kind={'writing':'chapter','characters':'character','memory':'memory'}.get(parsed[1])
 if kind and parsed[2]:refs.append((kind,parsed[2]))
 for key,value in record.get('values',{}).items():
  normalized=key.lower()
  inferred=next((candidate for candidate in ('chapter','character','memory') if normalized.endswith(candidate+'_id') or normalized.endswith(candidate+'_ids')),None)
  if inferred is None:continue
  if normalized.endswith('_ids'):refs.extend((inferred,item) for item in value)
  elif value:refs.append((inferred,value))
 return refs

def validate_draft_record(value):
 required={'project_id','document_key','base_revision','values','position','updated_at'}
 allowed=required|{'sensitive_fields_required'}
 if type(value) is not dict or set(value)-allowed or not required<=set(value):raise DraftError('草稿格式无效')
 project=value['project_id']
 if type(project) is not str or not project or len(project)>500:raise DraftError('草稿项目无效')
 key=json.dumps(_key(value['document_key'],project),ensure_ascii=False,separators=(',',':'))
 if type(value['base_revision']) is not int or value['base_revision']<0:raise DraftError('草稿保存编号无效')
 values=_values(value['values']);position=_position(value['position'])
 if type(value['updated_at']) is not str or len(value['updated_at'])>100:raise DraftError('草稿时间无效')
 try:stamp=datetime.fromisoformat(value['updated_at'])
 except ValueError:raise DraftError('草稿时间无效') from None
 if stamp.tzinfo is None:raise DraftError('草稿时间缺少时区')
 marker=value.get('sensitive_fields_required',False)
 if type(marker) is not bool:raise DraftError('草稿格式无效')
 result=dict(project_id=project,document_key=key,base_revision=value['base_revision'],values=values,position=position,updated_at=value['updated_at'])
 if marker:result['sensitive_fields_required']=True
 return result

def _synchronized(method):
 @wraps(method)
 def locked(self,*args,**kwargs):
  with self._lock:return method(self,*args,**kwargs)
 return locked

def read_draft(path):
 """Validate a recovery record; never reinterpret malformed metadata as a draft."""
 if path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction()):raise DraftError('草稿文件类型无效')
 if path.stat().st_size>MAX_DRAFT_BYTES:raise DraftError('草稿超过本地容量上限')
 value=json.loads(path.read_text(encoding='utf-8'))
 if type(value) is not dict or set(value) not in ({'version','project_id','document_key','base_revision','values','position','updated_at'}, {'version','project_id','document_key','base_revision','values','position','updated_at','sensitive_fields_required'}):raise DraftError('草稿格式无效')
 if type(value['version']) is not int or value['version']!=1:raise DraftError('草稿版本无效')
 record=validate_draft_record({key:item for key,item in value.items() if key!='version'})
 if _filename(record['project_id'],record['document_key'])!=path.name:raise DraftError('草稿文件名与文档不匹配')
 return record

class DiskDrafts:
 def __init__(self,directory,*,create=True):
  self.directory=Path(directory)
  self._lock=threading.RLock()
  # A failed recovery partition must not prevent opening the saved book.
  if create:
   try:self.directory.mkdir(parents=True,exist_ok=True)
   except OSError:pass
 def _path(self,project,key):
  target=self.directory/_filename(project,key)
  if self.directory.resolve() not in target.resolve().parents:raise DraftError('草稿路径无效')
  return target
 def _write_record(self,record,*,only_if_missing=False):
  record=validate_draft_record(record)
  project,key=record['project_id'],record['document_key']
  target=self._path(project,key);temporary=None
  try:
   self.directory.mkdir(parents=True,exist_ok=True)
   if only_if_missing and target.exists():return False
   value=dict(version=1,**record)
   raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
   if len(raw)>MAX_DRAFT_BYTES:raise DraftError('草稿超过本地容量上限')
   handle=tempfile.NamedTemporaryFile(prefix='.draft-',suffix='.tmp',dir=self.directory,delete=False)
   temporary=Path(handle.name)
   with handle:
    handle.write(raw);handle.flush();os.fsync(handle.fileno())
   os.replace(temporary,target)
  except OSError:
   if temporary is not None:
    try:temporary.unlink()
    except OSError:pass
   raise DraftError('本地草稿保存失败，请保留输入后重试') from None
  return True
 @_synchronized
 def save(self,project,document_key,base_revision,values,position=None):
  key=json.dumps(_key(document_key,project),ensure_ascii=False,separators=(',',':'))
  if type(base_revision) is not int or base_revision<0:raise DraftError('草稿保存编号无效')
  target=self._path(project,key);sensitive_required=False
  if target.exists():
   try:sensitive_required=read_draft(target).get('sensitive_fields_required',False)
   except (OSError,ValueError,TypeError,KeyError):pass
  record=dict(project_id=project,document_key=key,base_revision=base_revision,values=_values(values),position=_position(position),updated_at=_now())
  if sensitive_required:record['sensitive_fields_required']=True
  self._write_record(record)
  return validate_draft_record(record)
 @_synchronized
 def import_record(self,record,*,only_if_missing=False):
  return self._write_record(filter_sensitive_fields(validate_draft_record(record)),only_if_missing=only_if_missing)
 @_synchronized
 def list_all(self):
  drafts=[];corrupt=[];unreadable=0;unreadable_files=[]
  if not self.directory.exists():return dict(drafts=drafts,corrupt=corrupt)
  try:
   files=[]
   for path in self.directory.iterdir():
    if path.suffix=='.json':files.append(path)
   if len(files)>MAX_FILES:raise DraftError('本地草稿数量超过读取上限；请先预览本地诊断，不要删除正式历史')
   files.sort()
  except OSError:raise DraftError('本地草稿读取失败；请保留当前输入，检查存储后重试') from None
  for path in files[:MAX_FILES]:
   try:drafts.append(read_draft(path))
   except OSError:unreadable+=1;unreadable_files.append(path.name)
   except (ValueError,TypeError,KeyError,UnicodeError,RecursionError):corrupt.append(path.name)
  result=dict(drafts=drafts,corrupt=corrupt)
  if unreadable:result['unreadable']=unreadable;result['unreadable_files']=unreadable_files
  return result
 @_synchronized
 def list(self,project):
  result=self.list_all()
  result['drafts']=[draft for draft in result['drafts'] if draft['project_id']==project]
  result.pop('unreadable_files',None)
  return result
 @_synchronized
 def clear(self,project,document_key):
  key=json.dumps(_key(document_key,project),ensure_ascii=False,separators=(',',':'))
  target=self._path(project,key)
  try:target.unlink()
  except FileNotFoundError:return dict(cleared=False)
  except OSError:raise DraftError('本地草稿清除失败') from None
  return dict(cleared=True)
