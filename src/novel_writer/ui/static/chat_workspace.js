import {api,downloadFile} from './api.js';
import {escapeHTML as h} from './views.js';

const attachmentScopes=new Map();
let sendingAttachments=false;
const scopeKey=project=>project||'unbound';
function attachmentState(project){
 const key=scopeKey(project);
 if(!attachmentScopes.has(key))attachmentScopes.set(key,{selected:new Map(),files:[],uploads:0,error:'',generation:0});
 return attachmentScopes.get(key);
}
export function hasPendingAttachments(project){return attachmentState(project).selected.size>0;}
export function attachmentsUploading(project){return attachmentState(project).uploads>0||sendingAttachments;}
function attachmentRows(state){
 const selected=[...state.selected.values()].map(file=>`<li><span>${h(file.filename||file.title)} · ${h(file.busy?'上传中':file.error||'已解析 · 待发送分类')}</span><button type="button" data-attachment-action="remove" data-id="${h(file.id)}" ${file.busy||sendingAttachments?'disabled':''}>移除</button>${file.retry?`<button type="button" data-attachment-action="retry" data-id="${h(file.id)}" ${sendingAttachments?'disabled':''}>重试上传</button>`:''}</li>`).join('');
 const library=state.files.map(file=>`<li><span>${h(file.filename||file.title)} · ${h(file.archived?'已归档':file.error|| (file.material_id?'已保存资料':'已解析'))}</span><button type="button" data-attachment-action="download" data-id="${h(file.id)}">下载原件</button>${!file.archived&&file.status==='parsed'?`<button type="button" data-attachment-action="select" data-id="${h(file.id)}" ${sendingAttachments||state.selected.has(file.id)?'disabled':''}>再次选择</button>`:''}<button type="button" data-attachment-action="${file.archived?'restore':'archive'}" data-id="${h(file.id)}" ${sendingAttachments?'disabled':''}>${file.archived?'恢复':'归档'}</button></li>`).join('');
 return `<p class="attachment-privacy">支持 TXT / MD / DOCX / PDF，单文件 ≤ 8 MiB；上传与解析仅在本机进行。点击发送后，所选内容才交给当前 API 模型自动分类（合计 ≤ 120000 字符）。原件持久保存在本机；归档原件不撤销已保存正文与设定。</p><p role="status">${h(state.error|| (state.uploads?'正在上传，请稍候再发送。':''))}</p><ul class="attachment-selection">${selected}</ul><details><summary>附件库（${state.files.length}）</summary><ul>${library||'<li>暂无已保存附件</li>'}</ul><p>原件下载单独留存；文档全量备份目前不包含附件原件。</p></details>`;
}
function paintAttachments(){
 const root=document.querySelector('#chat-attachments');
 if(root)root.innerHTML=attachmentRows(attachmentState(hooks?.project()));
 composerState(Boolean(activeJob));
}
async function loadAttachments(project){
 const state=attachmentState(project),generation=++state.generation;
 try{
  const result=await api(base+'/attachments/'+encodeURIComponent(scopeKey(project)));
  if(generation!==state.generation)return;
  state.files=Array.isArray(result)?result:(result.attachments||[]);
 }catch(error){if(generation===state.generation)state.error='附件库读取失败：'+error.message;}
 if(scopeKey(hooks?.project())===scopeKey(project))paintAttachments();
}
function fileBase64(file){
 return new Promise((resolve,reject)=>{
  if(file.size>8*1024*1024){reject(new Error('单文件不能超过 8 MiB'));return;}
  const reader=new FileReader();
  reader.onerror=()=>reject(new Error('无法读取文件，请重新选择'));
  reader.onabort=()=>reject(new Error('文件读取已取消'));
  reader.onload=()=>resolve(String(reader.result).split(',')[1]);
  reader.readAsDataURL(file);
 });
}
async function uploadSelected(project,entry){
 const state=attachmentState(project);state.uploads++;entry.busy=true;entry.error='';entry.retry=false;paintAttachments();
 try{
  const content_base64=await fileBase64(entry.file);
  const result=await post(base+'/attachment',{filename:entry.filename,content_base64,project_id:project||null,operation_id:entry.operationId});
  state.selected.delete(entry.id);
  if(result.status==='parsed')state.selected.set(result.id,result);
  else state.error=entry.filename+'：'+(result.error||'解析失败，原件已保留，可从附件库下载');
  await loadAttachments(project);
 }catch(error){entry.error=error.message;entry.retry=true;}
 finally{entry.busy=false;state.uploads--;paintAttachments();}
}
async function acceptAttachments(files,project){
 const state=attachmentState(project);
 for(const file of files){
  if(!/\.(txt|md|markdown|docx|pdf)$/i.test(file.name)||file.size>8*1024*1024){state.error=file.name+'：仅支持 TXT、MD、DOCX、PDF，且每个文件不超过 8 MiB';paintAttachments();continue;}
  const entry={id:crypto.randomUUID(),operationId:crypto.randomUUID(),filename:file.name,file,busy:true};
  state.selected.set(entry.id,entry);await uploadSelected(project,entry);
 }
}
function bindAttachments(){
 const composer=document.querySelector('#chat-composer'),tools=composer?.querySelector('.composer-tools');
 if(!composer||!tools)return;
 if(!document.querySelector('#chat-upload')){
  const button=document.createElement('button');button.type='button';button.id='chat-upload';button.textContent='上传文件';
  const input=document.createElement('input');input.id='chat-upload-input';input.type='file';input.multiple=true;input.accept='.txt,.md,.markdown,.docx,.pdf';input.hidden=true;
  tools.prepend(button,input);
  const root=document.createElement('div');root.id='chat-attachments';root.className='chat-attachments';composer.append(root);
 }
 const input=document.querySelector('#chat-upload-input');
 const localButton=document.querySelector('#chat-local-path');
 if(localButton)localButton.onclick=async()=>{
  const field=document.querySelector('#chat-local-path-input'),project=hooks?.project();
  localButton.disabled=true;
  try{await importLocalPath(field.value,project);field.value='';}
  catch(error){hooks?.notice(error.message,true);}
  finally{localButton.disabled=false;}
 };
 document.querySelector('#chat-upload').onclick=()=>input.click();
 input.onchange=()=>{const files=Array.from(input.files||[]),project=hooks?.project();input.value='';void acceptAttachments(files,project);};
 composer.ondragover=event=>{if(event.dataTransfer?.types.includes('Files')){event.preventDefault();composer.classList.add('attachment-dragover');}};
 composer.ondragleave=()=>composer.classList.remove('attachment-dragover');
 composer.ondrop=event=>{event.preventDefault();composer.classList.remove('attachment-dragover');if(sendingAttachments)return;void acceptAttachments(Array.from(event.dataTransfer?.files||[]),hooks?.project());};
 document.querySelector('#chat-attachments').onclick=async event=>{
  const button=event.target.closest('[data-attachment-action]');if(!button)return;
  const project=hooks?.project(),state=attachmentState(project),id=button.dataset.id,action=button.dataset.attachmentAction;
  const file=state.files.find(f=>f.id===id)||state.selected.get(id);if(!file)return;
  button.disabled=true;
  try{
   if(action==='remove')state.selected.delete(id);
   else if(action==='retry')await uploadSelected(project,file);
   else if(action==='select')state.selected.set(id,file);
   else if(action==='download')await downloadFile(base+'/attachment/'+encodeURIComponent(id)+'/download',file.filename||file.title);
   else {await post(base+'/attachment/'+encodeURIComponent(id)+'/'+action,{project_id:project||null});state.selected.delete(id);await loadAttachments(project);}
  }catch(error){state.error=error.message;}
  finally{paintAttachments();}
 };
 paintAttachments();void loadAttachments(hooks?.project());
}
const base='/api/settings/chat';
let timer=null,activityTimer=null,activityInFlight=false,activityEpoch=0,activeJob=null,pending=null,hooks=null;
let cancelPendingJobId=null;
const chatSessions=new Map();
let chatRender=0,sessionBusy=false;
export function resetAgentView(){
 ++chatRender;++activityEpoch;
 if(timer)clearTimeout(timer);
 if(activityTimer)clearTimeout(activityTimer);
 timer=null;activityTimer=null;activeJob=null;cancelPendingJobId=null;hooks=null;
}
function displayedJob(){
 const project=hooks?.project();
 return activeJob&&activeJob.project_id===project&&activeJob.session_id===sessionState(project).id?activeJob:null;
}
function activityHTML(rows=[]){
 const visible=rows.slice(0,2);
 return `<aside id="chat-running-books" class="panel" role="status"><strong>后台创作：${visible.length}/2 本书</strong>${visible.length?visible.map(j=>`<p>${h(j.title||'小说')} · ${h(j.status==='running'?'运行中':'正在结束')}</p>`).join(''):'<p>当前没有后台创作任务。</p>'}<details><summary>技术详情</summary>${visible.map(j=>`<p>项目 ${h(j.project_id)} · 会话 ${h(j.session_id)} · 任务 ${h(j.id)}</p>`).join('')||'<p>暂无任务编号。</p>'}</details></aside>`;
}
const consoleBase=project=>'/api/projects/'+encodeURIComponent(project)+'/console';
function sessionState(project){
 if(!chatSessions.has(project))chatSessions.set(project,{id:'',initialized:false,sessions:[],running:false});
 return chatSessions.get(project);
}
function sessionChangeBlocked(project,action){
 if(sessionBusy||sendingAttachments||(action!=='select'&&(displayedJob()||sessionState(project).running)))return '请先停止或等待当前任务完成，再操作会话。';
 if(document.querySelector('#chat-input')?.value||hasPendingAttachments(project)||attachmentsUploading(project))return '请先发送或清空输入，并发送或移除所选附件、等待上传完成，再操作会话；草稿不会转移到其他会话。';
 return '';
}
const post=(url,value)=>api(url,{method:'POST',body:JSON.stringify(value)});
const labels={running:'创作中',completed:'已完成',failed:'未完成',cancelled:'已停止',interrupted:'上次任务已中断',awaiting_confirmation:'等待删除确认'};
const reviewLabels={reviewing:'审核中',passed:'通过',failed:'未通过',unverified:'未核实',stale:'正文已变更，需重新审核',accepted_by_author_rule:'达到五次，按作者规则放行'};
function contextReceipt(job){
 const list=value=>Array.isArray(value)?value:[],count=value=>Array.isArray(value)?value.length:Number(value)||0;
 const esc=value=>h(value==null?'未记录':String(value)),items=(values,render,empty)=>list(values).map(value=>render(value??{})).join('')||`<li>${h(empty)}</li>`;
 const latest=list(job?.context_usage).at(-1),manifest=list(job?.skills_manifest);
 const purposes={planner:'规划',writer:'写作',reviewer:'审核',revision:'修订',maintenance:'资料同步'};
 const statuses={prepared:'已准备',request_attempted:'已尝试请求',response_received:'已收到响应'};
 const skills=items(manifest,s=>`<li>${esc(s.name)} · ID ${esc(s.id)} · SHA256 ${esc(s.sha256)}<ul>${items(s.files,f=>`<li>${esc(f.path)} · SHA256 ${esc(f.sha256)} · ${esc(f.chars)} 字符</li>`,'无文件记录')}</ul></li>`,'无 Skill 记录');
 const runtimePolicy=latest?.runtime_author_policy;const policyReceipt=runtimePolicy?`<details data-receipt-key="runtime-policy"><summary>当前创作与审核标准</summary><p>正文至少 ${esc(runtimePolicy.han_count_minimum??4000)} 个汉字，无字数上限。</p><p>每章最多保存 ${esc(runtimePolicy.automatic_revision_save_limit_per_chapter_per_job??5)} 次自动修订；第${esc(runtimePolicy.automatic_revision_save_limit_per_chapter_per_job??5)}次成功保存后按作者规则放行并继续维护，不再调用独立审核。</p><ol><li>${h('遵循当前有效章节细纲与全书大纲')}</li><li>${h('有具体依据的因果逻辑、连续性、时间线和人物事实')}</li><li>${h('导入文风规则与自然表达')}</li></ol></details>`:'';const skillDetails=`${policyReceipt}<details data-receipt-key="skills"><summary>Skills 清单</summary><p>Skills ${h(manifest.length)} 项，文件 ${h(manifest.reduce((n,s)=>n+list(s?.files).length,0))} 个。</p><ul>${skills}</ul></details>`;
 if(!latest)return `<details data-receipt-key="context-empty"><summary>请求上下文记录</summary><p>尚无请求记录</p>${skillDetails}</details>`;
 const coverage=latest.coverage||{},rules=latest.rules??coverage.rules??{},memories=coverage.memories||{};
 const chapters=items(latest.chapters,c=>`<li>第 ${esc(c.number)} 章 · ID ${esc(c.id)} · SHA256 ${esc(c.body_sha256)}</li>`,'无正文记录');
 const omitted=list(coverage.body_omitted_numbers).map(value=>esc(value)).join('、')||'无';
 const outlines=Array.isArray(coverage.outlines)?coverage.outlines:coverage.outlines?.omitted;
 const includedRules=items(rules.included,r=>`<li>ID ${esc(r.id??r.rule_id)} · 版本 ${esc(r.version_id??r.version)} · 范围 ${esc(r.scope)} · SHA256 ${esc(r.sha256??r.body_sha256??r.hash)}</li>`,'无纳入规则记录');
 const pages=items(latest.material_pages,p=>`<li>ID ${esc(p.material_id)} · 版本 ${esc(p.version_id)} · 范围 ${esc(p.offset)}–${esc(p.end)} · SHA256 ${esc(p.sha256)}</li>`,'无实际资料页记录');
 const materials=items(latest.materials,m=>`<li>ID ${esc(m.material_id??m.id)} · 版本 ${esc(m.version_id)} · 名称 ${esc(m.name??m.title)}</li>`,'无资料元数据记录');
 const filterCounts=Object.entries(memories).filter(([key,value])=>/_excluded$/i.test(key)&&(Array.isArray(value)||typeof value==='number')).map(([key,value])=>`${esc(key)}：${h(count(value))}`).join('；')||'无筛选计数记录';
 const http=latest.http_status!=null?` · HTTP ${esc(latest.http_status)}`:'';
 return `<details data-receipt-key="context"><summary>请求上下文记录</summary><p>最新请求：版本 ${esc(latest.project_revision)} · ${esc(purposes[latest.purpose]||latest.purpose)} · 调用 ${esc(latest.call_ordinal)} · ${esc(statuses[latest.status]||'状态未记录')}${http}。</p><p>本记录仅说明请求纳入情况或响应接收状态，不证明模型遵从，也不证明模型已读完全部内容。</p><details data-receipt-key="context-body"><summary>正文与覆盖</summary><ul>${chapters}</ul><p>未纳入正文章节：${omitted}；排除已删除章节 ${h(count(coverage.hidden_chapter_count))} 章。未纳入人物 ${h(count(coverage.characters?.omitted))} 项、记忆 ${h(count(memories.omitted))} 项、细纲 ${h(count(outlines))} 项。</p><p>记忆纳入 ${h(count(memories.selected??memories.included))} 项；筛选统计：${filterCounts}。</p></details><details data-receipt-key="context-rules"><summary>规则</summary><p>纳入 ${h(count(rules.included))} 项；条件规则 ${h(count(rules.conditional))} 项；省略 ${h(count(rules.omitted))} 项；冲突 ${h(count(rules.conflicts))} 项。</p><ul>${includedRules}</ul></details><details><summary>资料元数据与实际页记录</summary><p>资料元数据 ${h(count(latest.materials))} 项（不是页数，不代表正文已纳入）。</p><ul>${materials}</ul><p>实际资料页记录 ${h(count(latest.material_pages))} 项：</p><ul>${pages}</ul></details>${skillDetails}</details>`;
}
export function requestCountsText(job){
 const count=value=>{const n=Number(value);return Number.isFinite(n)&&n>0?Math.floor(n):0;};
 const stats=job?.request_stats;
 if(!stats||typeof stats!=='object'||Array.isArray(stats))return `历史发送${count(job?.calls)}次（有效响应与重发次数未记录）`;
 const complete=count(stats.response_complete),resends=count(stats.network_resends),unknown=count(stats.unknown),missingResends=count(stats.resend_unknown);
 const values=[unknown?(complete?`已确认有效响应 ${complete} 次`:'有效响应次数待核实'):`有效响应 ${complete} 次`,missingResends?(resends?`已记录网络重发 ${resends} 次`:'网络重发次数未记录'):`网络重发 ${resends} 次`,`完成 ${count(job?.actions)} 项操作`];
 for(const [key,label] of [['pending','待处理'],['failed','失败'],['cancelled','已取消'],['unknown','未核实']]){const n=count(stats[key]);if(n)values.push(`${label} ${n} 次`);}
 const historical=count(stats.historical_http200);if(historical)values.push(`历史HTTP200响应${historical}次（完整性未记录）`);
 const resendUnknown=count(stats.resend_unknown);if(resendUnknown)values.push(`重发记录未知 ${resendUnknown} 次`);
 values.push(`实际发送 ${count(stats.total_attempts)} 次`);
 return values.join(' · ');
}
function reviewStatus(job){
 const reports=job.chapter_reviews||[],counts=job.review_counts||{},actualPassed=Number(job.passed_count)||0,authorAccepted=Number(job.author_accepted_count??counts.accepted_by_author_rule)||0;
 return `<p>正文章节：生成 ${h(job.generated_count||0)} · 保存 ${h(job.saved_count||0)} · 已审核 ${h(job.reviewed_count||0)} · 实际审核通过 ${h(actualPassed)} · 按作者规则放行 ${h(authorAccepted)} · 未通过 ${h(counts.failed||0)} · 未核实 ${h(counts.unverified||0)} · 已过期 ${h(counts.stale||0)}</p><p>审核状态：${h(reviewLabels[job.review_status]||'尚未审核')}</p>${reports.map((report,index)=>{const isAuthorAccepted=report.status==='accepted_by_author_rule',revision=report.revision_iteration==null?'':` · 自动修订${h(report.revision_iteration)}/5`,round=report.iteration==null||isAuthorAccepted?'':` · 审核第${h(Number(report.iteration)+1)}轮`,key=report.id??report.report_id??`${report.number}-${report.source_revision}-${report.content_sha256||''}-${report.status}-${report.revision_iteration??''}-${index}`;return `<details data-receipt-key="review:${h(key)}"><summary>第${h(report.number)}章 · ${h(reviewLabels[report.status]||report.status)}${revision}${round}</summary><p>${isAuthorAccepted?'此作者规则放行回执未经过审核。':`审核：${h(report.reviewer?.name||'')} · ${h(report.reviewer?.model_id||'')} · 源版本 ${h(report.source_revision)}`}</p>${report.previous_review_report_id?`<p>关联前次审核报告：${h(report.previous_review_report_id)}</p>`:''}${report.acceptance_reason?`<p>放行原因：${h(report.acceptance_reason)}</p>`:''}<p>正文 SHA256：${h(report.content_sha256)}</p>${report.material_id?`<p>报告已保存至资料库：${h(report.material_id)}</p>`:''}${report.error?`<p>${h(report.error)}</p>`:''}${report.diagnostics!=null?`<details><summary>审核诊断</summary><pre>${h(typeof report.diagnostics==='string'?report.diagnostics:JSON.stringify(report.diagnostics,null,2))}</pre></details>`:''}${report.raw_response!=null?`<details><summary>审核原始响应</summary><pre>${h(report.raw_response)}</pre></details>`:''}<ul>${(report.issues||[]).map(issue=>`<li>${h(issue.severity)} / ${h(issue.category)}：${h(issue.message)}<blockquote>${h(issue.evidence)}</blockquote></li>`).join('')}</ul></details>`;}).join('')}`;
}

