import { api } from './api.js';
import {renderModelPlanning,bindModelPlanning} from './model_planning.js';

const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const STATUS={planned:'计划中',occurred:'已发生',dropped:'已放弃'};
const REASON={late:'晚于计划',early:'早于计划',unplanned:'未计划',missing:'引用缺失',blocked:'受阻'};
const KIND={arc_stage:'弧光阶段',key_event:'关键事件',chapter_dependency:'章节依赖'};

const chapterLabel=value=>`第${value.number}章 ${value.title}${value.trashed?'（回收站，引用受阻）':value.archived?'（已归档）':''}`;
const chapterName=(listing,id)=>{
  const value=listing.chapters.find(item=>item.id===id);
  return value?chapterLabel(value):'未指定';
};
const chapterOptions=(listing,selected,emptyLabel)=>{
  const active=listing.chapters.filter(value=>!value.hidden);
  const known=listing.chapters.find(value=>value.id===selected);
  const missing=selected&&!known;
  return `<option value="">${esc(emptyLabel)}</option>${active.map(value=>`<option value="${esc(value.id)}" ${value.id===selected?'selected':''}>${esc(chapterLabel(value))}</option>`).join('')}${known?.hidden?`<option value="${esc(known.id)}" selected disabled>${esc(chapterLabel(known))}（不可作为新记录）</option>`:''}${missing?`<option value="${esc(selected)}" selected disabled>引用缺失：${esc(selected)}</option>`:''}`;
};
const characterOptions=(listing,selected,emptyLabel)=>{
  const known=listing.characters.find(value=>value.id===selected);
  return `<option value="">${esc(emptyLabel)}</option>${listing.characters.filter(value=>!value.archived).map(value=>`<option value="${esc(value.id)}" ${value.id===selected?'selected':''}>${esc(value.name)}</option>`).join('')}${known?.archived?`<option value="${esc(selected)}" selected disabled>${esc(known.name)}（已归档）</option>`:''}${selected&&!known?`<option value="${esc(selected)}" selected>引用缺失：${esc(selected)}</option>`:''}`;
};
const arcOptions=(listing,selected,emptyLabel)=>{
  const known=listing.character_arcs.find(value=>value.id===selected);
  return `<option value="">${esc(emptyLabel)}</option>${listing.character_arcs.filter(value=>!value.archived).map(value=>`<option value="${esc(value.id)}" ${value.id===selected?'selected':''}>${esc(value.title)}</option>`).join('')}${known?.archived?`<option value="${esc(known.id)}" selected>${esc(known.title)}（已归档）</option>`:''}${selected&&!known?`<option value="${esc(selected)}" selected>引用缺失：${esc(selected)}</option>`:''}`;
};

function stat(label,value,detail=''){
  return `<div class="context-card"><h4>${esc(value)}</h4><p class="hint">${esc(label)}${detail?' · '+esc(detail):''}</p></div>`;
}

function warningList(listing){
  const titles=new Map();
  for(const arc of listing.character_arcs)for(const stage of arc.stages)titles.set(stage.id,`${arc.title} / ${stage.title}`);
  for(const event of listing.key_events)titles.set(event.id,event.title);
  for(const dependency of listing.chapter_dependencies)titles.set(dependency.id,`${dependency.kind_label} ${dependency.predecessor_number??'缺失'} → ${dependency.successor_number??'缺失'}`);
  const references=listing.deviation.references.map(reference=>{
    const name=titles.get(reference.entity_id)||reference.entity_id;
    const label=reference.state==='archived'?'章节已归档':'章节引用缺失';
    return `<li>${esc(KIND[reference.kind]||reference.kind)}「${esc(name)}」的${esc(reference.field)}：${esc(label)}${reference.chapter_number?`（第${reference.chapter_number}章 ${esc(reference.chapter_title)}）`:''}</li>`;
  });
  const blocked=listing.deviation.deviations.filter(value=>value.reason==='blocked').map(value=>`<li>${esc(KIND[value.kind]||value.kind)}「${esc(value.title)}」：${esc(value.detail)}</li>`);
  const rows=[...references,...blocked];
  if(!rows.length)return '<p class="hint">没有缺失/归档引用或受阻项。章节确认不会自动把阶段或事件标记为已发生。</p>';
  return `<div class="context-card"><h4>需要作者处理的引用与阻塞</h4><ul>${rows.join('')}</ul></div>`;
}

