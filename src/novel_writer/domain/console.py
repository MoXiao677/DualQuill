"""Persistent creative console: sessions, plans, and explicit V24 runs."""
from dataclasses import dataclass
from typing import Literal
from novel_writer.domain.tasks import check_types,parse,encode,require,uuid_value
from novel_writer.domain.models import _timestamp

STEP_TYPES=('idea','outline','draft','continue','scene','selection','chapter.inspect','context.preview')
READ_ONLY_TYPES=('chapter.inspect','context.preview')
STEP_STATUS=('planned','prepared','failed')
ENGINES=('chapter_planning','chapter_writing','scene_expansion')
ROLES=('author','system','assistant','result')
RUN_STATUS=('running','paused','cancelled','completed')
RUN_STEP_STATUS=('queued','prepared','awaiting_confirmation','awaiting_adoption','completed','blocked','skipped','cancelled','failed')
RUN_ACTIONS=('start','advance','pause','resume','cancel','skip')
TERMINAL_RUN_STATUS=('cancelled','completed')
TERMINAL_RUN_STEP_STATUS=('completed','skipped','cancelled')

class Value:
 def __post_init__(self):
  check_types(type(self),self)
  if hasattr(self,'id'):uuid_value(self.id)
  if hasattr(self,'project_id'):require(type(self.project_id) is str and bool(self.project_id.strip()),'console.invalid_project')
  if hasattr(self,'created_at'):_timestamp(self.created_at,'console.created_at')

@dataclass(frozen=True,kw_only=True)
class Ref(Value):
 kind:Literal['task','candidate','receipt','session','step']
 id:str
 def __post_init__(self):
  super().__post_init__();uuid_value(self.id)

@dataclass(frozen=True,kw_only=True)
class Session(Value):
 id:str
 project_id:str
 title:str
 archived:bool
 created_at:str
 updated_at:str
 def __post_init__(self):
  super().__post_init__();require(0<len(self.title.strip())<=200,'console.invalid_title')

@dataclass(frozen=True,kw_only=True)
class Message(Value):
 id:str
 project_id:str
 session_id:str
 role:Literal['author','system','assistant','result']
 text:str
 refs:tuple[Ref,...]
 created_at:str
 def __post_init__(self):
  super().__post_init__();uuid_value(self.session_id);require(self.role in ROLES and type(self.text) is str and len(self.text)<=50000,'console.invalid_message')

@dataclass(frozen=True,kw_only=True)
class Step(Value):
 id:str
 type:Literal['idea','outline','draft','continue','scene','selection','chapter.inspect','context.preview']
 chapter_id:str
 instruction:str
 status:Literal['planned','prepared','failed']
 scene_order:int|None
 selection_start:int|None
 selection_end:int|None
 def __post_init__(self):
  super().__post_init__();uuid_value(self.chapter_id);require(self.type in STEP_TYPES and self.status in STEP_STATUS and type(self.instruction) is str and len(self.instruction)<=3000,'console.invalid_step')
  if self.type=='scene':require(type(self.scene_order) is int and self.scene_order>=1 and self.selection_start is None and self.selection_end is None,'console.invalid_step')
  elif self.type=='selection':require(self.scene_order is None and type(self.selection_start) is int and type(self.selection_end) is int and self.selection_start>=0 and self.selection_start<self.selection_end,'console.invalid_step')
  else:require(self.scene_order is None and self.selection_start is None and self.selection_end is None,'console.invalid_step')

@dataclass(frozen=True,kw_only=True)
class Plan(Value):
 id:str
 project_id:str
 session_id:str
 revision:int
 steps:tuple[Step,...]
 updated_at:str
 def __post_init__(self):
  super().__post_init__();uuid_value(self.session_id);require(self.revision>=1 and len(self.steps)<=100 and len({v.id for v in self.steps})==len(self.steps),'console.invalid_plan')

@dataclass(frozen=True,kw_only=True)
class Dispatch(Value):
 id:str
 project_id:str
 session_id:str
 step_id:str
 engine:Literal['chapter_planning','chapter_writing','scene_expansion']
 task_id:str
 created_at:str
 def __post_init__(self):
  super().__post_init__();uuid_value(self.session_id);uuid_value(self.step_id);uuid_value(self.task_id);require(self.engine in ENGINES,'console.invalid_dispatch')

