// Local policies never grant a paid model request.
export function memoryAutomationPolicy(workspace){
  const event=(workspace.memory_automation_events||[]).filter(e=>e.kind==='policy').at(-1);
  return event?.authorization_project_id===workspace.document.project.id?event.policy:{track_updates:false,auto_select:false};
}

export function renderMemoryAutomation(workspace,escapeHTML){
  const policy=memoryAutomationPolicy(workspace),events=workspace.memory_automation_events||[];
  const chapters=new Map(workspace.document.chapters.map(c=>[c.id,`第${c.number}章 ${c.title}`]));
  const jobs=events.filter(e=>e.kind==='impact').map(job=>{
    const action=events.filter(e=>e.job_id===job.id).at(-1),closed=action?.kind==='cancel'||action?.kind==='resolve',status=action?.kind==='cancel'?'已取消':action?.kind==='resolve'?'已核对':'待核对更新';
    return `<article class="context-card"><p>保存编号 ${job.revision} · ${status} · ${job.memory_ids.length} 条受影响记忆 / ${job.rollup_ids.length} 个汇总</p><p>${escapeHTML(job.chapter_ids.map(id=>chapters.get(id)||id).join('；'))}</p><details><summary>精确影响来源</summary><pre class="context-text">${escapeHTML(JSON.stringify({chapter_ids:job.chapter_ids,memory_ids:job.memory_ids,rollup_ids:job.rollup_ids},null,2))}</pre></details><button type="button" data-memory-queue="${closed?'reopen':'cancel'}" data-job-id="${escapeHTML(job.id)}">${closed?'重新打开待核对项':'取消本项'}</button>${!closed?`<button type="button" data-memory-queue="resolve" data-job-id="${escapeHTML(job.id)}">标记本项已人工核对</button>`+job.chapter_ids.map(id=>`<button type="button" data-memory-update-summary="${escapeHTML(id)}">核对${escapeHTML(chapters.get(id)||id)}的摘要请求</button>`).join(''):''}</article>`;
  }).reverse();
  return renderMemoryRefresh(workspace,escapeHTML)+`<section class="panel" id="memory-automation"><h2>增量记忆与自动选用</h2><p>默认关闭。启用后，保存正文、修改记忆、归档、恢复或重排会在同一事务记录精确影响队列；不自动调用模型或覆盖摘要。自动选用仅使用作者已确认、来源新鲜、无冲突且故事位置合法的正文事实；规划和未采纳候选排除。字符预算不足整条排除，可在上下文预览查看原因。</p><label class="check-label"><input id="memory-track-updates" type="checkbox" ${policy.track_updates?'checked':''}>保存后记录待核对更新</label><label class="check-label"><input id="memory-auto-select" type="checkbox" ${policy.auto_select?'checked':''}>允许自动选择已确认正文记忆（上下文入口可逐次取消）</label><button id="save-memory-policy" type="button">明确保存本书策略</button><p class="hint">开关不授权外发或自动付费。摘要仍须逐请求核对冻结内容、预算并确认执行；模型输出仅为待核实提案，只有显式接受才新增记忆。取消队列不取消已单独准备的模型任务。</p><h3>更新队列（含已处理，共${jobs.length}项）</h3>${jobs.join('')||'<p class="hint">尚无增量项；开启前的历史不会伪造为新保存事件。</p>'}</section>`;
}


export function renderMemoryRefresh(workspace,h){
  const events=workspace.memory_refresh_events||[],policy=events.filter(e=>e.kind==='policy').at(-1);
  const enabled=policy?.project_id===workspace.document.project.id&&policy.auto_refresh;
  const memories=new Map((workspace.memories||[]).map(m=>[m.id,m]));
  const jobs=events.filter(e=>e.kind==='impact').map(job=>{
    const last=events.filter(e=>e.job_id===job.id).at(-1),status=last?.status||'pending';
    const labels={pending:'待刷新',failed:'刷新失败，可重试',succeeded:'已刷新'};
    return `<article class="context-card" data-refresh-card="${h(job.id)}"><h3>保存编号 ${job.revision} · ${labels[status]}</h3><p>${job.memory_ids.length} 条记忆 / ${job.rollup_ids.length} 个汇总</p>${last?.error?`<p role="alert">${h(last.error)}</p>`:''}<details><summary>来源与刷新记录</summary><pre>${h(JSON.stringify({sources:job.sources,attempts:events.filter(e=>e.job_id===job.id)},null,2))}</pre></details>${status!=='succeeded'?job.memory_ids.map(id=>{
      const m=memories.get(id);if(!m?.active)return '';
      return `<label>${h(m.title)}：作者核对后的新文本<textarea data-refresh-memory="${h(id)}" placeholder="${m.kind==='chapter_summary'?'留空表示明确使用当前正文原文':'请核对正文后填写新事实'}"></textarea></label><details><summary>查看旧版本</summary><pre>${h(JSON.stringify((workspace.memory_history||[]).filter(e=>e.memory_id===id),null,2))}</pre></details>`;
    }).join('')+`<button type="button" data-memory-refresh="${h(job.id)}">${status==='failed'?'重试刷新':'确认刷新本项'}</button>`:''}</article>`;
  }).reverse();
  return `<section class="panel"><h2>长篇记忆待刷新队列</h2><p>正文保存后自动记录影响范围，默认不改记忆内容。确认时填写人工事实的新文本；章节摘要留空将使用当前正文原文，不生成语义摘要。相关章节、卷和书汇总随后一起重建，任一步失败保留原内容并显示原因。</p><label><input id="memory-refresh-auto" type="checkbox" ${enabled?'checked':''}>自动刷新本地章节原文摘录及相关汇总（默认关闭；人工事实需填写新文本，否则记录失败；不调用模型）</label><button id="save-memory-refresh-policy" type="button">保存自动刷新策略</button>${jobs.join('')||'<p>暂无受影响项。</p>'}</section>`;
}
