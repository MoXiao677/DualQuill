"""Persistent console with explicit, non-autonomous V24 run orchestration."""
from copy import deepcopy
from uuid import uuid4,uuid5,NAMESPACE_URL
from novel_writer.domain.console import (
 Session,Message,Plan,Step,Dispatch,Ref,Run,RunStep,RunAction,STEP_TYPES,RUN_COLLECTIONS,
 TERMINAL_RUN_STATUS,TERMINAL_RUN_STEP_STATUS,
)
from novel_writer.domain.models import utc_now
from novel_writer.domain.tasks import require,uuid_value,encode
from novel_writer.application.fields import check_fields
from novel_writer.application.console_tools import registered,READ_ONLY,catalogue
from novel_writer.application.console_usage import actual_usage,usage_summary
import json
from functools import wraps
from threading import RLock

def serialized(method):
 @wraps(method)
 def call(self,*args,**kwargs):
  with self.lock:return method(self,*args,**kwargs)
 return call

def upgrade(state):
 from novel_writer.application.chapter_lifecycle import upgrade_base as previous
 previous(state);state['workspace_version']=max(state['workspace_version'],20)
 for name in ('console_sessions','console_messages','console_plans','console_dispatches'):state.setdefault(name,[])
 return state

def upgrade_runs(state):
 from novel_writer.application.memory_rollups import upgrade as previous
 previous(state);state['workspace_version']=max(state['workspace_version'],24)
 for name in RUN_COLLECTIONS:state.setdefault(name,[])
 return state

