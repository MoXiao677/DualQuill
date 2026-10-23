"""V12 book-level model input, events, raw results and corrected planning candidates."""
from novel_writer.domain.sampling import Sampling
from dataclasses import dataclass
from typing import Literal
import json,math
from uuid import UUID
from novel_writer.domain.tasks import check_types,parse,encode,require,uuid_value,digest
from novel_writer.domain.models import _timestamp
from novel_writer.domain.book_creation import PlanData,STEPS,STEP_FIELDS,fingerprint
from novel_writer.domain.connections import validate_endpoint,PROTOCOL_NAMES
from novel_writer.domain.model_contract import ProviderResponse

def request_digest(body,destination,stamp):return fingerprint(dict(body=body,destination=encode(destination),configuration_stamp=stamp))
class Value:
 def __post_init__(self):
  check_types(type(self),self)
  if hasattr(self,'id'):uuid_value(self.id)
  if hasattr(self,'project_id'):require(bool(self.project_id.strip()),'book_ai.invalid_input')
  if hasattr(self,'created_at'):_timestamp(self.created_at,'book_ai.created_at')
  if isinstance(self,BookDestination):
   if self.connection_id not in ('gg','catie','odys'):uuid_value(self.connection_id)
   uuid_value(self.revision);require(self.protocol in PROTOCOL_NAMES,'book_ai.unsupported_protocol');validate_endpoint(self.base_url,allow_local=self.allow_local)
   require(self.stream_mode in ('json','sse'),'流式配置非法')
   require(self.sha256==fingerprint({key:value for key,value in encode(self).items() if key!='sha256'}),'book_ai.invalid_destination')
  elif isinstance(self,BookBinding):
   from novel_writer.domain.sampling import validate_body
   validate_body(self.request_body,self.destination.protocol,self.sampling)
   require(self.connection_id==self.destination.connection_id and 0<len(self.model_id)<=200 and all(ord(c)>=32 for c in self.model_id),'book_ai.invalid_input')
   require(math.isfinite(self.temperature) and 0<=self.temperature<=2 and 128<=self.max_tokens<=8192 and math.isfinite(self.budget_limit) and 0<self.budget_limit<=10000 and self.allow_unknown_cost,'book_ai.unknown_cost_required')
   require(len(self.request_body.encode('utf-8'))<=2000000 and len(self.configuration_stamp)==64 and self.request_sha256==request_digest(self.request_body,self.destination,self.configuration_stamp),'book_ai.invalid_request_hash')
  elif isinstance(self,BookTask):
   for value in (self.request_id,self.source_version_id,self.branch_id,self.owner_id):uuid_value(value)
   require((self.step in STEPS or self.step=='dialogue' and self.binding.prompt_version=='book-dialogue-json-1') and self.source_sha256==fingerprint(self.source_guard) and self.original_source_sha256==digest(self.original_source_json),'book_ai.invalid_source')
   require(128<=self.max_output_chars<=100000 and 100<=self.timeout_ms<=300000 and 1<=self.budget_max_calls<=10 and 128<=self.budget_max_output_tokens<=81920,'book_ai.invalid_limits')
  elif isinstance(self,BookCandidate):
   require(self.raw_sha256==digest(self.raw_text) and len(self.raw_text)<=100000 and len(self.errors)<=100,'book_ai.invalid_candidate')
   require((self.plan is None)==bool(self.errors),'book_ai.invalid_candidate');require(self.data_sha256==fingerprint(self.plan if self.plan is not None else dict(text=self.raw_text,errors=self.errors)),'book_ai.invalid_candidate')

@dataclass(frozen=True,kw_only=True)
class BookDestination(Value):
 connection_id:str
 revision:str
 protocol:str
 base_url:str
 allow_local:bool
 sha256:str
 stream_mode:Literal['json','sse']='json'