function stageCard(listing,arc,stage){
  const occurred=stage.status==='occurred',editable=!arc.archived;
  return `<article class="context-card" data-fbp-stage="${esc(stage.id)}">
    <div class="panel-heading"><div><h4>${stage.ordinal}. ${esc(stage.title)}</h4><p class="hint"><span class="badge">${esc(STATUS[stage.status]||stage.status)}</span> · ${esc(stage.summary||'无说明')}</p></div>
      <div>${editable&&stage.status==='planned'?`<button type="button" data-fbp-action="drop_stage" data-fbp-id="${esc(stage.id)}">放弃阶段</button>`:''}
      ${editable&&stage.status!=='planned'?`<button type="button" data-fbp-action="reopen_stage" data-fbp-id="${esc(stage.id)}">回到计划</button>`:''}</div></div>
    <div class="field-grid">
      <div><h5>计划位置</h5><p>${esc(chapterName(listing,stage.planned_chapter_id))}</p></div>
      <div><h5>实际发生（作者记录）</h5><p>${occurred?esc(chapterName(listing,stage.occurred_chapter_id)):'尚未记录'}</p>${stage.body_reference?`<p class="hint">正文引用：${esc(stage.body_reference)}</p>`:''}</div>
    </div>
    ${editable&&stage.status==='planned'?`<form data-fbp-form="occur_stage" data-fbp-id="${esc(stage.id)}">
      <div class="field-grid"><div class="field"><label>发生章节（仅启用章节）</label><select name="occurrence_chapter_id" required>${chapterOptions(listing,'','选择实际发生章节')}</select></div>
      <div class="field"><label>正文引用（必填）</label><input name="body_reference" maxlength="4000" required placeholder="粘贴发生章节实际已保存正文的精确引文"></div></div>
      <button type="submit">显式记录发生</button></form>`:''}
    ${editable?`<details><summary>编辑阶段计划</summary><form data-fbp-form="update_stage" data-fbp-id="${esc(stage.id)}">
      <div class="field-grid"><div class="field"><label>标题</label><input name="title" maxlength="200" value="${esc(stage.title)}" required></div>
      <div class="field"><label>计划章节</label><select name="planned_chapter_id">${chapterOptions(listing,stage.planned_chapter_id,'未指定计划章节')}</select></div></div>
      <div class="field"><label>说明</label><textarea name="summary" maxlength="4000">${esc(stage.summary||'')}</textarea></div>
      <button type="submit">保存阶段计划</button></form></details>`:''}
  </article>`;
}

function arcCard(listing,arc){
  const stages=arc.stages.map(stage=>stageCard(listing,arc,stage)).join('');
  return `<article class="context-card" data-fbp-arc="${esc(arc.id)}">
    <div class="panel-heading"><div><h3>${esc(arc.title)}</h3><p class="hint">${esc(listing.characters.find(value=>value.id===arc.character_id)?.name||'人物引用缺失')} · ${arc.stage_count} 个阶段 · 已发生 ${arc.occurred_stage_count}${arc.archived?' · 已归档':''}</p></div>
      <div>${arc.archived?`<button type="button" data-fbp-action="restore_arc" data-fbp-id="${esc(arc.id)}">恢复弧光</button>`:`<button type="button" data-fbp-action="archive_arc" data-fbp-id="${esc(arc.id)}">归档弧光</button>`}</div></div>
    <p>${esc(arc.summary||'无说明')}</p>
    <details><summary>编辑弧光</summary><form data-fbp-form="update_arc" data-fbp-id="${esc(arc.id)}">
      <div class="field"><label>标题</label><input name="title" maxlength="200" value="${esc(arc.title)}" required></div>
      <div class="field"><label>说明</label><textarea name="summary" maxlength="4000">${esc(arc.summary||'')}</textarea></div>
      <button type="submit">保存弧光</button></form></details>
    <h5>阶段（按序）</h5>${stages||'<p class="hint">尚无阶段。</p>'}
    ${arc.archived?'':`<details><summary>新增阶段</summary><form data-fbp-form="create_stage" data-fbp-id="${esc(arc.id)}">
      <div class="field-grid"><div class="field"><label>阶段标题</label><input name="title" maxlength="200" required></div>
      <div class="field"><label>计划章节</label><select name="planned_chapter_id">${chapterOptions(listing,'','未指定计划章节')}</select></div></div>
      <div class="field"><label>阶段说明</label><textarea name="summary" maxlength="4000"></textarea></div>
      <button type="submit">新增阶段</button></form></details>`}
  </article>`;
}

