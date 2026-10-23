import {renderSampling,captureSampling,fillSampling,samplingOptions} from './sampling.js';
import {api} from './api.js';
import {renderCandidateCount,prepareWritingCandidates} from './writing_candidates.js';
import {escapeHTML as h} from './views.js';
import {diffLines} from './state.js';
import {connectionChoices,modelAdapterId} from './model_tasks.js';

const preparations=new Map(),tasks=new Map();
const emit=()=>window.dispatchEvent(new CustomEvent('novel-scene-expansion-dirty',{detail:[...preparations.values(),...tasks.values()].some(v=>v.dirty)}));
const pre=value=>'<pre class="context-text">'+h(typeof value==='string'?value:JSON.stringify(value,null,2))+'</pre>';
const text=(id,label,value)=>'<div class="field"><label for="'+id+'">'+label+'</label><textarea id="'+id+'">'+h(value)+'</textarea></div>';
const field=(id,label,value,type='text')=>'<div class="field"><label for="'+id+'">'+label+'</label><input id="'+id+'" type="'+type+'" value="'+h(value)+'"></div>';
const check=(id,label,value)=>'<label class="check-label"><input type="checkbox" id="'+id+'" '+(value?'checked':'')+'>'+label+'</label>';
const statuses={pending:'待本次确认',running:'执行中',succeeded:'候选完成',failed:'失败',cancelled:'已取消',interrupted:'已中断，需明确重新准备',candidate_ready:'候选完成',adopted:'已采纳'};
const key=(workspace,chapter)=>workspace.document.project.id+'/'+chapter;

function preparation(workspace,chapter,range){
 const id=key(workspace,chapter);
 if(!preparations.has(id)){preparations.set(id,{values:{kind:range?'selection':'scene',scene_order:String(workspace.document.chapter_outlines.find(v=>v.chapter_id===chapter)?.scenes?.[0]?.order||1),start:String(range?.[0]??0),end:String(range?.[1]??0),instruction:'',chars:'600',characters:workspace.document.characters.map(v=>v.id),world:true,rules:true,facts:true,budget:'16000',connection:'',model:'',temperature:'.3',tokens:'1024',risk:'1',unknown:false},source:null,payload:null,dirty:false});}
 return preparations.get(id);
}
function sourceOptions(chapter,values){return {chapter_id:chapter,...(values.ruleTask?{rule_task_id:values.ruleTask}:{}),target_kind:values.kind,scene_order:values.kind==='scene'?Number(values.scene_order):null,selection_start:values.kind==='selection'?Number(values.start):null,selection_end:values.kind==='selection'?Number(values.end):null,instruction:values.instruction,target_chars:Number(values.chars),character_ids:[...values.characters],include_worldbuilding:values.world,include_writing_rules:values.rules,include_facts:values.facts,context_budget_chars:Number(values.budget)};}

