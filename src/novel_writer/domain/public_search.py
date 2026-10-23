"""V14 grounded discovery, identity confirmation and public-page provenance."""
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit,urlunsplit
import ipaddress,re
from novel_writer.domain.styles import Value,Configuration as StyleConfiguration,fingerprint
from novel_writer.domain.tasks import require,parse,encode,digest,uuid_value
from novel_writer.domain.model_contract import ProviderResponse

def public_url(value,**_ignored):
 require(type(value) is str and 0<len(value)<=2048 and not any(ord(c)<33 or ord(c)==127 for c in value) and '\\' not in value,'public_url_invalid')
 try:
  parsed=urlsplit(value);port=parsed.port;host=parsed.hostname
  require(parsed.scheme in ('http','https') and host and parsed.username is None and parsed.password is None and (port is None or 1<=port<=65535) and '%' not in host,'public_url_invalid')
  normalized=host.encode('idna').decode().lower().rstrip('.')
  require(normalized not in ('localhost','localhost.localdomain') and not normalized.endswith(('.localhost','.local','.internal')),'public_address_blocked')
  try:address=ipaddress.ip_address(normalized)
  except ValueError:require(re.fullmatch('[a-z0-9.-]+',normalized) and '.' in normalized,'public_url_invalid')
  else:require(address.is_global,'public_address_blocked')
 except (ValueError,UnicodeError) as error:raise ValueError(str(error) if str(error) in ('public_url_invalid','public_address_blocked') else 'public_url_invalid') from None
 return parsed

@dataclass(frozen=True,kw_only=True)
class Configuration(StyleConfiguration):
 adapter_id:Literal['grounded-search-v1']
 def __post_init__(self):super().__post_init__();require(self.destination.protocol=='gemini-content','search.unsupported_protocol')

@dataclass(frozen=True,kw_only=True)
class Query(Value):
 id:str
 project_id:str
 operation_id:str
 owner_id:str
 title:str
 platform:str
 author:str
 query_key:str
 configuration:Configuration
 preset_version_id:str|None
 max_calls:int
 max_output_tokens:int
 body_sha256:str
 request_sha256:str
 created_at:str

@dataclass(frozen=True,kw_only=True)
class Event(Value):
 id:str
 project_id:str
 query_id:str|None
 read_id:str|None
 previous_event_id:str|None
 status:Literal['pending','running','succeeded','failed','cancelled','interrupted']
 owner_id:str
 created_at:str

@dataclass(frozen=True,kw_only=True)
class Result(Value):
 id:str
 project_id:str
 query_id:str
 response_sha256:str
 raw_sha256:str
 queries:tuple[str,...]
 search_entry_sha256:str|None
 error_code:str|None
 created_at:str

@dataclass(frozen=True,kw_only=True)
class Support(Value):
 part_index:int
 start_byte:int
 end_byte:int
 text_sha256:str

@dataclass(frozen=True,kw_only=True)
class Source(Value):
 id:str
 project_id:str
 query_id:str
 result_id:str
 chunk_index:int
 title:str
 url:str
 supports:tuple[Support,...]
 created_at:str

@dataclass(frozen=True,kw_only=True)
class Identity(Value):
 id:str
 project_id:str
 operation_id:str
 query_id:str
 source_id:str
 created_at:str

@dataclass(frozen=True,kw_only=True)
class Read(Value):
 id:str
 project_id:str
 operation_id:str
 owner_id:str
 identity_id:str
 source_id:str
 url:str
 request_sha256:str
 created_at:str

@dataclass(frozen=True,kw_only=True)
class Hop(Value):
 url:str
 addresses:tuple[str,...]
 status:int|None
 location:str|None
 error_code:str|None

@dataclass(frozen=True,kw_only=True)
class Page(Value):
 id:str
 project_id:str
 read_id:str
 original_url:str
 final_url:str
 hops:tuple[Hop,...]
 http_status:int|None
 raw_sha256:str|None
 text_sha256:str|None
 encoding:str|None
 title:str
 char_count:int
 sample_type:Literal['page_text','description','toc','unavailable']
 error_code:str|None
 fetched_at:str
 created_at:str

@dataclass(frozen=True,kw_only=True)
class Import(Value):
 id:str
 project_id:str
 operation_id:str
 page_id:str
 source_id:str
 start:int
 end:int
 sample_type:Literal['prose_excerpt','page_text','description','toc']
 created_at:str

COLLECTIONS={'web_queries':Query,'web_events':Event,'web_results':Result,'web_sources':Source,'web_identities':Identity,'web_reads':Read,'web_pages':Page,'web_imports':Import}
def query_hash(query):return fingerprint(dict(title=query['title'],platform=query['platform'],author=query['author']))
def request_hash(body_sha,configuration):return fingerprint(dict(body_sha256=body_sha,configuration=configuration))
def read_hash(url,source,owner):return fingerprint(dict(url=url,source_id=source,owner_id=owner,max_bytes=1048576,max_redirects=4,timeout_seconds=20))
def last_event(state,identifier):return next(v for v in reversed(state['web_events']) if (v['query_id'] or v['read_id'])==identifier)
def blob_refs(state):
 return {v[key] for collection,keys in [('web_queries',('body_sha256',)),('web_results',('response_sha256','raw_sha256','search_entry_sha256')),('web_pages',('raw_sha256','text_sha256'))] for v in state.get(collection,[]) for key in keys if v[key] is not None}

