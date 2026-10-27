import {activeChapters} from './views.js';
import {renderAnnotations,bindAnnotations,stopAnnotations,annotationsDirty,annotationsMayLeave} from './annotations.js';
import {renderAgentChat,renderAgentSettings,bindAgentPage,sendAgentMessage,changeEntity,syncAgentControls,resetAgentView,hasPendingAttachments,attachmentsUploading,importLocalPath} from './chat_workspace.js';
import {renderChapterWritingPrepare,bindChapterWritingPrepare,renderChapterWritingTask,bindChapterWritingTask,useChapterWritingInput} from './chapter_writing.js';
import {renderChapterPlanningPrepare,bindChapterPlanningPrepare,renderChapterPlanningTask,bindChapterPlanningTask} from './chapter_planning.js';
import {renderSceneExpansionPrepare,bindSceneExpansionPrepare,renderSceneExpansionTask,bindSceneExpansionTask} from './scene_expansion.js';
import {renderMigration,bindMigration} from './migration.js';
import {renderChapterManagement,bindChapterManagement} from './chapter_management.js';
import {renderProviderManagement,bindProviderManagement} from './provider_management.js';
import {renderConsole,bindConsole,selectedConsoleSession,selectConsoleSession,selectedConsoleRun,selectConsoleRun} from './console.js';
import {renderScopedRules,bindScopedRules} from './rules_scope.js';
import {renderRuleReviews,bindRuleReviews} from './rule_reviews.js';
import {renderSemanticRetrieval,bindSemanticRetrieval} from './semantic_retrieval.js';
import {renderMaterials,bindMaterials} from './materials.js';
import {renderFullBookPlanning,bindFullBookPlanning} from './full_book_planning.js';
import {renderLocalData,bindLocalData} from './local_data.js';
import {renderAuthorScope,bindAuthorScope} from './author_scope.js';


'use strict';
import { api, setToken, downloadFile } from './api.js';
import {t,getLanguage} from './i18n.js';
import {renderCustomProvider,saveCustomProvider,renderModelPurposeGuide,providerDisplayName} from './provider_views.js';
import {renderCreationPresets,bindCreationPresets} from './creation_presets.js';
import {loadStyles,renderStyles,bindStyles,selectStyleSource} from './styles.js';
import {loadPublicSearch,renderPublicSearch,bindPublicSearch} from './public_search.js';
import {loadStyleTrials,renderStyleTrials,bindStyleTrials,selectStyleTrialTask} from './style_trials.js';
import {renderBookCreation,bindBookCreation} from './book_creation.js';
import {renderBookAI,bindBookAI} from './book_ai.js';
import { DraftStore, PromptStore, diffLines } from './state.js';
import { createLayout } from './layout.js';
import {renderKnowledge,bindKnowledge,knowledgeOptions} from './knowledge.js';
import {renderModelPrepare,bindModelPrepare,renderModelTask,renderModelReview,bindModelReview,useGenerationPreset,resetModelPreparation,renderSummaryPrepare,bindSummaryPrepare} from './model_tasks.js';
import {renderComparisonCreate,renderComparison,bindComparison,renderExtensions,bindExtensions} from './comparison_views.js';
import {renderWorkflow,bindWorkflow} from './workflow_views.js';
import { escapeHTML, field, panelForm, textareaValues, renderProject, renderOutline, renderWriting, renderCharacters, formValues, hydratePlanning, changePlanning, renderPreview,renderMemories,renderRetrieval,renderTaskPanel,renderReviewPanel,archivedChapterIds } from './views.js';

const $ = selector => document.querySelector(selector);
let workspace = null, projects = [], view = 'chat', writingPane = 'body';
let shelfScope='active';
let selectedChapter = '', selectedCharacter = '', selectedSkill = '';
let chapterWritingMode='draft',chapterWritingDirty=false;
let chapterPlanningMode='brainstorm',chapterPlanningDirty=false,selectedPlanningTask='',chapterPlanningListing=null,chapterPlanningDetail=null;
let expansionRange=null,selectedExpansionTask='',expansionListing=null,expansionDetail=null,sceneExpansionDirty=false;
let consoleListing=null,consoleDetail=null,consoleRunListing=null,consoleRunDetail=null;
let rulesData=null,ruleResolved=null;
let materialsData=null,materialsDetail=null,materialCurrentVersion=null,selectedMaterial='';
let fullBookPlanningData=null;
let dirty = false, busy = false, createKind = 'project';
let sessionModels=false;
const disabledBeforeRequest = new Map();
const drafts = new DraftStore(), documents = [], activity = [];
let draftsLoadedProject='',draftWriteQueue=Promise.resolve();
const draftStorageFailures=new Set(),draftClearRetries=new Map();
const draftTimers=new Map();
const prompts = new PromptStore();
let unboundPrompt=false;
const pendingProviders = new Set();
const promptProject=()=>unboundPrompt?'':workspace?.document.project.id||'';
const layout = createLayout();
let activeKey = '', baseline = {}, contextView = 'history', composing = false, rendering = 0;
let requestFocus = null;
let diffScheduled = false;
let previewRequest=0;
let taskPreview=null,selectedTask='',taskViewData=null,taskPollTimer=null;
const adoptionIdentities=new Map();
let knowledgeData=null;
let selectedModelReview='',modelReviewDetail=null;
let selectedComparison='',comparisonData=null,comparisonTimer=null,extensionData=null;
let selectedWorkflow='',workflowData=null,stopWorkflowPolling=null;
let creationPresetData=null;
let bookCreationData=null,bookCreationDirty=false;
let bookAiData=null,bookAiCaps=null,bookAiPollTimer=null,bookAiDirty=false;
let styleData=null,styleTimer=null,styleDirty=false;
let publicSearchData=null,publicSearchTimer=null,publicSearchDirty=false;
let styleTrialData=null,styleTrialTimer=null,styleTrialDirty=false;
let selectedReview='',reviewDetail=null;
const reviewIdentities=new Map(),reviewInputDrafts=new Map();
let selectedMemory='new',retrievalRequest=0,localSearchResult=null,searchSelections=[];
let summaryCapabilities=null;
let memoryRollupData=null,memoryRollupForm=null,memoryRollupPreview=null,rollupOperationId='';
let pendingBackupOperation='', activeBackupOperation='';
try { pendingBackupOperation=sessionStorage.getItem('novel-writer.backup-operation')||''; } catch {}
function rememberBackupOperation(value) {
  pendingBackupOperation=value;
  try { if(value)sessionStorage.setItem('novel-writer.backup-operation',value);else sessionStorage.removeItem('novel-writer.backup-operation'); } catch {}
}
let pendingMigrationOperation='', activeMigrationOperation='';
try {pendingMigrationOperation=sessionStorage.getItem('novel-writer.migration-operation')||'';} catch {}
function rememberMigrationOperation(value) {
  pendingMigrationOperation=value;
  try {if(value)sessionStorage.setItem('novel-writer.migration-operation',value);else sessionStorage.removeItem('novel-writer.migration-operation');} catch {}
}
const icons = { chat: '↗', writing: '✎', annotations: '✍', project: '▤', outline: '☷', characters: '♙', world: '◇', memory: '◌', history: '↶', rules: '≋', materials: '▣', skills: 'S', guide: '?', modules: '▦', settings: '⚙' };
const tabs = [['chat','创作对话'],['project', '项目资料'], ['outline', '全书大纲'], ['writing', '章节写作'], ['annotations', '正文批注'], ['characters', '人物设定'], ['world', '世界观'], ['memory','长篇记忆'], ['rules', '文风规则'], ['materials','本地资料'], ['history','历史与恢复'], ['settings', '设置'], ['modules', '模块规划'], ['skills', 'Skills'], ['guide', '使用指南']];
const globalViews = ['creation','chat','project','skills','guide','modules','settings','history'];
const moduleNames = {annotations:'正文批注',project:'小说项目与书架',outline:'大纲与分卷规划',writing:'章节与正文编辑',characters:'人物、世界观与记忆',rules:'文风与创作规则',materials:'本地资料与字面索引',history:'历史、备份与恢复',settings:'模型 / API 中心',modules:'审核、图谱与工作流'};

function notify(message, error = false) {
  if(typeof message==='string'&&message.startsWith('creation.')){const [code,name]=message.split(':');message=t(code)+(name?' '+t('creation.field.'+name):'');}
  $('#notification').hidden = false;
  $('#notification').textContent = message;
  $('#notification').classList.toggle('error', error);
  recordActivity(error ? '操作提示 / 错误' : '操作完成', error);
}

function recordActivity(message, error = false) {
  activity.unshift({ time: new Date().toLocaleTimeString(getLanguage()), message, error });
  activity.splice(100);
  $('#activity-log').innerHTML = activity.map(item => `<li class="${item.error ? 'error' : ''}"><time>${item.time}</time> · ${escapeHTML(item.message)}</li>`).join('');
}

function documentKey() {
  return JSON.stringify([workspace?.document.project.id || '', view, view === 'writing' ? selectedChapter : view === 'characters' ? selectedCharacter : view==='memory'?selectedMemory:'', view === 'writing' ? writingPane : '']);
}
function readForm(form = $('#content form[data-action]')) {
  if (!form) return {};
  return formValues(form);
}
function captureDraft() {
  const form = $('#content form[data-action]');
  if (!form || !activeKey || busy) return;
  const values = readForm(form);
  dirty = JSON.stringify(values) !== JSON.stringify(baseline);
  if (dirty) {
    const editor = $('#edit-content');
    drafts.put(activeKey, workspace.document.project.id, workspace.revision, values, { top: $('#content').scrollTop, cursor: editor?.selectionStart, end: editor?.selectionEnd, editorTop: editor?.scrollTop });
    scheduleDraftPersist(activeKey);
  } else { drafts.remove(activeKey); clearDiskDraft(workspace.document.project.id,activeKey); }
  saveIndicator(); renderDocumentTabs(); updateWordCount();
}
function moduleDocuments() {
  const group=id=>['characters','world','memory'].includes(id)?'lore':id;
  return documents.filter(doc=>(doc.project||'')===(workspace?.document.project.id||'')&&group(doc.view)===group(view));
}
function renderDocumentTabs() {
  const strip=$('#document-tabs');
  strip.hidden=view==='chat';
  strip.innerHTML=view==='chat'?'':`<div class="document-tab"><button data-view="chat" aria-label="返回创作对话">创作对话${prompts.get(promptProject()).text?' •':''}</button></div>` + moduleDocuments().map(doc => `<div class="document-tab ${doc.key === activeKey ? 'active' : ''}"><button data-open-tab="${escapeHTML(doc.key)}" aria-label="打开文档 ${escapeHTML(doc.title)}" title="${escapeHTML(doc.title)}">${escapeHTML(doc.title)}${drafts.get(doc.key) ? ' •' : ''}</button><button data-close-tab="${escapeHTML(doc.key)}" aria-label="关闭 ${escapeHTML(doc.title)}">×</button></div>`).join('');
  revealActive('#document-tabs','.active',true);
}
function revealActive(containerSelector, itemSelector, horizontal=false) {
  const container=$(containerSelector),item=container?.querySelector(itemSelector);
  if(!item||!container.getClientRects().length) return;
  const bounds=item.getBoundingClientRect(),area=container.getBoundingClientRect();
  if(horizontal) {
    if(bounds.left<area.left) container.scrollLeft+=bounds.left-area.left;
    else if(bounds.right>area.right) container.scrollLeft+=bounds.right-area.right;
  } else {
    if(bounds.top<area.top) container.scrollTop+=bounds.top-area.top;
    else if(bounds.bottom>area.bottom) container.scrollTop+=bounds.bottom-area.bottom;
  }
}
function focusDocument() {
  const target=(view==='chat'?$('#chat-input'):null)||$('#edit-content')||$('#content form[data-action] input:not([type=hidden])')||$('#content');
  target?.focus({preventScroll:true});
}
function rememberDocument() {
  activeKey = documentKey();
  if(view==='chat') { renderDocumentTabs(); return; }
  if(view==='writing'&&!selectedChapter||view==='characters'&&!selectedCharacter) { renderDocumentTabs();return; }
  let doc = documents.find(item => item.key === activeKey);
  const chapter = workspace?.document.chapters.find(item => item.id === selectedChapter);
  const character = workspace?.document.characters.find(item => item.id === selectedCharacter);
  const name = view === 'writing' && chapter ? `${chapter.title} / ${{body:'正文',idea:'IDEA',outline:'细纲'}[writingPane]}` : view === 'characters' && character ? character.name : tabs.find(item => item[0] === view)?.[1];
  const title = name || '工作台';
  if (!doc) { doc = { key: activeKey }; documents.push(doc); }
  Object.assign(doc, { project: workspace?.document.project.id, view, chapter: selectedChapter, character: selectedCharacter,memory:selectedMemory, pane: writingPane, title });
  renderDocumentTabs();
}
function hydrateDraft() {
  const form = $('#content form[data-action]');
  hydratePlanning(form);
  baseline = readForm(form);
  const draft = drafts.get(activeKey);
  if (form && draft) for (const [name, value] of Object.entries(draft.values)) {
    const element=form.elements.namedItem(name);
    if(element?.multiple)for(const option of element.options)option.selected=JSON.parse(value).includes(option.value);
    else if(element)element.value=value;
  }
  hydratePlanning(form);
  dirty = Boolean(form && draft);
  if (draft?.position) {
    $('#content').scrollTop = draft.position.top || 0;
    const editor = $('#edit-content');
    if (editor) { editor.setSelectionRange(draft.position.cursor || 0, draft.position.end || 0); editor.scrollTop = draft.position.editorTop || 0; }
  } else $('#content').scrollTop = 0;
  const stale = form && draft && draft.baseRevision !== workspace.revision;
  const sensitiveNotice=draft?.sensitiveFieldsRequired?'此草稿中的敏感字段已从备份或复制数据中移除，请手动重新填写。':'';
  $('#draft-review').hidden = !draft || (!stale && !draft.local);
  if (stale) $('#draft-review').innerHTML = `<strong>${draft.local?'本地恢复草稿（未保存） · ':''}草稿基于保存编号 ${draft.baseRevision}，最新为 ${workspace.revision}。请对照后明确选择。</strong>${sensitiveNotice?`<p>${escapeHTML(sensitiveNotice)}</p>`:''}<details open><summary>最新已保存内容 / 当前草稿</summary>${Object.keys(baseline).filter(name => !name.endsWith('_id')).map(name => `<p>${escapeHTML(form.elements.namedItem(name)?.labels?.[0]?.textContent || name)}</p><pre>已保存：${escapeHTML(baseline[name])}</pre><pre>草稿：${escapeHTML(draft.values[name])}</pre>`).join('')}</details><button id="rebase-draft" type="button">保留草稿并绑定最新版本</button> <button id="discard-draft" type="button">放弃本标签草稿</button>`;
  else if(draft?.local) $('#draft-review').innerHTML = `<strong>本地恢复草稿（未保存）</strong><p>基于保存编号 ${draft.baseRevision}，最新为 ${workspace.revision}。草稿尚未写入正文；保存成功后才会清除。</p>${sensitiveNotice?`<p>${escapeHTML(sensitiveNotice)}</p>`:''}<button id="discard-draft" type="button">放弃本地草稿</button>`;
  renderDocumentTabs(); saveIndicator(); updateWordCount();
}
function updateWordCount() {
  const editor = $('#edit-content');
  const text = editor?.value || '';
  $('#word-count').textContent = `${text.replace(/\s/g, '').length} 字`;
  $('#selection-count').textContent = editor && editor.selectionEnd > editor.selectionStart ? `选区 ${editor.selectionEnd - editor.selectionStart} 字` : '';
  const chapter = workspace?.document.chapters.find(item => item.id === selectedChapter);
  $('#console-scope').textContent = workspace ? `当前范围：${workspace.document.project.title}${chapter ? ' / ' + chapter.title : ''}${editor?.selectionEnd > editor?.selectionStart ? ' / 正文选区' : ' / 当前文档'}。内容尚未外发。` : '尚未选择小说。';
}

function saveIndicator() {
  const localDraft=drafts.get(activeKey)?.local===true;
  $('#save-state').textContent = busy ? '正在处理…' : localDraft ? '本地恢复草稿（未保存）' : dirty ? '未保存修改' : workspace ? `已保存 · ${workspace.revision}` : '尚未选择小说';
  $('#save-state').classList.toggle('unsaved', dirty);
  if(draftStorageFailures.size){$('#save-state').textContent+=' · 恢复草稿存储异常（设置中可重试）';$('#save-state').classList.add('unsaved');}
  $('#overview-project').textContent=workspace?.document.project.title||'未绑定小说';
  $('#overview-save').textContent=$('#save-state').textContent;
  $('#overview-chapters').textContent=`${workspace?.document.chapters.length||0} 章 · ${workspace?.document.characters.length||0} 位人物`;
  $('#overview-task').textContent=busy?'正在处理本地读写':'当前窗口空闲';
}

function draftUrl(project){return '/api/projects/'+encodeURIComponent(project)+'/drafts';}
function clearDiskDraft(project,key){
  if(!project||!key)return;
  const failure='clear:'+key;draftClearRetries.set(key,project);
  draftWriteQueue=draftWriteQueue.then(()=>api(draftUrl(project)+'/clear',{method:'POST',body:JSON.stringify({document_key:key})})).then(()=>{draftClearRetries.delete(key);draftStorageFailures.delete(failure);draftStorageFailures.delete('write:'+key);saveIndicator();}).catch(()=>{
    draftClearRetries.set(key,project);
    if(!draftStorageFailures.has(failure))notify('恢复草稿未能清除；正式保存结果不受影响。重开可能再次显示旧草稿，请在设置中重试。',true);
    draftStorageFailures.add(failure);saveIndicator();
  });
  return draftWriteQueue;
}
function persistDraftNow(key,keepalive=false){
  const draft=drafts.get(key);if(!draft)return draftWriteQueue;
  const body={document_key:key,base_revision:draft.baseRevision,values:draft.values,position:draft.position};
  const failure='write:'+key;
  draftWriteQueue=draftWriteQueue.then(()=>api(draftUrl(draft.project),{method:'POST',body:JSON.stringify(body),keepalive})).then(()=>{draftStorageFailures.delete(failure);saveIndicator();}).catch(()=>{
    if(!draftStorageFailures.has(failure))notify('本地草稿暂未写入磁盘；输入仍保留在当前窗口。请保留窗口，在设置中重试。',true);
    draftStorageFailures.add(failure);saveIndicator();
  });
  return draftWriteQueue;
}
function scheduleDraftPersist(key){
  const previous=draftTimers.get(key);if(previous)clearTimeout(previous);
  draftTimers.set(key,setTimeout(()=>{draftTimers.delete(key);void persistDraftNow(key);},800));
}
async function flushDrafts(keepalive=false){
  for(const timer of draftTimers.values())clearTimeout(timer);draftTimers.clear();
  for(const [key,draft] of drafts.entries())if(draft.project)await persistDraftNow(key,keepalive);
}
function draftDocument(key,project){
  try{const parsed=JSON.parse(key);const view=parsed[1],chapter=parsed[2],pane=parsed[3];const foundChapter=workspace?.document.chapters.find(v=>v.id===chapter),foundCharacter=workspace?.document.characters.find(v=>v.id===chapter);
    const title=view==='writing'&&foundChapter?`${foundChapter.title} / ${{body:'正文',idea:'IDEA',outline:'细纲'}[pane]||pane}`:view==='characters'&&foundCharacter?foundCharacter.name:tabs.find(item=>item[0]===view)?.[1]||'本地草稿';
    return {key,project,view,chapter:view==='writing'?chapter:'',character:view==='characters'?chapter:'',memory:view==='memory'?chapter:selectedMemory,pane:view==='writing'?pane:'',title};}catch{return null;}
}
async function loadDiskDrafts(project){
  if(!project||draftsLoadedProject===project)return;
  let result;const failure='read:'+project;
  try{result=await api(draftUrl(project));draftsLoadedProject=project;draftStorageFailures.delete(failure);}
  catch{draftStorageFailures.add(failure);notify('本地恢复草稿暂不可读取；已保存正文仍可打开。请保留当前输入，在设置中重试。',true);saveIndicator();return;}
  for(const item of result.drafts||[]){
    // Retrying recovery must never replace newer input already held in memory.
    if(drafts.get(item.document_key)||draftClearRetries.has(item.document_key))continue;
    drafts.restore(item.document_key,project,item.base_revision,item.values,item.position,item.updated_at,item.sensitive_fields_required);
    const doc=draftDocument(item.document_key,project);if(doc&&!documents.some(v=>v.key===doc.key))documents.push(doc);
  }
  if(result.corrupt?.length)notify(`已忽略 ${result.corrupt.length} 个损坏的本地草稿文件；其他草稿仍保留。`,true);
  if(result.unreadable){draftStorageFailures.add(failure);notify(`有 ${result.unreadable} 个本地草稿暂不可读取，未删除；请检查存储后在设置中重试。`,true);saveIndicator();}
}

