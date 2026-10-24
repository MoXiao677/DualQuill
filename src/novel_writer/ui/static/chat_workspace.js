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
let timer=null,activeJob=null,pending=null,hooks=null;
const post=(url,value)=>api(url,{method:'POST',body:JSON.stringify(value)});
const labels={running:'创作中',completed:'已完成',failed:'未完成',cancelled:'已停止',interrupted:'上次任务已中断',awaiting_confirmation:'等待删除确认'};

export async function renderAgentChat(workspace){
 const project=workspace?.document.project.id;
 const listing=await api(base+'/jobs');
 const jobs=listing.jobs.filter(j=>j.project_id===project);
 const job=jobs.at(-1);
 activeJob=job?.status==='running'?job:null;
 const sessions=workspace?.console_sessions?.filter(s=>s.title==='自动创作对话')||[];
 const messages=(workspace?.console_messages||[]).filter(m=>sessions.some(s=>s.id===m.session_id)).slice(-160);
 const thread=messages.length?'<div class="agent-thread">'+messages.map(m=>`<article class="agent-message" data-role="${h(m.role)}"><strong>${m.role==='author'?'你':'创作助手'}</strong><div>${h(m.text)}</div></article>`).join('')+'</div>':`<div class="chat-home"><div class="chat-home-inner"><div class="chat-wordmark">D<span>DUALQUILL</span></div><h2>${project?'继续这本书。':'从一句话开始写书。'}</h2><p>告诉我想写什么、改哪里或继续哪一章。<br>人物、设定、大纲和章节会自动保存。</p></div></div>`;
 const status=job?`<section class="agent-status" role="status"><strong>${h(labels[job.status]||job.status)}</strong><p id="agent-progress">${h(job.error||job.progress)}</p><small id="agent-counts">模型调用 ${job.calls} 次 · 完成 ${job.actions} 项操作</small>${job.status==='awaiting_confirmation'?`<p>将整本书移入回收站，正文和历史保留。</p><button type="button" data-agent-confirm="${h(job.id)}" data-accepted="true">确认删除整本书</button><button type="button" data-agent-confirm="${h(job.id)}" data-accepted="false">取消</button>`:''}</section>`:'';
 const receipt=job?.reply&&messages.at(-1)?.text!==job.reply&&job.status!=='running'?`<p class="agent-receipt">${h(job.reply)}</p>`:'';
 return `<section id="agent-chat" class="panel agent-chat">${thread}${status}${receipt}</section>`;
}

export async function renderAgentSettings(existing){
 const settings=existing||await api(base);
 const selected=settings.connections.find(c=>c.id===settings.connection_id);
 const options=settings.connections.map(c=>`<option value="${h(c.id)}" ${c.id===settings.connection_id?'selected':''}>${h(c.name)} · ${h(c.model_id)}</option>`).join('');
 return `<section class="panel"><h2>写作 API</h2><p>保存一个连接后，回到聊天即可创作。资料和正文自动保存，每次修改保留历史。</p>${settings.offline?'<p>当前为手动模式。<button type="button" id="agent-enable-models">开启模型创作</button></p>':''}<form id="agent-api-form" autocomplete="off"><label>已保存连接<select name="connection_id" id="agent-connection"><option value="">添加新连接</option>${options}</select></label><label>API 地址<input name="base_url" type="url" value="${h(selected?.base_url||'')}" placeholder="https://example.com/v1" required></label><label>API 密钥<input name="api_key" type="password" autocomplete="new-password" placeholder="${selected?'已保存，留空保留原密钥':'输入 API 密钥'}"></label><label>模型编号<input name="model_id" value="${h(selected?.model_id||'')}" placeholder="例如 gemini-4-argon 或 gpt-6.1-sol" required></label><details><summary>连接兼容选项（通常不用改）</summary><label>连接名称<input name="name" value="${h(selected?.name||'写作 API')}"></label><label>接口类型<select name="protocol"><option value="openai-chat">OpenAI 兼容 / 中转站</option><option value="gemini-content" ${selected?.protocol==='gemini-content'?'selected':''}>Gemini 原生</option><option value="anthropic-messages" ${selected?.protocol==='anthropic-messages'?'selected':''}>Anthropic 原生</option></select></label><label>OpenAI 请求方式<select name="wire_mode">${[['auto','自动选择'],['responses','Responses'],['chat','Chat Completions']].map(([id,label])=>`<option value="${id}" ${settings.wire_mode===id?'selected':''}>${label}</option>`).join('')}</select></label></details><button class="primary" type="submit">保存并使用这个 API</button><p id="agent-api-status" role="status"></p></form><p class="hint">密钥由本机 Windows 账户加密保存。保存不会发出模型请求；发送聊天后按所选站点规则消耗额度。</p><p class="hint">大段创作会逐章执行；可随时点输入框旁的停止按钮。删除内容可以恢复。</p></section>`;
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
 const send=document.querySelector('#chat-send'),stop=document.querySelector('#chat-stop');
 if(send){send.disabled=running||attachmentsUploading(hooks?.project());send.title=running?'任务正在执行':attachmentsUploading(hooks?.project())?'附件正在处理':'发送并自动更新小说';}
 if(stop){stop.disabled=!running;stop.title='停止当前创作；已保存内容保留';}
}
export function syncAgentControls(){composerState(Boolean(activeJob));}

