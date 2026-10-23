import {api} from './api.js';
import {escapeHTML as h} from './views.js';
import {t} from './i18n.js';
export function providerDisplayName(provider){const index=['gg','catie','odys'].indexOf(provider.id);return index<0?provider.name:t('provider.legacy')+' '+(index+1);}
export function renderModelPurposeGuide(){
 const roles=['planning','drafting','review','style','search'];
 return '<section id="model-purpose-guide" class="panel"><h2>'+t('model_use.heading')+'</h2><p>'+t('model_use.note')+'</p><div class="capability-list">'+roles.map(role=>'<article class="capability"><h3>'+t('model_use.'+role)+'</h3><p>'+t('model_use.'+role+'_note')+'</p></article>').join('')+'</div></section>';
}
export function renderCustomProvider(settings,saved=null){
 const id=saved?.id||crypto.randomUUID(),disabled=(settings.configuration_writes_enabled??!settings.offline_mode)?'':'disabled',prefix='custom-'+id;
 const input=(name,key,value='',type='text')=>'<div class="field"><label for="'+prefix+'-'+name+'">'+t(key)+'</label><input id="'+prefix+'-'+name+'" name="'+name+'" type="'+type+'" value="'+h(value)+'" '+disabled+(type==='password'?' autocomplete="new-password"':' required')+'></div>';
 return '<form class="panel provider-card" '+(!saved?'id="custom-provider-form"':'')+' data-custom-provider="'+id+'" autocomplete="off"><h3>'+h(saved?.name||t('provider.add'))+'</h3><p class="hint">'+t('provider.note')+'</p>'+input('name','provider.name',saved?.name||'')+'<div class="field"><label for="'+prefix+'-protocol">'+t('provider.protocol')+'</label><select id="'+prefix+'-protocol" name="protocol" '+disabled+'>'+[['openai-chat','Chat Completions compatible'],['anthropic-messages','Anthropic Messages'],['gemini-content','Google Gemini generateContent']].map(([value,label])=>'<option value="'+value+'" '+(saved?.protocol===value?'selected':'')+'>'+label+'</option>').join('')+'</select></div>'+input('base_url','provider.url',saved?.base_url||'','url')+input('model_id','provider.model',saved?.model_id||'')+input('api_key','provider.key','','password')+'<label><input type="checkbox" name="allow_local" '+(saved?.allow_local?'checked ':'')+disabled+'>'+t('provider.local')+'</label><p class="hint">'+t('provider.keyNote')+'</p><button type="submit" '+disabled+'>'+t('provider.save')+'</button><p class="provider-result" role="status"></p></form>';
}
export async function saveCustomProvider(form){
 const values=Object.fromEntries(new FormData(form));
 const result=await api('/api/providers/custom',{method:'POST',body:JSON.stringify({id:form.dataset.customProvider,name:values.name,base_url:values.base_url,protocol:values.protocol,model_id:values.model_id,api_key:values.api_key,allow_local:form.elements.allow_local.checked})});
 form.elements.api_key.value='';return result;
}