async function retryDiskDrafts(){
  for(const [key,project] of [...draftClearRetries])await clearDiskDraft(project,key);
  await flushDrafts();
  if(workspace){draftsLoadedProject='';await loadDiskDrafts(workspace.document.project.id);}
  saveIndicator();
  return draftStorageFailures.size?'仍有恢复草稿读写失败；当前窗口输入保留，请检查存储后重试。':'恢复草稿读写重试完成；正式内容未自动提交。返回文档即可核对恢复输入。';
}

const localDisplayControl=element=>['toggle-modules','toggle-left','toggle-right','close-left','close-right','drawer-backdrop','focus-mode','toggle-theme','toggle-bottom','quick-activity','close-bottom'].includes(element.id)||element.hasAttribute('data-bottom');
const settingsNavigation=element=>element.id==='chat-model'||element.dataset.view==='settings';
function disableBusyControls(){
  document.querySelectorAll('button, input, textarea, select').forEach(element=>{
    if(!disabledBeforeRequest.has(element))disabledBeforeRequest.set(element,element.disabled);
    if(!localDisplayControl(element)&&!settingsNavigation(element))element.disabled=true;
  });
}
function setBusy(value) {
  busy = value;
  if (value) {
    const focused=document.activeElement;
    requestFocus=focused?.id ? {id:focused.id,start:focused.selectionStart,end:focused.selectionEnd,top:focused.scrollTop,contentTop:$('#content').scrollTop} : null;
    disableBusyControls();
  } else {
    disabledBeforeRequest.forEach((wasDisabled, element) => { element.disabled = wasDisabled; });
    disabledBeforeRequest.clear();
    $('#reload-project').disabled = !workspace;
    if(view==='chat')syncAgentControls();
    if(view==='chat') updatePromptSummary();
    const element=requestFocus && document.getElementById(requestFocus.id);
    if(element && !element.disabled && element.getClientRects().length && !document.querySelector('dialog[open]')) {
      element.focus({preventScroll:true});
      if(typeof requestFocus.start==='number' && ['TEXTAREA','INPUT'].includes(element.tagName)) { element.setSelectionRange(requestFocus.start,requestFocus.end);element.scrollTop=requestFocus.top;$('#content').scrollTop=requestFocus.contentTop; }
    }
    requestFocus=null;
  }
  saveIndicator();
}

function mayLeave() {
  return !busy && annotationsMayLeave();
}


function renderLibrary() {
  $('#project-count').textContent = projects.length;
  $('#project-list').innerHTML = `<label for="project-scope-filter">书架范围</label><select id="project-scope-filter">${[['active','创作中'],['archived','已归档'],['deleted','回收站'],['all','全部']].map(([value,label])=>`<option value="${value}" ${shelfScope===value?'selected':''}>${label}</option>`).join('')}</select>`+(projects.some(project=>shelfScope==='all'||(project.author_state||'active')===shelfScope) ? projects.filter(project=>shelfScope==='all'||(project.author_state||'active')===shelfScope).map(project => `<div class="agent-shelf-row"><button class="book-link ${workspace?.document.project.id === project.id ? 'active' : ''}" data-project="${escapeHTML(project.id)}"><span>${escapeHTML(project.title)}</span><small>保存编号 ${project.revision}</small></button><button type="button" class="quiet" data-chat-book="${escapeHTML(project.id)}" data-restore="${['deleted','archived'].includes(project.author_state)}" aria-label="${['deleted','archived'].includes(project.author_state)?'恢复':'删除'}这本书">${['deleted','archived'].includes(project.author_state)?'恢复':'删除'}</button></div>`).join('') : '<p class="sidebar-empty">当前书架范围没有小说。</p>');
  $('#project-scope-filter').onchange=event=>{shelfScope=event.target.value;renderLibrary();};
  renderChapterTree();
}

function renderChapterTree() {
  const archived=workspace?archivedChapterIds(workspace):new Set(),chapters=[...(workspace?.document.chapters||[])].sort((a,b)=>a.number-b.number).filter(chapter=>!archived.has(chapter.id)),query = $('#chapter-filter').value.trim().toLocaleLowerCase();
  const filtered = chapters.filter(chapter => chapter.title.toLocaleLowerCase().includes(query));
  $('#chapter-count').textContent = query ? `${filtered.length} / ${chapters.length}` : chapters.length;
  $('#chapter-tree').innerHTML = filtered.length ? filtered.map(chapter => `<button class="tree-link ${chapter.id === selectedChapter && view === 'writing' ? 'active' : ''}" data-chapter="${chapter.id}" title="${escapeHTML(chapter.title)}"><span class="chapter-number">${String(chapter.number).padStart(2,'0')}</span><span>${escapeHTML(chapter.title)}${drafts.get(JSON.stringify([workspace.document.project.id, 'writing', chapter.id, 'body'])) ? ' •' : ''}</span></button>`).join('') : '<p class="sidebar-empty">' + (query ? '没有匹配的章节。' : '打开章节写作，新建第一章。') + '</p>';
  revealActive('#chapter-tree','.active');
}

async function refreshProjects() {
  projects = await api('/api/projects');
  renderLibrary();
  recordActivity('书架读取完成');
}


function updateModeChrome(){
 $('#model-status').textContent=t(sessionModels?'desktop.statusModels':'desktop.statusManual');
 $('.sidebar-footer').textContent=t(sessionModels?'desktop.sidebarModels':'desktop.sidebarManual');
 $('.mode-status').textContent=t(sessionModels?'desktop.modeModels':'desktop.modeManual');
 $('#chat-model').textContent=t('desktop.modelCenter');
 if($('#overview-model'))$('#overview-model').textContent=t(sessionModels?'desktop.statusModels':'desktop.statusManual');
}

function renderChrome() {
  const project = workspace?.document.project;
  $('#book-title').textContent = view==='chat'?`创作对话 · ${project?.title||'未绑定小说'}`:project?.title || '未绑定小说 · 创作工作台';
  $('#book-title').title = project?.title || '';
  $('#book-description').textContent = view==='chat' ? '创作对话 / 大纲候选与正式提案' : tabs.find(([id])=>id===view)?.[1] || '';
  $('#reload-project').disabled = !workspace;
  $('#export-project').hidden = !workspace;
  if (project) $('#export-project').href = `/api/projects/${project.id}/export`;
  const navButton=([id,name])=>`<button data-view="${id}" aria-label="${name}" title="${moduleNames[id]||name}" class="${view===id?'active':''}" ${!workspace&&!globalViews.includes(id)?'disabled':''}><span class="activity-icon" aria-hidden="true">${icons[id]}</span><span class="module-label">${moduleNames[id]||name}</span></button>`;
  $('#tabs').innerHTML = navButton(tabs[0])+navButton(tabs.find(([id])=>id==='writing'))+navButton(tabs.find(([id])=>id==='annotations'))+navButton(['settings','API 设置'])+'<details class="agent-advanced"><summary>查看资料与高级功能</summary>'+tabs.filter(([id])=>moduleNames[id]&&!['writing','annotations','settings'].includes(id)).map(navButton).join('')+'<div class="nav-utilities">'+tabs.filter(([id])=>['skills','guide'].includes(id)).map(navButton).join('')+'</div></details>';
  const lore=['characters','world','memory'].includes(view);
  $('#module-tabs').hidden=!lore;
  $('#module-tabs').innerHTML=lore?[['characters','人物资料','打开人物模块'],['world','世界观资料','打开世界观模块'],['memory','长篇记忆','打开长篇记忆模块']].map(([id,label,name])=>`<button data-view="${id}" aria-label="${name}" class="${view===id?'active':''}" type="button">${label}</button>`).join(''):'';
  renderLibrary();
  saveIndicator();
}

async function openProject(id, preserveView = false) {
  if (!mayLeave()) return;
  resetAgentView();++rendering;
  captureDraft();await flushDrafts();
  setBusy(true);
  try {
    const previousProject=workspace?.document.project.id;
    workspace = await api(`/api/projects/${encodeURIComponent(id)}`);
    if(previousProject!==id){selectedMemory='new';localSearchResult=null;searchSelections=[];selectedReview='';reviewDetail=null;draftsLoadedProject='';memoryRollupData=null;memoryRollupForm=null;memoryRollupPreview=null;rollupOperationId='';}
    await loadDiskDrafts(id);
    unboundPrompt=false;
    selectedChapter = workspace.document.chapters.some(item => item.id === selectedChapter) ? selectedChapter : workspace.document.chapters[0]?.id || '';
    selectedCharacter = workspace.document.characters[0]?.id || '';
    if (!preserveView) view = 'chat';
    sessionStorage.setItem('novel-project', id);
    await renderMain();
    recordActivity('小说读取完成');
  } catch (error) { notify(error.message, true); } finally { setBusy(false); }
}

async function perform(action, values) {
  if (busy || !workspace) return;
  const savedKey = activeKey, oldRevision = workspace.revision, projectId = workspace.document.project.id;
  const editing = action.startsWith('save_') ? drafts.get(savedKey) : null;
  if (editing && editing.baseRevision !== oldRevision) { notify('草稿基于旧版本，请先对照并明确绑定最新版本，或放弃本标签草稿。', true); return false; }
  setBusy(true);
  let committed = false;
  try {
    const saved = await api(`/api/projects/${workspace.document.project.id}/actions`, { method: 'POST', body: JSON.stringify({ action, fields: values, expected_revision: workspace.revision }) });
    workspace = saved;
    memoryRollupPreview=null;rollupOperationId='';
    localSearchResult=null;searchSelections=[];retrievalRequest++;
    committed = true;
    drafts.acknowledge(projectId, oldRevision, workspace.revision, action.startsWith('save_') ? savedKey : action === 'restore_chapter' ? JSON.stringify([projectId, 'writing', selectedChapter, 'body']) : null);
    if(action.startsWith('save_'))clearDiskDraft(projectId,savedKey);
    if(action==='restore_chapter')clearDiskDraft(projectId,JSON.stringify([projectId,'writing',selectedChapter,'body']));
    for(const [key,draft] of drafts.entries())if(draft.project===projectId)scheduleDraftPersist(key);
    if (action === 'add_chapter') { selectedChapter = workspace.document.chapters.at(-1).id; view = 'writing'; writingPane = 'body'; }
    if (action === 'add_character') { selectedCharacter = workspace.document.characters.at(-1).id; view = 'characters'; }
    if (action === 'restore_chapter') { view = 'writing'; writingPane = 'body'; }
    if(action==='save_memory'){selectedMemory=values.memory_id||workspace.memories.at(-1).id;view='memory';}
    recordActivity('数据库写入完成 · 保存编号 ' + workspace.revision);
    await renderMain();
    await refreshProjects();
    notify(`已保存到本地 · 保存编号 ${workspace.revision}`);
    return true;
  } catch (error) {
    notify(committed ? `内容已保存，但页面刷新失败：${error.message}。请重新读取，不要重复创建。` : error.message, true);
    return committed;
  } finally { setBusy(false); }
}


function renderContext() {
  document.querySelectorAll('[data-context]').forEach(button => button.classList.toggle('active', button.dataset.context === contextView));
  let html = '<p class="hint">选择小说后查看已保存的上下文。</p>';
  if (workspace && contextView === 'characters') html = workspace.document.characters.length ? workspace.document.characters.map(character => `<article class="context-card"><h3>${escapeHTML(character.name)}</h3><p>${escapeHTML(character.role)}\n${escapeHTML(character.personality)}\n${escapeHTML(character.background)}\n${escapeHTML(character.notes)}</p><button data-edit-character="${character.id}" type="button">编辑人物资料</button></article>`).join('') : '<p class="hint">尚无人物资料。</p><button data-view="characters" type="button">打开人物设定</button>';
  else if (workspace && contextView === 'world') html = `<p class="hint">当前小说已保存的设定</p><div class="context-text">${escapeHTML(workspace.worldbuilding || '尚未填写世界观。')}</div><button data-view="world" type="button">编辑世界观</button>`;
  else if (contextView === 'memory') html = `<h3>手动长篇记忆</h3><p class="hint">当前书已保存 ${workspace?.memories?.length||0} 条记忆。打开主页面复核出处与确认状态；自动分层记忆和语义检索仍未完成。</p><button data-view="memory" type="button">打开长篇记忆</button>`;
  else if (workspace && contextView === 'history') {
    const chapter = workspace.document.chapters.find(item => item.id === selectedChapter);
    if (chapter) {
      const versions = workspace.document.versions.filter(item => item.entity_type === 'chapter' && item.entity_id === chapter.id).slice().reverse();
      html = `<div class="history-panel"><h3>${escapeHTML(chapter.title)}</h3><div class="field"><label for="version-select">历史版本</label><select id="version-select" data-passive>${versions.map(item => `<option value="${item.id}">正文第 ${item.version_number} 版</option>`).join('')}</select></div><p id="version-note" class="hint"></p><pre id="version-preview" class="version-preview"></pre><h3>所选版本 → 当前正文${dirty && view === 'writing' && writingPane === 'body' ? '草稿' : ''}</h3><p class="diff-legend">− 删除行　+ 新增行　· 相同行；仅比较，不写入</p><div id="version-diff" class="version-diff" aria-label="正文差异"></div><button id="restore-version" type="button">恢复此版为新草稿</button><p class="hint">恢复追加新版本，保留原始历史和章节顺序。</p></div>`;
    } else html = '<p class="hint">打开一个章节后查看正文历史。</p>';
  }
  $('#context-content').innerHTML = html;
  showVersion();
}

function showVersion() {
  const id = $('#version-select')?.value;
  if (!id) return;
  const version = workspace.document.versions.find(item => item.id === id);
  $('#version-preview').textContent = version.snapshot.content || '这一版尚无正文。';
  $('#version-note').textContent = version.change_note + ' · ' + new Date(version.created_at).toLocaleString(getLanguage());
  const chapter = workspace.document.chapters.find(item => item.id === selectedChapter);
  const current = view === 'writing' && writingPane === 'body' ? $('#edit-content')?.value ?? chapter.content : chapter.content;
  $('#version-diff').innerHTML = diffLines(version.snapshot.content || '', current).map(row => `<div class="diff-line diff-${row.kind}">${row.kind === 'add' ? '+' : row.kind === 'remove' ? '−' : '·'} ${escapeHTML(row.text) || ' '}</div>`).join('');
}


async function renderModules(){const cards=[["writing","ready","手动正文与版本","正文、IDEA与章纲分别保存，确认章修改和恢复须授权。"],["creation","partial","从零规划与AI辅助","七步方案、分支、锁与确认已可用；真实规划质量待验。"],["model-prepare","partial","模型改写与审核","初稿、追加续写、整章改写与引文审核可用，逐请求确认；细纲生成和场景/选区扩写已接通，真实质量待验。"],["rules","partial","文风导入、提炼与试写","资料/自有卡、原生搜索公开样本、短试写与A/B；真实文风效果待验。"],["memory","partial","长篇记忆","正文变更自动进入待刷新队列；作者确认更新、历史追踪和失败重试可用。本地原文摘录自动刷新默认关闭，语义摘要仍须逐请求确认。"],["reviews","partial","离线规则审核与查重","明确时间/字面规则与基础重复检查可用，不代表完整语义或全网审核。"],["knowledge","partial","图谱与规划反馈","人工实体关系、合并恢复、字段反馈与局部提案可用，自动抽取未完成。"],["comparisons","partial","同题盲评比较","冻结共同输入、逐侧执行、评分揭晓和打开候选；不是通用模型排名。"],["workflows","ready","持久工作流与人工节点","保存章纲→多候选初稿→深审→等你选稿→采纳写正文，全链路可跑；暂停取消、中断续跑、失败重试可用。真实模型质量待验。"],["history","ready","完整备份、恢复与复制","当前已实现对象的历史完整保存，恢复到新目录、复制使用新编号；不含密钥或未保存输入。"],["settings","partial","模型连接与预设","自建连接、独立步骤绑定和会话开关可用；真实服务与账单另验。"],["chat","partial","持久对话与完整创作链","持久会话、可编辑计划、显式单步运行及细纲/扩写/分级规则已接通；后台自动执行未完成。"],["writing","partial","章节生命周期与异常恢复","章节重排/跨卷拖拽、回收站恢复、严格编码迁移和磁盘草稿恢复可用；真实长篇性能待验。"]];const labels={ready:'可使用',partial:'可用·待模型验证',planned:'开发中'};return '<section class="panel"><h2>审核、图谱与工作流</h2><p>从下方进入已实现的具体流程。每项说明实际范围；模型结果仍待核实，开启模型不授予自动执行权限。</p></section><div class="capability-list">'+cards.map(([target,status,title,description])=>'<article class="capability"><h3>'+escapeHTML(title)+'</h3><p>'+escapeHTML(description)+'</p><span class="badge '+status+'">'+labels[status]+'</span>'+(target?'<button type="button" data-view="'+target+'" '+(!workspace&&!globalViews.includes(target)?'disabled':'')+'>打开</button>':'')+'</article>').join('')+'</div>';}

async function renderSettings() {
  const settings=await api('/api/settings/chat');sessionModels=!settings.offline;
  return renderAgentSettings(settings);
}
async function renderAdvancedSettings() {
  const settings = await api('/api/settings');
  creationPresetData=workspace?await api('/api/projects/'+encodeURIComponent(workspace.document.project.id)+'/creation-presets'):null;
  const canon = workspace ? await api('/api/projects/'+encodeURIComponent(workspace.document.project.id)+'/canon-maintenance') : null;
  const offline = settings.offline_mode === true;
  const canConfigure=settings.configuration_writes_enabled??!offline;
  sessionModels=settings.real_model_enabled===true;

  const desktopMode = window.novelDesktop ? '<section class="panel" id="desktop-mode" data-mode="'+(offline?'manual':'models')+'">'+'<h2>'+t('desktop.heading')+'</h2><p>'+t(offline?'desktop.manualHint':'desktop.modelsHint')+'</p><p class="hint">'+t('desktop.note')+'</p>'+(offline?'<label><input id="desktop-model-consent" type="checkbox">'+t('desktop.consent')+'</label><button id="desktop-enable-models" type="button">'+t('desktop.enable')+'</button>':'<button id="desktop-manual" type="button">'+t('desktop.manual')+'</button>')+'</section>' : '';
  const legacyCards = Object.values(settings.connections).filter(provider=>!provider.custom&&(provider.key_configured===true||provider.model_id)).map(provider => {
    const id=provider.id, test=provider.last_test;
    const disabled=canConfigure?'':'disabled';
    const keyStatus=offline?'完全手动：配置可在本机保存；连接检查和外发关闭。':provider.key_configured?'密钥已加密保存 · 留空保留原密钥':'尚未配置密钥';
    const details=offline?'配置已本地保存；连接检查需先开启模型会话。':test?`${test.message}${test.http_status?' · HTTP '+test.http_status:''}${test.ok?' · '+test.models.length+' 个模型':''}`:'尚未测试连接';
    return `<form class="panel provider-card" data-provider="${id}" data-read-only="${!canConfigure}" autocomplete="off"><h3>${escapeHTML(providerDisplayName(provider))}</h3><p class="hint">${keyStatus}</p><div class="field"><label for="provider-url-${id}">API Base URL</label><input id="provider-url-${id}" name="base_url" type="url" required ${disabled} value="${escapeHTML(provider.base_url)}"></div><div class="field-grid"><div class="field"><label for="provider-key-${id}">API Key</label><input id="provider-key-${id}" name="api_key" type="password" autocomplete="new-password" ${disabled} placeholder="${offline?'手动模式 · 留空保留已有密钥':provider.key_configured?'已配置，留空保留':'请输入本站 API Key'}"></div><div class="field"><label for="provider-model-${id}">模型 ID</label><input id="provider-model-${id}" name="model_id" ${disabled} value="${escapeHTML(provider.model_id)}" list="provider-models-${id}" placeholder="${offline?'填写模型编号（保存不联网）':'连接后选择本站模型'}"><datalist id="provider-models-${id}">${(test?.models||[]).map(model=>`<option value="${escapeHTML(model)}"></option>`).join('')}</datalist></div></div><div class="provider-actions"><button class="primary" type="submit" ${disabled}>保存配置</button><button type="button" data-test-provider="${id}" ${offline||!provider.key_configured?'disabled':''}>测试连接</button></div><p class="provider-result hint ${test&&!test.ok?'error':''}" role="status">${escapeHTML(details)}</p><p class="hint">${offline?'保存配置只在本机进行；完全手动时不检查连接、不发送模型请求。':'测试使用已保存配置，只请求模型列表；修改密钥或模型后请先保存。'}</p></form>`;
  }).join('');
  const cards=desktopMode+renderLocalData()+renderModelPurposeGuide()+renderCreationPresets(workspace,creationPresetData)+renderCustomProvider(settings)+Object.values(settings.connections).filter(v=>v.custom).map(v=>renderCustomProvider(settings,v)).join('')+(legacyCards?'<details id="legacy-connections"><summary>'+t('provider.legacy_heading')+'</summary><p>'+t('provider.legacy_note')+'</p>'+legacyCards+'</details>':'')+renderProviderManagement(settings,await api('/api/providers/catalog'));
  const canonPanel = canon ? `<section class="panel" id="canon-maintenance-panel"><h2>自动设定维护</h2><p class="hint">保存章节后自动检查大纲、人物、伏笔、时间线和世界观。每次变更保留原文引文、前后值和可回退点；分析失败会显示在这里。</p><label class="check-label"><input id="canon-maintenance-toggle" type="checkbox" ${canon.enabled?'checked':''} data-canon-revision="${canon.revision}">保存章节后自动同步设定</label><p class="hint" role="status">状态：${escapeHTML(canon.sync_status)} · 审计事件 ${canon.events.length} 条 · 回退点 ${canon.checkpoints.length} 个</p>${canon.events.length?`<details><summary>查看最近审计事件</summary><ul>${canon.events.slice(-8).reverse().map(item=>`<li>${escapeHTML(item.status)} · ${escapeHTML(item.kind)}${item.field?' · '+escapeHTML(item.field):''}${item.error?' · '+escapeHTML(item.error):''}</li>`).join('')}</ul></details>`:''}</section>` : '';
  return canonPanel+`<section class="panel"><h2>模型 / API 中心</h2><p>${t('provider.centerNote')}</p><p class="hint">${offline?(canConfigure?'手动模式：可保存本机配置；没有连接检查或模型外发。':'离线维护：不读取凭据，配置保存与连接检查均已禁用。'):'密钥由本机后端使用 Windows 账户加密保存。页面只显示配置状态，保存和打开页面不会自动请求站点。'}</p><p class="hint">${t('provider.tasksNote')}</p></section>${cards}<section class="panel"><h3>本地数据位置</h3><p class="path-display">${escapeHTML(settings.database_path)}</p><p class="hint">请在历史与恢复模块下载完整备份包，在线一致性快照包含全部小说历史和 Skills。JSON 导出不含完整项目快照与独立 Skills；备份不含 API 配置或凭据。</p></section>`;
}

