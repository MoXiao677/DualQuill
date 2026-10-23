import {api} from './api.js';
import {connectionChoices,modelAdapterId} from './model_tasks.js';
import {renderSampling,captureSampling,samplingOptions} from './sampling.js';

const drafts=new Map();
const h=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pre=v=>`<pre class="context-text" style="white-space:pre-wrap;overflow-wrap:anywhere">${h(typeof v==='string'?v:JSON.stringify(v,null,2)).replaceAll('\r','&#13;')}</pre>`;
const statuses={pending:'待逐请求确认',running:'执行中',succeeded:'待核实模型建议',failed:'失败（不自动重试）',cancelled:'已取消',interrupted:'已中断，须重新准备'};
const input=(name,label,value,type='text')=>`<label>${label}<input name="${name}" type="${type}" step="any" value="${h(value)}"></label>`;
function draft(workspace,listing){
  const project=workspace.document.project.id,caps=listing.model_capabilities||{};
  const connection=caps.connections?.find(c=>c.model_id)||caps.connections?.[0];
  if(!drafts.has(project))drafts.set(project,{chapter_id:listing.chapters.find(c=>!c.hidden)?.id||'',character_ids:[],
    connection_id:connection?.id||'',model_id:connection?.model_id||'',instruction:'依据已保存正文提出规划建议；计划与发生分开。',
    context_budget_chars:24000,max_tokens:2048,temperature:.3,budget_limit:1,max_external_calls:10,max_reserved_output_tokens:81920,
    max_output_chars:20000,timeout_ms:120000,allow_unknown_cost:false,source:null,payload:null,sampling:null});
  return drafts.get(project);
}
const sourceOptions=d=>({chapter_id:d.chapter_id,character_ids:d.character_ids,instruction:d.instruction,context_budget_chars:Number(d.context_budget_chars)});
function taskCard(view){
  const t=view.task,b=t.binding;
  const suggestions=view.candidates.map(c=>c.plan.suggestions.map((s,index)=>{
    const linked=view.links.some(l=>l.candidate_id===c.id&&l.suggestion_index===index);
    const enabled=view.source_fresh&&view.connection_fresh&&!linked;
    return `<article class="context-card" data-model-suggestion="${h(c.id+':'+index)}"><h5>建议 ${index+1} · 待核实</h5><p>${h(s.reason)}</p><blockquote>${h(s.quote)}</blockquote><p>Unicode字符范围 [${s.start}, ${s.end})</p>${pre(s.actions)}
      <button type="button" data-model-transfer-preview="${h(c.id)}" data-index="${index}" ${enabled?'':'disabled'}>${linked?'已转待审提案':'预览本条转提案'}</button>
      <button type="button" data-model-propose="${h(c.id)}" data-index="${index}" disabled>仅保存本条待审提案</button><div data-model-transfer-impact></div></article>`;
  }).join('')).join('');
  return `<article class="context-card" data-model-task="${h(t.id)}"><h4>${h(statuses[view.display_status]||view.display_status)}</h4>
    <p>来源${view.source_fresh?'未变':'已过期'} · 配置${view.connection_fresh?'未变':'已变化或模型会话关闭'} · 语义质量待作者核实</p>
    <details><summary>冻结的确切请求、去向与预算</summary>${pre({destination:b.destination,model_id:b.model_id,source_sha256:t.source_sha256,
      request_sha256:b.request_sha256,budget_sha256:t.budget_sha256,max_external_calls:t.budget_max_calls,max_reserved_output_tokens:t.budget_max_output_tokens,
      max_tokens:b.max_tokens,max_output_chars:t.max_output_chars,timeout_ms:t.timeout_ms,budget_limit_usd:b.budget_limit,allow_unknown_cost:b.allow_unknown_cost})}${pre(b.request_body)}</details>
    ${view.display_status==='pending'?`<label><input type="checkbox" data-model-confirm>我已核对完整外发正文、规则、人物、规划、确切去向及未知费用，确认仅此请求</label><button type="button" data-model-send="${h(t.id)}" disabled>确认并发送这一个请求</button>`:''}
    ${['pending','running'].includes(view.display_status)?`<button type="button" data-model-cancel="${h(t.id)}">取消本次任务</button>`:''}
    ${view.stream_preview?`<h5>临时流式预览（未完成，不是候选）</h5>${pre(view.stream_preview.text)}`:''}
    ${view.events.at(-1)?.error_code?`<p role="status">${h(view.events.at(-1).error_code)}</p>`:''}
    ${view.responses.length?`<details><summary>实际完整响应记录</summary>${view.responses.map(r=>pre(r.response)).join('')}</details>`:''}
    ${suggestions}</article>`;
}
export function renderModelPlanning(workspace,listing){
  const d=draft(workspace,listing),caps=listing.model_capabilities||{},views=listing.model_planning?.tasks||[];
  return `<section data-model-planning><h4>原生正文驱动模型建议</h4><p class="hint">来源预览和冻结不发送。逐请求确认后使用现有模型连接；仅合法完整JSON及精确已保存引文成为候选。取消、超时、非法输出不产生提案。单条转提案后，仍须下方独立影响预览与人工接受。</p>
    <p>${caps.real_model_enabled?'本次模型会话已开启。':'当前完全手动；请在模型中心明确开启模型会话。'}</p>
    <form data-model-planning-form><div class="field-grid">
    <label>已保存来源章节<select name="chapter_id">${listing.chapters.filter(c=>!c.hidden).map(c=>`<option value="${h(c.id)}" ${c.id===d.chapter_id?'selected':''}>第${c.number}章 ${h(c.title)}</option>`).join('')}</select></label>
    <label>明确选入人物<select name="character_ids" multiple>${listing.characters.filter(c=>!c.archived).map(c=>`<option value="${h(c.id)}" ${d.character_ids.includes(c.id)?'selected':''}>${h(c.name)}</option>`).join('')}</select></label>
    <label>本次连接<select name="connection_id">${connectionChoices(caps).map(([id,label])=>`<option value="${h(id)}" ${id===d.connection_id?'selected':''}>${h(label)}</option>`).join('')}</select></label>
    ${input('model_id','模型编号',d.model_id)}${input('context_budget_chars','上下文字符预算（1024–100000）',d.context_budget_chars,'number')}
    ${input('max_tokens','本次输出token上限',d.max_tokens,'number')}${input('temperature','温度',d.temperature,'number')}
    ${input('max_output_chars','输出JSON字符上限',d.max_output_chars,'number')}${input('timeout_ms','总时限毫秒（100–300000）',d.timeout_ms,'number')}
    ${input('max_external_calls','本书正文规划累计外发次数预算（最多10）',d.max_external_calls,'number')}
    ${input('max_reserved_output_tokens','本书累计预留输出token预算',d.max_reserved_output_tokens,'number')}
    ${input('budget_limit','单次风险预算美元（非实际费用硬封顶）',d.budget_limit,'number')}</div>
    <label>本次要求<textarea name="instruction" maxlength="4000"></textarea></label>${renderSampling('body-model',d.sampling).replace('当前为完整响应，未实现流式增量。','默认完整JSON；当前连接须明确声明SSE，流式文本仅为内存预览，合法终止前不生成候选。')}
    <label><input name="allow_unknown_cost" type="checkbox" ${d.allow_unknown_cost?'checked':''}>明确允许费用未知</label>
    <button type="button" data-model-source>预览实际正文和全部来源</button><button type="submit" ${d.source&&caps.real_model_enabled?'':'disabled'}>冻结本次请求（不发送）</button>
    <div data-model-source-preview>${d.source?pre(d.source.context_text):''}</div></form><p data-model-status role="status"></p>
    <div data-model-tasks>${views.slice(-30).reverse().map(taskCard).join('')||'<p>尚无模型规划任务。</p>'}</div></section>`;
}

