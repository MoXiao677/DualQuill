"""TXT/Markdown chapter detection, preview, append import and saved-only export."""
import base64,binascii,hashlib,json,re
from pathlib import Path
from novel_writer.domain.tasks import require
from novel_writer.application.fields import check_fields
from novel_writer.storage.json_codec import document_from_dict,document_to_dict

MAX_BYTES=5*1024*1024
MAX_CHAPTERS=500
ENCODINGS=('auto','utf-8','utf-8-sig','gb18030')
FENCE=re.compile(r'^\s*(```|~~~)')
MD=re.compile(r'^(#{1,2})\s+(.+?)\s*#*\s*$')
CN=re.compile(r'^\s*第\s*[0-9零〇一二三四五六七八九十百千万两]+\s*[章节]\s*(.*?)\s*$')
EN=re.compile(r'^\s*Chapter\s+([0-9]+|[IVXLCDM]+)\b\s*[:.\-]?\s*(.*?)\s*$',re.IGNORECASE)

def _decode(raw,encoding):
 require(type(raw) is bytes and len(raw)<=MAX_BYTES,'文件超过 5 MiB 上限')
 require(encoding in ENCODINGS,'不支持的编码选项')
 if raw.startswith((b'\xff\xfe\x00\x00',b'\x00\x00\xfe\xff',b'\xff\xfe',b'\xfe\xff')):
  raise ValueError('检测到 UTF-16/UTF-32 BOM；当前只支持 UTF-8（含 BOM）与 GB18030')
 if raw.startswith(b'\xef\xbb\xbf') and encoding in ('auto','utf-8','utf-8-sig'):
  try:return raw.decode('utf-8-sig'),'utf-8-sig'
  except UnicodeDecodeError:raise ValueError('文件带有 UTF-8 BOM，但后续字节不是合法 UTF-8') from None
 if encoding=='auto':
  try:text=raw.decode('utf-8');actual='utf-8'
  except UnicodeDecodeError:
   try:text=raw.decode('gb18030');actual='gb18030'
   except UnicodeDecodeError:raise ValueError('文件既不是严格 UTF-8，也不是严格 GB18030；已拒绝导入且不做乱码替换') from None
  require('\x00' not in text,'文件包含 NUL 字节，无法作为 TXT/Markdown 导入')
  return text,actual
 try:text=raw.decode(encoding)
 except UnicodeDecodeError:raise ValueError('文件无法按所选编码解码，请核对编码后重试') from None
 require('\x00' not in text,'文件包含 NUL 字节，无法作为 TXT/Markdown 导入')
 return text,encoding

def _heading(line):
 stripped=line.strip()
 match=FENCE.match(stripped)
 if match:return None
 match=MD.match(stripped)
 if match:
  inner=match.group(2).strip();cn=CN.match(inner)
  return (cn.group(1) or inner).strip() if cn else inner
 match=CN.match(stripped)
 if match:return (match.group(1) or stripped).strip()
 match=EN.match(stripped)
 if match:return stripped
 return None

def detect(text,filename):
 require(type(text) is str and filename.lower().endswith(('.txt','.md')),'只支持 .txt 或 .md 文件')
 lines=text.splitlines(keepends=True);markers=[];offset=0;fenced=False
 for line in lines:
  if FENCE.match(line.strip()):fenced=not fenced
  elif not fenced:
   title=_heading(line)
   if title is not None:markers.append((offset,offset+len(line),title))
  offset+=len(line)
 if not markers:
  markers=[(0,0,Path(filename).stem or '导入章节')]
 preamble=text[:markers[0][0]]
 if preamble:markers.insert(0,(0,0,'前言（标题前原文）'))
 items=[]
 for index,(start,content_start,title) in enumerate(markers):
  end=markers[index+1][0] if index+1<len(markers) else len(text)
  if content_start>end:content_start=end
  content=text[content_start:end]
  items.append(dict(index=index+1,title=title.strip()[:300] or f'导入章节 {index+1}',start=start,content_start=content_start,end=end,chars=len(content),content=content,preview=content[:200]))
 require(len(items)<=MAX_CHAPTERS,'分章数量超过 500 上限')
 return items,preamble

def _source_sha(raw):return hashlib.sha256(raw).hexdigest()
def _preview_sha(raw,encoding,items):
 body=json.dumps(dict(contract='preserve-preamble-v2',source=_source_sha(raw),encoding=encoding,ranges=[(v['start'],v['content_start'],v['end']) for v in items]),ensure_ascii=False,sort_keys=True,separators=(',',':'))
 return hashlib.sha256(body.encode('utf-8')).hexdigest()

def preview(project_id,raw,encoding,state,filename='导入.txt'):
 decoded,actual=_decode(raw,encoding);items,preamble=detect(decoded,filename)
 return dict(project_id=project_id,filename=filename,requested_encoding=encoding,encoding=actual,encoding_auto=encoding=='auto',source_sha256=_source_sha(raw),preview_sha256=_preview_sha(raw,actual,items),items=items,preamble_chars=len(preamble),total_chars=len(decoded),workspace_revision=state['revision'],encoding_policy='BOM/UTF-8 优先，失败后严格 GB18030，仍失败则拒绝；从不使用替换字符')