function sessionTrash(state){
 const deleted=state.deleted||[];
 return deleted.length?`<details class="chat-session-trash"><summary>会话回收站（${deleted.length}）</summary>${deleted.map(s=>`<p>${h(s.title)} <button type="button" data-chat-session="restore" data-session-id="${h(s.id)}">恢复会话</button></p>`).join('')}</details>`:'';
}
function sessionTitle(initial){
 return new Promise(resolve=>{
  const dialog=document.createElement('dialog');
  dialog.innerHTML='<form method="dialog"><label>会话名称<input name="title" maxlength="200" required></label><button value="save">保存</button><button value="cancel" formnovalidate>取消</button></form>';
  dialog.querySelector('input').value=initial;
  dialog.addEventListener('close',()=>{const value=dialog.returnValue==='save'?dialog.querySelector('input').value.trim():null;dialog.remove();resolve(value||null);},{once:true});
  document.body.append(dialog);dialog.showModal();dialog.querySelector('input').focus();
 });
}

export async function renderAgentChat(workspace){
 const project=workspace?.document.project.id||'',epoch=++chatRender,entryHooks=hooks;
 if(timer)clearTimeout(timer);
 timer=null;activeJob=null;cancelPendingJobId=null;
 const state=sessionState(project);
 const selection=state.initialized?(state.id||'none'):'latest';
 const result=project?await api(base+'/view/'+encodeURIComponent(project)+'/'+encodeURIComponent(selection)):{sessions:[],jobs:[],messages:[],running:false,selected_id:''};
 if(epoch!==chatRender||hooks!==entryHooks)return '';
 const listing=result,sessions=result.sessions||[];
 state.sessions=sessions;state.deleted=result.deleted_sessions||[];
 state.id=result.selected_id||'';state.initialized=true;
 const selected=sessions.find(s=>s.id===state.id);
 const jobs=listing.jobs.filter(j=>j.project_id===project&&Boolean(state.id)&&j.session_id===state.id);
 const job=jobs.at(-1);
 state.running=Boolean(result.running);
 const detail=result;
 if(epoch!==chatRender||hooks!==entryHooks)return '';
 activeJob=jobs.findLast(j=>j.status==='running')||null;if(!activeJob&&cancelPendingJobId&&!jobs.some(j=>j.id===cancelPendingJobId))cancelPendingJobId=null;
 const messages=(detail?.messages||[]).filter(m=>m.session_id===state.id).slice(-160);
 const sessionControls=project?`<div class="chat-session-controls"><label for="chat-session-select">本书聊天会话</label><select id="chat-session-select"><option value="" ${!selected?'selected':''}>${state.id?'所选会话不可用，请明确选择':'请选择会话或新建聊天会话'}</option>${sessions.map(s=>`<option value="${h(s.id)}" ${s.id===state.id?'selected':''}>${h(s.title)}${s.archived?'（已归档）':''}</option>`).join('')}</select><button type="button" data-chat-session="new">新建聊天会话（不新建小说）</button><button type="button" data-chat-session="rename" ${selected?'':'disabled'}>重命名聊天会话</button><button type="button" data-chat-session="delete" ${selected?'':'disabled'}>删除会话</button><button type="button" data-chat-session="archive" ${selected?'':'disabled'}>${selected?.archived?'恢复聊天会话':'归档聊天会话'}</button><p role="status">${state.running&&!activeJob?'本书其他会话正在执行任务；可切换查看，发送前请等待任务完成。':selected?.archived?'已归档：可阅读历史；恢复后才能发送。':state.id&&!selected?'所选会话不存在，禁止发送；请选择有效会话。':!sessions.length?'首次发送前会先保存一个新的聊天会话。':''}</p></div>`:'';
 const thread=messages.length?'<div class="agent-thread">'+messages.map(m=>`<article class="agent-message" data-role="${h(m.role)}"><strong>${m.role==='author'?'你':'创作助手'}</strong><div>${h(m.text)}</div></article>`).join('')+'</div>':`<div class="chat-home"><div class="chat-home-inner"><div class="chat-wordmark" role="img" aria-label="DualQuill"><svg viewBox="0 0 620 90" aria-hidden="true" focusable="false"><g fill="currentColor" transform="scale(1.2156862745 1)"><path fill-rule="evenodd" d="M0 18H42V0H60V72H0ZM18 36V54H42V36Z"/><path d="M74 18H92V54H116V18H134V72H74Z"/><path fill-rule="evenodd" d="M166 18H208V72H148V36H166ZM166 36H190V54H166Z"/><path d="M222 0H240V54H250V72H222Z"/><path fill-rule="evenodd" d="M264 18H324V90H306V72H264ZM282 36V54H306V36Z"/><path d="M338 18H356V54H380V18H398V72H338Z"/><path d="M412 18H426V32H412ZM412 42H426V72H412Z"/><path d="M440 0H458V54H468V72H440Z"/><path d="M482 0H500V54H510V72H482Z"/></g></svg></div><h2>${project?'继续这本书。':'从一句话开始写书。'}</h2><p>告诉我想写什么、改哪里或继续哪一章。<br>人物、设定、大纲和章节会自动保存。</p></div></div>`;
 const status=job?`<section class="agent-status" role="status"><strong>${h(labels[job.status]||job.status)}</strong><p id="agent-error" ${job.error?'':'hidden'}>${h(job.error||'')}</p><details><summary>创作进度与审核详情</summary><p role="status">完成项为完整工具；审核/修订可能仍在运行</p><p id="agent-progress">${h(job.progress)}</p><small id="agent-counts" title="本地请求统计，不代表站点计费">${h(requestCountsText(job))}</small><div id="agent-live-receipts">${reviewStatus(job)}${contextReceipt(job)}</div></details>${job.status==='awaiting_confirmation'?`<p>将整本书移入回收站，正文和历史保留。</p><button type="button" data-agent-confirm="${h(job.id)}" data-accepted="true">确认删除整本书</button><button type="button" data-agent-confirm="${h(job.id)}" data-accepted="false">取消</button>`:''}</section>`:'';
 const receipt=job?.reply&&messages.at(-1)?.text!==job.reply&&job.status!=='running'?`<p class="agent-receipt">${h(job.reply)}</p>`:'';
  return `<section id="agent-chat" class="panel agent-chat" data-chat-render="${epoch}">${activityHTML(result.activity||[])}${sessionControls}${sessionTrash(state)}${thread}${status}${receipt}</section>`;
}

