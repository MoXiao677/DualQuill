"""Natural-language planning reuses console history and frozen BookAI candidates."""
from copy import deepcopy
from uuid import uuid5,NAMESPACE_URL
from novel_writer.domain.tasks import require,uuid_value,parse
from novel_writer.domain.book_ai import BookTask
from novel_writer.domain.book_creation import fingerprint,current_locks
from novel_writer.storage.json_codec import strict_json_loads
from novel_writer.application.console_usage import actual_usage,usage_summary

class CreativeDialogue:
 def __init__(self,console,book_ai):self.console,self.ai=console,book_ai
 def describe(self,project,session):
  detail=self.console.describe(project,session);state=self.ai.service.get(project);tasks={v['id']:v for v in state.get('book_ai_tasks',[]) if v['step']=='dialogue'};turns=[];seen=set()
  for message in detail['messages']:
   if message['role']=='author':turns.append(dict(role='author',text=message['text'],message_id=message['id']))
   for ref in message['refs']:
    if ref['kind']!='task' or ref['id'] not in tasks or ref['id'] in seen:continue
    seen.add(ref['id'])
    task=self.ai._describe(state,parse(BookTask,tasks[ref['id']]));task['usage']=actual_usage(task)
    candidate=task['latest_candidate'];reply=''
    if candidate:
     try:reply=strict_json_loads(candidate['raw_text']).get('reply','')
     except (ValueError,AttributeError):pass
    turns.append(dict(role='assistant',text=reply,task=task))
  unique={v['task']['task']['id']:v['task'] for v in turns if v.get('task')}
  return dict(session=detail['session'],turns=turns,revision=state['revision'],usage=usage_summary(list(unique.values())),enabled=self.ai.adapter.enabled and not self.ai.providers.offline)
 def prepare(self,project,request):
  fields={'operation_id','session_id','text','model_options','max_output_chars','timeout_ms'}
  require(type(request) is dict and set(request)==fields,'对话请求字段缺失或未知');identity=uuid_value(request['operation_id']);session=uuid_value(request['session_id'])
  require(type(request['text']) is str and 0<len(request['text'].strip())<=4000,'请输入1至4000字符的创作要求')
  # Persist the author's input even when configuration, offline or transport gates fail.
  message=self.console.append_message(project,dict(operation_id=identity,session_id=session,role='author',text=request['text'],refs=[]))
  view=self.describe(project,session);state=self.ai.service.get(project)
  task_id=str(uuid5(NAMESPACE_URL,identity+'/book-task'));old=next((v for v in state.get('book_ai_tasks',[]) if v['id']==task_id),None)
  if old:
   require(old['preparation_sha256']==fingerprint(dict(request,dialogue_retry=True)),'对话操作编号已绑定其它参数');return self.ai.describe(project,task_id)
  require(not any(v.get('task',{}).get('status') in ('pending','running') and v['task']['display_status']!='interrupted' for v in view['turns']),'先取消或完成上次待确认请求，再准备新一轮')
  require(view['enabled'],'模型会话关闭；需求已保留。请配置并明确开启会话后准备新请求')
  manual=self.ai.manual;plan=manual.describe(project)['selected']
  if plan is None:
   manual.start(project,dict(operation_id=str(uuid5(NAMESPACE_URL,identity+'/plan')),name='对话大纲方案',expected_revision=self.ai.service.get(project)['revision']));plan=manual.describe(project)['selected']
  history=[]
  for turn in view['turns']:
   if turn['role']=='author':history.append(dict(role='user',content=turn['text']))
   elif turn['task']['latest_candidate']:
    history.append(dict(role='assistant',content=turn['task']['latest_candidate']['raw_text']))
  original=dict(kind='creative_dialogue',session_id=session,message_id=message['id'],history=history,plan=deepcopy(plan['data']),locked_fields=list(current_locks(state)),formal_outline=deepcopy(state['document']['book_outline']),formal_worldbuilding=state['worldbuilding'])
  require(len(str(original))<=180000,'会话上下文已超过上限，请新建会话；历史仍保留，不会静默截断')
  return self.ai.prepare(project,dict(operation_id=identity,version_id=plan['id'],step='dialogue',preset_step='outline',instruction=request['text'],model_options=request['model_options'],max_output_chars=request['max_output_chars'],timeout_ms=request['timeout_ms']),_dialogue=original,_dialogue_identity=fingerprint(dict(request,dialogue_retry=True)))
