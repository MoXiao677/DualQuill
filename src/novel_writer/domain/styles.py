"""V13 immutable material references, bounded extraction and human style versions."""
from novel_writer.domain.sampling import Sampling
from dataclasses import dataclass
from typing import Literal
import re
from novel_writer.domain.tasks import check_types,parse,encode,require,uuid_value,digest
from novel_writer.domain.models import _timestamp
from novel_writer.domain.book_ai import BookDestination
from novel_writer.domain.book_creation import fingerprint

FEATURES=('viewpoint','syntax_vocabulary','rhythm','dialogue','description','rhetoric_emotion')
COLLECTIONS=('style_sources','style_analyses','style_requests','style_events','style_results','style_candidates','style_cards','style_choices','style_budgets')
SHA=re.compile('[0-9a-f]{64}')

class Value:
 def __post_init__(self):
  check_types(type(self),self)
  if hasattr(self,'id'):uuid_value(self.id)
  if hasattr(self,'created_at'):_timestamp(self.created_at,'styles.created_at')
  for name in ('blob_sha256','text_sha256','body_sha256','request_sha256','response_sha256','raw_sha256','configuration_stamp'):
   if hasattr(self,name):require(SHA.fullmatch(getattr(self,name)) is not None,'styles.invalid_hash')

@dataclass(frozen=True,kw_only=True)
class Features(Value):
 viewpoint:str
 syntax_vocabulary:str
 rhythm:str
 dialogue:str
 description:str
 rhetoric_emotion:str
 def __post_init__(self):
  super().__post_init__()
  require(all(len(getattr(self,k))<=2000 for k in FEATURES),'styles.card_limit')
  from novel_writer.domain.style_checks import validate_features
  validate_features({k:getattr(self,k) for k in FEATURES})

@dataclass(frozen=True,kw_only=True)
class Evidence(Value):
 start:int
 end:int
 feature:Literal['viewpoint','syntax_vocabulary','rhythm','dialogue','description','rhetoric_emotion']
 def __post_init__(self):super().__post_init__();require(0<=self.start<self.end,'styles.invalid_range')

@dataclass(frozen=True,kw_only=True)
class Draft(Value):
 prompt:str
 card:Features
 evidence:tuple[Evidence,...]
 def __post_init__(self):super().__post_init__();require(0<len(self.prompt.strip())<=8000 and len(self.evidence)<=100,'styles.card_limit')

@dataclass(frozen=True,kw_only=True)
class Source(Value):
 id:str
 project_id:str
 operation_id:str
 kind:Literal['article','book','prompt','card']
 name:str
 encoding:Literal['utf-8','utf-8-sig','utf-16','gb18030']
 origin:str
 blob_sha256:str
 text_sha256:str
 byte_count:int
 char_count:int
 created_at:str

@dataclass(frozen=True,kw_only=True)
class Configuration(Value):
 adapter_id:Literal['style-http-v1']
 source_adapter_id:Literal['chat-completions-http-v1','configured-http-v2']
 connection_id:str
 model_id:str
 temperature:float
 max_tokens:int
 budget_limit:float
 allow_unknown_cost:bool
 destination:BookDestination
 configuration_stamp:str
 sampling:Sampling|None=None


@dataclass(frozen=True,kw_only=True)
class Analysis(Value):
 id:str
 project_id:str
 operation_id:str
 source_id:str
 start:int
 end:int
 chunk_chars:int
 max_calls:int
 max_output_tokens:int
 configuration:Configuration
 preset_version_id:str|None
 created_at:str

@dataclass(frozen=True,kw_only=True)
class Request(Value):
 id:str
 project_id:str
 operation_id:str
 analysis_id:str
 owner_id:str
 chunk_index:int
 start:int
 end:int
 body_sha256:str
 request_sha256:str
 created_at:str

@dataclass(frozen=True,kw_only=True)
class Event(Value):
 id:str
 project_id:str
 request_id:str
 previous_event_id:str|None
 status:Literal['pending','running','succeeded','failed','cancelled','interrupted']
 owner_id:str
 created_at:str

@dataclass(frozen=True,kw_only=True)
class Result(Value):
 id:str
 project_id:str
 request_id:str
 response_sha256:str
 complete:bool
 error_code:str|None
 created_at:str

