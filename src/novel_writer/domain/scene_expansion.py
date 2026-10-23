"""V18 exact-range prose expansion for one outline scene or body selection."""
from novel_writer.domain.sampling import Sampling
from dataclasses import dataclass
from typing import Literal
import math,re
from novel_writer.domain.tasks import check_types,parse,encode,require,uuid_value,digest
from novel_writer.domain.models import _timestamp
from novel_writer.domain.book_ai import BookDestination
from novel_writer.domain.book_creation import fingerprint
from novel_writer.domain.chapter_planning import CharacterGuard,FactGuard,StyleGuard,OutlineGuard,SceneGuard
from novel_writer.domain.model_contract import ProviderResponse

TARGETS=('scene','selection')
SHA=re.compile('[0-9a-f]{64}')

class Value:
 def __post_init__(self):
  check_types(type(self),self)
  if hasattr(self,'id'):uuid_value(self.id)
  if hasattr(self,'project_id'):require(type(self.project_id) is str and bool(self.project_id.strip()),'scene_expansion.invalid_project')
  if hasattr(self,'created_at'):_timestamp(self.created_at,'scene_expansion.created_at')
  for name in ('source_sha256','body_sha256','selected_sha256','outline_sha256','idea_sha256','data_sha256','review_sha256','configuration_stamp','context_sha256','request_sha256'):
   if hasattr(self,name) and getattr(self,name) is not None:require(SHA.fullmatch(getattr(self,name)) is not None,'scene_expansion.invalid_hash')

@dataclass(frozen=True,kw_only=True)
class ExpansionGuard(Value):
 chapter_id:str
 chapter_number:int
 chapter_title:str
 chapter_status:str
 chapter_version_id:str|None
 body_sha256:str
 body_chars:int
 selection_start:int
 selection_end:int
 selected_sha256:str
 target_kind:Literal['scene','selection']
 scene:SceneGuard|None
 outline:OutlineGuard|None
 outline_version_id:str|None
 outline_sha256:str
 idea_sha256:str
 characters:tuple[CharacterGuard,...]
 known_character_ids:tuple[str,...]
 worldbuilding:str
 writing_rules:str
 facts:tuple[FactGuard,...]
 style:StyleGuard|None
 locks_sha256:str
 rule_sources:tuple[dict,...]|None=None

@dataclass(frozen=True,kw_only=True)
class ExpansionBinding(Value):
 adapter_id:Literal['scene-expansion-http-v1']
 source_adapter_id:Literal['chat-completions-http-v1','configured-http-v2']
 connection_id:str
 model_id:str
 temperature:float
 max_tokens:int
 budget_limit:float
 allow_unknown_cost:bool
 prompt_version:Literal['chapter-expand-1']
 destination:BookDestination
 configuration_stamp:str
 request_body:str
 request_sha256:str
 sampling:Sampling|None=None

 def __post_init__(self):
  super().__post_init__()
  from novel_writer.domain.sampling import validate_body
  validate_body(self.request_body,self.destination.protocol,self.sampling)
  require(self.connection_id==self.destination.connection_id and 0<len(self.model_id)<=200 and all(ord(c)>=32 for c in self.model_id),'scene_expansion.invalid_input')
  require(math.isfinite(self.temperature) and 0<=self.temperature<=2 and 128<=self.max_tokens<=8192 and math.isfinite(self.budget_limit) and 0<self.budget_limit<=10000 and self.allow_unknown_cost,'scene_expansion.unknown_cost_required')
  require(len(self.request_body.encode('utf-8'))<=2000000 and len(self.configuration_stamp)==64,'scene_expansion.invalid_request')
  from novel_writer.domain.book_ai import request_digest
  require(self.request_sha256==request_digest(self.request_body,self.destination,self.configuration_stamp),'scene_expansion.invalid_request_hash')

