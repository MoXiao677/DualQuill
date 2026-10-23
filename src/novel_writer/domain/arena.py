"""C12 projections and validation over existing S6A/planning/review records."""
from copy import deepcopy
import json
from math import isfinite
from novel_writer.domain.tasks import require,encode,digest
from novel_writer.domain.connections import canonical_messages

VERSION=38

def validate_budget(budget,profiles):
    require(type(budget) is dict and set(budget)=={'max_calls','max_output_tokens'},'竞技场预算字段缺失或未知')
    require(type(budget['max_calls']) is int and len(profiles)<=budget['max_calls']<=8,'竞技场请求次数上限不足或非法')
    require(type(budget['max_output_tokens']) is int and sum(p.max_tokens if hasattr(p,'max_tokens') else p['max_tokens'] for p in profiles)<=budget['max_output_tokens']<=65536,'竞技场输出token总上限不足或非法')

def validate_quotes(quotes,size):
    require(type(quotes) in (tuple,list) and len(quotes)==size,'价格来源须逐配置对应')
    for q in quotes:
        if q is None:continue
        require(type(q) is dict and set(q)=={'input_per_million','output_per_million','currency','source'},'手工价格字段缺失或未知')
        require(all(type(q[k]) in (int,float) and isfinite(q[k]) and 0<=q[k]<=1e12 for k in ('input_per_million','output_per_million')),'手工价格须为明确有限非负数字')
        require(type(q['source']) is str and 0<len(q['source'].strip())<=500,'手工价格须注明来源，未核实不得当供应商账单')
        require(type(q['currency']) is str and 1<=len(q['currency'])<=12 and q['currency'].isascii() and q['currency'].isalpha(),'价格币种须为字母代码')

def cost_estimate(usage,quote):
    if quote is None:return dict(amount=None,currency=None,status='unknown_price',source=None)
    known=usage.get('prompt_tokens') is not None and usage.get('completion_tokens') is not None
    amount=(usage['prompt_tokens']*quote['input_per_million']+usage['completion_tokens']*quote['output_per_million'])/1_000_000 if known else None
    return dict(amount=amount,currency=quote['currency'].upper(),status='manual_usage_estimate' if known else 'unknown_usage',source=quote['source'],verified=False,note='作者手工价格 × 供应商报告usage；不是供应商账单')

def additional_records(state,tasks,candidates,results):
    tasks=deepcopy(tasks);candidates=list(candidates);results=list(results)
    for report in state.get('model_reports',[]):
        task=tasks.get(report['task_id'])
        if task and task['status']=='succeeded' and task['candidate_id'] is None:
            task['candidate_id']=report['id']
            candidates.append(dict(id=report['id'],task_id=task['id'],output_text=json.dumps(report['output'],ensure_ascii=False,sort_keys=True)))
    for task in state.get('chapter_planning_tasks',[]):
        events=[e for e in state.get('chapter_planning_events',[]) if e['task_id']==task['id']]
        if not events:continue
        last=events[-1];started=next((e for e in events if e['status']=='running'),None)
        # Only the terminal model candidate is comparable. Corrections/reviews
        # remain in their existing workflow, never silently change blind scores.
        terminal=next((e for e in events if e['kind']=='completed'),None)
        candidate=next((c for c in state.get('chapter_planning_candidates',[]) if terminal and c['id']==terminal['candidate_id'] and c['plan'] is not None and not c['errors']),None)
        status=last['status']
        tasks[task['id']]=dict(id=task['id'],chapter_id=task['chapter_id'],status=status,candidate_id=candidate['id'] if status=='succeeded' and candidate else None,
                              started_at=started['created_at'] if started else None,finished_at=last['created_at'] if status in ('succeeded','failed','cancelled','interrupted') else None)
        if candidate:candidates.append(dict(id=candidate['id'],task_id=task['id'],output_text=candidate['raw_text']))
    results.extend(state.get('chapter_planning_results',[]))
    return tasks,candidates,results

def validate_arena_experiment(e,state,children):
    from novel_writer.domain.experiments import SIDES,common_instruction,messages_sha
    require(state['workspace_version']>=VERSION,'多题型竞技场需要V38或更新工作区')
    size=len(e.profiles);require(2<=size<=8 and len(e.configurations)==size and {c.index for c in e.configurations}==set(range(size)) and {c.side for c in e.configurations}==set(SIDES[:size]),'竞技场须有2至8个独立匿名配置')
    require(0<len(e.title.strip())<=300 and 0<len(e.rubric.strip())<=2000 and len(e.instruction)<=2000 and 1<=e.source_revision<=state['revision'],'竞技场输入超限/来源编号非法')
    validate_budget(e.budget,e.profiles)
    validate_quotes(e.price_quotes,size)
    require(all(p.prompt_version==('review-json-1' if e.task_kind=='audit_chapter' else 'rewrite-1') for p in e.profiles),'竞技场配置与题型不兼容')
    tasks={t['id']:t for t in state.get('chapter_planning_tasks' if e.task_kind=='outline_chapter' else 'generation_tasks',[])};common=None
    for slot in e.configurations:
        require(slot.task_id in tasks and slot.task_id not in children,'竞技场任务悬空或复用');children.add(slot.task_id);task=tasks[slot.task_id];profile=encode(e.profiles[slot.index])
        require(task['chapter_id']==e.chapter_id,'竞技场目标章节不符')
        if e.task_kind=='outline_chapter':
            require(task['mode']=='outline' and e.planning_options is not None and task['source_options']==e.planning_options,'竞技场细纲来源不符')
            require(e.planning_options.get('include_writing_rules') is True and task['instruction']==common_instruction(e.instruction,e.rubric),'竞技场细纲未包含共同规则或评价要求')
            b=task['binding'];expected=dict(profile,adapter_id='chapter-planning-http-v1',source_adapter_id=profile['adapter_id'],prompt_version='chapter-outline-json-1')
            require({k:v for k,v in b.items() if k not in ('destination','configuration_stamp','request_body','request_sha256')}==expected,'竞技场细纲配置不符')
            body=canonical_messages(json.loads(b['request_body']),b['destination']['protocol'])
            snapshot=dict(source_guard=task['source_guard'],source_options=task['source_options'],context_text=task['context_text'],context_sha256=task['context_sha256'],messages=body)
            require(task['max_output_chars']==e.max_output_chars and task['timeout_ms']==e.timeout_ms,'竞技场细纲上限不符')
            require(digest(json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':')))==e.common_messages_sha256,'竞技场细纲共同消息不符')
        else:
            f=task['frozen'];p=dict(f['parameters']);b=p.pop('binding');require(task['task_type']==e.task_kind and f['source_revision']==e.source_revision,'竞技场题型或来源编号不符')
            require({k:v for k,v in b.items() if k not in ('request_body','request_sha256','destination')}==profile,'竞技场配置不符')
            require(e.planning_options is None and p['instruction']==common_instruction(e.instruction,e.rubric) and p['max_output_chars']==e.max_output_chars and p['timeout_ms']==e.timeout_ms,'竞技场共同参数不符')
            require(f['context_options']==encode(e.context_options) and f['context_sha256']==e.context_sha256 and any(d['kind']=='writing_rules' for d in f['dependencies']),'竞技场上下文或规则不符')
            require(messages_sha(f)==e.common_messages_sha256,'竞技场共同消息不符');snapshot=dict(f,parameters=p)
        require(common is None or common==snapshot,'竞技场配置未共享同一冻结来源');common=snapshot