async function configureCanonToggle(input) {
  if (!workspace || input.disabled) return;
  const project = workspace.document.project.id;
  const expected = Number(input.dataset.canonRevision);
  input.disabled = true;
  try {
    const result = await api('/api/projects/'+encodeURIComponent(project)+'/canon-maintenance', {
      method: 'POST', body: JSON.stringify({operation_id: crypto.randomUUID(), enabled: input.checked, expected_revision: expected})
    });
    input.dataset.canonRevision = String(result.revision);
    workspace = await api('/api/projects/'+encodeURIComponent(project));
    notify(input.checked ? '自动设定维护已开启' : '自动设定维护已关闭');
    await renderMain();
  } catch (error) {
    input.checked = !input.checked;
    notify(error.message, true);
  } finally { input.disabled = false; }
}

async function configureProvider(form, test=false) {
  if(form.dataset.readOnly==='true') return;
  const id=form.dataset.provider;
  if(pendingProviders.has(id)) return;
  pendingProviders.add(id);
  const output=form.querySelector('.provider-result');
  const buttons=[...form.querySelectorAll('button')];
  buttons.forEach(button=>button.disabled=true);
  output.textContent=test?'正在检查已保存连接…':'正在加密保存…';
  output.classList.remove('error');
  try {
    const result=await api(test?'/api/providers/test':'/api/providers/save',{
      method:'POST',body:JSON.stringify(test?{id}:{id,...Object.fromEntries(new FormData(form))})
    });
    if(test) {
      output.textContent=result.message+(result.http_status?' · HTTP '+result.http_status:'')+(result.ok?' · '+result.models.length+' 个模型':'');
      output.classList.toggle('error',!result.ok);
      form.querySelector('datalist').innerHTML=result.models.map(model=>`<option value="${escapeHTML(model)}"></option>`).join('');
    } else {
      form.elements.api_key.value='';
      form.elements.api_key.placeholder='已配置，留空保留';
      output.textContent='配置已在本机加密保存；连接检查需在模型会话开启后明确点击。';
    }
    recordActivity(test?'API 模型列表连接检查完成':'API 配置已加密保存');
  } catch(error) { output.textContent=error.message;output.classList.add('error'); }
  finally {
    pendingProviders.delete(id);
    buttons.forEach(button=>button.disabled=false);
    try { const settings=await api('/api/settings');form.querySelector('[data-test-provider]').disabled=!settings.connection_checks_enabled||!settings.connections[id].key_configured; }
    catch { form.querySelector('[data-test-provider]').disabled=true; }
  }
}

function renderChat() {
  const project=workspace?.document.project;
  return `<div class="chat-home"><div class="chat-home-inner"><div class="chat-wordmark" aria-hidden="true">D<span>DUALQUILL</span></div><h2>从一个故事开始。</h2><p>描述构思，梳理人物，推敲下一章。<br>把创作的意图，留在同一个工作台。</p><div class="chat-offline"><span class="offline-dot"></span>创建或打开小说后，可逐轮生成和修改全书大纲</div><div class="chat-home-actions"><button data-view="project" type="button">打开小说书架 <span aria-hidden="true">↗</span></button>${project?'<button data-view="writing" type="button">继续手动写作 <span aria-hidden="true">↗</span></button>':'<button data-create="project" type="button">创建小说 <span aria-hidden="true">＋</span></button>'}</div><p class="chat-home-note">未绑定小说时，此输入仅保留在本窗口。<br>打开小说后可与模型多轮讨论大纲；每次外发及正式写入均需明确确认。</p></div></div>`;
}

function updatePromptSummary() {
  const prompt=prompts.get(promptProject()), bound=Boolean(promptProject());
  const chapter=bound?workspace?.document.chapters.find(item=>item.id===prompt.chapter):null;
  const character=bound?workspace?.document.characters.find(item=>item.id===prompt.character):null;
  const labels=[bound?workspace.document.project.title:'未绑定小说',chapter?.title,character?.name,prompt.world?'世界观':null].filter(Boolean);
  const hasContext=prompt.chapter||prompt.character||prompt.world;
  const stale=hasContext&&workspace&&prompt.revision!==workspace.revision;
  $('#chat-context-summary').textContent=(workspace?.document.project.title||'新小说')+' · 自动读取人物、设定、大纲和近期正文';
  $('#chat-context-summary').classList.toggle('stale',Boolean(stale));
  $('#chat-context-summary').title=$('#chat-context-summary').textContent;
  $('#add-chat-context').disabled=!bound;
  $('#switch-prompt-scope').hidden=!workspace||(!unboundPrompt&&!prompts.get('').text);
  $('#switch-prompt-scope').textContent=unboundPrompt?'返回当前小说需求':'查看未绑定需求';
  $('#clear-chat-prompt').disabled=!prompt.text;
  $('#prompt-state').textContent=prompt.text?'需求未发送 · 仅本窗口':'需求准备';
}
let composerSettings=null,composerSettingsRequest=0,composerSaving=false;
function composerTaskBlocked(){
  const running=item=>['running','submitting','queued','executing'].includes(item?.display_status||item?.status||item?.task?.status);
  return busy||agentSubmitting||composerSaving||Boolean($('#chat-send')?.disabled)||Object.entries(workspace||{}).some(([key,value])=>/tasks|runs|jobs/.test(key)&&Array.isArray(value)&&value.some(running));
}
function composerNovelBlocked(){
  if(busy||agentSubmitting||composerSaving||dirty||annotationsDirty()||$('#chat-input').value||prompts.get(promptProject()).text||hasPendingAttachments(workspace?.document.project.id)||attachmentsUploading(workspace?.document.project.id)){
    notify('请先完成当前提交或本地读写、保存修改、发送或清空输入并处理附件；后台创作不阻止切换小说。',true);return true;
  }
  return false;
}
function renderComposerNovels(){
  if(view!=='chat')return;
  const composer=$('#chat-composer');
  let host=$('#chat-novel-controls');
  if(!host){
    host=document.createElement('div');host.id='chat-novel-controls';host.className='chat-novel-controls';
    host.innerHTML='<label for="chat-novel-select">当前小说</label><select id="chat-novel-select" data-passive></select><button id="chat-create-novel" type="button">创建新小说</button>';
    composer.insertAdjacentElement('afterend',host);
    host.querySelector('select').onchange=async event=>{
      const select=event.currentTarget,id=select.value,current=workspace?.document.project.id||'';
      select.value=current;
      if(id===current||!id||composerNovelBlocked())return;
      if(!projects.some(item=>item.id===id&&(item.author_state||'active')==='active'))return;
      await openProject(id,true);
      if(select.isConnected)select.value=workspace?.document.project.id||'';
    };
    host.querySelector('button').onclick=()=>{if(!composerNovelBlocked())openCreate('project');};
  }
  const current=workspace?.document.project.id||'',active=projects.filter(item=>(item.author_state||'active')==='active');
  const options=(current&&!active.some(item=>item.id===current)?`<option value="${escapeHTML(current)}" disabled>${escapeHTML(workspace.document.project.title)}（非创作中）</option>`:'')+
    (!current?'<option value="" disabled>未绑定小说</option>':'')+active.map(item=>`<option value="${escapeHTML(item.id)}">${escapeHTML(item.title)}</option>`).join('');
  const select=host.querySelector('select');
  if(select.dataset.options!==options){select.innerHTML=options;select.dataset.options=options;}
  select.value=current;select.disabled=!active.length;
}
function renderComposerControls(settings=null){
  const tools=$('#chat-composer .composer-tools');
  if(!tools||view!=='chat')return;
  let host=$('#chat-composer-controls');
  if(!host){
    host=document.createElement('div');host.id='chat-composer-controls';host.className='composer-controls';
    host.style.cssText='display:flex;align-items:center;gap:8px;flex-wrap:wrap';
    host.innerHTML='<label for="chat-writer-connection">写作连接 <select id="chat-writer-connection" data-passive></select></label><label for="chat-reviewer-connection">审核连接 <select id="chat-reviewer-connection" data-passive></select></label><span id="chat-composer-control-notice" class="hint" role="status"></span>';
    tools.insertBefore(host,tools.querySelector('#chat-model')||tools.querySelector('#chat-send'));
    host.querySelectorAll('select').forEach(select=>{select.onchange=()=>changeComposerConnection(select);});
  }
  const connections=Array.isArray(settings?.connections)?settings.connections:Object.entries(settings?.connections||{}).map(([id,item])=>({...item,id:item.id||id}));
  const valid=connections.filter(item=>item&&item.id);
  for(const [id,key] of [['chat-writer-connection','connection_id'],['chat-reviewer-connection','reviewer_connection_id']]){
    const select=host.querySelector('#'+id),selected=settings?.[key]||'';
    const placeholder=!settings?'正在读取连接…':!valid.length?'暂无可用连接，请先在设置中配置':selected?'已选连接不可用，请在设置中检查':'尚未选择连接';
    const options=(!valid.some(item=>item.id===selected)?`<option value="${escapeHTML(selected)}" disabled>${placeholder}</option>`:'')+valid.map(item=>`<option value="${escapeHTML(item.id)}">${escapeHTML(item.name||item.id)} · ${escapeHTML(item.model_id||'未指定模型')}</option>`).join('');
    if(select.dataset.options!==options){select.innerHTML=options;select.dataset.options=options;}
    select.value=selected;select.dataset.previous=selected;select.disabled=!settings||!valid.length||composerSaving;
  }
  host.querySelector('[role="status"]').textContent=settings?.offline?'离线模式：选择仅保存本机配置，不发送模型请求。':'';
}
async function loadComposerControls(renderId,projectId){
  const request=++composerSettingsRequest;
  const current=()=>request===composerSettingsRequest&&renderId===rendering&&view==='chat'&&(workspace?.document.project.id||'')===projectId;
  try{
    const settings=await api('/api/settings/chat');
    if(!current()||composerSaving)return;
    composerSettings=settings;renderComposerControls(settings);renderComposerNovels();
  }catch(error){if(current()){$('#chat-composer-control-notice').textContent='连接设置读取失败：'+error.message;}}
}
async function changeComposerConnection(select){
  const settings=composerSettings,previous=select.dataset.previous||'',next=select.value;
  select.value=previous;
  if(!settings||next===previous)return;
  if(busy||agentSubmitting||composerSaving){notify('请等待当前提交或设置保存完成，再切换默认连接。',true);return;}
  const writer=select.id==='chat-writer-connection',other=writer?settings.reviewer_connection_id:settings.connection_id;
  if(next&&next===other){notify('写作连接与审核连接必须不同；原选择已保留。',true);return;}
  const renderId=rendering,projectId=workspace?.document.project.id||'';
  const current=()=>renderId===rendering&&view==='chat'&&(workspace?.document.project.id||'')===projectId&&select.isConnected;
  const body=writer?{connection_id:next,wire_mode:settings.wire_mode}:{reviewer_connection_id:next};
  composerSaving=true;++composerSettingsRequest;
  const send=$('#chat-send'),sendDisabled=send.disabled;send.disabled=true;
  $('#chat-composer-controls').querySelectorAll('select').forEach(input=>{input.disabled=true;});
  try{
    await api('/api/settings/chat/config',{method:'POST',body:JSON.stringify(body)});
    if(current()){composerSettings={...settings,...body};select.value=next;select.dataset.previous=next;notify('连接选择已保存；未发送模型请求。');}
  }catch(error){if(current()){select.value=previous;notify('连接保存失败，保留原选择：'+error.message,true);}}
  finally{
    composerSaving=false;
    if(current()){send.disabled=sendDisabled;renderComposerControls(composerSettings);}
    else if(view==='chat'){syncAgentControls();void loadComposerControls(rendering,workspace?.document.project.id||'');}
  }
}
function renderPrompt() {
  $('#chat-composer').hidden=view!=='chat';
  $('#prompt-state').hidden=view!=='chat'||Boolean(workspace);
  if(view==='chat') {
    const text=prompts.get(promptProject()).text;
    if($('#chat-input').value!==text)$('#chat-input').value=text;
    updatePromptSummary();renderComposerControls(composerSettings);renderComposerNovels();
    if(!composerSaving)void loadComposerControls(rendering,workspace?.document.project.id||'');
  }else{
    ++composerSettingsRequest;$('#chat-composer-controls')?.remove();$('#chat-novel-controls')?.remove();
  }
}
function openChatContext() {
  if(!workspace||!promptProject()) return;
  const prompt=prompts.get(workspace.document.project.id);
  const options=(items,selected,label)=>'<option value="">不绑定</option>'+items.map(item=>`<option value="${escapeHTML(item.id)}" ${item.id===selected?'selected':''}>${escapeHTML(item[label])}</option>`).join('');
  $('#chat-context-fields').innerHTML=`<p class="hint">当前小说：${escapeHTML(workspace.document.project.title)}</p><div class="field"><label for="chat-chapter">绑定章节</label><select id="chat-chapter" name="chapter">${options(activeChapters(workspace),prompt.chapter,'title')}</select></div><div class="field"><label for="chat-character">绑定人物</label><select id="chat-character" name="character">${options(workspace.document.characters,prompt.character,'name')}</select></div><label class="check-label"><input name="world" type="checkbox" ${prompt.world?'checked':''}>包含已保存世界观</label>`;
  $('#chat-context-dialog').showModal();
}
async function renderHistoryEntry() {
  let capabilities=null;
  try {capabilities=await api('/api/backups/capabilities');} catch {}
  const backupReady=capabilities?.backup_format_version===51&&capabilities?.full_library===true&&capabilities?.independent_restore===true;
  const backupDisabled=backupReady?'':'disabled';
  const backendNote=backupReady?'':'<p class="hint">当前运行后端尚未加载完整备份功能，或能力暂无法确认。请保留输入，按使用指南安全更新并重开软件后使用。</p>';

  const chapters=workspace?.document.chapters||[];
  return `<section class="panel"><h2>历史、备份与恢复</h2><p class="hint">选择章节后打开版本差异。恢复章节会追加新草稿，保留原历史与顺序。</p>${chapters.length?'<div class="field"><label for="history-chapter">历史章节</label><select id="history-chapter" data-passive>'+chapters.map(item=>`<option value="${item.id}" ${item.id===selectedChapter?'selected':''}>${escapeHTML(item.title)}</option>`).join('')+'</select></div><button id="open-history-panel" type="button">查看所选章节历史</button>':'<p>当前未选择有章节的小说。</p>'}</section><section class="panel"><h3>完整小说库备份</h3>${backendNote}<p class="hint">包含所有小说、已保存正文与资料、全部版本和整书快照、全局 Skills 原文。未保存输入需先保存；API 配置、密钥和令牌不会进入包。</p><button id="create-backup" ${backupDisabled} class="primary" type="button">下载完整库备份</button><h3>恢复到独立新目录</h3><p class="hint">上传完整备份包，校验后保留原编号、时间与历史。恢复结果存入新的独立目录；当前工作台继续使用原库。此入口只恢复独立新目录；导入当前库使用下方新项目迁移。</p><div class="field"><label for="backup-file">完整备份包</label><input id="backup-file" ${backupDisabled} type="file" accept=".nwbak" data-passive></div><button id="restore-backup" ${backupDisabled} type="button">恢复到独立新目录</button><button id="cancel-backup-operation" type="button" hidden>取消当前恢复</button><button id="check-backup-operation" ${backupDisabled} type="button">核对上次恢复结果</button><p id="backup-result" class="path-display" role="status">${escapeHTML(pendingBackupOperation ? '待核对操作：'+pendingBackupOperation : '')}</p><h3>当前工作区 JSON</h3><p class="hint">顶部 JSON 导出仅含当前工作区与实体历史，缺少完整整书快照和全局 Skills。</p><button data-view="settings" type="button">查看本地数据位置</button></section>${await renderMigrationEntry()}`;
}

async function renderMigrationEntry() {
  let ready=false;
  try {const capabilities=await api('/api/migrations/capabilities');ready=capabilities.new_projects===true&&capabilities.legacy_json===true&&capabilities.copy_project===true;} catch {}
  return `<section class="panel"><h3>导入或复制为新项目</h3>${ready?'':'<p class="hint">当前运行后端尚未加载迁移功能，或能力暂无法确认。</p>'}<p class="hint">V1完整备份包、兼容SQLite库、旧小说或工作区JSON按内容识别。库来源导入全部小说与全部全局Skills；保留已有小说，复制本使用新编号并独立编辑。Skills在当前库全局共享：同ID全字段相同才复用，冲突另编号，同名资料不会去重。只导入已保存内容，请先保存需要迁移的输入。</p><div class="field"><label for="migration-file">迁移来源文件</label><input id="migration-file" type="file" accept=".nwbak,.sqlite3,.sqlite,.db,.json" data-passive ${ready?'':'disabled'}></div><button id="preview-import-projects" type="button" ${ready?'':'disabled'}>预检迁移来源</button><button id="preview-copy-project" type="button" ${ready&&workspace?'':'disabled'}>预检当前小说副本</button><button id="import-projects" type="button" ${ready?'':'disabled'}>导入为新项目</button><button id="copy-project" type="button" ${ready&&workspace?'':'disabled'}>复制当前小说为新项目</button><button id="check-migration-operation" type="button" ${ready?'':'disabled'}>核对上次迁移结果</button><button id="cancel-migration-operation" type="button" hidden>取消当前迁移</button><p class="hint">旧JSON没有完整整书快照或全局Skills，结果会列出缺失范围；初始导入快照不代表原历史。SQLite文件若有WAL未合并，请优先从源工作台下载完整备份包。</p><p id="migration-result" class="path-display" role="status">${escapeHTML(pendingMigrationOperation?'待核对操作：'+pendingMigrationOperation:'')}</p><details><summary>查看编号映射与完整报告</summary><pre id="migration-report" class="path-display"></pre></details></section>`;
}

async function showMigrationCompletion(result) {
  const names={project_snapshots:'完整整书历史',skills:'全局Skills',ideas:'IDEA',worldbuilding:'世界观',writing_rules:'文风规则',entity_versions:'实体版本历史'};
  const missing=result.missing_scopes?.map(key=>names[key]||key)||[];
  const reused=result.skills.filter(s=>s.action==='reused').length;
  const draftNotice=result.sensitive_fields_required?'草稿中的敏感字段已移除，请在恢复的草稿中重新填写。':'';
  const droppedNotice=result.drafts_dropped?.length?`已丢弃 ${result.drafts_dropped.length} 份无法确认归属的草稿，详见报告。`:'';
  $('#migration-result').textContent=`迁移完成，已核对落盘数据。${result.state==='already_present'?'原操作已完成，本次未重复导入。':''}新项目 ${result.projects.length} 个，全局Skills ${result.skills.length} 条（复用 ${reused} 条）。${missing.length?'来源缺少：'+missing.join('、')+'。':''}${result.legacy_notice||''}${result.normalizations?.length?' 补齐默认字段 '+result.normalizations.length+' 项，详见报告。':''}${draftNotice}${droppedNotice}${result.cleanup_warnings?.join(' ')||''}`;
  $('#migration-report').textContent=JSON.stringify(result,null,2);
  rememberMigrationOperation('');
  await refreshProjects();
}