export async function renderAgentSettings(existing){
 const settings=existing||await api(base);
 const selectedSkills=new Set(settings.skill_ids||[]);
 const skillsForm=`<section class="panel"><h2>Skills</h2><form id="agent-skills-form"><label>选择方式<select name="skill_mode"><option value="all-imported" ${settings.skill_mode==='all-imported'?'selected':''}>自动使用全部导入（包括未来导入）</option><option value="selected" ${settings.skill_mode!=='all-imported'?'selected':''}>手动选择（空选禁用）</option></select></label>${(settings.available_skills||[]).map(s=>`<label><input type="checkbox" name="skill_ids" value="${h(s.id)}" ${selectedSkills.has(s.id)?'checked':''}>${h(s.name)}</label>`).join('')}<button type="submit">保存 Skills</button><button type="button" data-skills-reset>恢复自动使用全部导入</button><p role="status" id="agent-skills-status"></p></form><p>每条作者消息开始时冻结已导入内容；保存不发送模型请求，不改变写作或审核连接。</p></section>`;
 const selected=settings.connections.find(c=>c.id===settings.connection_id);
 const options=settings.connections.map(c=>`<option value="${h(c.id)}" ${c.id===settings.connection_id?'selected':''}>${h(c.name)} · ${h(c.model_id)}</option>`).join('');
 const reviewerOptions=settings.connections.filter(c=>c.id!==settings.connection_id).map(c=>`<option value="${h(c.id)}" ${c.id===settings.reviewer_connection_id?'selected':''}>${h(c.name)} · ${h(c.model_id)}</option>`).join('');
 const reviewerForm=`<section class="panel"><h2>独立审核</h2><form id="agent-reviewer-form"><label>审核连接<select name="reviewer_connection_id" required><option value="">请选择独立连接</option>${reviewerOptions}</select></label><button type="submit">保存审核连接</button><p id="agent-reviewer-status" role="status"></p></form><p class="hint">只保存审核选择，不切换写作 API，也不发送请求。生成或审核章节前必须有不同于写作连接的有效审核连接。审核重点：遵循大纲、剧情逻辑与连续性、去AI化文风。至少4000汉字，不因超过旧字数上限退稿。每章最多自动修订五次，达到五次后按作者规则自动放行并继续后续章节，审核意见保留。传输与 Schema 重试独立于每章五次自动修订上限。作者可随时停止；超时、断线和临时服务错误会自动重连当前步骤；鉴权、配置或无效响应等实际错误会停止并保留草稿和审核历史。可在聊天中请求“审核已保存的第1至10章，通过的章节不要重写”。</p></section>`;
 return `<section class="panel"><h2>写作 API</h2><p>保存一个连接后，回到聊天即可创作。资料和正文自动保存，每次修改保留历史。</p>${settings.offline?'<p>当前为手动模式。<button type="button" id="agent-enable-models">开启模型创作</button></p>':''}<form id="agent-api-form" autocomplete="off"><label>已保存连接<select name="connection_id" id="agent-connection"><option value="">添加新连接</option>${options}</select></label><label>API 地址<input name="base_url" type="url" value="${h(selected?.base_url||'')}" placeholder="https://example.com/v1" required></label><label>API 密钥<input name="api_key" type="password" autocomplete="new-password" placeholder="${selected?'已保存，留空保留原密钥':'输入 API 密钥'}"></label><label>模型编号<input name="model_id" value="${h(selected?.model_id||'')}" placeholder="例如 gemini-4-argon 或 gpt-6.1-sol" required></label><details><summary>连接兼容选项（通常不用改）</summary><label>连接名称<input name="name" value="${h(selected?.name||'写作 API')}"></label><label>接口类型<select name="protocol"><option value="openai-chat">OpenAI 兼容 / 中转站</option><option value="gemini-content" ${selected?.protocol==='gemini-content'?'selected':''}>Gemini 原生</option><option value="anthropic-messages" ${selected?.protocol==='anthropic-messages'?'selected':''}>Anthropic 原生</option></select></label><label>OpenAI 请求方式<select name="wire_mode">${[['auto','自动选择'],['responses','Responses'],['chat','Chat Completions']].map(([id,label])=>`<option value="${id}" ${settings.wire_mode===id?'selected':''}>${label}</option>`).join('')}</select></label></details><button class="primary" type="submit">保存并使用这个 API</button><p id="agent-api-status" role="status"></p></form><p class="hint">密钥由本机 Windows 账户加密保存。保存不会发出模型请求；发送聊天后按所选站点规则消耗额度。</p><p class="hint">大段创作会逐章执行；可随时点输入框旁的停止按钮。删除内容可以恢复。</p></section>${reviewerForm}${skillsForm}`;
}

