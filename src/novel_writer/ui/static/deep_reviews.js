import {api} from './api.js';
import {escapeHTML as h,activeChapters} from './views.js';
import {renderSampling,captureSampling,samplingOptions} from './sampling.js';

const drafts=new Map(),reasons=new Map(),decisions=new Map();
const checks=[['relative_time','相对时间与锚点'],['uncertain_time','不确定时间与区间'],['duration','持续时间与单位'],['causality','因果与信息传递'],['motivation','人物动机'],['character_knowledge','人物知识边界'],['book_pacing','全书节奏（主观意见）'],['character_arc','人物弧光（主观意见）'],['semantic_repetition','语义重复桥段（双侧证据）']];
const pre=value=>'<pre class="context-text">'+h(typeof value==='string'?value:JSON.stringify(value,null,2)).replaceAll('\r','&#13;')+'</pre>';
const multi=(name,label,items)=>'<label>'+h(label)+'<select data-passive name="'+name+'" multiple>'+items.map(([id,title,selected])=>'<option value="'+h(id)+'" '+(selected?'selected':'')+'>'+h(title)+'</option>').join('')+'</select></label>';
const field=(name,label,value,type='text')=>'<label>'+h(label)+'<input name="'+name+'" type="'+type+'" value="'+h(value)+'" '+(type==='number'?'step="any"':'')+'></label>';

export function renderDeepReviewPrepare(workspace,chapter,caps){
 const chapters=activeChapters(workspace),project=workspace.document.project.id,connection=caps.connections?.[0];
 const d=drafts.get(project)||{connection_id:connection?.id||'',model_id:connection?.model_id||'',temperature:.3,max_tokens:4096,budget_limit:1,max_output_chars:20000,timeout_ms:120000,instruction:'核对所选范围的时间、因果、知识边界、节奏、人物弧光与重复桥段；证据不足保留待核实。',checks:checks.map(v=>v[0]),chapter_ids:[chapter],candidate_ids:[],material_ids:[],memory_ids:[],planning_ids:[],allow_unknown_cost:false};
 drafts.set(project,d);
 const plans=[...(workspace.document.book_outline?[workspace.document.book_outline]:[]),...workspace.document.chapter_outlines,...(workspace.character_arcs||[]),...(workspace.key_events||[])];
 const candidates=(workspace.generation_candidates||[]).filter(c=>!(workspace.adoption_receipts||[]).some(r=>r.candidate_id===c.id));
 return '<section id="deep-review-preparation" class="panel"><h2>深层审核与语义查重（明确选择本地范围）</h2><p>九类检查产生带引文的待核实模型意见。相对时间须核对锚点，时间区间重叠不能当矛盾，人物未知不能按叙述者知识补全。节奏与弧光属于主观意见，部分章节不会标成全书覆盖。</p><p>本功能复用保存正文模型审核与真实候选身份守卫。候选未采纳、资料仅参考、规划未发生；不自动改稿或生成事实。只比较所选本书集合，不是全网查重或原创性保证。</p><form id="deep-review-prepare-form"><label><input type="checkbox" name="whole_book" '+(d.whole_book?'checked':'')+'>明确选择整书分批审核（包含当前全部有效章；每批仍须在任务页确认发送）</label>'+field('batch_size','每批章数（1–40，硬上限40）',d.batch_size||10,'number')+multi('chapter_ids','单批正文范围（最多40章）',chapters.map(c=>[c.id,'第'+c.number+'章 · '+c.title,d.chapter_ids.includes(c.id)]))+multi('candidate_ids','明确授权发送的真实候选',candidates.map(c=>[c.id,'候选 '+c.id,d.candidate_ids.includes(c.id)]))+multi('material_ids','明确授权发送的本地资料（须当前索引）',(workspace.materials||[]).filter(m=>!m.archived).map(m=>[m.id,m.title,d.material_ids.includes(m.id)]))+multi('memory_ids','已确认事实记忆（过期/归档后拒绝）',(workspace.memories||[]).filter(m=>m.active&&m.confirmed).map(m=>[m.id,m.title,d.memory_ids.includes(m.id)]))+multi('planning_ids','显式规划/人物弧光/事件（计划材料）',plans.map(p=>[p.id,p.title||p.name||p.id,d.planning_ids.includes(p.id)]))+multi('checks','本次检查项目',checks.map(([id,title])=>[id,title,d.checks.includes(id)]))+'<label>模型连接<select name="connection_id">'+(caps.connections||[]).map(c=>'<option value="'+h(c.id)+'" '+(c.id===d.connection_id?'selected':'')+'>'+h(c.name||c.id)+'</option>').join('')+'</select></label>'+field('model_id','模型编号',d.model_id)+field('instruction','本次审核要求',d.instruction)+field('temperature','温度',d.temperature,'number')+field('max_tokens','输出token上限',d.max_tokens,'number')+renderSampling('deep',d.sampling)+field('budget_limit','单次风险预算（美元，非硬封顶）',d.budget_limit,'number')+field('max_output_chars','JSON字符上限',d.max_output_chars,'number')+field('timeout_ms','总时限（毫秒）',d.timeout_ms,'number')+'<label><input type="checkbox" name="allow_unknown_cost" '+(d.allow_unknown_cost?'checked':'')+'>我理解费用未知，并在任务页逐次确认确切外发请求</label><button type="submit" '+(caps.real_model_enabled?'':'disabled')+'>冻结深层审核请求（不发送）</button><p id="deep-review-prepare-status" role="status"></p></form><section id="deep-review-books" aria-live="polite"></section></section>';
}

