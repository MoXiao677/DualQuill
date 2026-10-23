"""人工记忆显式写入/复核，确认与来源新鲜度分离。"""
from copy import deepcopy
from uuid import uuid4
from novel_writer.domain.models import DataValidationError,utc_now
from novel_writer.domain.memory import capture_source,outdated,MemoryRecord
from novel_writer.application.fields import check_fields,text

KINDS={'book_summary','volume_summary','chapter_summary','character_state','event','foreshadow','payoff'}
def records(state):
    return [dict(deepcopy(m),outdated=outdated(state,m['source'])) for m in state.get('memories',[])]

def save(state,action,values):
    allowed={'memory_id','kind','title','text','position_chapter_id','character_id','volume_number','confirmed','active','source'}
    check_fields(values,allowed if action=='save_memory' else {'memory_id','confirmed','source'})
    result=deepcopy(state);result['workspace_version']=max(state['workspace_version'],2)
    result.setdefault('memories',[]);result.setdefault('memory_history',[])
    identifier=values.get('memory_id');existing=next((m for m in result['memories'] if m['id']==identifier),None)
    if identifier is not None and existing is None:raise DataValidationError('记忆不存在或不属于当前书')
    if action!='save_memory' and existing is None:raise DataValidationError('请先选择本书记忆')
    now=utc_now()
    if existing is None:
        required={'kind','title','text','position_chapter_id','source'}
        if not required<=set(values):raise DataValidationError('新增记忆缺少类别/正文/故事位置/出处')
        memory=dict(id=str(uuid4()),project_id=state['document']['project']['id'],revision=1,
            kind=values['kind'],title=values['title'],text=values['text'],position_chapter_id=values['position_chapter_id'],
            character_id=values.get('character_id'),volume_number=values.get('volume_number'),confirmed=values.get('confirmed',False),
            active=values.get('active',True),source=capture_source(state,values['source']),created_at=now,updated_at=now)
        action_name='create';result['memories'].append(memory)
    else:
        memory=existing
        if action=='archive_memory':memory['active']=False;action_name='archive'
        elif action=='review_memory':
            memory['source']=capture_source(state,values.get('source',{'kind':memory['source']['kind'],'entity_id':memory['source']['entity_id']}))
            memory['confirmed']=values.get('confirmed',True);action_name='review'
        else:
            for name in allowed-{'memory_id','source'}:
                if name in values:memory[name]=values[name]
            if 'source' in values and values['source']!={'kind':memory['source']['kind'],'entity_id':memory['source']['entity_id']}:
                raise DataValidationError('更换/更新出处请使用显式复核')
            action_name='edit'
        memory['revision']+=1;memory['updated_at']=now
    if memory['kind'] not in KINDS:raise DataValidationError('未知记忆类别')
    memory['title']=text(memory['title'],'记忆标题',required=True);text(memory['text'],'记忆正文')
    previous=[h for h in result['memory_history'] if h['memory_id']==memory['id']]
    result['memory_history'].append(dict(id=str(uuid4()),memory_id=memory['id'],revision=memory['revision'],
        previous_version_id=previous[-1]['id'] if previous else None,snapshot=deepcopy(memory),saved_at=now,action=action_name))
    return result
