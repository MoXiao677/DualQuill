"""V16 manual corrections and adoption decisions in the shared task pipeline."""
from dataclasses import dataclass
from typing import Literal
from novel_writer.domain.model_contract import Value,ProviderResponse,ModelWritingParameters
from novel_writer.domain.tasks import parse,require,digest,uuid_value
from novel_writer.domain.memory import fingerprint

CAPABILITIES=('draft_chapter','continue_chapter')
@dataclass(frozen=True,kw_only=True)
class Correction(Value):
 id:str
 operation_id:str
 project_id:str
 chapter_id:str
 task_id:str
 candidate_id:str
 previous_id:str|None
 text:str
 created_at:str
@dataclass(frozen=True,kw_only=True)
class Decision(Value):
 id:str
 project_id:str
 task_id:str
 candidate_id:str
 correction_id:str|None
 receipt_id:str
 review_id:str
 request_sha256:str
 applied_text_sha256:str
 created_at:str
@dataclass(frozen=True,kw_only=True)
class LateResult(Value):
 id:str
 project_id:str
 task_id:str
 attempt_id:str
 terminal_status:Literal['failed','cancelled','interrupted']
 response:ProviderResponse
 created_at:str
COLLECTIONS={'writing_corrections':Correction,'writing_decisions':Decision,'writing_late_results':LateResult}

def candidate_text(state,task,correction_id=None):
 raw=next((v for v in state['generation_candidates'] if v['id']==task.candidate_id),None);require(raw is not None,'正文候选缺失')
 if correction_id is None:return raw['output_text']
 edit=next((v for v in state.get('writing_corrections',[]) if v['id']==correction_id),None);require(edit is not None and edit['task_id']==task.id and edit['candidate_id']==task.candidate_id,'人工修正不属于当前候选');return edit['text']
def compose(task,text):return (task.frozen.target.text if task.task_type=='continue_chapter' else '')+text
def adopted_text(state,task,receipt):
 decision=next((v for v in state.get('writing_decisions',[]) if v['receipt_id']==receipt.id),None);require(decision is not None and decision['task_id']==task.id and decision['candidate_id']==receipt.candidate_id,'正文采纳缺少明确决定记录')
 text=compose(task,candidate_text(state,task,decision['correction_id']));require(digest(text)==decision['applied_text_sha256'],'正文采纳内容指纹不符');return text
def validate_state(state):
 from novel_writer.domain.tasks import GenerationTask
 tasks={v['id']:parse(GenerationTask,v) for v in state['generation_tasks']};edits={};operations=set();receipts={v['id']:v for v in state['adoption_receipts']};decisions=set();late=set();project=state['document']['project']['id']
 presets={v['id'] for v in state.get('creation_presets',[])};styles={v['id'] for v in state.get('style_cards',[])};lock_ids={v['id'] for name in ('book_creation_locks','planning_locks') for v in state.get(name,[])};positions={v['id']:i for i,v in enumerate(state['generation_tasks'])}
 for task in tasks.values():
  if task.task_type not in CAPABILITIES:continue
  spec=task.frozen.parameters.writing;require(spec.preset_version_id is None or spec.preset_version_id in presets,'正文用途预设引用悬空');require(spec.style_version_id is None or spec.style_version_id in presets|styles,'正文文风/预设提示引用悬空');require(set(spec.lock_ids)<=lock_ids,'正文锁快照引用悬空')
  if spec.retry_of is not None:require(spec.retry_of in tasks and tasks[spec.retry_of].task_type in CAPABILITIES and tasks[spec.retry_of].chapter_id==task.chapter_id and positions[spec.retry_of]<positions[task.id],'正文显式重试引用非法')
 for name,model in COLLECTIONS.items():
  require(type(state[name]) is list and len(state[name])<=100000,'正文历史集合超限');ids=set()
  for row in state[name]:
   value=parse(model,row);require(value.id not in ids and value.project_id==project and value.task_id in tasks,'正文历史身份/归属非法');ids.add(value.id);task=tasks[value.task_id];require(task.task_type in CAPABILITIES and isinstance(task.frozen.parameters,ModelWritingParameters),'正文历史任务类型非法')
   if isinstance(value,Correction):
    uuid_value(value.operation_id);require(value.operation_id not in operations and value.chapter_id==task.chapter_id and value.candidate_id==task.candidate_id and bool(value.text.strip()) and len(value.text)<=task.frozen.parameters.max_output_chars,'人工修正身份/正文非法');operations.add(value.operation_id)
    previous=next((v for v in reversed(list(edits.values())) if v.task_id==task.id),None);require(value.previous_id==(previous.id if previous else None),'人工修正版本链断裂');edits[value.id]=value
   elif isinstance(value,Decision):
    require(value.receipt_id in receipts and value.receipt_id not in decisions and value.candidate_id==task.candidate_id,'正文决定关联非法');decisions.add(value.receipt_id);receipt=receipts[value.receipt_id];uuid_value(value.review_id)
    require(receipt['task_id']==task.id and (value.correction_id is None or value.correction_id in edits),'正文决定修正/收据非法');require(digest(compose(task,candidate_text(state,task,value.correction_id)))==value.applied_text_sha256,'正文决定内容非法')
    request=dict(candidate_id=value.candidate_id,adoption_id=value.receipt_id,expected_revision=receipt['requested_revision'],authorize_confirmed=receipt['authorize_confirmed'],correction_id=value.correction_id,review_id=value.review_id,confirmed_review=True);require(value.request_sha256==fingerprint(request),'正文决定与作者确认不符')
   else:
    require(value.attempt_id==task.attempt_id and task.status in ('failed','cancelled','interrupted') and value.terminal_status==task.status and task.id not in late,'迟到响应关联非法');late.add(task.id)
def validate_transition(state,previous):
 validate_state(state)
 for name in COLLECTIONS:require(state[name][:len(previous.get(name,[]))]==previous.get(name,[]),'正文修正/决定/迟到响应只能追加')