def validate_state(state):
 project=state['document']['project']['id'];objects={};seen=set()
 for collection,model in COLLECTIONS.items():
  require(type(state[collection]) is list,'search.invalid_collection');objects[collection]={}
  for raw in state[collection]:
   record=parse(model,raw);require(record.id not in seen and record.project_id==project,'search.invalid_identity');seen.add(record.id);objects[collection][record.id]=raw
   if hasattr(record,'operation_id'):uuid_value(record.operation_id)
 for query in state['web_queries']:
  require(0<len(query['title'].strip())<=200 and 0<len(query['platform'].strip())<=200 and len(query['author'])<=200 and query['query_key']==query_hash(query) and 1<=query['max_calls']<=10 and 128<=query['max_output_tokens']<=81920 and query['request_sha256']==request_hash(query['body_sha256'],query['configuration']),'search.invalid_query');uuid_value(query['owner_id']);config=query['configuration'];require(config['allow_unknown_cost'] and 128<=config['max_tokens']<=8192 and 0<=config['temperature']<=2 and 0<config['budget_limit']<=10000 and config['connection_id']==config['destination']['connection_id'],'search.invalid_configuration')
 for result in state['web_results']:require(result['query_id'] in objects['web_queries'] and len(result['queries'])<=50 and all(len(q)<=1000 for q in result['queries']),'search.invalid_result')
 for source in state['web_sources']:
  public_url(source['url']);require(source['result_id'] in objects['web_results'] and source['query_id']==objects['web_results'][source['result_id']]['query_id'] and 0<=source['chunk_index']<100 and 0<len(source['title'])<=1000 and source['supports'] and len(source['supports'])<=100,'search.invalid_source')
  for support in source['supports']:require(0<=support['part_index']<100 and 0<=support['start_byte']<support['end_byte']<=1048576,'search.invalid_support')
 for identity in state['web_identities']:require(identity['source_id'] in objects['web_sources'] and identity['query_id']==objects['web_sources'][identity['source_id']]['query_id'],'search.invalid_identity')
 for read in state['web_reads']:
  identity=objects['web_identities'].get(read['identity_id']);source=objects['web_sources'].get(read['source_id']);require(identity is not None and source is not None and identity['source_id']==source['id'] and read['url']==source['url'] and read['request_sha256']==read_hash(read['url'],read['source_id'],read['owner_id']),'search.invalid_read')
 events={};allowed={None:{'pending'},'pending':{'running','cancelled'},'running':{'succeeded','failed','cancelled','interrupted'}}
 for event in state['web_events']:
  identifier=event['query_id'] or event['read_id'];previous=events.get(identifier);require((event['query_id'] is None)!=(event['read_id'] is None) and identifier in (objects['web_queries'] if event['query_id'] else objects['web_reads']) and event['previous_event_id']==(previous['id'] if previous else None) and event['status'] in allowed.get(previous['status'] if previous else None,set()),'search.invalid_event');events[identifier]=event
 require(set(events)==set(objects['web_queries'])|set(objects['web_reads']),'search.missing_event')
 for page in state['web_pages']:
  read=objects['web_reads'].get(page['read_id']);require(read is not None and read['url']==page['original_url'] and 0<=page['char_count']<=4_000_000 and len(page['hops'])<=5,'search.invalid_page')
  if page['error_code'] is None:public_url(page['final_url']);require(page['http_status']==200 and page['raw_sha256'] is not None and page['text_sha256'] is not None and page['char_count']>0,'search.invalid_page')
  for hop in page['hops']:
   require(all(ipaddress.ip_address(ip).is_global for ip in hop['addresses']),'search.invalid_public_address')
 for imported in state['web_imports']:
  page=objects['web_pages'].get(imported['page_id']);material=next((v for v in state.get('style_sources',[]) if v['id']==imported['source_id']),None);require(page is not None and page['error_code'] is None and material is not None and material['kind']=='article' and 0<=imported['start']<imported['end']<=page['char_count'] and material['char_count']==imported['end']-imported['start'],'search.invalid_import')
  require(page['sample_type'] not in ('description','toc') or page['sample_type']==imported['sample_type'],'search.sample_type_mismatch')

def validate_transition(state,previous):
 previous=previous or {}
 for collection in COLLECTIONS:
  old=previous.get(collection,[]);require(state[collection][:len(old)]==old,'search.immutable_history')
 for identity in state['web_identities'][len(previous.get('web_identities',[])):]:require(any(v['id']==identity['source_id'] for v in previous.get('web_sources',[])),'search.identity_confirmation_required')
 for imported in state['web_imports'][len(previous.get('web_imports',[])):]:require(any(v['id']==imported['page_id'] for v in previous.get('web_pages',[])),'search.sample_preview_required')

@dataclass(frozen=True,kw_only=True)
class SearchCall(Value):
 query:Query
 request_body:str
 def __post_init__(self):super().__post_init__();require(digest(self.request_body)==self.query.body_sha256,'search.invalid_request')
@dataclass(frozen=True,kw_only=True)
class ReadCall(Value):
 read:Read
@dataclass(frozen=True,kw_only=True)
class SearchOutcome(Value):
 response:ProviderResponse
 raw_response:str
@dataclass(frozen=True,kw_only=True)
class FetchOutcome(Value):
 original_url:str
 final_url:str
 hops:tuple[Hop,...]
 http_status:int|None
 raw:bytes
 text:str
 encoding:str|None
 title:str
 sample_type:Literal['page_text','description','toc','unavailable']
 complete:bool
 error_code:str|None