@dataclass(frozen=True,kw_only=True)
class BookBinding(Value):
 adapter_id:Literal['book-http-v1']
 source_adapter_id:Literal['chat-completions-http-v1','configured-http-v2']
 connection_id:str
 model_id:str
 temperature:float
 max_tokens:int
 budget_limit:float
 allow_unknown_cost:bool
 prompt_version:Literal['book-step-json-1','book-dialogue-json-1']
 destination:BookDestination
 configuration_stamp:str
 request_body:str
 request_sha256:str
 sampling:Sampling|None=None

@dataclass(frozen=True,kw_only=True)
class BookTask(Value):
 id:str
 request_id:str
 preparation_sha256:str
 project_id:str
 source_version_id:str
 branch_id:str
 step:str
 preset_step:Literal['brainstorm','outline']
 preset_version_id:str|None
 selection_source:Literal['preset','override']
 owner_id:str
 source_guard:PlanData
 source_sha256:str
 original_source_json:str
 original_source_sha256:str
 formal_sha256:str
 locks_sha256:str
 binding:BookBinding
 instruction:str
 max_output_chars:int
 timeout_ms:int
 budget_max_calls:int
 budget_max_output_tokens:int
 created_at:str
@dataclass(frozen=True,kw_only=True)
class BookEvent(Value):
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
class BookResult(Value):
 id:str
 project_id:str
 task_id:str
 attempt_id:str
 response:ProviderResponse
 created_at:str
@dataclass(frozen=True,kw_only=True)
class BookCandidate(Value):
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
 plan:PlanData|None
 errors:tuple[str,...]
 data_sha256:str
 created_at:str
@dataclass(frozen=True,kw_only=True)
class BookAdoption(Value):
 id:str
 project_id:str
 task_id:str
 candidate_id:str
 review_id:str
 operation_id:str
 version_id:str
 created_at:str
@dataclass(frozen=True,kw_only=True)
class BookReview(Value):
 id:str
 project_id:str
 operation_id:str
 task_id:str
 candidate_id:str
 candidate_sha256:str
 source_version_id:str
 owner_id:str
 source_sha256:str
 formal_sha256:str
 locks_sha256:str
 configuration_stamp:str
 plan:PlanData
 review_sha256:str
 created_at:str
@dataclass(frozen=True,kw_only=True)
class BookAdapterCall:
 task_id:str
 attempt_id:str
 capability:Literal['brainstorm_book','outline_book']
 task:BookTask
 request_sha256:str
 confirmed:bool
 def __post_init__(self):
  check_types(type(self),self);uuid_value(self.task_id);uuid_value(self.attempt_id);self.task.__post_init__();require(self.task_id==self.task.id and self.request_sha256==self.task.binding.request_sha256 and self.confirmed,'book_ai.confirm_required')
  require(self.capability==('brainstorm_book' if self.task.preset_step=='brainstorm' else 'outline_book'),'book_ai.step_scope')

COLLECTIONS={'book_ai_tasks':BookTask,'book_ai_events':BookEvent,'book_ai_results':BookResult,'book_ai_candidates':BookCandidate,'book_ai_reviews':BookReview,'book_ai_adoptions':BookAdoption}
def task_status(state,identifier):
 value=next((e for e in reversed(state.get('book_ai_events',[])) if e['task_id']==identifier),None);require(value is not None,'book_ai.missing_task');return value
