

import {memoryAutomationPolicy,renderMemoryAutomation} from './memory_automation.js';
// 编辑视图沿用原有业务表单；textarea 原文通过 value 注入。
export const escapeHTML = value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');
export const textareaValues = new Map();

const planFields={
  volumes:[['number','分卷顺序','number'],['title','卷名','text'],['summary','分卷概要','long'],['chapter_ids','分卷章节','chapters']],
  scenes:[['order','场景顺序','number'],['summary','场景目标','long'],['character_ids','场景人物','characters'],['location','场景地点','text'],['story_time','场景时间','text']],
  goals:[['value','人物目标','long']],
  relationships:[['target_character_id','关系对象','character'],['relation','关系名称','text'],['description','关系说明','long']]
};
function planRows(name,items,choices) {
  return items.map((item,index)=>`<fieldset class="plan-row" data-plan-row><legend>${{volumes:'分卷',scenes:'场景',goals:'目标',relationships:'关系'}[name]} ${index+1}</legend>${planFields[name].map(([key,label,type])=>{
    const id=`plan-${name}-${index}-${key}`,value=name==='goals'?item:(item[key]??'');
    const options=type==='chapters'?choices.chapters:choices.characters;
    const control=['chapters','characters','character'].includes(type)
      ?`<select id="${id}" data-plan-field="${key}" ${type==='character'?'':'multiple size="4"'}>${type==='character'?'<option value="">请选择本书人物</option>':''}${options.map(option=>`<option value="${escapeHTML(option.id)}" ${(Array.isArray(value)?value.includes(option.id):value===option.id)?'selected':''}>${escapeHTML(option.label)}</option>`).join('')}</select>`
      :type==='long'?`<textarea id="${id}" data-plan-field="${key}"></textarea>`:`<input id="${id}" data-plan-field="${key}" type="${type==='number'?'number':'text'}" ${type==='number'?'min="1" step="1"':''} value="${escapeHTML(value)}">`;
    return `<div class="field"><label for="${id}">${label}</label>${control}</div>`;
  }).join('')}<button type="button" data-plan-remove="${index}">删除此项</button></fieldset>`).join('');
}
export function planningEditor(name,label,items,workspace) {
  const choices={chapters:activeChapters(workspace).map(c=>({id:c.id,label:`第${c.number}章 · ${c.title}`})),characters:workspace.document.characters.map(c=>({id:c.id,label:c.name}))};
  return `<section class="planning-editor" data-plan="${name}" data-plan-choices="${escapeHTML(JSON.stringify(choices))}"><h3>${label}</h3><input type="hidden" name="${name}" data-structured value="${escapeHTML(JSON.stringify(items))}"><div class="plan-rows">${planRows(name,items,choices)}</div><button type="button" data-plan-add>添加${{volumes:'分卷',scenes:'场景',goals:'目标',relationships:'关系'}[name]}</button><p class="hint">删除全部项目后保存会明确清空本列表；其它未修改字段与旧历史保留。</p></section>`;
}
function selectedReferences(select,previous) {
  const selected=[...select.selectedOptions].map(option=>option.value);
  // 未取消的旧项保留原顺序及合法重复；新增成员按选项顺序追加。
  return [...previous.filter(id=>selected.includes(id)),...selected.filter(id=>!previous.includes(id))];
}
export function syncPlanning(form) {
  if(!form)return;
  for(const section of form.querySelectorAll('[data-plan]')) {
    const name=section.dataset.plan;
    const previous=JSON.parse(section.querySelector('[data-structured]').value);
    const items=[...section.querySelectorAll('[data-plan-row]')].map((row,index)=>{
      const item=Object.fromEntries(planFields[name].map(([key,label,type])=>{
        const input=row.querySelector(`[data-plan-field="${key}"]`);
        const original=input.planOriginal;
        const text=type==='long'&&typeof original==='string'&&input.value===original.replace(/\r\n?/g,'\n')?original:input.value;
        return [key,['chapters','characters'].includes(type)?selectedReferences(input,previous[index][key]):type==='number'?Number(input.value):text];
      }));return name==='goals'?item.value:item;
    });
    section.querySelector('[data-structured]').value=JSON.stringify(items);
  }
  for(const select of form.querySelectorAll('[data-reference-list]')) {
    const hidden=form.elements.namedItem(select.dataset.referenceList);
    hidden.value=JSON.stringify(selectedReferences(select,JSON.parse(hidden.value)));
  }
}
export function hydratePlanning(form) {
  if(!form)return;
  for(const section of form.querySelectorAll('[data-plan]')) {
    const name=section.dataset.plan,items=JSON.parse(section.querySelector('[data-structured]').value);
    section.querySelector('.plan-rows').innerHTML=planRows(name,items,JSON.parse(section.dataset.planChoices));
    [...section.querySelectorAll('[data-plan-row]')].forEach((row,index)=>{
      for(const [key,label,type] of planFields[name])if(type==='long') {
        const input=row.querySelector(`[data-plan-field="${key}"]`),value=name==='goals'?items[index]:items[index][key];
        input.value=value;input.planOriginal=value;
      }
    });
  }
  for(const select of form.querySelectorAll('[data-reference-list]')) {
    const references=JSON.parse(form.elements.namedItem(select.dataset.referenceList).value);
    for(const option of select.options)option.selected=references.includes(option.value);
  }
}
export function changePlanning(button) {
  const section=button.closest('[data-plan]'),form=section.closest('form');syncPlanning(form);
  const name=section.dataset.plan,hidden=section.querySelector('[data-structured]'),items=JSON.parse(hidden.value);
  if(button.hasAttribute('data-plan-remove'))items.splice(Number(button.dataset.planRemove),1);
  else if(name==='goals')items.push('');
  else items.push(Object.fromEntries(planFields[name].map(([key,label,type])=>[key,type==='number'?Math.max(0,...items.map(item=>Number(item[key])||0))+1:['chapters','characters'].includes(type)?[]:''])));
  hidden.value=JSON.stringify(items);hydratePlanning(form);
}
export function formValues(form,{structured=false}={}) {
  syncPlanning(form);
  return Object.fromEntries([...form.elements].filter(el=>el.name&&el.name!=='authorize_confirmed').map(el=>{
    let value=el.type==='checkbox'?el.checked:el.multiple?JSON.stringify([...el.selectedOptions].map(o=>o.value)):el.value;
    if(structured&&(el.hasAttribute('data-structured')||el.multiple))value=JSON.parse(value);
    return [el.name,value];
  }));
}

