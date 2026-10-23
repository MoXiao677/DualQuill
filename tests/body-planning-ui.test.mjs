import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const source=await readFile(new URL('../src/novel_writer/ui/static/full_book_planning.js',import.meta.url),'utf8');
const module=await import('data:text/javascript;base64,'+Buffer.from(source.replace("import { api } from './api.js';","const api=(...args)=>globalThis.bodyPlanningTestApi(...args);").replace("import {renderModelPlanning,bindModelPlanning} from './model_planning.js';","const renderModelPlanning=()=>'';const bindModelPlanning=()=>{};")).toString('base64'));
const workspace={revision:8,document:{project:{id:'fictional-project'},book_outline:null}};
const listing={method:'显式规划',chapters:[{id:'c1',number:1,title:'虚构',content:'😀旧钥匙。'}],characters:[],character_arcs:[],character_arc_stages:[],key_events:[],chapter_dependencies:[],dependency_kinds:[],
  deviation:{references:[],deviations:[],deviations_by_reason:{late:0,early:0,unplanned:0,missing:0,blocked:0},confirmed_chapter_count:0,latest_confirmed_chapter_number:null,stage_counts:{planned:0,occurred:0,dropped:0},event_counts:{planned:0,occurred:0,dropped:0},dependency_counts:{enabled:0,disabled:0,archived:0}},
  body_planning:{locks:[],entities:[],proposals:[{id:'p1',origin:'ai_import',reason:'<script>虚构建议</script>',quote:'😀旧钥匙。',actions:[{action:'create_event',values:{title:'<img src=x>'}}],receipt:null,outdated:false}]}};
const settle=()=>new Promise(resolve=>setImmediate(resolve));

function controls(withForm=false){
  const listeners={},notices=[],calls=[];
  const accept={disabled:true};const impact={innerHTML:''};
  const card={dataset:{bodyProposal:'p1'},querySelector:selector=>selector.includes('impact')?impact:accept};
  const form=withForm?{elements:{chapter_id:{value:'c1'},quote:{value:'😀旧钥匙。'},start:{value:''},completion:{hidden:true,value:''}},addEventListener:()=>{}}:null;
  const root={querySelectorAll:()=>[card],querySelector:selector=>selector==='[data-body-form]'?form:null,addEventListener:(name,handler)=>{(listeners[name]??=[]).push(handler);}};
  globalThis.window={confirm:()=>true};
  globalThis.bodyPlanningTestApi=async(path,options)=>{calls.push({path,body:JSON.parse(options.body)});if(path.endsWith('/preview'))return {preview_sha256:'issued-token',deviation:{reason_delta:{late:-1,early:0,unplanned:0,missing:0,blocked:0}},impact:{later_chapter_ids:[],foreshadow_node_ids:[]},changes:[{after:'<img src=x>'}],limitations:['引文验证不等于语义质量']};if(path.endsWith('/completion'))return {model_request_sent:false,quote:'😀旧钥匙。'};return {decision:'accepted'};};
  let oldDisabled;
  module.bindFullBookPlanning(root,workspace,listing,{busy:value=>{if(value){oldDisabled=accept.disabled;accept.disabled=true;}else accept.disabled=oldDisabled;},notice:(...args)=>notices.push(args),refresh:async()=>{}});
  const click=async(attribute,dataset,disabled=false)=>{
    const button={dataset,disabled,hasAttribute:name=>name===attribute,closest:()=>card};
    const event={target:{closest:selector=>selector.includes(attribute)?button:null}};
    for(const handler of listeners.click||[])handler(event);
    await settle();await settle();
  };
  return {click,calls,notices,accept,impact,form};
}

test('render keeps proposals pending, escapes author/import text and disables acceptance',()=>{
  const html=module.renderFullBookPlanning(workspace,listing);
  assert.match(html,/影响预览/);assert.match(html,/data-body-accept="p1" disabled/);
  assert.match(html,/&lt;script&gt;虚构建议&lt;\/script&gt;/);assert.doesNotMatch(html,/<script>虚构建议/);
  assert.match(html,/&lt;img src=x&gt;/);assert.match(html,/模型候选均须独立转待审提案/);
});

test('acceptance requires issued preview and sends current revision with exact token',async()=>{
  const ui=controls();
  await ui.click('data-body-accept',{bodyAccept:'p1'});
  assert.equal(ui.calls.length,0);assert.match(ui.notices[0][0],/先查看影响预览/);
  await ui.click('data-body-preview',{bodyPreview:'p1'});
  assert.equal(ui.accept.disabled,false);assert.match(ui.impact.innerHTML,/&lt;img src=x&gt;/);
  await ui.click('data-body-accept',{bodyAccept:'p1'});
  assert.equal(ui.calls.length,2);assert.equal(ui.calls[1].body.preview_sha256,'issued-token');
  assert.equal(ui.calls[1].body.expected_revision,8);assert.equal(ui.calls[1].body.decision,'accepted');
});

test('explicit reject needs no preview and sends no acceptance token',async()=>{
  const ui=controls();await ui.click('data-body-reject',{bodyReject:'p1'});
  assert.equal(ui.calls.length,1);assert.equal(ui.calls[0].body.decision,'rejected');
  assert.equal(ui.calls[0].body.preview_sha256,undefined);
});

test('completion uses Unicode offsets and shows readonly context without a generation request',async()=>{
  const ui=controls(true);await ui.click('data-body-context',{});
  assert.equal(ui.calls.length,1);assert.equal(ui.calls[0].body.start,0);assert.equal(ui.calls[0].body.end,5);
  assert.equal(ui.form.elements.completion.hidden,false);assert.match(ui.form.elements.completion.value,/"model_request_sent": false/);
});
