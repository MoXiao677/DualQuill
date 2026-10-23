"""Short trials share task scheduling and arena scores; never call chapter adoption."""
from copy import deepcopy
from novel_writer.domain.sampling import kwargs as sampling_kwargs
from uuid import uuid4
import json,secrets,threading,time
from novel_writer.domain.style_trials import *
from novel_writer.domain.models import utc_now
from novel_writer.domain.memory import capture_source
from novel_writer.domain.tasks import parse,encode
from novel_writer.domain.book_ai import BookDestination
from novel_writer.application.styles import binary,sha,uid,fields,WireInput
from novel_writer.application.book_creation import get_version
from novel_writer.application.model_reviews import canonical_options
from novel_writer.application.custom_protocols import ConfiguredHttpTransport
from novel_writer.application.task_protocol import CancellationToken,TaskCancelled,TaskTimeout
from novel_writer.application.model_adapter import empty_response
from novel_writer.storage.json_codec import strict_json_loads

def upgrade(state):
 from novel_writer.application.public_search import upgrade as previous
 previous(state);state['workspace_version']=max(state['workspace_version'],15)
 for name in COLLECTIONS:state.setdefault(name,[])
def find(state,collection,identifier):
 value=next((v for v in state.get(collection,[]) if v['id']==identifier),None);require(value is not None,'trial.missing_record');return value
def lock_ids(state):return tuple(v['id'] for name in ('book_creation_locks','planning_locks') for v in state.get(name,[]))
def selected_preset(state):
 choices=state.get('creation_preset_choices',[]);return next((v for v in state.get('creation_presets',[]) if choices and v['id']==choices[-1]['version_id']),None)
def public_data(value):
 if type(value) is dict:return {k:public_data(v) for k,v in value.items() if k not in ('id','project_id','chapter_id','outline_id','version_id','created_at','updated_at','current_version_id','previous_version_id','target_character_id') and not k.endswith('_ids')}
 if type(value) is list:return [public_data(v) for v in value]
 return value
def build_seed(state,raw):
 options=parse(SeedOptions,raw);doc=state['document'];chapter=next((v for v in doc['chapters'] if v['id']==options.chapter_id),None);require(options.chapter_id is None or chapter is not None,'trial.invalid_scope');sources={};guards=[]
 def guard(kind,identifier):
  value=parse(Guard,capture_source(state,dict(kind=kind,entity_id=identifier)))
  if not any((v.kind,v.entity_id)==(value.kind,value.entity_id) for v in guards):guards.append(value)
 for name in options.fields:
  if name=='project':sources[name]=public_data(doc['project']);guard('project',doc['project']['id'])
  elif name=='worldbuilding':sources[name]=state['worldbuilding'];guard('worldbuilding',doc['project']['id'])
  elif name=='characters':
   sources[name]=public_data(doc['characters'])
   for character in doc['characters']:guard('character',character['id'])
  elif name=='book_outline':
   sources[name]=public_data(doc['book_outline'])
   if doc['book_outline']:guard('book_outline',doc['book_outline']['id'])
   else:guard('project',doc['project']['id'])
  elif name=='chapter_body':
   start=options.chapter_start;end=options.chapter_end if options.chapter_end is not None else len(chapter['content']);require(0<=start<end<=len(chapter['content']) and end-start<=20000,'trial.choose_range');sources[name]=dict(title=chapter['title'],start=start,end=end,total_chars=len(chapter['content']),text=chapter['content'][start:end]);guard('chapter',chapter['id'])
  elif name=='chapter_plan':
   plan=next((v for v in doc['chapter_outlines'] if v['chapter_id']==chapter['id']),None);sources[name]=public_data(plan);guard('chapter_outline',plan['id']) if plan else guard('chapter',chapter['id'])
  elif name=='idea':sources[name]=state['ideas'].get(chapter['id'],'');guard('idea',chapter['id'])
  elif name=='selected_plan':
   plan=get_version(state,options.plan_version_id);require(state['book_creation_choices'][-1]['version_id']==plan['id'] and plan['id']==next(v['id'] for v in reversed(state['book_creation_versions']) if v['branch_id']==plan['branch_id']),'trial.source_changed');sources[name]=public_data(plan['data'])
 require(options.author_text.strip() or sources,'trial.empty_seed');preset=selected_preset(state);rules=state['writing_rules'] if options.include_rules else '';prompt=preset['settings']['style_prompt'] if options.include_preset_prompt and preset else ''
 if options.include_rules:guard('writing_rules',doc['project']['id'])
 source_json=json.dumps(dict(author_text=options.author_text,selected_saved_material=sources),ensure_ascii=False,sort_keys=True,separators=(',',':'));require(len(source_json)<=24000,'trial.seed_limit');values=dict(options=options,source_revision=state['revision'],source_json=source_json,source_sha256=digest(source_json),guards=tuple(guards),lock_ids=lock_ids(state),preset_version_id=preset['id'] if preset and options.include_preset_prompt else None,legacy_rules=rules,preset_prompt=prompt);values['seed_sha256']=seed_hash(values);return Seed(**values)