function showMigrationPreview(result) {
  $('#migration-result').textContent=`预检完成，当前库未写入。计划新项目 ${result.projects.length} 个、全局Skills ${result.skills.length} 条：复用 ${result.skills.filter(s=>s.action==='reused').length}、冲突另编号 ${result.skills.filter(s=>s.action==='remapped').length}、保留编号新增 ${result.skills.filter(s=>s.action==='inserted').length}。${result.missing_scopes.length?'来源缺少 '+result.missing_scopes.join('、')+'。':''}请核对完整报告后，使用相同文件或当前小说执行导入/复制。`;
  $('#migration-report').textContent=JSON.stringify(result,null,2);
}

async function checkMigrationOperation() {
  if(!pendingMigrationOperation) {$('#migration-result').textContent+=' 当前没有待核对的迁移操作。';return;}
  try {
    const result=await api('/api/migrations/operations/'+pendingMigrationOperation);
    if(result.state==='already_present')await showMigrationCompletion(result);
    else $('#migration-result').textContent=`操作 ${pendingMigrationOperation}：${result.state==='running'?'仍在运行，请稍后核对。':'尚未提交，请使用同一来源和编号重试；没有创建半项目。'}`;
  } catch(error) {
    if(error.status===404) {rememberMigrationOperation('');$('#migration-result').textContent+=' 未建立迁移收据，未提交此操作。';}
    else $('#migration-result').textContent=`迁移结果待核对：${error.message}。请保留原文件与操作编号 ${pendingMigrationOperation}。`;
  }
}

async function transferMigration(copy=false,preview=false) {
  const file=$('#migration-file').files[0];
  if(!copy&&!file) {$('#migration-result').textContent='请先选择迁移来源文件。';return;}
  if(copy&&!workspace)return;
  rememberMigrationOperation(pendingMigrationOperation||crypto.randomUUID());
  activeMigrationOperation=pendingMigrationOperation;
  setBusy(true);
  const cancelButton=$('#cancel-migration-operation');cancelButton.hidden=false;cancelButton.disabled=false;
  $('#migration-result').textContent=copy?'正在复制已保存小说及全部历史…':'正在识别来源、完整预检并导入新项目…';
  $('#migration-report').textContent='';
  try {
    const result=await api(copy?'/api/migrations/copy':'/api/migrations/import',{
      method:'POST',body:copy?JSON.stringify({operation_id:activeMigrationOperation,project_id:workspace.document.project.id,preview}):file,
      headers:copy?{}:{'Content-Type':'application/octet-stream','X-Novel-Migration-Operation':activeMigrationOperation,'X-Novel-Migration-Preview':preview?'1':'0'}
    });
    if(result.state==='ready')showMigrationPreview(result);else await showMigrationCompletion(result);
  } catch(error) {
    $('#migration-result').textContent=`迁移失败：${error.message}`;
    await checkMigrationOperation();
  } finally {activeMigrationOperation='';cancelButton.hidden=true;setBusy(false);}
}

async function cancelMigrationOperation() {
  if(!activeMigrationOperation)return;
  try {
    const result=await api('/api/migrations/operations/'+activeMigrationOperation+'/cancel',{method:'POST',body:'{}'});
    if(result.state==='already_present')await showMigrationCompletion(result);
    else $('#migration-result').textContent='已请求取消，请等待最终结果；提交若已先完成，仍会如实报告。';
  } catch(error) {$('#migration-result').textContent='取消结果待核对：'+error.message;}
}

async function transferBackup(restore=false) {
  const output=$('#backup-result');
  const file=$('#backup-file').files[0];
  if(restore&&!file) { notify('请先选择完整备份包。',true);return; }
  if(restore) { rememberBackupOperation(pendingBackupOperation||crypto.randomUUID());activeBackupOperation=pendingBackupOperation; }
  setBusy(true);
  const cancelButton=$('#cancel-backup-operation');
  if(restore) {cancelButton.hidden=false;cancelButton.disabled=false;}
  output.textContent=restore?'正在上传、完整校验并恢复到新目录…':'正在生成并校验完整库备份…';
  output.removeAttribute('data-database-path');
  try {
    const result=await api(restore?'/api/backups/restore':'/api/backups/export',{
      method:'POST',body:restore?file:'{}',headers:restore?{'Content-Type':'application/octet-stream','X-Novel-Backup-Operation':activeBackupOperation}:{}
    });
    if(restore) {
      showBackupCompletion(result);
    } else {
      const saved=await downloadFile(result.download_url,'novel-library.nwbak');if(!saved){output.textContent='已取消保存。';return;}
      output.textContent='\u5b8c\u6574\u5907\u4efd\u5305\u5df2\u6821\u9a8c\uff0c\u5df2\u8bf7\u6c42\u4e0b\u8f7d\uff1b\u8bf7\u786e\u8ba4\u6587\u4ef6\u5df2\u4fdd\u5b58\u3002'+draftDropSummary(result.drafts_dropped);
      notify('备份包含全部项目历史与 Skills，凭据已排除。');
    }
    if(result.cleanup_warnings?.length)output.textContent+=' '+result.cleanup_warnings.join(' ');
  } catch(error) {
    output.textContent=`操作失败：${error.message}`;notify(error.message,true);
    if(restore)await checkBackupOperation();
  }
  finally { activeBackupOperation='';cancelButton.hidden=true;setBusy(false); }
}

function showBackupCompletion(result) {
  const output=$('#backup-result');output.dataset.databasePath=result.database_path;
  output.textContent=`\u6062\u590d\u5b8c\u6210\uff0c\u843d\u76d8\u91cd\u5f00\u6821\u9a8c\u901a\u8fc7\u3002\u72ec\u7acb\u6570\u636e\u5e93\uff1a${result.database_path}\u3002\u53ef\u7528\u542f\u52a8\u53c2\u6570 --database \u6307\u5411\u6b64\u6587\u4ef6\u6253\u5f00\uff1b\u5f53\u524d\u5de5\u4f5c\u53f0\u7ee7\u7eed\u4f7f\u7528\u539f\u5e93\u3002${result.sensitive_fields_required?' \u8349\u7a3f\u4e2d\u7684\u654f\u611f\u5b57\u6bb5\u5df2\u79fb\u9664\uff0c\u8bf7\u91cd\u586b\u5199\u3002':''}${draftDropSummary(result.drafts_dropped)}`;
  if(result.extension_dependencies?.length)output.textContent+=` 已保留 ${result.extension_dependencies.length} 个扩展模板依赖；本机启用和能力许可未继承，请打开恢复库后在“受控数据模板”逐版本核对并授权。`;
  rememberBackupOperation('');notify('独立恢复完成，当前工作台仍使用原库。');
}
function draftDropSummary(items) {
  return items?.length ? ` \u5df2\u9010\u9879\u4e22\u5f03\u65e0\u6cd5\u786e\u8ba4\u5f52\u5c5e\u7684\u8349\u7a3f\uff1a${items.map(item => `${item.document_key || item.file_name}\uff08${item.reason}\uff09`).join('\uff1b')}\u3002` : '';
}
async function checkBackupOperation() {
  if(!pendingBackupOperation) {notify('当前没有待核对的恢复操作。');return;}
  const identity=pendingBackupOperation,output=$('#backup-result');
  try {
    const result=await api('/api/backups/operations/'+identity);
    if(result.state==='completed')showBackupCompletion(result);
    else output.textContent=`操作 ${identity}：${result.state==='running'?'仍在运行，请稍后核对结果。':'目标尚未发布；重新选择同一备份包可按原编号重试。'}`;
  } catch(error) {
    if(error.status===404) {rememberBackupOperation('');output.textContent+=` 操作 ${identity} 未建立恢复收据，未发布新目标。`;}
    else output.textContent=`操作 ${identity} 状态尚无法核对：${error.message}。请保留同一包与编号，勿重复新建。`;
  }
}
async function cancelBackupOperation() {
  if(!activeBackupOperation)return;
  try {
    const result=await api('/api/backups/operations/'+activeBackupOperation+'/cancel',{method:'POST',body:'{}'});
    if(result.state==='completed')showBackupCompletion(result);
    else $('#backup-result').textContent='已请求取消，请等待最终结果；发布若已先完成，仍会报告恢复完成。';
  } catch(error) {notify(error.message,true);}
}

async function renderSkills() {
  const skills = await api('/api/skills');
  if (!skills.some(item => item.id === selectedSkill)) selectedSkill = skills[0]?.id || '';
  const skill = selectedSkill ? await api(`/api/skills/${selectedSkill}`) : null;
  if(skill)textareaValues.set('skill-source',skill.files.find(item=>item.path===skill.primary_path)?.content||'');
  return `<section class="panel skill-import"><h2>把自己的 Skills 放进资料库</h2><p class="hint">单个 SKILL.md 或包含它的技能文件夹。只保存 Markdown 文字，不执行脚本；最多 100 个文件，总计 2 MiB。</p><div class="field-grid"><div class="field"><label for="skill-file">选择 SKILL.md</label><input id="skill-file" type="file" accept=".md" data-passive></div><div class="field"><label for="skill-folder">或选择技能文件夹</label><input id="skill-folder" type="file" webkitdirectory multiple data-passive></div></div><button id="import-skill" class="primary" type="button">导入所选资料</button><p class="hint">文件夹中的非 Markdown 文件会跳过。每次只选择一个技能；导入后不会自动安装到 Codex。</p></section><div class="skills-grid"><section class="panel"><h3>已导入技能 · ${skills.length}</h3>${skills.length ? skills.map(item => `<button class="skill-item ${item.id === selectedSkill ? 'active' : ''}" data-skill="${item.id}">${escapeHTML(item.name)}</button>`).join('') : '<p class="hint">还没有导入资料。</p>'}</section><section class="panel">${skill ? `<h2>${escapeHTML(skill.name)}</h2><p class="hint">${escapeHTML(skill.description || '查看原始资料。')}</p><div class="field"><label for="skill-source-select">资料文件</label><select id="skill-source-select" data-passive>${skill.files.map(item => `<option value="${escapeHTML(item.path)}" ${item.path === skill.primary_path ? 'selected' : ''}>${escapeHTML(item.path)}</option>`).join('')}</select></div><textarea id="skill-source" class="skill-source" readonly aria-label="技能原文" data-passive></textarea>` : '<h2>资料会完整保留</h2><p class="hint">导入后查看技能说明和参考文档，由作者明确选择哪些资料进入任务上下文。</p>'}</section></div>`;
}

async function showSkillSource() {
  const selection = $('#skill-source-select');
  if (!selection) return;
  const skill = await api(`/api/skills/${selectedSkill}`);
  $('#skill-source').value = skill.files.find(item => item.path === selection.value)?.content || '';
}

function captureChatScroll(){
  const content=$('#content');
  if(content.dataset.renderedView!=='chat')return null;
  return {project:content.dataset.renderedProject,top:content.scrollTop,
    nearBottom:content.scrollHeight-content.clientHeight-content.scrollTop<=64};
}

