"""V22 scoped writing rules with append-only history and exact-text conflict detection."""
from dataclasses import dataclass
from typing import Literal
from novel_writer.domain.tasks import check_types,parse,encode,require,uuid_value
from novel_writer.domain.models import _timestamp

SCOPES=('global','book','volume','chapter','task')
KINDS=('required','forbidden','guidance')
OPERATIONS=('create','update','enable','disable','archive','unarchive','delete','import')
SOURCES=('manual','import')

class Value:
 def __post_init__(self):
  check_types(type(self),self);uuid_value(self.id)
  require(type(self.project_id) is str and bool(self.project_id.strip()),'scoped_rules.invalid_project')
  require(self.scope in SCOPES and self.kind in KINDS and type(self.text) is str and 0<len(self.text.strip())<=2000,'scoped_rules.invalid_rule')
  require(type(self.enabled) is bool and type(self.archived) is bool and self.source in ('manual','legacy') and self.version>=1,'scoped_rules.invalid_rule')
  _timestamp(self.created_at,'scoped_rules.created_at');_timestamp(self.updated_at,'scoped_rules.updated_at')

@dataclass(frozen=True,kw_only=True)
class Rule(Value):
 id:str
 project_id:str
 scope:Literal['global','book','volume','chapter','task']
 scope_id:str|None
 kind:Literal['required','forbidden','guidance']
 text:str
 enabled:bool
 archived:bool
 source:Literal['manual','legacy']
 version:int
 created_at:str
 updated_at:str

@dataclass(frozen=True,kw_only=True)
class RuleHistory:
 id:str
 project_id:str
 rule_id:str
 operation:Literal['create','update','enable','disable','archive','unarchive','delete','import']
 before:dict|None
 after:dict|None
 source:Literal['manual','import']
 created_at:str
 def __post_init__(self):
  check_types(type(self),self);uuid_value(self.id);uuid_value(self.rule_id)
  require(type(self.project_id) is str and bool(self.project_id.strip()),'scoped_rules.invalid_project')
  require(self.operation in OPERATIONS and self.source in SOURCES,'scoped_rules.invalid_history')
  _timestamp(self.created_at,'scoped_rules.history_created_at')
  for snapshot in (self.before,self.after):
   if snapshot is not None:
    value=parse(Rule,snapshot);require(value.id==self.rule_id and value.project_id==self.project_id,'scoped_rules.invalid_history')
  if self.operation in ('create','import'):require(self.before is None and self.after is not None,'scoped_rules.invalid_history')
  elif self.operation=='delete':require(self.before is not None and self.after is None,'scoped_rules.invalid_history')
  else:require(self.before is not None and self.after is not None,'scoped_rules.invalid_history')

COLLECTIONS={'scoped_rules':Rule,'scoped_rule_history':RuleHistory}

@dataclass(frozen=True,kw_only=True)
class TaskRuleBinding:
 id:str
 project_id:str
 chapter_id:str
 task_type:Literal['rewrite_chapter','audit_chapter','draft_chapter','continue_chapter','brainstorm_chapter','outline_chapter','expand_scene_selection']
 created_at:str
 def __post_init__(self):
  check_types(type(self),self);uuid_value(self.id);require(bool(self.chapter_id.strip()),'scoped_rules.invalid_chapter')
  require(bool(self.project_id.strip()),'scoped_rules.invalid_project')
  _timestamp(self.created_at,'scoped_rules.binding_created_at')

def has_task_rules(state):
 return bool(state.get('rule_task_bindings')) or any(v.get('scope')=='task' for v in state.get('scoped_rules',[])) or any(s and s.get('scope')=='task' for h in state.get('scoped_rule_history',[]) for s in (h.get('before'),h.get('after')))