export function bindDeepReviewPrepare(root,workspace,chapter,onPrepared){
 const form=root.querySelector('#deep-review-prepare-form');if(!form)return;
 const project=workspace.document.project.id,d=drafts.get(project),enabled=!form.querySelector('[type="submit"]').disabled;let busy=false,payload=null;
 const bookRoot=root.querySelector('#deep-review-books');
 const chapterLabel=id=>{const c=chaptersForBook().find(c=>c.id===id);return c?'第'+c.number+'章 · '+c.title+' ('+id+')':id;};
 const chaptersForBook=()=>workspace.document.chapters;
 const chapterLabels=ids=>ids.map(chapterLabel);
 const refreshBooks=async()=>{try{const result=await api('/api/projects/'+encodeURIComponent(project)+'/deep-review-books/list');
 bookRoot.innerHTML='<h3>整书分批审核 · 可重开续跑</h3><button type="button" data-book-refresh>刷新批次状态</button>'+result.runs.map(run=>'<article data-book-run="'+h(run.id)+'"><h4>'+h(run.created_at)+' · '+(run.coverage.complete?'全部当前正文已审':'尚未覆盖全书')+'</h4><p>已审 '+run.coverage.reviewed_chapters.length+' / '+run.coverage.total_chapters+' 章（'+Math.round(run.coverage.ratio*100)+'%）</p>'+pre({已审:chapterLabels(run.coverage.reviewed_chapters),未审:chapterLabels(run.coverage.unreviewed_chapters),来源变化:chapterLabels(run.coverage.stale_chapters),失败批次:run.failed_batches.map(i=>i+1)})+run.limitations.map(x=>'<p>'+h(x)+'</p>').join('')+run.batches.map(b=>'<div><p>第 '+(b.index+1)+' 批 · '+h(b.status)+' · '+b.chapter_ids.length+' 章</p>'+pre(chapterLabels(b.chapter_ids))+pre(b.attempts)+'<button type="button" data-book-batch="'+b.index+'" data-book-revision="'+run.revision+'">准备 / 查看本批任务（不发送）</button>'+(['failed','cancelled','interrupted'].includes(b.status)?'<button type="button" data-book-batch="'+b.index+'" data-book-retry="true" data-book-revision="'+run.revision+'">明确重试本批（可能再次计费；仍需确认发送）</button>':'')+'</div>').join('')+'<details><summary>分批汇总报告（模型意见待核实）</summary>'+run.reports.map(r=>pre(r.output)).join('')+pre(run.chapters)+'</details></article>').join('');
 }catch(error){bookRoot.textContent='整书审核清单读取失败：'+error.message;}};
 bookRoot.addEventListener('click',async event=>{const button=event.target.closest('button');if(!button||busy)return;event.preventDefault();event.stopPropagation();if(button.hasAttribute('data-book-refresh')){await refreshBooks();return;}if(!button.hasAttribute('data-book-batch'))return;
 try{busy=true;button.disabled=true;const run=button.closest('[data-book-run]').dataset.bookRun,result=await api('/api/projects/'+encodeURIComponent(project)+'/deep-review-books/'+encodeURIComponent(run)+'/prepare',{method:'POST',body:JSON.stringify({batch_index:Number(button.dataset.bookBatch),retry_failed:button.dataset.bookRetry==='true',expected_revision:Number(button.dataset.bookRevision)})});await onPrepared(result.task.id);
 }catch(error){form.querySelector('#deep-review-prepare-status').textContent=error.message+'；不自动重试。';}finally{busy=false;button.disabled=false;}});
 void refreshBooks();
 const capture=()=>{for(const e of form.elements){if(!e.name)continue;d[e.name]=e.multiple?[...e.selectedOptions].map(o=>o.value):e.type==='checkbox'?e.checked:e.value;}d.sampling=captureSampling(form.querySelector('[data-sampling="deep"]'));payload=null;};
 form.addEventListener('input',capture);form.addEventListener('change',capture);
 form.addEventListener('submit',async event=>{event.preventDefault();event.stopPropagation();if(busy)return;
  const status=form.querySelector('#deep-review-prepare-status'),button=form.querySelector('[type="submit"]');
  try{if(!d.allow_unknown_cost)throw Error('请明确核对费用未知风险。');if(!d.whole_book&&!d.chapter_ids.length)throw Error('请明确选择正文范围。');
   if(!payload)payload={request_id:crypto.randomUUID(),chapter_id:d.chapter_ids.includes(chapter)?chapter:d.chapter_ids[0],chapter_ids:d.chapter_ids,selection:{checks:d.checks,candidate_ids:d.candidate_ids,material_ids:d.material_ids,memory_ids:d.memory_ids,planning_ids:d.planning_ids},instruction:d.instruction,max_output_chars:Number(d.max_output_chars),timeout_ms:Number(d.timeout_ms),expected_revision:workspace.revision,model_options:{...samplingOptions(d.sampling),adapter_id:['gg','catie','odys'].includes(d.connection_id)?'chat-completions-http-v1':'configured-http-v2',connection_id:d.connection_id,model_id:d.model_id,temperature:Number(d.temperature),max_tokens:Number(d.max_tokens),budget_limit:Number(d.budget_limit),allow_unknown_cost:true,prompt_version:'deep-review-json-1'}};
   busy=true;button.disabled=true;let path='/deep-reviews/prepare',body=payload;if(d.whole_book){path='/deep-review-books/create';body={...payload,batch_size:Number(d.batch_size||10)};delete body.chapter_ids;delete body.chapter_id;}const result=await api('/api/projects/'+encodeURIComponent(project)+path,{method:'POST',body:JSON.stringify(body)});payload=null;if(d.whole_book){status.textContent='整书批次清单已保存；尚未发送。';await refreshBooks();}else await onPrepared(result.task.id);
  }catch(error){status.textContent=error.message+'；输入保留，不自动发送或重试。';}finally{busy=false;if(button.isConnected)button.disabled=!enabled;}
 });
}

