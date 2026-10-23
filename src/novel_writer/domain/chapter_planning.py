"""V17 chapter-scoped model planning: IDEA brainstorm and chapter outline/scene beats.

Records are independent from manuscript writing.  Candidates are structured
JSON, but nothing becomes a saved IDEA or ChapterOutline until an explicit,
reviewed adoption.
"""
from novel_writer.domain.sampling import Sampling
from dataclasses import dataclass
from typing import Literal
import json
import math
import re
from novel_writer.domain.tasks import check_types, parse, encode, require, uuid_value, digest
from novel_writer.domain.models import _timestamp
from novel_writer.domain.book_ai import BookDestination
from novel_writer.domain.book_creation import fingerprint
from novel_writer.domain.connections import PROTOCOL_NAMES, validate_endpoint
from novel_writer.domain.model_contract import ProviderResponse

MODES=('brainstorm','outline')
FIELDS={'brainstorm':('idea',),'outline':('core_idea','objective','character_ids','scenes','story_time')}
SCENE_FIELDS=('order','summary','character_ids','location','story_time')
SHA=re.compile('[0-9a-f]{64}')

class Value:
 def __post_init__(self):
  check_types(type(self),self)
  if hasattr(self,'id'):uuid_value(self.id)
  if hasattr(self,'project_id'):require(type(self.project_id) is str and bool(self.project_id.strip()),'chapter_planning.invalid_project')
  if hasattr(self,'created_at'):_timestamp(self.created_at,'chapter_planning.created_at')
  for name in ('source_sha256','original_source_sha256','locks_sha256','request_sha256','candidate_sha256','data_sha256','review_sha256','configuration_stamp','context_sha256'):
   if hasattr(self,name):
    value=getattr(self,name)
    require(value is None or SHA.fullmatch(value) is not None,'chapter_planning.invalid_hash')

@dataclass(frozen=True,kw_only=True)
class CharacterGuard(Value):
 id:str
 name:str
 role:str
 personality:str
 background:str
 goals:tuple[str,...]
 notes:str

@dataclass(frozen=True,kw_only=True)
class SceneGuard(Value):
 order:int
 summary:str
 character_ids:tuple[str,...]
 location:str
 story_time:str

@dataclass(frozen=True,kw_only=True)
class OutlineGuard(Value):
 id:str|None
 version_id:str|None
 core_idea:str
 objective:str
 character_ids:tuple[str,...]
 scenes:tuple[SceneGuard,...]
 story_time:str
 status:str

@dataclass(frozen=True,kw_only=True)
class FactGuard(Value):
 id:str
 title:str
 text:str
 position_chapter_id:str
 position_number:int

@dataclass(frozen=True,kw_only=True)
class LocationGuard(Value):
 name:str
 chapter_id:str
 order:int

@dataclass(frozen=True,kw_only=True)
class StyleGuard(Value):
 id:str
 name:str
 prompt:str
 card_sha256:str

@dataclass(frozen=True,kw_only=True)
class ChapterSourceGuard(Value):
 project_id:str
 project_title:str
 project_genre:str
 project_summary:str
 project_language:str
 chapter_id:str
 chapter_number:int
 chapter_title:str
 chapter_status:str
 idea:str
 outline:OutlineGuard|None
 volume_number:int|None
 volume_title:str
 volume_summary:str
 book_outline:dict|None
 book_outline_sha256:str
 worldbuilding:str
 writing_rules:str
 characters:tuple[CharacterGuard,...]
 known_character_ids:tuple[str,...]
 locations:tuple[LocationGuard,...]
 facts:tuple[FactGuard,...]
 style:StyleGuard|None
 locks_sha256:str
 rule_sources:tuple[dict,...]|None=None

