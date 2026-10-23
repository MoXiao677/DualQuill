const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function setup(){
 const calls=[],listeners={},notices=[];let refreshes=0;
 const h=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const selection={step_ids:['step'],max_steps:2,max_seconds:15};
 const preview={revision:9,sha256:'frozen',request:selection,items:[{kind:'readonly',source:{text:'<script>saved</script>'}}]};
 const context=vm.createContext({crypto:require('node:crypto'),sessionStorage:{getItem:()=>'',setItem:()=>{}},h,archivedChapterIds:()=>new Set(),renderCreativeDialogue:()=>'',bindCreativeDialogue:()=>{},api:async(url,options)=>{calls.push({url,payload:JSON.parse(options.body)});return url.endsWith('/preview')?preview:{};}});
 const source=name=>fs.readFileSync(path.join(__dirname,'../src/novel_writer/ui/static',name),'utf8').replace(/^import .*;\r?$/gm,'').replace(/\bexport /g,'');
 vm.runInContext(source('console_usage.js')+'\n'+source('console.js')+'\nglobalThis.subject={renderConsole,bindConsole};',context);
 const workspace={revision:8,document:{project:{id:'book'},chapters:[{id:'chapter',number:1,title:'测试章'}]}},session={id:'session',title:'会话',archived:false},detail={session,messages:[],dispatches:[],plan:{revision:1,steps:[]}};
 const run={id:'run',session_id:'session',status:'running',current_step_id:'step',can_advance:true,plan_revision:1,plan_revision_current:1,steps:[{id:'step',status:'queued',type:'chapter.inspect',chapter_id:'chapter'}]};
 const view={revision:8,session,run,background:{batches:[{id:'batch',status:'failed',events:[{detail:{reason:'<img src=x onerror=alert(1)>'}}]}]}};
 const editor={innerHTML:''},panel={innerHTML:''},confirm={checked:false},inputs={'#console-plan-editor':editor,'#console-background-preview':panel,'#console-background-confirm':confirm,'#console-background-max-steps':{value:'2'},'#console-background-max-seconds':{value:'15'}};
 const root={dataset:{},querySelector:selector=>inputs[selector]||null,querySelectorAll:selector=>selector==='[data-console-background-step]:checked'?[{dataset:{consoleBackgroundStep:'step'}}]:[],addEventListener:(name,fn)=>listeners[name]=fn};
 const hooks={busy:()=>{},notice:message=>notices.push(message),refresh:async()=>refreshes++,openTask:()=>{}};
 const render=()=>context.subject.renderConsole(workspace,{sessions:[session]},detail,{}, {runs:[run]},view);
 const bind=()=>context.subject.bindConsole(root,workspace,{},detail,{},hooks,{},view);
 async function click(id){listeners.click({target:{closest:()=>({id,dataset:{}})}});await new Promise(setImmediate);await new Promise(setImmediate);}
 return {calls,notices,panel,confirm,run,view,render,bind,click,refreshes:()=>refreshes};
}
test('background controls escape audit text and never restore batch permission',()=>{
 const s=setup(),html=s.render();assert.match(html,/console-background-preview-request/);assert.match(html,/&lt;img src=x/);assert.doesNotMatch(html,/<img src=x/);
 for(const input of html.matchAll(/<input[^>]*data-console-background-step[^>]*>/g))assert.doesNotMatch(input[0],/\bchecked\b/);
 s.bind();assert.equal(s.calls.length,0);
});
test('preview never starts a batch, confirmation sends the frozen request',async()=>{
 const s=setup();s.render();s.bind();await s.click('console-background-start');assert.equal(s.calls.length,0);
 await s.click('console-background-preview-request');assert.equal(s.calls.at(-1).url,'/api/projects/book/console/runs/run/background/preview');assert.equal(s.calls.some(c=>c.url.endsWith('/start')),false);assert.match(s.panel.innerHTML,/&lt;script&gt;saved/);
 await s.click('console-background-start');assert.equal(s.calls.some(c=>c.url.endsWith('/start')),false);
 s.confirm.checked=true;await s.click('console-background-start');const request=s.calls.at(-1);assert.equal(request.url,'/api/projects/book/console/runs/run/background/start');assert.equal(request.payload.preview_sha256,'frozen');assert.equal(request.payload.expected_revision,9);assert.equal(request.payload.confirmed,true);assert.deepEqual(request.payload.step_ids,['step']);assert.equal(s.refreshes(),1);
});
test('batch pause and cancel use their own authenticated endpoints',async()=>{
 const s=setup();s.render();s.bind();for(const action of ['pause','cancel'])await s.click('console-background-'+action);
 assert.deepEqual(s.calls.map(c=>c.url),['/api/projects/book/console/runs/run/background/pause','/api/projects/book/console/runs/run/background/cancel']);assert.ok(s.calls.every(c=>Object.keys(c.payload).length===0));
});
test('a prepared model step can request fresh batch authorization',()=>{
 const s=setup();s.run.can_advance=false;s.run.steps[0].type='idea';s.run.steps[0].status='awaiting_confirmation';
 const button=()=>s.render().match(/<button id="console-background-preview-request"[^>]*>/)[0];
 assert.doesNotMatch(button(),/\bdisabled\b/);s.bind();assert.equal(s.calls.length,0);
 s.run.blocked_reason='saved source changed';assert.match(button(),/\bdisabled\b/);
 s.run.blocked_reason=null;s.view.background.batches[0].status='running';assert.match(button(),/\bdisabled\b/);
});