export function renderDeepReview(detail){
 const project=detail.report.project_id;
 return '<section id="model-review-panel" class="panel"><h2>深层审核与语义重复提案 · 全部待核实</h2><p>方法：模型意见；引文校验只证明出处，不证明判断正确。'+(detail.outdated?'来源已变化，报告已过期。':'冻结来源未变。')+'</p><p>正文覆盖 '+detail.coverage.selected_chapters+' / '+detail.coverage.total_active_chapters+' 章 · '+(detail.coverage.mode==='full_book'?'覆盖当前有效全书正文':'仅所选章节，不能代表全书结论')+'</p>'+pre(detail.output.overview)+detail.limitations.map(v=>'<p>'+h(v)+'</p>').join('')+detail.findings.map(entry=>{
  const key=project+'/'+detail.report.id+'/'+entry.index,reason=reasons.get(key)||'';
  return '<article class="context-card" data-deep-finding="'+entry.index+'"><h3>'+h(entry.finding.category)+' · '+h(entry.status)+'</h3><p>'+h(entry.finding.statement)+'</p>'+entry.finding.evidence.map(e=>'<p>'+h(e.source_kind)+' · '+h(e.entity_id)+' · 版本 '+h(e.version_id||'候选/结构来源')+' · Unicode字符 ['+e.start+', '+e.end+')</p>'+pre(e.quote)+'<details><summary>实际来源身份与摘要</summary>'+pre(e)+'</details>').join('')+'<label>误报/豁免/重新打开的理由<textarea data-deep-reason="'+entry.index+'">'+h(reason)+'</textarea></label><button type="button" data-deep-kind="false_positive">记录误报</button><button type="button" data-deep-kind="waive">豁免精确双侧证据</button><button type="button" data-deep-kind="reopen">重新打开</button><details><summary>追加处理历史（不代表事实确认）</summary>'+pre(entry.history)+'</details></article>';
 }).join('')+'<p id="model-review-operation" role="status"></p><details><summary>完整冻结实际来源，可按Unicode区间复核</summary>'+pre(detail.scope)+'</details><details><summary>实际模型返回与真实/未知用量</summary>'+pre(detail.response.response)+'</details></section>';
}

export function bindDeepReview(root,workspace,detail,onRefresh){
 let busy=false;const project=workspace.document.project.id;
 root.addEventListener('input',event=>{if(event.target.dataset.deepReason!==undefined)reasons.set(project+'/'+detail.report.id+'/'+event.target.dataset.deepReason,event.target.value);});
 root.addEventListener('click',async event=>{const button=event.target.closest('[data-deep-kind]');if(!button||busy)return;event.stopPropagation();
  const index=Number(button.closest('[data-deep-finding]').dataset.deepFinding),key=project+'/'+detail.report.id+'/'+index,reason=reasons.get(key)||'',decisionKey=key+'/'+button.dataset.deepKind;
  try{if(!reason.trim())throw Error('请填写处理理由，原报告与引文仍会保留。');let request=decisions.get(decisionKey);
   if(!request){request={operation_id:crypto.randomUUID(),expected_revision:detail.revision,finding_index:index,kind:button.dataset.deepKind,reason};decisions.set(decisionKey,request);}else if(request.reason!==reason)throw Error('已有待核对的处理请求；请保留原理由后重试或刷新核对。');
   busy=true;button.disabled=true;await api('/api/projects/'+encodeURIComponent(project)+'/deep-reviews/'+detail.report.id+'/decision',{method:'POST',body:JSON.stringify(request)});decisions.delete(decisionKey);await onRefresh();
  }catch(error){root.querySelector('#model-review-operation').textContent=error.message;}finally{busy=false;if(button.isConnected)button.disabled=false;}
 });
}
