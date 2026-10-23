import {api} from './api.js';
import {escapeHTML as h} from './views.js';

// Keep editable preparation values per book, never execution/risk consent.
const preparationDrafts=new Map();
const draftFields=['connection','tokens','risk','calls','total','chars','timeout'];

export function renderRuleReviews(){return '<section id="rule-reviews" class="panel"><h2>模型语义规则审阅</h2><p>仅发送所选章节/任务的已保存规则。先预览、冻结具体请求与预算，再逐请求确认外发。结果始终是待核实意见；双侧逐字引文校验不代表模型判断正确，不授予正式修改许可。</p><div data-review-controls></div><div data-review-history></div><p data-review-notice role="status"></p></section>';}

export function frozenReview(view,enabled){
 const t=view.task,b=t.binding;
 return '<article class="rule-item" data-review-task="'+h(t.id)+'"><h3>'+h(view.display_status)+' · '+h(t.id)+'</h3><p>来源'+(view.source_fresh?'仍有效':'已过期，不能发送/使用意见')+' · 待核实 / 无正式修改许可</p><details><summary>完整冻结规则、去向、请求和预算（发送前展开复核）</summary><pre>'+h(JSON.stringify({project_id:t.project_id,chapter_id:t.chapter_id,target_task_id:t.target_task_id,rules:t.rules,wire_source:t.wire_source,copy_mappings:t.copy_mappings,destination:b.destination,request_sha256:b.request_sha256,risk_budget:b.budget_limit,allow_unknown_cost:b.allow_unknown_cost,max_tokens:b.max_tokens,max_output_chars:t.max_output_chars,timeout_ms:t.timeout_ms,budget_max_calls:t.budget_max_calls,budget_max_output_tokens:t.budget_max_output_tokens},null,2))+'</pre><pre>'+h(b.request_body)+'</pre></details>'+
 (view.status==='pending'&&view.display_status!=='interrupted'?'<label><input type="checkbox" data-review-confirm>我已复核完整冻结请求、具体去向及预算，确认此次外发（费用未知）</label><button type="button" data-review-execute '+(!enabled||!view.source_fresh?'disabled':'')+'>确认并发送一次</button>':'')+
 (['pending','running'].includes(view.status)?'<button type="button" data-review-cancel>取消本次请求</button>':'')+
 (view.stream_preview?'<p>临时流式预览，未保存为意见：</p><pre>'+h(view.stream_preview.text)+'</pre>':'')+
 view.results.map(r=>'<details><summary>持久结果 '+h(r.id)+' · '+(r.output?'待核实模型意见':'无合法意见，保留失败响应')+'</summary><pre>'+h(JSON.stringify(r,null,2))+'</pre></details>'+(r.output?'<button type="button" data-review-inspect="'+h(r.id)+'" '+(!view.can_inspect?'disabled':'')+'>复核当前来源并只读查看意见</button>':'')).join('')+'<pre data-review-inspected></pre><details><summary>执行历史</summary><pre>'+h(JSON.stringify(view.events,null,2))+'</pre></details></article>';
}

