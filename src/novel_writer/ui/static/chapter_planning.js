import {renderSampling,captureSampling,fillSampling,samplingOptions} from './sampling.js';
import {api} from './api.js';
import {renderCandidateCount,prepareWritingCandidates} from './writing_candidates.js';
import {escapeHTML as h} from './views.js';
import {connectionChoices,modelAdapterId} from './model_tasks.js';

const preparations=new Map(),tasks=new Map();
const emit=()=>window.dispatchEvent(new CustomEvent('novel-chapter-planning-dirty',{detail:[...preparations.values(),...tasks.values()].some(v=>v.dirty)}));
const pre=value=>'<pre class="context-text">'+h(typeof value==='string'?value:JSON.stringify(value,null,2))+'</pre>';
const text=(id,label,value)=>'<div class="field"><label for="'+id+'">'+label+'</label><textarea id="'+id+'">'+h(value)+'</textarea></div>';
const field=(id,label,value,type='text')=>'<div class="field"><label for="'+id+'">'+label+'</label><input id="'+id+'" type="'+type+'" value="'+h(value)+'"></div>';
const check=(id,label,value)=>'<label class="check-label"><input type="checkbox" id="'+id+'" '+(value?'checked':'')+'>'+label+'</label>';
const modes={brainstorm:'IDEA 构思',outline:'章节细纲与场景'};
const statuses={pending:'待本次确认',running:'执行中',succeeded:'候选完成',failed:'候选需修正',cancelled:'已取消',interrupted:'已中断，需明确重新准备',candidate_ready:'候选完成',needs_correction:'需人工修正',adopted:'已采纳'};
const key=(workspace,chapter)=>workspace.document.project.id+'/'+chapter;

function preparation(workspace,chapter,mode){
 const id=key(workspace,chapter);
 if(!preparations.has(id)){
  const settings=window.__novelCreationSettings||null,step=settings?.steps?.find(v=>v.step===mode);
  preparations.set(id,{values:{sampling:step?.sampling,instruction:'',characters:workspace.document.characters.map(v=>v.id),world:true,rules:true,facts:true,locations:true,budget:'12000',connection:step?.connection_id||'',model:step?.model_id||'',temperature:String(step?.temperature??.3),tokens:String(step?.max_tokens??768),risk:String(step?.budget_limit??1),unknown:step?.allow_unknown_cost??false},source:null,payload:null,dirty:false});
 }
 return preparations.get(id);
}

function sourceOptions(chapter,mode,values){
 return {chapter_id:chapter,mode,...(values.ruleTask?{rule_task_id:values.ruleTask}:{}),instruction:values.instruction,character_ids:[...values.characters],include_worldbuilding:values.world,include_writing_rules:values.rules,include_facts:values.facts,include_locations:values.locations,context_budget_chars:Number(values.budget)};
}