def seed_fresh(state,seed):
 try:
  current=build_seed(state,seed['options']);return current.seed_sha256==seed['seed_sha256'] and tuple(seed['lock_ids'])==lock_ids(state) and all((actual:=capture_source(state,dict(kind=g['kind'],entity_id=g['entity_id'])))['version_id']==g['version_id'] and actual['source_sha256']==g['source_sha256'] for g in seed['guards']) and current.preset_version_id==seed['preset_version_id']
 except (ValueError,KeyError,StopIteration):return False
def emit(state,task,status,owner):
 previous=next((v for v in reversed(state['style_trial_events']) if v['task_id']==task['id']),None);state['style_trial_events'].append(encode(Event(id=str(uuid4()),project_id=task['project_id'],task_id=task['id'],previous_event_id=previous['id'] if previous else None,status=status,owner_id=owner,created_at=utc_now())))

class TrialAdapter:
 adapter_id='style-trial-v1';capabilities=('style_trial',)
 def __init__(self,providers,enabled):self.providers,self.enabled,self.transport=providers,enabled,ConfiguredHttpTransport()
 def saved(self,configuration,*,reserve=True):
  require(self.enabled and not self.providers.offline,'trial.models_disabled');return self.providers.generation_book_connection(configuration.connection_id,configuration.model_id,destination=encode(configuration.destination),stamp=configuration.configuration_stamp,enabled=self.enabled,confirmed=True,reserve=reserve)
 def run_trial(self,call,token):token.checkpoint();saved=self.saved(call.task.configuration);return self.transport.send(WireInput(call.request_body),saved,token,call.task.seed.options.target_chars)