function eventCard(listing,event){
  const occurred=event.status==='occurred',boundArc=listing.character_arcs.find(value=>value.id===event.arc_id),editable=!boundArc?.archived;
  return `<article class="context-card" data-fbp-event="${esc(event.id)}">
    <div class="panel-heading"><div><h4>${event.planned_order}. ${esc(event.title)}</h4><p class="hint"><span class="badge">${esc(STATUS[event.status]||event.status)}</span> · ${esc(event.character_name||'未绑定人物')} · ${esc(event.arc_title||'未绑定弧光')}</p></div>
      <div>${editable&&event.status==='planned'?`<button type="button" data-fbp-action="drop_event" data-fbp-id="${esc(event.id)}">放弃事件</button>`:''}
      ${editable&&event.status!=='planned'?`<button type="button" data-fbp-action="reopen_event" data-fbp-id="${esc(event.id)}">回到计划</button>`:''}</div></div>
    <div class="field-grid">
      <div><h5>计划位置</h5><p>${esc(chapterName(listing,event.planned_chapter_id))}</p></div>
      <div><h5>实际发生（作者记录）</h5><p>${occurred?esc(chapterName(listing,event.occurred_chapter_id)):'尚未记录'}</p>${event.body_reference?`<p class="hint">正文引用：${esc(event.body_reference)}</p>`:''}</div>
    </div>
    <p>${esc(event.summary||'无说明')}</p>
    ${editable&&event.status==='planned'?`<form data-fbp-form="occur_event" data-fbp-id="${esc(event.id)}">
      <div class="field-grid"><div class="field"><label>发生章节（仅启用章节）</label><select name="occurrence_chapter_id" required>${chapterOptions(listing,'','选择实际发生章节')}</select></div>
      <div class="field"><label>正文引用（必填）</label><input name="body_reference" maxlength="4000" required></div></div>
      <button type="submit">显式记录发生</button></form>`:''}
    ${editable?`<details><summary>编辑事件计划</summary><form data-fbp-form="update_event" data-fbp-id="${esc(event.id)}">
      <div class="field-grid"><div class="field"><label>标题</label><input name="title" maxlength="200" value="${esc(event.title)}" required></div>
      <div class="field"><label>计划顺序</label><input name="planned_order" type="number" min="1" value="${event.planned_order}"></div>
      <div class="field"><label>人物</label><select name="character_id">${characterOptions(listing,event.character_id,'不绑定人物')}</select></div>
      <div class="field"><label>弧光</label><select name="arc_id">${arcOptions(listing,event.arc_id,'不绑定弧光')}</select></div>
      <div class="field"><label>计划章节</label><select name="planned_chapter_id">${chapterOptions(listing,event.planned_chapter_id,'未指定计划章节')}</select></div></div>
      <div class="field"><label>说明</label><textarea name="summary" maxlength="4000">${esc(event.summary||'')}</textarea></div>
      <button type="submit">保存事件计划</button></form></details>`:''}
  </article>`;
}

function dependencyRow(listing,dependency){
  const pred=chapterName(listing,dependency.predecessor_chapter_id);
  const succ=chapterName(listing,dependency.successor_chapter_id);
  return `<article class="context-card" data-fbp-dependency="${esc(dependency.id)}">
    <div class="panel-heading"><div><h4>${esc(dependency.kind_label)}</h4><p class="hint">${esc(pred)} → ${esc(succ)}${dependency.archived?' · 已归档':dependency.enabled?' · 已启用':' · 已停用'}</p></div>
      <div><button type="button" data-fbp-action="set_dependency_enabled" data-fbp-id="${esc(dependency.id)}" data-fbp-enabled="${dependency.enabled?'0':'1'}" ${dependency.archived?'disabled':''}>${dependency.enabled?'停用':'启用'}</button>
      ${dependency.archived?`<button type="button" data-fbp-action="restore_dependency" data-fbp-id="${esc(dependency.id)}">恢复</button>`:`<button type="button" data-fbp-action="archive_dependency" data-fbp-id="${esc(dependency.id)}">归档</button>`}</div></div>
    ${dependency.note?`<p>${esc(dependency.note)}</p>`:''}
    <details><summary>编辑依赖</summary><form data-fbp-form="update_dependency" data-fbp-id="${esc(dependency.id)}">
      <div class="field-grid"><div class="field"><label>前驱章节</label><select name="predecessor_chapter_id" required>${chapterOptions(listing,dependency.predecessor_chapter_id,'选择前驱章节')}</select></div>
      <div class="field"><label>后继章节</label><select name="successor_chapter_id" required>${chapterOptions(listing,dependency.successor_chapter_id,'选择后继章节')}</select></div>
      <div class="field"><label>依赖类型</label><select name="kind">${listing.dependency_kinds.map(kind=>`<option value="${esc(kind.id)}" ${kind.id===dependency.kind?'selected':''}>${esc(kind.label)}</option>`).join('')}</select></div></div>
      <div class="field"><label>说明</label><input name="note" maxlength="4000" value="${esc(dependency.note||'')}"></div>
      <button type="submit" ${dependency.archived?'disabled':''}>保存依赖</button></form></details>
  </article>`;
}