export function field(name, label, value = '', multiline = false, required = false, scope = 'edit', extraClass = '') {
  const id = `${scope}-${name}`;
  if (multiline) textareaValues.set(id, value);
  const input = multiline
    ? `<textarea id="${id}" name="${name}" class="${extraClass}" ${required ? 'required' : ''}></textarea>`
    : `<input id="${id}" name="${name}" value="${escapeHTML(value)}" ${required ? 'required' : ''} autocomplete="off">`;
  return `<div class="field"><label for="${id}">${label}</label>${input}</div>`;
}

export function panelForm(action, title, description, body, button) {
  return `<form id="active-editor" class="panel" data-action="${action}"><div class="panel-heading"><div><h2>${title}</h2><p class="hint">${description}</p></div><button type="submit" form="active-editor" class="primary">${button}</button></div>${body}<div class="form-footer"><span>Ctrl+S 保存当前文档 · 保存后写入本地数据库</span></div></form>`;
}


export function renderProject(workspace) {
  const p = workspace.document.project;
  return panelForm('save_project', '这本书的起点', '整理基本资料。作者和类型可以稍后补充。',
    '<div class="field-grid">' + field('title', '书名', p.title, false, true) + field('author', '作者', p.author) + field('genre', '小说类型', p.genre) + '</div>' + field('summary', '小说简介', p.summary, true), '保存项目资料');
}

export function renderOutline(workspace) {
  const outline = workspace.document.book_outline || {};
  return panelForm('save_book_outline', '给故事一条完整的主线', '先写主题与结局，再逐步补足故事的起承转合。',
    field('theme', '核心主题', outline.theme) + field('premise', '故事起点', outline.premise, true) + field('main_plot', '全书主线', outline.main_plot, true) + field('ending', '预期结局', outline.ending, true) + planningEditor('volumes','分卷与章节归属',outline.volumes||[],workspace), '保存全书大纲');
}

export function renderWriting(workspace, selectedChapter, writingPane) {
  const archived=archivedChapterIds(workspace),all=[...workspace.document.chapters].sort((a,b)=>a.number-b.number),chapters=all.filter(c=>!archived.has(c.id));
  const trash=new Map();for(const event of workspace.chapter_trash_events||[])trash.set(event.chapter_id,event.kind);
  const archivedList=all.filter(c=>archived.has(c.id)&&trash.get(c.id)!=='trash');
  if (!chapters.length) return '<div class="empty-state"><h2>第一章，从这里开始</h2><p>可以直接导入 TXT/Markdown，或新建章节后分别记录 IDEA、细纲和正文。</p><button class="primary" data-create="chapter">＋ 新建章节</button><button id="open-import-export" type="button">TXT/MD 导入与导出</button></div>'+(archivedList.length?archivedPanel(archivedList):'');
  const chapter = chapters.find(item => item.id === selectedChapter) || chapters[0];
  const outline = workspace.document.chapter_outlines.find(item => item.chapter_id === chapter.id) || {};
  const toolbar = `<div class="chapter-toolbar chapter-writing-toolbar"><div class="field"><label for="chapter-select">当前章节</label><select id="chapter-select" data-passive>${chapters.map(item => `<option value="${item.id}" ${item.id === chapter.id ? 'selected' : ''}>第 ${item.number} 章 · ${escapeHTML(item.title)}</option>`).join('')}</select></div><button data-create="chapter">＋ 新建章节</button><button id="move-chapter-up" type="button">上移</button><button id="move-chapter-down" type="button">下移</button><button id="archive-chapter" type="button">归档本章</button><button id="open-import-export" type="button">TXT/MD 导入与导出</button><button id="open-chapter-planning" type="button" title="AI 只生成章节 IDEA 或细纲候选；采纳前不写正文。">AI 章节构思</button><button id="jump-body-protection" type="button">正文选区锁 / 解锁</button><button id="open-scene-expansion" type="button" title="按已采纳场景或正文选区扩写；范围外原文保持不变。">AI 场景/选区扩写</button><button id="start-draft" type="button" title="仅用于已保存空正文；已有正文请续写或改写。" ${chapter.content!==''?'disabled':''}>写初稿</button><button id="start-continuation" type="button" title="只追加新增文字，保留已保存原稿全部前缀。" ${chapter.content.trim()?'':'disabled'}>续写</button><button id="open-context-preview" type="button">预览已保存上下文</button><button id="open-generation-tasks" type="button">任务与候选</button><button id="open-workflows" type="button">工作流与人工节点</button><button id="open-comparisons" type="button">同题盲评比较</button><button id="open-extensions" type="button">受控数据模板</button><button id="open-model-prepare" type="button">模型任务（需单次确认）</button><button id="open-knowledge" type="button">图谱与反馈</button><button id="open-offline-review" type="button">离线审核与查重</button></div>`;
  const subtabs = '<div class="subtabs">' + [['body', '正文'], ['idea', 'IDEA'], ['outline', '章节细纲']].map(([id, title]) => `<button data-pane="${id}" class="${writingPane === id ? 'active' : ''}">${title}</button>`).join('') + '</div>';
  let form;
  const idField = `<input type="hidden" name="chapter_id" value="${chapter.id}">`;
  if (writingPane === 'idea') {
    form = panelForm('save_idea', '留下本章的灵感', '一句话、一个场景或一段对话，都可以先记录在这里。', idField + field('content', '本章 IDEA', workspace.ideas[chapter.id] || '', true, false, 'edit', 'tall'), '保存 IDEA');
  } else if (writingPane === 'outline') {
    const people=`<div class="field"><label for="outline-people">本章参与人物</label><input type="hidden" name="character_ids" data-structured value="${escapeHTML(JSON.stringify(outline.character_ids||[]))}"><select id="outline-people" data-reference-list="character_ids" multiple size="4">${workspace.document.characters.map(c=>`<option value="${escapeHTML(c.id)}" ${(outline.character_ids||[]).includes(c.id)?'selected':''}>${escapeHTML(c.name)}</option>`).join('')}</select></div>`;
    form = panelForm('save_chapter_outline', '把想法整理成细纲', '说明这一章发生什么，以及它在全书中的作用。', idField + field('core_idea', '核心情节', outline.core_idea, true) + field('objective', '本章目标', outline.objective, true) + field('story_time', '剧情时间', outline.story_time)+people+planningEditor('scenes','章内场景计划',outline.scenes||[],workspace), '保存章节细纲');
  } else {
    const status = `<div class="field"><label for="chapter-status">正文状态</label><select id="chapter-status" name="status"><option value="draft" ${chapter.status === 'draft' ? 'selected' : ''}>草稿</option><option value="confirmed" ${chapter.status === 'confirmed' ? 'selected' : ''}>已确认</option></select></div>`;
    const authorization = chapter.status === 'confirmed' ? '<label class="check-label"><input type="checkbox" name="authorize_confirmed" required>我确认修改这章正式内容，并保留此前版本。</label>' : '';
    form = panelForm('save_chapter', '写下这一章', '每次保存都会追加版本。正文中的换行与空格会原样保留。', idField + field('title', '标题', chapter.title, false, true) + field('content', '正文', chapter.content, true, false, 'edit', 'body-editor') + status + authorization, '保存正文');
  }
  return toolbar + subtabs + `<div class="editor-grid">${form}<p class="hint">手动写作始终可用；模型任务须开启会话并单次确认</p></div>`+(archivedList.length?archivedPanel(archivedList):'');
}

