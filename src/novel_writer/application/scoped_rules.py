"""Scoped rule CRUD, history, import preview and resolution: chapter > volume > book > global."""
import csv
import io
import json
from copy import deepcopy
from uuid import uuid4,uuid5,NAMESPACE_URL
from novel_writer.domain.scoped_rules import Rule,RuleHistory,SCOPES,KINDS
from novel_writer.domain.models import utc_now
from novel_writer.domain.tasks import require,uuid_value,digest
from novel_writer.application.fields import check_fields

ORDER={'task':-1,'chapter':0,'volume':1,'book':2,'global':3}
IMPORT_FIELDS=('scope','scope_id','kind','text','enabled')
MAX_IMPORT_BYTES=512*1024
MAX_IMPORT_RULES=500
IMPORT_PREVIEW_VERSION=1

def upgrade(state):
 from novel_writer.application.console import upgrade as previous
 previous(state);state['workspace_version']=max(state['workspace_version'],22);state.setdefault('scoped_rules',[]);state.setdefault('scoped_rule_history',[]);return state

def _chapter(state,chapter_id):
 return next((v for v in state['document']['chapters'] if v['id']==chapter_id),None)

def _volume_for_chapter(state,chapter_id):
 outline=state['document']['book_outline']
 if outline is None:return None
 return next((v for v in outline['volumes'] if chapter_id in v['chapter_ids']),None)

def legacy_rule(state):
 text=state.get('writing_rules','')
 if not text.strip():return None
 return dict(id=str(uuid5(NAMESPACE_URL,state['document']['project']['id']+'/legacy-writing-rules')),project_id=state['document']['project']['id'],scope='book',scope_id=state['document']['project']['id'],kind='guidance',text=text,enabled=True,archived=False,source='legacy',version=1,created_at='1970-01-01T00:00:00+00:00',updated_at='1970-01-01T00:00:00+00:00')

def task_binding(state,identifier,chapter_id=None):
 uuid_value(identifier)
 binding=next((v for v in state.get('rule_task_bindings',[]) if v['id']==identifier),None)
 require(binding is not None and binding['project_id']==state['document']['project']['id'],'任务规则目标不存在或不属于当前书')
 require(chapter_id is None or binding['chapter_id']==chapter_id,'任务规则目标章节不匹配')
 return binding

def _resolve(state,chapter_id,extra=(),task_id=None,*,complete=False):
 if task_id is not None:task_binding(state,task_id,chapter_id)
 chapter=_chapter(state,chapter_id);require(chapter is not None,'目标章节不存在');volume=_volume_for_chapter(state,chapter_id);project=state['document']['project']['id'];candidates=[]
 legacy=legacy_rule(state)
 if legacy:candidates.append(legacy)
 for rule in list(state.get('scoped_rules',[]))+list(extra):
  if not rule['enabled'] or rule['archived']:continue
  if rule['scope']=='global' or rule['scope']=='book' and rule['scope_id']==project or rule['scope']=='volume' and volume is not None and rule['scope_id']==str(volume['number']) or rule['scope']=='chapter' and rule['scope_id']==chapter_id or rule['scope']=='task' and task_id is not None and rule['scope_id']==task_id:candidates.append(deepcopy(rule))
 candidates.sort(key=lambda v:(ORDER[v['scope']],0 if v['kind']=='required' else 1 if v['kind']=='forbidden' else 2,str(v['id'])))
 deduped=[];seen=set()
 for rule in candidates:
  key=(rule['kind'],rule['text'])
  if key in seen:continue
  seen.add(key);deduped.append(rule)
 conflicts=[]
 by_text={}
 for rule in deduped:by_text.setdefault(rule['text'],[]).append(rule)
 for text,rules in by_text.items():
  kinds={v['kind'] for v in rules}
  if 'required' in kinds and 'forbidden' in kinds:conflicts.append(dict(text=text,rule_ids=[v['id'] for v in rules],scopes=[v['scope'] for v in rules]))
 return dict(chapter_id=chapter_id,volume_number=volume['number'] if volume else None,rules=candidates if complete else deduped,conflicts=conflicts)

def resolve(state,chapter_id,task_id=None):return _resolve(state,chapter_id,task_id=task_id)

