import { api } from './api.js';

const STATUS={current:'索引已更新',stale:'索引过期（需显式重建）',missing:'尚无索引'};
const esc=value=>String(value).replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const tagsText=tags=>tags.join('、');

function card(value,selected){
  return `<article class="context-card" data-material-card data-material-tags="${esc(JSON.stringify(value.tags))}">
    <div class="panel-heading"><div><h3>${esc(value.title)}</h3><p class="hint">${esc(value.format.toUpperCase())} · ${value.version_count} 版 · ${value.char_count} 字符 · ${esc(tagsText(value.tags)||'无标签')}</p></div><button type="button" data-material-open="${esc(value.id)}">${selected?'正在查看':'查看/编辑'}</button></div>
    <p><span class="badge">${value.archived?'已归档':'启用中'}</span> <span class="badge ${value.index_status}">${esc(STATUS[value.index_status]||value.index_status)}</span>${value.chunk_count?` · ${value.chunk_count} 个字面分块`:''}</p>
  </article>`;
}

export function renderMaterials(workspace,listing,detail,currentVersion){
  const active=listing.materials.filter(value=>!value.archived);
  const rows=listing.materials.map(value=>card(value,value.id===detail?.material.id)).join('');
  const tags=listing.tags.map(tag=>`<option value="${esc(tag)}">${esc(tag)}</option>`).join('');
  let detailHTML='<p class="hint">选择一份资料查看版本、归档与重建索引；资料原文不会自动进入模型上下文。</p>';
  if(detail){
    const material=detail.material;
    const versions=detail.versions.map(version=>`<li><button type="button" data-material-version="${esc(version.id)}" data-material-id="${esc(material.id)}">第 ${version.version_number} 版</button> · ${version.char_count} 字符 · ${esc(version.created_at)} · ${esc(version.note||'无版本说明')}</li>`).join('');
    detailHTML=`<section class="panel" id="material-detail" data-material-id="${esc(material.id)}">
      <div class="panel-heading"><div><h2>${esc(material.title)}</h2><p class="hint">当前第 ${material.current_version_number} 版 · ${material.char_count} 字符 · ${esc(STATUS[material.index_status]||material.index_status)}。旧版本只读保留。</p></div><span class="badge ${material.index_status}">${esc(STATUS[material.index_status]||material.index_status)}</span></div>
      ${material.archived?'<p class="hint">资料已归档：不能更新或重建索引，历史仍可读取。</p>':''}
      <form id="material-update-form" data-material-id="${esc(material.id)}">
        <div class="field-grid">
          <div class="field"><label for="material-update-title">标题</label><input id="material-update-title" name="title" value="${esc(material.title)}" maxlength="200" required></div>
          <div class="field"><label for="material-update-format">格式</label><select id="material-update-format" name="format"><option value="txt" ${material.format==='txt'?'selected':''}>TXT</option><option value="md" ${material.format==='md'?'selected':''}>Markdown</option></select></div>
          <div class="field"><label for="material-update-tags">标签（逗号分隔，最多20个）</label><input id="material-update-tags" name="tags" value="${esc(tagsText(material.tags))}"></div>
        </div>
        <div class="field"><label for="material-update-note">版本说明</label><input id="material-update-note" name="note" maxlength="1000"></div>
        <div class="field"><label for="material-update-text">当前正文（保存会新增版本，不覆盖旧版本）</label><textarea id="material-update-text" name="text" class="tall" required>${esc(currentVersion?.text||'')}</textarea></div>
        <button type="submit" class="primary" ${material.archived?'disabled':''}>保存为新版本</button>
        <button type="button" data-material-archive="${esc(material.id)}" ${material.archived?'hidden':''}>归档</button>
        <button type="button" data-material-restore="${esc(material.id)}" ${material.archived?'':'hidden'}>恢复</button>
        <button type="button" data-material-rebuild="${esc(material.id)}" ${material.archived?'disabled':''}>显式增量更新本资料索引</button>
      </form>
      <button type="button" id="material-index-cancel" hidden>取消索引更新</button><p id="material-index-status" role="status">索引任务只在本进程运行，重开不会自动续跑；相同窗口复用ID与哈希，位移窗口重新计算。</p>
      <button type="button" id="material-suggest-tags" ${material.archived?'disabled':''}>查看可追溯标签建议</button><pre id="material-tag-suggestions" class="context-text"></pre><p class="hint">建议来自原文标题和重复词项；请自行填写标签并保存新版本，不会自动采纳。</p>
      <h3>版本历史（只读）</h3><ol>${versions}</ol><pre id="material-version-view" class="context-text">选择旧版本查看原文；当前版本内容已在上方编辑框。</pre>
    </section>`;
  }
  return `<section class="panel" id="materials-root">
    <div class="panel-heading"><div><h2>本地资料</h2><p class="hint">只支持 UTF-8 TXT/Markdown。更新追加版本；索引是固定 ${800} 字符窗口（重叠 ${120} 字符）的字面定位，不是语义检索或向量索引。资料不会自动进入模型上下文。</p></div><button type="button" data-material-rebuild-all ${active.length?'':'disabled'}>显式重建全部启用资料索引</button></div>
    <form id="material-create-form">
      <div class="field-grid">
        <div class="field"><label for="material-title">标题</label><input id="material-title" name="title" maxlength="200" required></div>
        <div class="field"><label for="material-format">格式</label><select id="material-format" name="format"><option value="txt">TXT</option><option value="md">Markdown</option></select></div>
        <div class="field"><label for="material-tags">标签（逗号分隔）</label><input id="material-tags" name="tags"></div>
      </div>
      <div class="field"><label for="material-note">来源/版本说明</label><input id="material-note" name="note" maxlength="1000"></div>
      <div class="field"><label for="material-text">粘贴 UTF-8 文本</label><textarea id="material-text" name="text" class="tall" placeholder="与文件二选一"></textarea></div>
      <div class="field"><label for="material-file">或上传 UTF-8 TXT/Markdown（最大 8 MiB）</label><input id="material-file" name="file" type="file" accept=".txt,.md,text/plain,text/markdown"></div>
      <button type="submit" class="primary">创建资料</button>
    </form>
    <h3>资料列表（${listing.materials.length}）</h3>
    <div class="field"><label for="material-tag-filter">按标签筛选</label><select id="material-tag-filter"><option value="">全部标签</option>${tags}</select></div>
    <div id="material-list">${rows||'<p class="hint">尚无本地资料。创建后需显式重建索引才能用于检索。</p>'}</div>
    ${detailHTML}
  </section>`;
}