const localPathOperations=new Map();
export async function importLocalPath(path,project){
 const state=attachmentState(project),key=JSON.stringify([scopeKey(project),path]);
 if(sendingAttachments||state.uploads)throw new Error('请等待附件处理完成');
 if(!localPathOperations.has(key))localPathOperations.set(key,crypto.randomUUID());
 state.uploads++;state.error='';paintAttachments();
 try{
  const result=await post(base+'/attachment/local-path',{path,project_id:project||null,operation_id:localPathOperations.get(key)});
  for(const file of result.attachments||[]){
   if(file.status==='parsed'&&!file.archived)state.selected.set(file.id,file);
   else state.error+=(state.error?'；':'')+(file.filename||file.title)+'：'+(file.error||'未解析');
  }
  await loadAttachments(project);
  if(state.error)throw new Error(state.error);
  if(!(result.attachments||[]).length)throw new Error('没有读取到附件');
  return result;
 }finally{state.uploads--;paintAttachments();}
}
function composerState(running){
 activeJob=displayedJob();running=Boolean(activeJob);
 const send=document.querySelector('#chat-send'),stop=document.querySelector('#chat-stop'),newSession=document.querySelector('#chat-new-session'),project=hooks?.project(),state=project?sessionState(project):null;
 const selected=state?.sessions.find(s=>s.id===state.id);
 const invalid=Boolean(state&&(state.id?(!selected||selected.archived):state.sessions.length));
 const sessionGuard=!project||running||Boolean(state?.running)||sessionBusy||sendingAttachments||attachmentsUploading(project);
 if(send){send.disabled=running||sessionBusy||attachmentsUploading(project)||invalid||Boolean(state?.running);send.title=running||state?.running?'任务正在执行':sessionBusy?'正在更新会话':attachmentsUploading(project)?'附件正在处理':invalid?'请选择有效且未归档的聊天会话':'发送并自动更新小说';}
 if(newSession){newSession.disabled=sessionGuard;newSession.title=sessionGuard?'请先停止当前任务或完成当前操作；当前会话历史会保留':'新建会话；当前会话历史会保留';}
 if(stop){stop.disabled=!running||!activeJob||Boolean(activeJob&&cancelPendingJobId===activeJob.id);stop.textContent=Boolean(activeJob&&cancelPendingJobId===activeJob.id)?'正在停止…':'停止';stop.title=activeJob&&cancelPendingJobId===activeJob.id?'正在请求停止；已保存内容保留':'停止当前创作；已保存内容保留';}
}
export function syncAgentControls(){composerState(Boolean(activeJob));}