export function archivedChapterIds(workspace){
  const latest=new Map();
  for(const event of workspace.chapter_lifecycle_events||[])latest.set(event.chapter_id,event.kind);
  const trash=new Map();for(const event of workspace.chapter_trash_events||[])trash.set(event.chapter_id,event.kind);
  for(const [id,kind] of trash)if(kind==='trash')latest.set(id,'archive');
  return new Set([...latest].filter(([,kind])=>kind==='archive').map(([id])=>id));
}
function archivedPanel(chapters){
  return `<details id="archived-chapters" class="panel"><summary>归档章节（${chapters.length}）</summary><p class="hint">归档章默认隐藏，正文、版本、细纲、IDEA 与任务历史保留；可直接恢复。</p>${chapters.map(c=>`<div class="archived-chapter"><span>第 ${c.number} 章 · ${escapeHTML(c.title)}</span><button type="button" data-restore-chapter="${c.id}">恢复</button></div>`).join('')}</details>`;
}


export function renderCharacters(workspace, selectedCharacter) {
  const characters = workspace.document.characters;
  if (!characters.length) return '<div class="empty-state"><h2>认识故事里的人</h2><p>记录人物的身份、性格和背景，让后续创作有据可查。</p><button class="primary" data-create="character">＋ 新建人物</button></div>';
  const character = characters.find(item => item.id === selectedCharacter) || characters[0];
  return `<div class="chapter-toolbar"><div class="field"><label for="character-select">当前人物</label><select id="character-select" data-passive>${characters.map(item => `<option value="${item.id}" ${item.id === character.id ? 'selected' : ''}>${escapeHTML(item.name)}</option>`).join('')}</select></div><button data-create="character">＋ 新建人物</button></div>` +
    panelForm('save_character', '人物设定', '改名不会改变人物编号，历史设定随版本保留。', `<input type="hidden" name="character_id" value="${character.id}">` + '<div class="field-grid">' + field('name', '人物姓名', character.name, false, true) + field('role', '身份与作用', character.role) + '</div>' + field('personality', '性格', character.personality, true) + field('background', '背景经历', character.background, true) + field('notes', '其他设定', character.notes, true)+planningEditor('goals','人物目标',character.goals,workspace)+planningEditor('relationships','人物关系',character.relationships,workspace), '保存人物');
}

