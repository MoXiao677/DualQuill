import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const base=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../src/novel_writer/ui/static');
const modules=new Map();
function sourceURL(filename){
 if(modules.has(filename))return modules.get(filename);
 const source=fs.readFileSync(filename,'utf8').replace(/(from\s+['"])(\.\.?\/[^'"]+)(['"])/g,(_m,a,b,c)=>a+sourceURL(path.resolve(path.dirname(filename),b))+c);
 const url='data:text/javascript;base64,'+Buffer.from(source).toString('base64');modules.set(filename,url);return url;
}
const ui=await import(sourceURL(path.join(base,'deep_reviews.js')));
const workspace={revision:1,document:{project:{id:'fictional-project'},chapters:[{id:'a',number:1,title:'<unsafe>',content:'🙂原文',status:'draft'},{id:'b',number:2,title:'第二章',content:'原文二',status:'draft'}],chapter_outlines:[],book_outline:null},materials:[{id:'m',title:'虚构参考',archived:false}],generation_candidates:[],memories:[],character_arcs:[],key_events:[]};

test('preparation renders all nine checks and explicit scopes without executing requests',()=>{
 const html=ui.renderDeepReviewPrepare(workspace,'a',{real_model_enabled:false,connections:[{id:'gg',name:'虚构连接',model_id:'fictional'}]});
 for(const value of ['relative_time','uncertain_time','duration','causality','motivation','character_knowledge','book_pacing','character_arc','semantic_repetition'])assert.ok(html.includes('value="'+value+'"'));
 for(const value of ['chapter_ids','candidate_ids','material_ids','memory_ids','planning_ids'])assert.ok(html.includes('name="'+value+'"'));
 assert.ok(html.includes('&lt;unsafe&gt;'));assert.ok(!html.includes('<unsafe>'));
 assert.match(html,/<button type="submit" disabled>/);assert.ok(html.includes('不自动改稿'));
});

test('review renders both exact Unicode quotes, coverage and history with no adoption buttons',()=>{
 const evidence=[{source_kind:'chapter',entity_id:'a',version_id:'v1',start:0,end:5,quote:'🙂<文>\r'},{source_kind:'material',entity_id:'m',version_id:'mv1',start:0,end:4,quote:'另侧<&>'}];
 const detail={report:{id:'r',project_id:'p'},method:'model_semantic_opinion',outdated:true,coverage:{selected_chapters:1,total_active_chapters:2,mode:'selected_chapters'},output:{overview:'待核实'},limitations:['不是全网查重或原创性保证'],scope:{sources:[]},findings:[{index:0,status:'false_positive',finding:{category:'repetition',statement:'<意见>',evidence},history:[{reason:'作者有意回环'}]}],response:{response:{complete:true}}};
 const html=ui.renderDeepReview(detail);
 assert.ok(html.includes('🙂&lt;文&gt;&#13;'));assert.ok(html.includes('另侧&lt;&amp;&gt;'));
 assert.ok(html.includes('正文覆盖 1 / 2 章'));assert.ok(html.includes('仅所选章节'));
 assert.ok(html.includes('来源已变化'));assert.ok(html.includes('作者有意回环'));
 for(const kind of ['false_positive','waive','reopen'])assert.ok(html.includes('data-deep-kind="'+kind+'"'));
 assert.ok(!html.includes('data-model-decision="accepted"'));assert.ok(!html.includes('adopt-generation-candidate'));
});

test('source code integrates shared task UI and exposes no browser persistence',()=>{
 const source=fs.readFileSync(path.join(base,'model_tasks.js'),'utf8');
 assert.ok(source.includes('renderDeepReviewPrepare(workspace,chapter,capabilities)'));
 assert.ok(source.includes('bindDeepReviewPrepare(document,workspace,chapter,onPrepared)'));
 const deep=fs.readFileSync(path.join(base,'deep_reviews.js'),'utf8');
 assert.ok(!/localStorage|sessionStorage|indexedDB/.test(deep));
 assert.ok(deep.includes("prompt_version:'deep-review-json-1'"));
});

