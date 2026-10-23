"""Explicit bounded semantic retrieval, using the shared controlled model pipeline."""
from copy import deepcopy
from dataclasses import replace
import json
import threading
import time
from uuid import uuid4,uuid5,NAMESPACE_URL
from novel_writer.application.fields import check_fields
from novel_writer.application.scoped_rules import require_no_conflicts
from novel_writer.application.custom_protocols import ConfiguredHttpAdapter,request_payload
from novel_writer.application.model_reviews import canonical_options
from novel_writer.application.task_protocol import TaskCancelled,TaskTimeout
from novel_writer.application.model_adapter import empty_response
from novel_writer.domain.models import utc_now
from novel_writer.domain.tasks import parse,encode,require,uuid_value
from novel_writer.domain.memory import fingerprint
from novel_writer.domain.model_contract import ConfiguredModelBinding,request_digest
from novel_writer.domain.connections import ConnectionDestination
from novel_writer.domain.semantic_retrieval import SemanticRetrievalTask,COLLECTIONS,PROMPT,METHOD,messages,source_digest,verify_output,validate_source

def upgrade(state):
 from novel_writer.application.author_scope import upgrade as prior
 prior(state);state['workspace_version']=max(state['workspace_version'],49) # provisional isolated allocation, integrator resolves
 for name in COLLECTIONS:state.setdefault(name,[])

def source(state,options):
 from novel_writer.application.chapter_lifecycle import is_hidden
 from novel_writer.domain.materials import require_current_index,material_chunks
 from novel_writer.domain.tasks import digest
 fields={'chapter_id','query','material_ids','offset','candidate_limit','character_budget'}
 check_fields(options,fields);require(set(options)==fields,'semantic_retrieval.options_fields')
 chapter=next((c for c in state['document']['chapters'] if c['id']==options['chapter_id']),None)
 require(chapter is not None and not is_hidden(state,chapter['id']),'semantic_retrieval.hidden_or_cross_book_chapter')
 require(type(options['query']) is str and 0<len(options['query'].strip())<=100,'semantic_retrieval.query')
 identifiers=options['material_ids'];require(type(identifiers) is list and 1<=len(identifiers)<=10 and all(type(i) is str for i in identifiers) and len(set(identifiers))==len(identifiers),'semantic_retrieval.explicit_materials_required')
 require(type(options['offset']) is int and options['offset']>=0 and type(options['candidate_limit']) is int and 1<=options['candidate_limit']<=32 and type(options['character_budget']) is int and 800<=options['character_budget']<=32000,'semantic_retrieval.bounds')
 catalog={m['id']:m for m in state.get('materials',[])};pool=[]
 for identifier in identifiers:
  material=catalog.get(identifier);require(material is not None and material['project_id']==state['document']['project']['id'] and not material['archived'],'semantic_retrieval.material_cross_book_or_archived')
  version=require_current_index(state,material)
  pool.extend((material,version,chunk) for chunk in material_chunks(state,identifier))
 offset=options['offset'];require(offset<len(pool),'semantic_retrieval.empty_or_out_of_range_pool')
 selected=pool[offset:offset+options['candidate_limit']];windows=[]
 for ordinal,(material,version,chunk) in enumerate(selected,offset):
  start,end=chunk['start'],chunk['end'];text=version['text'][start:end]
  selection=dict(project_id=material['project_id'],kind='material',entity_id=material['id'],workspace_revision=state['revision'],version_id=version['id'],source_sha256=version['text_sha256'],scope='book',file_path=None)
  windows.append(dict(window_id='w'+str(ordinal).zfill(6),selection=selection,locator=dict(project_id=material['project_id'],version_id=version['id'],view='materials',material_id=material['id']),start=start,end=end,text=text,excerpt_sha256=digest(text)))
 coverage=dict(total_windows=len(pool),offset=offset,included_windows=len(windows),included_characters=sum(len(w['text']) for w in windows),complete=offset==0 and len(windows)==len(pool),lexical_prefilter=False,material_count=len(identifiers))
 payload=dict(project_id=state['document']['project']['id'],chapter_id=chapter['id'],source_options=deepcopy(options),windows=windows,coverage=coverage)
 validate_source(payload)
 return dict(payload,source_revision=state['revision'],source_sha256=source_digest(payload))