export function renderPreview(workspace,selectedChapter,searchSelections=[]) {
  const archived=archivedChapterIds(workspace);const options=[...workspace.document.chapters].sort((a,b)=>a.number-b.number).filter(c=>!archived.has(c.id)).map(c=>`<option value="${escapeHTML(c.id)}" ${c.id===selectedChapter?'selected':''}>第${c.number}章 · ${escapeHTML(c.title)}</option>`).join('');
  const flags=[['include_current_plan','包含本章细纲、场景与IDEA（创作计划）'],['include_book_outline','包含全书大纲（可能包含未来主线与结局）'],['include_characters','包含本书全部人物完整设定（可能包含未来目标与关系）'],['include_worldbuilding','包含世界观（无故事位置，可能包含未来设定）'],['include_writing_rules','包含文风规则（无故事位置）'],['include_memories','包含已确认且来源未变的本书记忆（按故事位置）'],['include_automatic_memories','自动选用已确认正文事实（需先在记忆页明确启用策略）'],['include_memory_rollups','启用已保存汇总：按范围选用、去重，整条来源预算不足则排除（默认关闭）'],['include_search_results',`包含明确选定的检索来源（${searchSelections.length}项，服务器重新核对）`]];
  return `<section class="panel"><h2>只读上下文预览</h2><p>当前书：${escapeHTML(workspace.document.project.title)}。仅读取服务器已保存资料；未发送模型，不修改正文。默认不选无故事位置的资料，无法自动识别自然语言剧透。</p><form id="context-preview-form"><input type="hidden" name="search_selections" data-structured value="${escapeHTML(JSON.stringify(searchSelections))}"><div class="field"><label for="preview-chapter">写作章节</label><select id="preview-chapter" name="chapter_id">${options}</select></div><div class="field"><label for="preview-scope">正文范围</label><select id="preview-scope" name="scope"><option value="previous">仅当前章之前的已保存正文（最近优先）</option><option value="through_current">包含当前章已保存正文，仍排除后续章</option></select></div><div class="field"><label for="preview-budget">资料字符上限</label><input id="preview-budget" name="budget_chars" type="number" min="128" max="20000" value="6000"></div>${flags.map(([name,label])=>`<label class="check-label"><input type="checkbox" name="${name}" ${(name==='include_search_results'&&searchSelections.length)||(name==='include_automatic_memories'&&memoryAutomationPolicy(workspace).auto_select)?'checked':''}>${label}</label>`).join('')}<p class="hint">本章计划是作者显式选入的创作意图，不代表已发生；完整人物资料选入本书全部人物。字符预算含资料串标题、分隔换行，不是精确token数。未保存草稿、其它书、Skills及API凭据均不读取。</p><button type="submit" class="primary">生成只读预览</button></form><p id="context-preview-status" role="status">请选择来源范围后生成预览。</p><pre id="context-preview-text" class="context-text"></pre><section class="panel"><h3>准备整章改写任务</h3><p class="hint">本章改写的本地协议验证入口；真实模型任务从章节页单独进入。</p><div class="field"><label for="task-instruction">整章改写要求</label><textarea id="task-instruction" maxlength="4000" data-passive></textarea></div><button id="prepare-local-task" type="button" disabled>准备整章改写任务</button><button id="open-generation-tasks" type="button">任务与候选</button><p id="task-prepare-result" role="status"></p></section><h3>来源与选入/排除说明</h3><pre id="context-preview-sources" class="context-text"></pre><details><summary>来源、版本、选入/排除及裁剪报告</summary><pre id="context-preview-report" class="path-display"></pre></details></section>`;
}