export async function bindRuleReviews(root,workspace){
 if(!root||root.dataset.bound)return;root.dataset.bound='true';
 const base='/api/projects/'+encodeURIComponent(workspace.document.project.id)+'/rule-reviews',notice=root.querySelector('[data-review-notice]');let listing,preview=null,busy=false;
 const post=(url,body)=>api(url,{method:'POST',body:JSON.stringify(body)});
 const refresh=async()=>{listing=await api(base);if(!root.isConnected)return;root.querySelector('[data-review-history]').innerHTML=listing.tasks.map(v=>frozenReview(v,listing.enabled)).join('');};
 try{
  const caps=await api('/api/tasks/capabilities');if(!root.isConnected)return;
  const connections=caps.connections.filter(c=>c.adapter_id==='configured-http-v2'&&c.model_id);
  root.querySelector('[data-review-controls]').innerHTML='<p>'+ (caps.real_model_enabled?'本会话允许模型任务，仍须逐次确认':'本会话模型关闭；可以预览/冻结，不能发送')+'</p><p>使用上方「查看章节」与「本次任务」的选择。</p><label>具体自建连接/默认模型<select data-review-connection>'+connections.map(c=>'<option value="'+h(c.id)+'">'+h(c.name)+' / '+h(c.model_id)+' / '+h(c.protocol)+'</option>').join('')+'</select></label><div class="field-grid">'+[['tokens','单次输出Token上限',1024,1,8192],['risk','本次风险预算',1,.01,1000],['calls','本书累计调用上限',1,1,10],['total','本书累计预留输出Token上限',1024,1,81920],['chars','输出字符上限',10000,128,100000],['timeout','时限（毫秒）',120000,100,300000]].map(([key,label,value,min,max])=>'<label>'+label+'<input type="number" data-review-'+key+' value="'+value+'" min="'+min+'" max="'+max+'" step="any"></label>').join('')+'</div><label><input type="checkbox" data-review-cost>明确允许费用未知并接受上述风险预算</label><button type="button" data-review-preview>预览当前完整规则（不发送）</button><pre data-review-source></pre><button type="button" data-review-prepare disabled>冻结请求与预算（不发送）</button><button type="button" data-review-refresh>刷新历史</button><button type="button" data-review-recover>显式恢复中断状态（不重发）</button>';
  const project=workspace.document.project.id,saved=preparationDrafts.get(project);
  if(saved)for(const key of draftFields){const input=root.querySelector('[data-review-'+key+']');if(key!=='connection'||connections.some(c=>c.id===saved[key]))input.value=saved[key];}
  const capture=()=>{preparationDrafts.set(project,Object.fromEntries(draftFields.map(key=>[key,root.querySelector('[data-review-'+key+']').value])));preview=null;root.querySelector('[data-review-prepare]').disabled=true;};
  root.addEventListener('input',capture);root.addEventListener('change',capture);
  root.addEventListener('click',event=>{const button=event.target.closest('button');if(!button||busy)return;void (async()=>{busy=true;notice.textContent='';try{
   if(button.hasAttribute('data-review-preview')){const chapter_id=document.getElementById('rule-resolve-chapter').value,target_task_id=document.getElementById('rule-active-task').value||null;preview=await post(base+'/preview',{chapter_id,target_task_id});root.querySelector('[data-review-source]').textContent=JSON.stringify(preview,null,2);root.querySelector('[data-review-prepare]').disabled=false;}
   else if(button.hasAttribute('data-review-prepare')){if(!preview)throw Error('请重新预览规则');if(!root.querySelector('[data-review-cost]').checked)throw Error('请明确接受费用未知与风险预算');if(preview.chapter_id!==document.getElementById('rule-resolve-chapter').value||preview.target_task_id!==(document.getElementById('rule-active-task').value||null))throw Error('章节/任务选择已变化，请重新预览');const c=connections.find(c=>c.id===root.querySelector('[data-review-connection]').value);if(!c)throw Error('请先在模型中心明确保存自建连接和默认模型');const number=key=>Number(root.querySelector('[data-review-'+key+']').value);await post(base+'/prepare',{request_id:crypto.randomUUID(),chapter_id:preview.chapter_id,target_task_id:preview.target_task_id,source_sha256:preview.source_sha256,model_options:{adapter_id:c.adapter_id,connection_id:c.id,model_id:c.model_id,temperature:.3,max_tokens:number('tokens'),budget_limit:number('risk'),allow_unknown_cost:true,prompt_version:'rule-conflicts-json-1'},max_output_chars:number('chars'),timeout_ms:number('timeout'),budget_max_calls:number('calls'),budget_max_output_tokens:number('total')});preview=null;root.querySelector('[data-review-prepare]').disabled=true;await refresh();notice.textContent='已冻结；尚未发送。展开请求逐项复核后再确认。';}
   else if(button.hasAttribute('data-review-refresh'))await refresh();
   else if(button.hasAttribute('data-review-recover')){await post(base+'/recover',{});await refresh();}
   else{const card=button.closest('[data-review-task]'),view=listing.tasks.find(v=>v.task.id===card?.dataset.reviewTask);if(!view)return;const url=base+'/'+encodeURIComponent(view.task.id);
    if(button.hasAttribute('data-review-execute')){if(!card.querySelector('[data-review-confirm]').checked)throw Error('每个请求都必须明确复核并确认');card.querySelector('[data-review-confirm]').checked=false;await post(url+'/execute',{confirm_external:true,request_sha256:view.task.binding.request_sha256});await refresh();}
    else if(button.hasAttribute('data-review-cancel')){await post(url+'/cancel',{});await refresh();}
    else if(button.hasAttribute('data-review-inspect')){const latest=await api(url),result=await post(url+'/inspect',{result_id:button.dataset.reviewInspect,request_sha256:latest.task.binding.request_sha256,expected_revision:latest.revision});card.querySelector('[data-review-inspected]').textContent=JSON.stringify(result,null,2);}
   }
  }catch(error){notice.textContent=error.message;}finally{busy=false;}})();});
  await refresh();const poll=async()=>{if(!root.isConnected)return;try{if(!busy&&listing?.tasks.some(v=>v.status==='running'))await refresh();}catch(error){notice.textContent=error.message;}if(root.isConnected)setTimeout(poll,750);};setTimeout(poll,750);
 }catch(error){notice.textContent=error.message;}
}