@dataclass(frozen=True,kw_only=True)
class PlanningBinding(Value):
 adapter_id:Literal['chapter-planning-http-v1']
 source_adapter_id:Literal['chat-completions-http-v1','configured-http-v2']
 connection_id:str
 model_id:str
 temperature:float
 max_tokens:int
 budget_limit:float
 allow_unknown_cost:bool
 prompt_version:Literal['chapter-idea-json-1','chapter-outline-json-1']
 destination:BookDestination
 configuration_stamp:str
 request_body:str
 request_sha256:str
 sampling:Sampling|None=None

 def __post_init__(self):
  super().__post_init__()
  from novel_writer.domain.sampling import validate_body
  validate_body(self.request_body,self.destination.protocol,self.sampling)
  require(self.connection_id==self.destination.connection_id and 0<len(self.model_id)<=200 and all(ord(c)>=32 for c in self.model_id),'chapter_planning.invalid_input')
  require(math.isfinite(self.temperature) and 0<=self.temperature<=2 and 128<=self.max_tokens<=8192 and math.isfinite(self.budget_limit) and 0<self.budget_limit<=10000 and self.allow_unknown_cost,'chapter_planning.unknown_cost_required')
  require(len(self.request_body.encode('utf-8'))<=2000000 and len(self.configuration_stamp)==64,'chapter_planning.invalid_request')
  from novel_writer.domain.book_ai import request_digest
  require(self.request_sha256==request_digest(self.request_body,self.destination,self.configuration_stamp),'chapter_planning.invalid_request_hash')

@dataclass(frozen=True,kw_only=True)
class PlanningTask(Value):
 id:str
 request_id:str
 preparation_sha256:str
 project_id:str
 chapter_id:str
 mode:Literal['brainstorm','outline']
 preset_step:Literal['brainstorm','outline']
 preset_version_id:str|None
 selection_source:Literal['preset','override']
 owner_id:str
 source_options:dict
 source_guard:ChapterSourceGuard
 source_sha256:str
 context_text:str
 context_sha256:str
 binding:PlanningBinding
 instruction:str
 max_output_chars:int
 timeout_ms:int
 budget_max_calls:int
 budget_max_output_tokens:int
 created_at:str
 def __post_init__(self):
  super().__post_init__()
  for value in (self.request_id,self.owner_id):uuid_value(value)
  require(self.mode in MODES and self.preset_step==self.mode and self.source_sha256==fingerprint(self.source_guard),'chapter_planning.invalid_source')
  require(digest(self.context_text)==self.context_sha256 and len(self.context_text)<=200000,'chapter_planning.invalid_context')
  require(1<=len(self.source_options.get('character_ids',[]))<=50 and type(self.source_options.get('instruction')) is str and len(self.source_options['instruction'])<=4000,'chapter_planning.invalid_options')
  require(1<=self.budget_max_calls<=10 and 128<=self.budget_max_output_tokens<=81920 and 128<=self.max_output_chars<=100000 and 100<=self.timeout_ms<=30000,'chapter_planning.invalid_limits')
  require((self.binding.prompt_version=='chapter-idea-json-1')==(self.mode=='brainstorm'),'chapter_planning.invalid_prompt')

@dataclass(frozen=True,kw_only=True)
class PlanningEvent(Value):
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
class PlanningResult(Value):
 id:str
 project_id:str
 task_id:str
 attempt_id:str
 response:ProviderResponse
 created_at:str

@dataclass(frozen=True,kw_only=True)
class PlanningCandidate(Value):
 id:str
 project_id:str
 task_id:str
 response_id:str
 operation_id:str
 revision:int
 previous_candidate_id:str|None
 origin:Literal['model','manual_correction']
 raw_text:str
 raw_sha256:str
 plan:dict|None
 errors:tuple[str,...]
 data_sha256:str
 created_at:str
 def __post_init__(self):
  super().__post_init__()
  uuid_value(self.operation_id)
  require(self.raw_sha256==digest(self.raw_text) and len(self.raw_text)<=100000 and len(self.errors)<=100,'chapter_planning.invalid_candidate')
  require((self.plan is None)==bool(self.errors),'chapter_planning.invalid_candidate')
  require(self.data_sha256==fingerprint(self.plan if self.plan is not None else dict(text=self.raw_text,errors=self.errors)),'chapter_planning.invalid_candidate')

@dataclass(frozen=True,kw_only=True)
class PlanningReview(Value):
 id:str
 project_id:str
 operation_id:str
 task_id:str
 candidate_id:str
 candidate_sha256:str
 mode:Literal['brainstorm','outline']
 source_sha256:str
 document_revision:int
 owner_id:str
 before:dict
 after:dict
 plan:dict|None
 created_at:str
 review_sha256:str

@dataclass(frozen=True,kw_only=True)
class PlanningAdoption(Value):
 id:str
 project_id:str
 task_id:str
 candidate_id:str
 review_id:str
 operation_id:str
 mode:Literal['brainstorm','outline']
 request_sha256:str
 expected_revision:int
 confirm_chapter:bool
 idea:str|None
 outline_id:str|None
 outline_version_id:str|None
 applied_revision:int
 created_at:str