function parseTags(value){
  return [...new Set(String(value||'').split(/[,，]/).map(tag=>tag.trim()).filter(Boolean))];
}

function readBase64(file){
  return new Promise((resolve,reject)=>{
    const reader=new FileReader();
    reader.onerror=()=>reject(new Error('文件读取失败'));
    reader.onload=()=>{const value=String(reader.result||'');resolve(value.slice(value.indexOf(',')+1));};
    reader.readAsDataURL(file);
  });
}

export function bindMaterials(root,workspace,listing,options){
  if(!root)return;
  const base=`/api/projects/${encodeURIComponent(workspace.document.project.id)}/materials`;
  const run=async task=>{
    if(options.busy)options.busy(true);
    try{await task();}
    catch(error){options.notice?.(error.message,true);}
    finally{if(options.busy)options.busy(false);}
  };
  root.querySelector('#material-create-form')?.addEventListener('submit',event=>{
    event.preventDefault();
    const form=event.currentTarget;
    run(async()=>{
      const file=form.elements.file.files[0];
      const text=form.elements.text.value;
      if(file&&text.trim())throw new Error('粘贴文本与文件只能选择一种');
      if(file&&file.size>8*1024*1024)throw new Error('文件超过 8 MiB 限制');
      if(!file&&!text.trim())throw new Error('请粘贴文本或选择文件');
      const payload={operation_id:crypto.randomUUID(),expected_revision:workspace.revision,
        title:form.elements.title.value.trim(),format:form.elements.format.value,
        tags:parseTags(form.elements.tags.value),note:form.elements.note.value};
      if(file)payload.data_base64=await readBase64(file);else payload.text=text;
      const result=await api(base,{method:'POST',body:JSON.stringify(payload)});
      options.notice?.('资料已创建；索引尚未生成，请显式重建后再检索。');
      await options.refresh?.(result.material.id);
    });
  });
  root.querySelectorAll('[data-material-open]').forEach(button=>button.addEventListener('click',async()=>{
    await options.select?.(button.dataset.materialOpen);
  }));
  root.querySelector('#material-tag-filter')?.addEventListener('change',event=>{
    const tag=event.currentTarget.value;
    root.querySelectorAll('[data-material-card]').forEach(card=>{
      card.hidden=Boolean(tag)&&!JSON.parse(card.dataset.materialTags||'[]').includes(tag);
    });
  });
  const detail=root.querySelector('#material-detail');
  if(!detail)return;
  const materialId=detail.dataset.materialId;
  let materialEdited=false;
  detail.querySelector('#material-update-form')?.addEventListener('input',()=>{materialEdited=true;});
  detail.querySelector('#material-update-form')?.addEventListener('submit',event=>{
    event.preventDefault();
    const form=event.currentTarget;
    run(async()=>{
      const payload={operation_id:crypto.randomUUID(),expected_revision:workspace.revision,
        title:form.elements.title.value.trim(),format:form.elements.format.value,
        tags:parseTags(form.elements.tags.value),note:form.elements.note.value,text:form.elements.text.value};
      await api(`${base}/${encodeURIComponent(materialId)}/update`,{method:'POST',body:JSON.stringify(payload)});
      options.notice?.('已保存为新版本；索引已过期，请显式重建后再检索。');
      await options.refresh?.(materialId);
    });
  });
  detail.querySelector('[data-material-archive]')?.addEventListener('click',event=>{
    if(!window.confirm('归档这份资料？归档后不能更新或重建索引，历史仍保留。'))return;
    run(async()=>{
      await api(`${base}/${encodeURIComponent(materialId)}/archive`,{method:'POST',body:JSON.stringify({operation_id:crypto.randomUUID(),expected_revision:workspace.revision})});
      options.notice?.('资料已归档；历史与版本未删除。');
      await options.refresh?.(materialId);
    });
  });
  detail.querySelector('[data-material-restore]')?.addEventListener('click',event=>run(async()=>{
    await api(`${base}/${encodeURIComponent(materialId)}/restore`,{method:'POST',body:JSON.stringify({operation_id:crypto.randomUUID(),expected_revision:workspace.revision})});
    options.notice?.('资料已恢复；索引需按需显式重建。');
    await options.refresh?.(materialId);
  }));
  let indexJob=null;
  const indexStatus=detail.querySelector('#material-index-status'),cancelButton=detail.querySelector('#material-index-cancel');
  cancelButton?.addEventListener('click',async()=>{
    if(!indexJob)return;
    try{await api(`${base}/index-jobs/${encodeURIComponent(indexJob.id)}/cancel`,{method:'POST',body:'{}'});indexStatus.textContent='已请求取消；正在核对事务是否已提交。';}
    catch(error){options.notice?.(error.message,true);}
  });
  detail.querySelector('[data-material-rebuild]')?.addEventListener('click',async event=>{
    if(indexJob)return;
    const button=event.currentTarget;button.disabled=true;
    try{
      indexJob=await api(`${base}/${encodeURIComponent(materialId)}/index-jobs`,{method:'POST',body:JSON.stringify({operation_id:crypto.randomUUID(),expected_revision:workspace.revision})});
      cancelButton.hidden=false;indexStatus.textContent='正在增量更新；可取消，取消成功时事务回滚。';
      while(root.isConnected&&['running','cancelling'].includes(indexJob.status)){
        await new Promise(resolve=>setTimeout(resolve,150));
        indexJob=await api(`${base}/index-jobs/${encodeURIComponent(indexJob.id)}`);
      }
      if(!root.isConnected)return;
      if(indexJob.status==='succeeded'){
        const stats=indexJob.result.index_update;
        options.notice?.(stats?`索引已更新：复用 ${stats.reused_chunks} 窗口，重算 ${stats.rebuilt_chunks} 窗口。`:'此操作已完成，未重复更新。');
        if(materialEdited)indexStatus.textContent='索引已完成；保留了尚未保存的表单输入。请保留输入并重新核对保存编号后再保存。';
        else await options.refresh?.(materialId);
      }else indexStatus.textContent=indexJob.status==='cancelled'?'已取消，索引与历史未变。':`索引未完成：${indexJob.error||indexJob.status}`;
    }catch(error){options.notice?.(error.message,true);}
    finally{indexJob=null;cancelButton.hidden=true;button.disabled=false;}
  });
  detail.querySelector('#material-suggest-tags')?.addEventListener('click',()=>run(async()=>{
    const result=await api(`${base}/${encodeURIComponent(materialId)}/suggest-tags`,{method:'POST',body:'{}'});
    detail.querySelector('#material-tag-suggestions').textContent=result.suggestions.length?result.suggestions.map(v=>`${v.tag} · ${v.method} · 版本 ${v.version_id} · [${v.start},${v.end}) · ${v.sha256}\n${v.evidence}`).join('\n\n'):'当前样本没有可追溯标签建议。';
  }));
  root.querySelector('[data-material-rebuild-all]')?.addEventListener('click',event=>run(async()=>{
    const result=await api(`${base}/rebuild-all`,{method:'POST',body:JSON.stringify({operation_id:crypto.randomUUID(),expected_revision:workspace.revision})});
    options.notice?.(`已重建 ${result.rebuilt_material_ids.length} 份启用资料；归档资料已跳过。`);
    await options.refresh?.(materialId);
  }));
  detail.querySelectorAll('[data-material-version]').forEach(button=>button.addEventListener('click',()=>run(async()=>{
    const view=await api(`${base}/${encodeURIComponent(button.dataset.materialId)}/versions/${encodeURIComponent(button.dataset.materialVersion)}`);
    detail.querySelector('#material-version-view').textContent=`第 ${view.version_number} 版 · ${view.created_at} · ${view.text_sha256}\n${view.note?view.note+'\n':''}\n${view.text}`;
  })));
}