export function renderChapterPlanningPrepare(workspace,chapterId,mode,caps){
 const chapter=workspace.document.chapters.find(v=>v.id===chapterId);if(!chapter)return '<section class="panel"><p>请先创建并保存实际章节。</p></section>';
 const d=preparation(workspace,chapterId,mode),v=d.values;
 return '<section id="chapter-planning-prepare" class="panel"><h2>章节构思与细纲（AI）</h2><p>只读取本书已保存章节、人物、世界观、位置、已确认事实、写作规则与所选文风。候选不会自动写入，也不会创建人物、地点或正文。</p>'+
  '<div class="field"><label for="planning-mode">本次步骤</label><select id="planning-mode"><option value="brainstorm" '+(mode==='brainstorm'?'selected':'')+'>IDEA 构思</option><option value="outline" '+(mode==='outline'?'selected':'')+'>章节细纲与场景节拍</option></select></div>'+
  '<label>本次任务规则身份（在规则页创建）<select id="planning-rule-task"><option value="">不使用单任务规则</option>'+(workspace.rule_task_bindings||[]).filter(t=>t.chapter_id===chapterId&&t.task_type===(mode==='brainstorm'?'brainstorm_chapter':'outline_chapter')).map(t=>'<option value="'+h(t.id)+'" '+(v.ruleTask===t.id?'selected':'')+'>'+h(t.id)+'</option>').join('')+'</select></label>'+text('planning-instruction','给模型的本章要求',v.instruction)+
  '<div class="field"><label for="planning-characters">明确选入的本书记载人物（目标人物必须已存在）</label><select id="planning-characters" multiple size="6">'+workspace.document.characters.map(c=>'<option value="'+h(c.id)+'" '+(v.characters.includes(c.id)?'selected':'')+'>'+h(c.name)+' · '+h(c.role||'')+'</option>').join('')+'</select></div>'+
  check('planning-world','选入已保存世界观',v.world)+check('planning-rules','选入写作规则',v.rules)+check('planning-facts','选入当前位置已确认且不过期的记忆事实',v.facts)+check('planning-locations','选入书中已保存的场景位置名称',v.locations)+
  field('planning-budget','上下文字符预算（512至24000）',v.budget,'number')+
  '<h3>构思/细纲用途预设与本次覆盖</h3><label for="planning-connection">本次模型连接（留空使用预设）</label><select id="planning-connection"><option value="">使用预设</option>'+connectionChoices(caps).map(([id,label])=>'<option value="'+h(id)+'" '+(id===v.connection?'selected':'')+'>'+h(label)+'</option>').join('')+'</select>'+
  field('planning-model','本次模型编号（可覆盖）',v.model)+field('planning-temperature','温度',v.temperature,'number')+field('planning-tokens','输出token上限',v.tokens,'number')+renderSampling('planning',v.sampling)+field('planning-risk','单次风险预算（美元，非硬封顶）',v.risk,'number')+check('planning-unknown','允许本次费用未知，执行前仍须单次确认',v.unknown)+
  ''+renderCandidateCount('planning',v.candidates)+'<button id="planning-source-preview" type="button">预览本书实际输入（不联网）</button><button id="planning-freeze" type="button" '+(!d.source||!caps.real_model_enabled?'disabled':'')+'>冻结本次构思请求（不发送）</button><button id="planning-open-settings" type="button">模型与预设设置</button><button id="planning-back-editor" type="button">返回正文</button>'+
  '<p id="planning-operation" role="status">'+(caps.real_model_enabled?'模型会话已开启，每一任务仍须单独确认外发。':'当前完全手动；可预览来源，开启模型会话后才可冻结请求。')+'</p>'+
  (d.source?'<details open><summary>实际来源、预算与提示</summary><p>来源指纹 '+h(d.source.source_sha256.slice(0,16))+'… · 字符预算 '+d.source.source_options.context_budget_chars+'</p>'+pre(d.source.context_text)+'</details>':'')+'</section>';
}

