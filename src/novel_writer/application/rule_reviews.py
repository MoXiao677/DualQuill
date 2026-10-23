"""Explicit rule-only model review on the shared registry, slot and cancellation owner."""
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
from novel_writer.domain.rule_reviews import RuleReviewTask,COLLECTIONS,PROMPT,rule_messages,source_digest,verify_output

def upgrade(state):
 from novel_writer.application.chapter_lifecycle import upgrade as prior
 prior(state);state['workspace_version']=max(state['workspace_version'],46);state.setdefault('rule_task_bindings',[]);state.setdefault('deep_review_actions',[]);state.setdefault('memory_automation_events',[])
 from novel_writer.domain.body_planning import COLLECTIONS as BODY_PLANNING_COLLECTIONS
 from novel_writer.domain.graph_extraction import COLLECTIONS as GRAPH_COLLECTIONS
 for name in (*BODY_PLANNING_COLLECTIONS,*GRAPH_COLLECTIONS):state.setdefault(name,[])
 for name in COLLECTIONS:state.setdefault(name,[])

def source(state,chapter_id,target_task_id):
 from novel_writer.application.chapter_lifecycle import is_hidden
 require(not is_hidden(state,chapter_id),'rule_reviews.hidden_chapter')
 resolved=require_no_conflicts(state,chapter_id,target_task_id,complete=True);rules=resolved['rules'];require(0<len(rules)<=1000,'rule_reviews.no_rules')
 require(len(json.dumps(rules,ensure_ascii=False))<=200000,'rule_reviews.source_too_large')
 return dict(project_id=state['document']['project']['id'],chapter_id=chapter_id,target_task_id=target_task_id,rules=rules,source_revision=state['revision'],source_sha256=source_digest(state['document']['project']['id'],chapter_id,target_task_id,rules))

def fresh(state,task):
 try:return source(state,task.chapter_id,task.target_task_id)['source_sha256']==task.source_sha256
 except (ValueError,KeyError):return False

def task_of(state,identifier):
 value=next((v for v in state.get('rule_review_tasks',[]) if v['id']==identifier),None)
 if value is None:raise KeyError('rule_reviews.task_not_in_book')
 return parse(RuleReviewTask,value)

def last_event(state,task_id):return next(v for v in reversed(state['rule_review_events']) if v['task_id']==task_id)

def emit(state,task,kind,status,attempt=None,error=None):
 previous=next((v for v in reversed(state['rule_review_events']) if v['task_id']==task.id),None)
 value=dict(id=str(uuid4()),task_id=task.id,previous_event_id=previous['id'] if previous else None,kind=kind,status=status,attempt_id=attempt if kind=='started' else previous['attempt_id'] if previous else None,error_code=error,created_at=utc_now())
 state['rule_review_events'].append(value);return value

class RuleReviewHttpAdapter(ConfiguredHttpAdapter):
 capabilities=('review_rule_conflicts',)
 def run_rules(self,task,attempt,confirmed,token):
  require(confirmed is True and bool(attempt),'rule_reviews.confirm_required');token.checkpoint()
  self.providers.assert_prepared(task.binding.connection_id,task.created_at)
  try:saved=self.saved_connection(task.binding,True)
  except (ValueError,OSError):return empty_response(error_code='connection_unavailable_or_changed')
  token.checkpoint();return self.transport.send(task.binding,saved,token,task.max_output_chars)

