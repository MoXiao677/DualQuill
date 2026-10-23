"""Explicit single saved chapter -> reviewed model summary -> manual new memory."""
from hashlib import sha256
import json
from novel_writer.application.fields import check_fields
from novel_writer.domain.tasks import require,encode,digest

PROMPT='chapter-summary-json-1'

def is_summary(task):
    return getattr(getattr(task.frozen.parameters,'binding',None),'prompt_version',None)==PROMPT

def memory_digest(state):
    return sha256(json.dumps(state.get('memories',[]),ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf8')).hexdigest()

def require_fresh(state,task):
    if is_summary(task):
        from novel_writer.application.chapter_lifecycle import is_hidden
        require(not is_hidden(state,task.chapter_id),'摘要章节已归档或回收，请重新选择')
        require(task.frozen.parameters.summary_memory_sha256==memory_digest(state),'记忆集合已变化，请重新准备并核对单章摘要')

def prepare(coordinator,project,request):
    fields={'request_id','chapter_id','expected_revision','instruction','max_output_chars','timeout_ms','model_options'}
    check_fields(request,fields);require(set(request)==fields,'单章摘要准备字段缺失')
    require(type(request['model_options']) is dict and request['model_options'].get('prompt_version')==PROMPT,'单章摘要须使用明确的专用提示版本')
    options=dict(chapter_id=request['chapter_id'],scope='previous',budget_chars=128,include_current_plan=False,include_book_outline=False,include_characters=False,include_worldbuilding=False,include_writing_rules=False,include_memories=False,include_search_results=False)
    rules=dict(version='offline-audit-1',forbidden_literals=[],required_literals=[],normalization='whitespace',near_threshold=.9,minimum_fragment_chars=12,check_timeline=False)
    parameters={name:request[name] for name in ('instruction','max_output_chars','timeout_ms')}
    parameters.update(rules=rules,selected_chapter_ids=[request['chapter_id']],previous_report_id=None)
    return coordinator.prepare(project,dict(request_id=request['request_id'],chapter_id=request['chapter_id'],task_type='audit_chapter',context_options=options,context_sha256=digest(''),parameters=parameters,expected_revision=request['expected_revision'],model_options=request['model_options']))