def require_no_conflicts(state,chapter_id,task_id=None,*,complete=False):
 result=_resolve(state,chapter_id,task_id=task_id,complete=complete);require(not result['conflicts'],'scoped_rules.conflict');return result

def operation_rules(state,chapter_id,options,capability,request_id=None):
 target=options.get('rule_task_id')
 if target is not None:
  require(task_binding(state,target,chapter_id)['task_type']==capability,'scoped_rules.task_capability_mismatch')
  if request_id is not None:require(target==request_id,'scoped_rules.task_request_mismatch')
 elif request_id is not None:require(not any(b['id']==request_id for b in state.get('rule_task_bindings',[])),'scoped_rules.reserved_binding_required')
 return require_no_conflicts(state,chapter_id,target,complete=target is not None)

def require_fresh_rules(state,task):
 from novel_writer.domain.tasks import capture_dependency,dependency_equal
 from novel_writer.application.semantic_summaries import is_summary
 from novel_writer.domain.graph_extraction import is_graph
 if is_summary(task):return
 # Graph dependencies are a complete identity guard, independent of display-text dedup.
 # Old frozen inputs remain immutable; an incomplete old snapshot must be re-prepared.
 resolved=require_no_conflicts(state,task.chapter_id,task.frozen.context_options.rule_task_id,complete=is_graph(task))
 frozen=[v for v in task.frozen.dependencies if v.kind=='rule']
 require({v.entity_id for v in frozen}=={v['id'] for v in resolved['rules']},'规则集合已变化，请重新准备任务')
 for dep in frozen:require(dependency_equal(dep,capture_dependency(state,'rule',dep.entity_id,use=dep.use)),'规则版本已变化，请重新准备任务')

def _history(state,rule_id,operation,before,after,source='manual',identifier=None):
 entry=RuleHistory(id=identifier or str(uuid4()),project_id=state['document']['project']['id'],rule_id=rule_id,operation=operation,before=deepcopy(before),after=deepcopy(after),source=source,created_at=utc_now())
 state.setdefault('scoped_rule_history',[]).append(encode_safe(entry))
 return entry

def _import_rows(fmt,content):
 require(fmt in ('json','csv'),'导入格式只支持 JSON 或 CSV')
 require(type(content) is str,'导入内容必须是文字')
 require(len(content.encode('utf-8'))<=MAX_IMPORT_BYTES,'导入内容超过 512 KiB 上限')
 if fmt=='json':
  try:data=json.loads(content)
  except RecursionError:raise ValueError('JSON 嵌套过深') from None
  except json.JSONDecodeError as error:raise ValueError('JSON 解析失败：第 '+str(error.lineno)+' 行第 '+str(error.colno)+' 列') from None
  if type(data) is dict and set(data)=={'rules'}:data=data['rules']
  require(type(data) is list,'JSON 顶层必须是规则数组，或只含 rules 的对象')
  require(len(data)<=MAX_IMPORT_RULES,'导入条数超过 500 上限')
  return [(number,row) for number,row in enumerate(data,1)]
 rows=[]
 try:reader=csv.reader(io.StringIO(content,newline=''))
 except TypeError:reader=csv.reader(io.StringIO(content))
 try:header=next(reader)
 except StopIteration:raise ValueError('CSV 内容为空') from None
 if header:header[0]=header[0].lstrip('\ufeff')
 require(header==list(IMPORT_FIELDS),'CSV 表头必须为 scope,scope_id,kind,text,enabled')
 try:
  for values in reader:
   number=reader.line_num
   if not values or all(not value.strip() for value in values):continue
   if len(values)!=len(IMPORT_FIELDS):
    rows.append((number,{'__raw__':values}))
   else:
    row=dict(zip(IMPORT_FIELDS,values))
    if type(row.get('enabled')) is str:
     lowered=row['enabled'].strip().lower()
     if lowered in ('true','false'):row['enabled']=lowered=='true'
    rows.append((number,row))
   require(len(rows)<=MAX_IMPORT_RULES,'导入条数超过 500 上限')
 except csv.Error as error:raise ValueError('CSV 解析失败：'+str(error)) from None
 return rows

