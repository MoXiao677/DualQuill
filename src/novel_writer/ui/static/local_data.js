import {api} from './api.js';

export function renderLocalData(){
  return `<section class="panel" id="local-data-safety"><h3>本地诊断与恢复草稿</h3>
    <p>诊断只含存储大小、草稿有效/损坏数量和运行模式，不包含正文、书名、路径、任务原文或凭据。点击后才读取本机状态。</p>
    <p class="hint">本地恢复草稿独立于正式正文和版本历史，未加密，不进入完整备份。清理只允许预览中逐项选中的损坏草稿；有效草稿、未知文件和全部正式历史保留。</p>
    <button type="button" id="local-data-preview">预览脱敏诊断与可清理范围</button>
    <button type="button" id="local-data-retry">重试恢复草稿读写</button>
    <p id="local-data-result" role="status">尚未读取诊断，也未执行清理。</p>
    <div id="local-data-candidates"></div>
    <button type="button" id="local-data-cleanup" disabled>确认清理选中损坏草稿</button>
    <div class="field"><label for="local-data-report">可复制的脱敏诊断 JSON（预览后生成）</label>
    <textarea id="local-data-report" rows="12" readonly data-passive aria-label="脱敏诊断 JSON"></textarea></div></section>`;
}

export function bindLocalData(root,{notice,retryDrafts}){
  if(!root)return;
  let preview=null,working=false;
  const result=root.querySelector('#local-data-result'),cleanup=root.querySelector('#local-data-cleanup');
  const previewButton=root.querySelector('#local-data-preview'),retryButton=root.querySelector('#local-data-retry');
  const selected=()=>[...root.querySelectorAll('[data-local-cleanup]:checked')].map(input=>input.value);
  const busy=value=>{working=value;previewButton.disabled=value;retryButton.disabled=value;cleanup.disabled=value||!preview||!selected().length;};
  const reset=()=>{preview=null;cleanup.disabled=true;root.querySelector('#local-data-candidates').replaceChildren();};
  previewButton.addEventListener('click',async()=>{
    if(working)return;reset();busy(true);
    try{
      preview=await api('/api/settings/local-data/preview',{method:'POST',body:'{}'});
      root.querySelector('#local-data-report').value=JSON.stringify(preview.report,null,2);
      const container=root.querySelector('#local-data-candidates');
      for(const item of preview.candidates){
        const label=document.createElement('label');label.className='check-label';
        const input=document.createElement('input');input.type='checkbox';input.value=item.id;input.dataset.localCleanup='true';
        input.addEventListener('change',()=>{cleanup.disabled=working||!selected().length;});
        label.append(input,document.createTextNode(`${item.label} · ${item.bytes} 字节`));container.append(label);
      }
      result.textContent=`预览完成：有效草稿 ${preview.report.recovery_drafts.valid}，损坏可清理 ${preview.candidates.length}，保留未知/特殊文件 ${preview.report.recovery_drafts.preserved}。${preview.warning} 预览五分钟内有效，文件变化须重做预览。`;
    }catch(error){reset();root.querySelector('#local-data-report').value='';result.textContent=error.message;notice(error.message,true);}
    finally{busy(false);}
  });
  cleanup.addEventListener('click',async()=>{
    if(working||!preview)return;const ids=selected();if(!ids.length)return;
    if(!window.confirm(`将永久删除选中的 ${ids.length} 个损坏恢复草稿。${preview.warning} 是否继续？`))return;
    busy(true);
    try{
      const outcome=await api('/api/settings/local-data/cleanup',{method:'POST',body:JSON.stringify({preview_token:preview.preview_token,selected:ids,confirmation:'清理损坏草稿'})});
      result.textContent=`实际清理 ${outcome.removed_count} 个，共 ${outcome.removed_bytes} 字节；尚未清理 ${outcome.remaining_count} 个。${outcome.warning} 如需继续，请重新预览。`;
    }catch(error){result.textContent=error.message;notice(error.message,true);}
    finally{reset();busy(false);}
  });
  retryButton.addEventListener('click',async()=>{
    if(working)return;busy(true);
    try{result.textContent=await retryDrafts();}catch(error){result.textContent=error.message;notice(error.message,true);}finally{busy(false);}
  });
}