def import_chapters(state,values):
 check_fields(values,{'filename','content_base64','encoding','items','preview_sha256','confirmed'})
 require(set(values)=={'filename','content_base64','encoding','items','preview_sha256','confirmed'} and values['confirmed'] is True,'导入需要明确确认')
 require(type(values['content_base64']) is str and len(values['content_base64'])<=MAX_BYTES*2,'文件超过上限')
 try:raw=base64.b64decode(values['content_base64'],validate=True)
 except (binascii.Error,ValueError):raise ValueError('文件内容不是有效 base64') from None
 decoded,actual=_decode(raw,values['encoding']);detected,preamble=detect(decoded,values['filename'])
 require(values['preview_sha256']==_preview_sha(raw,actual,detected),'文件内容或分章范围已变化，请重新预览')
 require(type(values['items']) is list and len(values['items'])==len(detected),'映射条目数量与预览不一致')
 from novel_writer.application.chapter_lifecycle import upgrade_base as upgrade
 from novel_writer.application.versions import record
 from novel_writer.domain.models import BookOutline,Chapter,VolumePlan
 from novel_writer.domain.models import utc_now
 upgrade(state);document=document_from_dict(state['document']);project_id=document.project.id
 number=max((v.number for v in document.chapters),default=0);created=[]
 for expected,item in zip(detected,values['items']):
  compact={'index','title','start','content_start','end','chars'}
  require(type(item) is dict and set(item) in (compact,compact|{'content','preview'}),'映射字段缺失或含未知字段')
  require(all(type(item[k]) is int and item[k]==expected[k] for k in ('index','start','content_start','end','chars')),'映射范围与文件不一致')
  if 'content' in item:require(item['content']==expected['content'],'映射正文与文件不一致')
  require(type(item['title']) is str and 0<len(item['title'].strip())<=300,'章节标题无效');number+=1
  chapter=Chapter(project_id=project_id,number=number,title=item['title'].strip());chapter.content=expected['content'];document.chapters.append(chapter);record(document,'chapter',chapter,'TXT/MD 导入章节');created.append(chapter.id)
 if document.book_outline is None:document.book_outline=BookOutline(project_id=project_id)
 volume=VolumePlan(number=max((v.number for v in document.book_outline.volumes),default=0)+1,title=(Path(values['filename']).stem or '导入章节')[:100],summary='TXT/MD 导入',chapter_ids=created);document.book_outline.volumes.append(volume);record(document,'book_outline',document.book_outline,'TXT/MD 导入新建分卷')
 document.project.updated_at=utc_now();state['document']=document_to_dict(document)
 return state

def _chapters(state,scope,chapter_id=None,volume_number=None):
 doc=state['document'];from novel_writer.domain.chapter_trash import hidden_ids
 hidden=hidden_ids(state);ordered=sorted(doc['chapters'],key=lambda c:c['number'])
 visible=[c for c in ordered if c['id'] not in hidden]
 if scope=='book':return visible
 if scope=='chapter':
  value=next((c for c in ordered if c['id']==chapter_id),None);require(value is not None,'导出章节不存在');require(value['id'] not in hidden,'导出章节已在归档或回收站');return [value]
 require(scope=='volume' and doc['book_outline'] is not None,'导出范围或分卷无效');volume=next((v for v in doc['book_outline']['volumes'] if v['number']==volume_number),None);require(volume is not None,'导出分卷不存在');ids=set(volume['chapter_ids']);return [c for c in visible if c['id'] in ids]

def _safe(value):
 cleaned=re.sub(r'[\\/:*?"<>|\r\n\t]+','_',value).strip(' ._');return (cleaned or 'novel')[:80]

def export_text(state,scope,format,chapter_id=None,volume_number=None):
 require(scope in ('chapter','volume','book') and format in ('txt','md'),'导出范围或格式无效');doc=state['document'];chapters=_chapters(state,scope,chapter_id,volume_number)
 pieces=[]
 if scope=='volume' and format=='md':
  volume=next(v for v in doc['book_outline']['volumes'] if v['number']==volume_number);pieces.append('# '+volume['title']+'\n\n')
 for chapter in chapters:
  heading=('## ' if format=='md' else '')+f"第{chapter['number']}章 {chapter['title']}";pieces.append(heading+'\n'+chapter['content']+('\n' if not chapter['content'].endswith('\n') else '')+'\n')
 return ''.join(pieces)

def export_payload(state,scope,format,chapter_id=None,volume_number=None):
 text=export_text(state,scope,format,chapter_id,volume_number);doc=state['document']
 name=doc['project']['title']
 if scope=='chapter':name=next(c['title'] for c in doc['chapters'] if c['id']==chapter_id)
 elif scope=='volume':name=next(v['title'] for v in doc['book_outline']['volumes'] if v['number']==volume_number)
 return dict(filename=_safe(name)+'.'+format,text=text,media_type='text/markdown; charset=utf-8' if format=='md' else 'text/plain; charset=utf-8')