@dataclass(frozen=True,kw_only=True)
class Candidate(Value):
 id:str
 project_id:str
 operation_id:str
 request_id:str
 result_id:str
 previous_candidate_id:str|None
 origin:Literal['model','manual_correction']
 raw_sha256:str
 draft:Draft|None
 errors:tuple[str,...]
 created_at:str

@dataclass(frozen=True,kw_only=True)
class Coverage(Value):
 source_id:str
 start:int
 end:int
 request_id:str
 candidate_id:str

@dataclass(frozen=True,kw_only=True)
class Card(Value):
 id:str
 project_id:str
 operation_id:str
 style_id:str
 previous_version_id:str|None
 revision:int
 name:str
 prompt:str
 card:Features
 analysis_id:str|None
 source_id:str|None
 coverage:tuple[Coverage,...]
 coverage_sha256:str
 created_at:str

@dataclass(frozen=True,kw_only=True)
class Choice(Value):
 id:str
 project_id:str
 operation_id:str
 chapter_id:str|None
 version_id:str|None
 created_at:str

@dataclass(frozen=True,kw_only=True)
class Budget(Value):
 id:str
 project_id:str
 operation_id:str
 analysis_id:str
 additional_calls:int
 additional_output_tokens:int
 created_at:str

MODELS=dict(zip(COLLECTIONS,(Source,Analysis,Request,Event,Result,Candidate,Card,Choice,Budget)))
def ranges(analysis):return [(i,start,min(start+analysis['chunk_chars'],analysis['end'])) for i,start in enumerate(range(analysis['start'],analysis['end'],analysis['chunk_chars']))]
def request_hash(body_sha256,configuration):return fingerprint(dict(body_sha256=body_sha256,configuration=configuration))
def last_event(state,identifier):return next(v for v in reversed(state['style_events']) if v['request_id']==identifier)
def blob_refs(state):
 return {v[key] for name,key in [('style_sources','blob_sha256'),('style_requests','body_sha256'),('style_results','response_sha256'),('style_candidates','raw_sha256')] for v in state.get(name,[])}

