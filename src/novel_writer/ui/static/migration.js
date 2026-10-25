import {api,downloadFile} from './api.js';
import {escapeHTML as h,archivedChapterIds} from './views.js';
const state={base64:'',filename:'',encoding:'auto',preview:null};
export function renderMigration(workspace){
 const chapters=[...workspace.document.chapters].filter(c=>!archivedChapterIds(workspace).has(c.id)).sort((a,b)=>a.number-b.number);const volumes=workspace.document.book_outline?.volumes||[];
 return '<div id="migration-root"><section id="migration-panel" class="panel"><h2>TXT / Markdown 导入</h2><p>先识别第X章/第X节/Chapter N/一二级 Markdown 标题，生成可编辑映射预览；首章标题前的原文默认作为独立前言条目保留（含空格和换行）；确认后追加为新章节并新建分卷，不覆盖已有章。自动检测严格按 UTF-8/BOM 优先，失败后严格 GB18030，均失败则拒绝；可手工覆盖后重新预览。</p>'+
  '<div class="field"><label for="migration-file">选择 .txt 或 .md 文件（最多 5 MiB / 500 条，前言计入）</label><input id="migration-file" type="file" accept=".txt,.md,text/plain,text/markdown"></div>'+
  '<div class="field"><label for="migration-encoding">编码</label><select id="migration-encoding"><option value="auto">自动：UTF-8/BOM 优先，失败后严格 GB18030</option><option value="utf-8">UTF-8</option><option value="utf-8-sig">UTF-8 BOM</option><option value="gb18030">GB18030（手动覆盖）</option></select></div>'+
  '<button id="migration-preview" type="button">识别并预览分章（不写入）</button><p id="migration-status" role="status"></p><div id="migration-preview-result"></div></section>'+
  '<section id="migration-export" class="panel"><h2>导出已保存内容</h2><p>只导出数据库已保存正文，未保存的窗口草稿和本地恢复草稿不会包含。编码 UTF-8。</p>'+
   '<div class="field-grid"><div class="field"><label for="export-scope">范围</label><select id="export-scope"><option value="book">整本</option><option value="volume">分卷</option><option value="chapter">单章</option></select></div><div class="field"><label for="export-format">格式</label><select id="export-format"><option value="txt">TXT</option><option value="md">Markdown</option></select></div></div>'+
   '<div class="field" id="export-volume-field"><label for="export-volume">分卷</label><select id="export-volume" '+(volumes.length?'':'disabled')+'>'+volumes.map(v=>'<option value="'+v.number+'">'+h(v.title)+'</option>').join('')+'</select></div>'+
   '<div class="field" id="export-chapter-field"><label for="export-chapter">章节</label><select id="export-chapter" '+(chapters.length?'':'disabled')+'>'+chapters.map(c=>'<option value="'+h(c.id)+'">第'+c.number+'章 · '+h(c.title)+'</option>').join('')+'</select></div>'+
  '<button id="export-download" type="button" '+(chapters.length?'':'disabled')+'>下载导出文件</button><p id="export-status" role="status"></p></section></div>';
}
async function fileBase64(file){
 if(!file)throw Error('请选择文件');if(file.size>5*1024*1024)throw Error('文件超过 5 MiB 上限');
 const data=await file.arrayBuffer();let binary='';const bytes=new Uint8Array(data);for(let i=0;i<bytes.length;i+=0x8000)binary+=String.fromCharCode(...bytes.subarray(i,i+0x8000));
 return btoa(binary);
}
export function bindMigration(root,workspace,hooks){
 if(!root||root.dataset.bound)return;root.dataset.bound='true';const base='/api/projects/'+encodeURIComponent(workspace.document.project.id);let busy=false;
  const scope=root.querySelector('#export-scope');const updateExportFields=()=>{const value=scope.value;root.querySelector('#export-volume-field').hidden=value!=='volume';root.querySelector('#export-chapter-field').hidden=value!=='chapter';};scope.addEventListener('change',updateExportFields);updateExportFields();
  const run=async fn=>{if(busy)return;busy=true;hooks.busy(true);try{await fn();}catch(error){hooks.notice(error.message,true);}finally{busy=false;hooks.busy(false);}};
 root.addEventListener('click',event=>{const button=event.target.closest('button');if(!button)return;
  if(button.id==='migration-preview'){void run(async()=>{
   const file=root.querySelector('#migration-file').files[0];state.base64=await fileBase64(file);state.filename=file.name;state.encoding=root.querySelector('#migration-encoding').value;
   const preview=await api(base+'/import/preview',{method:'POST',body:JSON.stringify({filename:state.filename,content_base64:state.base64,encoding:state.encoding})});state.preview=preview;
   root.querySelector('#migration-status').textContent='识别到 '+preview.items.length+' 章 · 实际编码 '+preview.encoding+' · 标题前原文 '+preview.preamble_chars+' 字符，已作为前言保留 · 可编辑标题后确认';
   root.querySelector('#migration-preview-result').innerHTML='<h3>分章映射预览</h3>'+preview.items.map((v,i)=>'<div class="import-row" data-import-row="'+i+'"><div class="field"><label for="import-title-'+i+'">章节标题</label><input id="import-title-'+i+'" data-import-title value="'+h(v.title)+'"></div><p class="hint">起点 '+v.start+' · 正文起点 '+v.content_start+' · 终点 '+v.end+' · '+v.chars+' 字符</p><pre>'+h(v.preview)+'</pre></div>').join('')+
    '<label class="check-label"><input id="import-confirm" type="checkbox">我已核对预览；确认追加为新章节，不覆盖已有章节</label><button id="import-commit" type="button" disabled>确认导入</button>';
   root.querySelector('#import-confirm').addEventListener('change',e=>{root.querySelector('#import-commit').disabled=!e.target.checked;});
  });}
  else if(button.id==='import-commit'){void run(async()=>{
   const items=state.preview.items.map((v,i)=>({index:v.index,title:root.querySelector('#import-title-'+i).value,start:v.start,content_start:v.content_start,end:v.end,chars:v.chars}));
   await api(base+'/import/commit',{method:'POST',body:JSON.stringify({expected_revision:hooks.revision(),filename:state.filename,content_base64:state.base64,encoding:state.encoding,items,preview_sha256:state.preview.preview_sha256,confirmed:true})});
   await hooks.refresh();const status=document.querySelector('#migration-status');if(status)status.textContent='导入完成，已追加新章节与分卷。';hooks.notice('导入完成，已追加新章节与分卷。');
  });}
  else if(button.id==='export-download'){void run(async()=>{
   if(!window.confirm('导出只含数据库已保存内容；未保存草稿不会包含。继续？'))return;
   const scope=root.querySelector('#export-scope').value,format=root.querySelector('#export-format').value;let path=base+'/export/'+scope+'/'+format;if(scope==='volume')path+='/'+root.querySelector('#export-volume').value;if(scope==='chapter')path+='/'+encodeURIComponent(root.querySelector('#export-chapter').value);
   const response=await fetch(path);if(!response.ok)throw Error('导出失败，请保留当前内容后重试。');const saved=await downloadFile(path,'novel.'+format);root.querySelector('#export-status').textContent=saved?'已请求下载（桌面保存完成；仅已保存内容）。':'已取消保存。';
  });}
 });
}