export async function sendAgentMessage(text,projectId,revision){
  const state=attachmentState(projectId),entryHooks=hooks,conversation=projectId?sessionState(projectId):null;
  if(entryHooks&&scopeKey(entryHooks.project())!==scopeKey(projectId))throw new Error('当前小说已切换，请确认后重新发送。');
  if(state.uploads||sendingAttachments||sessionBusy)throw new Error('请等待文件上传或会话操作完成');
  if(displayedJob()||conversation?.running)throw new Error('请先停止或等待本书任务完成');
  const selected=[...state.selected.values()];
  if(selected.some(file=>file.status!=='parsed'))throw new Error('请重试或移除上传失败的文件后再发送');
  const attachment_ids=selected.map(file=>file.id).sort();
  let request={text:text||(attachment_ids.length?'请自动分类整理这些附件，并将完整章节原文按来源导入；遇到现有设定冲突请先询问。':''),project_id:projectId||null,expected_revision:revision??null,attachment_ids};
  const originalId=conversation?.id;
  const ensureCurrent=()=>{if(hooks!==entryHooks||(entryHooks&&scopeKey(entryHooks.project())!==scopeKey(projectId)))throw new Error('当前小说已切换，请回到原小说重试发送。');};
  sendingAttachments=true;paintAttachments();
  try{
   if(conversation){
    const listing=await api(consoleBase(projectId));ensureCurrent();
    if(conversation.id!==originalId)throw new Error('会话已切换，请确认后重新发送。');
    conversation.sessions=listing.sessions||[];conversation.initialized=true;
    let session=conversation.sessions.find(s=>s.id===conversation.id);
    if(conversation.id?(!session||session.archived):conversation.sessions.length)throw new Error('请选择有效且未归档的聊天会话后再发送。');
    if(!session){
     conversation.createOperationId=conversation.createOperationId||crypto.randomUUID();
     session=await post(consoleBase(projectId)+'/sessions',{operation_id:conversation.createOperationId,title:'新聊天会话'});
     conversation.sessions=[...conversation.sessions.filter(s=>s.id!==session.id),session];conversation.id=session.id;
     delete conversation.createOperationId;ensureCurrent();
    }
    if(!session.id||session.archived)throw new Error('请选择有效且未归档的聊天会话后再发送。');
    request.session_id=session.id;
    const latest=conversation.id!==originalId?await api('/api/projects/'+encodeURIComponent(projectId)):{revision:request.expected_revision};ensureCurrent();
    if(conversation.id!==session.id)throw new Error('会话已切换，请确认后重新发送。');
    if(conversation.id!==originalId)request.expected_revision=latest.revision??latest.document?.revision??latest.project?.revision??listing.revision??revision??null;
   }
   ensureCurrent();
   const key=JSON.stringify({...request,expected_revision:null});
   if(!pending||pending.key!==key)pending={key,id:crypto.randomUUID(),request:{...request,attachment_ids:[...request.attachment_ids]}};
   request={...pending.request,attachment_ids:[...pending.request.attachment_ids]};
   try{
    const result=await post(base+'/start',{...request,operation_id:pending.id});
    for(const id of request.attachment_ids)state.selected.delete(id);
    if(conversation)conversation.running=result.status==='running';if(result.status==='running')cancelPendingJobId=null;
    pending=null;
    return result;
   }catch(error){
    if(error.status===400||error.status===409||error.status===422)pending=null;
    throw error;
   }
  }finally{sendingAttachments=false;paintAttachments();}
 }