@dataclass(frozen=True,kw_only=True)
class RunStep(Value):
 id:str
 project_id:str
 run_id:str
 plan_step_id:str
 position:int
 type:Literal['idea','outline','draft','continue','scene','selection','chapter.inspect','context.preview']
 chapter_id:str
 instruction:str
 scene_order:int|None
 selection_start:int|None
 selection_end:int|None
 status:Literal['queued','prepared','awaiting_confirmation','awaiting_adoption','completed','blocked','skipped','cancelled','failed']
 dispatch_id:str|None
 engine:Literal['chapter_planning','chapter_writing','scene_expansion']|None
 task_id:str|None
 blocked_reason:str|None
 created_at:str
 updated_at:str
 def __post_init__(self):
  super().__post_init__();uuid_value(self.run_id);uuid_value(self.plan_step_id);uuid_value(self.chapter_id)
  require(self.position>=0 and self.type in STEP_TYPES and self.status in RUN_STEP_STATUS,'console.invalid_run_step')
  require(type(self.instruction) is str and len(self.instruction)<=3000 and (self.blocked_reason is None or (type(self.blocked_reason) is str and len(self.blocked_reason)<=2000)),'console.invalid_run_step')
  if self.type=='scene':require(type(self.scene_order) is int and self.scene_order>=1 and self.selection_start is None and self.selection_end is None,'console.invalid_run_step')
  elif self.type=='selection':require(self.scene_order is None and type(self.selection_start) is int and type(self.selection_end) is int and self.selection_start>=0 and self.selection_start<self.selection_end,'console.invalid_run_step')
  else:require(self.scene_order is None and self.selection_start is None and self.selection_end is None,'console.invalid_run_step')
  require((self.dispatch_id is None)==(self.task_id is None)==(self.engine is None),'console.invalid_run_step')
  for value in (self.dispatch_id,self.task_id):
   if value is not None:uuid_value(value)
  if self.engine is not None:require(self.engine in ENGINES,'console.invalid_run_step')

@dataclass(frozen=True,kw_only=True)
class Run(Value):
 id:str
 project_id:str
 session_id:str
 plan_revision:int
 status:Literal['running','paused','cancelled','completed']
 current_step_id:str|None
 created_at:str
 updated_at:str
 def __post_init__(self):
  super().__post_init__();uuid_value(self.session_id);require(self.plan_revision>=1 and self.status in RUN_STATUS,'console.invalid_run')
  if self.current_step_id is not None:uuid_value(self.current_step_id)
  if self.status in TERMINAL_RUN_STATUS:require(self.current_step_id is None,'console.invalid_run')
  else:require(self.current_step_id is not None,'console.invalid_run')

@dataclass(frozen=True,kw_only=True)
class RunAction(Value):
 id:str
 project_id:str
 run_id:str
 operation_id:str
 action:Literal['start','advance','pause','resume','cancel','skip']
 expected_revision:int
 step_id:str|None
 from_status:str|None
 to_status:str|None
 step_from_status:str|None
 step_to_status:str|None
 created_at:str
 def __post_init__(self):
  super().__post_init__();uuid_value(self.run_id);uuid_value(self.operation_id);require(self.action in RUN_ACTIONS and self.expected_revision>=1,'console.invalid_run_action')
  if self.step_id is not None:uuid_value(self.step_id)
  require(self.from_status is None or self.from_status in RUN_STATUS,'console.invalid_run_action')
  require(self.to_status is None or self.to_status in RUN_STATUS,'console.invalid_run_action')
  require(self.step_from_status is None or self.step_from_status in RUN_STEP_STATUS,'console.invalid_run_action')
  require(self.step_to_status is None or self.step_to_status in RUN_STEP_STATUS,'console.invalid_run_action')

COLLECTIONS={
 'console_sessions':Session,
 'console_messages':Message,
 'console_plans':Plan,
 'console_dispatches':Dispatch,
}
RUN_COLLECTIONS={
 'console_runs':Run,
 'console_run_steps':RunStep,
 'console_run_actions':RunAction,
}

