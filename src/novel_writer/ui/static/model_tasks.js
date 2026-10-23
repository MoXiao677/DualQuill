import {renderSampling,captureSampling,fillSampling,samplingOptions} from './sampling.js';
import {renderDeepReviewPrepare,bindDeepReviewPrepare,renderDeepReview,bindDeepReview} from './deep_reviews.js';
import {activeChapters} from './views.js';
import {providerDisplayName} from './provider_views.js';


import {api} from './api.js';
import {memoryAutomationPolicy} from './memory_automation.js';
import {escapeHTML as h} from './views.js';
import {diffLines} from './state.js';
import {activeCreationSettings} from './creation_presets.js';
import {t} from './i18n.js';
const preparationDrafts=new Map(),pendingRequests=new Map(),decisionRequests=new Map(),reviewChecks=new Map();
export function resetModelPreparation(project){preparationDrafts.delete(project);}
export function useGenerationPreset(project,chapter,settings){preparationDrafts.set(project,{sampling:settings.sampling,task_type:'rewrite_chapter',connection_id:settings.connection_id,model_id:settings.model_id,temperature:settings.temperature,max_tokens:settings.max_tokens,max_output_chars:settings.max_output_chars,timeout_ms:settings.timeout_ms,instruction:'',budget_limit:1,allow_unknown_cost:false,selected_chapter_ids:[chapter],include_current_plan:false,include_book_outline:false,memory_ids:[]});}
const exactText=value=>'<span>'+h(value).replaceAll('\r','&#13;')+'</span>';
const pre=value=>'<pre class="context-text">'+exactText(typeof value==='string'?value:JSON.stringify(value,null,2))+'</pre>';
const options=items=>items.map(([value,label,selected])=>'<option value="'+h(value)+'" '+(selected?'selected':'')+'>'+h(label)+'</option>').join('');
let sequence=0;
const select=(name,label,items,multiple=false)=>{const id='model-field-'+(++sequence);return '<div class="field"><label for="'+id+'">'+label+'</label><select data-passive id="'+id+'" name="'+name+'" '+(multiple?'multiple':'')+'>'+options(items)+'</select></div>';};
const input=(name,label,value,type='text')=>{const id='model-field-'+(++sequence);return '<div class="field"><label for="'+id+'">'+label+'</label><input id="'+id+'" name="'+name+'" type="'+type+'" value="'+h(value)+'" '+(type==='number'?'step="any"':'')+'></div>';};
const check=(name,label,checked=false)=>'<label class="check-label"><input name="'+name+'" type="checkbox" '+(checked?'checked':'')+'>'+label+'</label>';
const statuses={pending:'待明确执行',running:'执行中',succeeded:'成功',failed:'失败',cancelled:'已取消',interrupted:'已中断'};
const summaryDrafts=new Map();
function summaryDraft(workspace,chapter,caps){
 const project=workspace.document.project.id,key=project+'/'+chapter;
 if(!summaryDrafts.has(key)){
  const preset=activeCreationSettings(workspace)?.steps.find(v=>v.step==='audit'),c=caps.connections.find(v=>v.id===preset?.connection_id)||caps.connections[0];
  summaryDrafts.set(key,{chapter_id:chapter,connection_id:preset?.connection_id||c?.id||'',model_id:preset?.model_id||c?.model_id||'',temperature:preset?.temperature??.3,max_tokens:preset?.max_tokens??2048,budget_limit:preset?.budget_limit??1,allow_unknown_cost:false,instruction:'概括本章已发生的事件与结果，不补造未来或计划。',max_output_chars:10000,timeout_ms:120000,sampling:preset?.sampling,payload:null});
 }
 return summaryDrafts.get(key);
}
export function renderSummaryPrepare(workspace,chapter,caps){
 const chapters=activeChapters(workspace),selected=chapters.some(v=>v.id===chapter)?chapter:chapters[0]?.id;
 if(!selected)return '<section id="summary-preparation" class="panel"><h2>单章模型语义摘要</h2><p>先创建并保存非空章节正文；不会把计划当事实。</p></section>';
 const d=summaryDraft(workspace,selected,caps),target=workspace.document.chapters.find(v=>v.id===selected);
 return '<section id="summary-preparation" class="panel"><h2>单章模型语义摘要（默认不执行）</h2><p>只冻结所选章已保存正文，未保存草稿、其他章节、计划与记忆正文不发送。先核对完整请求，再逐次确认外发；结果是带引文的摘要提案，接受后新增记忆，不覆盖原记忆或正文，也不自动重建汇总。</p><form id="summary-prepare-form">'+select('chapter_id','唯一已保存章节',chapters.map(c=>[c.id,'第'+c.number+'章 · '+c.title,c.id===selected]))+select('connection_id','本次摘要模型连接',connectionChoices(caps).map(([id,label])=>[id,label,id===d.connection_id]))+input('model_id','模型编号',d.model_id)+input('instruction','本次摘要要求',d.instruction)+input('temperature','温度',d.temperature,'number')+input('max_tokens','输出token上限',d.max_tokens,'number')+renderSampling('summary',d.sampling)+input('budget_limit','单次风险预算（美元，非硬封顶）',d.budget_limit,'number')+check('allow_unknown_cost','我明确允许费用未知，执行前仍须核对并单次确认')+input('max_output_chars','模型JSON字符硬上限',d.max_output_chars,'number')+input('timeout_ms','总时限（毫秒，100至300000）',d.timeout_ms,'number')+'<button type="submit" '+(caps.real_model_enabled&&target.content.trim()?'':'disabled')+'>冻结本章摘要请求（不发送）</button></form><p id="summary-prepare-status" role="status">'+(caps.real_model_enabled?'模型会话已开启；准备和页面不会自动发送。':'当前完全手动；请在模型中心明确开启本次会话后再准备。')+'</p><details><summary>实际已保存正文（'+Array.from(target.content).length+'字符）</summary><pre id="summary-saved-body" class="context-text">'+exactText(target.content)+'</pre></details></section>';
}
export function bindSummaryPrepare(root,workspace,chapter,caps,hooks){
 const form=root?.querySelector('#summary-prepare-form');if(!form)return;
 const selected=form.elements.chapter_id.value,d=summaryDraft(workspace,selected,caps),project=workspace.document.project.id;let busy=false;
 const capture=()=>{for(const name of ['model_id','instruction','temperature','max_tokens','budget_limit','allow_unknown_cost','max_output_chars','timeout_ms','connection_id']){const e=form.elements.namedItem(name);d[name]=e.type==='checkbox'?e.checked:e.value;}d.sampling=captureSampling(form.querySelector('[data-sampling="summary"]'));d.payload=null;};
 form.elements.allow_unknown_cost.checked=d.allow_unknown_cost;
 form.addEventListener('input',capture);
 form.addEventListener('change',event=>{if(event.target.name==='chapter_id'){void hooks.chapter(event.target.value);return;}capture();if(event.target.name==='connection_id'){const c=caps.connections.find(v=>v.id===d.connection_id);if(c){d.model_id=c.model_id||'';form.elements.model_id.value=d.model_id;}}});
 form.addEventListener('submit',event=>{event.preventDefault();event.stopPropagation();if(busy)return;busy=true;hooks.busy(true);void(async()=>{try{
  if(!d.allow_unknown_cost)throw Error('请明确核对本次费用未知风险。');
  if(!d.payload)d.payload={request_id:crypto.randomUUID(),chapter_id:selected,expected_revision:workspace.revision,instruction:d.instruction,max_output_chars:Number(d.max_output_chars),timeout_ms:Number(d.timeout_ms),model_options:{...samplingOptions(d.sampling),adapter_id:modelAdapterId(d.connection_id),connection_id:d.connection_id,model_id:d.model_id,temperature:Number(d.temperature),max_tokens:Number(d.max_tokens),budget_limit:Number(d.budget_limit),allow_unknown_cost:true,prompt_version:'chapter-summary-json-1'}};
  const result=await api('/api/projects/'+encodeURIComponent(project)+'/model-summaries/prepare',{method:'POST',body:JSON.stringify(d.payload)});d.payload=null;await hooks.prepared(result.task.id);
 }catch(error){const status=root.querySelector('#summary-prepare-status');if(status)status.textContent=error.message+'；输入保留，不自动重试。';hooks.notice(error.message,true);}finally{busy=false;hooks.busy(false);}})();});
}
export const modelAdapterId=id=>['gg','catie','odys'].includes(id)?'chat-completions-http-v1':'configured-http-v2';
export const connectionChoices=(caps,missing=false)=>[...(caps?.connections||[{id:'gg',name:'GG'},{id:'catie',name:'Catiecli'},{id:'odys',name:'Odys'}]).map(connection=>[connection.id,providerDisplayName(connection)+' · '+(connection.protocol||'openai-chat')]),...(missing?[['',t('preset.manual')]]:[])];
const lines=(a,b)=>diffLines(a,b).map(r=>(r.kind==='add'?'+ ':r.kind==='remove'?'- ':'  ')+r.text).join('\n');
export function renderModelPrepare(workspace,chapter,capabilities){
 return renderDeepReviewPrepare(workspace,chapter,capabilities)+renderLegacyModelPrepare(workspace,chapter,capabilities);
}
function renderLegacyModelPrepare(workspace,chapter,capabilities){
 return '<section id="model-preparation" class="panel"><h2>准备模型任务</h2><p id="model-prepare-gate">'+(capabilities.real_model_enabled?'本次启动允许模型任务；每次执行仍须单次确认。':'真实模型生成关闭；可只读准备请求，执行会被拒绝。')+'</p><p>这里只冻结已保存内容，不发送小说。真实站点兼容性、费用和语义质量尚未验收。配置使用模型中心已保存的供应商、声明协议与模型编号。</p><form id="model-prepare-form">'+select('task_type','模型任务能力',[['rewrite_chapter','整章改写候选'],['audit_chapter','模型审核与摘要（待核实）']])+select('connection_id','模型连接',[...connectionChoices(capabilities),['',t('preset.manual')]])+input('model_id','所选连接的模型编号','')+input('instruction','本次模型要求','')+input('temperature','温度',.3,'number')+input('max_tokens','输出令牌上限',512,'number')+input('max_output_chars','候选字符上限',10000,'number')+input('timeout_ms','总时限（毫秒，最多300000）',120000,'number')+renderSampling('model',null)+input('budget_limit','单次风险预算声明（美元）',1,'number')+check('allow_unknown_cost','允许供应商费用未知，理解本地无法保证硬封顶')+select('selected_chapter_ids','模型审核引用范围',activeChapters(workspace).map(c=>[c.id,'第'+c.number+'章 · '+c.title,c.id===chapter]),true)+check('include_current_plan','把本章计划作为计划材料（非事件证据）')+check('include_book_outline','包含全书大纲（含未来主线与结局）')+check('include_automatic_memories','自动选用已确认正文事实（需启用本书策略）',memoryAutomationPolicy(workspace).auto_select)+check('include_memory_rollups','启用已保存汇总（仅前章、去重、整条来源预算；默认关闭）')+select('memory_ids','明确选择上下文记忆',(workspace.memories||[]).filter(m=>m.active&&m.confirmed).map(m=>[m.id,m.title]),true)+'<p>规划仅作上下文，模型提案的引用当前限已保存正文。准备后可逐字核对完整外发请求；输入令牌与计价未知，不用字符数编造费用。</p><button type="submit">冻结外发请求供核对</button><p id="model-prepare-status" role="status"></p></form></section>';
}
export function bindModelPrepare(root,workspace,chapter,onPrepared){
 bindDeepReviewPrepare(document,workspace,chapter,onPrepared);
 const form=root.querySelector('#model-prepare-form'),project=workspace.document.project.id;let pending=false;
 const values=()=>({sampling:captureSampling(form),...Object.fromEntries([...form.elements].filter(e=>e.name).map(e=>[e.name,e.multiple?[...e.selectedOptions].map(o=>o.value):e.type==='checkbox'?e.checked:e.value]))});
 const active=activeCreationSettings(workspace);
 const preferences=taskType=>{const chosen=active?.steps.find(value=>value.step===(taskType==='audit_chapter'?'audit':'rewrite'));return {sampling:chosen?.sampling,task_type:taskType,connection_id:chosen?.connection_id||'',model_id:chosen?.model_id||'',temperature:chosen?.temperature??.3,max_tokens:chosen?.max_tokens??512,budget_limit:chosen?.budget_limit??1,allow_unknown_cost:chosen?.allow_unknown_cost??false,instruction:t('preset.languageInstruction')+active.manuscript_language+(active.style_prompt?' '+t('preset.styleInstruction')+active.style_prompt:'')};};
 const fill=previous=>{if(previous)fillSampling(form,previous.sampling);if(previous)for(const [name,value]of Object.entries(previous)){const e=form.elements.namedItem(name);if(!e)continue;if(e.multiple){for(const o of e.options)o.selected=value.includes(o.value);}else if(e.type==='checkbox')e.checked=value;else e.value=value;}};
 fill(preparationDrafts.get(project)||(active?preferences('rewrite_chapter'):null));
 form.addEventListener('change',event=>{if(active&&event.target.name==='task_type')fill(preferences(event.target.value));});
 const capture=()=>preparationDrafts.set(project,values());root.addEventListener('input',capture);root.addEventListener('change',capture);
 root.addEventListener('submit',async event=>{event.preventDefault();event.stopPropagation();if(pending)return;pending=true;capture();const v=values(),button=form.querySelector('[type="submit"]');button.disabled=true;
  try{
   if(!v.connection_id||!v.model_id)throw new Error(t('preset.needConfig'));
   if(v.task_type==='audit_chapter'&&!v.selected_chapter_ids.includes(chapter))throw new Error('审核引用范围须包含当前章。');
   const opts={chapter_id:chapter,budget_chars:4000,include_current_plan:v.include_current_plan,include_book_outline:v.include_book_outline,include_memories:v.memory_ids.length>0,include_memory_rollups:v.include_memory_rollups,include_automatic_memories:v.include_automatic_memories,memory_ids:v.memory_ids};
   const preview=await api('/api/projects/'+encodeURIComponent(project)+'/context-preview',{method:'POST',body:JSON.stringify(opts)});
   const parameters={instruction:v.instruction,max_output_chars:Number(v.max_output_chars),timeout_ms:Number(v.timeout_ms)};
   if(v.task_type==='audit_chapter')Object.assign(parameters,{rules:{version:'offline-audit-1',forbidden_literals:[],required_literals:[],normalization:'whitespace',near_threshold:.85,minimum_fragment_chars:12,check_timeline:false},selected_chapter_ids:v.selected_chapter_ids,previous_report_id:null});
   const model_options={...samplingOptions(v.sampling),adapter_id:modelAdapterId(v.connection_id),connection_id:v.connection_id,model_id:v.model_id,temperature:Number(v.temperature),max_tokens:Number(v.max_tokens),budget_limit:Number(v.budget_limit),allow_unknown_cost:v.allow_unknown_cost,prompt_version:v.task_type==='audit_chapter'?'review-json-1':'rewrite-1'};
   const hash=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(preview.context_text)),context_sha256=[...new Uint8Array(hash)].map(n=>n.toString(16).padStart(2,'0')).join('');
   const signature=project+'/'+JSON.stringify({opts,parameters,model_options,context_sha256});let payload=pendingRequests.get(signature);
   if(!payload){payload={request_id:crypto.randomUUID(),chapter_id:chapter,task_type:v.task_type,context_options:opts,context_sha256,parameters,model_options,expected_revision:preview.revision};pendingRequests.set(signature,payload);}
   let prepared;try{prepared=await api('/api/projects/'+encodeURIComponent(project)+'/tasks/prepare',{method:'POST',body:JSON.stringify(payload)});}catch(error){const listing=await api('/api/projects/'+encodeURIComponent(project)+'/tasks');prepared=listing.tasks.find(t=>t.task.request_id===payload.request_id);if(!prepared)throw error;}
   await onPrepared(prepared.task.id);pendingRequests.delete(signature);
  }catch(error){form.querySelector('#model-prepare-status').textContent='准备失败：'+error.message+'。输入仍在本窗口保留。';}
  finally{pending=false;if(button.isConnected)button.disabled=false;}
 });
}
export function renderModelTask(workspace,listing,capabilities,data){
 const task=data.task,b=task.frozen.parameters.binding,candidate=data.candidates[0],receipt=data.receipts[0],response=data.model_results[0]?.response;
 const destination=b.destination?'<pre id="model-destination" class="context-text">'+h(JSON.stringify(b.destination,null,2))+'</pre>':'';
 const graphLink=data.graph_extractions?.length?'<button id="open-graph-proposals" type="button">查看图谱提案与精确引文</button>':'';
 const list=graphLink+destination+'<div class="field"><label for="task-select">已保存任务</label><select id="task-select" data-passive>'+options(listing.tasks.map(v=>[v.task.id,(v.real_model_request?'模型':'本地')+' · '+statuses[v.display_status]+' · '+v.task.id,v.task.id===task.id]))+'</select></div>';
 const result=response?'<p id="model-usage">供应商报告用量：输入 '+(response.usage.prompt_tokens??'未知')+' / 输出 '+(response.usage.completion_tokens??'未知')+' / 总计 '+(response.usage.total_tokens??'未知')+'；费用未知。实际返回模型 '+h(response.reported_model||'未知')+' · '+h(response.finish_reason||response.error_code||'未知')+'</p>'+(!response.complete?'<p>响应失败或部分输出，不作为可采纳候选。</p>':'')+'<details><summary>实际供应商原始返回（只读，不执行工具或URL）</summary>'+pre(response.raw_response)+'<p>'+(response.raw_truncated?'原始包超过保留上限，标记为截取。':'原始包在保留上限内。')+(response.redacted?'意外凭据回显已删除，响应未作为完成候选。':'')+'</p></details>':'';
 return '<section class="panel"><h2>模型任务与候选</h2>'+(data.stream_preview?'<section data-stream-preview><h3>流式临时预览（尚非候选）</h3><pre class="context-text">'+exactText(data.stream_preview.text)+'</pre><p>取消、超时或断流后清空；完整校验后才保存候选。</p></section>':'')+list+'<p id="task-status" role="status">状态：'+statuses[data.display_status]+(task.error_code?' · '+h(task.error_code):'')+'</p><p id="model-execution-gate">'+(capabilities.real_model_enabled?'启动已明确启用；每次执行仍需下面的单次确认。':'真实模型生成关闭；当前任务不能外发执行。')+'</p><p>连接 '+h(b.connection_id)+' · 配置模型 '+h(b.model_id)+' · adapter '+h(b.adapter_id)+' · 提示词 '+h(b.prompt_version)+' · 输出上限 '+b.max_tokens+' token · 预算声明 '+b.budget_limit+' 美元；输入令牌与供应商费用未知，本地不能保证硬封顶。取消不能保证供应商未处理或未计费。</p><h3>确切外发请求</h3><pre id="model-outbound" class="context-text">'+h(b.request_body)+'</pre><p>请求摘要 '+h(b.request_sha256)+'</p>'+check('confirm-model-send','我已核对确切外发内容、令牌上限、预算和未知费用风险')+'<button id="execute-model-task" type="button" '+(task.status==='pending'&&capabilities.real_model_enabled?'':'disabled')+'>单次确认执行模型任务</button><button id="cancel-generation-task" type="button" '+(['pending','running'].includes(task.status)?'':'disabled')+'>取消任务</button><button id="refresh-generation-task" type="button">刷新任务状态</button>'+result+(data.model_reports.length?'<button id="open-model-report" type="button">查看模型审核与提案</button>':'')+(candidate?'<h3>模型返回候选（质量待核实）</h3><pre id="task-candidate" class="context-text">'+h(candidate.output_text)+'</pre><h3>原稿 → 候选差异</h3><pre id="task-candidate-diff" class="context-text">'+h(lines(task.frozen.target.text,candidate.output_text))+'</pre>'+(task.frozen.target.status==='confirmed'?'<label class="check-label"><input id="task-authorize-confirmed" type="checkbox">我确认修改已确认章节，并保留旧版本。</label>':'')+'<button id="adopt-generation-candidate" type="button" '+(receipt?'disabled':'')+'>明确采纳候选为新草稿</button>':'<p>审核只产生待核实报告；失败/部分输出不进入正文采纳。</p>')+'<p id="task-adoption-result" role="status">'+(receipt?'采纳已核对 · 保存编号 '+receipt.applied_revision:'')+'</p><details><summary>冻结输入与追加事件</summary>'+pre(task.frozen)+pre(data.events)+'</details></section>';
}
const evidence=(items,scope)=>items.map((e,index)=>'<p>来源 '+h(e.chapter_id)+' · 版本 '+h(e.version_id||'保存'+e.source_revision)+' · 字符 '+e.start+'–'+e.end+'</p>'+pre(e.quote)+'<button type="button" data-model-jump="'+scope+':'+index+'">打开引文版本</button>').join('');
export function renderModelReview(detail){
 if(detail?.scope&&detail.method==='model_semantic_opinion')return renderDeepReview(detail);
 if(!detail)return '<section class="panel"><h2>模型审核</h2><p>尚无已完成的模型审核报告。</p></section>';
 const findings=detail.output.findings.map((f,i)=>'<article class="context-card"><h3>模型意见 / 因果推断 · 待核实</h3><p>'+h(f.statement)+'</p><p>'+h(f.category)+' · '+h(f.assessment)+'</p>'+evidence(f.evidence,'finding:'+i)+'</article>').join('');
 const proposals=detail.proposals.map((p,i)=>'<article class="context-card" data-model-memory="'+p.id+'"><h3>'+h(p.draft.title)+' · 模型摘要/推断待核实</h3><p>'+(p.receipt?h(p.receipt.decision):'待作者决定')+'</p>'+pre(p.draft.text)+evidence(p.draft.evidence,'memory:'+i)+'<details><summary>现有不同记忆（接受也将保留）</summary>'+p.conflicts.map(m=>pre(m.text)).join('')+'</details>'+check('inference-'+p.id,'我已核对引文和推断，明确确认新增记忆')+check('conflicts-'+p.id,'保留现有不同记忆')+'<button type="button" data-model-decision="accepted" data-model-id="'+p.id+'" '+(p.receipt||detail.outdated?'disabled':'')+'>明确接受模型摘要为新记忆</button><button type="button" data-model-decision="rejected" data-model-id="'+p.id+'" '+(p.receipt?'disabled':'')+'>拒绝模型记忆提案</button></article>').join('');
 const bridges=detail.bridges.map((p,i)=>'<article class="context-card" data-model-bridge="'+p.id+'"><h3>模型重复桥段建议 · 待核实</h3><p>'+(p.receipt?h(p.receipt.decision):'待作者决定')+' · '+h(p.draft.statement)+'</p>'+evidence(p.draft.evidence,'bridge:'+i)+'<p>建议替换第'+(p.draft.side+1)+'侧原文，尚未写正文：</p>'+pre(p.draft.replacement)+check('inference-'+p.id,'我已核对双侧引文，明确准备局部提案')+'<button type="button" data-model-decision="accepted" data-model-id="'+p.id+'" '+(p.receipt||detail.outdated?'disabled':'')+'>明确转为可编辑局部提案</button><button type="button" data-model-decision="rejected" data-model-id="'+p.id+'" '+(p.receipt?'disabled':'')+'>拒绝模型桥段提案</button>'+(p.receipt?.local_proposal_id?'<button type="button" data-open-local-model>打开局部提案核对差异</button>':'')+'</article>').join('');
 return '<section class="panel" id="model-review-panel"><h2>模型审核与提案</h2><p id="model-review-status">'+(detail.outdated?'来源已过期，不能接受。':'来源未变。')+'模型意见、摘要及因果推断均待核实，真实检出率/语义质量未验收。分析不直接采纳为正文。</p><p id="model-review-operation" role="status"></p>'+pre(detail.output.overview)+findings+'<h3>记忆提案</h3>'+proposals+'<h3>重复桥段建议</h3>'+bridges+'<details><summary>只读实际模型返回及真实/未知用量</summary>'+pre(detail.response.response)+'</details></section>';
}
export function bindModelReview(root,workspace,detail,onRefresh,onJump,onLocal){
 if(root&&detail?.scope&&detail.method==='model_semantic_opinion'){bindDeepReview(root,workspace,detail,onRefresh);return;}
 if(!root||!detail)return;const project=workspace.document.project.id;let pending=false;
 for(const e of root.querySelectorAll('input[type="checkbox"]')){e.checked=reviewChecks.get(project+'/'+e.name)||false;e.addEventListener('change',()=>reviewChecks.set(project+'/'+e.name,e.checked));}
 root.addEventListener('click',async event=>{const b=event.target.closest('button');if(!b)return;event.stopPropagation();if(pending)return;
  try{
   if(b.dataset.modelJump){const [kind,i,j]=b.dataset.modelJump.split(':'),entry=kind==='finding'?detail.output.findings[Number(i)]:kind==='memory'?detail.proposals[Number(i)].draft:detail.bridges[Number(i)].draft;await onJump(entry.evidence[Number(j)]);return;}
   if(b.hasAttribute('data-open-local-model')){await onLocal();return;}
   if(!b.dataset.modelDecision)return;
   const id=b.dataset.modelId,decision=b.dataset.modelDecision,key=project+'/'+detail.report.id+'/'+id+'/'+decision;
   const confirm=root.querySelector('[name="inference-'+id+'"]').checked,preserve=root.querySelector('[name="conflicts-'+id+'"]')?.checked||false;
   if(decision==='accepted'&&!confirm)throw new Error('请先核对引文/推断，并明确勾选本项确认。');
   let request=decisionRequests.get(key);if(!request){request={decision_id:crypto.randomUUID(),proposal_id:id,decision,expected_revision:detail.revision,confirm_inference:confirm,preserve_conflicts:preserve};decisionRequests.set(key,request);}
   pending=true;b.disabled=true;
   try{await api('/api/projects/'+encodeURIComponent(project)+'/model-reviews/'+detail.report.id+'/proposal',{method:'POST',body:JSON.stringify(request)});}catch(error){const known=await api('/api/projects/'+encodeURIComponent(project)+'/model-reviews/'+detail.report.id);if(![...known.proposals,...known.bridges].some(p=>p.receipt?.id===request.decision_id))throw error;}
   await onRefresh();decisionRequests.delete(key);
  }catch(error){root.querySelector('#model-review-operation').textContent='处理未完成：'+error.message;}
  finally{pending=false;if(b.isConnected)b.disabled=false;}
 });
}