function updateLiveReceipts(job){const root=document.querySelector('#agent-live-receipts');if(!root)return;const html=reviewStatus(job)+contextReceipt(job);if(root.dataset.receiptsHtml===html)return;const scrollTop=root.scrollTop,scrollLeft=root.scrollLeft,openPaths=new Set();const pathFor=detail=>{const parts=[];let node=detail;while(node&&node!==root){const key=node.dataset.receiptKey||`${node.tagName}:${node.querySelector(':scope > summary')?.textContent||''}`;const siblings=[...node.parentElement.children].filter(child=>child.tagName===node.tagName&&(child.dataset.receiptKey||`${child.tagName}:${child.querySelector(':scope > summary')?.textContent||''}`)===key);parts.unshift(key+'#'+siblings.indexOf(node));node=node.parentElement;}return parts.join('/');};root.querySelectorAll('details[open]').forEach(detail=>openPaths.add(pathFor(detail)));root.innerHTML=html;root.dataset.receiptsHtml=html;root.querySelectorAll('details').forEach(detail=>{if(openPaths.has(pathFor(detail)))detail.open=true;});root.scrollTop=scrollTop;root.scrollLeft=scrollLeft;}function poll(job){
 if(timer)clearTimeout(timer);
 const currentHooks=hooks,root=document.querySelector('#agent-chat'),epoch=chatRender,project=job.project_id,session=job.session_id||'';
 const current=()=>hooks===currentHooks&&chatRender===epoch&&root?.isConnected&&document.querySelector('#agent-chat')===root&&currentHooks?.project()===project&&sessionState(project).id===session;
 const pollTimer=setTimeout(async()=>{
  const isCurrent=()=>timer===pollTimer&&current();
  if(!isCurrent())return;
  try{
   const result=await api(base+'/jobs/'+encodeURIComponent(job.id));
   if(!isCurrent())return;
   if(result.project_id!==project||(result.session_id||'')!==session){
    const notice=currentHooks.notice;
    sessionState(project).running=false;
    resetAgentView();hooks=currentHooks;pollActivity(currentHooks);composerState(false);
    notice('任务已转入新建小说或其他会话；请通过当前小说选择器选择新建小说查看，当前页面不会自动切换。');
    await currentHooks.refresh(project);
    if(!isCurrent())return;
    return;
   }
   sessionState(project).running=result.status==='running';
   activeJob=result.status==='running'?result:null;if(result.status!=='running'&&cancelPendingJobId===result.id)cancelPendingJobId=null;updateLiveReceipts(result);
   composerState(Boolean(activeJob));
   const progress=document.querySelector('#agent-progress');
   if(progress)progress.textContent=result.error||result.progress;
   const counts=document.querySelector('#agent-counts');
   if(counts)counts.textContent=requestCountsText(result);
   const label=document.querySelector('#agent-chat .agent-status > strong');
   if(label)label.textContent=labels[result.status]||result.status;
   if(activeJob){poll(result);return;}
   if(!isCurrent())return;
   currentHooks.notice(result.error||result.reply||'操作已保存',result.status==='failed');
   await currentHooks.refresh(project);
   if(!isCurrent())return;
   if(timer===pollTimer)timer=null;
  }catch(error){
   if(!isCurrent())return;
   composerState(Boolean(activeJob));
   const progress=document.querySelector('#agent-progress');
   if(progress)progress.textContent='暂时无法读取进度：'+error.message+'。正在自动重试状态读取，请勿重复发送。';
   poll(job);
  }
 },1200);
 timer=pollTimer;
}