test('preparation submits the explicit selection once and retries the same frozen request after failure',async()=>{
 const project={...workspace,document:{...workspace.document,project:{id:'fictional-binding'}}};
 ui.renderDeepReviewPrepare(project,'a',{real_model_enabled:true,connections:[{id:'gg',name:'虚构连接',model_id:'fictional'}]});
 const events=new Map(),status={textContent:''},button={disabled:false,isConnected:true};
 const sampling={dataset:{nativeProfile:'{}'},matches:()=>true,querySelector:()=>({value:''})};
 const text=(name,value)=>({name,value,type:'text'}),multi=(name,values)=>({name,multiple:true,selectedOptions:values.map(value=>({value}))});
 const form={elements:[multi('chapter_ids',['b']),multi('candidate_ids',[]),multi('material_ids',['m']),multi('memory_ids',[]),multi('planning_ids',[]),multi('checks',['character_knowledge','semantic_repetition']),text('connection_id','gg'),text('model_id','fictional'),text('instruction','只比较明确来源'),text('temperature','.2'),text('max_tokens','1024'),text('budget_limit','1'),text('max_output_chars','9000'),text('timeout_ms','2000'),{name:'allow_unknown_cost',type:'checkbox',checked:true}],querySelector:selector=>selector==='[type="submit"]'?button:selector==='[data-sampling="deep"]'?sampling:status,addEventListener:(name,handler)=>events.set(name,handler)};
 const root={querySelector:()=>form},prepared=[],requests=[],originalFetch=globalThis.fetch;
 ui.bindDeepReviewPrepare(root,project,'a',async id=>prepared.push(id));
 events.get('change')();
 globalThis.fetch=async(url,options)=>{requests.push({url,body:JSON.parse(options.body)});return requests.length===1?{ok:false,status:409,json:async()=>({error:'虚构网络后核对失败'})}:{ok:true,json:async()=>({task:{id:'fictional-task'}})};};
 const submit=()=>events.get('submit')({preventDefault(){},stopPropagation(){}});
 try{
  await submit();assert.equal(requests.length,1);assert.equal(prepared.length,0);assert.match(status.textContent,/输入保留/);
  await Promise.all([submit(),submit()]);assert.equal(requests.length,2);assert.deepEqual(requests[0],requests[1]);
  const request=requests[1].body;
  assert.equal(request.chapter_id,'b');assert.deepEqual(request.chapter_ids,['b']);assert.deepEqual(request.selection.material_ids,['m']);
  assert.deepEqual(request.selection.checks,['character_knowledge','semantic_repetition']);
  assert.equal(request.expected_revision,1);assert.equal(request.model_options.prompt_version,'deep-review-json-1');assert.equal(request.model_options.max_tokens,1024);
  assert.deepEqual(prepared,['fictional-task']);assert.equal(button.disabled,false);
  assert.ok(requests.every(r=>r.url.endsWith('/deep-reviews/prepare')));
 }finally{globalThis.fetch=originalFetch;}
});

test('whole book creates a durable plan without sending and prepares one explicitly selected batch',async()=>{
 const project={...workspace,document:{...workspace.document,project:{id:'fictional-book-binding'}}};
 ui.renderDeepReviewPrepare(project,'a',{real_model_enabled:true,connections:[{id:'gg',model_id:'fictional'}]});
 const events=new Map(),bookEvents=new Map(),status={textContent:''},button={disabled:false,isConnected:true};
 const sampling={dataset:{nativeProfile:'{}'},matches:()=>true,querySelector:()=>({value:''})};
 const form={elements:[{name:'whole_book',type:'checkbox',checked:true},{name:'allow_unknown_cost',type:'checkbox',checked:true},{name:'batch_size',type:'number',value:'3'}],querySelector:s=>s==='[type="submit"]'?button:s==='[data-sampling="deep"]'?sampling:status,addEventListener:(n,f)=>events.set(n,f)};
 const book={innerHTML:'',addEventListener:(n,f)=>bookEvents.set(n,f)};
 const root={querySelector:s=>s==='#deep-review-books'?book:form},requests=[],prepared=[],originalFetch=globalThis.fetch;
 globalThis.fetch=async(url,options)=>{requests.push({url,body:options?.body?JSON.parse(options.body):null});return {ok:true,json:async()=>url.endsWith('/list')?{runs:[]}:url.endsWith('/create')?{id:'book-run'}:{task:{id:'batch-task'}}};};
 try{
  ui.bindDeepReviewPrepare(root,project,'a',async id=>prepared.push(id));events.get('change')();
  await events.get('submit')({preventDefault(){},stopPropagation(){}});
  const create=requests.find(r=>r.url.endsWith('/create'));
  assert.equal(create.body.batch_size,3);assert.ok(!('chapter_ids' in create.body));assert.ok(!('chapter_id' in create.body));
  assert.deepEqual(prepared,[]);assert.ok(!requests.some(r=>r.url.endsWith('/execute')));
  const batchButton={disabled:false,dataset:{bookBatch:'1',bookRevision:'7'},hasAttribute:n=>n==='data-book-batch',closest:()=>({dataset:{bookRun:'book-run'}})};
  await bookEvents.get('click')({target:{closest:()=>batchButton},preventDefault(){},stopPropagation(){}});
  const request=requests.find(r=>r.url.endsWith('/book-run/prepare'));
  assert.deepEqual(request.body,{batch_index:1,retry_failed:false,expected_revision:7});assert.deepEqual(prepared,['batch-task']);
  assert.ok(!requests.some(r=>r.url.endsWith('/execute')));
 }finally{globalThis.fetch=originalFetch;}
});
