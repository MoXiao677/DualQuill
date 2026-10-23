import {api} from './api.js';
import {renderCreativeDialogue,bindCreativeDialogue} from './creative_dialogue.js';
import {escapeHTML as h} from './views.js';
import {archivedChapterIds} from './views.js';
import {renderActualUsage} from './console_usage.js';
let selected=sessionStorage.getItem('novel-console-session')||'',selectedRun=sessionStorage.getItem('novel-console-run')||'',draftPlan=[],draftSession='',draftCandidate=null;
const types={'chapter.inspect':'只读：已保存章节','context.preview':'只读：上下文预览',idea:'IDEA 构思',outline:'章节细纲',draft:'正文初稿',continue:'正文续写',scene:'场景扩写',selection:'选区扩写'};
const readonlyTools=['chapter.inspect','context.preview'];
const statuses={planned:'待派发',prepared:'已准备（未执行）',failed:'派发失败'};
const taskStatuses={pending:'待确认',running:'执行中',succeeded:'完成',failed:'失败',cancelled:'已取消',interrupted:'已中断',candidate_ready:'候选完成',adopted:'已采纳'};
const runStatuses={running:'运行中',paused:'已暂停',cancelled:'已取消',completed:'已完成'};
const runStepStatuses={queued:'待推进',prepared:'已准备（未确认）',awaiting_confirmation:'等待任务确认/执行',awaiting_adoption:'等待采纳',completed:'已完成',blocked:'受阻（需明确跳过或取消）',skipped:'已明确跳过',cancelled:'已取消',failed:'失败'};
export function selectedConsoleSession(){return selected;}
export function selectConsoleSession(id){selected=id;try{sessionStorage.setItem('novel-console-session',id);}catch{}}
export function selectedConsoleRun(){return selectedRun;}
export function selectConsoleRun(id){selectedRun=id;try{sessionStorage.setItem('novel-console-run',id);}catch{}}
export function renderConsole(workspace,listing,detail,caps,runListing,runDetail){
 const sessions=listing.sessions||[];if(selected&&!sessions.some(v=>v.id===selected))selected='';
 const panel=(detail&&detail.session)?'':sessions.length?'<p class="hint">从左侧选择一个会话，或新建会话。</p>':'<p class="hint">还没有会话。新建一个，把需求和操作计划留在本书。</p>';
 const active=[...workspace.document.chapters].sort((a,b)=>a.number-b.number).filter(c=>!archivedChapterIds(workspace).has(c.id));
 let body=panel;
 if(detail&&detail.session){const s=detail.session;draftSession=s.id;draftCandidate=null;draftPlan=(detail.plan?.steps||[]).map(v=>({...v}));body='<div class="console-session-head"><div class="field"><label for="console-session-title">会话名称</label><input id="console-session-title" value="'+h(s.title)+'"></div><button id="console-session-rename" type="button">保存名称</button><button id="console-session-archive" type="button">'+(s.archived?'恢复会话':'归档会话')+'</button></div>'+
  renderCreativeDialogue(workspace,detail,caps)+'<details><summary>操作记录与手动编排</summary><div class="console-messages">'+detail.messages.map(m=>'<article class="console-message" data-role="'+h(m.role)+'"><strong>'+h({author:'作者',system:'系统',assistant:'助手文本',result:'结果'}[m.role]||m.role)+'</strong><p>'+h(m.text)+'</p>'+messageRefs(m)+'</article>').join('')+'</div>'+
  '<div class="field"><label for="console-message-text">记录一条需求或作者决定</label><textarea id="console-message-text" rows="3"></textarea></div><button id="console-message-add" type="button" '+(s.archived?'disabled':'')+'>加入会话</button>'+
  '<section id="console-linked-candidate" aria-live="polite"></section>'+renderActualUsage(detail.usage)+proposalPanel(detail,active)+'<h3>可编辑操作计划</h3><p class="hint">计划只是数据。只读工具通过运行执行；模型步骤仅准备待确认任务，付费发送和正式采纳各自确认。编辑已绑定计划会阻止旧运行；已有历史的步骤保留。</p><div id="console-plan-editor"></div><button id="console-plan-save" type="button" '+(s.archived?'disabled':'')+'>保存计划</button><button id="console-plan-add" type="button" '+(s.archived?'disabled':'')+'>＋ 添加步骤</button>'+
  runPanel(workspace,detail,runListing,runDetail)+
  '<div class="console-results"><h3>任务结果回链</h3>'+(detail.dispatches.length?detail.dispatches.map(d=>'<div class="console-result"><p>'+h(types[d.engine==='chapter_writing'?'draft':d.engine==='chapter_planning'?'idea':'scene']||d.engine)+' · 任务 '+h(d.task_id.slice(0,8))+' · '+h(taskStatuses[d.display_status]||d.display_status)+'</p><p class="hint">候选 '+h(d.candidate_id||'无')+' · 采纳收据 '+h(d.receipt_id||'无')+(d.late?' · 有迟到响应':'')+'</p><button type="button" data-console-task="'+h(d.engine)+'|'+h(d.task_id)+'">打开既有任务页</button></div>').join(''):'<p class="hint">尚无派发任务。</p>')+'</div></details>';
 }
 return '<section id="console-root" class="panel"><div class="console-layout"><aside class="console-sessions"><h2>持久会话</h2><div class="field"><label for="console-new-title">新会话名称</label><input id="console-new-title" value="新会话"></div><button id="console-create" type="button" '+(workspace.document.project.id?'':'disabled')+'>新建会话</button><div id="console-session-list">'+sessions.map(s=>'<button class="console-session-item '+(s.id===selected?'active':'')+'" type="button" data-console-session="'+h(s.id)+'"><span>'+h(s.title)+'</span><small>'+h(s.last_message||'空会话')+' · '+s.step_count+' 步'+(s.archived?' · 已归档':'')+'</small></button>').join('')+'</div></aside><main class="console-main"><h2>创作对话</h2><p class="hint">会话、消息和计划随本书保存；模型文本只显示，不会触发工具或写入。每个步骤派发后仍是待确认任务。</p>'+body+'</main></div></section>';
}
function proposalPanel(detail,active){
 const candidate=detail.dialogue?.turns.filter(v=>v.task?.latest_candidate).at(-1)?.task.latest_candidate;
 return '<details><summary>注册工具与不可信计划预览</summary><p class="hint">仅接受白名单工具及其参数。模型文本中的脚本、命令、URL和权限无效；预览不保存、不执行。候选建议只关联来源，不把全书候选自动写入章节或正式内容。</p><details><summary>工具参数与权限白名单</summary><pre class="context-text">'+h(JSON.stringify(detail.tools||[],null,2))+'</pre></details><label for="console-tool-proposal">粘贴工具计划JSON（steps / tool / arguments）</label><textarea id="console-tool-proposal" rows="5" placeholder="仅数据提案"></textarea><button id="console-proposal-preview" type="button" '+(detail.session.archived?'disabled':'')+'>校验并加入可编辑草案（未保存）</button><label for="console-proposal-chapter">候选建议的目标章节</label><select id="console-proposal-chapter">'+active.map(c=>'<option value="'+h(c.id)+'">第'+c.number+'章 · '+h(c.title)+'</option>').join('')+'</select><button id="console-candidate-plan" type="button" data-candidate-id="'+h(candidate?.id||'')+'" '+(candidate&&active.length&&!detail.session.archived?'':'disabled')+'>关联最新大纲候选，加入工具计划草案</button><p id="console-proposal-status" role="status"></p></details>';
}
function messageRefs(message){
 return (message.refs||[]).map(ref=>ref.kind==='candidate'?'<button type="button" data-console-candidate-ref="'+h(ref.id)+'">查看关联候选 '+h(ref.id)+'</button>':'<span class="hint">'+h(ref.kind)+' '+h(ref.id)+'</span>').join(' ');
}
function planRow(step,index,active){
 const optional=step.type==='scene'?'<div class="field"><label for="console-step-'+index+'-scene">场景序号</label><input id="console-step-'+index+'-scene" type="number" value="'+h(step.scene_order??1)+'"></div>':step.type==='selection'?'<div class="field-grid"><div class="field"><label for="console-step-'+index+'-start">选区起点</label><input id="console-step-'+index+'-start" type="number" value="'+h(step.selection_start??0)+'"></div><div class="field"><label for="console-step-'+index+'-end">选区终点</label><input id="console-step-'+index+'-end" type="number" value="'+h(step.selection_end??0)+'"></div></div>':'';
 return '<fieldset class="console-step" data-console-step="'+index+'"><legend>步骤 '+(index+1)+'</legend><div class="field"><label for="console-step-'+index+'-type">类型</label><select id="console-step-'+index+'-type">'+Object.entries(types).map(([id,label])=>'<option value="'+id+'" '+(step.type===id?'selected':'')+'>'+label+'</option>').join('')+'</select></div><div class="field"><label for="console-step-'+index+'-chapter">目标章节</label><select id="console-step-'+index+'-chapter">'+active.map(c=>'<option value="'+h(c.id)+'" '+(step.chapter_id===c.id?'selected':'')+'>第'+c.number+'章 · '+h(c.title)+'</option>').join('')+'</select></div><div class="field"><label for="console-step-'+index+'-instruction">指令</label><textarea id="console-step-'+index+'-instruction" rows="3">'+h(step.instruction)+'</textarea></div>'+optional+'<p class="hint">'+h(statuses[step.status]||step.status)+'</p><button type="button" data-console-up="'+index+'">上移</button><button type="button" data-console-down="'+index+'">下移</button><button type="button" data-console-remove="'+index+'">删除</button><button type="button" data-console-dispatch="'+index+'" '+(readonlyTools.includes(step.type)?'disabled':'')+'>派发准备（不外发）</button></fieldset>';
}
function readRows(root){const rows=[...root.querySelectorAll('[data-console-step]')].map((row,index)=>{const id=draftPlan[index]?.id||crypto.randomUUID(),type=row.querySelector('[id$="-type"]').value,chapter=row.querySelector('[id$="-chapter"]').value,instruction=row.querySelector('[id$="-instruction"]').value,scene=row.querySelector('[id$="-scene"]'),start=row.querySelector('[id$="-start"]'),end=row.querySelector('[id$="-end"]');return {id,type,chapter_id:chapter,instruction,status:draftPlan[index]?.status||'planned',scene_order:scene?Number(scene.value):null,selection_start:start?Number(start.value):null,selection_end:end?Number(end.value):null};});draftPlan=rows;return rows;}
function drawPlan(root,active){const editor=root.querySelector('#console-plan-editor');if(!editor)return;editor.innerHTML=draftPlan.length?draftPlan.map((v,i)=>planRow(v,i,active)).join(''):'<p class="hint">还没有步骤。添加 IDEA 构思、细纲、初稿、续写或场景/选区扩写。</p>';}
function runPanel(workspace,detail,listing,view){
 const session=detail?.session;if(!session)return '';
 const runs=(listing?.runs||[]).filter(v=>v.session_id===session.id);
 const plan=detail.plan||{revision:1,steps:[]};
 const active=runs.some(v=>v.status==='running'||v.status==='paused');
 const canStart=!session.archived&&plan.steps.length>0&&!active;
 const reasons=[];
 if(session.archived)reasons.push('会话已归档，不能开始运行。');
 else if(!plan.steps.length)reasons.push('计划没有可执行步骤。');
 else if(active)reasons.push('此会话已有进行中的运行；请先完成或取消。');
 return '<div id="console-runs" class="console-runs"><h3>显式运行编排</h3><p class="hint">开始运行会冻结当前计划；可逐步读取已保存资料或准备一个待确认任务；可预先允许本次确定性只读连续推进，遇到模型准备即停止。</p><button id="console-run-start" type="button" '+(canStart?'':'disabled')+'>开始运行（绑定计划第'+plan.revision+'版）</button>'+(reasons.length?'<p class="hint">'+h(reasons.join(' '))+'</p>':'')+'<div id="console-run-list">'+(runs.length?runs.slice().reverse().map(v=>'<button class="console-run-item '+(v.id===selectedRun?'active':'')+'" type="button" data-console-run="'+h(v.id)+'"><span>'+h(runStatuses[v.status]||v.status)+' · 运行 '+h(v.id.slice(0,8))+'</span><small>'+(v.completed_steps||0)+'/'+v.step_count+' 步 · 绑定计划第'+v.plan_revision+'版</small></button>').join(''):'<p class="hint">还没有运行记录。</p>')+'</div><div id="console-run-detail">'+(view?renderRunDetail(workspace,view):'<p class="hint">选择一条运行查看步骤状态与受控操作。</p>')+'</div></div>';
}
function renderRunDetail(workspace,view){
 const run=view.run,steps=run.steps||view.steps||[],chapters=new Map(workspace.document.chapters.map(c=>[c.id,c]));
 const reason=run.blocked_reason||'';
 const current=steps.find(v=>v.id===run.current_step_id),canRead=run.can_advance&&readonlyTools.includes(current?.type);
 return '<div class="console-run-head"><strong>运行 '+h(run.id.slice(0,8))+'</strong> · '+h(runStatuses[run.status]||run.status)+'</div><p class="hint">绑定计划第'+run.plan_revision+'版 · 当前第'+run.plan_revision_current+'版'+(run.plan_changed?' · 计划已修改，推进已阻止':'')+(view.session?.archived?' · 会话已归档':'')+'</p>'+renderBackground(view)+renderActualUsage(run.usage)+'<p id="console-run-blocked" class="console-blocked" role="status">'+h(reason)+'</p><fieldset><legend>仅本次请求的只读连续推进许可（重开不保留）</legend>'+readonlyTools.map(id=>'<label><input type="checkbox" data-console-readonly="'+id+'">允许 '+h(types[id])+'</label>').join('')+'<p class="hint">勾选后点击连续推进；遇到模型准备、失败或守卫立即停止。不会确认任何付费请求或正式采纳。</p><button id="console-run-readonly" type="button" '+(canRead?'':'disabled')+'>按本次许可连续推进只读步骤</button></fieldset><div class="console-run-controls"><button id="console-run-advance" type="button" '+(run.can_advance?'':'disabled')+'>推进一步（只读或准备任务）</button><button id="console-run-pause" type="button" '+(run.can_pause?'':'disabled')+'>暂停</button><button id="console-run-resume" type="button" '+(run.can_resume?'':'disabled')+'>恢复</button><button id="console-run-cancel" type="button" '+(run.can_cancel?'':'disabled')+'>取消运行</button><button id="console-run-skip" type="button" '+(run.can_skip?'':'disabled')+'>明确跳过当前步骤</button></div><div class="console-run-steps">'+steps.map((step,index)=>renderRunStep(step,index,run.current_step_id===step.id,chapters)).join('')+'</div>';
}
function renderBackground(view){
 const run=view.run,steps=run.steps||view.steps||[],batches=view.background?.batches||[];
 const running=batches.some(b=>b.status==='running'),canStart=run.can_advance&&!running;
 const statuses={running:'执行中',completed:'已完成',awaiting_human:'等待人工决定',step_limit:'达到步数上限',time_limit:'达到时间上限',paused:'已暂停',cancelled:'已取消',interrupted:'已中断',failed:'失败'};
 return '<fieldset><legend>后台批次</legend><p class="hint">从当前步骤连续选择，预览本批来源、确切请求和预算后单独确认。遇到正文生成或采纳即等待人工决定；重开不会继续旧批次。</p>'+steps.filter(s=>['queued','awaiting_confirmation'].includes(s.status)).map(s=>'<label><input type="checkbox" data-console-background-step="'+h(s.id)+'" '+(canStart?'':'disabled')+'>'+h(types[s.type]||s.type)+' · 步骤 '+(steps.indexOf(s)+1)+'</label>').join('')+'<label for="console-background-max-steps">最多执行步数</label><input id="console-background-max-steps" type="number" min="1" max="100" value="10"><label for="console-background-max-seconds">最长执行秒数</label><input id="console-background-max-seconds" type="number" min="0.01" max="3600" value="60" step="0.01"><button id="console-background-preview-request" type="button" '+(canStart?'':'disabled')+'>预览所选步骤与请求</button><section id="console-background-preview" aria-live="polite"></section><button id="console-background-pause" type="button" '+(running?'':'disabled')+'>暂停后台批次</button><button id="console-background-cancel" type="button" '+(running?'':'disabled')+'>取消后台批次</button><button id="console-background-refresh" type="button">刷新批次状态</button>'+batches.slice().reverse().map(b=>'<details><summary>'+h(statuses[b.status]||b.status)+' · 批次 '+h(b.id.slice(0,8))+'</summary><pre class="context-text">'+h(JSON.stringify(b.events,null,2))+'</pre></details>').join('')+'</fieldset>';
}
function renderRunStep(step,index,current,chapters){
 const chapter=chapters.get(step.chapter_id);
 const blocked=step.blocked_reason?'<p class="hint">'+h(step.blocked_reason)+'</p>':'';
 const link=step.engine&&step.task_id?'<button type="button" data-console-task="'+h(step.engine)+'|'+h(step.task_id)+'">打开既有任务页</button>':'';
 return '<article class="console-run-step" data-run-step="'+h(step.id)+'" data-run-step-status="'+h(step.status)+'"><p><strong>'+h(types[step.type]||step.type)+' · 步骤 '+(index+1)+(current?' · 当前':'')+' · '+h(runStepStatuses[step.status]||step.status)+'</strong></p><p>'+h(step.instruction||'（无指令）')+'</p><p class="hint">'+h(chapter?'第'+chapter.number+'章 · '+chapter.title:'章节 '+String(step.chapter_id).slice(0,8))+' · 保存状态 '+h(step.persisted_status||step.status)+(step.display_status?' · 任务状态 '+h(taskStatuses[step.display_status]||step.display_status):'')+'</p><p class="hint">任务 '+h(step.task_id||'无')+' · 候选 '+h(step.candidate_id||'无')+' · 采纳收据 '+h(step.receipt_id||'无')+(step.late?' · 有迟到响应':'')+'</p>'+(step.usage?renderActualUsage(step.usage):'')+(step.result?'<details><summary>已保存只读结果 · 消息 '+h(step.result.id)+'</summary><pre class="context-text">'+h(step.result.text)+'</pre></details>':'')+link+blocked+'</article>';
}
export function bindConsole(root,workspace,listing,detail,caps,hooks,runListing,runDetail){
 if(!root||root.dataset.bound)return;root.dataset.bound='true';const base='/api/projects/'+encodeURIComponent(workspace.document.project.id)+'/console';let backgroundPreview=null,busy=false;const run=async fn=>{if(busy)return;busy=true;hooks.busy(true);try{await fn();}catch(error){hooks.notice(error.message,true);}finally{busy=false;hooks.busy(false);}};
 if(detail?.session)bindCreativeDialogue(root,workspace,detail,caps,hooks);
 const active=[...workspace.document.chapters].sort((a,b)=>a.number-b.number).filter(c=>!archivedChapterIds(workspace).has(c.id));const planRoot=root;drawPlan(planRoot,active);
 root.addEventListener('change',event=>{if(event.target?.dataset?.consoleBackgroundStep||event.target?.id?.startsWith('console-background-max-')){backgroundPreview=null;const panel=root.querySelector('#console-background-preview');if(panel)panel.innerHTML='';}if(event.target?.id?.endsWith('-type')){const rows=readRows(planRoot);const changed=rows[Number(event.target.id.split('-')[2])];if(changed){changed.scene_order=changed.type==='scene'?1:null;changed.selection_start=changed.type==='selection'?0:null;changed.selection_end=changed.type==='selection'?0:null;drawPlan(planRoot,active);}}});
 root.addEventListener('click',event=>{const button=event.target.closest('button');if(!button)return;
  if(button.dataset.consoleCandidateRef){const id=button.dataset.consoleCandidateRef;const task=detail.dialogue?.turns.map(v=>v.task).find(v=>v?.candidates?.some(c=>c.id===id));const candidate=task?.candidates.find(c=>c.id===id);const panel=root.querySelector('#console-linked-candidate');if(!candidate||!panel){hooks.notice('候选历史不可读，请刷新本会话。',true);return;}panel.innerHTML='<h4>已关联候选 '+h(id)+'</h4><p class="hint">来源任务 '+h(task.task.id)+'；只读历史，未授权付费或正式采纳。</p><pre class="context-text">'+h(candidate.raw_text)+'</pre>';panel.scrollIntoView({block:'nearest'});return;}
  if(button.id==='console-create'){void run(async()=>{const title=root.querySelector('#console-new-title').value.trim()||'新会话';const session=await api(base+'/sessions',{method:'POST',body:JSON.stringify({operation_id:crypto.randomUUID(),title})});selectConsoleSession(session.id);await hooks.refresh();});return;}
  if(button.dataset.consoleSession){selectConsoleSession(button.dataset.consoleSession);void run(()=>hooks.refresh());return;}
  if(button.id==='console-session-rename'){void run(async()=>{await api(base+'/sessions/'+selected+'/rename',{method:'POST',body:JSON.stringify({title:root.querySelector('#console-session-title').value})});await hooks.refresh();});return;}
  if(button.id==='console-session-archive'){void run(async()=>{await api(base+'/sessions/'+selected+'/archive',{method:'POST',body:JSON.stringify({archived:!detail.session.archived})});await hooks.refresh();});return;}
  if(button.id==='console-message-add'){void run(async()=>{const text=root.querySelector('#console-message-text').value;if(!text.trim())throw Error('请先记录一条需求');await api(base+'/sessions/'+selected+'/messages',{method:'POST',body:JSON.stringify({operation_id:crypto.randomUUID(),role:'author',text,refs:[]})});await hooks.refresh();});return;}
  if(button.id==='console-plan-add'){readRows(planRoot);draftPlan.push({id:crypto.randomUUID(),type:'chapter.inspect',chapter_id:active[0]?.id||'',instruction:'',status:'planned',scene_order:null,selection_start:null,selection_end:null});drawPlan(planRoot,active);return;}
  if(button.id==='console-proposal-preview'||button.id==='console-candidate-plan'){void run(async()=>{readRows(planRoot);let result;if(button.id==='console-proposal-preview'){const proposal=JSON.parse(root.querySelector('#console-tool-proposal').value);result=await api(base+'/sessions/'+selected+'/proposal-preview',{method:'POST',body:JSON.stringify({proposal})});}else{result=await api(base+'/sessions/'+selected+'/candidate-plan',{method:'POST',body:JSON.stringify({candidate_id:button.dataset.candidateId,chapter_id:root.querySelector('#console-proposal-chapter').value})});draftCandidate=result.candidate_id;}draftPlan.push(...result.steps);drawPlan(planRoot,active);root.querySelector('#console-proposal-status').textContent=result.notice+' 已加入草案，请编辑并保存。';});return;}
  if(button.id==='console-plan-save'){void run(async()=>{const steps=readRows(planRoot);await api(base+'/sessions/'+selected+'/plan',{method:'POST',body:JSON.stringify({steps,expected_plan_revision:detail.plan.revision,...(draftCandidate?{candidate_id:draftCandidate}:{})})});await hooks.refresh();});return;}
  if(button.id==='console-run-start'){void run(async()=>{const started=await api(base+'/runs',{method:'POST',body:JSON.stringify({operation_id:crypto.randomUUID(),session_id:selected,expected_revision:workspace.revision})});selectConsoleRun(started.run.id);hooks.notice('已开始运行；仅冻结计划，尚未准备或执行任务。');await hooks.refresh();});return;}
  if(button.dataset.consoleRun){selectConsoleRun(button.dataset.consoleRun);void run(()=>hooks.refresh());return;}
  if(button.id?.startsWith('console-background-')){void run(async()=>{
   const current=runDetail?.run;if(!current)throw Error('请先选择一条运行');
   const route=base+'/runs/'+encodeURIComponent(current.id)+'/background';
   if(button.id==='console-background-refresh'){await hooks.refresh();return;}
   if(button.id==='console-background-preview-request'){
    backgroundPreview=null;
    const request={step_ids:[...root.querySelectorAll('[data-console-background-step]:checked')].map(v=>v.dataset.consoleBackgroundStep),max_steps:Number(root.querySelector('#console-background-max-steps').value),max_seconds:Number(root.querySelector('#console-background-max-seconds').value)};
    if(!request.step_ids.length)throw Error('请从当前步骤连续勾选本批步骤');
    await api(route+'/recover',{method:'POST',body:'{}'});
    const preview=await api(route+'/preview',{method:'POST',body:JSON.stringify(request)});
    const panel=root.querySelector('#console-background-preview');
    if(panel){panel.innerHTML='<h4>本批冻结来源、请求与预算</h4><pre class="context-text">'+h(JSON.stringify(preview,null,2))+'</pre><label><input id="console-background-confirm" type="checkbox">已核对本批所列来源、确切请求、执行上限及费用风险，授权本批执行</label><button id="console-background-start" type="button">确认启动后台批次</button>';backgroundPreview=preview;}
    return;
   }
   if(button.id==='console-background-start'){
    if(!backgroundPreview)throw Error('请先预览本批来源、请求和预算');
    if(!root.querySelector('#console-background-confirm')?.checked)throw Error('请明确勾选本批执行授权');
    const preview=backgroundPreview; backgroundPreview=null;
    await api(route+'/start',{method:'POST',body:JSON.stringify({...preview.request,operation_id:crypto.randomUUID(),expected_revision:preview.revision,preview_sha256:preview.sha256,confirmed:true})});
    hooks.notice('后台批次已启动；可刷新状态，候选采纳仍需单独确认。');await hooks.refresh();return;
   }
   const action={'console-background-pause':'pause','console-background-cancel':'cancel'}[button.id];
   if(action){await api(route+'/'+action,{method:'POST',body:'{}'});await hooks.refresh();}
  });return;}
  const runAction={'console-run-advance':'advance','console-run-readonly':'advance','console-run-pause':'pause','console-run-resume':'resume','console-run-cancel':'cancel','console-run-skip':'skip'}[button.id];
  if(runAction){void run(async()=>{const current=runDetail?.run;if(!current)throw Error('请先选择一条运行');if(!runDetail.revision)throw Error('运行保存编号缺失，请刷新');const payload={operation_id:crypto.randomUUID(),expected_revision:runDetail.revision};if(button.id==='console-run-readonly'){payload.allow_readonly=[...root.querySelectorAll('[data-console-readonly]:checked')].map(v=>v.dataset.consoleReadonly);if(!payload.allow_readonly.length)throw Error('请先勾选本次允许的只读工具');}if(runAction==='skip'){if(!current.current_step_id)throw Error('当前没有可跳过的步骤');payload.step_id=current.current_step_id;}await api(base+'/runs/'+encodeURIComponent(current.id)+'/'+runAction,{method:'POST',body:JSON.stringify(payload)});hooks.notice(runAction==='advance'?'推进已保存；只读连续推进遇到模型准备即停止，付费和正式采纳仍需各自确认。':'运行状态已更新。');await hooks.refresh();});return;}
  const index=Number(button.dataset.consoleUp??button.dataset.consoleDown??button.dataset.consoleRemove??button.dataset.consoleDispatch);
  if(Number.isInteger(index)&&index>=0){readRows(planRoot);
   if(button.dataset.consoleUp!==undefined&&index>0){[draftPlan[index-1],draftPlan[index]]=[draftPlan[index],draftPlan[index-1]];drawPlan(planRoot,active);return;}
   if(button.dataset.consoleDown!==undefined&&index<draftPlan.length-1){[draftPlan[index+1],draftPlan[index]]=[draftPlan[index],draftPlan[index+1]];drawPlan(planRoot,active);return;}
   if(button.dataset.consoleRemove!==undefined){draftPlan.splice(index,1);drawPlan(planRoot,active);return;}
   if(button.dataset.consoleDispatch!==undefined){const step=draftPlan[index];void run(async()=>{const steps=readRows(planRoot);await api(base+'/sessions/'+selected+'/plan',{method:'POST',body:JSON.stringify({steps})});const result=await api(base+'/sessions/'+selected+'/dispatch',{method:'POST',body:JSON.stringify({operation_id:crypto.randomUUID(),step_id:steps[index].id})});hooks.notice('已准备任务；到既有任务页逐请求确认。');await hooks.refresh();});return;}
  }
  if(button.dataset.consoleTask){const [engine,task]=button.dataset.consoleTask.split('|');hooks.openTask(engine,task);}
 });
}