class RuleReviewCoordinator:
 def __init__(self,parent,providers,*,enabled=False):
  self.parent,self.service,self.repository,self.providers=parent,parent.service,parent.repository,providers
  self.adapter=RuleReviewHttpAdapter(providers,enabled=enabled);parent.registry.register('review_rule_conflicts',self.adapter)
 def preview(self,project,request):
  fields={'chapter_id','target_task_id'};check_fields(request,fields);require(set(request)==fields,'rule_reviews.preview_fields')
  return dict(source(self.service.get(project),request['chapter_id'],request['target_task_id']),model_request_sent=False,semantic_quality_verified=False)
 def prepare(self,project,request):
  fields={'request_id','chapter_id','target_task_id','source_sha256','model_options','max_output_chars','timeout_ms','budget_max_calls','budget_max_output_tokens'}
  check_fields(request,fields);require(set(request)==fields,'rule_reviews.prepare_fields');identity=uuid_value(request['request_id']);stamp=fingerprint(request)
  state=self.service.get(project);existing=next((v for v in state.get('rule_review_tasks',[]) if v['request_id']==identity),None)
  if existing:require(existing['preparation_sha256']==stamp,'rule_reviews.identity_conflict');return self.describe(project,existing['id'])
  current=source(state,request['chapter_id'],request['target_task_id']);require(current['source_sha256']==request['source_sha256'],'rule_reviews.source_changed')
  options=deepcopy(request['model_options']);require(type(options) is dict and options.get('adapter_id')=='configured-http-v2','rule_reviews.explicit_configured_model_required');options['prompt_version']=PROMPT;options=canonical_options(options);self.providers.validate_sampling(options)
  destination=ConnectionDestination(**self.adapter.freeze_destination(options));body=json.dumps(request_payload(destination.protocol,rule_messages(project,request['chapter_id'],request['target_task_id'],current['rules']),dict(options,destination=encode(destination))),ensure_ascii=False,sort_keys=True,separators=(',',':'))
  binding=self._binding(options,destination,body)
  def operation(state):
   require(not any(b['id']==identity for b in state.get('rule_task_bindings',[])),'rule_reviews.separate_request_identity_required')
   previous=next((v for v in state.get('rule_review_tasks',[]) if v['request_id']==identity),None)
   if previous:require(previous['preparation_sha256']==stamp,'rule_reviews.identity_conflict');return None,previous['id']
   current=source(state,request['chapter_id'],request['target_task_id']);require(current['source_sha256']==request['source_sha256'],'rule_reviews.source_changed');upgrade(state)
   task=RuleReviewTask(id=str(uuid5(NAMESPACE_URL,identity+'/rule-review')),request_id=identity,preparation_sha256=stamp,project_id=project,chapter_id=request['chapter_id'],target_task_id=request['target_task_id'],rules=tuple(current['rules']),wire_source={k:current[k] for k in ('project_id','chapter_id','target_task_id','rules')},copy_mappings=(),source_sha256=current['source_sha256'],source_revision=current['source_revision'],binding=binding,owner_id=self.parent.owner_id,max_output_chars=request['max_output_chars'],timeout_ms=request['timeout_ms'],budget_max_calls=request['budget_max_calls'],budget_max_output_tokens=request['budget_max_output_tokens'],created_at=utc_now())
   state['rule_review_tasks'].append(encode(task));emit(state,task,'prepared','pending');return state,task.id
  identifier=self.repository.atomic(project,operation,identity_claim=('rule_review_tasks','request_id',identity));return self.describe(project,identifier)
 def _binding(self,options,destination,body):
  from novel_writer.domain.sampling import kwargs
  return ConfiguredModelBinding(**{k:v for k,v in options.items() if k!='sampling'},**kwargs(options),destination=destination,request_body=body,request_sha256=request_digest(body,destination))
 def describe(self,project,identifier=None):
  state=self.service.get(project)
  if identifier is None:return dict(revision=state['revision'],enabled=self.adapter.enabled and not self.providers.offline,tasks=[self._describe(state,task_of(state,v['id'])) for v in state.get('rule_review_tasks',[])])
  return self._describe(state,task_of(state,identifier))
 def _describe(self,state,task):
  last=last_event(state,task.id);status=last['status'];current=fresh(state,task);results=[deepcopy(r) for r in state['rule_review_results'] if r['task_id']==task.id]
  with self.parent.lock:live=task.id in self.parent.active
  display='interrupted' if (status in ('pending','running') and task.owner_id!=self.parent.owner_id) or (status=='running' and not live) else status
  result=dict(task=encode(task),status=status,display_status=display,events=[v for v in state['rule_review_events'] if v['task_id']==task.id],results=results,source_fresh=current,can_inspect=current and status=='succeeded',revision=state['revision'],semantic_quality_verified=False,automatic_rule_changes=False,formal_modification_permission=False)
  result.update(self.parent.stream_preview(task.id,display=='running'));return result
 def start(self,project,identifier,confirmation):
  task=task_of(self.service.get(project),identifier);self.adapter.validate_start(task.binding,confirmation);self.providers.assert_prepared(task.binding.connection_id,task.created_at)
  require(task.owner_id==self.parent.owner_id and not self.parent.closed.is_set(),'rule_reviews.fresh_preparation_required');require(self.parent.slot.acquire(blocking=False),'rule_reviews.busy')
  try:
   def operation(state):
    current=task_of(state,identifier);require(last_event(state,identifier)['status']=='pending','rule_reviews.already_run');require(fresh(state,current),'rule_reviews.source_changed')
    started={v['task_id'] for v in state['rule_review_events'] if v['kind']=='started'};spent=[v for v in state['rule_review_tasks'] if v['id'] in started]
    require(len(spent)<current.budget_max_calls and sum(v['binding']['max_tokens'] for v in spent)+current.binding.max_tokens<=current.budget_max_output_tokens,'rule_reviews.budget_exceeded')
    return state,emit(state,current,'started','running',str(uuid4()))['attempt_id']
   attempt=self.repository.atomic(project,operation);token=self.parent.stream_token(time.monotonic()+task.timeout_ms/1000);worker=threading.Thread(target=self._worker,args=(task,attempt,token),daemon=True)
   with self.parent.lock:self.parent.active[task.id]=(worker,token)
   worker.start();return self.describe(project,identifier)
  except BaseException:self.parent.slot.release();raise
 def _worker(self,task,attempt,token):
  response=None;error=None;output=None
  try:
   state=self.service.get(task.project_id);require(last_event(state,task.id)['status']=='running' and fresh(state,task),'rule_reviews.source_changed_before_send')
   response=self.parent.registry.execute_rules(task,attempt,True,token);token.checkpoint()
   if response.complete:
    try:output=verify_output(response.output_text,task.rules)
    except (ValueError,TypeError,KeyError,RecursionError):error='invalid_rule_opinion_or_evidence'
   else:error=response.error_code or 'incomplete_response'
  except TaskCancelled:error='interrupted' if self.parent.closed.is_set() else 'cancelled'
  except TaskTimeout:error='timeout'
  except Exception:error='rule_review_failed'
  try:
   def complete(state):
    last=last_event(state,task.id)
    if response is not None:state['rule_review_results'].append(dict(id=str(uuid5(NAMESPACE_URL,attempt+'/response')),project_id=task.project_id,task_id=task.id,attempt_id=attempt,response=encode(response),output=output if last['status']=='running' and error is None else None,created_at=utc_now()))
    if last['status']!='running':return (state if response is not None else None),True
    code=error or (None if output is not None else 'no_verified_opinion')
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
   for raw in state.get('rule_review_tasks',[]):
    task=task_of(state,raw['id']);last=last_event(state,task.id)
    with self.parent.lock:live=task.id in self.parent.active
    if last['status']=='running' and not live:emit(state,task,'interrupted','interrupted',error='explicit_recovery');changed.append(task.id)
   return (state if changed else None),dict(interrupted=changed)
  return self.repository.atomic(project,operation)
 def inspect(self,project,identifier,request):
  fields={'result_id','request_sha256','expected_revision'};check_fields(request,fields);require(set(request)==fields,'rule_reviews.inspect_fields');state=self.service.get(project);task=task_of(state,identifier)
  require(type(request['expected_revision']) is int and request['expected_revision']==state['revision'] and request['request_sha256']==task.binding.request_sha256,'rule_reviews.inspect_binding_changed')
  require(fresh(state,task) and last_event(state,identifier)['status']=='succeeded','rule_reviews.stale_or_failed_opinion');result=next((r for r in state['rule_review_results'] if r['id']==request['result_id'] and r['task_id']==identifier and r['output'] is not None),None);require(result is not None,'rule_reviews.result_not_in_task')
  return dict(result=deepcopy(result),status='needs_verification',semantic_quality_verified=False,formal_modification_permission=False,automatic_rule_changes=False)