@dataclass(frozen=True,kw_only=True)
class ExpansionTask(Value):
 id:str
 request_id:str
 preparation_sha256:str
 project_id:str
 chapter_id:str
 target_kind:Literal['scene','selection']
 scene_order:int|None
 selection_start:int
 selection_end:int
 preset_version_id:str|None
 selection_source:Literal['preset','override']
 owner_id:str
 source_options:dict
 source_guard:ExpansionGuard
 source_sha256:str
 original_text:str
 context_text:str
 context_sha256:str
 binding:ExpansionBinding
 instruction:str
 max_output_chars:int
 timeout_ms:int
 budget_max_calls:int
 budget_max_output_tokens:int
 created_at:str
 def __post_init__(self):
  super().__post_init__()
  for value in (self.request_id,self.owner_id):uuid_value(value)
  require(self.target_kind in TARGETS and self.source_sha256==fingerprint(self.source_guard),'scene_expansion.invalid_source')
  require(digest(self.original_text)==self.source_guard.body_sha256 and len(self.original_text)==self.source_guard.body_chars,'scene_expansion.invalid_body')
  require(len(self.context_text)<=200000 and digest(self.context_text)==self.context_sha256 and type(self.source_options.get('character_ids')) is list and 1<=len(self.source_options['character_ids'])<=50,'scene_expansion.invalid_context')
  require(1<=self.budget_max_calls<=10 and 128<=self.budget_max_output_tokens<=81920 and 64<=self.max_output_chars<=100000 and 100<=self.timeout_ms<=30000,'scene_expansion.invalid_limits')
  if self.target_kind=='scene':
   require(isinstance(self.scene_order,int) and self.selection_start==self.selection_end==len(self.original_text) and self.source_guard.scene is not None and self.source_guard.scene.order==self.scene_order,'scene_expansion.invalid_scene_target')
  else:require(self.scene_order is None and 0<=self.selection_start<self.selection_end<=len(self.original_text) and self.source_guard.scene is None,'scene_expansion.invalid_selection')

@dataclass(frozen=True,kw_only=True)
class ExpansionEvent(Value):
 id:str
 task_id:str
 previous_event_id:str|None
 kind:Literal['prepared','started','completed','cancelled','candidate_corrected','adopted','response_recorded']
 status:Literal['pending','running','succeeded','failed','cancelled','interrupted']
 attempt_id:str|None
 owner_id:str
 response_id:str|None
 candidate_id:str|None
 error_code:str|None
 created_at:str

@dataclass(frozen=True,kw_only=True)
class ExpansionResult(Value):
 id:str
 project_id:str
 task_id:str
 attempt_id:str
 response:ProviderResponse
 created_at:str

@dataclass(frozen=True,kw_only=True)
class ExpansionCandidate(Value):
 id:str
 project_id:str
 task_id:str
 response_id:str
 operation_id:str
 revision:int
 previous_candidate_id:str|None
 origin:Literal['model','manual_correction']
 text:str
 data_sha256:str
 created_at:str
 def __post_init__(self):
  super().__post_init__()
  uuid_value(self.operation_id)
  require(0<len(self.text)<=100000 and self.data_sha256==digest(self.text),'scene_expansion.invalid_candidate')

@dataclass(frozen=True,kw_only=True)
class ExpansionReview(Value):
 id:str
 project_id:str
 operation_id:str
 task_id:str
 candidate_id:str
 candidate_sha256:str
 source_sha256:str
 document_revision:int
 owner_id:str
 before_text:str
 after_text:str
 selected_before:str
 selected_after:str
 created_at:str
 review_sha256:str

@dataclass(frozen=True,kw_only=True)
class ExpansionAdoption(Value):
 id:str
 project_id:str
 task_id:str
 candidate_id:str
 review_id:str
 operation_id:str
 request_sha256:str
 expected_revision:int
 confirm_chapter:bool
 authorize_confirmed:bool
 selected_start:int
 selected_end:int
 replacement:str
 version_before:str|None
 version_after:str
 applied_revision:int
 created_at:str