export function renderFullBookPlanning(workspace,listing){
  if(!listing)return '';
  const deviation=listing.deviation;
  const arcs=listing.character_arcs.map(arc=>arcCard(listing,arc)).join('');
  const events=listing.key_events.map(event=>eventCard(listing,event)).join('');
  const dependencies=listing.chapter_dependencies.map(value=>dependencyRow(listing,value)).join('');
  const reasonRows=Object.entries(deviation.deviations_by_reason).filter(([,count])=>count>0).map(([reason,count])=>`<li>${esc(REASON[reason]||reason)}：${count}</li>`).join('');
  return `<section class="panel" id="full-book-planning-root">
    <div class="panel-heading"><div><h2>全书规划 · 弧光 / 关键事件 / 章节依赖</h2><p class="hint">${esc(listing.method)}。计划位置与实际发生分列显示；确认章节正文不会自动改变这里的发生状态。</p></div><span class="badge">V26</span></div>
    ${renderBodyPlanning(workspace,listing)}
    <div class="field-grid">
      ${stat('已确认章节',deviation.confirmed_chapter_count,`最新第${deviation.latest_confirmed_chapter_number??'—'}章`)}
      ${stat('弧光阶段',deviation.stage_counts.planned+deviation.stage_counts.occurred+deviation.stage_counts.dropped,`计划 ${deviation.stage_counts.planned} / 发生 ${deviation.stage_counts.occurred} / 放弃 ${deviation.stage_counts.dropped}`)}
      ${stat('关键事件',deviation.event_counts.planned+deviation.event_counts.occurred+deviation.event_counts.dropped,`计划 ${deviation.event_counts.planned} / 发生 ${deviation.event_counts.occurred} / 放弃 ${deviation.event_counts.dropped}`)}
      ${stat('章节依赖',deviation.dependency_counts.enabled+deviation.dependency_counts.disabled+deviation.dependency_counts.archived,`启用 ${deviation.dependency_counts.enabled} / 停用 ${deviation.dependency_counts.disabled} / 归档 ${deviation.dependency_counts.archived}`)}
    </div>
    <div class="context-card"><h4>偏差与进度</h4><p class="hint">${esc(deviation.occurrence_policy)}</p>${reasonRows?`<ul>${reasonRows}</ul>`:'<p class="hint">当前没有位置偏差。</p>'}
      ${deviation.deviations.length?`<ul>${deviation.deviations.map(value=>`<li>${esc(KIND[value.kind]||value.kind)}「${esc(value.title)}」：${esc(REASON[value.reason]||value.reason)} · ${esc(value.detail)}</li>`).join('')}</ul>`:''}
    </div>
    ${warningList(listing)}
    <h3>人物弧光（${listing.character_arcs.length}）</h3>
    <form data-fbp-form="create_arc">
      <div class="field-grid"><div class="field"><label>人物</label><select name="character_id" required>${characterOptions(listing,'','选择人物')}</select></div>
      <div class="field"><label>弧光标题</label><input name="title" maxlength="200" required></div></div>
      <div class="field"><label>说明</label><textarea name="summary" maxlength="4000"></textarea></div>
      <button type="submit">新增人物弧光</button>
    </form>
    ${arcs||'<p class="hint">尚无人物弧光。</p>'}
    <h3>关键事件（${listing.key_events.length}）</h3>
    <form data-fbp-form="create_event">
      <div class="field-grid"><div class="field"><label>事件标题</label><input name="title" maxlength="200" required></div>
      <div class="field"><label>计划顺序</label><input name="planned_order" type="number" min="1" placeholder="留空自动追加"></div>
      <div class="field"><label>人物</label><select name="character_id">${characterOptions(listing,'','不绑定人物')}</select></div>
      <div class="field"><label>弧光</label><select name="arc_id">${arcOptions(listing,'','不绑定弧光')}</select></div>
      <div class="field"><label>计划章节</label><select name="planned_chapter_id">${chapterOptions(listing,'','未指定计划章节')}</select></div></div>
      <div class="field"><label>说明</label><textarea name="summary" maxlength="4000"></textarea></div>
      <button type="submit">新增关键事件</button>
    </form>
    ${events||'<p class="hint">尚无关键事件。</p>'}
    <h3>章节依赖（${listing.chapter_dependencies.length}）</h3>
    <form data-fbp-form="create_dependency">
      <div class="field-grid"><div class="field"><label>前驱章节</label><select name="predecessor_chapter_id" required>${chapterOptions(listing,'','选择前驱章节')}</select></div>
      <div class="field"><label>后继章节</label><select name="successor_chapter_id" required>${chapterOptions(listing,'','选择后继章节')}</select></div>
      <div class="field"><label>依赖类型</label><select name="kind">${listing.dependency_kinds.map(kind=>`<option value="${esc(kind.id)}">${esc(kind.label)}</option>`).join('')}</select></div></div>
      <div class="field"><label>说明</label><input name="note" maxlength="4000"></div>
      <button type="submit">新增章节依赖</button>
    </form>
    ${dependencies||'<p class="hint">尚无章节依赖。</p>'}
  </section>`;
}