function pollActivity(currentHooks){
 if(activityTimer)clearTimeout(activityTimer);
 const epoch=++activityEpoch,render=chatRender,root=document.querySelector('#agent-chat'),project=currentHooks.project(),session=sessionState(project).id;
 if(!root)return;
 const current=()=>activityEpoch===epoch&&chatRender===render&&hooks===currentHooks&&currentHooks.project()===project&&sessionState(project).id===session&&root.isConnected&&document.querySelector('#agent-chat')===root;
 const tick=async()=>{
  if(!current())return;
  if(activityInFlight){activityTimer=setTimeout(tick,3000);return;}
  activityInFlight=true;
  try{
   const rows=await api(base+'/activity');
   if(!current())return;
   if(!Array.isArray(rows))throw new Error('后台状态响应无效');
   sessionState(project).running=rows.some(row=>row.project_id===project);
   const overview=root.querySelector('#chat-running-books');
   if(overview){
    const expanded=Boolean(overview.querySelector('details[open]'));
    overview.outerHTML=activityHTML(rows);
    if(expanded)root.querySelector('#chat-running-books details')?.setAttribute('open','');
   }
   composerState(Boolean(displayedJob()));
  }catch(error){
   if(!current())return;
   const heading=root.querySelector('#chat-running-books > strong');
   if(heading)heading.textContent='后台状态暂不可用，正在重试';
  }finally{
   activityInFlight=false;
   if(current())activityTimer=setTimeout(tick,3000);
  }
 };
 activityTimer=setTimeout(tick,0);
}