export const memoryKindLabels={book_summary:'全书摘要',volume_summary:'分卷摘要',chapter_summary:'章节摘要',character_state:'人物状态',event:'事件',foreshadow:'伏笔',payoff:'回收'};
export function renderMemories(workspace,entries,selectedMemory,selectedChapter,rollupData=null,rollupForm=null,rollupPreview=null) {
  const m=selectedMemory==='new'?null:(entries.find(item=>item.id===selectedMemory)||entries[0]||null);
  const options=(items,value,placeholder='请选择')=>`<option value="">${placeholder}</option>`+items.map(i=>`<option value="${escapeHTML(i.id)}" ${i.id===value?'selected':''}>${escapeHTML(i.label)}</option>`).join('');
  const chapters=activeChapters(workspace).map(c=>({id:c.id,label:`第${c.number}章 ${c.title}`}));
  const sourceOptions=chapters.map(c=>({value:{kind:'chapter',entity_id:c.id},label:'正文 · '+c.label}));
  sourceOptions.push(...chapters.map(c=>({value:{kind:'idea',entity_id:c.id},label:'IDEA · '+c.label})));
  for(const c of workspace.document.characters)sourceOptions.push({value:{kind:'character',entity_id:c.id},label:'人物 · '+c.name});
  for(const o of workspace.document.chapter_outlines)sourceOptions.push({value:{kind:'chapter_outline',entity_id:o.id},label:'细纲 · '+(chapters.find(c=>c.id===o.chapter_id)?.label||o.chapter_id)});
  if(workspace.document.book_outline)sourceOptions.push({value:{kind:'book_outline',entity_id:workspace.document.book_outline.id},label:'全书大纲'});
  for(const [kind,label]of[['project','项目资料'],['worldbuilding','世界观'],['writing_rules','文风规则']])sourceOptions.push({value:{kind,entity_id:workspace.document.project.id},label});
  const selectedSource=m?{kind:m.source.kind,entity_id:m.source.entity_id}:{kind:'chapter',entity_id:selectedChapter||chapters[0]?.id};
  const status=m?`${m.active?'启用':'已归档'} · ${m.confirmed?'作者已确认':'未确认'} · ${m.outdated?'来源已过期，复核前不作为事实':'来源未变'} · 记忆第${m.revision}版`:'新记忆尚未保存';
  const toolbar=`<div class="chapter-toolbar"><div class="field"><label for="memory-select">当前记忆</label><select id="memory-select" data-passive><option value="new" ${!m?'selected':''}>新增记忆</option>${entries.map(i=>`<option value="${escapeHTML(i.id)}" ${m?.id===i.id?'selected':''}>${escapeHTML(i.title)}${i.active?'':'（已归档）'}</option>`).join('')}</select></div><button id="new-memory" type="button">新增手动记忆</button><button id="open-local-search" type="button">本地字面检索</button></div><p id="memory-freshness" role="status">${escapeHTML(status)}</p>`;
  const body=`${m?`<input type="hidden" name="memory_id" value="${escapeHTML(m.id)}">`:''}<div class="field"><label for="memory-kind">记忆分类</label><select id="memory-kind" name="kind">${Object.entries(memoryKindLabels).map(([id,label])=>`<option value="${id}" ${(m?.kind||'chapter_summary')===id?'selected':''}>${label}</option>`).join('')}</select></div>`+
    field('title','记忆标题',m?.title||'',false,true)+field('text','记忆正文',m?.text||'',true)+
    `<div class="field"><label for="memory-position">适用故事位置</label><select id="memory-position" name="position_chapter_id">${options(chapters,m?.position_chapter_id||selectedChapter)}</select></div>`+
    `<div class="field"><label for="memory-volume">适用分卷（可选）</label><select id="memory-volume" name="volume_number" data-structured><option value="null">无</option>${(workspace.document.book_outline?.volumes||[]).map(v=>`<option value="${v.number}" ${v.number===m?.volume_number?'selected':''}>${escapeHTML(v.title)}</option>`).join('')}</select></div>`+
    `<div class="field"><label for="memory-character">关联人物（可选）</label><select id="memory-character" name="character_id" data-structured><option value="null">无</option>${workspace.document.characters.map(c=>`<option value="${escapeHTML(JSON.stringify(c.id))}" ${c.id===m?.character_id?'selected':''}>${escapeHTML(c.name)}</option>`).join('')}</select></div>`+
    `<div class="field"><label for="memory-source">来源对象</label><select id="memory-source" name="source" data-structured ${m?'disabled':''}>${sourceOptions.map(s=>`<option value="${escapeHTML(JSON.stringify(s.value))}" ${s.value.kind===selectedSource.kind&&s.value.entity_id===selectedSource.entity_id?'selected':''}>${escapeHTML(s.label)}</option>`).join('')}</select></div>`+
    `<label class="check-label"><input name="confirmed" type="checkbox" ${m?.confirmed?'checked':''}>作者已确认</label><label class="check-label"><input name="active" type="checkbox" ${m?.active===false?'':'checked'}>启用此记忆</label><p class="hint">只记录作者输入，不提取或猜测。确认与来源新鲜度分开；保存纠正不更新出处，正文改写/恢复后须显式复核。来源固定到已保存版本或revision+字段指纹。</p>`;
  const actions=m?`<div class="chapter-toolbar"><button id="review-memory" type="button">复核来源并更新确认</button><button id="archive-memory" type="button">归档记忆</button><button id="show-memory-source" type="button">查看固定来源</button></div><pre id="memory-source-result" class="context-text"></pre><details><summary>不可变编辑历史</summary><pre class="context-text">${escapeHTML(JSON.stringify((workspace.memory_history||[]).filter(h=>h.memory_id===m.id),null,2))}</pre></details>`:'';
  const volumes=workspace.document.book_outline?.volumes||[];
  const scope=rollupForm?.scope||'book',volumeNumber=rollupForm?.scope_volume_number??volumes[0]?.number??null,through=rollupForm?.through_chapter_id||selectedChapter||chapters[0]?.id||'';
  const chapterLabel=id=>chapters.find(c=>c.id===id)?.label||id;
  const rollupRows=(rollupData?.rollups||[]).map(item=>`<article class="context-card"><h4>${escapeHTML(item.title)} ${item.stale?'<span class="badge planned">来源已变化</span>':'<span class="badge ready">来源未变</span>'}</h4><p>${item.scope==='book'?'全书':item.scope==='chapter'?'独立单章':`第${item.scope_volume_number}卷`} · 截至 ${escapeHTML(chapterLabel(item.through_chapter_id))} · 汇总第${item.revision}版 · ${item.sources.length} 条来源</p><details><summary>查看汇总正文与来源</summary><pre class="context-text">${escapeHTML(item.text)}</pre><p class="path-display">${escapeHTML(item.sources.map(source=>`${source.memory_id} · 第${source.memory_revision}版`).join('\n'))}</p></details>${item.unavailable_reason?`<p class="error">${escapeHTML(item.unavailable_reason)}</p>`:''}<details data-rollup-history="${escapeHTML(item.id)}"><summary>不可变汇总历史与章节来源</summary><pre class="context-text">${escapeHTML(JSON.stringify((workspace.memory_rollup_history||[]).filter(v=>v.rollup_id===item.id),null,2))}</pre></details><button type="button" ${item.available===false?'disabled':''} data-rollup-rebuild="${escapeHTML(item.id)}" data-rollup-revision="${item.revision}">按当前记忆显式重建</button></article>`).join('');
  const conflicts=rollupData?.conflicts||[];
  const conflictRows=conflicts.map((conflict,index)=>`<article class="context-card" id="memory-conflict-${index}"><h4>${escapeHTML(memoryKindLabels[conflict.kind]||conflict.kind)} · ${escapeHTML(conflict.title)}</h4><p>${escapeHTML(chapterLabel(conflict.position_chapter_id))} · 同一人物/分卷/位置/标题下有 ${conflict.memory_ids.length} 条不同正文。请逐条核对后修改或归档原记忆；系统不会自动合并。</p>${conflict.texts.map(text=>`<div class="memory-conflict-text"><p>${escapeHTML(text.text)}</p><button type="button" data-memory-jump="${escapeHTML(text.memory_id)}">跳到原记忆</button></div>`).join('')}</article>`).join('');
  const previewLabel=rollupPreview?.existing?(rollupPreview.existing.stale?'已保存汇总的来源已变化，预览可显式重建':'已存在同范围汇总，保存会显式重建'):'只读预览，尚未保存';
  const rollupPanel=`<section class="panel" id="memory-rollups"><h2>分层记忆汇总</h2><p class="hint">只汇总当前已启用、作者已确认、来源未变且不晚于所选故事位置的记忆。独立单章只选有效位置恰在该章的记忆，不包含前章或未来章；章节正文或来源变化会标记过期。正文按位置、分类、标题稳定排序并保留原文；不调用模型，不会自动覆盖。存在同位置同标题的不同正文时阻止保存。</p><form id="memory-rollup-form"><div class="field-grid"><div class="field"><label for="rollup-scope">汇总范围</label><select id="rollup-scope" data-passive><option value="book" ${scope==='book'?'selected':''}>全书</option><option value="volume" ${scope==='volume'?'selected':''}>单卷</option><option value="chapter" ${scope==='chapter'?'selected':''}>独立单章（仅此章有效位置）</option></select></div><div class="field"><label for="rollup-volume">分卷（选择单卷时）</label><select id="rollup-volume" data-structureless data-passive><option value="">未选择</option>${volumes.map(v=>`<option value="${v.number}" ${v.number===volumeNumber?'selected':''}>${escapeHTML(v.title)}</option>`).join('')}</select></div><div class="field"><label for="rollup-through">截至故事位置</label><select id="rollup-through" data-passive>${chapters.map(c=>`<option value="${escapeHTML(c.id)}" ${c.id===through?'selected':''}>${escapeHTML(c.label)}</option>`).join('')}</select></div></div><button id="preview-memory-rollup" type="button">只读预览汇总</button></form><p id="rollup-status" role="status">${rollupPreview?escapeHTML(rollupPreview.can_save?previewLabel:`${previewLabel}；仍有 ${rollupPreview.conflicts.length} 组冲突，不能保存`):'尚未生成预览。'}</p>${rollupPreview?`<pre id="rollup-preview-text" class="context-text">${escapeHTML(rollupPreview.text)}</pre><details><summary>预览来源（${rollupPreview.sources.length}）</summary><pre class="context-text">${escapeHTML(rollupPreview.sources.map(source=>`${source.memory_id} · 第${source.memory_revision}版 · ${source.position_chapter_id}`).join('\n'))}</pre></details><button id="save-memory-rollup" type="button" class="primary" ${rollupPreview.can_save?'':'disabled'}>${rollupPreview.existing?'显式重建已保存汇总':'保存为新汇总'}</button>`:''}<h3>已保存汇总（${(rollupData?.rollups||[]).length}）</h3>${rollupRows||'<p class="hint">尚无已保存的分层汇总。</p>'}</section><section class="panel" id="memory-conflicts"><h3>记忆冲突报告（${conflicts.length}）</h3><p class="hint">同分类、同人物、同分卷、同位置且同标题，但正文不同。这里只报告，不自动改正文或合并记忆。</p>${conflictRows||'<p class="hint">当前没有未解决的同位置差异记忆。</p>'}</section>`;
  return toolbar+renderMemoryAutomation(workspace,escapeHTML)+panelForm('save_memory','手动长篇记忆','摘要、人物状态、事件与伏笔/回收均由作者核实；归档不删历史。模型摘要只成为待核实提案。',body,'保存记忆')+actions+rollupPanel;
}