def validate_state(state):
 document=state['document'];project=document['project']['id'];chapters={v['id'] for v in document['chapters']}
 sessions={};messages=[];plans=[];dispatches=[]
 for name,model in COLLECTIONS.items():
  require(type(state[name]) is list and len(state[name])<=100000,'console.invalid_collection');parsed=[parse(model,v) for v in state[name]];require(len({v.id for v in parsed})==len(parsed),'console.duplicate_id')
  if name=='console_sessions':
   for value in parsed:require(value.project_id==project,'console.invalid_session');sessions[value.id]=value
  elif name=='console_messages':messages=parsed
  elif name=='console_plans':plans=parsed
  else:dispatches=parsed
 for message in messages:
  require(message.project_id==project and message.session_id in sessions and all(ref.id for ref in message.refs),'console.orphan_message')
 seen_plans=set()
 for plan in plans:
  require(plan.project_id==project and plan.session_id in sessions and plan.session_id not in seen_plans,'console.invalid_plan');seen_plans.add(plan.session_id)
  for step in plan.steps:
   require(step.chapter_id in chapters,'console.invalid_step')
   require(step.type not in READ_ONLY_TYPES or state['workspace_version']>=39,'只读工具计划需要 V39 工作区')
 step_by_session={plan.session_id:{step.id:step for step in plan.steps} for plan in plans}
 for item in dispatches:
  require(item.project_id==project and item.session_id in sessions and item.step_id in step_by_session.get(item.session_id,{}),'console.orphan_dispatch')
 if state.get('workspace_version',0)<24:
  require(not any(name in state for name in RUN_COLLECTIONS),'console.runs_require_v24');return
 runs=[];run_steps=[];run_actions=[]
 for name,model in RUN_COLLECTIONS.items():
  require(type(state[name]) is list and len(state[name])<=100000,'console.invalid_collection');parsed=[parse(model,v) for v in state[name]];require(len({v.id for v in parsed})==len(parsed),'console.duplicate_id')
  if name=='console_runs':runs=parsed
  elif name=='console_run_steps':run_steps=parsed
  else:run_actions=parsed
 run_by_id={}
 for run in runs:
  require(run.project_id==project and run.session_id in sessions and run.id not in run_by_id,'console.invalid_run');run_by_id[run.id]=run
 steps_by_run={}
 dispatch_by_id={v.id:v for v in dispatches}
 for step in run_steps:
  require(step.type not in READ_ONLY_TYPES or state['workspace_version']>=39,'只读工具运行需要 V39 工作区')
  run=run_by_id.get(step.run_id);require(run is not None and step.project_id==project and step.chapter_id in chapters and step.plan_step_id in step_by_session.get(run.session_id,{}),'console.orphan_run_step')
  steps_by_run.setdefault(step.run_id,[]).append(step)
  if step.dispatch_id is not None:
   dispatch=dispatch_by_id.get(step.dispatch_id);require(dispatch is not None and dispatch.project_id==project and dispatch.session_id==run.session_id and dispatch.step_id==step.plan_step_id and dispatch.engine==step.engine and dispatch.task_id==step.task_id,'console.orphan_run_step')
 for run in runs:
  steps=sorted(steps_by_run.get(run.id,[]),key=lambda value:value.position)
  require([value.position for value in steps]==list(range(len(steps))),'console.invalid_run_steps')
  require(run.current_step_id is None or any(value.id==run.current_step_id for value in steps),'console.invalid_run_cursor')
 operations=set()
 for action in run_actions:
  require(action.project_id==project and action.run_id in run_by_id and action.operation_id not in operations,'console.orphan_run_action');operations.add(action.operation_id)
  require(action.step_id is None or any(value.id==action.step_id and value.run_id==action.run_id for value in run_steps),'console.orphan_run_action')

def validate_transition(state,previous):
 validate_state(state);old=previous or {}
 old_sessions={v['id'] for v in old.get('console_sessions',[])};require(old_sessions<= {v['id'] for v in state['console_sessions']},'console.sessions_cannot_be_deleted')
 for name in ('console_messages','console_dispatches'):
  prior=old.get(name,[]);require(state[name][:len(prior)]==prior,'console.history_append_only')
 old_messages={v['id']:v for v in old.get('console_messages',[])}
 for item in state['console_messages'][:len(old.get('console_messages',[]))]:require(old_messages.get(item['id'])==item,'console.messages_immutable')
 if state['workspace_version']<24:return
 old_runs={v['id']:v for v in old.get('console_runs',[])};new_runs={v['id']:v for v in state['console_runs']}
 require(set(old_runs)<=set(new_runs),'console.runs_cannot_be_deleted')
 for identifier,old_run in old_runs.items():
  new_run=new_runs[identifier]
  for key in ('id','project_id','session_id','plan_revision','created_at'):require(old_run[key]==new_run[key],'console.run_binding_immutable')
  if old_run['status']!=new_run['status']:
   require(old_run['status'] not in TERMINAL_RUN_STATUS,'console.run_terminal_immutable')
   require(new_run['status'] in RUN_STATUS,'console.invalid_run_transition')
 old_steps={v['id']:v for v in old.get('console_run_steps',[])};new_steps={v['id']:v for v in state['console_run_steps']}
 require(set(old_steps)<=set(new_steps),'console.run_steps_cannot_be_deleted')
 for identifier,old_step in old_steps.items():
  new_step=new_steps[identifier]
  for key in ('id','project_id','run_id','plan_step_id','position','type','chapter_id','instruction','scene_order','selection_start','selection_end','created_at'):
   require(old_step[key]==new_step[key],'console.run_step_binding_immutable')
  for key in ('dispatch_id','engine','task_id'):
   if old_step[key] is not None:require(old_step[key]==new_step[key],'console.run_step_dispatch_immutable')
  if old_step['status']!=new_step['status']:require(old_step['status'] not in TERMINAL_RUN_STEP_STATUS,'console.run_step_terminal_immutable')
 old_actions=old.get('console_run_actions',[]);require(state['console_run_actions'][:len(old_actions)]==old_actions,'console.run_actions_append_only')