export function bindChapterPlanningPrepare(root,workspace,chapter,mode,caps,hooks){
 if(!root||root.dataset.bound)return;root.dataset.bound='true';const d=preparation(workspace,chapter,mode),form=root.querySelector('form')||root;const base='/api/projects/'+encodeURIComponent(workspace.document.project.id)+'/chapter-planning';let busy=false;
 const selectedMode=()=>root.querySelector('#planning-mode')?.value||mode;
 const read=()=>{d.values.candidates=root.querySelector('#planning-candidates').value;
  d.values.ruleTask=root.querySelector('#planning-rule-task')?.value||'';
  d.values.instruction=root.querySelector('#planning-instruction').value;
  d.values.characters=[...root.querySelector('#planning-characters').selectedOptions].map(v=>v.value);
  d.values.sampling=captureSampling(root);for(const [name,id] of Object.entries({world:'planning-world',rules:'planning-rules',facts:'planning-facts',locations:'planning-locations',unknown:'planning-unknown'})){const e=root.querySelector('#'+id);d.values[name]=e.checked;}
  d.values.sampling=captureSampling(root);for(const [name,id] of Object.entries({budget:'planning-budget',connection:'planning-connection',model:'planning-model',temperature:'planning-temperature',tokens:'planning-tokens',risk:'planning-risk'})){d.values[name]=root.querySelector('#'+id).value;}
 };
 const changed=()=>{read();d.source=null;d.payload=null;d.dirty=true;const b=root.querySelector('#planning-freeze');if(b)b.disabled=true;emit();};
 root.addEventListener('input',changed);root.addEventListener('change',changed);
 const modeSelect=root.querySelector('#planning-mode');if(modeSelect)modeSelect.addEventListener('change',()=>hooks.mode(modeSelect.value));
 async function operation(fn){if(busy)return;busy=true;hooks.busy(true);try{await fn();}catch(error){hooks.notice(error.message,true);}finally{busy=false;hooks.busy(false);}}
 root.addEventListener('click',event=>{
  const b=event.target.closest('button');if(!b)return;
  if(b.id==='planning-open-settings'){event.stopPropagation();return hooks.settings();}
  if(b.id==='planning-back-editor'){event.stopPropagation();return hooks.editor();}
  if(b.id==='planning-source-preview'){event.stopPropagation();read();void operation(async()=>{d.source=await api(base+'/preview',{method:'POST',body:JSON.stringify(sourceOptions(chapter,selectedMode(),d.values))});d.payload=null;await hooks.refresh();});}
  if(b.id==='planning-freeze'){event.stopPropagation();submit(event);}
 });
 const submit=event=>{event.preventDefault();event.stopPropagation();read();void operation(async()=>{
  if(!caps.real_model_enabled)throw Error('请先在设置明确开启模型会话。');
  if(!d.source)throw Error('请先预览本书实际输入。');
  if(!d.values.characters.length)throw Error('请至少选择一个本书人物。');
  const v=d.values,override=v.connection&&v.model;
  if(!override&&!caps.connections?.some(()=>true)){/* preset may still be configured */}
  if(override&&!v.unknown)throw Error('请核对风险预算并明确允许费用未知。');
  if(!d.payload)d.payload={operation_id:v.ruleTask||crypto.randomUUID(),source_options:sourceOptions(chapter,selectedMode(),v),source_sha256:d.source.source_sha256,model_options:override?{...samplingOptions(v.sampling),adapter_id:modelAdapterId(v.connection),connection_id:v.connection,model_id:v.model,temperature:Number(v.temperature),max_tokens:Number(v.tokens),budget_limit:Number(v.risk),allow_unknown_cost:v.unknown,prompt_version:'rewrite-1'}:null,max_output_chars:12000,timeout_ms:30000};
  const result=await prepareWritingCandidates(workspace.document.project.id,'chapter_planning',base,d.payload,Number(d.values.candidates||1));d.dirty=false;emit();if(result.experiment_id)await hooks.compared(result.experiment_id);else await hooks.prepared(result.task.id);
 });};
 form.addEventListener('submit',submit);
}

function taskState(data){const id=data.task.id;if(!tasks.has(id))tasks.set(id,{text:data.latest_candidate?.raw_text||'',candidateId:data.latest_candidate?.id||null,review:null,pending:null,dirty:false});const d=tasks.get(id);if(!d.dirty&&d.candidateId!==(data.latest_candidate?.id||null)){d.text=data.latest_candidate?.raw_text||'';d.candidateId=data.latest_candidate?.id||null;d.review=null;d.pending=null;}return d;}
function changeText(review){if(review.mode==='brainstorm')return '<p>IDEA 前：'+h(review.before.idea||'')+'</p><p>IDEA 后：'+h(review.after.idea||'')+'</p>';
 const rows=[];for(const name of ['core_idea','objective','story_time','character_ids']){if(JSON.stringify(review.before[name])!==JSON.stringify(review.after[name]))rows.push('<li>'+h(name)+'：'+h(JSON.stringify(review.before[name]))+' → '+h(JSON.stringify(review.after[name]))+'</li>');}
 if(JSON.stringify(review.before.scenes)!==JSON.stringify(review.after.scenes))rows.push('<li>scenes：<pre class="context-text">'+h(JSON.stringify(review.after.scenes,null,2))+'</pre></li>');
 return '<ul>'+rows.join('')+'</ul>';}

