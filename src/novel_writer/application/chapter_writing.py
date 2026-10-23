"""Initial draft and append-only continuation on TaskCoordinator; no new scheduler."""
from copy import deepcopy
from uuid import uuid4,uuid5,NAMESPACE_URL
from novel_writer.domain.model_contract import WritingSpec,ModelWritingParameters
from novel_writer.domain.chapter_writing import CAPABILITIES,Correction,Decision,LateResult,COLLECTIONS,candidate_text,compose
from novel_writer.domain.tasks import require,parse,encode,digest,uuid_value,capture_dependency,dependency_equal
from novel_writer.domain.memory import fingerprint
from novel_writer.domain.models import utc_now
from novel_writer.application.fields import check_fields
from novel_writer.application.tasks import context_options,get_task
from novel_writer.application.context_preview import preview

def selected_preset(state):
 choice=state.get('creation_preset_choices',[]);return next((v for v in state.get('creation_presets',[]) if choice and v['id']==choice[-1]['version_id']),None)
def locks(state):return tuple(v['id'] for name in ('book_creation_locks','planning_locks') for v in state.get(name,[]))
def options(raw):
 fields={'chapter_id','mode','context_options','instruction','target_chars','required_literals','forbidden_literals'};check_fields(raw,fields);require(set(raw)==fields and raw['mode'] in ('draft','continue'),'请选择写初稿或续写');require(type(raw['instruction']) is str and len(raw['instruction'])<=3000 and type(raw['target_chars']) is int and 100<=raw['target_chars']<=20000,'正文要求或目标字数非法')
 for name in ('required_literals','forbidden_literals'):require(type(raw[name]) is list and len(raw[name])<=32 and all(type(v) is str and 0<len(v)<=200 and v.strip() for v in raw[name]),'必写/禁写条目非法')
 require(not set(raw['required_literals'])&set(raw['forbidden_literals']),'必写与禁写条目冲突');return deepcopy(raw)
def semantic_source(state,chapter,report,ctx,spec):
 sources=[]
 for row in report['sources']:
  if not row['included']:continue
  kind=row['kind'];identifier=row['entity_id'];values=[]
  if kind=='chapter_plan':
   plan=next((v for v in state['document']['chapter_outlines'] if v['id']==identifier),None)
   if plan:values.append(capture_dependency(state,'chapter_outline',identifier).source_sha256)
   values.append(capture_dependency(state,'idea',chapter['id']).source_sha256)
  elif kind=='search_result':values.append(row['source']['source_sha256'])
  else:values.append(capture_dependency(state,'chapter' if kind=='chapter_body' else kind,identifier).source_sha256)
  sources.append(dict(kind=kind,values=values,included_chars=row['included_chars'],original_chars=row['original_chars'],truncated=row['truncated']))
 own={k:v for k,v in spec.items() if k not in ('preset_version_id','style_version_id','lock_ids')}
 return fingerprint(dict(target=chapter,selected_sources=sources,context_options=encode(ctx),style=report.get('style_snapshot'),writing=own))
def build_source(state,raw,*,selection_revision=None):
 raw=options(raw);chapter=next((v for v in state['document']['chapters'] if v['id']==raw['chapter_id']),None);require(chapter is not None,'写作章节不存在')
 from novel_writer.application.chapter_lifecycle import is_archived
 require(not is_archived(state,chapter['id']),'chapter_lifecycle.archived_target')
 require((chapter['content']=='') if raw['mode']=='draft' else bool(chapter['content'].strip()),'初稿仅用于空正文；已有正文请选择续写或已有改写入口')
 defaults=dict(chapter_id=chapter['id'],include_current_plan=True,include_characters=True,include_worldbuilding=True,include_writing_rules=True,include_memories=True)
 supplied=raw['context_options'];require(type(supplied) is dict and supplied.get('chapter_id')==chapter['id'],'正文上下文章不符');ctx=context_options({**defaults,**supplied});require(ctx.include_current_plan and ctx.include_writing_rules,'初稿/续写必须明确包含已保存IDEA/章纲与写作规则')
 report=preview(state if selection_revision is None else dict(state,revision=selection_revision),encode(ctx));require(not any(v['truncated'] for v in report['sources'] if v['kind'] in ('chapter_plan','writing_rules','character','worldbuilding','memory')),'必要写作资料超过上下文预算，请增加预算或缩小明确选择')
 from novel_writer.application.scoped_rules import require_no_conflicts
 rules=require_no_conflicts(state,chapter['id'],ctx.rule_task_id)
 required_literals=list(dict.fromkeys(list(raw['required_literals'])+[v['text'] for v in rules['rules'] if v['kind']=='required']))
 forbidden_literals=list(dict.fromkeys(list(raw['forbidden_literals'])+[v['text'] for v in rules['rules'] if v['kind']=='forbidden']))
 preset=selected_preset(state);language=preset['settings']['manuscript_language'] if preset else state['document']['project'].get('language','zh-CN');prompt=preset['settings']['style_prompt'] if preset else '';style=report.get('style_snapshot');spec=dict(mode=raw['mode'],target_chars=raw['target_chars'],required_literals=required_literals,forbidden_literals=forbidden_literals,base_instruction=raw['instruction'],manuscript_language=language,preset_prompt=prompt,preset_version_id=preset['id'] if preset else None,style_version_id=style['id'] if style else None,lock_ids=list(locks(state)))
 signature=fingerprint(dict(target=chapter,context_sha256=digest(report['context_text']),context_options=encode(ctx),spec=spec));return dict(source_options=raw,context_options=encode(ctx),context=report,target=deepcopy(chapter),writing=spec,source_sha256=signature,semantic_sha256=semantic_source(state,chapter,report,ctx,spec),draft_profile=next((v for v in preset['settings']['steps'] if v['step']=='draft'),None) if preset else None,model_request_sent=False)
