"""V19 append-only archive/restore markers for chapters; no content deletion."""
from dataclasses import dataclass
from typing import Literal
from novel_writer.domain.tasks import check_types,parse,encode,require,uuid_value
from novel_writer.domain.models import _timestamp

class Value:
 def __post_init__(self):
  check_types(type(self),self);uuid_value(self.id);uuid_value(self.operation_id)
  require(bool(self.chapter_id.strip()),'chapter_lifecycle.invalid_chapter')
  require(type(self.project_id) is str and bool(self.project_id.strip()),'chapter_lifecycle.invalid_project');_timestamp(self.created_at,'chapter_lifecycle.created_at')

@dataclass(frozen=True,kw_only=True)
class LifecycleEvent(Value):
 id:str
 project_id:str
 operation_id:str
 chapter_id:str
 kind:Literal['archive','restore']
 created_at:str

COLLECTIONS={'chapter_lifecycle_events':LifecycleEvent}

def is_archived(state,chapter_id):
 latest=next((v for v in reversed(state.get('chapter_lifecycle_events',[])) if v['chapter_id']==chapter_id),None)
 return latest is not None and latest['kind']=='archive'

def archived_ids(state):return {v['chapter_id'] for v in state.get('chapter_lifecycle_events',[]) if is_archived(state,v['chapter_id'])}

def require_active(state,chapter_id):
 require(not is_archived(state,chapter_id),'chapter_lifecycle.archived_target')
 from novel_writer.domain.chapter_trash import is_trashed
 require(not is_trashed(state,chapter_id),'chapter_lifecycle.trashed_target')

def validate_state(state):
 project=state['document']['project']['id'];chapters={v['id'] for v in state['document']['chapters']};events=state.get('chapter_lifecycle_events',[])
 require(type(events) is list and len(events)<=100000,'chapter_lifecycle.invalid_collection');ids=set();operations=set()
 for raw in events:
  value=parse(LifecycleEvent,raw);require(value.id not in ids and value.operation_id not in operations and value.project_id==project and value.chapter_id in chapters,'chapter_lifecycle.invalid_event');ids.add(value.id);operations.add(value.operation_id)

def validate_transition(state,previous):
 validate_state(state);old=(previous or {}).get('chapter_lifecycle_events',[])
 require(state['chapter_lifecycle_events'][:len(old)]==old,'chapter_lifecycle.history_append_only')