def _normalize_rule(state,row):
 errors=[]
 if type(row) is not dict or '__raw__' in row:
  return None,[dict(field='*',message='CSV 列数必须为 5')]
 unknown=set(row)-set(IMPORT_FIELDS);missing=[name for name in IMPORT_FIELDS if name not in row]
 if unknown:errors.append(dict(field=','.join(sorted(unknown)),message='含未知字段'))
 if missing:errors.append(dict(field=','.join(missing),message='字段缺失'))
 scope=row.get('scope');kind=row.get('kind');text=row.get('text');enabled=row.get('enabled');scope_id=row.get('scope_id')
 if type(scope) is not str or scope not in SCOPES:errors.append(dict(field='scope',message='作用域必须是 global/book/volume/chapter/task'))
 if type(kind) is not str or kind not in KINDS:errors.append(dict(field='kind',message='类型必须是 required/forbidden/guidance'))
 if type(text) is not str or not text.strip() or len(text)>2000:errors.append(dict(field='text',message='原文必须是 1–2000 字文字'))
 if type(enabled) is not bool:errors.append(dict(field='enabled',message='enabled 必须是布尔值 true/false'))
 normalized=None
 if scope in SCOPES:
  project=state['document']['project']['id'];outline=state['document']['book_outline'];volumes={str(v['number']) for v in (outline['volumes'] if outline else [])};chapters={v['id'] for v in state['document']['chapters']}
  if scope=='global':
   if scope_id not in (None,''):errors.append(dict(field='scope_id',message='全局规则不接受实体编号'))
   normalized=None
  elif scope=='book':
   if scope_id in (None,''):normalized=project
   elif scope_id==project:normalized=project
   else:errors.append(dict(field='scope_id',message='书级规则必须绑定当前书'))
  elif scope=='volume':
   normalized=str(scope_id) if type(scope_id) in (str,int) else None
   if normalized not in volumes:errors.append(dict(field='scope_id',message='卷级规则目标不存在'))
  elif scope=='chapter':
   normalized=scope_id
   if type(normalized) is not str or normalized not in chapters:errors.append(dict(field='scope_id',message='章级规则目标不存在'))
  else:
   normalized=scope_id
   try:task_binding(state,scope_id)
   except ValueError:errors.append(dict(field='scope_id',message='任务规则目标不存在或不属于当前书'))
 return (dict(scope=scope,scope_id=normalized,kind=kind,text=text,enabled=enabled) if not errors else None),errors

def _conflicts(state,extra):
 found={}
 targets=[(c['id'],None) for c in state['document']['chapters']]+[(v['chapter_id'],v['id']) for v in state.get('rule_task_bindings',[]) if any(r['scope']!='task' or r['scope_id']==v['id'] for r in extra)]
 for chapter_id,task_id in targets:
  for conflict in _resolve(state,chapter_id,extra,task_id)['conflicts']:
   key=json.dumps(conflict,sort_keys=True,ensure_ascii=False)
   found[key]=conflict
 result=[]
 for conflict in found.values():
  rows=sorted(int(value.split(':',1)[1]) for value in conflict['rule_ids'] if type(value) is str and value.startswith('import:'))
  conflict['rows']=rows;conflict['blocks_import']=bool(rows);result.append(conflict)
 return result

def _preview(state,fmt,content):
 raw_rows=_import_rows(fmt,content)
 rows=[];proposed=[];blocked=False
 for number,raw in raw_rows:
  rule,errors=_normalize_rule(state,raw)
  item=dict(row=number,status='ok' if not errors else 'error',errors=errors)
  if rule is None:blocked=True
  else:
   item['rule']=rule;proposed.append(dict(rule,id='import:'+str(number),archived=False,source='import',version=1,project_id=state['document']['project']['id']))
  rows.append(item)
 conflicts=_conflicts(state,proposed) if proposed else []
 if conflicts:blocked=True
 by_row={item['row']:item for item in rows}
 for conflict in conflicts:
  for number in conflict['rows']:
   item=by_row.get(number)
   if item is None:continue
   item['status']='conflict';item['errors'].append(dict(field='text',message='与现有或其它的同类文本构成 required/forbidden 冲突'))
 normalized=[dict(scope=rule['scope'],scope_id=rule['scope_id'],kind=rule['kind'],text=rule['text'],enabled=rule['enabled']) for item in rows if item.get('rule') for rule in (item['rule'],)]
 preview_sha256=digest(json.dumps(dict(version=IMPORT_PREVIEW_VERSION,revision=state['revision'],format=fmt,rules=normalized),ensure_ascii=False,sort_keys=True,separators=(',',':')))
 return dict(revision=state['revision'],format=fmt,count=len(rows),rows=rows,conflicts=conflicts,can_confirm=bool(rows) and not blocked,preview_sha256=preview_sha256)