@dataclass(frozen=True,kw_only=True)
class PlanningLateResult(Value):
 id:str
 project_id:str
 task_id:str
 attempt_id:str
 terminal_status:Literal['failed','cancelled','interrupted']
 response:ProviderResponse
 created_at:str

@dataclass(frozen=True,kw_only=True)
class PlanningAdapterCall:
 task_id:str
 attempt_id:str
 capability:Literal['brainstorm_chapter','outline_chapter']
 task:PlanningTask
 request_sha256:str
 confirmed:bool
 def __post_init__(self):
  uuid_value(self.task_id);uuid_value(self.attempt_id)
  require(self.capability in ('brainstorm_chapter','outline_chapter') and type(self.task) is PlanningTask and self.confirmed is True,'chapter_planning.invalid_call')
  require((self.capability=='brainstorm_chapter')==(self.task.mode=='brainstorm'),'chapter_planning.invalid_call')
  require(self.request_sha256==self.task.binding.request_sha256,'chapter_planning.invalid_call')

COLLECTIONS={
 'chapter_planning_tasks':PlanningTask,
 'chapter_planning_events':PlanningEvent,
 'chapter_planning_results':PlanningResult,
 'chapter_planning_candidates':PlanningCandidate,
 'chapter_planning_reviews':PlanningReview,
 'chapter_planning_adoptions':PlanningAdoption,
 'chapter_planning_late_results':PlanningLateResult,
}

def review_digest(value):
 body={key:value[key] for key in ('id','project_id','operation_id','task_id','candidate_id','candidate_sha256','mode','source_sha256','document_revision','owner_id','before','after','plan','created_at')}
 return fingerprint(body)

def validate_scenes(raw,known_character_ids):
 require(type(raw) is list and 1<=len(raw)<=50,'chapter_planning.scenes_required')
 scenes=[]
 for index,item in enumerate(raw):
  require(type(item) is dict and set(item)==set(SCENE_FIELDS),'chapter_planning.invalid_scene')
  require(type(item['order']) is int and item['order']==index+1,'chapter_planning.scene_order')
  require(type(item['summary']) is str and 0<len(item['summary'].strip())<=2000,'chapter_planning.invalid_scene')
  require(type(item['location']) is str and len(item['location'])<=200,'chapter_planning.invalid_scene')
  require(type(item['story_time']) is str and len(item['story_time'])<=200,'chapter_planning.invalid_scene')
  ids=item['character_ids'];require(type(ids) is list and len(ids)<=50,'chapter_planning.invalid_scene')
  require(all(type(v) is str and v in known_character_ids for v in ids),'chapter_planning.unknown_character')
  scenes.append(dict(order=item['order'],summary=item['summary'],character_ids=list(ids),location=item['location'],story_time=item['story_time']))
 return scenes

def parse_candidate(mode,text,known_character_ids):
 errors=[];plan=None
 try:
  from novel_writer.storage.json_codec import strict_json_loads
  value=strict_json_loads(text);require(type(value) is dict,'chapter_planning.object_required')
  allowed=set(FIELDS[mode]);errors.extend('unknown:'+key[:100] for key in sorted(set(value)-allowed));errors.extend('missing:'+key for key in sorted(allowed-set(value)))
  if not errors and mode=='brainstorm':
   require(type(value['idea']) is str and 0<len(value['idea'].strip())<=8000,'chapter_planning.invalid_idea')
   plan=dict(idea=value['idea'])
  elif not errors:
   require(type(value['core_idea']) is str and len(value['core_idea'])<=4000,'chapter_planning.invalid_outline')
   require(type(value['objective']) is str and len(value['objective'])<=4000,'chapter_planning.invalid_outline')
   require(type(value['story_time']) is str and len(value['story_time'])<=200,'chapter_planning.invalid_outline')
   ids=value['character_ids'];require(type(ids) is list and len(ids)<=50 and all(type(v) is str and v in known_character_ids for v in ids),'chapter_planning.unknown_character')
   plan=dict(core_idea=value['core_idea'],objective=value['objective'],character_ids=list(ids),scenes=validate_scenes(value['scenes'],known_character_ids),story_time=value['story_time'])
 except (ValueError,TypeError,KeyError,UnicodeError) as error:
  message=str(error)
  errors.append(message if message.startswith('chapter_planning.') else 'chapter_planning.invalid_json')
 return plan,tuple(errors[:100])