class ConsoleCoordinator:
 def __init__(self,service,writing,planning,expansion):
  self.service,self.repository,self.writing,self.planning,self.expansion=service,service.repository,writing,planning,expansion
  self.lock=RLock()
  self.engines={'chapter_planning':planning,'chapter_writing':writing,'scene_expansion':expansion}
 def _action(self,state,operation):
  return next((value for value in state.get('console_run_actions',[]) if value['operation_id']==operation),None)
 def _replay(self,state,operation,run_id,action,step_id=None):
  old=self._action(state,operation)
  if old is None:return None
  require(old['run_id']==run_id and old['action']==action and (step_id is None or old['step_id']==step_id),'运行操作身份已绑定其它命令')
  return old
 def _run(self,state,run_id):
  run=next((value for value in state.get('console_runs',[]) if value['id']==run_id),None)
  if run is None:raise KeyError('运行不存在')
  return run
 def _session(self,state,session_id):
  session=next((value for value in state.get('console_sessions',[]) if value['id']==session_id),None);require(session is not None,'会话不存在');return session
 def _plan(self,state,session_id):
  plan=next((value for value in state.get('console_plans',[]) if value['session_id']==session_id),None);require(plan is not None,'会话计划不存在');return plan
 def _run_steps(self,state,run_id):
  return sorted((value for value in state.get('console_run_steps',[]) if value['run_id']==run_id),key=lambda value:value['position'])
 def _dispatch_view(self,project,item):
  result=deepcopy(item);status=display='unknown';candidate=receipt=None;late=False;detail={}
  try:
   engine=self.writing.parent if item['engine']=='chapter_writing' and self.writing else self.engines[item['engine']];require(engine is not None,'任务引擎不可用')
   detail=engine.describe(project,item['task_id']);status=detail.get('status') or detail.get('task',{}).get('status','unknown');display=detail.get('display_status',status);candidate=detail.get('latest_candidate',{}).get('id') if detail.get('latest_candidate') else detail.get('task',{}).get('candidate_id');receipt=detail.get('adoptions',[{}])[0].get('id') if detail.get('adoptions') else detail.get('receipts',[{}])[0].get('id') if detail.get('receipts') else None;late=bool(detail.get('late_results') or detail.get('writing',{}).get('late_results'))
  except (ValueError,KeyError):display='interrupted';detail=dict(unavailable=True)
  result.update(status=status,display_status=display,candidate_id=candidate,receipt_id=receipt,late=late,usage=actual_usage(detail),source_fresh=detail.get('source_fresh',detail.get('writing',{}).get('source_fresh')),connection_fresh=detail.get('connection_fresh'));return result
 def _run_step_view(self,project,run,step,plan_revision,archived,state=None):
  state=state if state is not None else self.service.get(project)
  persisted=step['status'];mapped=persisted;reason=step.get('blocked_reason');dispatch=None
  if step.get('dispatch_id'):
   dispatch=next((value for value in state.get('console_dispatches',[]) if value['id']==step['dispatch_id']),None)
   if dispatch is not None:
    dispatch=self._dispatch_view(project,dispatch);display=dispatch['display_status'];candidate=dispatch['candidate_id']
    if persisted not in TERMINAL_RUN_STEP_STATUS:
     if display in ('pending','running'):mapped='awaiting_confirmation'
     elif display in ('adopted',) or dispatch.get('receipt_id'):mapped='completed'
     elif display in ('succeeded','candidate_ready') and candidate:mapped='awaiting_adoption'
     elif display=='failed':mapped='failed';reason='任务失败；不会自动跳过。请明确跳过此步或取消运行。'
     elif display=='cancelled':mapped='cancelled';reason='任务已取消；不会自动跳过。请明确跳过此步或取消运行。'
     elif display in ('interrupted','unknown'):mapped='blocked';reason='任务中断或状态不可读；不会自动跳过。请明确跳过此步或取消运行。'
     elif display=='succeeded':mapped='blocked';reason='任务已完成但没有可采纳候选；请明确跳过此步或取消运行。'
     else:mapped='blocked';reason='任务状态不可推进；请明确跳过此步或取消运行。'
  if plan_revision!=run['plan_revision'] and mapped not in TERMINAL_RUN_STEP_STATUS:reason='计划已修改：运行绑定第%s版，当前第%s版；推进已阻止。'%(run['plan_revision'],plan_revision)
  if archived and mapped not in TERMINAL_RUN_STEP_STATUS:reason='会话已归档；不能推进，可取消运行或明确跳过当前步骤。'
  if mapped not in TERMINAL_RUN_STEP_STATUS:
   from novel_writer.domain.chapter_trash import hidden_ids
   if step['chapter_id'] in hidden_ids(state):reason='目标章节已归档或移入回收站；推进已阻止。'
   if dispatch and (dispatch.get('source_fresh') is False or dispatch.get('connection_fresh') is False):reason='任务输入或模型配置已变化；请取消旧任务并重新准备，不会重发。'
  result=next((v for v in reversed(state.get('console_messages',[])) if v['role']=='result' and step['created_at']<=v['created_at']<=step['updated_at'] and any(ref['kind']=='step' and ref['id']==step['plan_step_id'] for ref in v['refs'])),None) if step['type'] in READ_ONLY else None
  return dict(deepcopy(step),persisted_status=persisted,status=mapped,display_status=dispatch['display_status'] if dispatch else None,task_status=dispatch['status'] if dispatch else None,candidate_id=dispatch['candidate_id'] if dispatch else None,receipt_id=dispatch['receipt_id'] if dispatch else None,late=dispatch['late'] if dispatch else False,blocked_reason=reason,usage=dispatch['usage'] if dispatch else None,result=deepcopy(result))
 def _run_view(self,state,run):
  session=self._session(state,run['session_id']);plan=self._plan(state,run['session_id']);archived=session['archived'];steps=[self._run_step_view(run['project_id'],run,value,plan['revision'],archived,state) for value in self._run_steps(state,run['id'])]
  status=run['status'];current=None
  # Finishing is an explicit append-only action; GET must not strand a persisted running cursor.
  if status=='completed':current=None
  else:current=run['current_step_id']
  current_step=next((value for value in steps if value['id']==current),None) if current else None
  reason=None
  if status not in TERMINAL_RUN_STATUS:
   if plan['revision']!=run['plan_revision']:reason='计划已修改：运行绑定第%s版，当前第%s版；推进已阻止。'%(run['plan_revision'],plan['revision'])
   elif archived:reason='会话已归档；不能推进，可取消运行或明确跳过当前步骤。'
   elif current_step and current_step['blocked_reason']:reason=current_step['blocked_reason']
  view=dict(deepcopy(run),persisted_status=run['status'],status=status,current_step_id=current,plan_revision_current=plan['revision'],plan_changed=plan['revision']!=run['plan_revision'],blocked_reason=reason,steps=steps)
  view.update(usage=usage_summary(steps),can_advance=status=='running' and not reason and current_step is not None and current_step['status'] in ('queued','completed'),can_pause=status=='running',can_resume=status=='paused' and not archived and not view['plan_changed'],can_cancel=status in ('running','paused'),can_skip=status in ('running','paused') and current_step is not None and current_step['status'] not in TERMINAL_RUN_STEP_STATUS)
  return view
 def list_runs(self,project,session_id=None):
  state=self.service.get(project);runs=[]
  for run in state.get('console_runs',[]):
   if session_id is not None and run['session_id']!=session_id:continue
   steps=self._run_steps(state,run['id']);runs.append(dict(deepcopy(run),step_count=len(steps),completed_steps=sum(value['status'] in ('completed','skipped') for value in steps)))
  return dict(revision=state['revision'],runs=runs)
 def describe_run(self,project,run_id):
  state=self.service.get(project);run=self._run(state,run_id);session=self._session(state,run['session_id']);plan=self._plan(state,run['session_id'])
  view=self._run_view(state,run);return dict(revision=state['revision'],session=deepcopy(session),plan=deepcopy(plan),run=view,steps=view['steps'])
 @serialized
 def start(self,project,request):
  fields={'operation_id','session_id','expected_revision'};check_fields(request,fields);require(set(request)==fields,'运行字段缺失');identity=uuid_value(request['operation_id']);require(type(request['expected_revision']) is int and request['expected_revision']>=1,'保存编号非法')
  def operation(state):
   upgrade_runs(state);old=self._action(state,identity)
   if old:
    require(old['action']=='start','运行操作身份已绑定其它命令');run=self._run(state,old['run_id']);require(run['session_id']==request['session_id'],'运行操作身份已绑定其它会话');return None,run['id']
   require(state['revision']==request['expected_revision'],'保存编号已变化，请刷新后重新开始运行')
   session=self._session(state,request['session_id']);require(not session['archived'],'归档会话不能开始运行');plan=self._plan(state,session['id']);require(plan['steps'],'计划没有可执行步骤')
   from novel_writer.domain.chapter_trash import hidden_ids
   chapters={value['id'] for value in state['document']['chapters']};hidden=hidden_ids(state);require(all(value['chapter_id'] in chapters and value['chapter_id'] not in hidden for value in plan['steps']),'计划步骤目标章节不存在或已归档/移入回收站')
   require(not any(value['session_id']==session['id'] and value['status'] in ('running','paused') for value in state['console_runs']),'此会话已有进行中的运行')
   now=utc_now();run_id=str(uuid5(NAMESPACE_URL,identity+'/run'));steps=[]
   for position,value in enumerate(plan['steps']):
    steps.append(encode(RunStep(id=str(uuid5(NAMESPACE_URL,identity+'/run-step/'+value['id'])),project_id=project,run_id=run_id,plan_step_id=value['id'],position=position,type=value['type'],chapter_id=value['chapter_id'],instruction=value['instruction'],scene_order=value['scene_order'],selection_start=value['selection_start'],selection_end=value['selection_end'],status='queued',dispatch_id=None,engine=None,task_id=None,blocked_reason=None,created_at=now,updated_at=now)))
   state['console_runs'].append(encode(Run(id=run_id,project_id=project,session_id=session['id'],plan_revision=plan['revision'],status='running',current_step_id=steps[0]['id'],created_at=now,updated_at=now)));state['console_run_steps'].extend(steps)
   state['console_run_actions'].append(encode(RunAction(id=str(uuid5(NAMESPACE_URL,identity+'/run-action')),project_id=project,run_id=run_id,operation_id=identity,action='start',expected_revision=request['expected_revision'],step_id=None,from_status=None,to_status='running',step_from_status=None,step_to_status=None,created_at=now)))
   state['console_messages'].append(encode(Message(id=str(uuid5(NAMESPACE_URL,identity+'/run-message')),project_id=project,session_id=session['id'],role='system',text='已开始运行（绑定计划第%s版）'%plan['revision'],refs=(),created_at=now)));session['updated_at']=now;return state,run_id
  run_id=self.repository.atomic(project,operation,identity_claim=('console_run_actions','operation_id',identity));return self.describe_run(project,run_id)
 def _finish_action(self,state,run,session,identity,action,expected,step_id,from_status,to_status,step_from,step_to):
  now=utc_now();state['console_run_actions'].append(encode(RunAction(id=str(uuid5(NAMESPACE_URL,identity+'/run-action')),project_id=run['project_id'],run_id=run['id'],operation_id=identity,action=action,expected_revision=expected,step_id=step_id,from_status=from_status,to_status=to_status,step_from_status=step_from,step_to_status=step_to,created_at=now)));run['updated_at']=now;session['updated_at']=now
 def _permission_text(self,allowed):
  return '仅本次请求允许连续执行确定性只读工具：'+json.dumps(sorted(allowed),ensure_ascii=False)+'；不授权付费请求或正式采纳；重开/恢复/复制后不续行。'
 def _read_tool(self,state,step):
  registered(step['type'])
  chapter=next((v for v in state['document']['chapters'] if v['id']==step['chapter_id']),None);require(chapter is not None,'目标章节不存在')
  from novel_writer.domain.chapter_trash import hidden_ids
  require(chapter['id'] not in hidden_ids(state),'目标章节已归档或移入回收站')
  if step['type']=='chapter.inspect':
   from hashlib import sha256
   text=chapter['content'];return dict(tool=step['type'],chapter_id=chapter['id'],title=chapter['title'],content_chars=len(text),content_sha256=sha256(text.encode('utf-8')).hexdigest(),preview=text[:1200],preview_truncated=len(text)>1200,source_revision=state['revision'])
  require(step['type']=='context.preview','不是已注册只读工具')
  from novel_writer.application.context_preview import preview
  return dict(tool=step['type'],source_revision=state['revision'],report=preview(state,dict(chapter_id=chapter['id'],scope='previous',budget_chars=6000,include_current_plan=True,include_writing_rules=True,include_characters=True,include_worldbuilding=True,include_memories=True)))
 def _advance_readonly(self,project,request,run_id,current_id,target_id,allowed):
  identity=request['operation_id']
  def operation(state):
   if self._replay(state,identity,run_id,'advance'):return None,None
   require(state['revision']==request['expected_revision'],'保存编号已变化，请刷新后推进')
   run=self._run(state,run_id);session=self._session(state,run['session_id']);plan=self._plan(state,session['id'])
   require(run['status']=='running' and not session['archived'] and plan['revision']==run['plan_revision'],'运行已暂停、取消、归档或计划已变化')
   require(run['current_step_id']==current_id,'运行游标已变化，请刷新')
   steps=self._run_steps(state,run_id);current=next(v for v in steps if v['id']==current_id);target=next(v for v in steps if v['id']==target_id)
   require(target['status']=='queued' and target['type'] in READ_ONLY,'只读步骤已变化')
   if current_id!=target_id:
    effective=self._run_step_view(project,run,current,plan['revision'],False);require(effective['status']=='completed' and not effective['blocked_reason'],'前一步尚未正式采纳')
    current['status']='completed';current['updated_at']=utc_now()
   state['console_messages'].append(encode(Message(id=str(uuid5(NAMESPACE_URL,identity+'/readonly-permission')),project_id=project,session_id=session['id'],role='system',text=self._permission_text(allowed),refs=(),created_at=utc_now())))
   count=0;first=target
   while target is not None and target['type'] in READ_ONLY and (count==0 or target['type'] in allowed):
    if count==0 and allowed:require(target['type'] in allowed,'当前只读工具不在本次作者许可内')
    try:
     result=self._read_tool(state,target);text=json.dumps(result,ensure_ascii=False,sort_keys=True);require(len(text)<=50000,'只读结果超过保存上限，未截断结果')
    except ValueError as error:
     target.update(status='failed',blocked_reason='只读工具失败：'+str(error),updated_at=utc_now());run['current_step_id']=target['id'];break
    state['console_messages'].append(encode(Message(id=str(uuid5(NAMESPACE_URL,identity+'/readonly-result/'+target['id'])),project_id=project,session_id=session['id'],role='result',text=text,refs=(Ref(kind='step',id=target['plan_step_id']),),created_at=utc_now())))
    target.update(status='completed',blocked_reason=None,updated_at=utc_now());count+=1
    target=next((v for v in steps if v['position']>target['position'] and v['status']=='queued'),None)
    run['current_step_id']=target['id'] if target else None
    if target is None:run['status']='completed'
    if not allowed:break
   self._finish_action(state,run,session,identity,'advance',request['expected_revision'],first['id'],'running',run['status'],'queued',first['status']);return state,None
  self.repository.atomic(project,operation,identity_claim=('console_run_actions','operation_id',identity));return self.describe_run(project,run_id)
 @serialized
 def advance(self,project,request,run_id):
  fields={'operation_id','expected_revision'};check_fields(request,fields|{'allow_readonly'});require(set(request) in (fields,fields|{'allow_readonly'}),'推进字段缺失');identity=uuid_value(request['operation_id']);require(type(request['expected_revision']) is int and request['expected_revision']>=1,'保存编号非法')
  allowed=request.get('allow_readonly',[]);require(type(allowed) is list and all(type(v) is str and v in READ_ONLY for v in allowed) and len(set(allowed))==len(allowed),'自动推进许可仅接受已注册的确定性只读工具；不授权收费或正式写入')
  state=self.service.get(project)
  if self._replay(state,identity,run_id,'advance'):
   permission=next((v for v in state['console_messages'] if v['id']==str(uuid5(NAMESPACE_URL,identity+'/readonly-permission'))),None)
   require((permission is not None and permission['text']==self._permission_text(allowed)) or (permission is None and not allowed),'操作编号已绑定不同的只读许可')
   return self.describe_run(project,run_id)
  require(state['revision']==request['expected_revision'],'保存编号已变化，请刷新后重新推进')
  run=self._run(state,run_id);session=self._session(state,run['session_id']);plan=self._plan(state,run['session_id']);require(not session['archived'],'归档会话不能推进');require(run['status']=='running','只有运行中的编排可以推进');require(plan['revision']==run['plan_revision'],'计划已修改，运行绑定已失效；推进已阻止')
  steps=self._run_steps(state,run_id);current=next((value for value in steps if value['id']==run['current_step_id']),None);require(current is not None,'运行游标不存在')
  effective=self._run_step_view(project,run,current,plan['revision'],session['archived'],state);status=effective['status']
  require(not effective['blocked_reason'],effective['blocked_reason'] or '步骤受阻')
  if status in ('awaiting_confirmation','awaiting_adoption','prepared'):raise ValueError('当前步骤尚未采纳或跳过，不能准备下一步')
  if status in ('failed','blocked','cancelled'):raise ValueError(effective['blocked_reason'] or '当前步骤不能自动推进；请明确跳过或取消运行')
  target=None;reconcile=None
  if status=='queued':target=current
  else:
   position=current['position'];target=next((value for value in steps if value['position']>position and value['status']=='queued'),None);reconcile=(current,'completed') if status=='completed' else None
  if target is None:
   def complete(current_state):
    upgrade_runs(current_state);old=self._action(current_state,identity)
    if old:require(old['run_id']==run_id and old['action']=='advance','运行操作身份已绑定其它命令');return None,None
    latest=self._run(current_state,run_id);latest_session=self._session(current_state,latest['session_id']);require(latest['status']=='running' and not latest_session['archived'] and self._plan(current_state,latest['session_id'])['revision']==latest['plan_revision'],'编排状态、归档或计划已变化，请刷新')
    latest_steps=self._run_steps(current_state,run_id);latest_current=next((value for value in latest_steps if value['id']==latest['current_step_id']),None);require(latest_current is not None and latest_current['id']==current['id'] and latest_current['status'] in ('awaiting_confirmation','awaiting_adoption','completed'),'运行步骤已变化，请刷新')
    if latest_current['status']!='completed':latest_current['status']='completed';latest_current['updated_at']=utc_now()
    latest['status']='completed';latest['current_step_id']=None;self._finish_action(current_state,latest,latest_session,identity,'advance',request['expected_revision'],latest_current['id'],'running','completed',status,'completed');return current_state,None
   self.repository.atomic(project,complete,identity_claim=('console_run_actions','operation_id',identity));return self.describe_run(project,run_id)
  registered(target['type'])
  if target['type'] in READ_ONLY:return self._advance_readonly(project,request,run_id,current['id'],target['id'],allowed)
  require(not allowed,'当前是模型任务准备步骤；只读连续推进到此停止，请明确单步准备')
  dispatch=next((value for value in state.get('console_dispatches',[]) if value['session_id']==run['session_id'] and value['step_id']==target['plan_step_id']),None)
  if dispatch is None:
   engine,task_id=self._prepare_step(state,session,target,str(uuid5(NAMESPACE_URL,run_id+'/prepare/'+target['id'])),project)
  else:engine,task_id=dispatch['engine'],dispatch['task_id']
  def operation(current_state):
   upgrade_runs(current_state);old=self._action(current_state,identity)
   if old:require(old['run_id']==run_id and old['action']=='advance','运行操作身份已绑定其它命令');return None,None
   latest=self._run(current_state,run_id);latest_session=self._session(current_state,latest['session_id']);latest_plan=self._plan(current_state,latest['session_id']);require(latest['status']=='running' and not latest_session['archived'],'编排状态或归档已变化，请刷新');require(latest_plan['revision']==latest['plan_revision'],'计划已修改，运行绑定已失效');require(latest['current_step_id']==current['id'],'运行游标已变化，请刷新')
   latest_steps=self._run_steps(current_state,run_id);latest_target=next(value for value in latest_steps if value['id']==target['id']);require(latest_target['status']=='queued','运行步骤已推进，请刷新')
   if reconcile is not None:
    previous=next(value for value in latest_steps if value['id']==reconcile[0]['id']);previous['status']='completed';previous['updated_at']=utc_now()
   latest_dispatch=next((value for value in current_state.get('console_dispatches',[]) if value['session_id']==latest['session_id'] and value['step_id']==latest_target['plan_step_id']),None)
   if latest_dispatch is None:
    dispatch_id=str(uuid5(NAMESPACE_URL,identity+'/dispatch'));latest_dispatch=encode(Dispatch(id=dispatch_id,project_id=project,session_id=latest['session_id'],step_id=latest_target['plan_step_id'],engine=engine,task_id=task_id,created_at=utc_now()));current_state['console_dispatches'].append(latest_dispatch)
   else:dispatch_id=latest_dispatch['id'];require(latest_dispatch['engine']==engine and latest_dispatch['task_id']==task_id,'派发任务已变化，请刷新')
   plan_step=next(value for value in latest_plan['steps'] if value['id']==latest_target['plan_step_id']);plan_step['status']='prepared';latest_plan['updated_at']=utc_now()
   latest_target.update(status='awaiting_confirmation',dispatch_id=dispatch_id,engine=engine,task_id=task_id,blocked_reason=None,updated_at=utc_now());latest['current_step_id']=latest_target['id'];latest['status']='running'
   current_state['console_messages'].append(encode(Message(id=str(uuid5(NAMESPACE_URL,identity+'/run-message')),project_id=project,session_id=latest['session_id'],role='system',text='运行推进：已准备任务（未执行）：'+target['type'],refs=(Ref(kind='task',id=task_id),),created_at=utc_now())))
   self._finish_action(current_state,latest,latest_session,identity,'advance',request['expected_revision'],latest_target['id'],'running','running',status,'awaiting_confirmation');return current_state,None
  self.repository.atomic(project,operation,identity_claim=('console_run_actions','operation_id',identity));return self.describe_run(project,run_id)
 def pause(self,project,request,run_id):
  return self._status_command(project,request,run_id,'pause')
 def resume(self,project,request,run_id):
  return self._status_command(project,request,run_id,'resume')
 @serialized
 def _status_command(self,project,request,run_id,action):
  fields={'operation_id','expected_revision'};check_fields(request,fields);require(set(request)==fields and action in ('pause','resume'),'运行命令字段缺失');identity=uuid_value(request['operation_id']);require(type(request['expected_revision']) is int and request['expected_revision']>=1,'保存编号非法')
  def operation(state):
   upgrade_runs(state)
   if self._replay(state,identity,run_id,action):return None,None
   require(state['revision']==request['expected_revision'],'保存编号已变化，请刷新后重试')
   run=self._run(state,run_id);session=self._session(state,run['session_id']);from_status=run['status'];to_status='paused' if action=='pause' else 'running'
   require((action=='pause' and from_status=='running') or (action=='resume' and from_status=='paused'),'运行状态不允许此命令');require(action!='resume' or not session['archived'],'归档会话不能恢复运行');require(action!='resume' or self._plan(state,session['id'])['revision']==run['plan_revision'],'计划已修改，不能恢复旧运行')
   run['status']=to_status;self._finish_action(state,run,session,identity,action,request['expected_revision'],run['current_step_id'],from_status,to_status,None,None)
   state['console_messages'].append(encode(Message(id=str(uuid5(NAMESPACE_URL,identity+'/run-message')),project_id=project,session_id=session['id'],role='system',text='运行已暂停' if action=='pause' else '运行已恢复',refs=(),created_at=utc_now())));return state,None
  self.repository.atomic(project,operation,identity_claim=('console_run_actions','operation_id',identity));return self.describe_run(project,run_id)
 @serialized
 def cancel(self,project,request,run_id):
  fields={'operation_id','expected_revision'};check_fields(request,fields);require(set(request)==fields,'取消字段缺失');identity=uuid_value(request['operation_id']);require(type(request['expected_revision']) is int and request['expected_revision']>=1,'保存编号非法')
  def operation(state):
   upgrade_runs(state)
   if self._replay(state,identity,run_id,'cancel'):return None,None
   require(state['revision']==request['expected_revision'],'保存编号已变化，请刷新后重试')
   run=self._run(state,run_id);session=self._session(state,run['session_id']);require(run['status'] in ('running','paused'),'运行已结束');from_status=run['status'];step_from=None;current_id=run['current_step_id']
   for step in self._run_steps(state,run_id):
    if step['status'] not in TERMINAL_RUN_STEP_STATUS:
     if step['id']==current_id:step_from=step['status']
     step['status']='cancelled';step['blocked_reason']=None;step['updated_at']=utc_now()
   run['status']='cancelled';run['current_step_id']=None;self._finish_action(state,run,session,identity,'cancel',request['expected_revision'],current_id,from_status,'cancelled',step_from,'cancelled')
   state['console_messages'].append(encode(Message(id=str(uuid5(NAMESPACE_URL,identity+'/run-message')),project_id=project,session_id=session['id'],role='system',text='编排已取消，后续步骤停止；已发送请求请到原任务页取消，已保存结果与候选保留。',refs=(),created_at=utc_now())));return state,None
  self.repository.atomic(project,operation,identity_claim=('console_run_actions','operation_id',identity));return self.describe_run(project,run_id)
 @serialized
 def skip(self,project,request,run_id):
  fields={'operation_id','expected_revision'};check_fields(request,fields|{'step_id'});require(set(request) in (fields,fields|{'step_id'}),'跳过字段缺失');identity=uuid_value(request['operation_id']);require(type(request['expected_revision']) is int and request['expected_revision']>=1,'保存编号非法');requested_step=request.get('step_id')
  if requested_step is not None:uuid_value(requested_step)
  def operation(state):
   upgrade_runs(state)
   if self._replay(state,identity,run_id,'skip',requested_step):return None,None
   require(state['revision']==request['expected_revision'],'保存编号已变化，请刷新后重试')
   run=self._run(state,run_id);session=self._session(state,run['session_id']);require(run['status'] in ('running','paused'),'运行已结束');current_id=run['current_step_id'];from_status=run['status'];require(requested_step is None or requested_step==current_id,'只能明确跳过当前步骤')
   steps=self._run_steps(state,run_id);current=next((value for value in steps if value['id']==current_id),None);require(current is not None and current['status'] not in TERMINAL_RUN_STEP_STATUS,'当前步骤已结束，无需跳过')
   step_from=current['status'];current['status']='skipped';current['blocked_reason']=None;current['updated_at']=utc_now();position=current['position'];target=next((value for value in steps if value['position']>position and value['status']=='queued'),None)
   if target is None:run['status']='completed';run['current_step_id']=None
   else:run['current_step_id']=target['id']
   self._finish_action(state,run,session,identity,'skip',request['expected_revision'],current['id'],from_status,run['status'],step_from,'skipped')
   state['console_messages'].append(encode(Message(id=str(uuid5(NAMESPACE_URL,identity+'/run-message')),project_id=project,session_id=session['id'],role='system',text='已明确跳过运行步骤（不会自动采纳或执行）',refs=(),created_at=utc_now())));return state,None
  self.repository.atomic(project,operation,identity_claim=('console_run_actions','operation_id',identity));return self.describe_run(project,run_id)
 def list(self,project):
  state=self.service.get(project);sessions=[]
  for session in state.get('console_sessions',[]):
   messages=[v for v in state.get('console_messages',[]) if v['session_id']==session['id']];plan=next((v for v in state.get('console_plans',[]) if v['session_id']==session['id']),None)
   sessions.append(dict(session,last_message=messages[-1]['text'] if messages else '',message_count=len(messages),step_count=len(plan['steps']) if plan else 0))
  return dict(revision=state['revision'],sessions=sessions)
 def create(self,project,request):
  check_fields(request,{'operation_id','title'});require(set(request)=={'operation_id','title'} and type(request['title']) is str and 0<len(request['title'].strip())<=200,'控制台会话标题无效');identity=uuid_value(request['operation_id'])
  def operation(state):
   upgrade(state);existing=next((v for v in state['console_sessions'] if v['id']==str(uuid5(NAMESPACE_URL,identity+'/session'))),None)
   if existing:return None,deepcopy(existing)
   now=utc_now();session=Session(id=str(uuid5(NAMESPACE_URL,identity+'/session')),project_id=project,title=request['title'].strip(),archived=False,created_at=now,updated_at=now);state['console_sessions'].append(encode(session));plan=Plan(id=str(uuid5(NAMESPACE_URL,identity+'/plan')),project_id=project,session_id=session.id,revision=1,steps=(),updated_at=now);state['console_plans'].append(encode(plan));return state,encode(session)
  return self.repository.atomic(project,operation)
 def rename(self,project,request):
  check_fields(request,{'session_id','title'});require(set(request)=={'session_id','title'} and type(request['title']) is str and 0<len(request['title'].strip())<=200,'会话标题无效')
  def operation(state):
   session=next((v for v in state['console_sessions'] if v['id']==request['session_id']),None);require(session is not None,'会话不存在');session['title']=request['title'].strip();session['updated_at']=utc_now();return state,deepcopy(session)
  return self.repository.atomic(project,operation)
 @serialized
 def archive(self,project,request):
  check_fields(request,{'session_id','archived'});require(set(request)=={'session_id','archived'} and type(request['archived']) is bool,'会话归档参数无效')
  def operation(state):
   session=next((v for v in state['console_sessions'] if v['id']==request['session_id']),None);require(session is not None,'会话不存在');session['archived']=request['archived'];session['updated_at']=utc_now();return state,deepcopy(session)
  return self.repository.atomic(project,operation)
 def append_message(self,project,request):
  base={'operation_id','session_id','role','text'};check_fields(request,base|{'refs'});require(set(request) in (base,base|{'refs'}),'消息字段缺失');identity=uuid_value(request['operation_id'])
  require(request['role'] in ('author','system','assistant','result') and type(request['text']) is str and len(request['text'])<=50000,'消息角色或文字无效')
  refs=[Ref(kind=v.get('kind'),id=v.get('id')) for v in request.get('refs',[])] if type(request.get('refs',[])) is list else None;require(refs is not None and len(refs)<=50,'消息引用无效')
  def operation(state):
   upgrade(state);old=next((v for v in state['console_messages'] if v['id']==str(uuid5(NAMESPACE_URL,identity+'/message'))),None)
   if old:require(old['session_id']==request['session_id'] and old['text']==request['text'],'消息身份冲突');return None,deepcopy(old)
   session=next((v for v in state['console_sessions'] if v['id']==request['session_id']),None);require(session is not None,'会话不存在');require(not session['archived'],'归档会话不能新增消息')
   message=Message(id=str(uuid5(NAMESPACE_URL,identity+'/message')),project_id=project,session_id=request['session_id'],role=request['role'],text=request['text'],refs=tuple(refs),created_at=utc_now());state['console_messages'].append(encode(message));session['updated_at']=message.created_at;return state,encode(message)
  return self.repository.atomic(project,operation)
 @serialized
 def save_plan(self,project,request):
  fields={'session_id','steps'};check_fields(request,fields|{'expected_plan_revision','candidate_id'});require(fields<=set(request) and type(request['steps']) is list and len(request['steps'])<=100,'计划步骤无效')
  if 'expected_plan_revision' in request:require(type(request['expected_plan_revision']) is int and request['expected_plan_revision']>=1,'计划版本非法')
  def operation(state):
   upgrade(state);plan=next((v for v in state['console_plans'] if v['session_id']==request['session_id']),None);require(plan is not None,'会话计划不存在')
   require('expected_plan_revision' not in request or plan['revision']==request['expected_plan_revision'],'计划已被修改，请刷新后重新编辑')
   session=next((v for v in state['console_sessions'] if v['id']==request['session_id']),None);require(session is not None and not session['archived'],'会话不存在或已归档')
   from novel_writer.domain.chapter_trash import hidden_ids
   hidden=hidden_ids(state);chapters={v['id'] for v in state['document']['chapters']};steps=[]
   for raw in request['steps']:
    require(type(raw) is dict and set(raw)=={'id','type','chapter_id','instruction','status','scene_order','selection_start','selection_end'},'步骤字段缺失或含未知字段')
    registered(raw['type']);step=Step(**deepcopy(raw));require(step.type in STEP_TYPES and step.chapter_id in chapters and step.chapter_id not in hidden,'未知步骤类型或目标章节/目标已归档或移入回收站');steps.append(step)
   if any(v.type in READ_ONLY for v in steps):
    from novel_writer.application.chapter_lifecycle import upgrade as upgrade_latest
    upgrade_latest(state);state.setdefault('rule_task_bindings',[]);state['workspace_version']=max(state['workspace_version'],39)
   # Dispatched steps remain immutable anchors for append-only task/result history.
   linked={v['step_id'] for v in state['console_dispatches'] if v['session_id']==request['session_id']}
   frozen={v['plan_step_id'] for v in state.get('console_run_steps',[]) if any(r['id']==v['run_id'] and r['session_id']==request['session_id'] for r in state.get('console_runs',[]))}
   by_id={v.id:encode(v) for v in steps}
   for old in plan['steps']:
    if old['id'] in linked|frozen:require(old['id'] in by_id,'已有运行/派发的步骤不可删除；可编辑计划使旧运行失效，历史保留')
   if request.get('candidate_id'):
    task,candidate=self._dialogue_candidate(state,request['session_id'],request['candidate_id'])
    state['console_messages'].append(encode(Message(id=str(uuid4()),project_id=project,session_id=request['session_id'],role='system',text='作者已编辑并保存关联候选的计划；候选不是正式内容，执行及采纳仍须分别确认。',refs=(Ref(kind='task',id=task['id']),Ref(kind='candidate',id=candidate['id'])),created_at=utc_now())))
   require(len({v.id for v in steps})==len(steps),'步骤身份重复');plan['steps']=[encode(v) for v in steps];plan['revision']+=1;plan['updated_at']=utc_now();session['updated_at']=plan['updated_at'];return state,deepcopy(plan)
  return self.repository.atomic(project,operation)
 def describe(self,project,identifier):
  state=self.service.get(project);session=next((v for v in state.get('console_sessions',[]) if v['id']==identifier),None);require(session is not None,'会话不存在')
  messages=[deepcopy(v) for v in state.get('console_messages',[]) if v['session_id']==identifier];plan=next((deepcopy(v) for v in state.get('console_plans',[]) if v['session_id']==identifier),None)
  dispatches=[self._dispatch_view(project,item) for item in state.get('console_dispatches',[]) if item['session_id']==identifier]
  return dict(revision=state['revision'],session=deepcopy(session),messages=messages,plan=plan,dispatches=dispatches,tools=catalogue(),usage=usage_summary(dispatches))
 def _dialogue_candidate(self,state,session_id,candidate_id):
  uuid_value(candidate_id);tasks={ref['id'] for v in state.get('console_messages',[]) if v['session_id']==session_id for ref in v['refs'] if ref['kind']=='task'}
  candidate=next((v for v in state.get('book_ai_candidates',[]) if v['id']==candidate_id),None)
  require(candidate is not None and candidate['task_id'] in tasks,'候选不存在或不属于当前会话')
  task=next((v for v in state.get('book_ai_tasks',[]) if v['id']==candidate['task_id'] and v['step']=='dialogue'),None);require(task is not None,'不是自然大纲对话候选');return task,candidate
 def preview_plan(self,project,request):
  fields={'session_id','proposal'};check_fields(request,fields);require(set(request)==fields and type(request['proposal']) is dict and set(request['proposal'])=={'steps'},'工具计划仅接受 steps 数据；不能携带脚本、命令、URL或许可')
  state=self.service.get(project);session=self._session(state,request['session_id']);require(not session['archived'],'归档会话不能导入计划');proposal=request['proposal']['steps'];require(type(proposal) is list and 0<len(proposal)<=100,'工具计划须包含1至100步')
  from novel_writer.domain.chapter_trash import hidden_ids
  chapters={v['id'] for v in state['document']['chapters']}-hidden_ids(state);steps=[]
  for value in proposal:
   require(type(value) is dict and set(value)=={'tool','arguments'},'模型步骤字段不可信：仅接受 tool 和 arguments')
   registered(value['tool']);args=value['arguments'];require(type(args) is dict and {'chapter_id','instruction'}<=set(args),'工具参数必须包含章节与纯文本指令')
   allowed={'chapter_id','instruction'}|({'scene_order'} if value['tool']=='scene' else {'selection_start','selection_end'} if value['tool']=='selection' else set())
   require(set(args)==allowed,'工具参数不符合注册schema；额外参数/权限不允许')
   step=Step(id=str(uuid4()),type=value['tool'],chapter_id=args['chapter_id'],instruction=args['instruction'],status='planned',scene_order=args.get('scene_order'),selection_start=args.get('selection_start'),selection_end=args.get('selection_end'));require(step.chapter_id in chapters,'工具目标不属于本书或已归档');steps.append(encode(step))
  return dict(revision=state['revision'],steps=steps,tools=catalogue(),notice='仅为不可信提案预览。请编辑并显式保存计划；没有执行、付费或采纳许可。')
 def candidate_plan(self,project,request):
  fields={'session_id','candidate_id','chapter_id'};check_fields(request,fields);require(set(request)==fields,'候选计划参数缺失')
  state=self.service.get(project);task,candidate=self._dialogue_candidate(state,request['session_id'],request['candidate_id'])
  # Deterministic suggestion from a validated candidate, not model-supplied commands.
  proposal=dict(steps=[dict(tool=kind,arguments=dict(chapter_id=request['chapter_id'],instruction=instruction)) for kind,instruction in (('chapter.inspect','读取目标章节的已保存状态'),('context.preview','预览已保存资料与来源'),('outline','参考本会话大纲候选，准备章节细纲；正式内容仍须人工采纳。'))])
  return dict(self.preview_plan(project,dict(session_id=request['session_id'],proposal=proposal)),candidate_id=candidate['id'],task_id=task['id'])
 def _prepare_step(self,state,session,step,operation,project=None):
  tool=registered(step['type']);require(tool['permission']=='prepare_only','只读工具须通过受控运行推进，不派发模型任务')
  project=project or session['project_id']
  chapters={v['id']:v for v in state['document']['chapters']};chapter=chapters.get(step['chapter_id']);require(chapter is not None,'步骤目标章节不存在')
  from novel_writer.domain.chapter_trash import hidden_ids
  require(chapter['id'] not in hidden_ids(state),'步骤目标章节已归档或移入回收站')
  characters=[v['id'] for v in state['document']['characters']];require(characters,'步骤需要至少一位本书人物')
  request_id=str(uuid5(NAMESPACE_URL,operation+'/request'));kind=step['type']
  if kind in ('idea','outline'):
   source=dict(chapter_id=chapter['id'],mode='brainstorm' if kind=='idea' else 'outline',instruction=step['instruction'],character_ids=characters,include_worldbuilding=True,include_writing_rules=True,include_facts=True,include_locations=True,context_budget_chars=20000)
   preview=self.planning.preview(project,source);prepared=self.planning.prepare(project,dict(operation_id=request_id,source_options=source,source_sha256=preview['source_sha256'],model_options=None,max_output_chars=12000,timeout_ms=30000));return 'chapter_planning',prepared['task']['id']
  if kind in ('draft','continue'):
   source=dict(chapter_id=chapter['id'],mode=kind,context_options=dict(chapter_id=chapter['id'],budget_chars=20000,include_current_plan=True,include_writing_rules=True,include_characters=True,include_worldbuilding=True,include_memories=True),instruction=step['instruction'],target_chars=2000,required_literals=[],forbidden_literals=[])
   preview=self.writing.preview(project,source);prepared=self.writing.prepare(project,dict(request_id=request_id,source_options=source,source_sha256=preview['source_sha256'],model_options=None,max_output_chars=20000,timeout_ms=30000,retry_of=None));return 'chapter_writing',prepared['task']['id']
  source=dict(chapter_id=chapter['id'],target_kind=kind,scene_order=step['scene_order'] if kind=='scene' else None,selection_start=step['selection_start'] if kind=='selection' else None,selection_end=step['selection_end'] if kind=='selection' else None,instruction=step['instruction'],target_chars=600,character_ids=characters,include_worldbuilding=True,include_writing_rules=True,include_facts=True,context_budget_chars=20000)
  preview=self.expansion.preview(project,source);prepared=self.expansion.prepare(project,dict(operation_id=request_id,source_options=source,source_sha256=preview['source_sha256'],model_options=None,max_output_chars=20000,timeout_ms=30000));return 'scene_expansion',prepared['task']['id']
 @serialized
 def dispatch(self,project,request):
  check_fields(request,{'operation_id','session_id','step_id'});require(set(request)=={'operation_id','session_id','step_id'},'派发字段缺失');identity=uuid_value(request['operation_id'])
  state=self.service.get(project);session=next((v for v in state.get('console_sessions',[]) if v['id']==request['session_id']),None);require(session is not None and not session['archived'],'会话不存在或已归档');plan=next((v for v in state.get('console_plans',[]) if v['session_id']==session['id']),None);require(plan is not None,'会话计划不存在');step=next((v for v in plan['steps'] if v['id']==request['step_id']),None);require(step is not None,'计划步骤不存在')
  existing=next((v for v in state.get('console_dispatches',[]) if v['session_id']==session['id'] and v['step_id']==step['id']),None)
  if existing:return self.describe(project,session['id'])
  engine,task_id=self._prepare_step(state,session,step,str(uuid5(NAMESPACE_URL,session['id']+'/prepare/'+step['id'])),project)
  dispatch_id=str(uuid5(NAMESPACE_URL,identity+'/dispatch'));message_id=str(uuid5(NAMESPACE_URL,identity+'/message'))
  def operation(current):
   upgrade(current);old=next((v for v in current['console_dispatches'] if v['id']==dispatch_id),None)
   if old:return None,None
   current_plan=next(v for v in current['console_plans'] if v['session_id']==session['id']);current_step=next((v for v in current_plan['steps'] if v['id']==step['id']),None);require(current_step is not None,'计划步骤已变化')
   current['console_dispatches'].append(encode(Dispatch(id=dispatch_id,project_id=project,session_id=session['id'],step_id=step['id'],engine=engine,task_id=task_id,created_at=utc_now())))
   current_step['status']='prepared';current_session=next(v for v in current['console_sessions'] if v['id']==session['id']);current_session['updated_at']=utc_now()
   current['console_messages'].append(encode(Message(id=message_id,project_id=project,session_id=session['id'],role='system',text='已准备任务（未执行）：'+step['type'],refs=(Ref(kind='task',id=task_id),),created_at=utc_now())))
   return current,True
  self.repository.atomic(project,operation)
  return self.describe(project,session['id'])