class RuleCoordinator:
 def __init__(self,service):self.service,self.repository=service,service.repository
 def list(self,project,chapter_id=None):
  state=self.service.get(project);rules=deepcopy(state.get('scoped_rules',[]));existing={v['id'] for v in rules};history=state.get('scoped_rule_history',[])
  deleted=list(dict.fromkeys(entry['rule_id'] for entry in history if entry['rule_id'] not in existing))
  result=dict(revision=state['revision'],rules=rules,legacy=legacy_rule(state),deleted_rule_ids=deleted,task_bindings=deepcopy(state.get('rule_task_bindings',[])))
  if chapter_id:result.update(resolve(state,chapter_id))
  return result
 def resolve(self,project,chapter_id,task_id=None):return resolve(self.service.get(project),chapter_id,task_id)
 def bind_task(self,project,request):
  fields={'request_id','chapter_id','task_type'};check_fields(request,fields);require(set(request)==fields,'任务绑定字段不完整')
  from novel_writer.domain.scoped_rules import TaskRuleBinding
  identifier=uuid_value(request['request_id'])
  def operation(state):
   require(_chapter(state,request['chapter_id']) is not None,'任务目标章节不存在')
   existing=next((v for v in state.get('rule_task_bindings',[]) if v['id']==identifier),None)
   if existing:
    require(all(existing[k]==request[k] for k in ('chapter_id','task_type')),'任务规则身份已绑定不同目标');return None,deepcopy(existing)
   require(not any(v['request_id']==identifier for name in ('generation_tasks','chapter_planning_tasks','scene_expansion_tasks','rule_review_tasks') for v in state.get(name,[])),'已冻结任务不能补绑规则')
   from novel_writer.application.chapter_lifecycle import upgrade as prior
   prior(state);state['workspace_version']=max(state['workspace_version'],36)
   if request['task_type'] in ('brainstorm_chapter','outline_chapter','expand_scene_selection'):
    from novel_writer.application.rule_reviews import upgrade as v37
    v37(state)
   binding=encode_safe(TaskRuleBinding(id=identifier,project_id=project,chapter_id=request['chapter_id'],task_type=request['task_type'],created_at=utc_now()))
   state.setdefault('rule_task_bindings',[]).append(binding);return state,deepcopy(binding)
  return self.repository.atomic(project,operation)
 def resolve_task(self,project,request):
  fields={'chapter_id','task_id'};check_fields(request,fields);require(set(request)==fields,'任务解析字段不完整')
  return self.resolve(project,request['chapter_id'],request['task_id'])
 def semantic_preview(self,project,request):
  fields={'chapter_id','task_id','observations'};check_fields(request,fields);require(set(request)==fields,'语义意见字段不完整')
  state=self.service.get(project);resolved=resolve(state,request['chapter_id'],request['task_id']);rules={v['id']:v for v in resolved['rules']}
  require(type(request['observations']) is list and len(request['observations'])<=100,'语义意见必须为至多100条列表')
  proposals=[]
  for raw in request['observations']:
   require(type(raw) is dict and set(raw)=={'rule_ids','quotes','reason'},'语义意见含未知或缺失字段')
   ids=raw['rule_ids'];quotes=raw['quotes'];reason=raw['reason']
   require(type(ids) is list and len(ids)==2 and all(type(v) is str and v in rules for v in ids) and len(set(ids))==2,'语义意见必须引用当前生效的两条不同规则')
   require(type(quotes) is list and len(quotes)==2 and all(type(q) is str and bool(q.strip()) and q in rules[i]['text'] for i,q in zip(ids,quotes)),'语义意见引文必须逐字匹配相应规则')
   require(type(reason) is str and 0<len(reason.strip())<=2000,'语义意见理由非法')
   proposals.append(dict(status='needs_verification',rule_ids=ids,quotes=quotes,reason=reason,rules=[deepcopy(rules[i]) for i in ids],hard_conflict=False,can_apply=False))
  return dict(revision=state['revision'],proposals=proposals,exact_conflicts=resolved['conflicts'],semantic_quality_verified=False,model_request_sent=False,automatic_rule_changes=False,notes='仅校验作者提交的模型或人工意见的结构和逐字引文；语义判断仍待人工核实，不能自动豁免、停用或删除强制规则。')
 def history(self,project,rule_id=None):
  state=self.service.get(project)
  if rule_id is not None:uuid_value(rule_id)
  entries=[deepcopy(v) for v in state.get('scoped_rule_history',[]) if rule_id is None or v['rule_id']==rule_id]
  return dict(revision=state['revision'],rule_id=rule_id,history=entries)
 def list_history(self,project,rule_id=None):return self.history(project,rule_id)
 def preview_import(self,project,request):
  check_fields(request,{'format','content'});require(set(request)=={'format','content'},'导入预览字段不完整')
  return _preview(self.service.get(project),request['format'],request['content'])
 def import_preview(self,project,request):return self.preview_import(project,request)
 def import_rules(self,project,request):
  check_fields(request,{'operation_id','format','content','preview_sha256'});require(set(request)=={'operation_id','format','content','preview_sha256'} and type(request['preview_sha256']) is str and len(request['preview_sha256'])==64,'导入提交字段不完整或预览编号无效');identity=uuid_value(request['operation_id'])
  def operation(state):
   upgrade(state);raw_rows=_import_rows(request['format'],request['content']);normalized=[];errors=[]
   for number,raw in raw_rows:
    rule,row_errors=_normalize_rule(state,raw)
    if row_errors:errors.append((number,row_errors))
    else:normalized.append(rule)
   require(not errors,'导入包含非法行，整体未写入：'+'；'.join('第'+str(number)+'行 '+row_errors[0]['field']+' '+row_errors[0]['message'] for number,row_errors in errors[:5]))
   require(normalized,'导入至少需要一条规则')
   identifiers=[str(uuid5(NAMESPACE_URL,identity+'/rule/'+str(index))) for index in range(1,len(normalized)+1)]
   history_ids=[str(uuid5(NAMESPACE_URL,identity+'/history/'+str(index))) for index in range(1,len(normalized)+1)]
   present={v['id']:v for v in state['scoped_rules']};existing=[present.get(value) for value in identifiers]
   recorded={entry['id'] for entry in state.get('scoped_rule_history',[])};history_seen=[value in recorded for value in history_ids]
   if any(history_seen):
    next_history=str(uuid5(NAMESPACE_URL,identity+'/history/'+str(len(normalized)+1)))
    require(all(history_seen) and next_history not in recorded,'导入操作编号的条数与首次导入不一致')
    require(all(value is not None for value in existing),'导入操作编号对应的规则已被删除，拒绝重放')
    for expected,actual in zip(normalized,existing):
     require(all(actual[name]==expected[name] for name in ('scope','scope_id','kind','text','enabled')),'导入操作编号已绑定不同内容')
    return None,dict(revision=state['revision'],idempotent=True,created=0,rules=deepcopy(existing))
   require(not any(value is not None for value in existing),'导入操作编号已有部分规则，拒绝覆盖')
   preview=_preview(state,request['format'],request['content']);require(preview['preview_sha256']==request['preview_sha256'],'预览已过期或内容不一致，请重新预览');require(preview['can_confirm'],'预览存在错误或冲突，不能导入')
   now=utc_now();created=[]
   for index,(rule,identifier) in enumerate(zip(normalized,identifiers),1):
    value=Rule(id=identifier,project_id=project,scope=rule['scope'],scope_id=rule['scope_id'],kind=rule['kind'],text=rule['text'],enabled=rule['enabled'],archived=False,source='manual',version=1,created_at=now,updated_at=now)
    encoded=encode_safe(value);state['scoped_rules'].append(encoded);created.append(encoded)
    _history(state,identifier,'import',None,encoded,source='import',identifier=str(uuid5(NAMESPACE_URL,identity+'/history/'+str(index))))
   return state,dict(revision=state['revision']+1,idempotent=False,created=len(created),rules=deepcopy(created))
  return self.repository.atomic(project,operation)
 def _scope(self,state,scope,scope_id):
  require(scope in SCOPES,'未知规则作用域')
  if scope=='global':require(scope_id in (None,''),'全局规则不接受实体编号');return None
  if scope=='book':require(scope_id==state['document']['project']['id'],'书级规则必须绑定当前书');return scope_id
  if scope=='volume':require(type(scope_id) is str and scope_id in {str(v['number']) for v in (state['document']['book_outline']['volumes'] if state['document']['book_outline'] else [])},'卷级规则目标不存在');return scope_id
  if scope=='task':task_binding(state,scope_id);return scope_id
  require(scope_id in {v['id'] for v in state['document']['chapters']},'章级规则目标不存在');return scope_id
 def save(self,project,request):
  check_fields(request,{'operation_id','rule_id','scope','scope_id','kind','text','enabled'});require(set(request)=={'operation_id','rule_id','scope','scope_id','kind','text','enabled'} and request['kind'] in KINDS,'规则字段不完整或类型未知');identity=uuid_value(request['operation_id'])
  require(type(request['enabled']) is bool,'规则启用状态必须为布尔值')
  def operation(state):
   upgrade(state);scope_id=self._scope(state,request['scope'],request['scope_id']);existing=next((v for v in state['scoped_rules'] if request['rule_id'] and v['id']==request['rule_id']),None)
   if existing is None:
    require(request['rule_id'] is None,'规则不存在');identifier=str(uuid5(NAMESPACE_URL,identity+'/rule'))
    created=next((v for v in state['scoped_rules'] if v['id']==identifier),None)
    if created is not None:
     require(all(created[name]==request[name] for name in ('scope','kind','text','enabled')) and created['scope_id']==scope_id,'规则操作编号已绑定不同内容');return None,deepcopy(created)
    require(not any(v['rule_id']==identifier for v in state.get('scoped_rule_history',[])),'该规则已删除，拒绝用旧操作编号重建')
    now=utc_now();rule=Rule(id=identifier,project_id=project,scope=request['scope'],scope_id=scope_id,kind=request['kind'],text=request['text'],enabled=request['enabled'],archived=False,source='manual',version=1,created_at=now,updated_at=now);value=encode_safe(rule);state['scoped_rules'].append(value);_history(state,identifier,'create',None,value);return state,deepcopy(value)
   require(existing['archived'] is False,'归档规则不能直接修改');before=deepcopy(existing);existing.update(scope=request['scope'],scope_id=scope_id,kind=request['kind'],text=request['text'],enabled=request['enabled'],version=existing['version']+1,updated_at=utc_now());_history(state,existing['id'],'update',before,existing);return state,deepcopy(existing)
  return self.repository.atomic(project,operation)
 def set_enabled(self,project,request):
  check_fields(request,{'rule_id','enabled'});require(set(request)=={'rule_id','enabled'} and type(request['enabled']) is bool,'启停参数无效')
  def operation(state):
   rule=next((v for v in state['scoped_rules'] if v['id']==request['rule_id']),None);require(rule is not None,'规则不存在');before=deepcopy(rule);rule['enabled']=request['enabled'];rule['version']+=1;rule['updated_at']=utc_now();_history(state,rule['id'],'enable' if request['enabled'] else 'disable',before,rule);return state,deepcopy(rule)
  return self.repository.atomic(project,operation)
 def archive(self,project,request):
  check_fields(request,{'rule_id','archived'});require(set(request)=={'rule_id','archived'} and type(request['archived']) is bool,'归档参数无效')
  def operation(state):
   rule=next((v for v in state['scoped_rules'] if v['id']==request['rule_id']),None);require(rule is not None,'规则不存在');before=deepcopy(rule);rule['archived']=request['archived'];rule['version']+=1;rule['updated_at']=utc_now();_history(state,rule['id'],'archive' if request['archived'] else 'unarchive',before,rule);return state,deepcopy(rule)
  return self.repository.atomic(project,operation)
 def delete(self,project,request):
  check_fields(request,{'rule_id'});require(set(request)=={'rule_id'},'删除参数无效')
  def operation(state):
   rule=next((v for v in state['scoped_rules'] if v['id']==request['rule_id']),None)
   if rule is not None:
    before=deepcopy(rule);state['scoped_rules']=[v for v in state['scoped_rules'] if v['id']!=request['rule_id']];_history(state,request['rule_id'],'delete',before,None)
   return state,True
  return self.repository.atomic(project,operation)

def encode_safe(value):
 from novel_writer.domain.tasks import encode
 return encode(value)