export function renderRetrieval(workspace,chapterId,skills,materialListing=null) {
  const scopes=[['body','本书正文'],['memories','本书记忆（结果会标确认/过期）'],['planning','全书规划/细纲（可能含未来设定）'],['characters','人物完整设定（可能含未来设定）'],['worldbuilding','世界观（无故事位置）'],['writing_rules','文风规则（无故事位置）'],['materials','明确选择的本地资料（字面扫描）'],['skills','明确选择的全局Skills']];
  const materials=(materialListing?.materials||[]).filter(value=>!value.archived);
  return `<section class="panel"><h2>本地字面与混合检索</h2><p>当前书：${escapeHTML(workspace.document.project.title)}。区分大小写的字面扫描，不是语义检索，不读取草稿或调用模型。本地资料不会被自动选中，也不会自动进入模型上下文。</p><form id="local-search-form"><div class="field"><label for="search-mode">检索方法</label><select id="search-mode" name="mode"><option value="literal">原文字面（区分大小写）</option><option value="hybrid">字面混合：Unicode / BM25 / 短语融合（不是语义检索）</option></select></div>${field('query','检索词','',false,true,'search')}<div class="field"><label for="search-position">检索故事位置</label><select id="search-position" name="chapter_id">${activeChapters(workspace).map(c=>`<option value="${escapeHTML(c.id)}" ${c.id===chapterId?'selected':''}>第${c.number}章 ${escapeHTML(c.title)}</option>`).join('')}</select></div>${scopes.map(([id,label])=>`<label class="check-label"><input type="checkbox" name="scope_${id}" ${['body','memories'].includes(id)?'checked':''}>${label}</label>`).join('')}<div class="field"><label for="search-materials">本地资料选择（必须明确勾选；只检索已重建的当前版本）</label><select id="search-materials" name="material_ids" multiple size="4">${materials.map(value=>`<option value="${escapeHTML(value.id)}">${escapeHTML(value.title)} · 第${value.current_version_number}版 · ${escapeHTML(value.index_status)}</option>`).join('')}</select>${materials.length?'':'<p class="hint">当前没有启用的本地资料；请先在“本地资料”页创建并重建索引。</p>'}</div><div class="field"><label for="search-skills">全局Skills选择</label><select id="search-skills" name="skill_ids" multiple size="3">${skills.map(s=>`<option value="${escapeHTML(s.id)}">${escapeHTML(s.name)}</option>`).join('')}</select></div><label class="check-label"><input name="whole_book" type="checkbox">全书检索（显式包含后续章；上下文仍会重新过滤）</label><button type="submit" class="primary">检索已保存资料</button></form><p id="local-search-status" role="status">请选择范围；默认排除后续章，自由资料需主动选入。资料命中只按固定字符窗口定位，不代表语义相关。</p><div id="local-search-results"></div><button id="preview-search-selection" type="button">预览已选资料</button><button data-view="memory" type="button">返回长篇记忆</button><button data-view="materials" type="button">管理本地资料</button></section>`;
}