async function renderMain() {
  resetAgentView();
  stopAnnotations();
  const entryChatScroll=captureChatScroll();
  const targetProject=workspace?.document.project.id||'',targetView=view;
  if(stopWorkflowPolling){stopWorkflowPolling();stopWorkflowPolling=null;}
  if(bookAiPollTimer){clearTimeout(bookAiPollTimer);bookAiPollTimer=null;}
  if(styleTimer){clearTimeout(styleTimer);styleTimer=null;}
  if(publicSearchTimer){clearTimeout(publicSearchTimer);publicSearchTimer=null;}
  if(styleTrialTimer){clearTimeout(styleTrialTimer);styleTrialTimer=null;}
  $('#start-book-creation').textContent=t('creation.open');
  if(comparisonTimer){clearTimeout(comparisonTimer);comparisonTimer=null;}
  previewRequest++;
  taskPreview=null;if(taskPollTimer){clearTimeout(taskPollTimer);taskPollTimer=null;}
  retrievalRequest++;
  const renderId = ++rendering;
  if (workspace) {
    const archived=archivedChapterIds(workspace),visible=[...workspace.document.chapters].sort((a,b)=>a.number-b.number).filter(item=>!archived.has(item.id));
    if (!visible.some(item=>item.id===selectedChapter)) selectedChapter=visible[0]?.id||'';
    if (!workspace.document.characters.some(item=>item.id===selectedCharacter)) selectedCharacter=workspace.document.characters[0]?.id||'';
  }
  renderChrome();
  layout.setView(view);
  renderPrompt();
  textareaValues.clear();
  let html;
  if (view === 'chat') {
    html=await renderAgentChat(workspace);
  }
  else if(view==='creation'){bookCreationData=workspace?await api('/api/projects/'+encodeURIComponent(workspace.document.project.id)+'/book-creation'):null;bookAiData=workspace&&bookCreationData?.selected?await api('/api/projects/'+encodeURIComponent(workspace.document.project.id)+'/book-ai'):null;bookAiCaps=bookAiData?await api('/api/tasks/capabilities'):null;html=renderBookCreation(workspace,bookCreationData)+(bookAiData?renderBookAI(workspace,bookCreationData,bookAiData,bookAiCaps):'');}
  else if(view==='annotations'&&workspace)html=renderAnnotations();
  else if (view === 'preview'&&workspace)html=renderPreview(workspace,selectedChapter,searchSelections);
  else if(view==='tasks'&&workspace)html=await taskEntry();
  else if(view==='reviews'&&workspace)html=await reviewEntry();
  else if(view==='compose'&&workspace){const caps=await api('/api/tasks/capabilities');html=renderChapterWritingPrepare(workspace,selectedChapter,chapterWritingMode,caps);}
  else if(view==='planning'&&workspace){const project=workspace.document.project.id,base='/api/projects/'+encodeURIComponent(project)+'/chapter-planning',caps=await api('/api/tasks/capabilities');chapterPlanningListing=await api(base);if(!chapterPlanningListing.tasks.some(v=>v.task.id===selectedPlanningTask))selectedPlanningTask=chapterPlanningListing.tasks.at(-1)?.task.id||'';chapterPlanningDetail=selectedPlanningTask?await api(base+'/'+selectedPlanningTask):null;html=renderChapterPlanningPrepare(workspace,selectedChapter,chapterPlanningMode,caps)+(chapterPlanningDetail?renderChapterPlanningTask(workspace,chapterPlanningListing,chapterPlanningDetail,caps):'');}
  else if(view==='expansion'&&workspace){const project=workspace.document.project.id,base='/api/projects/'+encodeURIComponent(project)+'/scene-expansion',caps=await api('/api/tasks/capabilities');expansionListing=await api(base);if(!expansionListing.tasks.some(v=>v.task.id===selectedExpansionTask))selectedExpansionTask=expansionListing.tasks.at(-1)?.task.id||'';expansionDetail=selectedExpansionTask?await api(base+'/'+selectedExpansionTask):null;html=renderSceneExpansionPrepare(workspace,selectedChapter,expansionRange,caps)+(expansionDetail?renderSceneExpansionTask(workspace,expansionListing,expansionDetail,caps):'');}
  else if(view==='migration'&&workspace)html=renderMigration(workspace);
  else if(view==='model-prepare'&&workspace){const caps=await api('/api/tasks/capabilities');html=renderModelPrepare(workspace,selectedChapter,caps);$('#model-status').textContent=caps.real_model_enabled?'模型任务允许 · 需单次确认':'真实模型关闭';}
  else if(view==='model-review'&&workspace)html=await modelReviewEntry();
  else if(view==='comparisons'&&workspace)html=await comparisonEntry();
  else if(view==='extensions'&&workspace){extensionData=await api('/api/projects/'+encodeURIComponent(workspace.document.project.id)+'/extensions');html=renderExtensions(workspace,extensionData);}
  else if(view==='workflows'&&workspace)html=await workflowEntry();
  else if(view==='knowledge'&&workspace){const options=knowledgeOptions(workspace.document.project.id,selectedChapter||activeChapters(workspace)[0]?.id),base=`/api/projects/${encodeURIComponent(workspace.document.project.id)}/knowledge/`;const [data,caps,proposals]=await Promise.all([api(base+'query',{method:'POST',body:JSON.stringify(options)}),api('/api/tasks/capabilities'),api(base+'extract-list',{method:'POST',body:JSON.stringify(options.chapter_id?{chapter_id:options.chapter_id}:{})})]);Object.assign(data,{graph_options:options,graph_caps:caps,graph_extractions:proposals.extractions});html=renderKnowledge(workspace,data);knowledgeData=data;}
  else if(view==='materials'&&workspace){
    const project=workspace.document.project.id,base=`/api/projects/${encodeURIComponent(project)}/materials`;
    materialsData=await api(base);
    if(!materialsData.materials.some(value=>value.id===selectedMaterial))selectedMaterial=materialsData.materials[0]?.id||'';
    materialsDetail=selectedMaterial?await api(`${base}/${encodeURIComponent(selectedMaterial)}`):null;
    materialCurrentVersion=materialsDetail?await api(`${base}/${encodeURIComponent(selectedMaterial)}/versions/${encodeURIComponent(materialsDetail.material.current_version_id)}`):null;
    html=renderMaterials(workspace,materialsData,materialsDetail,materialCurrentVersion);
  }
  else if (view === 'retrieval'&&workspace){
    const project=workspace.document.project.id;
    html=renderRetrieval(workspace,selectedChapter,await api('/api/skills'),await api(`/api/projects/${encodeURIComponent(project)}/materials`))+renderSemanticRetrieval();
  }
  else if (view === 'memory'&&workspace) {
    const entries=await api(`/api/projects/${workspace.document.project.id}/memories`);
    if(selectedMemory!=='new'&&!entries.some(m=>m.id===selectedMemory))selectedMemory=entries[0]?.id||'new';
    memoryRollupData=await api(`/api/projects/${encodeURIComponent(workspace.document.project.id)}/rollups`);
    if(!memoryRollupForm||memoryRollupForm.project!==workspace.document.project.id)memoryRollupForm={project:workspace.document.project.id,scope:'book',scope_volume_number:workspace.document.book_outline?.volumes?.[0]?.number??null,through_chapter_id:selectedChapter||workspace.document.chapters[0]?.id||''};
    summaryCapabilities=await api('/api/tasks/capabilities');
    html=renderMemories(workspace,entries,selectedMemory,selectedChapter,memoryRollupData,memoryRollupForm,memoryRollupPreview)+renderSummaryPrepare(workspace,selectedChapter,summaryCapabilities);
  }
  else if (view === 'history') html=await renderHistoryEntry();
  else if (view === 'guide') {
    const response = await fetch('/guide.html');
    if (!response.ok) throw new Error('使用指南读取失败。');
    html = await response.text();
  } else if (view === 'modules') html = await renderModules();
  else if (view === 'settings') html = await renderSettings();
  else if (view === 'skills') html = await renderSkills();
  else if (!workspace) html = '<div class="empty-state welcome"><p class="eyebrow">A PLACE FOR YOUR STORIES</p><h2>一本长篇，需要一个安静的起点。</h2><p>大纲、人物、灵感与正文，都放在这本书里。<br>从第一章开始，也把每一次修改留下来。</p><button class="primary" data-create="project">创建第一本小说</button><div class="welcome-steps"><span><b>01</b>整理故事与人物</span><span><b>02</b>记录 IDEA，写下正文</span><span><b>03</b>保存每一版内容</span></div></div>';
  else if (view === 'project') html = renderProject(workspace)+renderAuthorScope(workspace);
  else if (view === 'outline') {if(workspace)fullBookPlanningData=await api('/api/projects/'+encodeURIComponent(workspace.document.project.id)+'/full-book-planning');html = renderOutline(workspace)+(workspace?renderFullBookPlanning(workspace,fullBookPlanningData):'');}
  else if (view === 'writing') html = renderWriting(workspace, selectedChapter, writingPane)+(writingPane==='body'?renderAuthorScope(workspace,selectedChapter):'')+renderChapterManagement(workspace,selectedChapter);
  else if (view === 'characters') html = renderCharacters(workspace, selectedCharacter);
  else if (view === 'world') html = panelForm('save_worldbuilding', '故事发生的世界', '记录地点、组织、力量体系，以及不能随意改变的设定。', field('content', '世界观与设定', workspace.worldbuilding, true, false, 'edit', 'tall'), '保存世界观');
  else if (view === 'rules') {styleTrialData=await loadStyleTrials(workspace);publicSearchData=await loadPublicSearch(workspace);styleData=await loadStyles(workspace);rulesData=await api('/api/projects/'+encodeURIComponent(workspace.document.project.id)+'/rules');ruleResolved=selectedChapter?await api('/api/projects/'+encodeURIComponent(workspace.document.project.id)+'/rules/resolve/'+encodeURIComponent(selectedChapter)):null;html=renderScopedRules(workspace,rulesData,selectedChapter,ruleResolved)+renderStyleTrials(workspace,styleTrialData)+renderPublicSearch(workspace,publicSearchData)+renderStyles(workspace,styleData)+panelForm('save_writing_rules', '保持这本书的声音', '写下叙事视角、语言节奏和表达偏好，供后续写作参考。旧规则会作为本书级 legacy 指引继续生效。', field('content', '文风与写作规则', workspace.writing_rules, true, false, 'edit', 'tall'), '保存写作规则');}
  if (renderId !== rendering || view!==targetView || (workspace?.document.project.id||'')!==targetProject) return;
  // Read the still-rendered DOM immediately before replacement: the author may
  // have scrolled while the asynchronous requests were pending.
  const latestChatScroll=captureChatScroll();
  const chatScroll=latestChatScroll||entryChatScroll;
  const content=$('#content');
  content.innerHTML = html;
  if(busy)disableBusyControls();
  content.dataset.renderedProject=targetProject;
  content.dataset.renderedView=targetView;
  if(view==='chat'||view==='settings')bindAgentPage({
    project:()=>workspace?.document.project.id||'',notice:notify,
    refresh:async (project,options={})=>{
      const current=()=>renderId===rendering&&view===targetView&&(workspace?.document.project.id||'')===targetProject;
      if(!current()||(project||'')!==targetProject)return;
      if(project){
        const fresh=await api('/api/projects/'+encodeURIComponent(project));
        if(!current())return;
        workspace=fresh;
      }
      if(!options.sessionOnly){
        const listing=await api('/api/projects');
        if(!current())return;
        projects=listing;
      }
      if(!current())return;
      await renderMain();
    }
  });
  const heading=$('#content form[data-action] .panel-heading');
  $('#editor-toolbar').replaceChildren();
  $('#editor-toolbar').hidden=!heading;
  if(heading) $('#editor-toolbar').append(heading);
  textareaValues.forEach((value, id) => { document.getElementById(id).value = value; });
  rememberDocument();
  if(targetView==='chat'){
    baseline={};dirty=false;
    $('#draft-review').hidden=true;
    saveIndicator();updateWordCount();
    requestAnimationFrame(()=>{
      if(renderId!==rendering || view!==targetView || (workspace?.document.project.id||'')!==targetProject ||
         content.dataset.renderedProject!==targetProject || content.dataset.renderedView!==targetView)return;
      const sameProject=chatScroll?.project===targetProject;
      content.scrollTop=!sameProject||chatScroll.nearBottom?content.scrollHeight:chatScroll.top;
    });
  }else hydrateDraft();
  renderChapterTree();
  renderContext(); updateModeChrome();
  if(view==='retrieval'&&workspace)bindSemanticRetrieval($('#semantic-retrieval'),workspace,{jump:async(result,index)=>{if(!result||result.project_id!==workspace?.document.project.id)return;localSearchResult=result;await jumpSearchSource(index);},selected:async(result,indexes)=>{if(!result||result.project_id!==workspace?.document.project.id)return;searchSelections=indexes.map(i=>result.hits[i].selection);selectedChapter=$('#local-search-form').elements.chapter_id.value;await navigate('preview');}});
  if(workspace&&(view==='writing'||view==='project'))bindAuthorScope($('#author-scope'),workspace,view==='writing'?selectedChapter:null,{busy:setBusy,notice:notify,refresh:async()=>{workspace=await api('/api/projects/'+encodeURIComponent(workspace.document.project.id));projects=await api('/api/projects');renderLibrary();await renderMain();}});
  if(view==='annotations'&&workspace){const project=targetProject;const current=()=>renderId===rendering&&view==='annotations'&&workspace?.document.project.id===project;bindAnnotations($('#annotations-root'),workspace,selectedChapter,{current,notice:notify,workspace:fresh=>{if(current()&&fresh.document.project.id===project)workspace=fresh;}});}
   if(view==='settings')bindProviderManagement({busy:setBusy,notice:notify,refresh:renderMain});
  if(view==='settings')bindLocalData($('#local-data-safety'),{notice:notify,retryDrafts:retryDiskDrafts});
  if(view==='writing'&&workspace)bindChapterManagement(workspace,selectedChapter,{busy:setBusy,notice:notify,refresh:async()=>{workspace=await api('/api/projects/'+encodeURIComponent(workspace.document.project.id));const hidden=archivedChapterIds(workspace);if(hidden.has(selectedChapter))selectedChapter=workspace.document.chapters.find(c=>!hidden.has(c.id))?.id||'';await renderMain();}});
  if(view==='compose'&&workspace){const project=workspace.document.project.id,epoch=rendering,caps=await api('/api/tasks/capabilities');bindChapterWritingPrepare($('#chapter-writing-prepare'),workspace,selectedChapter,chapterWritingMode,caps,{busy:setBusy,notice:notify,settings:()=>navigate('settings'),editor:()=>navigate('writing'),refresh:async()=>{if(view!=='compose'||workspace?.document.project.id!==project||rendering!==epoch)return;workspace=await api('/api/projects/'+encodeURIComponent(project));await renderMain();},compared:async id=>{if(workspace?.document.project.id!==project)return;selectedComparison=id;workspace=await api('/api/projects/'+encodeURIComponent(project));await navigate('comparisons');},prepared:async id=>{if(view!=='compose'||workspace?.document.project.id!==project)return;selectedTask=id;workspace=await api('/api/projects/'+encodeURIComponent(project));view='tasks';await renderMain();}});}
  if(view==='planning'&&workspace){const project=workspace.document.project.id,epoch=rendering,caps=await api('/api/tasks/capabilities');const current=()=>view==='planning'&&workspace?.document.project.id===project&&rendering===epoch;const refresh=async()=>{if(!current())return;workspace=await api('/api/projects/'+encodeURIComponent(project));await renderMain();};bindChapterPlanningPrepare($('#chapter-planning-prepare'),workspace,selectedChapter,chapterPlanningMode,caps,{busy:setBusy,notice:notify,settings:()=>navigate('settings'),editor:()=>navigate('writing'),mode:value=>{chapterPlanningMode=value;},refresh,compared:async id=>{if(workspace?.document.project.id!==project)return;selectedComparison=id;workspace=await api('/api/projects/'+encodeURIComponent(project));await navigate('comparisons');},prepared:async id=>{if(!current())return;selectedPlanningTask=id;await refresh();}});if(chapterPlanningDetail)bindChapterPlanningTask($('#chapter-planning-task'),workspace,chapterPlanningDetail,{busy:setBusy,notice:notify,editor:()=>navigate('writing'),refresh,select:async id=>{selectedPlanningTask=id;await refresh();},draft:async chapterId=>{chapterWritingMode='draft';selectedChapter=chapterId;await navigate('compose');}});}
  if(view==='expansion'&&workspace){const project=workspace.document.project.id,epoch=rendering,caps=await api('/api/tasks/capabilities');const current=()=>view==='expansion'&&workspace?.document.project.id===project&&rendering===epoch;const refresh=async()=>{if(!current())return;workspace=await api('/api/projects/'+encodeURIComponent(project));await renderMain();};bindSceneExpansionPrepare($('#scene-expansion-prepare'),workspace,selectedChapter,expansionRange,caps,{busy:setBusy,notice:notify,settings:()=>navigate('settings'),editor:()=>{expansionRange=null;return navigate('writing');},refresh,compared:async id=>{if(workspace?.document.project.id!==project)return;selectedComparison=id;workspace=await api('/api/projects/'+encodeURIComponent(project));await navigate('comparisons');},prepared:async id=>{if(!current())return;selectedExpansionTask=id;await refresh();}});if(expansionDetail)bindSceneExpansionTask($('#scene-expansion-task'),workspace,expansionDetail,{busy:setBusy,notice:notify,editor:()=>{expansionRange=null;return navigate('writing');},refresh,select:async id=>{selectedExpansionTask=id;await refresh();}});}
  if(view==='migration'&&workspace){const project=workspace.document.project.id,epoch=rendering;bindMigration($('#migration-root'),workspace,{busy:setBusy,notice:notify,revision:()=>workspace.revision,refresh:async()=>{if(view!=='migration'||workspace?.document.project.id!==project||rendering!==epoch)return;workspace=await api('/api/projects/'+encodeURIComponent(project));await renderMain();}});}
  if(view==='chat'&&workspace&&$('#console-root')){const project=workspace.document.project.id,epoch=rendering;const current=()=>view==='chat'&&workspace?.document.project.id===project&&rendering===epoch;const refresh=async()=>{if(!current())return;workspace=await api('/api/projects/'+encodeURIComponent(project));await renderMain();};bindConsole($('#console-root'),workspace,consoleListing,consoleDetail,await api('/api/tasks/capabilities'),{busy:setBusy,notice:notify,refresh,openTask:async(engine,task)=>{if(engine==='chapter_planning'){selectedPlanningTask=task;await navigate('planning');}else if(engine==='scene_expansion'){selectedExpansionTask=task;await navigate('expansion');}else{selectedTask=task;await navigate('tasks');}}},consoleRunListing,consoleRunDetail);}
  if(view==='tasks')hydrateTaskPanel();
  if(view==='rules'&&workspace){const project=workspace.document.project.id;styleTimer=bindStyles($('#styles-root'),workspace,styleData,{busy:setBusy,settings:()=>navigate('settings'),refresh:async()=>{if(view!=='rules'||workspace?.document.project.id!==project)return;workspace=await api('/api/projects/'+encodeURIComponent(project));await renderMain();}});}
  if(view==='rules'&&workspace){const project=workspace.document.project.id;$('#scoped-rules-panel').insertAdjacentHTML('afterend',renderRuleReviews());void bindRuleReviews($('#rule-reviews'),workspace);bindScopedRules($('#scoped-rules-panel'),workspace,rulesData,selectedChapter,{busy:setBusy,notice:notify,refresh:async()=>{if(view!=='rules'||workspace?.document.project.id!==project)return;workspace=await api('/api/projects/'+encodeURIComponent(project));await renderMain();},resolve:async chapterId=>{selectedChapter=chapterId;workspace=await api('/api/projects/'+encodeURIComponent(project));await renderMain();}});}
  if(view==='rules'&&workspace){const project=workspace.document.project.id;styleTrialTimer=bindStyleTrials($('#style-trial-panel'),workspace,styleTrialData,{busy:setBusy,settings:()=>navigate('settings'),refresh:async()=>{if(view!=='rules'||workspace?.document.project.id!==project)return;workspace=await api('/api/projects/'+encodeURIComponent(project));await renderMain();}});}
  if(view==='rules'&&workspace){const project=workspace.document.project.id;publicSearchTimer=bindPublicSearch($('#public-search-panel'),workspace,publicSearchData,{busy:setBusy,settings:()=>navigate('settings'),useStyleSource:id=>selectStyleSource(project,id),refresh:async()=>{if(view!=='rules'||workspace?.document.project.id!==project)return;workspace=await api('/api/projects/'+encodeURIComponent(project));await renderMain();}});}
  if(view==='materials'&&workspace){const project=workspace.document.project.id;bindMaterials($('#materials-root'),workspace,materialsData,{busy:setBusy,notice:notify,select:async id=>{if(view!=='materials'||workspace?.document.project.id!==project)return;selectedMaterial=id;materialCurrentVersion=null;await renderMain();},refresh:async id=>{if(view!=='materials'||workspace?.document.project.id!==project)return;if(id)selectedMaterial=id;workspace=await api(`/api/projects/${encodeURIComponent(project)}`);await renderMain();}});}
  if(view==='outline'&&workspace){const project=workspace.document.project.id,epoch=rendering;bindFullBookPlanning($('#full-book-planning-root'),workspace,fullBookPlanningData,{busy:setBusy,notice:notify,refresh:async()=>{if(view!=='outline'||workspace?.document.project.id!==project||rendering!==epoch)return;workspace=await api('/api/projects/'+encodeURIComponent(project));await renderMain();}});}
  if(view==='creation'){const refresh=async project=>{if(view!=='creation')return;const selected=project||workspace?.document.project.id;if(selected){workspace=await api('/api/projects/'+encodeURIComponent(selected));sessionStorage.setItem('novel-project',selected);}await refreshProjects();await renderMain();};bindBookCreation($('#creation-flow'),workspace,bookCreationData,{busy:setBusy,writing:()=>navigate('writing'),refresh});if(bookAiData)bookAiPollTimer=bindBookAI($('#book-ai-panel'),workspace,bookCreationData,bookAiData,bookAiCaps,{busy:setBusy,refresh,settings:()=>navigate('settings')});}
  if(view==='settings'&&workspace&&creationPresetData){const project=workspace.document.project.id;bindCreationPresets($('#creation-presets'),workspace,creationPresetData,{busy:setBusy,notice:notify,applied:()=>resetModelPreparation(project),refresh:async()=>{if(view!=='settings'||workspace?.document.project.id!==project)return;workspace=await api('/api/projects/'+encodeURIComponent(project));await renderMain();}});}
  if(view==='reviews')hydrateReviewDrafts();
  if(view==='workflows'&&workspace){const project=workspace.document.project.id,epoch=rendering;const current=()=>workspace?.document.project.id===project&&view==='workflows'&&epoch===rendering;const refresh=async()=>{if(!current())return;workspace=await api('/api/projects/'+encodeURIComponent(project));await renderMain();};stopWorkflowPolling=bindWorkflow($('#workflow-panel'),workspace,workflowData.listing,workflowData.view,selectedChapter,{refresh,created:async id=>{if(!current())return;selectedWorkflow=id;await refresh();}});}
  if(view==='comparisons'&&workspace){const project=workspace.document.project.id,epoch=rendering;const current=()=>workspace?.document.project.id===project&&view==='comparisons'&&epoch===rendering;const refresh=async()=>{if(!current())return;workspace=await api('/api/projects/'+encodeURIComponent(project));await renderMain();};bindComparison($('#comparison-panel'),workspace,selectedChapter,comparisonData,{refresh,created:async id=>{if(!current())return;selectedComparison=id;await refresh();},newExperiment:async()=>{if(current()){selectedComparison='new';await renderMain();}},openCandidate:async id=>{if(!current())return;workspace=await api('/api/projects/'+encodeURIComponent(project));if(workspace.scene_expansion_tasks?.some(v=>v.id===id)){selectedExpansionTask=id;selectedChapter=workspace.scene_expansion_tasks.find(v=>v.id===id).chapter_id;await navigate('expansion');}else if(workspace.chapter_planning_tasks?.some(v=>v.id===id)){selectedPlanningTask=id;selectedChapter=workspace.chapter_planning_tasks.find(v=>v.id===id).chapter_id;await navigate('planning');}else if(workspace.style_trial_tasks?.some(v=>v.id===id)){selectStyleTrialTask(project,id);await navigate('rules');}else{selectedTask=id;await navigate('tasks');}},usePreset:async settings=>{if(!current())return;useGenerationPreset(project,selectedChapter,settings);await navigate('model-prepare');}});if(comparisonData.setup?.executing)comparisonTimer=setTimeout(()=>refresh().catch(e=>notify(e.message,true)),200);}
  if(view==='extensions'&&workspace){const project=workspace.document.project.id,epoch=rendering;bindExtensions($('#extension-panel'),workspace,extensionData,selectedChapter,async()=>{if(workspace?.document.project.id!==project||view!=='extensions'||epoch!==rendering)return;workspace=await api('/api/projects/'+encodeURIComponent(project));await renderMain();});}
  if(view==='model-prepare'&&workspace){const project=workspace.document.project.id,epoch=rendering;bindModelPrepare($('#model-preparation'),workspace,selectedChapter,async id=>{if(workspace?.document.project.id!==project||view!=='model-prepare'||epoch!==rendering)return;selectedTask=id;workspace=await api('/api/projects/'+encodeURIComponent(project));view='tasks';await renderMain();});}
  if(view==='memory'&&workspace&&summaryCapabilities){const project=workspace.document.project.id;bindSummaryPrepare($('#summary-preparation'),workspace,selectedChapter,summaryCapabilities,{busy:setBusy,notice:notify,chapter:async id=>{selectedChapter=id;await renderMain();},prepared:async id=>{if(view!=='memory'||workspace?.document.project.id!==project)return;selectedTask=id;workspace=await api('/api/projects/'+encodeURIComponent(project));view='tasks';await renderMain();}});}
  if(view==='model-review'&&workspace){const project=workspace.document.project.id;bindModelReview($('#model-review-panel'),workspace,modelReviewDetail,async()=>{if(workspace?.document.project.id!==project||view!=='model-review')return;workspace=await api('/api/projects/'+encodeURIComponent(project));await renderMain();},async e=>{await openChapter(e.chapter_id);if(e.version_id&&$('#version-select')){contextView='history';renderContext();$('#version-select').value=e.version_id;layout.show('right');showVersion();}},async()=>{workspace=await api('/api/projects/'+encodeURIComponent(project));await navigate('knowledge');});}
  if(view==='knowledge'&&workspace){const project=workspace.document.project.id;bindKnowledge($('#knowledge-panel'),workspace,knowledgeData,async()=>{if(workspace?.document.project.id!==project||view!=='knowledge')return;workspace=await api(`/api/projects/${encodeURIComponent(project)}`);await renderMain();},async id=>{if(workspace?.document.project.id!==project||view!=='knowledge')return;selectedTask=id;workspace=await api(`/api/projects/${encodeURIComponent(project)}`);view='tasks';await renderMain();});}
}

