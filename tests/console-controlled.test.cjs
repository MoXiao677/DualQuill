// Trusted UI module behavior in a VM; no browser, network, or provider access.
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const crypto=require('node:crypto');
const staticRoot=path.join(__dirname,'../src/novel_writer/ui/static');
function setup(){
 const calls=[],notices=[],listeners={},storage=new Map();let refreshes=0;
 const escapeHTML=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const context=vm.createContext({crypto,sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},h:escapeHTML,
  archivedChapterIds:()=>new Set(),renderCreativeDialogue:()=>'',bindCreativeDialogue:()=>{},
  api:async(url,request)=>{calls.push({url,payload:JSON.parse(request.body)});return {steps:[],notice:'已校验'};}});
 const source=name=>fs.readFileSync(path.join(staticRoot,name),'utf8').replace(/^import .*;\r?$/gm,'').replace(/\bexport /g,'');
 vm.runInContext(source('console_usage.js')+'\n'+source('console.js')+'\nglobalThis.subject={renderConsole,bindConsole,selectConsoleSession,renderActualUsage};',context);
 const workspace={revision:7,document:{project:{id:'book'},chapters:[{id:'chapter',number:1,title:'虚构章节'}]}};
 const session={id:'session',title:'虚构会话',archived:false},listing={sessions:[session]};
 const detail={session,messages:[],dispatches:[],plan:{revision:2,steps:[]},tools:[],usage:{external_attempts:0,cost_status:'not_requested',reported_subtotals:{}}};
 const run={id:'run',status:'running',current_step_id:'step',can_advance:true,can_pause:true,can_cancel:true,can_skip:true,plan_revision:2,plan_revision_current:2,steps:[{id:'step',type:'chapter.inspect',chapter_id:'chapter',status:'queued',instruction:'<script>untrusted</script>'}]};
 const runDetail={revision:7,session,run};context.subject.selectConsoleSession(session.id);
 const html=()=>context.subject.renderConsole(workspace,listing,detail,{}, {runs:[{...run,session_id:session.id,step_count:1}]},runDetail);
 const editor={innerHTML:''},root={dataset:{},checked:[],querySelector:q=>q==='#console-plan-editor'?editor:null,querySelectorAll:q=>q==='[data-console-readonly]:checked'?root.checked:[],addEventListener:(name,fn)=>listeners[name]=fn};
 const hooks={busy:()=>{},notice:(...v)=>notices.push(v),refresh:async()=>refreshes++,openTask:()=>{}};
 const bind=()=>context.subject.bindConsole(root,workspace,listing,detail,{},hooks,{},runDetail);
 async function click(id,dataset={}){listeners.click({target:{closest:()=>({id,dataset})}});await new Promise(setImmediate);await new Promise(setImmediate);}
 return {context,calls,notices,root,html,bind,click,storage,refreshes:()=>refreshes};
}
test('rendered controls escape model text and never restore a read permission',()=>{
 const s=setup();const html=s.html();
 assert.match(html,/&lt;script&gt;untrusted&lt;\/script&gt;/);assert.doesNotMatch(html,/<script>untrusted/);
 assert.match(html,/console-run-readonly/);assert.match(html,/console-proposal-preview/);
 for(const input of html.matchAll(/<input[^>]*data-console-readonly[^>]*>/g))assert.doesNotMatch(input[0],/\bchecked\b/);
 s.bind();assert.equal(s.calls.length,0);s.html();assert.equal(s.calls.length,0);
 assert.equal(s.storage.size,1);assert.equal(s.storage.has('allow_readonly'),false);
});
test('continuous advance requires explicit checkboxes and sends only allowlisted ids',async()=>{
 const s=setup();s.html();s.bind();await s.click('console-run-readonly');
 assert.equal(s.calls.length,0);assert.match(s.notices[0][0],/先勾选/);
 s.root.checked=[{dataset:{consoleReadonly:'chapter.inspect'}}];await s.click('console-run-readonly');
 assert.equal(s.calls.length,1);assert.equal(s.calls[0].url,'/api/projects/book/console/runs/run/advance');
 assert.deepEqual(s.calls[0].payload.allow_readonly,['chapter.inspect']);assert.equal(s.calls[0].payload.expected_revision,7);
 assert.equal(s.refreshes(),1);assert.equal(s.calls.some(v=>/execute|adopt|apply/.test(v.url)),false);
});
test('pause, resume and cancel are explicit actions and binding does not advance',async()=>{
 const s=setup();s.html();s.bind();
 for(const action of ['pause','resume','cancel'])await s.click('console-run-'+action);
 assert.deepEqual(s.calls.map(v=>v.url.split('/').at(-1)),['pause','resume','cancel']);
 assert.ok(s.calls.every(v=>!('allow_readonly' in v.payload)));
});
test('unknown or partial usage remains readable without a fabricated cost or token total',()=>{
 const s=setup();const html=s.context.subject.renderActualUsage({status:'partial_or_unknown',external_attempts:1,reported_subtotals:{prompt_tokens:20,completion_tokens:null,total_tokens:null}});
 assert.match(html,/费用未知/);assert.match(html,/输出 未知/);assert.match(html,/小计不代表完整总量/);assert.doesNotMatch(html,/0 USD|\$0/);
});