export function renderChapterPlanningTask(workspace,listing,data,caps){
 const task=data.task,d=taskState(data),candidate=data.latest_candidate,adopted=data.adoptions.length>0,review=d.review;
 const raw=data.responses.at(-1)?.response||data.late_results?.at(-1)?.response;
 return '<section id="chapter-planning-task" class="panel"><h2>章节构思任务与候选</h2><label for="planning-task-select">已保存任务</label><select id="planning-task-select">'+listing.tasks.map(v=>'<option value="'+h(v.task.id)+'" '+(v.task.id===task.id?'selected':'')+'>'+h(modes[v.task.mode])+' · '+h(statuses[v.display_status]||v.display_status)+' · '+h(v.task.id.slice(0,8))+'</option>').join('')+'</select>'+
 '<p id="planning-status" data-status="'+h(data.display_status)+'">'+h(statuses[data.display_status]||data.display_status)+' '+h(task.error_code||'')+'</p>'+
 '<p>请求模型 '+h(task.binding.model_id)+' · 输出上限 '+task.binding.max_tokens+' token · 风险声明 '+task.binding.budget_limit+' 美元。</p>'+
 '<details><summary>冻结去向</summary>'+pre(task.binding.destination)+'</details><details open><summary>本次确切外发请求</summary><pre id="planning-frozen-request" class="context-text">'+h(task.binding.request_body)+'</pre></details>'+
 check('planning-confirm-request','我已核对本次内容、去向、模型、预算与未知费用',false)+
 '<button id="planning-execute" type="button" '+(!caps.real_model_enabled||data.status!=='pending'||data.display_status==='interrupted'?'disabled':'')+'>单次确认执行</button><button id="planning-cancel" type="button" '+(['pending','running'].includes(data.status)?'':'disabled')+'>取消本次任务</button><button id="planning-refresh" type="button">刷新状态</button><button id="planning-back-editor" type="button">返回正文</button>'+
 (data.display_status==='interrupted'?'<p class="error">旧会话/恢复不继承执行许可；请重新预览并准备新任务，系统不会自动重发。</p>':'')+
 (!data.source_fresh&&!adopted?'<p class="error">IDEA、细纲、人物、资料、规则、风格、锁或配置已变化，旧候选不能再采纳。</p>':'')+
 (candidate?'<h3>结构化候选</h3><p>人工修正只保存候选历史；正式 IDEA/细纲在明确采纳前不变。</p><textarea id="planning-candidate-text" rows="14">'+h(d.text)+'</textarea><button id="planning-save-correction" type="button" '+(adopted?'disabled':'')+'>保存人工修正（不写入）</button><button id="planning-review" type="button" '+(adopted||d.dirty||!data.source_fresh?'disabled':'')+'>复核具体差异</button>'+
  (review?'<h3>本次明确复核的差异</h3><div id="planning-reviewed-diff">'+changeText(review)+'</div>'+check('planning-confirm-adopt','我已核对具体差异，明确采纳到真实 IDEA/章节细纲',false)+check('planning-confirm-chapter','我确认目标是本书当前这一章',false)+'<button id="planning-adopt" type="button" '+(adopted||!data.source_fresh?'disabled':'')+'>明确采纳</button>':'')+
  (adopted?'<p id="planning-adopted">已采纳到真实 '+(task.mode==='brainstorm'?'IDEA':'章节细纲版本')+' · 保存编号 '+data.adoptions[0].applied_revision+'</p><button id="planning-to-draft" type="button">用此 IDEA/细纲准备初稿</button>':'')+
  '<details><summary>原始响应、修正与采纳历史</summary>'+pre(data.candidates)+pre(data.reviews)+pre(data.adoptions)+'</details>'+
  (raw?'<details><summary>实际原始响应</summary>'+pre({reported_model:raw.reported_model,usage:raw.usage,complete:raw.complete,error_code:raw.error_code})+'<pre class="context-text">'+h(raw.raw_response)+'</pre></details>':'')
  :'<p>尚无可采纳候选。失败、部分输出、取消与迟到不会写入 IDEA 或细纲，也不自动重试。</p>')+
 '</section>';
}