export function renderSceneExpansionPrepare(workspace,chapterId,range,caps){
 const chapter=workspace.document.chapters.find(v=>v.id===chapterId);if(!chapter)return '<section class="panel"><p>请先创建并保存实际章节。</p></section>';
 const d=preparation(workspace,chapterId,range),v=d.values,outline=workspace.document.chapter_outlines.find(v=>v.chapter_id===chapterId);
 return '<section id="scene-expansion-prepare" class="panel"><h2>场景 / 选区扩写（AI）</h2><p>只扩写一个已采纳场景或一个非空正文选区。冻结当前正文与范围；候选采用后只替换该范围，范围外原文逐字节保留，不整章替换、不写人物/地点实体。</p>'+
  '<div class="field"><label for="expansion-kind">扩写目标</label><select id="expansion-kind"><option value="scene" '+(v.kind==='scene'?'selected':'')+'>已采纳细纲场景（按序号）</option><option value="selection" '+(v.kind==='selection'?'selected':'')+'>正文选区（Unicode 码点）</option></select></div>'+
  (outline&&outline.scenes.length?'<div class="field"><label for="expansion-scene">场景序号</label><select id="expansion-scene">'+outline.scenes.map(s=>'<option value="'+s.order+'" '+(String(s.order)===v.scene_order?'selected':'')+'>第'+s.order+'场 · '+h(s.summary)+' · '+h(s.location)+'</option>').join('')+'</select></div>':'<p class="error">本章没有已采纳细纲场景；请先完成章节构思与细纲采纳，或改选正文选区。</p>')+
  '<div class="field-grid">'+field('expansion-start','选区起始码点',v.start,'number')+field('expansion-end','选区结束码点（不含）',v.end,'number')+'</div><p>选区按 Unicode 码点计；空选区不能扩写。场景目标在正文末尾插入，原文全部保留。</p>'+
  '<label>本次任务规则身份（在规则页创建）<select id="expansion-rule-task"><option value="">不使用单任务规则</option>'+(workspace.rule_task_bindings||[]).filter(t=>t.chapter_id===chapterId&&t.task_type==='expand_scene_selection').map(t=>'<option value="'+h(t.id)+'" '+(v.ruleTask===t.id?'selected':'')+'>'+h(t.id)+'</option>').join('')+'</select></label>'+text('expansion-instruction','本次扩写要求',v.instruction)+field('expansion-chars','目标新增字符数',v.chars,'number')+
  '<div class="field"><label for="expansion-characters">明确选入的本书人物</label><select id="expansion-characters" multiple size="5">'+workspace.document.characters.map(c=>'<option value="'+h(c.id)+'" '+(v.characters.includes(c.id)?'selected':'')+'>'+h(c.name)+' · '+h(c.role||'')+'</option>').join('')+'</select></div>'+
  check('expansion-world','选入已保存世界观',v.world)+check('expansion-rules','选入写作规则',v.rules)+check('expansion-facts','选入当前位置已确认且不过期的记忆事实',v.facts)+field('expansion-budget','上下文字符预算（512至24000）',v.budget,'number')+
  '<h3>正文用途预设与本次覆盖</h3><label for="expansion-connection">本次模型连接（留空使用正文预设）</label><select id="expansion-connection"><option value="">使用预设</option>'+connectionChoices(caps).map(([id,label])=>'<option value="'+h(id)+'" '+(id===v.connection?'selected':'')+'>'+h(label)+'</option>').join('')+'</select>'+
  field('expansion-model','本次模型编号（可覆盖）',v.model)+field('expansion-temperature','温度',v.temperature,'number')+field('expansion-tokens','输出token上限',v.tokens,'number')+renderSampling('expansion',v.sampling)+field('expansion-risk','单次风险预算（美元，非硬封顶）',v.risk,'number')+check('expansion-unknown','允许本次费用未知，执行前仍须单次确认',v.unknown)+
  ''+renderCandidateCount('expansion',v.candidates)+'<button id="expansion-source-preview" type="button">预览冻结范围与本书资料（不联网）</button><button id="expansion-freeze" type="button" '+(!d.source||!caps.real_model_enabled?'disabled':'')+'>冻结本次扩写请求（不发送）</button><button id="expansion-open-settings" type="button">模型与预设设置</button><button id="expansion-back-editor" type="button">返回正文</button>'+
  '<p id="expansion-operation" role="status">'+(caps.real_model_enabled?'模型会话已开启，每一任务仍须单独确认。':'当前完全手动；开启模型会话后才可冻结请求。')+'</p>'+
  (d.source?'<details open><summary>冻结范围与来源</summary><p>范围 '+d.source.source_options.selection_start+'–'+d.source.source_options.selection_end+' · 正文 '+d.source.guard.body_chars+' 字符 · 来源 '+h(d.source.source_sha256.slice(0,16))+'…</p>'+pre(d.source.context_text)+'</details>':'')+'</section>';
}