async function reviewEntry() {
  const project=workspace.document.project.id,listing=await api(`/api/projects/${encodeURIComponent(project)}/reviews`);
  if(!listing.reports.some(r=>r.id===selectedReview))selectedReview=listing.reports.at(-1)?.id||'';
  reviewDetail=selectedReview?await api(`/api/projects/${encodeURIComponent(project)}/reviews/${selectedReview}`):null;
  return renderReviewPanel(workspace,listing,reviewDetail,selectedChapter);
}
async function modelReviewEntry(){
  const project=workspace.document.project.id,listing=await api('/api/projects/'+encodeURIComponent(project)+'/model-reviews');
  if(!listing.reports.some(r=>r.id===selectedModelReview))selectedModelReview=listing.reports.at(-1)?.id||'';
  modelReviewDetail=selectedModelReview?await api('/api/projects/'+encodeURIComponent(project)+'/model-reviews/'+selectedModelReview):null;
  return renderModelReview(modelReviewDetail);
}
async function comparisonEntry(){
  const project=workspace.document.project.id,base='/api/projects/'+encodeURIComponent(project),listing=await api(base+'/comparisons');
  if(selectedComparison==='new'||!listing.experiments.length){comparisonData={listing,create:true,caps:await api('/api/tasks/capabilities')};return renderComparisonCreate(workspace,comparisonData.caps);}
  if(!listing.experiments.some(e=>e.id===selectedComparison))selectedComparison=listing.experiments.at(-1).id;
  let blind=await api(base+'/comparisons/'+selectedComparison),setup=blind.ready?null:await api(base+'/comparisons/'+selectedComparison+'/setup');
  if(setup?.results_ready){blind=await api(base+'/comparisons/'+selectedComparison);setup=null;}
  const caps=await api('/api/tasks/capabilities'),extensions=await api(base+'/extensions');
  comparisonData={listing,blind,setup,caps,presets:extensions.presets};return renderComparison(listing,blind,setup,caps,extensions.presets);
}
async function workflowEntry(){
  const project=workspace.document.project.id,projectBase='/api/projects/'+encodeURIComponent(project),base=projectBase+'/workflows';
  workspace=await api(projectBase);
  const listing=await api(base);
  if(!listing.runs.some(r=>r.id===selectedWorkflow))selectedWorkflow=listing.runs.at(-1)?.id||'';
  const view=selectedWorkflow?await api(base+'/runs/'+selectedWorkflow):null,caps=await api('/api/tasks/capabilities');workflowData={listing,view,caps};return renderWorkflow(workspace,listing,view,caps);
}
function captureReviewDrafts() {
  for(const card of document.querySelectorAll('[data-review-rule]')){
    const index=Number(card.querySelector('[data-review-issue]').dataset.reviewIssue),issue=reviewDetail?.issues[index];
    if(issue)reviewInputDrafts.set(workspace.document.project.id+':'+issue.id,{reason:card.querySelector('[data-review-reason]').value,whitelist:card.querySelector('[data-review-whitelist]').checked});
  }
}
function hydrateReviewDrafts() {
  for(const card of document.querySelectorAll('[data-review-rule]')){
    const index=Number(card.querySelector('[data-review-issue]').dataset.reviewIssue),issue=reviewDetail?.issues[index],saved=issue&&reviewInputDrafts.get(workspace.document.project.id+':'+issue.id);
    if(saved){card.querySelector('[data-review-reason]').value=saved.reason;card.querySelector('[data-review-whitelist]').checked=saved.whitelist;}
  }
}
async function prepareAuditTask(form=null,recheck=false) {
  const project=workspace.document.project.id;
  let parameters,options;
  if(recheck&&reviewDetail){
    const old=reviewDetail.parameters;parameters={instruction:old.instruction,max_output_chars:old.max_output_chars,timeout_ms:old.timeout_ms,rules:old.rules,selected_chapter_ids:old.selected_chapter_ids,previous_report_id:reviewDetail.report.id};
    options={chapter_id:old.selected_chapter_ids[0],budget_chars:4000,include_current_plan:old.rules.check_timeline};
  } else {
    const values=formValues(form,{structured:true});
    if(!values.selected_chapter_ids.length){notify('请明确选择本书章节范围。',true);return;}
    const lines=value=>value.split(/\r?\n/).filter(t=>t.length>0);
    parameters={instruction:'作者明确所选范围的离线字面/结构规则审核',max_output_chars:10000,timeout_ms:10000,rules:{version:'offline-audit-1',forbidden_literals:lines(values.forbidden),required_literals:lines(values.required),normalization:values.normalization,near_threshold:Number(values.near_threshold),minimum_fragment_chars:12,check_timeline:values.check_timeline},selected_chapter_ids:values.selected_chapter_ids,previous_report_id:null};
    options={chapter_id:values.selected_chapter_ids[0],budget_chars:4000,include_current_plan:values.check_timeline,include_memories:values.include_memories,include_search_results:values.include_search_results,search_selections:values.include_search_results?searchSelections:[]};
  }
  setBusy(true);
  try {
    const context=await api(`/api/projects/${encodeURIComponent(project)}/context-preview`,{method:'POST',body:JSON.stringify(options)});
    const hash=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(context.context_text));
    const payload={request_id:crypto.randomUUID(),chapter_id:options.chapter_id,task_type:'audit_chapter',context_options:options,context_sha256:[...new Uint8Array(hash)].map(v=>v.toString(16).padStart(2,'0')).join(''),parameters,expected_revision:context.revision};
    const prepared=await api(`/api/projects/${encodeURIComponent(project)}/tasks/prepare`,{method:'POST',body:JSON.stringify(payload)});
    if(workspace?.document.project.id!==project)return;
    selectedTask=prepared.task.id;workspace=await api(`/api/projects/${encodeURIComponent(project)}`);view='tasks';await renderMain();
  }catch(error){if($('#audit-prepare-status'))$('#audit-prepare-status').textContent='准备失败：'+error.message;}
  finally{setBusy(false);}
}
async function reviewOperation(button) {
  if(!reviewDetail)return;
  captureReviewDrafts();const project=workspace.document.project.id,report=reviewDetail.report.id;
  const proposal=button.dataset.proposalDecision!==undefined,waiverId=button.dataset.revokeWaiver;
  let payload;
  if(proposal){
    const item=reviewDetail.proposals[Number(button.dataset.proposalIndex)],decision=button.dataset.proposalDecision;
    const key=item.id+':'+decision,identity=reviewIdentities.get(key)||crypto.randomUUID();reviewIdentities.set(key,identity);
    payload={decision_id:identity,proposal_id:item.id,decision,expected_revision:reviewDetail.revision,confirmed:true,preserve_conflicts:button.closest('[data-memory-proposal]').querySelector('[data-proposal-conflicts]').checked};
  } else {
    const issue=waiverId?reviewDetail.issues.find(i=>i.id===reviewDetail.waivers.find(w=>w.id===waiverId).issue_id):reviewDetail.issues[Number(button.dataset.reviewIssue)];
    const card=button.closest('[data-review-rule]'),kind=waiverId?'revoke_waiver':button.dataset.reviewAction;
    const reason=waiverId?'作者明确停用白名单':card.querySelector('[data-review-reason]').value,whitelist=waiverId?false:card.querySelector('[data-review-whitelist]').checked;
    const key=JSON.stringify([issue.id,kind,reason,whitelist,waiverId]),identity=reviewIdentities.get(key)||crypto.randomUUID();reviewIdentities.set(key,identity);
    payload={operation_id:identity,issue_id:issue.id,kind,reason,whitelist,expected_revision:reviewDetail.revision};if(waiverId)payload.waiver_id=waiverId;
  }
  setBusy(true);
  try {
    try{await api(`/api/projects/${encodeURIComponent(project)}/reviews/${report}/${proposal?'proposal':'issue'}`,{method:'POST',body:JSON.stringify(payload)});}
    catch(error){const known=await api(`/api/projects/${encodeURIComponent(project)}/reviews/${report}`);const completed=proposal?known.proposals.find(p=>p.id===payload.proposal_id)?.receipt?.id===payload.decision_id:known.actions.some(a=>a.id===payload.operation_id);if(!completed)throw error;}
    if(workspace?.document.project.id!==project)return;
    workspace=await api(`/api/projects/${encodeURIComponent(project)}`);await renderMain();
  }catch(error){if($('#review-operation-status'))$('#review-operation-status').textContent='处理未完成：'+error.message;}
  finally{setBusy(false);}
}
async function jumpReviewEvidence(value) {
  if(!reviewDetail||reviewDetail.report.project_id!==workspace?.document.project.id)return;
  const [index,side]=value.split(':').map(Number),evidence=reviewDetail.issues[index]?.finding.evidence[side];if(!evidence)return;
  await openChapter(evidence.chapter_id);
  if(evidence.source_kind==='chapter_outline'){writingPane='outline';await renderMain();}
  else if(evidence.version_id&&$('#version-select')){contextView='history';renderContext();$('#version-select').value=evidence.version_id;layout.show('right');showVersion();}
}

async function taskEntry() {
  const project=workspace.document.project.id;
  const [listing,capabilities]=await Promise.all([api(`/api/projects/${encodeURIComponent(project)}/tasks`),api('/api/tasks/capabilities')]);
  taskViewData=listing.tasks.find(v=>v.task.id===selectedTask)||listing.tasks.at(-1)||null;
  if(taskViewData)selectedTask=taskViewData.task.id;
  $('#model-status').textContent=capabilities.real_model_enabled?'模型任务允许 · 需单次确认':'真实模型关闭';
  if(taskViewData?.writing)return renderChapterWritingTask(workspace,listing,capabilities,taskViewData);
  if(taskViewData?.real_model_request)return renderModelTask(workspace,listing,capabilities,taskViewData);
  return renderTaskPanel(workspace,listing,capabilities,selectedTask);
}
function hydrateTaskPanel() {
  if(taskViewData?.writing){const project=workspace.document.project.id;bindChapterWritingTask($('#chapter-writing-task'),workspace,taskViewData,{busy:setBusy,notice:notify,editor:()=>navigate('writing'),hasBodyDraft:chapter=>Boolean(drafts.get(JSON.stringify([project,'writing',chapter,'body']))),refresh:async()=>{if(view!=='tasks'||workspace?.document.project.id!==project)return;workspace=await api('/api/projects/'+encodeURIComponent(project));await renderMain();},again:async task=>{chapterWritingMode=useChapterWritingInput(workspace,task);selectedChapter=task.chapter_id;await navigate('compose');}});}

  if(taskViewData?.candidates[0]&&$('#task-candidate-diff'))$('#task-candidate-diff').textContent=diffLines(taskViewData.task.frozen.target.text,taskViewData.candidates[0].output_text).map(r=>`${r.kind==='add'?'+ ':r.kind==='remove'?'- ':'  '}${r.text}`).join('\n');
  if(taskViewData?.display_status==='running') {
    const project=workspace.document.project.id,epoch=rendering;
    taskPollTimer=setTimeout(()=>refreshTaskPanel(project,epoch).catch(error=>{if(epoch===rendering&&$('#task-status'))$('#task-status').textContent='状态待核对：'+error.message;}),200);
  }
}
async function refreshTaskPanel(project=workspace?.document.project.id,epoch=rendering) {
  if(view!=='tasks'||epoch!==rendering||workspace?.document.project.id!==project)return;
  const html=await taskEntry();
  if(view!=='tasks'||epoch!==rendering||workspace?.document.project.id!==project)return;
  $('#content').innerHTML=html;hydrateTaskPanel();
}
async function prepareGenerationTask() {
  if(!taskPreview||taskPreview.project!==workspace?.document.project.id){notify('请先生成当前已保存上下文预览。',true);return;}
  const snapshot=taskPreview,project=snapshot.project;
  const parameters={instruction:$('#task-instruction').value,max_output_chars:10000,timeout_ms:3000};
  if(snapshot.payload&&JSON.stringify(snapshot.payload.parameters)!==JSON.stringify(parameters)){notify('原准备身份已绑定参数，请重新生成预览再准备新任务。',true);return;}
  if(!snapshot.payload){
    const hash=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(snapshot.report.context_text));
    snapshot.payload={request_id:crypto.randomUUID(),chapter_id:snapshot.report.chapter_id,task_type:'rewrite_chapter',context_options:structuredClone(snapshot.options),context_sha256:[...new Uint8Array(hash)].map(n=>n.toString(16).padStart(2,'0')).join(''),parameters,expected_revision:snapshot.report.revision};
  }
  setBusy(true);
  try {
    let prepared;
    try{prepared=await api(`/api/projects/${encodeURIComponent(project)}/tasks/prepare`,{method:'POST',body:JSON.stringify(snapshot.payload)});}
    catch(error){const listed=await api(`/api/projects/${encodeURIComponent(project)}/tasks`);const known=listed.tasks.find(v=>v.task.request_id===snapshot.payload.request_id);if(!known)throw error;prepared=known;}
    if(workspace?.document.project.id!==project)return;
    selectedTask=prepared.task.id;workspace=await api(`/api/projects/${encodeURIComponent(project)}`);view='tasks';await renderMain();
  }catch(error){if($('#task-prepare-result'))$('#task-prepare-result').textContent='准备失败：'+error.message;}
  finally{setBusy(false);}
}
async function taskAction(action) {
  const project=workspace.document.project.id,task=selectedTask;if(!task)return;
  setBusy(true);
  try {
    let body={};
    if(action==='execute'&&taskViewData?.real_model_request){if(!$('[name="confirm-model-send"]').checked)throw new Error('请先核对外发内容、令牌上限和未知费用风险，并勾选本次确认。');body={confirm_external:true,request_sha256:taskViewData.task.frozen.parameters.binding.request_sha256};}
    await api(`/api/projects/${encodeURIComponent(project)}/tasks/${encodeURIComponent(task)}/${action}`,{method:'POST',body:JSON.stringify(body)});
    if(workspace?.document.project.id!==project)return;
    workspace=await api(`/api/projects/${encodeURIComponent(project)}`);await renderMain();
  }catch(error){notify(error.message,true);}
  finally{setBusy(false);}
}
async function adoptGenerationCandidate() {
  const data=taskViewData,candidate=data?.candidates[0];if(!candidate)return;
  const project=workspace.document.project.id,task=data.task.id;
  const identity=adoptionIdentities.get(candidate.id)||crypto.randomUUID();adoptionIdentities.set(candidate.id,identity);
  const request={candidate_id:candidate.id,adoption_id:identity,expected_revision:data.revision,authorize_confirmed:$('#task-authorize-confirmed')?.checked===true};
  setBusy(true);
  try {
    let receipt;
    try{receipt=await api(`/api/projects/${encodeURIComponent(project)}/tasks/${encodeURIComponent(task)}/adopt`,{method:'POST',body:JSON.stringify(request)});}
    catch(error){try{receipt=await api(`/api/projects/${encodeURIComponent(project)}/adoptions/${identity}`);}catch{throw error;}}
    if(receipt.task_id!==task||receipt.candidate_id!==candidate.id)throw new Error('采纳收据与候选不一致');
    if(workspace?.document.project.id!==project)return;
    workspace=await api(`/api/projects/${encodeURIComponent(project)}`);await renderMain();
  }catch(error){if($('#task-adoption-result'))$('#task-adoption-result').textContent='采纳未完成：'+error.message;}
  finally{setBusy(false);}
}

async function showMemorySource() {
  const project=workspace.document.project.id,identifier=selectedMemory,epoch=rendering;
  try {
    const result=await api(`/api/projects/${encodeURIComponent(project)}/memories/${encodeURIComponent(identifier)}/source`);
    if(epoch!==rendering||project!==workspace?.document.project.id||identifier!==selectedMemory)return;
    $('#memory-source-result').textContent=`固定来源工作区 ${result.source.workspace_revision} · 实体版本 ${result.source.version_id||'无独立版本'}\n${JSON.stringify(result.value,null,2)}`;
  }catch(error){if(epoch===rendering&&$('#memory-source-result'))$('#memory-source-result').textContent=error.message;}
}

function readRollupForm() {
  const scope=$('#rollup-scope').value,volume=$('#rollup-volume').value;
  return {project:workspace.document.project.id,scope,scope_volume_number:scope==='volume'?(volume?Number(volume):null):null,through_chapter_id:$('#rollup-through').value};
}
async function changeMemoryRefresh(button){
  if(!workspace)return;
  const project=workspace.document.project.id;
  const request={action:button.id==='save-memory-refresh-policy'?'policy':'refresh',operation_id:crypto.randomUUID(),expected_revision:workspace.revision};
  if(request.action==='policy')request.auto_refresh=$('#memory-refresh-auto').checked;
  else{
    request.job_id=button.dataset.memoryRefresh;request.memory_texts={};
    for(const input of button.closest('[data-refresh-card]').querySelectorAll('[data-refresh-memory]')){
      if(input.value.trim())request.memory_texts[input.dataset.refreshMemory]=input.value;
    }
  }
  setBusy(true);
  try{
    const result=await api(`/api/projects/${encodeURIComponent(project)}/memory-refresh`,{method:'POST',body:JSON.stringify(request)});
    if(workspace?.document.project.id!==project)return;
    workspace=await api(`/api/projects/${encodeURIComponent(project)}`);await renderMain();
    if(result.status==='failed')notify(result.error,true);
  }catch(error){notify(error.message,true);}finally{setBusy(false);}
}
async function changeMemoryAutomation(button){
  if(!workspace)return;
  const project=workspace.document.project.id;
  const request={operation_id:crypto.randomUUID(),expected_revision:workspace.revision,action:button.id==='save-memory-policy'?'policy':button.dataset.memoryQueue};
  if(request.action==='policy')request.policy={track_updates:$('#memory-track-updates').checked,auto_select:$('#memory-auto-select').checked};
  else request.job_id=button.dataset.jobId;
  setBusy(true);
  try{await api(`/api/projects/${encodeURIComponent(project)}/memory-automation`,{method:'POST',body:JSON.stringify(request)});if(workspace?.document.project.id!==project)return;workspace=await api(`/api/projects/${encodeURIComponent(project)}`);await renderMain();}
  catch(error){notify(error.message,true);}finally{setBusy(false);}
}
async function previewMemoryRollup() {
  if(!workspace)return;
  const values=readRollupForm();
  if(values.scope==='volume'&&values.scope_volume_number===null){notify('请选择要汇总的分卷。',true);return;}
  setBusy(true);
  try {
    const preview=await api(`/api/projects/${encodeURIComponent(values.project)}/rollups/preview`,{method:'POST',body:JSON.stringify({scope:values.scope,scope_volume_number:values.scope_volume_number,through_chapter_id:values.through_chapter_id})});
    memoryRollupForm=values;memoryRollupPreview=preview;rollupOperationId=crypto.randomUUID();await renderMain();
  }catch(error){notify(error.message,true);}
  finally{setBusy(false);}
}
async function saveMemoryRollup() {
  const preview=memoryRollupPreview,form=memoryRollupForm;
  if(!workspace||!preview||!form)return;
  if(!preview.can_save){notify('存在未解决的记忆冲突，请先核对并修改或归档原记忆。',true);return;}
  if(!rollupOperationId)rollupOperationId=crypto.randomUUID();
  const project=workspace.document.project.id;let committed=false;
  setBusy(true);
  try {
    if(preview.existing)await api(`/api/projects/${encodeURIComponent(project)}/rollups/${encodeURIComponent(preview.existing.id)}/rebuild`,{method:'POST',body:JSON.stringify({operation_id:rollupOperationId,expected_revision:preview.revision,expected_rollup_revision:preview.existing.revision})});
    else await api(`/api/projects/${encodeURIComponent(project)}/rollups`,{method:'POST',body:JSON.stringify({operation_id:rollupOperationId,scope:form.scope,scope_volume_number:form.scope_volume_number,through_chapter_id:form.through_chapter_id,expected_revision:preview.revision})});
    committed=true;workspace=await api(`/api/projects/${encodeURIComponent(project)}`);
    memoryRollupPreview=null;rollupOperationId='';await renderMain();notify('记忆汇总已保存；原记忆与完整版本历史保留。');
  }catch(error){notify(committed?'汇总已保存，但页面刷新失败：'+error.message+'。请重新读取，不要重复生成。':error.message,true);}
  finally{setBusy(false);}
}
async function rebuildMemoryRollup(button) {
  if(!workspace||!window.confirm('按当前已确认且来源未变的记忆重建这份汇总？旧汇总版本会保留在历史中。'))return;
  const project=workspace.document.project.id,identifier=button.dataset.rollupRebuild,revision=Number(button.dataset.rollupRevision);let committed=false;
  setBusy(true);
  try {
    await api(`/api/projects/${encodeURIComponent(project)}/rollups/${encodeURIComponent(identifier)}/rebuild`,{method:'POST',body:JSON.stringify({operation_id:crypto.randomUUID(),expected_revision:workspace.revision,expected_rollup_revision:revision})});
    committed=true;workspace=await api(`/api/projects/${encodeURIComponent(project)}`);memoryRollupPreview=null;rollupOperationId='';await renderMain();notify('记忆汇总已显式重建，旧版本保留。');
  }catch(error){notify(committed?'汇总已重建，但页面刷新失败：'+error.message+'。请重新读取。':error.message,true);}
  finally{setBusy(false);}
}
function invalidateRetrieval() {
  retrievalRequest++;localSearchResult=null;searchSelections=[];
  if($('#local-search-results'))$('#local-search-results').replaceChildren();
  if($('#local-search-status'))$('#local-search-status').textContent='范围或检索词已变化，请重新检索。';
}
async function searchSaved(form) {
  invalidateRetrieval();const epoch=retrievalRequest,project=workspace.document.project.id;
  const values=formValues(form,{structured:true}),signature=JSON.stringify(values);
  const options={query:values.query,chapter_id:values.chapter_id,whole_book:values.whole_book,mode:values.mode||'literal',
    scopes:Object.keys(values).filter(k=>k.startsWith('scope_')&&values[k]).map(k=>k.slice(6)),skill_ids:values.skill_ids,material_ids:values.material_ids||[]};
  $('#local-search-status').textContent='正在检索已保存资料…';
  try {
    const result=await api(`/api/projects/${encodeURIComponent(project)}/search`,{method:'POST',body:JSON.stringify(options)});
    if(epoch!==retrievalRequest||!form.isConnected||project!==workspace?.document.project.id||signature!==JSON.stringify(formValues(form,{structured:true})))return;
    localSearchResult=result;
    $('#local-search-status').textContent=`${result.hits.length} 条命中 · 保存编号 ${result.revision}${result.limited?'（达到结果上限）':''}。${result.warnings.join(' ')}`;
    $('#local-search-results').innerHTML=result.hits.map((hit,index)=>`<article class="context-card"><p>${escapeHTML(hit.kind)} · ${hit.selection.scope==='global'?'全局资料':'本书'} · ${escapeHTML(hit.entity_id)} · 来源版本 ${escapeHTML(hit.selection.version_id||hit.selection.source_sha256)}${hit.kind==='memory'?` · ${hit.confirmed?'已确认':'未确认'} / ${hit.outdated?'已过期':'来源未变'} / ${hit.active?'启用':'归档'}`:''}${hit.kind==='material'?` · 资料《${escapeHTML(hit.material_title)}》第 ${hit.version_number} 版 · 字面位置 ${hit.start}–${hit.end} · 分块 ${hit.chunk_ordinal+1}（${hit.chunk_start}–${hit.chunk_end}）`:''}</p>${hit.explanation?`<p>字面融合得分 ${hit.score} · 词项覆盖 ${Math.round(hit.explanation.coverage*100)}% · 短语 ${hit.explanation.phrase?'是':'否'} · 命中词 ${escapeHTML(hit.explanation.matched_terms.join('、'))}</p><p>精确引文 [${hit.selection.excerpt.start},${hit.selection.excerpt.end}) · SHA256 ${escapeHTML(hit.selection.excerpt.sha256)}；选入的是此窗口，仍需版本与时效复核。</p>`:''}<pre class="context-text">${escapeHTML(hit.snippet)}</pre><button type="button" data-search-jump="${index}">跳到出处</button><label class="check-label"><input type="checkbox" data-search-pick="${index}">选入此来源</label></article>`).join('');
  }catch(error){if(epoch===retrievalRequest&&form.isConnected)$('#local-search-status').textContent='检索失败：'+error.message;}
}
async function jumpSearchSource(index) {
  const hit=localSearchResult?.hits[index];if(!hit||localSearchResult.project_id!==workspace?.document.project.id)return;
  const locator=hit.locator;
  const sourceProject=localSearchResult.project_id;
  if(locator.view==='writing') {
    await openChapter(locator.chapter_id);
    if(locator.pane){writingPane=locator.pane;await renderMain();}
    if(locator.version_id&&$('#version-select')?.querySelector(`option[value="${CSS.escape(locator.version_id)}"]`)){
      $('#version-select').value=locator.version_id;contextView='history';layout.show('right');showVersion();
    }
  } else {
    captureDraft();await flushDrafts();
    if(workspace?.document.project.id!==sourceProject)return;
    if(locator.character_id)selectedCharacter=locator.character_id;
    if(locator.memory_id)selectedMemory=locator.memory_id;
    if(locator.skill_id)selectedSkill=locator.skill_id;
    if(locator.material_id)selectedMaterial=locator.material_id;
    await navigate(locator.view);
    if(locator.view==='materials'&&locator.material_id&&locator.version_id&&workspace?.document.project.id===sourceProject&&view==='materials'&&selectedMaterial===locator.material_id){
      const target=$('#material-version-view');
      const version=await api(`/api/projects/${encodeURIComponent(sourceProject)}/materials/${encodeURIComponent(locator.material_id)}/versions/${encodeURIComponent(locator.version_id)}`);
      if(target?.isConnected&&workspace?.document.project.id===sourceProject&&view==='materials'&&selectedMaterial===locator.material_id){target.textContent=`来源第 ${version.version_number} 版 · ${version.id} · SHA256 ${version.text_sha256}\n引用区间 [${hit.start},${hit.end})（Unicode码点）\n\n${version.text}`;target.scrollIntoView({block:'nearest'});}
    }
    if(locator.file_path&&$('#skill-source-select')){$('#skill-source-select').value=locator.file_path;await showSkillSource();}
  }
}

