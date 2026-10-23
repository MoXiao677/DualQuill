import {api} from './api.js';
import {escapeHTML as esc, archivedChapterIds} from './views.js';

export function trashedChapterIds(workspace) {
  const latest=new Map();
  for(const event of workspace.chapter_trash_events||[])latest.set(event.chapter_id,event.kind);
  return new Set([...latest].filter(([,kind])=>kind==='trash').map(([id])=>id));
}
export function renderChapterManagement(workspace,chapterId) {
  const hidden=archivedChapterIds(workspace),trash=trashedChapterIds(workspace);
  const volumes=workspace.document.book_outline?.volumes||[];
  const active=workspace.document.chapters.some(c=>c.id===chapterId&&!hidden.has(c.id));
  return `<section id="chapter-management" class="panel"><h3>分卷移动与回收站</h3><p class="hint">可将左侧章节拖到目标卷，或用下拉框和键盘选择位置后移动。操作保留正文与全部历史。</p>${active?`<label for="move-volume">目标卷</label><select id="move-volume">${volumes.map(v=>`<option value="${v.number}">${esc(v.title)}</option>`).join('')}</select><label for="move-position">卷内位置（从 1 开始；留空放卷末）</label><input id="move-position" type="number" min="1" step="1"><button type="button" id="move-volume-confirm" ${volumes.length?'':'disabled'}>移动本章</button><button type="button" id="trash-preview">删除影响预览</button>`:''}<div id="volume-drop-targets">${volumes.map(v=>`<div tabindex="0" data-drop-volume="${v.number}" class="context-card">拖入卷：${esc(v.title)}</div>`).join('')}</div><div id="trash-preview-result"></div><details id="chapter-trash"><summary>回收站（${trash.size}）</summary><p>不物理清理正文或历史，恢复到回收前的卷和位置。旧引用保留并显示受阻。</p>${workspace.document.chapters.filter(c=>trash.has(c.id)).map(c=>`<p>${esc(c.title)} <button type="button" data-restore-trash="${c.id}">恢复原卷与顺序</button></p>`).join('')}</details><p id="chapter-management-status" role="status"></p></section>`;
}
export function bindChapterManagement(workspace,chapterId,hooks) {
  const root=document.querySelector('#chapter-management');if(!root)return;
  const base='/api/projects/'+encodeURIComponent(workspace.document.project.id);
  let preview=null;
  const run=async(action,fields,revision=workspace.revision)=>{
    hooks.busy(true);
    try{await api(base+'/actions',{method:'POST',body:JSON.stringify({action,fields,expected_revision:revision})});await hooks.refresh();}
    catch(error){hooks.notice(error.message,true);const status=document.querySelector('#chapter-management-status');if(status)status.textContent=error.message;}
    finally{hooks.busy(false);}
  };
  const move=async(id,number,index)=>{
    const volume=workspace.document.book_outline?.volumes.find(v=>v.number===number);if(!volume)return;
    const remaining=volume.chapter_ids.filter(v=>v!==id);
    await run('move_chapter_to_volume',{chapter_id:id,target_volume_number:number,target_index:index??remaining.length,confirmed:true});
  };
  root.querySelector('#move-volume-confirm')?.addEventListener('click',()=>{
    const raw=root.querySelector('#move-position').value;
    return move(chapterId,Number(root.querySelector('#move-volume').value),raw===''?null:Number(raw)-1);
  });
  for(const button of document.querySelectorAll('#chapter-tree [data-chapter]')){
    button.draggable=true;
    button.ondragstart=event=>event.dataTransfer.setData('application/x-novel-chapter',JSON.stringify({project_id:workspace.document.project.id,chapter_id:button.dataset.chapter}));
  }
  for(const target of root.querySelectorAll('[data-drop-volume]')){
    target.ondragover=event=>event.preventDefault();
    target.ondrop=async event=>{
      event.preventDefault();
      try{const item=JSON.parse(event.dataTransfer.getData('application/x-novel-chapter'));if(item.project_id!==workspace.document.project.id)throw Error('禁止跨书拖拽章节');if(!workspace.document.chapters.some(c=>c.id===item.chapter_id&&!archivedChapterIds(workspace).has(c.id)))throw Error('章节不存在或已隐藏');await move(item.chapter_id,Number(target.dataset.dropVolume),null);}
      catch(error){hooks.notice(error.message,true);}
    };
  }
  root.querySelector('#trash-preview')?.addEventListener('click',async()=>{
    try{
      preview=await api(base+'/chapters/'+encodeURIComponent(chapterId)+'/trash-preview');
      root.querySelector('#trash-preview-result').innerHTML=`<h4>删除「${esc(preview.title)}」的影响</h4><p>${preview.reference_count} 处引用。正文、版本、细纲、IDEA、记忆、任务及旧引用全部保留。</p><pre>${esc(JSON.stringify(preview.references,null,2))}</pre><label for="trash-title">请输入精确章节标题</label><input id="trash-title" autocomplete="off"><label><input id="trash-ack" type="checkbox">已知悉引用影响，旧引用会受阻且不会自动改写</label><button id="trash-confirm" type="button" ${preview.can_trash?'':'disabled'}>确认移入回收站</button>`;
      root.querySelector('#trash-confirm').onclick=()=>run('trash_chapter',{chapter_id:chapterId,operation_id:crypto.randomUUID(),confirm_title:root.querySelector('#trash-title').value,acknowledge_references:root.querySelector('#trash-ack').checked,confirmed:true},preview.revision);
    }catch(error){hooks.notice(error.message,true);}
  });
  for(const button of root.querySelectorAll('[data-restore-trash]'))button.onclick=()=>run('restore_trashed_chapter',{chapter_id:button.dataset.restoreTrash,operation_id:crypto.randomUUID(),confirmed:true});
}