export function bindSceneExpansionPrepare(root,workspace,chapter,range,caps,hooks){
 if(!root||root.dataset.bound)return;root.dataset.bound='true';const d=preparation(workspace,chapter,range),base='/api/projects/'+encodeURIComponent(workspace.document.project.id)+'/scene-expansion';let busy=false;
 const read=()=>{d.values.candidates=root.querySelector('#expansion-candidates').value;
  d.values.ruleTask=root.querySelector('#expansion-rule-task')?.value||'';
  d.values.sampling=captureSampling(root);for(const [name,id] of Object.entries({kind:'expansion-kind',scene_order:'expansion-scene',start:'expansion-start',end:'expansion-end',instruction:'expansion-instruction',chars:'expansion-chars',budget:'expansion-budget',connection:'expansion-connection',model:'expansion-model',temperature:'expansion-temperature',tokens:'expansion-tokens',risk:'expansion-risk'})){const e=root.querySelector('#'+id);if(e)d.values[name]=e.value;}
  d.values.characters=[...root.querySelector('#expansion-characters').selectedOptions].map(v=>v.value);
  d.values.sampling=captureSampling(root);for(const [name,id] of Object.entries({world:'expansion-world',rules:'expansion-rules',facts:'expansion-facts',unknown:'expansion-unknown'})){const e=root.querySelector('#'+id);if(e)d.values[name]=e.checked;}
 };
 const changed=()=>{read();d.source=null;d.payload=null;d.dirty=true;const b=root.querySelector('#expansion-freeze');if(b)b.disabled=true;emit();};
 root.addEventListener('input',changed);root.addEventListener('change',changed);
 async function operation(fn){if(busy)return;busy=true;hooks.busy(true);try{await fn();}catch(error){hooks.notice(error.message,true);}finally{busy=false;hooks.busy(false);}}
 root.addEventListener('click',event=>{const b=event.target.closest('button');if(!b)return;
  if(b.id==='expansion-open-settings'){event.stopPropagation();return hooks.settings();}
  if(b.id==='expansion-back-editor'){event.stopPropagation();return hooks.editor();}
  if(b.id==='expansion-source-preview'){event.stopPropagation();read();void operation(async()=>{d.source=await api(base+'/preview',{method:'POST',body:JSON.stringify(sourceOptions(chapter,d.values))});d.payload=null;await hooks.refresh();});}
  if(b.id==='expansion-freeze'){event.stopPropagation();read();void operation(async()=>{
   if(!caps.real_model_enabled)throw Error('请先在设置明确开启模型会话。');if(!d.source)throw Error('请先预览冻结范围。');if(!d.values.characters.length)throw Error('请至少选择一个本书人物。');
   const v=d.values,override=v.connection&&v.model;if(override&&!v.unknown)throw Error('请核对风险预算并明确允许费用未知。');
   if(!d.payload)d.payload={operation_id:v.ruleTask||crypto.randomUUID(),source_options:sourceOptions(chapter,v),source_sha256:d.source.source_sha256,model_options:override?{...samplingOptions(v.sampling),adapter_id:modelAdapterId(v.connection),connection_id:v.connection,model_id:v.model,temperature:Number(v.temperature),max_tokens:Number(v.tokens),budget_limit:Number(v.risk),allow_unknown_cost:v.unknown,prompt_version:'rewrite-1'}:null,max_output_chars:12000,timeout_ms:30000};
   const result=await prepareWritingCandidates(workspace.document.project.id,'scene_expansion',base,d.payload,Number(d.values.candidates||1));d.dirty=false;emit();if(result.experiment_id)await hooks.compared(result.experiment_id);else await hooks.prepared(result.task.id);
  });}
 });
}