@dataclass(frozen=True,kw_only=True)
class ExpansionLateResult(Value):
 id:str
 project_id:str
 task_id:str
 attempt_id:str
 terminal_status:Literal['failed','cancelled','interrupted']
 response:ProviderResponse
 created_at:str

@dataclass(frozen=True,kw_only=True)
class ExpansionAdapterCall:
 task_id:str
 attempt_id:str
 capability:Literal['expand_scene_selection']
 task:ExpansionTask
 request_sha256:str
 confirmed:bool
 def __post_init__(self):
  uuid_value(self.task_id);uuid_value(self.attempt_id)
  require(self.capability=='expand_scene_selection' and type(self.task) is ExpansionTask and self.confirmed is True and self.request_sha256==self.task.binding.request_sha256,'scene_expansion.invalid_call')

COLLECTIONS={
 'scene_expansion_tasks':ExpansionTask,
 'scene_expansion_events':ExpansionEvent,
 'scene_expansion_results':ExpansionResult,
 'scene_expansion_candidates':ExpansionCandidate,
 'scene_expansion_reviews':ExpansionReview,
 'scene_expansion_adoptions':ExpansionAdoption,
 'scene_expansion_late_results':ExpansionLateResult,
}

def review_digest(value):
 body={key:value[key] for key in ('id','project_id','operation_id','task_id','candidate_id','candidate_sha256','source_sha256','document_revision','owner_id','before_text','after_text','selected_before','selected_after','created_at')}
 return fingerprint(body)

def _rows(state,name,model):return [parse(model,v) for v in state.get(name,[])]

def validate_state(state):
 document=state['document'];chapters={v['id']:v for v in document['chapters']};characters={v['id'] for v in document['characters']}
 tasks={};attempts={};statuses={}
 for name,model in COLLECTIONS.items():
  require(type(state[name]) is list and len(state[name])<=100000,'scene_expansion.invalid_collection');values=_rows(state,name,model)
  require(len({v.id for v in values})==len(values),'scene_expansion.duplicate_id')
  if name=='scene_expansion_tasks':
   for value in values:
    require(value.chapter_id in chapters and value.project_id==document['project']['id'],'scene_expansion.invalid_chapter')
    require(set(value.source_guard.known_character_ids)<=characters,'scene_expansion.unknown_character')
    tasks[value.id]=value
   require(len({v.request_id for v in values})==len(values),'scene_expansion.duplicate_request')
  elif name=='scene_expansion_events':
   for value in values:
    require(value.task_id in tasks,'scene_expansion.orphan_event')
    if value.kind=='started':attempts[value.task_id]=value.attempt_id
    statuses[value.task_id]=value.status
  elif name=='scene_expansion_results':
   for value in values:require(value.task_id in tasks,'scene_expansion.orphan_result')
  elif name=='scene_expansion_candidates':
   for value in values:
    task=tasks.get(value.task_id);require(task is not None and len(value.text)<=task.max_output_chars,'scene_expansion.orphan_candidate')
  elif name=='scene_expansion_reviews':
   for value in values:require(value.task_id in tasks and value.review_sha256==review_digest(encode(value)),'scene_expansion.orphan_review')
  elif name=='scene_expansion_adoptions':
   for value in values:
    require(value.task_id in tasks and value.expected_revision>=1 and value.confirm_chapter is True,'scene_expansion.orphan_adoption')
  elif name=='scene_expansion_late_results':
   for value in values:require(value.task_id in tasks and attempts.get(value.task_id)==value.attempt_id and statuses.get(value.task_id) in ('failed','cancelled','interrupted'),'scene_expansion.orphan_late')

def validate_transition(state,previous):
 validate_state(state)
 for name in COLLECTIONS:
  old=(previous or {}).get(name,[])
  require(state[name][:len(old)]==old,'scene_expansion.history_append_only')