const ACTION_TARGET={archive_arc:'arc_id',restore_arc:'arc_id',drop_stage:'stage_id',reopen_stage:'stage_id',drop_event:'event_id',reopen_event:'event_id',archive_dependency:'dependency_id',restore_dependency:'dependency_id',set_dependency_enabled:'dependency_id'};
const CONFIRM={archive_arc:'归档这条人物弧光？阶段与历史仍保留，但不能再新增/更新其阶段。',drop_stage:'放弃这个阶段？可在之后回到计划。',reopen_stage:'回到计划会清除已记录的发生章节和正文引用。继续？',drop_event:'放弃这个关键事件？可在之后回到计划。',reopen_event:'回到计划会清除已记录的发生章节和正文引用。继续？',archive_dependency:'归档这条章节依赖？历史仍保留，但不再出现在偏差检查中。'};

export function bindFullBookPlanning(root,workspace,listing,options){
  if(!root||!listing)return;
  const project=workspace.document.project.id;
  bindBodyPlanning(root,workspace,listing,options);
  bindModelPlanning(root,workspace,listing,options);
  const base=`/api/projects/${encodeURIComponent(project)}/full-book-planning/actions`;
  const run=async task=>{
    if(options.busy)options.busy(true);
    try{await task();}
    catch(error){options.notice?.(error.message,true);}
    finally{if(options.busy)options.busy(false);}
  };
  const send=async(action,payload)=>{
    const body={action,operation_id:crypto.randomUUID(),expected_revision:workspace.revision,...payload};
    const result=await api(base,{method:'POST',body:JSON.stringify(body)});
    options.notice?.('全书规划已保存。');
    await options.refresh?.();
    return result;
  };
  const nullable=value=>String(value||'').trim()||null;
  const text=value=>String(value||'').trim();
  root.addEventListener('click',event=>{
    const button=event.target.closest('[data-fbp-action]');
    if(!button||button.disabled)return;
    const action=button.dataset.fbpAction,key=ACTION_TARGET[action];
    if(!key)return;
    if(CONFIRM[action]&&!window.confirm(CONFIRM[action]))return;
    const payload={[key]:button.dataset.fbpId};
    if(action==='set_dependency_enabled')payload.enabled=button.dataset.fbpEnabled==='1';
    run(()=>send(action,payload));
  });
  root.addEventListener('submit',event=>{
    const form=event.target.closest('form[data-fbp-form]');
    if(!form)return;
    event.preventDefault();
    const action=form.dataset.fbpForm,id=form.dataset.fbpId,value=name=>text(form.elements[name]?.value);
    const payload={};
    if(action==='create_arc')Object.assign(payload,{character_id:value('character_id'),title:value('title'),summary:value('summary')});
    else if(action==='update_arc')Object.assign(payload,{arc_id:id,title:value('title'),summary:value('summary')});
    else if(action==='create_stage')Object.assign(payload,{arc_id:id,title:value('title'),summary:value('summary'),planned_chapter_id:nullable(value('planned_chapter_id'))});
    else if(action==='update_stage')Object.assign(payload,{stage_id:id,title:value('title'),summary:value('summary'),planned_chapter_id:nullable(value('planned_chapter_id'))});
    else if(action==='occur_stage'||action==='occur_event'){
      const target=action==='occur_stage'?'stage_id':'event_id';
      if(!value('occurrence_chapter_id')||!value('body_reference')){options.notice?.('必须选择发生章节并填写正文引用。',true);return;}
      if(!window.confirm('显式记录发生？章节确认不会自动完成这一步；之后回到计划会清除本次记录。'))return;
      Object.assign(payload,{[target]:id,occurrence_chapter_id:value('occurrence_chapter_id'),body_reference:value('body_reference')});
    }
    else if(action==='create_event'){
      Object.assign(payload,{title:value('title'),summary:value('summary'),character_id:nullable(value('character_id')),arc_id:nullable(value('arc_id')),planned_chapter_id:nullable(value('planned_chapter_id'))});
      if(value('planned_order'))payload.planned_order=Number(value('planned_order'));
    }
    else if(action==='update_event'){
      Object.assign(payload,{event_id:id,title:value('title'),summary:value('summary'),character_id:nullable(value('character_id')),arc_id:nullable(value('arc_id')),planned_chapter_id:nullable(value('planned_chapter_id'))});
      if(value('planned_order'))payload.planned_order=Number(value('planned_order'));
      else{options.notice?.('更新事件时计划顺序不能为空。',true);return;}
    }
    else if(action==='create_dependency')Object.assign(payload,{predecessor_chapter_id:value('predecessor_chapter_id'),successor_chapter_id:value('successor_chapter_id'),kind:value('kind'),note:value('note')});
    else if(action==='update_dependency')Object.assign(payload,{dependency_id:id,predecessor_chapter_id:value('predecessor_chapter_id'),successor_chapter_id:value('successor_chapter_id'),kind:value('kind'),note:value('note')});
    else return;
    run(()=>send(action,payload));
  });
}