def validate_state(state):
 parsed={};project=state['document']['project']['id']
 for name,kind in COLLECTIONS.items():
  require(type(state[name]) is list and len(state[name])<=10000,'book_ai.too_large');parsed[name]=[parse(kind,v) for v in state[name]];require(len({v.id for v in parsed[name]})==len(parsed[name]),'book_ai.duplicate_identity')
  for value in parsed[name]:
   if hasattr(value,'project_id'):require(value.project_id==project,'book_ai.wrong_book')
 plans={v['id']:v for v in state['book_creation_versions']};tasks={v.id:v for v in parsed['book_ai_tasks']};events={};results={v.id:v for v in parsed['book_ai_results']};candidates={};latest={}
 for task in tasks.values():
  require(task.step!='dialogue' or state['workspace_version']>=28,'book_ai.dialogue_requires_v28')
  require(task.source_version_id in plans and task.branch_id==plans[task.source_version_id]['branch_id'] and task.source_guard==parse(PlanData,plans[task.source_version_id]['data']),'book_ai.invalid_source')
 for event in parsed['book_ai_events']:
  require(event.task_id in tasks,'book_ai.missing_task');previous=events.get(event.task_id);require(event.previous_event_id==(previous.id if previous else None),'book_ai.broken_history')
  require(previous is not None or event.kind=='prepared' and event.status=='pending','book_ai.broken_history')
  if event.kind=='started':require(previous is not None and previous.status=='pending' and event.status=='running' and event.attempt_id is not None,'book_ai.invalid_transition')
  if event.kind=='completed':require(previous is not None and previous.status=='running' and event.status in ('succeeded','failed','cancelled','interrupted'),'book_ai.invalid_transition')
  if event.kind=='cancelled':require(previous is not None and previous.status in ('pending','running') and event.status=='cancelled','book_ai.invalid_transition')
  events[event.task_id]=event
 for result in results.values():require(result.task_id in tasks and any(e.task_id==result.task_id and e.attempt_id==result.attempt_id and e.kind=='started' for e in parsed['book_ai_events']),'book_ai.invalid_response')
 for candidate in parsed['book_ai_candidates']:
  require(candidate.task_id in tasks and candidate.response_id in results and results[candidate.response_id].task_id==candidate.task_id and results[candidate.response_id].response.complete,'book_ai.invalid_candidate');previous=latest.get(candidate.task_id);require((candidate.revision,candidate.previous_candidate_id)==((previous.revision+1,previous.id) if previous else (1,None)),'book_ai.broken_history')
  if candidate.origin=='model':require(previous is None and candidate.raw_text==results[candidate.response_id].response.output_text,'book_ai.invalid_candidate')
  if candidate.plan is not None:
   base=encode(tasks[candidate.task_id].source_guard);value=encode(candidate.plan);require(all(base[key]==value[key] for key in base if key not in STEP_FIELDS[tasks[candidate.task_id].step]),'book_ai.step_scope')
  candidates[candidate.id]=candidate;latest[candidate.task_id]=candidate
 reviews={}
 for review in parsed['book_ai_reviews']:
  require(review.task_id in tasks and review.candidate_id in candidates and candidates[review.candidate_id].task_id==review.task_id and candidates[review.candidate_id].data_sha256==review.candidate_sha256 and review.source_version_id in plans,'book_ai.invalid_review');require(review.source_sha256==fingerprint(plans[review.source_version_id]['data']),'book_ai.invalid_review');require(review.review_sha256==review_digest(review),'book_ai.invalid_review');reviews[review.id]=review
 seen=set()
 for adoption in parsed['book_ai_adoptions']:
  require(adoption.candidate_id in candidates and candidates[adoption.candidate_id].task_id==adoption.task_id and candidates[adoption.candidate_id].plan is not None and adoption.version_id in plans and adoption.task_id not in seen and adoption.review_id in reviews and reviews[adoption.review_id].candidate_id==adoption.candidate_id,'book_ai.invalid_adoption');seen.add(adoption.task_id)
def review_digest(review):
 value=encode(review) if not isinstance(review,dict) else review
 return fingerprint({key:item for key,item in value.items() if key not in ('id','operation_id','review_sha256','created_at')})
def validate_transition(state,previous):
 previous=previous or {}
 for name in COLLECTIONS:
  old=previous.get(name,[]);require(state[name][:len(old)]==old,'book_ai.history_immutable')
 old_candidates={v['id'] for v in previous.get('book_ai_candidates',[])}
 old_reviews={v['id'] for v in previous.get('book_ai_reviews',[])}
 for adoption in state['book_ai_adoptions'][len(previous.get('book_ai_adoptions',[])):]:require(adoption['candidate_id'] in old_candidates and adoption['review_id'] in old_reviews,'book_ai.candidate_required')