def validate_state(state):
 document=state['document'];chapters={v['id']:v for v in document['chapters']}
 characters={v['id'] for v in document['characters']}
 outlines={v['id']:v for v in document['chapter_outlines']}
 tasks={};attempts={};statuses={}
 for name,model in COLLECTIONS.items():
  require(type(state[name]) is list and len(state[name])<=100000,'chapter_planning.invalid_collection')
  values=[parse(model,v) for v in state[name]];require(len({v.id for v in values})==len(values),'chapter_planning.duplicate_id')
  if name=='chapter_planning_tasks':
   for value in values:
    require(value.chapter_id in chapters and value.project_id==state['document']['project']['id'],'chapter_planning.invalid_chapter')
    require(set(value.source_guard.known_character_ids)<=characters,'chapter_planning.unknown_character')
    tasks[value.id]=value
   require(len({v.request_id for v in values})==len(values),'chapter_planning.duplicate_request')
  elif name=='chapter_planning_events':
   for value in values:
    require(value.task_id in tasks,'chapter_planning.orphan_event')
    if value.kind=='started':attempts[value.task_id]=value.attempt_id
    statuses[value.task_id]=value.status
  elif name=='chapter_planning_results':
   for value in values:require(value.task_id in tasks and value.attempt_id is not None,'chapter_planning.orphan_result')
  elif name=='chapter_planning_candidates':
   for value in values:
    task=tasks.get(value.task_id);require(task is not None and value.response_id in {r.id for r in parse_results(state)},'chapter_planning.orphan_candidate')
    if value.plan is not None:
     if task.mode=='brainstorm':require(set(value.plan)=={'idea'} and type(value.plan['idea']) is str and bool(value.plan['idea'].strip()),'chapter_planning.invalid_candidate')
     else:
      require(set(value.plan)==set(FIELDS['outline']) and type(value.plan['core_idea']) is str and type(value.plan['objective']) is str and type(value.plan['story_time']) is str,'chapter_planning.invalid_candidate')
      ids=value.plan['character_ids'];require(type(ids) is list and all(v in task.source_guard.known_character_ids for v in ids),'chapter_planning.unknown_character');validate_scenes(value.plan['scenes'],task.source_guard.known_character_ids)
  elif name=='chapter_planning_reviews':
   for value in values:
    require(value.task_id in tasks and value.candidate_id in {c.id for c in parse_candidates(state)} and value.review_sha256==review_digest(encode(value)),'chapter_planning.orphan_review')
  elif name=='chapter_planning_adoptions':
   for value in values:
    require(value.task_id in tasks and value.review_id in {r.id for r in parse_reviews(state)} and value.candidate_id in {c.id for c in parse_candidates(state)},'chapter_planning.orphan_adoption')
    require(value.outline_id is None or value.outline_id in outlines,'chapter_planning.orphan_outline')
    candidate=next(c for c in parse_candidates(state) if c.id==value.candidate_id);review=next(r for r in parse_reviews(state) if r.id==value.review_id)
    require(value.request_sha256==fingerprint(dict(operation_id=value.operation_id,task_id=value.task_id,candidate_id=value.candidate_id,candidate_sha256=candidate.data_sha256,review_id=value.review_id,review_sha256=review.review_sha256,expected_revision=value.expected_revision,confirm_chapter=value.confirm_chapter)),'chapter_planning.invalid_adoption')
  elif name=='chapter_planning_late_results':
   for value in values:
    require(value.task_id in tasks and attempts.get(value.task_id)==value.attempt_id and statuses.get(value.task_id) in ('failed','cancelled','interrupted'),'chapter_planning.orphan_late')

def _parsed(state,name,model):return [parse(model,v) for v in state.get(name,[])]
def parse_results(state):return _parsed(state,'chapter_planning_results',PlanningResult)
def parse_candidates(state):return _parsed(state,'chapter_planning_candidates',PlanningCandidate)
def parse_reviews(state):return _parsed(state,'chapter_planning_reviews',PlanningReview)

def validate_transition(state,previous):
 validate_state(state)
 for name in COLLECTIONS:
  old=(previous or {}).get(name,[])
  require(state[name][:len(old)]==old,'chapter_planning.history_append_only')