function planningTargets(listing){
  return [...listing.character_arcs.map(v=>({kind:'arc',id:v.id,label:`弧光：${v.title}`})),
    ...listing.character_arc_stages.map(v=>({kind:'stage',id:v.id,label:`阶段：${v.title}`})),
    ...listing.key_events.map(v=>({kind:'event',id:v.id,label:`事件：${v.title}`})),
    ...listing.chapter_dependencies.map(v=>({kind:'dependency',id:v.id,label:`依赖：${v.predecessor_number} → ${v.successor_number}`}))];
}

function renderBodyPlanning(workspace,listing){
  const body=listing.body_planning||{proposals:[],entities:[],locks:[]};
  const targets=planningTargets(listing).map(v=>`<option value="${esc(v.kind+':'+v.id)}">${esc(v.label)}</option>`).join('');
  const proposals=body.proposals.slice(-50).reverse().map(p=>`<article class="context-card" data-body-proposal="${esc(p.id)}"><h4>${esc(p.reason)}</h4>
    <p class="hint">${esc(p.origin)} · ${p.receipt?esc(p.receipt.decision):p.outdated?'已过期，可拒绝后重新提出':'待作者核对'} · ${p.actions.length} 项变更</p>
    <blockquote>${esc(p.quote)}</blockquote><pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(JSON.stringify(p.actions,null,2))}</pre>
    ${p.receipt?'':`<button type="button" data-body-preview="${esc(p.id)}" ${p.outdated?'disabled':''}>影响预览</button>
    <button type="button" data-body-accept="${esc(p.id)}" disabled>接受此提案</button><button type="button" data-body-reject="${esc(p.id)}">拒绝此提案</button><div data-body-impact></div>`}</article>`).join('');
  return `<details class="context-card" data-body-planning><summary>正文驱动规划 / 偏离提案 / AI 补全</summary>
    <p class="hint">正文和计划分开。标题匹配、AI导入及模型候选均须独立转待审提案，再经影响预览和人工接受；语义质量待核实。</p>
    ${renderModelPlanning(workspace,listing)}
    <form data-body-form>
      <div class="field-grid"><div class="field"><label>已保存来源章节</label><select name="chapter_id" required>${chapterOptions(listing,'','选择来源章节')}</select></div>
      <div class="field"><label>引文起点（Unicode字符，可留空自动定位唯一原文）</label><input name="start" type="number" min="0"></div></div>
      <div class="field"><label>正文精确引文（最多4000字符）</label><textarea name="quote" maxlength="8000" required></textarea></div>
      <div class="field-grid"><div class="field"><label>提案类型</label><select name="mode"><option value="move">调整计划位置</option><option value="occur">记录实际发生</option><option value="create_event">新增计划事件</option><option value="drop">放弃缺席阶段/事件</option><option value="disable">停用受阻依赖</option><option value="f1">反馈全书大纲字段</option></select></div>
      <div class="field"><label>目标（新增事件可忽略）</label><select name="target">${targets}</select></div>
      <div class="field"><label>新计划位置</label><select name="planned_chapter_id">${chapterOptions(listing,'','不指定计划位置')}</select></div>
      <div class="field"><label>新事件标题</label><input name="title" maxlength="200"></div>
      <div class="field"><label>大纲字段</label><select name="field"><option value="ending">结局</option><option value="theme">主题</option><option value="premise">前提</option><option value="main_plot">主线</option></select></div></div>
      <div class="field"><label>大纲字段建议值（仅大纲反馈使用）</label><textarea name="new_text"></textarea></div>
      <div class="field"><label>提案理由</label><input name="reason" maxlength="4000" value="依据已保存正文核对计划"></div>
      <button type="submit">保存待审提案</button><button type="button" data-body-infer>按正文标题匹配提出建议</button><button type="button" data-body-context>准备 AI 补全上下文</button>
      <details><summary>导入 AI 建议（待审，不直接执行）</summary><p class="hint">粘贴补全结果的 actions JSON 数组，每项包含 action 和 values。不会调用外部模型。</p><textarea name="ai_actions" aria-label="AI建议actions数组"></textarea><button type="button" data-body-import>保存 AI 待审建议</button></details>
      <textarea name="completion" readonly aria-label="AI补全上下文" hidden></textarea>
    </form>
    <h4>规划目标锁定</h4><form data-body-lock><select name="target">${targets}</select><input name="reason" maxlength="4000" required placeholder="锁定或解锁理由"><button type="submit" name="lock" value="1">锁定</button><button type="submit" name="lock" value="0">明确解锁</button></form>
    <p class="hint">${esc(body.locks.filter((v,i,a)=>v.locked&&!a.slice(i+1).some(n=>n.target_kind===v.target_kind&&n.target_id===v.target_id)).map(v=>planningTargets(listing).find(t=>t.kind===v.target_kind&&t.id===v.target_id)?.label||v.target_id).join('；')||'没有已锁定的C07目标')}。F1字段锁继续使用既有知识反馈锁定。</p>
    <h4>人物及结构化设定生命周期</h4>${body.entities.map(e=>`<p>${esc(e.label)} · ${e.archived?'已归档':'启用'} <button type="button" data-body-entity="${esc(e.kind+':'+e.entity_id)}" data-body-archive="${e.archived?'0':'1'}">${e.archived?'恢复':'预览引用并归档'}</button></p>`).join('')}
    <h4>待审与历史（${body.proposals.length}项，显示最近50项）</h4>${proposals||'<p class="hint">尚无正文规划提案。</p>'}
  </details>`;
}

