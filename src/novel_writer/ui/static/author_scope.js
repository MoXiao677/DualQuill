import {api} from './api.js';
import {escapeHTML as esc} from './views.js';

const stateName={active:'创作中',archived:'已归档',deleted:'回收站'};
export function scopeState(workspace){
  let state=workspace.document.project.status==='archived'?'archived':'active';
  for(const event of workspace.author_scope_events||[])if(event.kind==='lifecycle')state=event.data.after;
  return state;
}
export function rangeLocks(workspace){
  const result=new Map();
  for(const event of workspace.author_scope_events||[]){
    if(event.kind==='lock'||event.kind==='rebase')result.set(event.data.lock_id,event.data);
    else if(event.kind==='unlock')result.delete(event.data.lock_id);
  }
  return [...result.values()];
}
export function codepointRange(text,start,end){
  const split=offset=>offset>0&&offset<text.length&&/[\uD800-\uDBFF]/.test(text[offset-1])&&/[\uDC00-\uDFFF]/.test(text[offset]);
  if(!Number.isInteger(start)||!Number.isInteger(end)||start<0||start>=end||end>text.length||split(start)||split(end))throw Error('请选择完整 Unicode 字符，不能截断表情字符。');
  return [Array.from(text.slice(0,start)).length,Array.from(text.slice(0,end)).length];
}
export async function bodyDigest(text){return [...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text)))].map(v=>v.toString(16).padStart(2,'0')).join('');}

export function renderAuthorScope(workspace,chapterId=null){
  const state=scopeState(workspace),locks=rangeLocks(workspace),chapter=workspace.document.chapters.find(v=>v.id===chapterId);
  const actions=state==='active'?[['archive','归档整书'],['trash','整书移入回收站']]:state==='archived'?[['restore','恢复整书'],['trash','整书移入回收站']]:[['restore','恢复整书']];
  return `<section id="author-scope" class="panel"><div class="panel-heading"><h2>${chapter?'正文选区保护':'整书管理'}</h2><span>${stateName[state]}</span></div>${state!=='active'?'<p class="hint">本书只读。恢复整书后才可继续编辑或执行模型任务。</p>':''}
    ${chapter?`<p>保护已保存的正文选区；范围按 Unicode 字符计数，结束位置不包含在范围内。手工保存、历史恢复和 AI 采纳均受保护。</p><button type="button" id="lock-body-selection" ${state!=='active'?'disabled':''}>锁定正文选区</button><div id="body-lock-list">${locks.filter(v=>v.chapter_id===chapter.id).map(lock=>`<article class="review-card"><p>范围 [${lock.start}, ${lock.end}) · 绑定版本 ${esc(lock.version_id)}</p><pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(Array.from(chapter.content).slice(lock.start,lock.end).join(''))}</pre><button type="button" data-unlock-range="${esc(lock.lock_id)}" ${state!=='active'?'disabled':''}>明确解锁此选区</button></article>`).join('')||'<p>本章尚无正文选区锁。</p>'}</div>`:`<p>归档和回收均保留整书正文、版本、稳定编号及范围锁；没有物理删除。</p>${actions.map(([action,label])=>`<button type="button" data-project-scope-preview="${action}">${label}</button>`).join('')}`}
    <div id="author-scope-preview" aria-live="polite"></div><p id="author-scope-result" role="status"></p></section>`;
}

export function bindAuthorScope(root,workspace,chapterId,{notice,refresh,busy}){
  if(!root)return;
  const project=workspace.document.project.id,base='/api/projects/'+encodeURIComponent(project),state=scopeState(workspace);
  const output=root.querySelector('#author-scope-result');
  if(state!=='active'){
    const editor=document.querySelector('#edit-content');if(editor)editor.readOnly=true;
    const hint=document.querySelector('.editor-grid > .hint');if(hint)hint.textContent='本书只读；恢复整书后才可继续编辑及模型任务。';
    for(const button of document.querySelectorAll('#content form[data-action] button[type="submit"]'))button.disabled=true;
  }
  const act=async(action,fields,revision=workspace.revision)=>{
    busy(true);
    try{await api(base+'/actions',{method:'POST',body:JSON.stringify({action,fields:{operation_id:crypto.randomUUID(),confirmed:true,...fields},expected_revision:revision})});await refresh();}
    finally{busy(false);}
  };
  root.addEventListener('click',async event=>{
    const button=event.target.closest('button');if(!button||button.disabled)return;
    try{
      if(button.dataset.projectScopePreview){
        const action=button.dataset.projectScopePreview,preview=await api(base+'/author-scope/preview/'+action);
        const target=root.querySelector('#author-scope-preview');
        target.innerHTML=`<div class="review-card"><p>将${esc(button.textContent)}《${esc(preview.title)}》：${preview.chapters} 章、${preview.body_characters} 字符、${preview.entity_versions} 个实体版本、${preview.active_range_locks} 个范围锁。保存编号 ${preview.expected_revision}。</p><p>${esc(preview.effects)}</p><label>输入完整书名确认 <input id="project-scope-confirm-title" autocomplete="off"></label><label class="check-label"><input id="project-scope-confirmed" type="checkbox">我已核对影响并明确确认本次操作</label><button type="button" id="commit-project-scope">确认执行</button><button type="button" id="cancel-project-scope">取消</button></div>`;
        target.querySelector('#commit-project-scope').onclick=async()=>{
          try{
            if(!target.querySelector('#project-scope-confirmed').checked||target.querySelector('#project-scope-confirm-title').value!==preview.title)throw Error('请勾选确认并输入完整书名。');
            await act(action+'_project',{confirm_title:preview.title},preview.expected_revision);
          }catch(error){output.textContent=error.message;notice(error.message,true);}
        };
        target.querySelector('#cancel-project-scope').onclick=()=>target.replaceChildren();
      }else if(button.id==='lock-body-selection'||button.dataset.unlockRange){
        const chapter=workspace.document.chapters.find(v=>v.id===chapterId),editor=document.querySelector('#edit-content');
        if(!chapter||!editor||editor.value!==chapter.content)throw Error('请先保存当前正文，再操作选区锁；当前输入已保留。');
        if(button.id==='lock-body-selection'){
          const [start,end]=codepointRange(editor.value,editor.selectionStart,editor.selectionEnd),selected=Array.from(chapter.content).slice(start,end).join('');
          if(!window.confirm(`确认持久锁定正文范围 [${start}, ${end})？\n${selected.slice(0,160)}\n范围绑定当前已保存版本；每次解锁都需重新确认。`))return;
          await act('lock_body_range',{chapter_id:chapter.id,version_id:chapter.current_version_id,body_sha256:await bodyDigest(chapter.content),start,end,text_sha256:await bodyDigest(selected)});
        }else{
          const lock=rangeLocks(workspace).find(v=>v.lock_id===button.dataset.unlockRange);
          if(!lock||!window.confirm(`确认仅解锁范围 [${lock.start}, ${lock.end})？这不会授权模型调用或解锁其他范围。`))return;
          await act('unlock_body_range',{lock_id:lock.lock_id,version_id:lock.version_id});
        }
      }
    }catch(error){output.textContent=error.message;notice(error.message,true);}
  });
}
