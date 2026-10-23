import {api} from './api.js';

const groups=new Map();
export function renderCandidateCount(prefix,value='1'){
 return '<div class="field"><label for="'+prefix+'-candidates">同一冻结输入的候选数量</label><select id="'+prefix+'-candidates">'+[1,2,3,4,5,6].map(n=>'<option value="'+n+'" '+(String(n)===String(value)?'selected':'')+'>'+n+(n===1?' 个（原单候选流程）':' 个（逐请求核对预算、确认后盲评）')+'</option>').join('')+'</select></div><p>多候选只准备独立任务，不发送请求；选中候选后仍须人工修正、复核具体范围差异并正式采纳。</p>';
}
export async function prepareWritingCandidates(project,kind,base,payload,count){
 if(!Number.isInteger(count)||count<1||count>6)throw Error('候选数量须为1至6。');
 if(count===1)return api(base+'/prepare',{method:'POST',body:JSON.stringify(payload)});
 if(payload.rule_task_id||payload.source_options?.rule_task_id||payload.context_options?.rule_task_id||payload.source_options?.context_options?.rule_task_id)throw Error('单任务规则绑定只属于一个请求，请选择1个候选；多个候选须分别准备各自的任务规则。');
 const identityField=kind==='chapter_writing'?'request_id':'operation_id',key=project+'/'+kind+'/'+payload[identityField]+'/'+count;
 let group=groups.get(key);
 if(!group){group={id:crypto.randomUUID(),requests:Array.from({length:count},(_,i)=>({...payload,[identityField]:i===0?payload[identityField]:crypto.randomUUID()}))};groups.set(key,group);}
 const taskIds=[];
 for(const request of group.requests){const result=await api(base+'/prepare',{method:'POST',body:JSON.stringify(request)});taskIds.push(result.task.id);}
 const current=await api('/api/projects/'+encodeURIComponent(project));
 if(!group.request)group.request={experiment_id:group.id,title:'逐段多候选 · '+({scene_expansion:'场景 / 选区扩写',chapter_planning:'章节构思 / 细纲',chapter_writing:'初稿 / 续写'}[kind]),task_kind:kind,task_ids:taskIds,expected_revision:current.revision};
 return api('/api/projects/'+encodeURIComponent(project)+'/comparisons',{method:'POST',body:JSON.stringify(group.request)});
}