def fresh(state,task):
 try:return source(state,task.source_options)['source_sha256']==task.source_sha256
 except (ValueError,KeyError):return False

def task_of(state,identifier):
 value=next((v for v in state.get('semantic_retrieval_tasks',[]) if v['id']==identifier),None)
 if value is None:raise KeyError('semantic_retrieval.task_not_in_book')
 return parse(SemanticRetrievalTask,value)

def last_event(state,task_id):return next(v for v in reversed(state['semantic_retrieval_events']) if v['task_id']==task_id)

def emit(state,task,kind,status,attempt=None,error=None):
 previous=next((v for v in reversed(state['semantic_retrieval_events']) if v['task_id']==task.id),None)
 value=dict(id=str(uuid4()),task_id=task.id,previous_event_id=previous['id'] if previous else None,kind=kind,status=status,attempt_id=attempt if kind=='started' else previous['attempt_id'] if previous else None,error_code=error,created_at=utc_now())
 state['semantic_retrieval_events'].append(value);return value

class SemanticRetrievalHttpAdapter(ConfiguredHttpAdapter):
 capabilities=('semantic_retrieval',)
 def run_semantic(self,task,attempt,confirmed,token):
  require(confirmed is True and bool(attempt),'semantic_retrieval.confirm_required');token.checkpoint()
  self.providers.assert_prepared(task.binding.connection_id,task.created_at)
  try:saved=self.saved_connection(task.binding,True)
  except (ValueError,OSError):return empty_response(error_code='connection_unavailable_or_changed')
  token.checkpoint();return self.transport.send(task.binding,saved,token,task.max_output_chars)