export function bindChapterPlanningTask(root,workspace,data,hooks){
 if(!root||root.dataset.bound)return;root.dataset.bound='true';const task=data.task,d=taskState(data),base='/api/projects/'+encodeURIComponent(workspace.document.project.id)+'/chapter-planning/'+encodeURIComponent(task.id);let busy=false;
 const area=root.querySelector('#planning-candidate-text');
 if(area)area.addEventListener('input',()=>{d.text=area.value;d.dirty=true;d.review=null;d.pending=null;const b=root.querySelector('#planning-review');if(b)b.disabled=true;emit();});
 const select=root.querySelector('#planning-task-select');if(select)select.addEventListener('change',()=>hooks.select(select.value));
 root.addEventListener('click',event=>{
  const b=event.target.closest('button');if(!b)return;
  if(b.id==='planning-back-editor'){event.stopPropagation();return hooks.editor();}
  if(b.id==='planning-to-draft'){event.stopPropagation();return hooks.draft(task.chapter_id);}
  if(b.id==='planning-refresh'){event.stopPropagation();return hooks.refresh();}
  if(busy)return;busy=true;hooks.busy(true);void(async()=>{try{
   if(b.id==='planning-execute'){if(!root.querySelector('#planning-confirm-request').checked)throw Error('请先勾选本次确切请求与费用确认。');await api(base+'/execute',{method:'POST',body:JSON.stringify({confirm_external:true,request_sha256:task.binding.request_sha256})});}
   else if(b.id==='planning-cancel')await api(base+'/cancel',{method:'POST',body:'{}'});
   else if(b.id==='planning-save-correction'){const result=await api('/api/projects/'+encodeURIComponent(workspace.document.project.id)+'/chapter-planning/correct',{method:'POST',body:JSON.stringify({operation_id:crypto.randomUUID(),task_id:task.id,candidate_id:data.latest_candidate.id,text:d.text})});d.candidateId=result.latest_candidate.id;d.dirty=false;d.review=null;d.pending=null;emit();}
   else if(b.id==='planning-review'){if(d.dirty)throw Error('请先保存人工修正，再复核。');d.review=await api('/api/projects/'+encodeURIComponent(workspace.document.project.id)+'/chapter-planning/review',{method:'POST',body:JSON.stringify({operation_id:crypto.randomUUID(),task_id:task.id,candidate_id:data.latest_candidate.id,candidate_sha256:data.latest_candidate.data_sha256})});d.pending=null;}
   else if(b.id==='planning-adopt'){if(!d.review||d.dirty)throw Error('请先复核当前候选的具体差异。');if(!root.querySelector('#planning-confirm-adopt').checked||!root.querySelector('#planning-confirm-chapter').checked)throw Error('请先核对差异并确认目标章节。');if(!d.pending)d.pending={operation_id:crypto.randomUUID(),task_id:task.id,candidate_id:data.latest_candidate.id,candidate_sha256:data.latest_candidate.data_sha256,review_id:d.review.id,review_sha256:d.review.review_sha256,expected_revision:data.revision,confirm_chapter:true};await api('/api/projects/'+encodeURIComponent(workspace.document.project.id)+'/chapter-planning/accept',{method:'POST',body:JSON.stringify(d.pending)});d.dirty=false;emit();}
   else return;
   await hooks.refresh();
  }catch(error){hooks.notice(error.message,true);}finally{busy=false;hooks.busy(false);}})();
 });
}