function invalidatePreview() {
  previewRequest++;
  taskPreview=null;if($('#prepare-local-task'))$('#prepare-local-task').disabled=true;
  if($('#context-preview-report'))$('#context-preview-report').textContent='';
  if($('#context-preview-text'))$('#context-preview-text').textContent='';
  if($('#context-preview-sources'))$('#context-preview-sources').textContent='';
  if($('#context-preview-status'))$('#context-preview-status').textContent='范围已变化，请重新生成预览。';
}
async function previewSavedContext(form) {
  invalidatePreview();
  const epoch=previewRequest,project=workspace.document.project.id;
  const options=formValues(form,{structured:true});options.budget_chars=Number(options.budget_chars);
  const signature=JSON.stringify(formValues(form));
  $('#context-preview-status').textContent='正在读取已保存资料…';
  try {
    const result=await api(`/api/projects/${encodeURIComponent(project)}/context-preview`,{method:'POST',body:JSON.stringify(options)});
    if(epoch!==previewRequest||!form.isConnected||workspace?.document.project.id!==project||signature!==JSON.stringify(formValues(form)))return;
    $('#context-preview-text').textContent=result.context_text;
    $('#context-preview-report').textContent=JSON.stringify(result,null,2);
    taskPreview={project,report:structuredClone(result),options:structuredClone(options)};
    if($('#prepare-local-task'))$('#prepare-local-task').disabled=false;
    const labels={chapter_plan:'本章创作计划',book_outline:'全书大纲',worldbuilding:'世界观',writing_rules:'文风规则',character:'人物完整设定',chapter_body:'章节正文',memory:'手动记忆',search_result:'重新核对的检索资料'};
    const reasons={memory_current:'仅前章范围排除当前章记忆',memory_conflict:'记忆存在未解冲突',memory_hidden_chapter:'记忆所属或出处章节已归档/回收',memory_missing:'记忆来源已不存在',memory_covered_by_rollup:'记忆已由选入汇总覆盖',search_memory_covered_by_rollup:'检索记忆已由汇总覆盖',selected_rollup:'选入已保存且来源有效的汇总',rollup_current:'当前章汇总，前章范围排除',rollup_future:'汇总超出当前故事位置',rollup_other_book:'汇总不属于本书',rollup_hidden:'汇总章节已归档/回收',rollup_other_volume:'汇总不属于当前卷',rollup_future_source:'汇总含未来来源',rollup_hidden_source:'汇总含已归档/回收出处',rollup_conflict:'汇总来源存在未解冲突',rollup_stale:'汇总来源已变化，请显式重建',rollup_superseded:'同范围已有较新汇总',rollup_covered:'汇总来源均已覆盖',rollup_budget:'汇总整条来源超出剩余预算',rollup_empty:'汇总没有可选来源',future_chapter:'后续章，排除',current_body_not_selected:'当前章正文未选入',unlocated_not_authorized:'无故事位置，未授权选入',plan_not_authorized:'本章计划未选入',budget:'字符预算已满，排除',explicit_unlocated:'作者明确选入，可能含未来设定',saved_at_or_before_position:'按故事位置选入',selected:'作者选入',memory_not_selected:'记忆未选入',memory_future:'记忆适用位置在未来',memory_archived:'记忆已归档',memory_unconfirmed:'记忆未确认',memory_outdated:'记忆出处已过期',selected_memory:'已确认/来源未变且位置允许',stale_search:'检索来源或保存编号已变化',future_search:'检索来源在后续章节',selected_search:'明确选入且已重新校验',selected_material:'明确选入的本地资料且索引仍为当前版本',material_archived:'本地资料已归档',material_index_missing:'本地资料尚无索引',material_index_stale:'本地资料索引已过期'};
    $('#context-preview-sources').textContent=result.sources.map(s=>`${labels[s.kind]||s.kind}${s.chapter_number?' · 第'+s.chapter_number+'章':''} · ${s.entity_id}\n保存编号 ${s.revision} · 实体版本 ${s.version_id||'无独立版本，仅工作区编号'}\n${s.included?'选入':'排除'} ${s.included_chars}/${s.original_chars} 字符${s.truncated?'（已裁剪）':''} · ${reasons[s.reason]||s.reason}`).join('\n\n');
    $('#context-preview-status').textContent=`已保存编号 ${result.revision} · 第${result.chapter_number}章 · ${result.used_chars}/${result.budget_chars} 字符（不是token数）。${result.warnings.join(' ')}`;
  } catch(error) {if(epoch===previewRequest&&form.isConnected)$('#context-preview-status').textContent='预览失败：'+error.message;}
}

function openCreate(kind) {
  if (!mayLeave()) return;
  captureDraft();
  createKind = kind;
  $('#create-form').reset();
  $('#dialog-error').textContent = '';
  $('#dialog-title').textContent = kind === 'project' ? '创建小说' : kind === 'chapter' ? '新建章节' : '新建人物';
  $('#dialog-fields').innerHTML = kind === 'project'
    ? field('title', '小说名称', '', false, true, 'new') + field('author', '作者', '', false, false, 'new') + field('genre', '小说类型', '', false, false, 'new')
    : kind === 'chapter' ? field('title', '章节标题', '', false, true, 'new') : field('name', '人物姓名', '', false, true, 'new');
  $('#create-dialog').showModal();
}

async function navigate(id) {
  if (!mayLeave()) {if(busy)notify('正在读取或保存，请稍候再切换页面。');return;}
  resetAgentView();++rendering;
  captureDraft();await flushDrafts();
  view = id;
  $('#notification').hidden = true;
  setBusy(true);
  try { await renderMain(); layout.closeDrawer(false); if(id==='project') layout.show('left'); } catch (error) { notify(error.message, true); } finally { setBusy(false); if(!layout.isDrawer())focusDocument(); }
}

async function openChapter(id) {
  if (!mayLeave() || !workspace.document.chapters.some(chapter => chapter.id === id)) return;
  resetAgentView();++rendering;
  captureDraft();await flushDrafts(); selectedChapter = id; view = 'writing'; writingPane = 'body';
  await renderMain(); layout.closeDrawer(false); $('#edit-content')?.focus();
}
async function openDocument(doc) {
  if (!doc || !mayLeave()) return;
  resetAgentView();++rendering;
  captureDraft();await flushDrafts();
  if (doc.project && doc.project !== workspace?.document.project.id) { await openProject(doc.project, true); if (workspace?.document.project.id !== doc.project) return; }
  view = doc.view; selectedChapter = doc.chapter; selectedCharacter = doc.character; selectedMemory=doc.memory||selectedMemory;writingPane = doc.pane;
  setBusy(true);
  try { await renderMain(); } catch (error) { notify(error.message, true); } finally { setBusy(false); focusDocument(); }
}

function commandItems() {
  return [
    ...tabs.map(([id,name]) => ({ name, run: () => navigate(id), disabled: !workspace && !globalViews.includes(id) })),
    {name:'保存当前文档 · Ctrl+S',run:()=>$('#content form[data-action]')?.requestSubmit(),disabled:!$('#content form[data-action]')},
    {name:'切换专注模式',run:()=>layout.focus()}, {name:'切换导航面板',run:()=>layout.toggle('left')},
    {name:'切换上下文面板',run:()=>layout.toggle('right')}, {name:'切换明暗主题',run:()=>layout.theme()},
    {name:'打开智能创作控制台（离线入口）',run:()=>showBottom('console')},
    {name:'查找当前正文',run:()=>openFind(),disabled:!$('#edit-content')},
    {name:'模型与预设设置',run:()=>navigate('settings')}, {name:'打开工作流',run:()=>navigate('workflows'),disabled:!workspace}, {name:'持久创作对话',run:()=>navigate('chat'),disabled:!workspace},
  ];
}
function renderCommands() {
  const query = $('#command-search').value.trim().toLocaleLowerCase();
  $('#command-list').innerHTML = commandItems().map((item,index)=>({...item,index})).filter(item=>item.name.toLocaleLowerCase().includes(query)).map(item=>`<button data-command="${item.index}" type="button" ${item.disabled?'disabled':''}>${item.name}</button>`).join('') || '<p class="hint">没有匹配的命令。</p>';
}
function openCommands() { $('#command-search').value = ''; renderCommands(); $('#command-dialog').showModal(); $('#command-search').focus(); }
function openFind() { if (!$('#edit-content')) { notify('正文查找只用于当前正文编辑区。'); return; } $('#find-bar').hidden=false; $('#find-input').focus(); }
function findNext() {
  const editor=$('#edit-content'), query=$('#find-input').value;
  if (!editor || !query) { $('#find-result').textContent=''; return; }
  let position=editor.value.indexOf(query,editor.selectionEnd);
  if (position<0) position=editor.value.indexOf(query);
  const count=editor.value.split(query).length-1;
  $('#find-result').textContent=position<0?'未找到':`${count} 处`;
  if (position>=0) { editor.focus(); editor.setSelectionRange(position,position+query.length); const line=editor.value.slice(0,position).split('\n').length-1; editor.scrollTop=line*parseFloat(getComputedStyle(editor).lineHeight); updateWordCount(); }
}
function showBottom(pane) {
  layout.bottom(true);
  $('#activity-log').hidden=pane!=='activity'; $('#console-shell').hidden=pane!=='console';
  document.querySelectorAll('[data-bottom]').forEach(button=>button.classList.toggle('active',button.dataset.bottom===pane));
  updateWordCount();
}

document.addEventListener('click', async event => {
  const button = event.target.closest('button');
  if(button?.id==='cancel-backup-operation') {await cancelBackupOperation();return;}
  if(button?.id==='cancel-migration-operation') {await cancelMigrationOperation();return;}
  if (!button) return;
  if(localDisplayControl(button)){
    if(button.id==='toggle-modules')layout.modules();
    else if(button.id==='toggle-left')layout.toggle('left');
    else if(button.id==='toggle-right')layout.toggle('right');
    else if(button.id==='close-left')layout.close('left');
    else if(button.id==='close-right')layout.close('right');
    else if(button.id==='drawer-backdrop')layout.closeDrawer();
    else if(button.id==='focus-mode')layout.focus();
    else if(button.id==='toggle-theme')layout.theme();
    else if(button.id==='close-bottom')layout.bottom(false);
    else if(button.hasAttribute('data-bottom'))showBottom(button.dataset.bottom);
    else layout.bottom();
    return;
  }
  if(busy){if(settingsNavigation(button))notify('正在读取或保存，请稍候再打开设置；后台创作无需停止。');return;}
  try {
  if(button.id==='jump-body-protection')$('#author-scope')?.scrollIntoView({block:'center'});
  else if(button.id==='start-book-creation')await navigate('creation');
  else if(button.id==='desktop-enable-models'||button.id==='desktop-manual') {
    const enabled=button.id==='desktop-enable-models';
    const settingsInput=captureSettingsInput();
    if(!window.novelDesktop || (enabled&&!$('#desktop-model-consent')?.checked)) {notify(t('desktop.consentRequired'),true);return;}
    setBusy(true);
    try {
      await api('/api/desktop/mode',{method:'POST',body:JSON.stringify({mode:enabled?'models':'manual',confirmed:true})});
      sessionModels=enabled;
      $('#model-status').textContent=t(enabled?'desktop.statusModels':'desktop.statusManual');
      $('.sidebar-footer').textContent=t(enabled?'desktop.sidebarModels':'desktop.sidebarManual');
      $('.mode-status').textContent=t(enabled?'desktop.modeModels':'desktop.modeManual');
      $('#chat-model').textContent=t(enabled?'desktop.modelCenter':'desktop.modelDisabled');
      await renderMain();
      restoreSettingsInput(settingsInput);
    } finally {setBusy(false);}
  }
  else if(button.id==='start-draft'||button.id==='start-continuation'){chapterWritingMode=button.id==='start-draft'?'draft':'continue';await navigate('compose');}
  else if(button.id==='open-chapter-planning'){chapterPlanningMode='brainstorm';await navigate('planning');}
  else if(button.id==='open-scene-expansion'){const editor=$('#edit-content');if(editor&&editor.selectionEnd>editor.selectionStart){const text=editor.value;expansionRange=[Array.from(text.slice(0,editor.selectionStart)).length,Array.from(text.slice(0,editor.selectionEnd)).length];}else expansionRange=null;await navigate('expansion');}
  else if(button.id==='open-export'){if(!workspace){notify('请先打开小说。',true);return;}await navigate('migration');$('#migration-export')?.scrollIntoView({block:'start'});}
   else if(button.id==='open-import-export')await navigate('migration');
  else if(button.id==='move-chapter-up'||button.id==='move-chapter-down'){
    const direction=button.id==='move-chapter-up'?'up':'down';if(!window.confirm('确认将当前章节'+(direction==='up'?'上移':'下移')+'一位？正文、版本、细纲与IDEA不会改变。'))return;
    if(await perform('move_chapter',{chapter_id:selectedChapter,direction,confirmed:true}))await renderMain();
  }
  else if(button.id==='archive-chapter'){
    if(!window.confirm('确认归档当前章节？正文、版本、细纲、IDEA与任务历史都会保留，默认列表隐藏，可恢复。'))return;
    const next=(workspace.document.chapters.filter(c=>c.id!==selectedChapter&&!archivedChapterIds(workspace).has(c.id))[0]||{}).id||'';
    if(await perform('archive_chapter',{chapter_id:selectedChapter,confirmed:true})){selectedChapter=next;await renderMain();}
  }
  else if(button.dataset.restoreChapter){if(!window.confirm('确认恢复这个归档章节？'))return;if(await perform('unarchive_chapter',{chapter_id:button.dataset.restoreChapter,confirmed:true})){selectedChapter=button.dataset.restoreChapter;writingPane='body';await renderMain();}}
  else if(button.id==='open-workflows')await navigate('workflows');
  else if(button.id==='open-comparisons'){if(selectedComparison==='new')selectedComparison='';await navigate('comparisons');}
  else if(button.id==='open-extensions')await navigate('extensions');
  else if(button.id==='open-model-prepare')await navigate('model-prepare');
  else if(button.id==='execute-model-task')await taskAction('execute');
  else if(button.id==='open-model-report'){selectedModelReview=taskViewData?.model_reports[0]?.id||'';await navigate('model-review');}
  else if(button.id==='open-graph-proposals'){await navigate('knowledge');}
  else if(button.id==='open-knowledge')await navigate('knowledge');
  else if(button.id==='open-offline-review')await navigate('reviews');
  else if(button.id==='open-review-report'){selectedReview=taskViewData?.reports[0]?.id||'';await navigate('reviews');}
  else if(button.id==='refresh-review-state'){captureReviewDrafts();setBusy(true);try{workspace=await api(`/api/projects/${encodeURIComponent(workspace.document.project.id)}`);await renderMain();}finally{setBusy(false);}}
  else if(button.id==='reprepare-review')await prepareAuditTask(null,true);
  else if(button.dataset.reviewAction||button.dataset.proposalDecision||button.dataset.revokeWaiver)await reviewOperation(button);
  else if(button.dataset.reviewJump)await jumpReviewEvidence(button.dataset.reviewJump);
  else if(button.dataset.openReview){selectedReview=button.dataset.openReview;await navigate('reviews');}
  else if(button.id==='open-generation-tasks')await navigate('tasks');
  else if(button.id==='prepare-local-task')await prepareGenerationTask();
  else if(button.id==='execute-local-task')await taskAction('execute');
  else if(button.id==='cancel-generation-task')await taskAction('cancel');
  else if(button.id==='refresh-generation-task')await refreshTaskPanel();
  else if(button.id==='adopt-generation-candidate')await adoptGenerationCandidate();
  else if(button.id==='recover-generation-tasks') {
    setBusy(true);try{await api(`/api/projects/${encodeURIComponent(workspace.document.project.id)}/tasks/recover`,{method:'POST',body:'{}'});await renderMain();}catch(error){notify(error.message,true);}finally{setBusy(false);}
  }
  else if(button.id==='open-local-search')await navigate('retrieval');
  else if(button.id==='preview-memory-rollup')await previewMemoryRollup();
  else if(button.id==='save-memory-refresh-policy'||button.dataset.memoryRefresh)await changeMemoryRefresh(button);
  else if(button.id==='save-memory-policy'||button.dataset.memoryQueue)await changeMemoryAutomation(button);
  else if(button.dataset.memoryUpdateSummary){selectedChapter=button.dataset.memoryUpdateSummary;await renderMain();$('#summary-preparation')?.scrollIntoView({block:'start'});}
  else if(button.id==='save-memory-rollup')await saveMemoryRollup();
  else if(button.hasAttribute('data-rollup-rebuild'))await rebuildMemoryRollup(button);
  else if(button.hasAttribute('data-memory-jump')){selectedMemory=button.dataset.memoryJump;view='memory';await renderMain();}
  else if(button.id==='new-memory'){captureDraft();selectedMemory='new';await renderMain();}
  else if(button.id==='archive-memory'&&selectedMemory!=='new')await perform('archive_memory',{memory_id:selectedMemory});
  else if(button.id==='review-memory'&&selectedMemory!=='new'){
    if(dirty)notify('请先保存记忆修订，再显式复核来源。',true);
    else await perform('review_memory',{memory_id:selectedMemory,confirmed:$('#active-editor').elements.confirmed.checked});
  }
  else if(button.id==='show-memory-source')await showMemorySource();
  else if(button.id==='preview-search-selection'){
    if(!searchSelections.length)notify('请先明确选入检索来源。',true);
    else {selectedChapter=$('#local-search-form').elements.chapter_id.value;await navigate('preview');}
  }
  else if(button.hasAttribute('data-search-jump'))await jumpSearchSource(Number(button.dataset.searchJump));
  else if(button.hasAttribute('data-plan-add')||button.hasAttribute('data-plan-remove')) {changePlanning(button);captureDraft();}
  else if(button.id==='open-context-preview')await navigate('preview');
  else if (button.dataset.command) { const command=commandItems()[Number(button.dataset.command)]; $('#command-dialog').close(); if (!command.disabled) await command.run(); }
  else if (button.id==='open-commands') openCommands();
  else if (button.id==='close-commands') $('#command-dialog').close();
  else if (button.id==='toggle-left') layout.toggle('left');
  else if (button.id==='toggle-modules') layout.modules();
  else if (button.id==='chat-model') await navigate('settings');
  else if (button.id==='create-backup') await transferBackup();
  else if (button.id==='restore-backup') await transferBackup(true);
  else if (button.id==='check-backup-operation') await checkBackupOperation();
  else if (button.id==='import-projects') await transferMigration();
  else if (button.id==='copy-project') await transferMigration(true);
  else if (button.id==='preview-import-projects') await transferMigration(false,true);
  else if (button.id==='preview-copy-project') await transferMigration(true,true);
  else if (button.id==='check-migration-operation') await checkMigrationOperation();
  else if (button.dataset.testProvider) await configureProvider(button.closest('form[data-provider]'),true);
  else if (button.id==='switch-prompt-scope') { unboundPrompt=!unboundPrompt;renderPrompt();renderDocumentTabs();$('#chat-input').focus(); }
  else if (button.id==='clear-chat-prompt') {
    if(!window.confirm('确认清空这份未发送的需求？其它小说和未保存正文不会受影响。'))return;
    const project=promptProject();prompts.set(project,{...prompts.get(project),text:''});renderPrompt();renderDocumentTabs();$('#chat-input').focus();
  }
  else if (button.id==='add-chat-context') openChatContext();
  else if (button.id==='close-chat-context') $('#chat-context-dialog').close();
  else if (button.id==='clear-chat-context') { const project=workspace.document.project.id;prompts.set(project,{...prompts.get(project),chapter:'',character:'',world:false,revision:null});$('#chat-context-dialog').close();updatePromptSummary();$('#chat-input').focus(); }
  else if (button.id==='open-history-panel') { selectedChapter=$('#history-chapter').value; await navigate('writing');contextView='history';renderContext();layout.show('right'); }
  else if (button.id==='toggle-right') layout.toggle('right');
  else if (button.id==='close-left') layout.close('left');
  else if (button.id==='close-right') layout.close('right');
  else if (button.id==='drawer-backdrop') layout.closeDrawer();
  else if (button.id==='focus-mode') layout.focus();
  else if (button.id==='toggle-theme') layout.theme();
  else if (button.id==='toggle-bottom'||button.id==='quick-activity') layout.bottom();
  else if (button.id==='close-bottom') layout.bottom(false);
  else if (button.dataset.bottom) showBottom(button.dataset.bottom);
  else if (button.id==='open-find') openFind();
  else if (button.id==='find-next') findNext();
  else if (button.id==='close-find') { $('#find-bar').hidden=true; $('#edit-content')?.focus(); }
  else if (button.dataset.context) { contextView=button.dataset.context; renderContext(); }
  else if (button.dataset.chapter) await openChapter(button.dataset.chapter);
  else if (button.dataset.editCharacter) { captureDraft(); selectedCharacter=button.dataset.editCharacter; await navigate('characters'); }
  else if (button.dataset.openTab) await openDocument(documents.find(doc=>doc.key===button.dataset.openTab));
  else if (button.dataset.closeTab) {
    const key=button.dataset.closeTab, index=documents.findIndex(doc=>doc.key===key);
    const siblings=moduleDocuments(), scopedIndex=siblings.findIndex(doc=>doc.key===key);
    if (drafts.get(key) && !window.confirm('关闭此标签会放弃这份未保存草稿。是否继续？其它标签草稿保留。')) return;
    drafts.remove(key);clearDiskDraft(workspace?.document.project.id,key); documents.splice(index,1);
    if (key===activeKey) { dirty=false; activeKey=''; baseline=readForm(); const remaining=siblings.filter(doc=>doc.key!==key); if (remaining.length) await openDocument(remaining[Math.min(scopedIndex,remaining.length-1)]); else await navigate('chat'); }
    else renderDocumentTabs();
  }
  else if (button.id==='rebase-draft') {
    if (!window.confirm('已对照最新已保存内容，确认保留当前草稿并以最新保存编号提交？保存会追加版本。')) return;
    drafts.rebase(activeKey,workspace.revision);scheduleDraftPersist(activeKey); await renderMain();
  } else if (button.id==='discard-draft') {
    if (!window.confirm('确认放弃本标签草稿，改用已保存内容？')) return;
    drafts.remove(activeKey);clearDiskDraft(workspace.document.project.id,activeKey); await renderMain();
  }
  else if (button.dataset.project) { await openProject(button.dataset.project); layout.closeDrawer(false); }
  else if (button.dataset.view) await navigate(button.dataset.view);
  else if (button.dataset.create) openCreate(button.dataset.create);
  else if (button.dataset.pane) {
    if (!mayLeave()) return;
    captureDraft();await flushDrafts();
    writingPane = button.dataset.pane;
    await renderMain();
    focusDocument();
  } else if (button.dataset.skill) {
    selectedSkill = button.dataset.skill;
    setBusy(true);
    try { await renderMain(); } catch (error) { notify(error.message, true); } finally { setBusy(false); }
  } else if (button.id === 'new-project') openCreate('project');
  else if (button.id === 'close-dialog') $('#create-dialog').close();
  else if (button.id === 'reload-project' && workspace) await openProject(workspace.document.project.id, true);
  else if (button.id === 'restore-version') {
    if (!mayLeave()) return;
    const chapter = workspace.document.chapters.find(item => item.id === selectedChapter);
    const bodyKey=JSON.stringify([workspace.document.project.id,'writing',selectedChapter,'body']);
    const question = (chapter.status === 'confirmed' ? '这是已确认的正式章节，恢复需要明确授权。' : '') + (drafts.get(bodyKey) ? '当前正文有未保存草稿，成功恢复后会放弃这份草稿。' : '') + '是否恢复所选版本为新草稿？原有已保存历史与章节顺序均保留。';
    if (!window.confirm(question)) return;
    await perform('restore_chapter', { chapter_id: selectedChapter, version_id: $('#version-select').value, authorize_confirmed: chapter.status === 'confirmed' });
  } else if (button.id === 'import-skill') {
    const chosen = Array.from($('#skill-file').files.length ? $('#skill-file').files : $('#skill-folder').files);
    if (!chosen.length) { notify('请先选择 SKILL.md 或技能文件夹。', true); return; }
    const markdown = chosen.filter(file => file.name.toLowerCase().endsWith('.md'));
    if (markdown.length > 100 || markdown.reduce((sum, file) => sum + file.size, 0) > 2 * 1024 * 1024) { notify('Markdown 资料超过 100 个文件或 2 MiB 限制，请缩减后重试。', true); return; }
    setBusy(true);
    try {
      const decoder = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true });
      const files = await Promise.all(markdown.map(async file => ({ path: file.webkitRelativePath || file.name, content: decoder.decode(await file.arrayBuffer()) })));
      const imported = await api('/api/skills/import', { method: 'POST', body: JSON.stringify({ files }) });
      selectedSkill = imported.id;
      await renderMain();
      notify(`技能资料“${imported.name}”已保存到本地。${chosen.length > markdown.length ? '非 Markdown 文件已跳过。' : ''}`);
    } catch (error) { notify(error.message, true); } finally { setBusy(false); }
  }
  } catch(error) { notify(error.message,true); }
});