def validate_state(state):
 project=state['document']['project']['id'];objects={}
 for name,model in MODELS.items():
  require(type(state[name]) is list,'styles.invalid_collection');seen=set()
  for raw in state[name]:
   item=parse(model,raw);require(item.project_id==project and item.id not in seen,'styles.invalid_identity');seen.add(item.id)
   if hasattr(item,'operation_id'):uuid_value(item.operation_id)
  objects[name]={v['id']:v for v in state[name]}
 for source in state['style_sources']:
  require(0<source['byte_count']<=8*1024**2 and 0<source['char_count']<=4_000_000 and len(source['name'])<=200 and not any(c in source['name'] for c in ('/',chr(92),chr(0))) and 0<len(source['origin'])<=1000,'styles.invalid_source')
 for analysis in state['style_analyses']:
  source=objects['style_sources'].get(analysis['source_id']);require(source is not None and 0<=analysis['start']<analysis['end']<=source['char_count'] and 2000<=analysis['chunk_chars']<=20000 and 1<=analysis['max_calls']<=10 and 128<=analysis['max_output_tokens']<=81920,'styles.invalid_range');config=analysis['configuration'];require(config['connection_id']==config['destination']['connection_id'] and 128<=config['max_tokens']<=8192 and config['allow_unknown_cost'] and 0<=config['temperature']<=2 and 0<config['budget_limit']<=10000,'styles.invalid_configuration')
 for request in state['style_requests']:
  analysis=objects['style_analyses'].get(request['analysis_id']);require(analysis is not None and (request['chunk_index'],request['start'],request['end']) in ranges(analysis) and request['request_sha256']==request_hash(request['body_sha256'],analysis['configuration']),'styles.invalid_request');uuid_value(request['owner_id'])
 events={}
 allowed={None:{'pending'},'pending':{'running','cancelled'},'running':{'succeeded','failed','cancelled','interrupted'}}
 for event in state['style_events']:
  old=events.get(event['request_id']);require(event['request_id'] in objects['style_requests'] and event['previous_event_id']==(old['id'] if old else None) and event['status'] in allowed.get(old['status'] if old else None,set()),'styles.invalid_event');events[event['request_id']]=event
 require(set(events)==set(objects['style_requests']),'styles.missing_event')
 for result in state['style_results']:require(result['request_id'] in objects['style_requests'],'styles.invalid_result')
 previous={}
 for candidate in state['style_candidates']:
  result=objects['style_results'].get(candidate['result_id']);old=previous.get(candidate['request_id']);require(result is not None and result['request_id']==candidate['request_id'] and candidate['previous_candidate_id']==(old['id'] if old else None) and (candidate['draft'] is None)==bool(candidate['errors']),'styles.invalid_candidate');request=objects['style_requests'][candidate['request_id']]
  if candidate['draft']:require(candidate['draft']['evidence'] and all(request['start']<=e['start']<e['end']<=request['end'] for e in candidate['draft']['evidence']),'styles.invalid_evidence')
  previous[candidate['request_id']]=candidate
 previous={}
 for card in state['style_cards']:
  old=previous.get(card['style_id']);require(card['previous_version_id']==(old['id'] if old else None) and card['revision']==(old['revision']+1 if old else 1) and 0<len(card['name'].strip())<=200 and 0<len(card['prompt'].strip())<=8000,'styles.invalid_card');uuid_value(card['style_id'])
  if card['analysis_id'] is not None:require(card['analysis_id'] in objects['style_analyses'] and card['coverage'],'styles.no_coverage')
  else:require(not card['coverage'],'styles.invalid_evidence')
  require((card['source_id'] is None or card['source_id'] in objects['style_sources']) and card['coverage_sha256']==fingerprint(card['coverage']),'styles.invalid_source')
  for evidence in card['coverage']:
   request=objects['style_requests'].get(evidence['request_id']);candidate=objects['style_candidates'].get(evidence['candidate_id']);require(request is not None and candidate is not None and candidate['request_id']==request['id'] and candidate['draft'] is not None and request['analysis_id']==card['analysis_id'] and (evidence['start'],evidence['end'])==(request['start'],request['end']) and evidence['source_id']==objects['style_analyses'][card['analysis_id']]['source_id'],'styles.invalid_evidence')
  previous[card['style_id']]=card
 for choice in state['style_choices']:require((choice['version_id'] is None or choice['version_id'] in objects['style_cards']) and (choice['chapter_id'] is None or choice['chapter_id'] in {c['id'] for c in state['document']['chapters']}),'styles.invalid_choice')
 for budget in state['style_budgets']:require(budget['analysis_id'] in objects['style_analyses'] and 1<=budget['additional_calls']<=10 and 128<=budget['additional_output_tokens']<=81920,'styles.invalid_budget')

def validate_transition(state,previous):
 previous=previous or {}
 for name in COLLECTIONS:
  old=previous.get(name,[]);require(state[name][:len(old)]==old,'styles.immutable_history')
 old_candidates={v['id'] for v in previous.get('style_candidates',[])}
 for card in state['style_cards'][len(previous.get('style_cards',[])):]:require(all(v['candidate_id'] in old_candidates for v in card['coverage']),'styles.review_required')

def selected_style(state,chapter_id=None):
 choices=state.get('style_choices',[]);chapter_choice=next((v for v in reversed(choices) if chapter_id is not None and v['chapter_id']==chapter_id),None);book_choice=next((v for v in reversed(choices) if v['chapter_id'] is None),None);choice=chapter_choice or book_choice
 if choice is not None:return next((v for v in state.get('style_cards',[]) if v['id']==choice['version_id']),None)
 presets=state.get('creation_preset_choices',[]);preset=next((v for v in state.get('creation_presets',[]) if presets and v['id']==presets[-1]['version_id']),None)
 if not preset:return None
 identifier=preset['settings']['style_id'];card=next((v for v in state.get('style_cards',[]) if v['id']==identifier),None)
 require(identifier is None or card is not None,'styles.missing_preset_style')
 if card:return card
 prompt=preset['settings']['style_prompt']
 return dict(id=preset['id'],name=preset['name'],prompt=prompt,card={},coverage=[]) if prompt else None

@dataclass(frozen=True,kw_only=True)
class StyleCall(Value):
 request:Request
 configuration:Configuration
 request_body:str
 def __post_init__(self):super().__post_init__();require(digest(self.request_body)==self.request.body_sha256 and self.request.request_sha256==request_hash(self.request.body_sha256,encode(self.configuration)),'styles.invalid_request')
