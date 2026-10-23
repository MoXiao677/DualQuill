const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const {randomUUID}=require('node:crypto');
const source=fs.readFileSync(path.join(__dirname,'../src/novel_writer/ui/static/rules_scope.js'),'utf8').replace(/^import .*;\r?$/gm,'').replace(/export function /g,'function ');
const chapter='11111111-1111-4111-8111-111111111111';
const task='22222222-2222-4222-8222-222222222222';
const workspace={document:{project:{id:'fiction-project'},book_outline:null,chapters:[{id:chapter,number:1,title:'虚构章'}]}};
function harness(overrides={}){
 const calls=[],notices=[],nodes=new Map(),handlers={};let busy=false,refreshes=0,resolves=0;
 const node=(id,value='')=>{const n={id,value,textContent:'',innerHTML:'',checked:true};nodes.set(id,n);return n;};
 node('rule-resolve-chapter',chapter);node('rule-active-task',task);node('rule-task-result');node('rule-prepare-status');node('rule-semantic-input');node('rule-semantic-result');
 const root={dataset:{},addEventListener:(name,handler)=>{handlers[name]=handler;},querySelector:selector=>nodes.get(selector.slice(1))};
 const data={rules:[],task_bindings:[{id:task,chapter_id:chapter,task_type:'draft_chapter'}]};
 const escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const context=vm.createContext({api:async(url,options)=>{const body=options?.body?JSON.parse(options.body):null;calls.push({url,body});if(overrides.api)return overrides.api(url,body);if(url.endsWith('/preview'))return {source_sha256:'source'};if(url.endsWith('/prepare'))return {task:{id:task}};return {};},h:escape,archivedChapterIds:()=>new Set(),crypto:{randomUUID},document:{getElementById:id=>nodes.get(id)},window:{confirm:()=>true},setTimeout});
 vm.runInContext(source+'\nglobalThis.entry={renderScopedRules,bindScopedRules};',context);
 context.entry.bindScopedRules(root,workspace,data,chapter,{busy:value=>{busy=value;},notice:message=>notices.push(message),refresh:async()=>{refreshes++;},resolve:async()=>{resolves++;}});
 return {calls,notices,nodes,data,node,render:(w=workspace,d=data)=>context.entry.renderScopedRules(w,d,chapter,null),refreshes:()=>refreshes,resolves:()=>resolves,click:async(id)=>{handlers.click({target:{closest:()=>({id,dataset:{}})}});for(let i=0;i<20&&busy;i++)await new Promise(resolve=>setImmediate(resolve));assert.equal(busy,false,'UI action settles');}};
}

test('task targets and semantic warnings render with escaped author text',()=>{
 const h=harness();const output=h.render({...workspace,document:{...workspace.document,chapters:[{id:chapter,number:1,title:'<img src=x>'}]}},{rules:[{id:task,scope:'task',kind:'required',text:'<script>bad()</script>',source:'manual',version:1,enabled:true}],task_bindings:h.data.task_bindings});
 assert.match(output,/value="task:22222222/);assert.match(output,/rule-active-task/);assert.match(output,/待核实语义意见/);assert.match(output,/不会自动停用/);assert.ok(!output.includes('<script>bad()'));assert.ok(output.includes('&lt;script&gt;'));
});
test('saving a task rule sends its explicit target and refreshes',async()=>{
 const h=harness();h.node('rule-scope','task');h.node('rule-target','task:'+task);h.node('rule-kind','required');h.node('rule-text','虚构必写');h.node('rule-enabled');await h.click('rule-save');
 assert.equal(h.calls.length,1);assert.match(h.calls[0].url,/\/rules\/save$/);assert.equal(h.calls[0].body.scope_id,task);assert.equal(h.calls[0].body.scope,'task');assert.equal(h.refreshes(),1);
});
test('task resolution stays on explicit binding and escapes rule text',async()=>{
 const h=harness({api:()=>({rules:[{id:task,scope:'task',kind:'required',text:'<b>虚构</b>',version:2}],conflicts:[]})});await h.click('rule-resolve');assert.equal(h.resolves(),0);assert.equal(h.calls[0].body.task_id,task);assert.match(h.calls[0].url,/resolve-task$/);assert.match(h.nodes.get('rule-task-result').innerHTML,/&lt;b&gt;/);
});
test('draft preparation reuses bound request identity and never executes',async()=>{
 const h=harness();await h.click('rule-prepare-draft');assert.deepEqual(h.calls.map(x=>x.url.split('/').pop()),['preview','prepare']);assert.equal(h.calls[0].body.context_options.rule_task_id,task);assert.equal(h.calls[1].body.request_id,task);assert.equal(h.calls[1].body.source_options.context_options.rule_task_id,task);assert.equal(h.calls[1].body.model_options,null);assert.match(h.nodes.get('rule-prepare-status').textContent,/未执行/);
});
test('wrong chapter task binding prevents all preview and prepare requests',async()=>{
 const h=harness();h.data.task_bindings[0].chapter_id='foreign';await h.click('rule-prepare-draft');assert.equal(h.calls.length,0);assert.equal(h.notices.length,1);assert.match(h.notices[0],/本章/);
});
test('semantic opinions use read-only preview and render as text',async()=>{
 const h=harness({api:()=>({proposals:[{status:'needs_verification',reason:'<script>opinion</script>',can_apply:false}],semantic_quality_verified:false})});h.nodes.get('rule-semantic-input').value=JSON.stringify([{rule_ids:['one','two'],quotes:['甲','乙'],reason:'可能'}]);await h.click('rule-semantic-preview');assert.equal(h.calls.length,1);assert.match(h.calls[0].url,/semantic-preview$/);assert.equal(h.calls[0].body.task_id,task);assert.match(h.nodes.get('rule-semantic-result').textContent,/needs_verification/);assert.equal(h.nodes.get('rule-semantic-result').innerHTML,'');
});
test('creating a binding reserves only an identity and selects it',async()=>{
 const h=harness();await h.click('rule-task-new');assert.equal(h.calls.length,1);assert.match(h.calls[0].url,/bind-task$/);assert.equal(h.calls[0].body.chapter_id,chapter);assert.equal(h.calls[0].body.task_type,'draft_chapter');assert.equal(h.nodes.get('rule-active-task').value,h.calls[0].body.request_id);assert.equal(h.refreshes(),1);
});