class TrialCoordinator:
 def __init__(self,parent,providers,styles,*,enabled=False):
  self.parent,self.service,self.repository,self.providers,self.styles=parent,parent.service,parent.repository,providers,styles;self.adapter=TrialAdapter(providers,enabled);parent.registry.register('style_trial',self.adapter);parent.trials=self
 def preview(self,project,options):return dict(seed=encode(build_seed(self.service.get(project),options)),model_request_sent=False,style_precedence=['author_instruction','explicit_card_or_baseline','explicit_legacy_rules','explicit_preset_prompt'],original_style_material_included=False)
 def _configuration(self,state,raw):
  preset=selected_preset(state)
  if raw is None:
   step=next((v for v in preset['settings']['steps'] if v['step']=='style_trial'),None) if preset else None;require(step is not None and step['connection_id'],'trial.configure_step');raw={k:v for k,v in step.items() if k!='step'};raw['prompt_version']='rewrite-1'
  options=canonical_options(raw);self.providers.validate_sampling(options);profile=parse(Profile,options)
  with self.providers.lock:destination=BookDestination(**self.providers.book_destination(profile.connection_id,profile.model_id));stamp=self.providers.configuration_stamp()
  configuration=Configuration(**sampling_kwargs(options),adapter_id='style-trial-v1',source_adapter_id=profile.adapter_id,connection_id=profile.connection_id,model_id=profile.model_id,temperature=profile.temperature,max_tokens=profile.max_tokens,budget_limit=profile.budget_limit,allow_unknown_cost=profile.allow_unknown_cost,destination=destination,configuration_stamp=stamp);return profile,configuration,preset['id'] if preset else None
 def _limits(self,state,calls,tokens,count,profiles):
  preset=selected_preset(state);budget=preset['settings']['budget'] if preset else dict(max_external_calls=10,max_reserved_output_tokens=81920);require(type(calls) is int and count<=calls<=budget['max_external_calls'] and type(tokens) is int and sum(p.max_tokens for p in profiles)<=tokens<=budget['max_reserved_output_tokens'],'trial.budget_exceeded')
 def _task(self,state,project,identity,seed,style_mode,style_version,profile,configuration,preset,budget,calls,tokens,timeout,retry,preparation_sha):
  require(style_mode in ('baseline','card') and (style_mode=='baseline')==(style_version is None),'trial.invalid_style');style=None
  if style_version is not None:
   card=find(state,'style_cards',style_version);style=StyleSnapshot(version_id=card['id'],style_id=card['style_id'],revision=card['revision'],name=card['name'],prompt=card['prompt'],card=parse(Features,card['card']))
  values=dict(id=uid(identity,'trial'),project_id=project,operation_id=identity,preparation_sha256=preparation_sha,owner_id=self.parent.owner_id,task_type='style_trial',prompt_version='style-trial-short-1',seed=seed,style_mode=style_mode,style=style,profile=profile,configuration=configuration,preset_version_id=preset,budget_id=budget,max_calls=calls,max_output_tokens=tokens,timeout_ms=timeout,retry_of=retry,created_at=utc_now());body=trial_body(encode_partial(values));values['body_sha256']=digest(body);values['request_sha256']=task_hash(digest(body),encode(configuration));task=Task(**values);state['style_trial_tasks'].append(encode(task));emit(state,encode(task),'pending',self.parent.owner_id);return task,body.encode()
 def prepare(self,project,request):
  fields(request,('operation_id','seed_options','seed_sha256','style_mode','style_version_id','model_options','max_calls','max_output_tokens','timeout_ms','retry_of'));identity=uuid_value(request['operation_id']);state=self.service.get(project);old=next((v for v in state.get('style_trial_tasks',[]) if v['operation_id']==identity),None)
  if old:require(old['preparation_sha256']==fingerprint(request),'trial.identity_conflict');return self.describe(project,old['id'])
  require(self.adapter.enabled and not self.providers.offline,'trial.models_disabled');profile,configuration,preset=self._configuration(state,request['model_options']);self._limits(state,request['max_calls'],request['max_output_tokens'],1,[profile]);blobs=[]
  def operation(current):
   old=next((v for v in current.get('style_trial_tasks',[]) if v['operation_id']==identity),None)
   if old:require(old['preparation_sha256']==fingerprint(request),'trial.identity_conflict');return None,old['id']
   seed=build_seed(current,request['seed_options']);require(seed.seed_sha256==request['seed_sha256'],'trial.source_changed');upgrade(current)
   if request['retry_of'] is not None:find(current,'style_trial_tasks',request['retry_of'])
   task,body=self._task(current,project,identity,seed,request['style_mode'],request['style_version_id'],profile,configuration,preset,identity,request['max_calls'],request['max_output_tokens'],request['timeout_ms'],request['retry_of'],fingerprint(request));blobs.append(body);return current,task.id
  identifier=self.repository.atomic(project,operation,identity_claim=('style_trial_tasks','operation_id',identity),blobs=blobs);return self.describe(project,identifier)
 def create_comparison(self,project,request):
  fields(request,('experiment_id','title','seed_options','seed_sha256','profiles','max_calls','max_output_tokens','timeout_ms'));identity=uuid_value(request['experiment_id']);state=self.service.get(project);require(type(request['profiles']) is list and len(request['profiles'])==2,'trial.invalid_experiment');require(self.adapter.enabled and not self.providers.offline,'trial.models_disabled');configured=[]
  for choice in request['profiles']:fields(choice,('style_mode','style_version_id','model_options'));configured.append(self._configuration(state,choice['model_options']))
  self._limits(state,request['max_calls'],request['max_output_tokens'],2,[v[0] for v in configured]);blobs=[]
  def operation(current):
   old=next((v for v in current.get('comparison_experiments',[]) if v['id']==identity),None)
   if old:require(is_trial_experiment(old) and old['title']==request['title'] and old['common_seed_sha256']==request['seed_sha256'] and old['preparation_sha256']==fingerprint(request),'trial.identity_conflict');return None,dict(experiment_id=identity)
   seed=build_seed(current,request['seed_options']);require(seed.seed_sha256==request['seed_sha256'] and seed.options.rubric.strip(),'trial.source_changed');upgrade(current);slots=[];sides=['A','B']
   if secrets.randbelow(2):sides.reverse()
   for i,(choice,(profile,configuration,preset)) in enumerate(zip(request['profiles'],configured)):
    task,body=self._task(current,project,uid(identity,'configuration-operation/'+str(i)),seed,choice['style_mode'],choice['style_version_id'],profile,configuration,preset,identity,request['max_calls'],request['max_output_tokens'],request['timeout_ms'],None,fingerprint(choice));blobs.append(body);slots.append(ArenaConfiguration(id=uid(identity,'configuration/'+str(i)),index=i,side=sides[i],task_id=task.id))
   experiment=TrialExperiment(id=identity,project_id=project,title=request['title'],trial_kind='style_trial',preparation_sha256=fingerprint(request),chapter_id=seed.options.chapter_id,source_revision=seed.source_revision,rubric=seed.options.rubric,profiles=tuple(v[0] for v in configured),configurations=tuple(slots),common_seed_sha256=seed.seed_sha256,created_at=utc_now());current['comparison_experiments'].append(encode(experiment));return current,dict(experiment_id=identity)
  return self.repository.atomic(project,operation,identity_claim=('comparison_experiments','id',identity),blobs=blobs)
 def _describe(self,state,identifier):
  task=find(state,'style_trial_tasks',identifier);last=last_event(state,identifier);candidate=next((v for v in state['style_trial_candidates'] if v['task_id']==identifier),None);responses=[v for v in state['style_trial_results'] if v['task_id']==identifier];display='interrupted' if last['status'] in ('pending','running') and task['owner_id']!=self.parent.owner_id else last['status'];return dict(task=task,status=last['status'],display_status=display,candidate=candidate,events=[v for v in state['style_trial_events'] if v['task_id']==identifier],responses=[dict(record=v,response=strict_json_loads(self.repository.blob(v['response_sha256']))) for v in responses],request_body=self.repository.blob(task['body_sha256']).decode(),source_fresh=seed_fresh(state,task['seed']),choices=[v for v in state['style_trial_choices'] if v['task_id']==identifier])
 def feature_details(self,state,identifier):
  from novel_writer.domain.style_checks import evaluate,summarize
  task=find(state,'style_trial_tasks',identifier)
  candidate=next((v for v in state.get('style_trial_candidates',[]) if v['task_id']==identifier),None)
  empty=dict(status='pending',checks=[])
  if candidate is None:return dict(feature_report=empty,repeatability=summarize([]),card_controls=[])
  # Never expose a blind experiment's identities or feature targets before reveal.
  experiment=next((e for e in state.get('comparison_experiments',[]) if is_trial_experiment(e) and any(v['task_id']==identifier for v in e['configurations'])),None)
  if experiment and not any(v['experiment_id']==experiment['id'] for v in state.get('comparison_reveals',[])):
   return dict(feature_report=dict(status='reveal_required',checks=[]),repeatability=summarize([]),card_controls=[])
  report=evaluate(task['style']['card'],candidate['output_text']) if task['style'] else dict(status='no_card',checks=[])
  def group(t):return (t['seed']['seed_sha256'],t['style']['version_id'] if t['style'] else None,t['configuration'])
  peers=[t for t in state['style_trial_tasks'] if group(t)==group(task)]
  successful={v['task_id']:v for v in state['style_trial_candidates'] if last_event(state,v['task_id'])['status']=='succeeded'}
  reports=[evaluate(t['style']['card'],successful[t['id']]['output_text']) for t in peers if t['style'] and t['id'] in successful and not any(is_trial_experiment(e) and any(c['task_id']==t['id'] for c in e['configurations']) and not any(r['experiment_id']==e['id'] for r in state.get('comparison_reveals',[])) for e in state.get('comparison_experiments',[]))]
  controls=[]
  if task['style'] is None:
   seen=set()
   for t in state['style_trial_tasks']:
    if not t['style'] or t['seed']['seed_sha256']!=task['seed']['seed_sha256'] or t['configuration']!=task['configuration']:continue
    e=next((e for e in state.get('comparison_experiments',[]) if is_trial_experiment(e) and any(c['task_id']==t['id'] for c in e['configurations'])),None)
    if e and not any(r['experiment_id']==e['id'] for r in state.get('comparison_reveals',[])):continue
    version=t['style']['version_id']
    if version not in seen:controls.append(dict(style_version_id=version,name=t['style']['name'],report=evaluate(t['style']['card'],candidate['output_text'])));seen.add(version)
  return dict(feature_report=report,repeatability=summarize(reports),card_controls=controls)
 def describe(self,project,identifier):
  state=self.service.get(project);return dict(self._describe(state,identifier),**self.feature_details(state,identifier))
 def listing(self,project):
  state=self.service.get(project);owned={c['task_id'] for e in state.get('comparison_experiments',[]) if is_trial_experiment(e) for c in e['configurations']};return dict(tasks=[self._describe(state,v['id']) for v in state.get('style_trial_tasks',[]) if v['id'] not in owned],experiments=[dict(id=e['id'],title=e['title'],source_revision=e['source_revision']) for e in state.get('comparison_experiments',[]) if is_trial_experiment(e)],enabled=self.adapter.enabled and not self.providers.offline)
 def start(self,project,identifier,confirmation):
  task=find(self.service.get(project),'style_trial_tasks',identifier);require(type(confirmation) is dict and set(confirmation)=={'confirm_external','request_sha256'} and confirmation['confirm_external'] is True and confirmation['request_sha256']==task['request_sha256'],'trial.confirm_request');self.adapter.saved(parse(Configuration,task['configuration']),reserve=False);require(task['owner_id']==self.parent.owner_id,'trial.interrupted');require(not self.parent.closed.is_set() and self.parent.slot.acquire(blocking=False),'trial.busy')
  try:
   def operation(state):
    require(last_event(state,identifier)['status']=='pending','trial.already_run');require(seed_fresh(state,task['seed']),'trial.source_changed');started={v['task_id'] for v in state['style_trial_events'] if v['status']=='running'};spent=[v for v in state['style_trial_tasks'] if v['id'] in started and v['budget_id']==task['budget_id']];require(len(spent)<task['max_calls'] and sum(v['profile']['max_tokens'] for v in spent)+task['profile']['max_tokens']<=task['max_output_tokens'],'trial.budget_exceeded');emit(state,task,'running',self.parent.owner_id);return state,True
   self.repository.atomic(project,operation);token=CancellationToken(threading.Event(),time.monotonic()+task['timeout_ms']/1000);worker=threading.Thread(target=self._worker,args=(task,token),daemon=True)
   with self.parent.lock:self.parent.active[identifier]=(worker,token)
   worker.start();return self.describe(project,identifier)
  except BaseException:self.parent.slot.release();raise
 def _worker(self,task,token):
  response=None;error=None
  try:response=self.parent.registry.execute_trial(TrialCall(task=parse(Task,task),request_body=self.repository.blob(task['body_sha256']).decode()),token);token.checkpoint()
  except TaskCancelled:error='interrupted' if self.parent.closed.is_set() else 'cancelled'
  except TaskTimeout:error='timeout'
  except Exception:error='trial.adapter_failed'
  try:
   response=response or empty_response(error_code=error or 'trial.adapter_failed');raw=binary(encode(response))
   def operation(state):
    result=Result(id=str(uuid4()),project_id=task['project_id'],task_id=task['id'],response_sha256=sha(raw),usage=response.usage,reported_model=response.reported_model,error_code=error or response.error_code,created_at=utc_now());state['style_trial_results'].append(encode(result))
    if last_event(state,task['id'])['status']!='running':return state,True
    failure=error or response.error_code;status='succeeded' if response.complete and failure is None else 'interrupted' if failure=='interrupted' else 'cancelled' if failure=='cancelled' else 'failed'
    if status=='succeeded':state['style_trial_candidates'].append(encode(Candidate(id=str(uuid4()),project_id=task['project_id'],task_id=task['id'],result_id=result.id,output_text=response.output_text,output_sha256=digest(response.output_text),created_at=utc_now())))
    emit(state,task,status,self.parent.owner_id);return state,True
   self.repository.atomic(task['project_id'],operation,blobs=(raw,))
  finally:
   with self.parent.lock:self.parent.active.pop(task['id'],None)
   self.parent.slot.release()
 def cancel(self,project,identifier):
  def operation(state):
   task=find(state,'style_trial_tasks',identifier)
   if last_event(state,identifier)['status'] not in ('pending','running'):return None,dict(accepted=False)
   emit(state,task,'cancelled',self.parent.owner_id);return state,dict(accepted=True)
  value=self.repository.atomic(project,operation)
  with self.parent.lock:active=self.parent.active.get(identifier)
  if active:active[1].event.set()
  return value
 def comparison_setup(self,state,experiment):
  tasks={v['id']:v for v in state['style_trial_tasks']};rows=[];projected=arena_tasks(state)
  with self.parent.lock:live=set(self.parent.active)
  for slot in experiment['configurations']:
   task=tasks[slot['task_id']];status=projected[task['id']]['status'];interrupted=task['owner_id']!=self.parent.owner_id and status in ('pending','running');rows.append(dict(configuration_id=slot['id'],configuration_label='配置'+str(slot['index']+1),profile=task['profile'],style=task['style'],style_mode=task['style_mode'],request_body=self.repository.blob(task['body_sha256']).decode(),request_sha256=task['request_sha256'],destination=task['configuration']['destination'],submitted=status!='pending' or interrupted,status='interrupted' if interrupted else status,can_cancel=status in ('pending','running')))
  return dict(experiment_id=experiment['id'],title=experiment['title'],trial_kind='style_trial',configurations=rows,common_seed_sha256=experiment['common_seed_sha256'],executing=any(v['task_id'] in live for v in experiment['configurations']),can_submit=not live,results_ready=all(projected[v['task_id']]['status'] in TERMINAL for v in experiment['configurations']))
 def choose(self,project,request):
  fields(request,('operation_id','task_id','action','chapter_id','confirmed'));identity=uuid_value(request['operation_id']);require(request['confirmed'] is True,'trial.confirm_choice')
  def operation(state):
   old=next((v for v in state['style_trial_choices'] if v['operation_id']==identity),None)
   if old:require((old['task_id'],old['action'],old['chapter_id'])==(request['task_id'],request['action'],request['chapter_id']),'trial.identity_conflict');return None,old
   task=find(state,'style_trial_tasks',request['task_id']);candidate=next((v for v in state['style_trial_candidates'] if v['task_id']==task['id']),None);require(candidate is not None and last_event(state,task['id'])['status']=='succeeded','trial.no_candidate');experiment=next((e for e in state['comparison_experiments'] if is_trial_experiment(e) and any(c['task_id']==task['id'] for c in e['configurations'])),None);require(experiment is None or any(r['experiment_id']==experiment['id'] for r in state['comparison_reveals']),'trial.reveal_first');style_choice=None
   if request['action']=='apply_style':
    require(seed_fresh(state,task['seed']),'trial.source_changed');operation=self.styles._choose_operation(project,dict(operation_id=uid(identity,'style-choice'),chapter_id=request['chapter_id'],version_id=task['style']['version_id'] if task['style'] else None,confirmed=True));_,style_choice=operation(state)
   else:require(request['action']=='open_candidate','trial.invalid_choice')
   record=Choice(id=uid(identity,'choice'),project_id=project,operation_id=identity,task_id=task['id'],candidate_id=candidate['id'],action=request['action'],chapter_id=request['chapter_id'],style_choice_id=style_choice['id'] if style_choice else None,created_at=utc_now());state['style_trial_choices'].append(encode(record));return state,encode(record)
  return self.repository.atomic(project,operation,identity_claim=('style_trial_choices','operation_id',identity))

def encode_partial(value):
 return {key:encode(item) if hasattr(item,'__dataclass_fields__') else item for key,item in value.items()}