export function bindAgentPage(currentHooks){
 hooks=currentHooks;
 pollActivity(currentHooks);
 bindAttachments();
 if(timer){clearTimeout(timer);timer=null;}
 composerState(Boolean(activeJob));
 const currentJob=displayedJob();
 if(currentJob)poll(currentJob);
 const root=document.querySelector('#agent-chat');
 const project=currentHooks.project(),state=sessionState(project),select=document.querySelector('#chat-session-select');
 const isCurrent=()=>hooks===currentHooks&&currentHooks.project()===project&&document.querySelector('#agent-chat')===root;
 const changeSession=async(action,id)=>{
  if(!project||!isCurrent())return;
  const blocked=sessionChangeBlocked(project,action);
  if(blocked){if(select)select.value=state.id;currentHooks.notice(blocked,true);return;}
  const previous=state.id,selected=state.sessions.find(s=>s.id===previous);
  let title;
  if(action==='new'){
   title=state.newOperation?.title||'新聊天会话 '+new Date().toLocaleString();
  }else if(action==='rename'){
   title=await sessionTitle(selected?.title||'');
   if(title===null||!isCurrent())return;
  }
  if(action==='delete'&&!confirm('将此会话移入回收站？聊天历史可恢复，小说正文、设定和附件保留。'))return;
  sessionBusy=true;composerState(Boolean(activeJob));
  let selectedId=state.id;
  try{
   if(action!=='select'){
    const listing=await api(consoleBase(project));
    if(!isCurrent())return;
    state.sessions=listing.sessions||[];
   }
   if(action==='select'){
    if(id&&!state.sessions.some(s=>s.id===id))throw new Error('所选会话不存在，请刷新后重新选择。');
    state.id=id;
   }else if(action==='new'){
    state.newOperation=state.newOperation||{title,id:crypto.randomUUID()};
    const created=await post(consoleBase(project)+'/sessions',{operation_id:state.newOperation.id,title:state.newOperation.title});
    if(typeof created?.id!=='string'||!created.id.trim())throw new Error('新会话创建失败：未返回有效会话编号，请重试。');
    if(!isCurrent())return;
    state.sessions=[...state.sessions.filter(s=>s.id!==created.id),created];
    state.id=created.id;
    pending=null;
    delete state.newOperation;
   }else if(action==='delete'||action==='restore'){
    await post(base+'/session-lifecycle',{project_id:project,session_id:action==='restore'?id:previous,action,confirmed:true});
    if(!isCurrent())return;
    if(action==='delete')state.id='';
    if(action==='restore')state.id=id;
    state.initialized=action==='restore';
   }else{
    const session=state.sessions.find(s=>s.id===previous);
    if(!session)throw new Error('所选会话不存在，请重新选择。');
    const updated=await post(consoleBase(project)+'/sessions/'+encodeURIComponent(previous)+'/'+action,action==='rename'?{title}:{archived:!session.archived});
    if(!isCurrent())return;
    state.sessions=state.sessions.map(s=>s.id===previous?{...s,...updated,...(action==='rename'?{title}:{archived:!session.archived})}:s);
   }
   state.initialized=action!=='delete';++chatRender;
   selectedId=state.id;
   await currentHooks.refresh(project,{sessionOnly:action==='select'});
   if(action==='new'){
    const stillSelected=()=>hooks?.project()===project&&sessionState(project).id===selectedId&&Boolean(document.querySelector('#agent-chat'));
    if(stillSelected())document.querySelector('#chat-input')?.focus();
    requestAnimationFrame(()=>requestAnimationFrame(()=>{
     if(stillSelected()){const content=document.querySelector('#content');if(content)content.scrollTop=0;}
    }));
   }
  }catch(error){
   if(hooks?.project()===project&&document.querySelector('#agent-chat')&&(isCurrent()||sessionState(project).id===selectedId)){
    const currentSelect=document.querySelector('#chat-session-select');
    if(currentSelect)currentSelect.value=state.id;
    hooks.notice(error.message,true);
   }
  }
  finally{sessionBusy=false;composerState(Boolean(activeJob));}
 };
 if(select)select.onchange=()=>void changeSession('select',select.value);
 const newSession=document.querySelector('#chat-new-session');
 if(newSession)newSession.onclick=()=>void changeSession('new');
 root?.addEventListener('click',event=>{
  const button=event.target.closest('[data-chat-session]');
  if(button&&root.contains(button))void changeSession(button.dataset.chatSession,button.dataset.sessionId);
 });
 root?.addEventListener('click',async event=>{
  const button=event.target.closest('[data-agent-confirm]');if(!button)return;
  button.disabled=true;
  try{await post(base+'/jobs/'+button.dataset.agentConfirm+'/confirm',{accepted:button.dataset.accepted==='true'});await hooks.refresh(hooks.project());}catch(error){hooks.notice(error.message,true);button.disabled=false;}
 });
 const stop=document.querySelector('#chat-stop');
 if(stop)stop.onclick=async()=>{const currentHooks=hooks,currentJob=displayedJob();if(!currentJob||cancelPendingJobId===currentJob.id)return;const jobId=currentJob.id;cancelPendingJobId=jobId;composerState(true);try{await post(base+'/jobs/'+jobId+'/cancel',{});if(currentHooks&&hooks===currentHooks&&activeJob?.id===jobId){composerState(true);currentHooks.notice('已请求停止，已保存内容保留。');}}catch(error){if(cancelPendingJobId===jobId)cancelPendingJobId=null;composerState(Boolean(activeJob));if(currentHooks&&hooks===currentHooks&&activeJob?.id===jobId)currentHooks.notice(error.message,true);}};
  const skillsForm=document.querySelector('#agent-skills-form');
   if(skillsForm){
    let savingSkills=false;
    const saveSkills=async(reset=false)=>{
     if(savingSkills)return;
     const currentHooks=hooks,buttons=[...skillsForm.querySelectorAll('button')],status=skillsForm.querySelector('#agent-skills-status');
     const payload=reset?{skill_mode:'all-imported'}:{skill_ids:[...skillsForm.querySelectorAll('input[name="skill_ids"]:checked')].map(input=>input.value)};
     savingSkills=true;buttons.forEach(button=>button.disabled=true);status.textContent='正在保存 Skills 设置…';
     try{
      await post(base+'/config',payload);
      const message=reset?'已恢复自动使用全部导入的 Skills，包括未来导入。':'Skills 选择已保存；空选表示禁用。';
      status.textContent=message;
      await currentHooks.refresh(currentHooks.project());currentHooks.notice(message);
     }catch(error){status.textContent=error.message;currentHooks.notice(error.message,true);}
     finally{savingSkills=false;buttons.forEach(button=>button.disabled=false);}
    };
    skillsForm.addEventListener('submit',event=>{event.preventDefault();event.stopPropagation();void saveSkills(skillsForm.elements.skill_mode.value==='all-imported');});
    skillsForm.querySelector('[data-skills-reset]')?.addEventListener('click',()=>void saveSkills(true));
    skillsForm.querySelectorAll('input[name="skill_ids"]').forEach(input=>input.addEventListener('change',()=>{skillsForm.elements.skill_mode.value='selected';}));
   }
   const reviewerForm=document.querySelector('#agent-reviewer-form');
  reviewerForm?.addEventListener('submit',async event=>{
   event.preventDefault();event.stopPropagation();
   const button=reviewerForm.querySelector('[type=submit]');button.disabled=true;
   try{const reviewer_connection_id=reviewerForm.elements.reviewer_connection_id.value;await post(base+'/config',{reviewer_connection_id});await hooks.refresh(hooks.project());hooks.notice('独立审核连接已保存。');}
   catch(error){reviewerForm.querySelector('#agent-reviewer-status').textContent=error.message;hooks.notice(error.message,true);}
   finally{button.disabled=false;}
  });
  const form=document.querySelector('#agent-api-form');
  if(!form)return;
 form.addEventListener('submit',async event=>{
  event.preventDefault();event.stopPropagation();
  const values=Object.fromEntries(new FormData(form));
  const button=form.querySelector('[type=submit]');button.disabled=true;
  try{
   const current=(await api(base)).connections.find(c=>c.id===values.connection_id);
   const id=current?.custom?current.id:crypto.randomUUID();
   const url=new URL(values.base_url.trim());
   url.pathname=url.pathname.replace(/\/(responses|chat\/completions)\/?$/,'').replace(/\/$/,'');
   if(!url.pathname&&values.protocol==='openai-chat')url.pathname='/v1';
   await post('/api/providers/custom',{id,name:values.name||'写作 API',base_url:url.href.replace(/\/$/,''),protocol:values.protocol,model_id:values.model_id.trim(),api_key:values.api_key,allow_local:false});
   await post(base+'/config',{connection_id:id,wire_mode:values.wire_mode});
   values.api_key='';form.elements.api_key.value='';
   await hooks.refresh(hooks.project());hooks.notice('API 已保存，回到聊天即可创作。');
  }catch(error){form.querySelector('#agent-api-status').textContent=error.message;hooks.notice(error.message,true);}finally{button.disabled=false;}
 });
 form.querySelector('#agent-connection').addEventListener('change',async event=>{
  const settings=await api(base),selected=settings.connections.find(c=>c.id===event.target.value);
  for(const name of ['base_url','model_id','name'])form.elements[name].value=selected?.[name]||'';
  form.elements.protocol.value=selected?.protocol==='gemini-content'?'gemini-content':selected?.protocol==='anthropic-messages'?'anthropic-messages':'openai-chat';
  form.elements.api_key.value='';
  if(selected){await post(base+'/config',{connection_id:selected.id,wire_mode:settings.wire_mode});hooks.notice('聊天已切换到 '+selected.name);}
 });
 document.querySelector('#agent-enable-models')?.addEventListener('click',async()=>{try{await post('/api/desktop/mode',{mode:'models',confirmed:true});await hooks.refresh(hooks.project());}catch(error){hooks.notice(error.message,true);}});
}

export async function changeEntity(project,revision,kind,id,restore=false){
 return post(base+'/entity',{project_id:project,expected_revision:revision,tool:restore?'restore_entity':'delete_entity',arguments:{kind,id},confirmed:true});
}