function taskState(data){const id=data.task.id;if(!tasks.has(id))tasks.set(id,{text:data.latest_candidate?.text||'',candidateId:data.latest_candidate?.id||null,review:null,pending:null,dirty:false});const d=tasks.get(id);if(!d.dirty&&d.candidateId!==(data.latest_candidate?.id||null)){d.text=data.latest_candidate?.text||'';d.candidateId=data.latest_candidate?.id||null;d.review=null;d.pending=null;}return d;}
export function renderSceneExpansionTask(workspace,listing,data,caps){
 const task=data.task,d=taskState(data),candidate=data.latest_candidate,adopted=data.adoptions.length>0,review=d.review,raw=data.responses.at(-1)?.response||data.late_results?.at(-1)?.response;
 return '<section id="scene-expansion-task" class="panel"><h2>扩写任务与候选</h2><label for="expansion-task-select">已保存任务</label><select id="expansion-task-select">'+listing.tasks.map(v=>'<option value="'+h(v.task.id)+'" '+(v.task.id===task.id?'selected':'')+'>'+h(v.task.target_kind==='scene'?'场景 '+v.task.scene_order:'选区 '+v.task.selection_start+'–'+v.task.selection_end)+' · '+h(statuses[v.display_status]||v.display_status)+' · '+h(v.task.id.slice(0,8))+'</option>').join('')+'</select>'+
  '<p id="expansion-status" data-status="'+h(data.display_status)+'">'+h(statuses[data.display_status]||data.display_status)+' '+h(task.error_code||'')+'</p><p>范围 '+task.selection_start+'–'+task.selection_end+' · 原正文 '+task.source_guard.body_chars+' 字符 · 请求模型 '+h(task.binding.model_id)+'。</p>'+
  '<details><summary>冻结去向</summary>'+pre(task.binding.destination)+'</details><details open><summary>本次确切外发请求</summary><pre id="expansion-frozen-request" class="context-text">'+h(task.binding.request_body)+'</pre></details>'+
  check('expansion-confirm-request','我已核对本次范围、内容、去向、模型、预算与未知费用',false)+
  '<button id="expansion-execute" type="button" '+(!caps.real_model_enabled||data.status!=='pending'||data.display_status==='interrupted'?'disabled':'')+'>单次确认执行</button><button id="expansion-cancel" type="button" '+(['pending','running'].includes(data.status)?'':'disabled')+'>取消本次任务</button><button id="expansion-task-refresh" type="button">刷新状态</button><button id="expansion-task-back-editor" type="button">返回正文</button>'+
  (data.display_status==='interrupted'?'<p class="error">旧会话/恢复不继承执行许可；请重新准备，不会自动重发。</p>':'')+(!data.source_fresh&&!adopted?'<p class="error">正文、选区、细纲、人物、资料、规则、风格、锁或配置已变化，旧候选不能采纳。</p>':'')+
  (candidate?'<h3>扩写候选（仅替换/插入该范围）</h3><p>正式正文尚未改变。人工修正只保存候选历史。</p><textarea id="expansion-candidate-text" rows="12">'+h(d.text)+'</textarea><button id="expansion-save-correction" type="button" '+(adopted?'disabled':'')+'>保存人工修正（不写正文）</button><button id="expansion-review" type="button" '+(adopted||d.dirty||!data.source_fresh?'disabled':'')+'>复核具体差异</button>'+
   (review?'<h3>本次明确复核的范围差异</h3><div id="expansion-reviewed-diff"><p>选区前：'+h(review.selected_before||'（空，末尾插入）')+'</p><p>选区后：'+h(review.selected_after)+'</p>'+pre(diffLines(review.before_text,review.after_text).map(v=>(v.kind==='add'?'+ ':v.kind==='remove'?'- ':'  ')+v.text).join('\n'))+'</div>'+check('expansion-confirm-adopt','我已逐字核对，明确采纳此范围扩写',false)+check('expansion-confirm-chapter','我确认目标是本书当前章节',false)+check('expansion-authorize-confirmed','若为已确认章节，我明确授权生成正文新版本',false)+'<button id="expansion-adopt" type="button" '+(adopted||!data.source_fresh?'disabled':'')+'>明确采纳为正文新版本</button>':'')+
   (adopted?'<p id="expansion-adopted">已生成正文新版本 · 保存编号 '+data.adoptions[0].applied_revision+'</p><button id="expansion-open-body" type="button">返回正文查看新版本</button>':'')+
   '<details><summary>原始响应、修正与采纳历史</summary>'+pre(data.candidates)+pre(data.reviews)+pre(data.adoptions)+'</details>'+(raw?'<details><summary>实际原始响应</summary>'+pre({reported_model:raw.reported_model,usage:raw.usage,complete:raw.complete,error_code:raw.error_code})+'<pre class="context-text">'+h(raw.raw_response)+'</pre></details>':'')
   :'<p>尚无可采纳候选。失败、部分输出、取消与迟到不会写正文，也不自动重试。</p>')+'</section>';
}
export function bindSceneExpansionTask(root,workspace,data,hooks){
 if(!root||root.dataset.bound)return;root.dataset.bound='true';const task=data.task,d=taskState(data),base='/api/projects/'+encodeURIComponent(workspace.document.project.id)+'/scene-expansion/'+encodeURIComponent(task.id);let busy=false;
 const area=root.querySelector('#expansion-candidate-text');if(area)area.addEventListener('input',()=>{d.text=area.value;d.dirty=true;d.review=null;d.pending=null;const b=root.querySelector('#expansion-review');if(b)b.disabled=true;emit();});
 const select=root.querySelector('#expansion-task-select');if(select)select.addEventListener('change',()=>hooks.select(select.value));
 root.addEventListener('click',event=>{const b=event.target.closest('button');if(!b)return;if(b.id==='expansion-task-back-editor'||b.id==='expansion-open-body'){event.stopPropagation();return hooks.editor();}if(b.id==='expansion-task-refresh'){event.stopPropagation();return hooks.refresh();}if(busy)return;busy=true;hooks.busy(true);void(async()=>{try{
  if(b.id==='expansion-execute'){if(!root.querySelector('#expansion-confirm-request').checked)throw Error('请先勾选本次确切请求确认。');await api(base+'/execute',{method:'POST',body:JSON.stringify({confirm_external:true,request_sha256:task.binding.request_sha256})});}
  else if(b.id==='expansion-cancel')await api(base+'/cancel',{method:'POST',body:'{}'});
  else if(b.id==='expansion-save-correction'){const result=await api('/api/projects/'+encodeURIComponent(workspace.document.project.id)+'/scene-expansion/correct',{method:'POST',body:JSON.stringify({operation_id:crypto.randomUUID(),task_id:task.id,candidate_id:data.latest_candidate.id,text:d.text})});d.candidateId=result.latest_candidate.id;d.dirty=false;d.review=null;d.pending=null;emit();}
  else if(b.id==='expansion-review'){if(d.dirty)throw Error('请先保存人工修正，再复核。');d.review=await api('/api/projects/'+encodeURIComponent(workspace.document.project.id)+'/scene-expansion/review',{method:'POST',body:JSON.stringify({operation_id:crypto.randomUUID(),task_id:task.id,candidate_id:data.latest_candidate.id,candidate_sha256:data.latest_candidate.data_sha256})});d.pending=null;}
  else if(b.id==='expansion-adopt'){if(!d.review||d.dirty)throw Error('请先复核具体范围差异。');if(!root.querySelector('#expansion-confirm-adopt').checked||!root.querySelector('#expansion-confirm-chapter').checked)throw Error('请勾选差异与目标章节确认。');const authorized=root.querySelector('#expansion-authorize-confirmed').checked;if(!d.pending||d.pending.authorize_confirmed!==authorized)d.pending={operation_id:crypto.randomUUID(),task_id:task.id,candidate_id:data.latest_candidate.id,candidate_sha256:data.latest_candidate.data_sha256,review_id:d.review.id,review_sha256:d.review.review_sha256,expected_revision:data.revision,confirm_chapter:true,authorize_confirmed:authorized};await api('/api/projects/'+encodeURIComponent(workspace.document.project.id)+'/scene-expansion/accept',{method:'POST',body:JSON.stringify(d.pending)});d.dirty=false;emit();}
  else return;await hooks.refresh();
 }catch(error){hooks.notice(error.message,true);}finally{busy=false;hooks.busy(false);}})();});
}