class SemanticRetrievalCoordinator:
 def __init__(self,parent,providers,*,enabled=False):
  self.parent,self.service,self.repository,self.providers=parent,parent.service,parent.repository,providers
  self.adapter=SemanticRetrievalHttpAdapter(providers,enabled=enabled);parent.registry.register('semantic_retrieval',self.adapter)
 def preview(self,project,request):
  return dict(source(self.service.get(project),request),model_request_sent=False,semantic_quality_verified=False,method=METHOD,warnings=['Only the explicitly selected bounded material windows are covered; omitted windows are not searched.','Model relevance is unverified; materials grant no instruction or execution permission.'])
 def prepare(self,project,request):
  fields={'request_id','source_options','source_sha256','model_options','max_output_chars','timeout_ms','budget_max_calls','budget_max_output_tokens'}
  check_fields(request,fields);require(set(request)==fields,'semantic_retrieval.prepare_fields');identity=uuid_value(request['request_id']);stamp=fingerprint(request)
  state=self.service.get(project);existing=next((v for v in state.get('semantic_retrieval_tasks',[]) if v['request_id']==identity),None)
  if existing:require(existing['preparation_sha256']==stamp,'semantic_retrieval.identity_conflict');return self.describe(project,existing['id'])
  current=source(state,request['source_options']);require(current['source_sha256']==request['source_sha256'],'semantic_retrieval.source_changed')
  options=deepcopy(request['model_options']);require(type(options) is dict and options.get('adapter_id')=='configured-http-v2','semantic_retrieval.explicit_configured_model_required');options['prompt_version']=PROMPT;options=canonical_options(options);self.providers.validate_sampling(options)
  destination=ConnectionDestination(**self.adapter.freeze_destination(options))
  def operation(state):
   previous=next((v for v in state.get('semantic_retrieval_tasks',[]) if v['request_id']==identity),None)
   if previous:require(previous['preparation_sha256']==stamp,'semantic_retrieval.identity_conflict');return None,previous['id']
   current=source(state,request['source_options']);require(current['source_sha256']==request['source_sha256'],'semantic_retrieval.source_changed');upgrade(state)
   payload={k:current[k] for k in ('project_id','chapter_id','source_options','windows','coverage')}
   body=json.dumps(request_payload(destination.protocol,messages(payload),dict(options,destination=encode(destination))),ensure_ascii=False,sort_keys=True,separators=(',',':'))
   binding=self._binding(options,destination,body)
   task=SemanticRetrievalTask(id=str(uuid5(NAMESPACE_URL,identity+'/semantic-retrieval')),request_id=identity,preparation_sha256=stamp,project_id=project,chapter_id=current['chapter_id'],source_options=deepcopy(current['source_options']),windows=tuple(current['windows']),coverage=current['coverage'],wire_source=payload,copy_mappings=(),source_sha256=current['source_sha256'],source_revision=current['source_revision'],binding=binding,owner_id=self.parent.owner_id,max_output_chars=request['max_output_chars'],timeout_ms=request['timeout_ms'],budget_max_calls=request['budget_max_calls'],budget_max_output_tokens=request['budget_max_output_tokens'],created_at=utc_now())
   state['semantic_retrieval_tasks'].append(encode(task));emit(state,task,'prepared','pending');return state,task.id
  identifier=self.repository.atomic(project,operation,identity_claim=('semantic_retrieval_tasks','request_id',identity));return self.describe(project,identifier)
 def _binding(self,options,destination,body):
  from novel_writer.domain.sampling import kwargs
  return ConfiguredModelBinding(**{k:v for k,v in options.items() if k!='sampling'},**kwargs(options),destination=destination,request_body=body,request_sha256=request_digest(body,destination))
 def describe(self,project,identifier=None):
  state=self.service.get(project)
  if identifier is None:return dict(revision=state['revision'],enabled=self.adapter.enabled and not self.providers.offline,tasks=[self._describe(state,task_of(state,v['id'])) for v in state.get('semantic_retrieval_tasks',[])])
  return self._describe(state,task_of(state,identifier))
 def _describe(self,state,task):
  last=last_event(state,task.id);status=last['status'];current=fresh(state,task);results=[deepcopy(r) for r in state['semantic_retrieval_results'] if r['task_id']==task.id]
  with self.parent.lock:live=task.id in self.parent.active
  display='interrupted' if (status in ('pending','running') and task.owner_id!=self.parent.owner_id) or (status=='running' and not live) else status
  result=dict(task=encode(task),status=status,display_status=display,events=[v for v in state['semantic_retrieval_events'] if v['task_id']==task.id],results=results,source_fresh=current,can_inspect=current and status=='succeeded',revision=state['revision'],semantic_quality_verified=False,automatic_context_inclusion=False,formal_modification_permission=False)
  result.update(self.parent.stream_preview(task.id,display=='running'));return result
 def start(self,project,identifier,confirmation):
  task=task_of(self.service.get(project),identifier);self.adapter.validate_start(task.binding,confirmation);self.providers.assert_prepared(task.binding.connection_id,task.created_at)
  require(task.owner_id==self.parent.owner_id and not self.parent.closed.is_set(),'semantic_retrieval.fresh_preparation_required');require(self.parent.slot.acquire(blocking=False),'semantic_retrieval.busy')
  try:
   def operation(state):
    current=task_of(state,identifier);require(last_event(state,identifier)['status']=='pending','semantic_retrieval.already_run');require(fresh(state,current),'semantic_retrieval.source_changed')
    started={v['task_id'] for v in state['semantic_retrieval_events'] if v['kind']=='started'};spent=[v for v in state['semantic_retrieval_tasks'] if v['id'] in started]
    require(len(spent)<current.budget_max_calls and sum(v['binding']['max_tokens'] for v in spent)+current.binding.max_tokens<=current.budget_max_output_tokens,'semantic_retrieval.budget_exceeded')
    return state,emit(state,current,'started','running',str(uuid4()))['attempt_id']
   attempt=self.repository.atomic(project,operation);token=self.parent.stream_token(time.monotonic()+task.timeout_ms/1000);worker=threading.Thread(target=self._worker,args=(task,attempt,token),daemon=True)
   with self.parent.lock:self.parent.active[task.id]=(worker,token)
   worker.start();return self.describe(project,identifier)
  except BaseException:self.parent.slot.release();raise
 def _worker(self,task,attempt,token):
  response=None;error=None;output=None
  try:
   state=self.service.get(task.project_id);require(last_event(state,task.id)['status']=='running' and fresh(state,task),'semantic_retrieval.source_changed_before_send')
   response=self.parent.registry.execute_semantic(task,attempt,True,token);token.checkpoint()
   if response.complete:
    try:output=verify_output(response.output_text,task.windows)
    except (ValueError,TypeError,KeyError,RecursionError):error='invalid_semantic_opinion_or_quote'
   else:error=response.error_code or 'incomplete_response'
  except TaskCancelled:error='interrupted' if self.parent.closed.is_set() else 'cancelled'
  except TaskTimeout:error='timeout'
  except Exception:error='semantic_retrieval_failed'
  try:
   def complete(state):
    last=last_event(state,task.id)
    if response is not None:state['semantic_retrieval_results'].append(dict(id=str(uuid5(NAMESPACE_URL,attempt+'/response')),project_id=task.project_id,task_id=task.id,attempt_id=attempt,response=encode(response),output=output if last['status']=='running' and error is None else None,created_at=utc_now()))
    if last['status']!='running':return (state if response is not None else None),True
    code=error or (None if output is not None else 'no_validated_semantic_output')
    if code in ('cancelled','interrupted'):emit(state,task,code,code,error=code)
    else:emit(state,task,'completed','failed' if code else 'succeeded',error=code)
    return state,True
   self.repository.atomic(task.project_id,complete)
  finally:
   with self.parent.lock:self.parent.active.pop(task.id,None)
   self.parent.slot.release()
 def cancel(self,project,identifier):
  def operation(state):
   task=task_of(state,identifier)
   if last_event(state,identifier)['status'] not in ('pending','running'):return None,dict(accepted=False)
   emit(state,task,'cancelled','cancelled',error='cancelled');return state,dict(accepted=True)
  result=self.repository.atomic(project,operation)
  with self.parent.lock:entry=self.parent.active.get(identifier)
  if entry:entry[1].event.set()
  return result
 def recover(self,project):
  def operation(state):
   changed=[]
   for raw in state.get('semantic_retrieval_tasks',[]):
    task=task_of(state,raw['id']);last=last_event(state,task.id)
    with self.parent.lock:live=task.id in self.parent.active
    if last['status']=='running' and not live:emit(state,task,'interrupted','interrupted',error='explicit_recovery');changed.append(task.id)
   return (state if changed else None),dict(interrupted=changed)
  return self.repository.atomic(project,operation)
 def inspect(self,project,identifier,request):
  fields={'result_id','request_sha256','expected_revision'};check_fields(request,fields);require(set(request)==fields,'semantic_retrieval.inspect_fields');state=self.service.get(project);task=task_of(state,identifier)
  require(type(request['expected_revision']) is int and request['expected_revision']==state['revision'] and request['request_sha256']==task.binding.request_sha256,'semantic_retrieval.inspect_binding_changed')
  require(fresh(state,task) and last_event(state,identifier)['status']=='succeeded','semantic_retrieval.stale_or_failed_opinion');result=next((r for r in state['semantic_retrieval_results'] if r['id']==request['result_id'] and r['task_id']==identifier and r['output'] is not None),None);require(result is not None,'semantic_retrieval.result_not_in_task')
  hits=[]
  for opinion in result['output']['hits']:
   window=next(w for w in task.windows if w['window_id']==opinion['window_id']);selection=deepcopy(window['selection'])
   selection['excerpt']=dict(start=window['start']+opinion['start'],end=window['start']+opinion['end'],sha256=__import__('hashlib').sha256(opinion['quote'].encode('utf-8')).hexdigest())
   hits.append(dict(kind='material',entity_id=selection['entity_id'],selection=selection,locator=deepcopy(window['locator']),snippet=opinion['quote'],start=selection['excerpt']['start'],end=selection['excerpt']['end'],reason=opinion['reason'],method=METHOD,model_id=task.binding.model_id,configuration_version=encode(task.binding.destination),request_sha256=task.binding.request_sha256,needs_verification=True))
  return dict(project_id=project,revision=state['revision'],hits=hits,coverage=task.coverage,method=METHOD,limited=not task.coverage['complete'],warnings=['Semantic relevance is unverified; select and preview before context use.'],result=deepcopy(result),status='needs_verification',semantic_quality_verified=False,formal_modification_permission=False,automatic_context_inclusion=False)