export const taskStatusLabels={pending:'待执行',running:'执行中',succeeded:'成功',failed:'失败',cancelled:'已取消',interrupted:'中断（不自动重跑）'};
export function renderTaskPanel(workspace,listing,capabilities,selectedTask) {
  const view=listing.tasks.find(v=>v.task.id===selectedTask)||listing.tasks.at(-1);
  const analysis=view?.task.task_type==='audit_chapter';
  const mode=`<p id="task-mode" class="hint">${analysis?'实际离线字面/结构时间规则，不是语义或因果模型，不发外部请求。':capabilities.local_protocol_demo?'明确启用：本地协议验证夹具，不是真实AI输出，无真实token/费用。':'真实模型关闭；本地协议执行也未启用。仅显式--local-protocol-demo可注册本地adapter。'}</p>`;
  const list=`<div class="field"><label for="task-select">当前任务</label><select id="task-select" data-passive>${listing.tasks.map(v=>`<option value="${escapeHTML(v.task.id)}" ${v===view?'selected':''}>第${v.task.frozen.target.number}章 · ${taskStatusLabels[v.display_status]} · ${escapeHTML(v.task.id)}</option>`).join('')}</select></div>`;
  if(!view)return `<section class="panel"><h2>整章任务与候选</h2>${mode}<p>当前没有任务。请从章节写作生成已保存上下文预览，再明确准备整章改写任务。</p></section>`;
  const task=view.task,candidate=view.candidates[0],receipt=view.receipts[0];
  return `<section class="panel"><h2>整章任务与候选</h2>${mode}${list}<p id="task-status" role="status">状态：${taskStatusLabels[view.display_status]} · 保存编号 ${view.revision}${task.error_code?' · '+escapeHTML(task.error_code):''}</p><div class="chapter-toolbar"><button id="execute-local-task" type="button" ${task.status==='pending'&&(analysis?capabilities.offline_audit_enabled:capabilities.local_protocol_demo)?'':'disabled'}>${analysis?'执行离线规则审核':'执行本地协议验证'}</button><button id="cancel-generation-task" type="button" ${['pending','running'].includes(task.status)?'':'disabled'}>取消任务</button><button id="refresh-generation-task" type="button">刷新任务状态</button>${view.display_status==='interrupted'&&task.status==='running'?'<button id="recover-generation-tasks" type="button">明确将中断落盘（不重跑）</button>':''}</div><p class="hint">只显式执行一次，不自动重试。读取/导入不执行任务，失去本会话执行归属时仅显示中断；明确核对后才写中断事件。</p>${view.reports?.length?'<button id="open-review-report" type="button">查看审核报告</button>':''}<h3>冻结原稿</h3><pre id="task-original" class="context-text">${escapeHTML(task.frozen.target.text)}</pre>${candidate?`<h3>完成候选 · 本地协议夹具</h3><pre id="task-candidate" class="context-text">${escapeHTML(candidate.output_text)}</pre><h3>原稿 → 候选差异</h3><pre id="task-candidate-diff" class="context-text"></pre>${task.frozen.target.status==='confirmed'?'<label class="check-label"><input id="task-authorize-confirmed" type="checkbox">我确认修改已确认章节，并保留旧版本。</label>':''}<p class="hint">采纳时在同一事务重新核对最新目标/相关依赖和保存编号；不会自动重新确认记忆。</p><button id="adopt-generation-candidate" type="button" ${receipt?'disabled':''}>明确采纳候选为新草稿</button>`:'<p>未完成、失败、取消或中断输出不是候选。</p>'}<p id="task-adoption-result" role="status">${receipt?'采纳已核对 · 保存编号 '+receipt.applied_revision+' · 正文版本 '+escapeHTML(receipt.version_after):''}</p><details><summary>冻结输入、来源/参数和实际事件</summary><pre id="task-frozen" class="context-text">${escapeHTML(JSON.stringify(task.frozen,null,2))}</pre><pre class="context-text">${escapeHTML(JSON.stringify(view.events,null,2))}</pre></details></section>`;
}