function bindBodyPlanning(root,workspace,listing,options){
  const project=workspace.document.project.id,previews=new Map(),form=root.querySelector('[data-body-form]');
  const call=(action,body)=>api(`/api/projects/${encodeURIComponent(project)}/body-planning/${action}`,{method:'POST',body:JSON.stringify(body)});
  const write=body=>({operation_id:crypto.randomUUID(),expected_revision:workspace.revision,...body});
  const run=async task=>{options.busy?.(true);try{await task();}catch(error){options.notice?.(error.message,true);}finally{
    options.busy?.(false);
    // The global request guard restores the pre-request disabled state. Reapply
    // only the acceptance grants issued by a successful preview on this view.
    for(const id of previews.keys()){
      const card=[...root.querySelectorAll('[data-body-proposal]')].find(c=>c.dataset.bodyProposal===id);
      const accept=card?.querySelector('[data-body-accept]');if(accept)accept.disabled=false;
    }
  }};
  const evidence=()=>{
    const chapter=listing.chapters.find(c=>c.id===form.elements.chapter_id.value),quote=form.elements.quote.value;
    if(!chapter||!quote)throw Error('请选择已保存章节并填写精确引文。');
    let start;
    if(form.elements.start.value!=='')start=Number(form.elements.start.value);
    else{const offset=chapter.content.indexOf(quote);if(offset<0||chapter.content.indexOf(quote,offset+1)>=0)throw Error('引文不存在或不唯一；请核对并填写Unicode起点。');start=Array.from(chapter.content.slice(0,offset)).length;}
    return {chapter_id:chapter.id,start,end:start+Array.from(quote).length,quote};
  };
  form?.addEventListener('submit',event=>{event.preventDefault();run(async()=>{
    const source=evidence(),mode=form.elements.mode.value,[kind,id]=form.elements.target.value.split(':'),values={},actions=[];
    const planned=form.elements.planned_chapter_id.value||null;
    if(mode==='create_event')actions.push({action:'create_event',values:{title:form.elements.title.value,planned_chapter_id:planned}});
    else if(mode==='f1'){
      if(!workspace.document.book_outline)throw Error('请先保存全书大纲。');
      actions.push({action:'prepare_plan',values:{target_kind:'book_outline',target_id:workspace.document.book_outline.id,field:form.elements.field.value,new_text:form.elements.new_text.value,reason:form.elements.reason.value,source:{kind:'chapter',entity_id:source.chapter_id}}});
    }else if(mode==='disable'){
      if(kind!=='dependency')throw Error('请选择章节依赖。');actions.push({action:'set_dependency_enabled',values:{dependency_id:id,enabled:false}});
    }else{
      if(!['stage','event'].includes(kind))throw Error('请选择阶段或关键事件。');values[`${kind}_id`]=id;
      if(mode==='move')values.planned_chapter_id=planned;
      if(mode==='occur')Object.assign(values,{occurrence_chapter_id:source.chapter_id,body_reference:source.quote});
      actions.push({action:`${mode==='move'?'update':mode==='occur'?'occur':'drop'}_${kind}`,values});
    }
    await call('prepare',write({...source,actions,reason:form.elements.reason.value,origin:'author'}));options.notice?.('待审提案已保存；正式规划尚未变更。');await options.refresh?.();
  });});
  root.querySelector('[data-body-lock]')?.addEventListener('submit',event=>{event.preventDefault();run(async()=>{
    const lockForm=event.currentTarget,[kind,id]=lockForm.elements.target.value.split(':');
    await call('set-lock',write({target_kind:kind,target_id:id,locked:event.submitter.value==='1',reason:lockForm.elements.reason.value}));await options.refresh?.();
  });});
  root.addEventListener('click',event=>{const button=event.target.closest('[data-body-preview],[data-body-accept],[data-body-reject],[data-body-context],[data-body-import],[data-body-infer],[data-body-entity]');if(!button||button.disabled)return;run(async()=>{
    if(button.hasAttribute('data-body-preview')){
      const id=button.dataset.bodyPreview,preview=await call('preview',{proposal_id:id});previews.set(id,preview);
      const card=button.closest('[data-body-proposal]');card.querySelector('[data-body-impact]').innerHTML=`<h5>偏离计数变化</h5><p>${Object.entries(preview.deviation.reason_delta).map(([k,v])=>`${esc(REASON[k])}: ${v>0?'+':''}${v}`).join('；')}</p><p>后续章节：${esc(preview.impact.later_chapter_ids.map(id=>chapterName(listing,id)).join('；')||'无')}；未回收人工伏笔：${preview.impact.foreshadow_node_ids.length}</p><pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(JSON.stringify(preview.changes,null,2))}</pre><p class="hint">${esc(preview.limitations.join('；'))}</p>`;
      card.querySelector('[data-body-accept]').disabled=false;
    }else if(button.hasAttribute('data-body-accept')||button.hasAttribute('data-body-reject')){
      const accepted=button.hasAttribute('data-body-accept'),id=accepted?button.dataset.bodyAccept:button.dataset.bodyReject,preview=previews.get(id);
      if(accepted&&!preview)throw Error('请先查看影响预览。');
      if(!window.confirm(accepted?'确认接受当前影响预览中的全部变更？不会改写正文。':'明确拒绝此提案？正式规划保持原状。'))return;
      await call('decide',write({proposal_id:id,decision:accepted?'accepted':'rejected',...(accepted?{preview_sha256:preview.preview_sha256}:{})}));options.notice?.(accepted?'提案已正式采纳。':'提案已拒绝。');await options.refresh?.();
    }else if(button.hasAttribute('data-body-entity')){
      const [kind,id]=button.dataset.bodyEntity.split(':'),references=await call('references',{kind,entity_id:id}),archive=button.dataset.bodyArchive==='1';
      if(!window.confirm(`${archive?'归档':'恢复'}此对象？保留${references.references.length}处引用与全部历史。\n${references.references.slice(0,12).join('\n')}`))return;
      await call('lifecycle',write({kind,entity_id:id,archived:archive,confirm:true}));await options.refresh?.();
    }else if(button.hasAttribute('data-body-context')){
      const context=await call('completion',evidence());form.elements.completion.hidden=false;form.elements.completion.value=JSON.stringify(context,null,2);options.notice?.('已准备补全上下文；未发送模型请求。');
    }else if(button.hasAttribute('data-body-infer')){
      await call('infer',write(evidence()));options.notice?.('标题匹配建议已保存为待审提案。');await options.refresh?.();
    }else{
      const actions=JSON.parse(form.elements.ai_actions.value);await call('prepare',write({...evidence(),actions,origin:'ai_import',reason:form.elements.reason.value}));options.notice?.('AI建议已保存，尚未正式采纳。');await options.refresh?.();
    }
  });});
}