export async function sendAgentMessage(text,projectId,revision){
 const state=attachmentState(projectId);
 if(state.uploads||sendingAttachments)throw new Error('请等待文件上传完成');
 const selected=[...state.selected.values()];
 if(selected.some(file=>file.status!=='parsed'))throw new Error('请重试或移除上传失败的文件后再发送');
 const attachment_ids=selected.map(file=>file.id).sort();
 const request={text:text||(attachment_ids.length?'请自动分类整理这些附件，并将完整章节原文按来源导入；遇到现有设定冲突请先询问。':''),project_id:projectId||null,expected_revision:revision??null,attachment_ids};
 const key=JSON.stringify(request);
 if(!pending||pending.key!==key)pending={key,id:crypto.randomUUID()};
 sendingAttachments=true;paintAttachments();
 try{
  const result=await post(base+'/start',{...request,operation_id:pending.id});
  for(const id of attachment_ids)state.selected.delete(id);
  pending=null;
  return result;
 }finally{sendingAttachments=false;paintAttachments();}
}

function poll(job){
 if(timer)clearTimeout(timer);
 timer=setTimeout(async()=>{
  try{
   const result=await api(base+'/jobs/'+encodeURIComponent(job.id));
   if(hooks?.project()!==job.project_id)return;
   if(result.project_id!==job.project_id){await hooks.refresh(result.project_id);return;}
   activeJob=result.status==='running'?result:null;
   composerState(Boolean(activeJob));
   const progress=document.querySelector('#agent-progress');
   if(progress)progress.textContent=result.error||result.progress;
   const counts=document.querySelector('#agent-counts');
   if(counts)counts.textContent=`模型调用 ${result.calls} 次 · 完成 ${result.actions} 项操作`;
   if(activeJob){poll(result);return;}
   await hooks.refresh(job.project_id);
   hooks.notice(result.error||result.reply||'操作已保存',result.status==='failed');
  }catch(error){
   composerState(false);
   const progress=document.querySelector('#agent-progress');
   if(progress)progress.textContent='暂时无法读取进度：'+error.message+'。请重新读取，不要重复发送。';
  }
 },1200);
}

export function bindAgentPage(currentHooks){
 hooks=currentHooks;
 bindAttachments();
 if(timer){clearTimeout(timer);timer=null;}
 composerState(Boolean(activeJob));
 if(activeJob&&activeJob.project_id===hooks.project())poll(activeJob);
 const root=document.querySelector('#agent-chat');
 root?.addEventListener('click',async event=>{
  const button=event.target.closest('[data-agent-confirm]');if(!button)return;
  button.disabled=true;
  try{await post(base+'/jobs/'+button.dataset.agentConfirm+'/confirm',{accepted:button.dataset.accepted==='true'});await hooks.refresh(hooks.project());}catch(error){hooks.notice(error.message,true);button.disabled=false;}
 });
 const stop=document.querySelector('#chat-stop');
 if(stop)stop.onclick=async()=>{if(!activeJob)return;try{await post(base+'/jobs/'+activeJob.id+'/cancel',{});stop.disabled=true;hooks.notice('已请求停止，已保存内容保留。');}catch(error){hooks.notice(error.message,true);}};
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