export function bindModelPlanning(root,workspace,listing,hooks){
  const panel=root?.querySelector('[data-model-planning]');if(!panel)return;
  const form=panel.querySelector('[data-model-planning-form]'),d=draft(workspace,listing),project=workspace.document.project.id;
  const base=`/api/projects/${encodeURIComponent(project)}/model-planning`,previews=new Map();
  let views=listing.model_planning?.tasks||[],busy=false;
  form.elements.instruction.value=d.instruction;
  const call=(path,body)=>api(base+'/'+path,{method:'POST',body:JSON.stringify(body)});
  const status=text=>{panel.querySelector('[data-model-status]').textContent=text;};
  const capture=()=>{
    for(const name of ['chapter_id','connection_id','model_id','instruction','context_budget_chars','max_tokens','temperature','budget_limit','max_external_calls','max_reserved_output_tokens','timeout_ms','max_output_chars'])d[name]=form.elements[name].value;
    d.character_ids=[...form.elements.character_ids.selectedOptions].map(o=>o.value);
    d.allow_unknown_cost=form.elements.allow_unknown_cost.checked;d.sampling=captureSampling(form);
  };
  const invalidate=()=>{capture();d.source=null;d.payload=null;form.querySelector('[type="submit"]').disabled=true;panel.querySelector('[data-model-source-preview]').textContent='输入已变化，请重新预览来源。';};
  form.addEventListener('input',invalidate);form.addEventListener('change',event=>{
    invalidate();if(event.target.name==='connection_id'){
      const connection=listing.model_capabilities?.connections.find(c=>c.id===d.connection_id);
      if(connection){d.model_id=connection.model_id||'';form.elements.model_id.value=d.model_id;}
    }
  });
  const paint=()=>{previews.clear();panel.querySelector('[data-model-tasks]').innerHTML=views.slice(-30).reverse().map(taskCard).join('');};
  async function refreshTasks(){if(!panel.isConnected)return;const result=await api(base);if(!panel.isConnected)return;views=result.tasks;paint();}
  async function run(fn){if(busy)return;busy=true;try{await fn();}catch(e){status(e.message+'；输入保留，不自动重试。');hooks.notice?.(e.message,true);}finally{busy=false;}}
  form.addEventListener('submit',event=>{event.preventDefault();event.stopPropagation();void run(async()=>{
    capture();if(!d.source)throw Error('请先重新预览实际来源。');if(!d.allow_unknown_cost)throw Error('请明确核对费用未知风险。');
    if(!d.payload)d.payload={operation_id:crypto.randomUUID(),expected_revision:d.source.revision,source_options:sourceOptions(d),source_sha256:d.source.source_sha256,
      model_options:{...samplingOptions(d.sampling),adapter_id:modelAdapterId(d.connection_id),connection_id:d.connection_id,model_id:d.model_id,temperature:Number(d.temperature),max_tokens:Number(d.max_tokens),budget_limit:Number(d.budget_limit),allow_unknown_cost:true,prompt_version:'rewrite-1'},
      budget:{max_external_calls:Number(d.max_external_calls),max_reserved_output_tokens:Number(d.max_reserved_output_tokens)},max_output_chars:Number(d.max_output_chars),timeout_ms:Number(d.timeout_ms)};
    await call('prepare',d.payload);status('请求已冻结，尚未发送；请展开核对完整请求与预算。');await refreshTasks();
    d.source=null;d.payload=null;form.querySelector('[type="submit"]').disabled=true;
  });});
  panel.addEventListener('change',event=>{if(event.target.matches('[data-model-confirm]'))event.target.closest('[data-model-task]').querySelector('[data-model-send]').disabled=!event.target.checked;});
  panel.addEventListener('click',event=>{
    const button=event.target.closest('[data-model-source],[data-model-send],[data-model-cancel],[data-model-transfer-preview],[data-model-propose]');if(!button||button.disabled)return;
    event.preventDefault();event.stopPropagation();void run(async()=>{
      if(button.hasAttribute('data-model-source')){capture();d.source=await call('preview',sourceOptions(d));d.payload=null;panel.querySelector('[data-model-source-preview]').innerHTML=pre(d.source.context_text);form.querySelector('[type="submit"]').disabled=!listing.model_capabilities?.real_model_enabled;return;}
      if(button.hasAttribute('data-model-send')){
        const view=views.find(v=>v.task.id===button.dataset.modelSend),task=view.task;
        if(!button.closest('[data-model-task]').querySelector('[data-model-confirm]').checked)throw Error('须逐请求明确确认。');
        button.disabled=true;await call(task.id+'/execute',{confirm_external:true,request_sha256:task.binding.request_sha256,budget_sha256:task.budget_sha256,expected_revision:task.prepared_revision});
        status('仅本次请求已发送；可取消。');await refreshTasks();return;
      }
      if(button.hasAttribute('data-model-cancel')){const result=await call(button.dataset.modelCancel+'/cancel',{});status(result.accepted?'取消已记录；不重试、不采纳迟到输出。':'任务已结束，没有新的取消决定。');await refreshTasks();return;}
      const id=button.dataset.modelTransferPreview||button.dataset.modelPropose,index=Number(button.dataset.index);
      const candidate=views.flatMap(v=>v.candidates).find(c=>c.id===id),selection={candidate_id:id,candidate_sha256:candidate.data_sha256,suggestion_index:index};
      const card=button.closest('[data-model-suggestion]'),key=id+':'+index;
      if(button.hasAttribute('data-model-transfer-preview')){
        const preview=await call('transfer-preview',selection);previews.set(key,preview);
        card.querySelector('[data-model-transfer-impact]').innerHTML=pre(preview);card.querySelector('[data-model-propose]').disabled=false;
      }else{
        const preview=previews.get(key);if(!preview)throw Error('请先预览本条建议。');
        if(!window.confirm('仅把这一条模型建议保存为待审提案？正式规划仍须另行影响预览和接受。'))return;
        await call('propose',{operation_id:crypto.randomUUID(),expected_revision:preview.revision,...selection,transfer_token:preview.transfer_token,confirmed:true});
        d.source=null;d.payload=null;status('单条待审提案已保存，尚未采纳。');await hooks.refresh?.();
      }
    });
  });
  async function poll(){
    if(!panel.isConnected)return;
    try{if(!busy&&views.some(v=>v.display_status==='running'))await refreshTasks();}catch(e){status(e.message+'；轮询已停止，请重新打开规划页。');return;}
    if(panel.isConnected)setTimeout(poll,1000);
  }
  setTimeout(poll,1000);
}