export function renderReviewPanel(workspace,listing,detail,selectedChapter) {
  const options=activeChapters(workspace).map(c=>`<option value="${escapeHTML(c.id)}" ${c.id===selectedChapter?'selected':''}>第${c.number}章 ${escapeHTML(c.title)}</option>`).join('');
  const form=`<section class="panel"><h2>离线审核与基础查重</h2><p>仅所选已保存章节与可选场景时间规划。明确时间、字面规则、精确/基础近似，不是语义/因果或全网模型；不改正文。</p><form id="audit-prepare-form"><div class="field"><label for="audit-chapters">审核章节范围</label><select id="audit-chapters" name="selected_chapter_ids" multiple size="5">${options}</select></div>${field('forbidden','禁用字面串（每行一条）','',true,false,'audit')}${field('required','必需字面串（每行一条）','',true,false,'audit')}<div class="field"><label for="audit-normalization">查重归一规则</label><select id="audit-normalization" name="normalization"><option value="whitespace">移除空白，保留大小写/标点</option><option value="punctuation">移除空白和Unicode标点，保留大小写</option></select></div><div class="field"><label for="audit-threshold">基础近似阈值</label><input id="audit-threshold" name="near_threshold" type="number" min="0.65" max="1" step="0.01" value="0.85"></div><label class="check-label"><input name="check_timeline" type="checkbox" checked>检查显式第N天/ISO日期的场景时间顺序（规划不是已发生事实）</label><label class="check-label"><input name="include_memories" type="checkbox">冻结有效已确认记忆作为参考（不从自由文本推断事实）</label><p class="hint">若从字面检索选入了全局Skills，可勾选下面来源参考；仍会重新核对，默认不会擅自读取全局资料。</p><label class="check-label"><input name="include_search_results" type="checkbox">冻结此前明确选定的检索来源作为参考</label><button type="submit" class="primary">冻结并准备离线审核</button></form><p id="audit-prepare-status" role="status"></p></section>`;
  const list=`<section class="panel"><div class="field"><label for="review-report-select">已保存审核报告</label><select id="review-report-select" data-passive>${listing.reports.map(r=>`<option value="${escapeHTML(r.id)}" ${r.id===detail?.report.id?'selected':''}>离线审核 · ${escapeHTML(r.id)}</option>`).join('')}</select></div><button id="refresh-review-state" type="button">刷新审核状态</button>${detail?'<button id="reprepare-review" type="button">准备复审（新报告，保留原记录）</button>':''}</section>`;
  if(!detail)return form+list;
  const names={forbidden_literal:'禁用字面串',missing_literal:'缺少必需字面串',timeline_order:'显式时间倒序',duplicate_exact:'精确重复',duplicate_near:'基础近似重复'};
  const findings=detail.issues.map((issue,index)=>`<article class="context-card" data-review-rule="${issue.finding.rule_id}"><h3>${names[issue.finding.rule_id]}</h3>${(()=>{const r=detail.rechecks?.find(r=>r.issue_id===issue.id);return r?`<p>复审：${{still_found:'仍命中',not_found:'本次未检出（不等于已解决）',unverified:'无法判定'}[r.status]} · ${escapeHTML(r.reason)}</p><pre class="context-text">${escapeHTML(JSON.stringify(r.source_changes,null,2))}</pre><button type="button" data-open-review="${escapeHTML(r.new_report_id)}">查看新复审证据</button>`:'<p>尚无新复审记录；没有手动“已解决”按钮。</p>';})()}<p>处理状态：${escapeHTML(issue.status)} · ${escapeHTML(issue.finding.message)}${issue.finding.score===null?'':' · 相似度 '+issue.finding.score.toFixed(3)}</p>${issue.finding.evidence.map((e,side)=>`<p>侧${side+1} · ${escapeHTML(e.source_kind)} · ${escapeHTML(e.entity_id)} · ${escapeHTML(e.field_path)} · 原字符${e.start}–${e.end} · 版本 ${escapeHTML(e.version_id||'工作区'+e.source_revision)}</p><pre class="context-text">${escapeHTML(e.quote||'（所选来源中没有匹配字面串；非全书/语义不存在结论）')}</pre><button type="button" data-review-jump="${index}:${side}">跳到证据出处</button>`).join('')}<div class="field"><label>处理理由<textarea data-review-reason></textarea></label></div><label class="check-label"><input type="checkbox" data-review-whitelist>将确切双侧原文与规则加入白名单</label><button type="button" data-review-action="acknowledge" data-review-issue="${index}">确认问题</button><button type="button" data-review-action="false_positive" data-review-issue="${index}">标为误报</button><button type="button" data-review-action="waive" data-review-issue="${index}">明确豁免</button><button type="button" data-review-action="reopen" data-review-issue="${index}">重开处理状态</button></article>`).join('');
  const proposals=detail.proposals.map((p,index)=>`<article class="context-card" data-memory-proposal><h3>${escapeHTML(p.proposal.title)}</h3><p>仅原文摘录，不是AI摘要/规划事实。状态 ${p.receipt?escapeHTML(p.receipt.decision):'待作者决定'}</p><pre class="context-text">${escapeHTML(p.proposal.text)}</pre><p>来源 ${escapeHTML(p.proposal.evidence.entity_id)} · 版本 ${escapeHTML(p.proposal.evidence.version_id||'工作区'+p.proposal.evidence.source_revision)}</p>${p.conflicts.map(m=>`<p>已有不同记忆 ${escapeHTML(m.title)}（将保留）</p><pre class="context-text">${escapeHTML(m.text)}</pre>`).join('')}<label class="check-label"><input type="checkbox" data-proposal-conflicts>确认并保留现有不同记忆</label><button type="button" data-proposal-decision="accepted" data-proposal-index="${index}" ${p.receipt||detail.outdated?'disabled':''}>接受并确认摘录为新记忆</button><button type="button" data-proposal-decision="rejected" data-proposal-index="${index}" ${p.receipt?'disabled':''}>拒绝提案</button></article>`).join('');
  const waivers=detail.waivers.map(w=>`<article class="context-card"><p>白名单 · ${escapeHTML(w.reason)} · ${escapeHTML(w.rule_id)}</p><button type="button" data-revoke-waiver="${escapeHTML(w.id)}">停用此白名单</button></article>`).join('');
  return form+list+`<section class="panel"><h2>审核报告</h2><p id="review-report-status" role="status">${detail.outdated?'来源已过期：请重新审核后接受':'来源未变'} · 保存编号 ${detail.revision} · ${detail.report.limited?'达到计算上限，未声称完整比对':'所选范围规则已运行'}</p><p>${detail.report.limitations.map(escapeHTML).join(' ')}</p><p id="review-operation-status" role="status"></p><div id="review-findings">${findings||'<p>当前规则/所选范围没有问题，不是全书语义无错证明。</p>'}</div><h3>原文记忆摘录提案</h3>${proposals||'<p>没有可用原文摘录。</p>'}<h3>白名单与反馈</h3>${waivers}<details><summary>冻结来源与规则快照</summary><pre class="context-text">${escapeHTML(JSON.stringify(detail.parameters,null,2))}</pre></details></section>`;
}


export function activeChapters(workspace){const hidden=archivedChapterIds(workspace);return workspace.document.chapters.filter(c=>!hidden.has(c.id));}