$('#create-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy) return;
  const values = Object.fromEntries(new FormData(event.currentTarget));
  if (createKind !== 'project') {
    if (await perform(createKind === 'chapter' ? 'add_chapter' : 'add_character', values)) $('#create-dialog').close();
    else $('#dialog-error').textContent = $('#notification').textContent;
    return;
  }
  setBusy(true);
  let committed = false;
  try {
    workspace = await api('/api/projects', { method: 'POST', body: JSON.stringify(values) });
    unboundPrompt=false;
    committed = true;
    selectedChapter = '';
    selectedCharacter = '';
    dirty = false;
    view = 'project';
    sessionStorage.setItem('novel-project', workspace.document.project.id);
    $('#create-dialog').close();
    layout.closeDrawer(false);
    await renderMain();
    await refreshProjects();
    notify('小说已创建并保存到本地。');
  } catch (error) {
    if (committed) notify(`小说已创建并保存，但页面刷新失败：${error.message}。请重新读取，不要重复创建。`, true);
    else $('#dialog-error').textContent = error.message;
  } finally { setBusy(false); }
});

$('#content').addEventListener('submit', async event => {
  event.preventDefault();
  if(event.target.id==='context-preview-form') {await previewSavedContext(event.target);return;}
  if(event.target.id==='local-search-form'){await searchSaved(event.target);return;}
  if(event.target.id==='audit-prepare-form'){await prepareAuditTask(event.target);return;}
  if(event.target.dataset.customProvider){
    if(busy)return;const settingsInput=captureSettingsInput(event.target),saving=saveCustomProvider(event.target);setBusy(true);
    try{await saving;await renderMain();restoreSettingsInput(settingsInput);notify(t('provider.saved'));}
    catch(error){event.target.querySelector('.provider-result').textContent=error.message;}finally{setBusy(false);}return;
  }
  if(event.target.dataset.provider) { await configureProvider(event.target);return; }
  if (busy || !event.target.dataset.action) return;
  const values = formValues(event.target,{structured:true});
  if (event.target.elements.authorize_confirmed) values.authorize_confirmed = event.target.elements.authorize_confirmed.checked;
  await perform(event.target.dataset.action, values);
});

$('#content').addEventListener('input', event => {
  if(event.target.hasAttribute('data-review-reason'))captureReviewDrafts();
  if(event.target.closest('#context-preview-form'))invalidatePreview();
  if(event.target.closest('#local-search-form'))invalidateRetrieval();
  if (event.target.closest('form[data-action]') && !event.target.hasAttribute('data-passive')) {
    captureDraft();
    if(event.target.id==='edit-content'&&!diffScheduled) { diffScheduled=true;requestAnimationFrame(()=>{diffScheduled=false;showVersion();}); }
  }
});

$('#content').addEventListener('change', async event => {
  if (event.target.id === 'canon-maintenance-toggle') { await configureCanonToggle(event.target); return; }
  if(event.target.closest('#context-preview-form'))invalidatePreview();
  if(event.target.closest('#local-search-form'))invalidateRetrieval();
  if (busy) return;
  const select = event.target;
  if(select.id==='workflow-run-select'){selectedWorkflow=select.value;await renderMain();return;}
  if(select.id==='comparison-select'){selectedComparison=select.value;await renderMain();return;}
  if(select.hasAttribute('data-review-whitelist'))captureReviewDrafts();
  else if(select.id==='review-report-select'){captureReviewDrafts();selectedReview=select.value;setBusy(true);try{await renderMain();}finally{setBusy(false);}}
  else if(select.hasAttribute('data-search-pick')) {
    searchSelections=[...$('#local-search-results').querySelectorAll('[data-search-pick]:checked')].map(el=>localSearchResult.hits[Number(el.dataset.searchPick)].selection);
  }
  else if(select.id==='task-select'){selectedTask=select.value;await refreshTaskPanel();}
  else if(select.id==='memory-select'){
    captureDraft();selectedMemory=select.value;setBusy(true);
    try{await renderMain();}finally{setBusy(false);}
  }
  else if (select.id === 'version-select') showVersion();
  else if (select.id === 'skill-source-select') {
    setBusy(true);
    try { await showSkillSource(); } catch (error) { notify(error.message, true); } finally { setBusy(false); }
  } else if (select.id === 'skill-file') $('#skill-folder').value = '';
  else if (select.id === 'skill-folder') $('#skill-file').value = '';
  else if (['chapter-select', 'character-select'].includes(select.id)) {
    if (!mayLeave()) { select.value = select.id === 'chapter-select' ? selectedChapter : selectedCharacter; return; }
    captureDraft();await flushDrafts();
    if (select.id === 'chapter-select') selectedChapter = select.value;
    else selectedCharacter = select.value;
    await renderMain();
  } else if (select.closest('form[data-action]') && !select.hasAttribute('data-passive')) captureDraft();
});

$('#context-content').addEventListener('change', event=> { if(event.target.id==='version-select') showVersion(); });
document.addEventListener('novel-layout-change',()=>{revealActive('#document-tabs','.active',true);revealActive('#chapter-tree','.active');});
$('#chapter-filter').addEventListener('input',renderChapterTree);
$('#command-search').addEventListener('input',renderCommands);
$('#command-search').addEventListener('keydown',event=>{if(composing||event.isComposing||event.keyCode===229)return;if(event.key==='ArrowDown'){event.preventDefault();$('#command-list button:not(:disabled)')?.focus();}else if(event.key==='Enter'){event.preventDefault();$('#command-list button:not(:disabled)')?.click();}});
$('#find-input').addEventListener('keydown',event=>{if(composing||event.isComposing||event.keyCode===229)return;if(event.key==='Enter'){event.preventDefault();findNext();}});
document.addEventListener('compositionstart',()=>{composing=true;});
document.addEventListener('compositionend',()=>{composing=false;captureDraft();});
document.addEventListener('selectionchange',updateWordCount);
document.addEventListener('keydown',event=>{
  if ((event.ctrlKey||event.metaKey) && event.key.toLowerCase()==='s') {
    event.preventDefault(); if(composing||event.isComposing||event.keyCode===229||busy||document.querySelector('dialog[open]')) return;
    $('#content form[data-action]')?.requestSubmit();
  } else if ((event.ctrlKey||event.metaKey) && event.key.toLowerCase()==='k') {
    event.preventDefault(); if(!busy&&!composing&&!event.isComposing&&event.keyCode!==229&&!document.querySelector('dialog[open]')) openCommands();
  } else if (event.key==='Escape' && !composing&&!event.isComposing&&event.keyCode!==229&&!$('#find-bar').hidden) { $('#find-bar').hidden=true; $('#edit-content')?.focus(); }
});

$('#export-project').addEventListener('click', event => {
  if (busy || (dirty && !window.confirm('导出文件只包含已经保存的内容，不含当前未保存修改。是否继续导出？'))) event.preventDefault();
});

document.querySelector('.brand').addEventListener('click', event => {
  event.preventDefault(); if(mayLeave()) navigate('chat');
});

$('#chat-input').addEventListener('input',()=>{
  const project=promptProject();
  prompts.set(project,{...prompts.get(project),text:$('#chat-input').value});updatePromptSummary();renderDocumentTabs();
});
function standaloneLocalPath(text){
 if(!text||/[\r\n]/.test(text))return null;
 let value=text.trim();
 if((value.startsWith('"')&&value.endsWith('"'))||(value.startsWith("'")&&value.endsWith("'")))value=value.slice(1,-1);
 return /^(?:[A-Za-z]:[\\/]|\/)/.test(value)?value:null;
}
let agentSubmitting=false;
// The composer input is persistent; bind once here, never during rendering.
$('#chat-input').onkeydown=event=>{
  if(event.key!=='Enter'||composing||event.isComposing||event.keyCode===229)return;
  if(event.ctrlKey||event.altKey||event.metaKey||event.shiftKey)return;
  event.preventDefault();
  if(event.repeat||busy||agentSubmitting||attachmentsUploading(workspace?.document.project.id)||$('#chat-send').disabled)return;
  $('#chat-composer').requestSubmit();
};
$('#project-list').addEventListener('click',async event=>{
 const button=event.target.closest('[data-chat-book]');if(!button)return;
 event.preventDefault();event.stopPropagation();if(busy)return;
 try{
  const project=button.dataset.chatBook,restore=button.dataset.restore==='true';
  const current=await api('/api/projects/'+encodeURIComponent(project));
  if(!restore&&!window.confirm('将《'+current.document.project.title+'》移入回收站？原文和历史可以恢复。'))return;
  setBusy(true);await changeEntity(project,current.revision,'book',project,restore);
  if(workspace?.document.project.id===project)workspace=await api('/api/projects/'+encodeURIComponent(project));
  await refreshProjects();renderChrome();await renderMain();notify(restore?'书籍已恢复。':'书籍已移入回收站。');
 }catch(error){notify(error.message,true);}finally{setBusy(false);}
});
$('#chat-composer').addEventListener('submit',async event=>{
  event.preventDefault();
  const text=$('#chat-input').value.trim();
  const attachmentProject=workspace?.document.project.id;
  if(busy||agentSubmitting||attachmentsUploading(attachmentProject))return;
  if(!text&&!hasPendingAttachments(attachmentProject))return;
  const project=promptProject(),submitEpoch=rendering,submitView=view;
  const current=()=>rendering===submitEpoch&&view===submitView&&workspace?.document.project.id===attachmentProject;
  agentSubmitting=true;$('#chat-send').disabled=true;
  try{
    const path=standaloneLocalPath(text);
    if(path){await importLocalPath(path,attachmentProject);if(!current())return;}
    const job=await sendAgentMessage(path?'':text,attachmentProject,workspace?.revision);
    if(!current())return;
    $('#chat-input').value='';
    prompts.set(project,{...prompts.get(project),text:''});
    const moved=job.project_id!==(attachmentProject||'');
    const fresh=attachmentProject?await api('/api/projects/'+encodeURIComponent(attachmentProject)):null;
    if(!current())return;
    const listing=await api('/api/projects');
    if(!current())return;
    if(fresh)workspace=fresh;
    projects=listing;
    unboundPrompt=false;await renderMain();
    notify(moved?'需求已保存；任务已转入新建小说，请通过当前小说选择器选择查看。':'需求已保存，正在处理。');
  }catch(error){if(current()){notify(error.message+'；请保留输入，若请求已发出可重新读取查看进度。',true);syncAgentControls();}}
  finally{agentSubmitting=false;}
});
$('#chat-context-form').addEventListener('submit',event=>{
  event.preventDefault();if(!workspace||busy)return;
  const form=event.currentTarget,project=workspace.document.project.id;
  const chapter=form.elements.chapter.value,character=form.elements.character.value;
  if(chapter&&!workspace.document.chapters.some(item=>item.id===chapter)||character&&!workspace.document.characters.some(item=>item.id===character))return;
  prompts.set(project,{...prompts.get(project),chapter,character,world:form.elements.world.checked,revision:workspace.revision});
  $('#chat-context-dialog').close();updatePromptSummary();$('#chat-input').focus();
});

window.addEventListener('beforeunload', event => {
  if (annotationsDirty() || drafts.size || prompts.hasText || dirty || busy || bookCreationDirty || bookAiDirty || styleDirty || publicSearchDirty || styleTrialDirty || chapterWritingDirty || chapterPlanningDirty || sceneExpansionDirty) { event.preventDefault(); event.returnValue = ''; }
});
window.addEventListener('novel-creation-dirty',event=>{bookCreationDirty=event.detail===true;});
window.addEventListener('novel-book-ai-dirty',event=>{bookAiDirty=event.detail===true;});
window.addEventListener('novel-style-dirty',event=>{styleDirty=event.detail===true;});
window.addEventListener('novel-public-search-dirty',event=>{publicSearchDirty=event.detail===true;});
window.addEventListener('novel-style-trial-dirty',event=>{styleTrialDirty=event.detail===true;});

window.novelDesktop?.onBackendEnded(()=>notify(t('desktop.backendStopped'),true));

function settingsControlKey(element){
 const form=element.closest('form');
 const formKey=form?.id||form?.dataset.action||form?.dataset.provider||form?.dataset.customProvider||form?.dataset.kForm||'';
 if(form&&element.name){const peers=[...form.elements].filter(v=>v.name===element.name);return formKey+'/'+element.name+'/'+peers.indexOf(element)+'/'+element.tagName;}
 if(element.id&&!/^(k-control|model-field|cmp-field|wf-field)-/.test(element.id))return 'id:'+element.id;
 const peers=form?[...form.elements].filter(v=>v.name===element.name):[];
 return formKey+'/'+element.name+'/'+peers.indexOf(element)+'/'+element.tagName;
}
function captureSettingsInput(skipForm=null){
 const controls=new Map();
 for(const element of document.querySelectorAll('input,textarea,select')){
  if(skipForm&&element.closest('form')===skipForm)continue;
  controls.set(settingsControlKey(element),{value:element.value,checked:element.checked,selected:element.multiple?[...element.selectedOptions].map(v=>v.value):null,files:element.type==='file'?[...element.files]:null,start:element.selectionStart,end:element.selectionEnd,direction:element.selectionDirection,top:element.scrollTop,left:element.scrollLeft,focused:element===document.activeElement});
 }
 return {controls,details:[...$('#content').querySelectorAll('details')].map(v=>v.open),top:$('#content').scrollTop,left:$('#content').scrollLeft};
}
function restoreSettingsInput(saved){
 for(const element of document.querySelectorAll('input,textarea,select')){
  const value=saved.controls.get(settingsControlKey(element));if(!value)continue;
  if(value.files){if(value.files.length){const transfer=new DataTransfer();for(const file of value.files)transfer.items.add(file);element.files=transfer.files;}}
  else if(value.selected){for(const option of element.options)option.selected=value.selected.includes(option.value);}
  else element.value=value.value;
  if(typeof value.checked==='boolean')element.checked=value.checked;
  if(typeof value.start==='number')element.setSelectionRange(value.start,value.end,value.direction||'none');
  if(value.focused)element.focus({preventScroll:true});element.scrollTop=value.top;element.scrollLeft=value.left;
 }
 [...$('#content').querySelectorAll('details')].forEach((value,index)=>{if(index<saved.details.length)value.open=saved.details[index];});
 $('#content').scrollTop=saved.top;$('#content').scrollLeft=saved.left;
}
(async () => {
  setBusy(true);
  try {
    document.documentElement.lang='zh-CN';
    setToken((await api('/api/session')).token);
    sessionModels=!(await api('/api/settings/chat')).offline;
    if(location.hash==='#settings') view='settings';
    await refreshProjects();
    const savedId = sessionStorage.getItem('novel-project');
    if (projects.some(item => item.id === savedId)) workspace = await api(`/api/projects/${savedId}`);
    else if (projects.length) workspace = await api(`/api/projects/${projects[0].id}`);
    if(workspace)await loadDiskDrafts(workspace.document.project.id);
    await renderMain();
  } catch (error) { notify(error.message, true); } finally { setBusy(false); }
})();

window.addEventListener('pagehide',()=>{
  captureDraft();void flushDrafts(true);
  if(activeBackupOperation)api('/api/backups/operations/'+activeBackupOperation+'/cancel',{method:'POST',body:'{}',keepalive:true}).catch(()=>{});
});
window.addEventListener('blur',()=>{captureDraft();void flushDrafts();});
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden'){captureDraft();void flushDrafts(true);}});

window.addEventListener('novel-chapter-writing-dirty',event=>{chapterWritingDirty=event.detail===true;});
window.addEventListener('novel-chapter-planning-dirty',event=>{chapterPlanningDirty=event.detail===true;});
window.addEventListener('novel-scene-expansion-dirty',event=>{sceneExpansionDirty=event.detail===true;});