def validate_state(state):
 project=state['document']['project']['id'];chapters={v['id'] for v in state['document']['chapters']};volumes={str(v['number']) for v in (state['document']['book_outline']['volumes'] if state['document']['book_outline'] else [])}
 rules=state.get('scoped_rules',[]);require(type(rules) is list and len(rules)<=10000,'scoped_rules.invalid_collection');ids=set()
 bindings={}
 require(type(state.get('rule_task_bindings',[])) is list and len(state.get('rule_task_bindings',[]))<=10000,'scoped_rules.invalid_bindings')
 for raw in state.get('rule_task_bindings',[]):
  binding=parse(TaskRuleBinding,raw);require(binding.id not in bindings and binding.project_id==project and binding.chapter_id in chapters,'scoped_rules.invalid_task_binding');bindings[binding.id]=binding
  require(state['workspace_version']>=46 or binding.task_type not in ('brainstorm_chapter','outline_chapter','expand_scene_selection'),'scoped_rules.planning_requires_v37')
 require(not has_task_rules(state) or state['workspace_version']>=36,'scoped_rules.task_requires_v36')
 for task in state.get('generation_tasks',[]):
  target=task['frozen']['context_options'].get('rule_task_id')
  require(task['request_id'] not in bindings or target==task['request_id'],'scoped_rules.reserved_binding_omitted')
  if target is not None:
   require(target in bindings and task['request_id']==target and bindings[target].chapter_id==task['chapter_id'] and bindings[target].task_type==task['task_type'],'scoped_rules.task_binding_mismatch')
 for raw in rules:
  rule=parse(Rule,raw);require(rule.id not in ids and rule.project_id==project,'scoped_rules.invalid_rule');ids.add(rule.id)
  if rule.scope=='global':require(rule.scope_id is None,'scoped_rules.invalid_scope')
  elif rule.scope=='book':require(rule.scope_id==project,'scoped_rules.invalid_scope')
  elif rule.scope=='volume':require(rule.scope_id in volumes,'scoped_rules.invalid_scope')
  elif rule.scope=='chapter':require(rule.scope_id in chapters,'scoped_rules.invalid_scope')
  else:require(rule.scope_id in bindings,'scoped_rules.invalid_task_scope')
 for name in ('chapter_planning_tasks','scene_expansion_tasks'):
  for task in state.get(name,[]):
   target=task['source_options'].get('rule_task_id');snapshots=task['source_guard'].get('rule_sources')
   require(task['request_id'] not in bindings or target==task['request_id'],'scoped_rules.reserved_binding_omitted')
   require((target is None)==(snapshots is None),'scoped_rules.missing_frozen_rule_sources')
   if target is not None:
    capability=('brainstorm_chapter' if task['mode']=='brainstorm' else 'outline_chapter') if name=='chapter_planning_tasks' else 'expand_scene_selection'
    require(state['workspace_version']>=46 and target==task['request_id'] and target in bindings and bindings[target].chapter_id==task['chapter_id'] and bindings[target].task_type==capability,'scoped_rules.independent_binding_mismatch')
    require(type(snapshots) is list and len({r['id'] for r in snapshots})==len(snapshots),'scoped_rules.invalid_frozen_rules')
    for rule in snapshots:require(parse(Rule,rule).project_id==project,'scoped_rules.cross_book_snapshot')
 history=state.get('scoped_rule_history',[]);require(type(history) is list and len(history)<=50000,'scoped_rules.invalid_history_collection');history_ids=set()
 for raw in history:
  entry=parse(RuleHistory,raw);require(entry.id not in history_ids and entry.project_id==project,'scoped_rules.invalid_history')
  for snapshot in (entry.before,entry.after):
   if snapshot and snapshot['scope']=='task':require(snapshot['scope_id'] in bindings,'scoped_rules.invalid_task_history')
  history_ids.add(entry.id)

def validate_transition(state,previous):
 validate_state(state)
 old_bindings=previous.get('rule_task_bindings',[]);new_bindings=state.get('rule_task_bindings',[])
 require(new_bindings[:len(old_bindings)]==old_bindings,'scoped_rules.bindings_not_append_only')
 old=previous.get('scoped_rule_history') if previous.get('workspace_version',0)>=22 else None
 if old is not None:
  new=state.get('scoped_rule_history',[])
  require(len(new)>=len(old) and new[:len(old)]==old,'scoped_rules.history_not_append_only')