def metrics(task,text):
 spec=task.frozen.parameters.writing;count=len(text);return dict(actual_new_chars=count,target_chars=spec.target_chars,deviation=count-spec.target_chars,unicode_unit='Unicode code points',retained_prefix_chars=len(task.frozen.target.text) if spec.mode=='continue' else 0,missing_required=[v for v in spec.required_literals if v not in text],forbidden_found=[v for v in spec.forbidden_literals if v in text],semantic_quality_verified=False)

class ChapterWriting:
 def __init__(self,parent,providers):self.parent,self.providers,self.service,self.repository=parent,providers,parent.service,parent.repository;self.reviews={};parent.writing=self
 def preview(self,project,raw):return build_source(self.service.get(project),raw)
 def prepare(self,project,request):
  fields={'request_id','source_options','source_sha256','model_options','max_output_chars','timeout_ms','retry_of'};check_fields(request,fields);require(set(request)==fields,'正文任务参数缺失');uuid_value(request['request_id']);state=self.service.get(project);old=next((v for v in state.get('generation_tasks',[]) if v['request_id']==request['request_id']),None)
  if old:require(old['frozen']['parameters'].get('writing',{}).get('preparation_sha256')==fingerprint(request),'同一正文准备身份绑定不同输入');return dict(task=old,revision=state['revision'])
  source=build_source(state,request['source_options']);require(source['source_sha256']==request['source_sha256'],'IDEA、章纲、正文、文风、锁或来源已变化，请重新预览');profile=request['model_options']
  if profile is None:
   step=source['draft_profile'];require(step and step['connection_id'],'请配置正文用途预设，或明确选择模型');profile={k:v for k,v in step.items() if k!='step'};profile['prompt_version']='rewrite-1'
  profile=deepcopy(profile);profile['prompt_version']='chapter-draft-1' if source['writing']['mode']=='draft' else 'chapter-continue-1'
  if request['retry_of'] is not None:
   previous=get_task(state,request['retry_of']);require(previous.task_type in CAPABILITIES and previous.chapter_id==source['target']['id'],'重试来源不属于当前章正文任务')
  spec=dict(source['writing']);spec.update(source_sha256=source['source_sha256'],semantic_sha256=source['semantic_sha256'],configuration_stamp=self.providers.configuration_stamp(),prepared_owner=self.parent.owner_id,retry_of=request['retry_of'],preparation_sha256=fingerprint(request));instruction=source['writing']['base_instruction'];require(len(instruction)<=4000,'正文要求超限')
  return self.parent.prepare(project,dict(request_id=request['request_id'],chapter_id=source['target']['id'],task_type='draft_chapter' if spec['mode']=='draft' else 'continue_chapter',context_options=source['context_options'],context_sha256=digest(source['context']['context_text']),parameters=dict(instruction=instruction,max_output_chars=request['max_output_chars'],timeout_ms=request['timeout_ms'],writing=spec),expected_revision=state['revision'],model_options=profile))
 def assert_spec(self,state,spec,context):
  clean_context=encode(context);clean_context.pop('retrieval_owner',None)
  selection_revision=context.search_selections[0].workspace_revision if context.search_selections and (context.include_memory_rollups or any(s.excerpt is not None or s.kind=='material' for s in context.search_selections)) else None
  current=build_source(state,dict(chapter_id=context.chapter_id,mode=spec.mode,context_options=clean_context,instruction=spec.base_instruction,target_chars=spec.target_chars,required_literals=list(spec.required_literals),forbidden_literals=list(spec.forbidden_literals)),selection_revision=selection_revision);require(current['semantic_sha256']==spec.semantic_sha256 and locks(state)==spec.lock_ids and current['writing']['style_version_id']==spec.style_version_id and current['writing']['preset_version_id']==spec.preset_version_id,'真正写作来源、文风或锁已变化，请重新准备');require(self.providers.configuration_stamp()==spec.configuration_stamp,'模型配置已变化，旧请求或候选不能沿用')
 def assert_fresh(self,state,task,*,execute=False):
  require(task.task_type in CAPABILITIES and isinstance(task.frozen.parameters,ModelWritingParameters),'不是初稿/续写任务');spec=task.frozen.parameters.writing;self.assert_spec(state,spec,task.frozen.context_options)
  for dep in task.frozen.dependencies:
   skill=self.service._skills([dep.entity_id])[0] if dep.kind=='skill' else None;actual=capture_dependency(state,dep.kind,dep.entity_id,use=dep.use,skill=skill,file_path=dep.file_path);require(dependency_equal(dep,actual) and dep.memory_fresh is not False,'具体IDEA、章纲、正文版本或依赖已变化')
  if execute:require(spec.prepared_owner==self.parent.owner_id,'旧会话/恢复任务许可不继承，请明确准备新任务')
 def correct(self,project,task_id,request):
  require(set(request)=={'operation_id','candidate_id','text'},'正文修正字段非法');identity=uuid_value(request['operation_id']);require(type(request['text']) is str and bool(request['text'].strip()),'候选修正不能为空')
  def operation(state):
   task=get_task(state,task_id);require(task.task_type in CAPABILITIES and task.status=='succeeded' and task.candidate_id==request['candidate_id'],'修正须绑定完成的当前正文候选');require(len(request['text'])<=task.frozen.parameters.max_output_chars,'候选修正超过明确字符上限');old=next((v for v in state['writing_corrections'] if v['operation_id']==identity),None)
   if old:require((old['task_id'],old['candidate_id'],old['text'])==(task_id,request['candidate_id'],request['text']),'修正身份重复绑定不同内容');return None,old
   previous=next((v for v in reversed(state['writing_corrections']) if v['task_id']==task_id),None);value=Correction(id=str(uuid4()),operation_id=identity,project_id=project,chapter_id=task.chapter_id,task_id=task_id,candidate_id=task.candidate_id,previous_id=previous['id'] if previous else None,text=request['text'],created_at=utc_now());state['writing_corrections'].append(encode(value));return state,encode(value)
  return self.repository.atomic(project,operation,identity_claim=('writing_corrections','operation_id',identity))
 def review(self,project,task_id,request):
  require(set(request)=={'candidate_id','correction_id'},'正文复核字段非法');state=self.service.get(project);task=get_task(state,task_id);self.assert_fresh(state,task);require(task.status=='succeeded' and task.candidate_id==request['candidate_id'],'只能复核完成的当前候选');text=candidate_text(state,task,request['correction_id']);identifier=str(uuid4());self.reviews[identifier]=(project,task_id,task.candidate_id,request['correction_id'],digest(compose(task,text)));return dict(review_id=identifier,revision=state['revision'],before=task.frozen.target.text,after=compose(task,text),new_text=text,metrics=metrics(task,text),candidate_id=task.candidate_id,correction_id=request['correction_id'])
 def adoption_text(self,state,task,request):
  self.assert_fresh(state,task);require(request['confirmed_review'] is True,'请明确确认本次正文差异');record=self.reviews.get(request['review_id']);text=compose(task,candidate_text(state,task,request['correction_id']));require(record==(task.project_id,task.id,task.candidate_id,request['correction_id'],digest(text)),'请在本次会话重新复核当前候选差异');return text
 def record_decision(self,state,task,request,text):
  value=Decision(id=str(uuid5(NAMESPACE_URL,request['adoption_id']+'/writing-decision')),project_id=task.project_id,task_id=task.id,candidate_id=task.candidate_id,correction_id=request['correction_id'],receipt_id=request['adoption_id'],review_id=request['review_id'],request_sha256=fingerprint(request),applied_text_sha256=digest(text),created_at=utc_now());state['writing_decisions'].append(encode(value))
 def replay(self,state,receipt,request):
  decision=next((v for v in state.get('writing_decisions',[]) if v['receipt_id']==receipt['id']),None);require(decision is not None and decision['request_sha256']==fingerprint(request),'同一正文采纳身份绑定不同确认或修正')
 def describe(self,state,task):
  edits=[v for v in state.get('writing_corrections',[]) if v['task_id']==task.id];text=candidate_text(state,task,edits[-1]['id'] if edits else None) if task.candidate_id else '';fresh=True
  try:self.assert_fresh(state,task)
  except ValueError:fresh=False
  return dict(late_results=[v for v in state.get('writing_late_results',[]) if v['task_id']==task.id],corrections=edits,new_text=text,after=compose(task,text) if task.candidate_id else None,metrics=metrics(task,text) if task.candidate_id else None,source_fresh=fresh,requires_new_preparation=task.frozen.parameters.writing.prepared_owner!=self.parent.owner_id)
 def append_late(self,state,task,response):
  if task.status not in ('failed','cancelled','interrupted') or any(v['task_id']==task.id for v in state['writing_late_results']):return False
  value=LateResult(id=str(uuid4()),project_id=task.project_id,task_id=task.id,attempt_id=task.attempt_id,terminal_status=task.status,response=response,created_at=utc_now());state['writing_late_results'].append(encode(value));return True
 def capture_late(self,project,original,response):
  def operation(state):
   task=get_task(state,original.id);changed=task.attempt_id==original.attempt_id and self.append_late(state,task,response);return (state if changed else None),None
  self.repository.atomic(project,operation)
