import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const source=fs.readFileSync(new URL('../src/novel_writer/ui/static/materials.js',import.meta.url),'utf8');
const materials=await import('data:text/javascript;base64,'+Buffer.from(source.replace("import { api } from './api.js';",'const api=(...args)=>globalThis.__c08Api(...args);')).toString('base64'));
const memoryAutomationUrl='data:text/javascript;base64,'+Buffer.from(fs.readFileSync(new URL('../src/novel_writer/ui/static/memory_automation.js',import.meta.url),'utf8')).toString('base64');
const viewsSource=fs.readFileSync(new URL('../src/novel_writer/ui/static/views.js',import.meta.url),'utf8').replace("'./memory_automation.js'",JSON.stringify(memoryAutomationUrl));
const views=await import('data:text/javascript;base64,'+Buffer.from(viewsSource).toString('base64'));
const workspace={revision:3,document:{project:{id:'fiction',title:'虚构书'},chapters:[{id:'chapter',number:1,title:'第一章'}]}};
const material={id:'material',title:'<img src=x>',format:'txt',tags:[],version_count:1,current_version_number:1,char_count:20,index_status:'stale',archived:false};

function element(){return {events:{},hidden:false,disabled:false,textContent:'',addEventListener(type,fn){this.events[type]=fn;}};}
function controls(){
  const rebuild=element(),cancel=element(),status=element(),suggest=element(),suggestions=element(),form=element();
  const elements={'[data-material-rebuild]':rebuild,'#material-index-cancel':cancel,'#material-index-status':status,'#material-suggest-tags':suggest,'#material-tag-suggestions':suggestions,'#material-update-form':form};
  const detail={dataset:{materialId:'material'},querySelector:key=>elements[key],querySelectorAll:()=>[]};
  const root={isConnected:true,querySelector:key=>key==='#material-detail'?detail:null,querySelectorAll:()=>[]};
  return {root,rebuild,cancel,status,suggest,suggestions,form};
}

test('render exposes explicit lexical modes and escapes material source text',()=>{
  const html=materials.renderMaterials(workspace,{materials:[material],tags:[]},{material,versions:[]},{text:'</textarea><script>fiction</script>'});
  assert.ok(html.includes('&lt;img src=x&gt;'));assert.ok(!html.includes('<script>fiction</script>'));
  assert.ok(html.includes('material-index-cancel'));assert.ok(html.includes('可追溯标签建议'));
  const retrieval=views.renderRetrieval(workspace,'chapter',[],{materials:[material]});
  assert.ok(retrieval.includes('value="literal"'));assert.ok(retrieval.includes('value="hybrid"'));
  assert.ok(retrieval.includes('不是语义检索'));assert.ok(!retrieval.includes('value="material" selected'));
});

test('running index can be cancelled while polling and reports confirmed rollback',async()=>{
  const c=controls();let cancelled=false;const calls=[];
  globalThis.__c08Api=async(path,options={})=>{
    calls.push({path,options});
    if(path.endsWith('/cancel')){cancelled=true;return {status:'cancelling'};}
    if(options.method==='POST')return {id:'job',status:'running'};
    return {id:'job',status:cancelled?'cancelled':'running'};
  };
  materials.bindMaterials(c.root,workspace,{},{});
  const done=c.rebuild.events.click({currentTarget:c.rebuild});await new Promise(resolve=>setImmediate(resolve));
  assert.equal(c.cancel.hidden,false);await c.cancel.events.click();await done;
  assert.equal(c.status.textContent,'已取消，索引与历史未变。');assert.equal(c.cancel.hidden,true);assert.equal(c.rebuild.disabled,false);
  assert.equal(calls.find(v=>v.path.endsWith('/cancel')).options.body,'{}');
});

test('completed index shows measured reuse and refreshes saved revision',async()=>{
  const c=controls();const notices=[];let refreshed=false;
  globalThis.__c08Api=async()=>({id:'job',status:'succeeded',result:{index_update:{reused_chunks:2,rebuilt_chunks:1}}});
  materials.bindMaterials(c.root,workspace,{}, {notice:text=>notices.push(text),refresh:async()=>{refreshed=true;}});
  await c.rebuild.events.click({currentTarget:c.rebuild});assert.ok(refreshed);assert.match(notices[0],/复用 2 窗口，重算 1 窗口/);
});

test('tag evidence remains text and never writes update automatically',async()=>{
  const c=controls();const calls=[];
  globalThis.__c08Api=async(path)=>{calls.push(path);return {suggestions:[{tag:'<x>',method:'heading',version_id:'v',start:0,end:3,sha256:'abc',evidence:'<x>'}]};};
  materials.bindMaterials(c.root,workspace,{},{});await c.suggest.events.click();
  assert.equal(calls.length,1);assert.ok(calls[0].endsWith('/suggest-tags'));assert.ok(c.suggestions.textContent.includes('<x>'));
});

test('background completion preserves unsaved material form instead of rerendering',async()=>{
  const c=controls();let refreshed=false;
  globalThis.__c08Api=async()=>({id:'job',status:'succeeded',result:{index_update:{reused_chunks:2,rebuilt_chunks:1}}});
  materials.bindMaterials(c.root,workspace,{}, {refresh:async()=>{refreshed=true;}});c.form.events.input();
  await c.rebuild.events.click({currentTarget:c.rebuild});assert.equal(refreshed,false);assert.match(c.status.textContent,/保留了尚未保存的表单输入/);
});
