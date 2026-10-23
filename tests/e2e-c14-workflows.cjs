const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {spawn}=require('node:child_process'),{chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),out=process.env.C14_EVIDENCE_DIR;
if(!out)throw new Error('C14_EVIDENCE_DIR must be inside the isolated task directory');
fs.mkdirSync(out,{recursive:true});
const report={checks:[],errors:[],external:[],real_provider_calls:0};let server,browser,page;
const trace=path.join(out,'loopback.json');
async function idle(){await page.waitForFunction(()=>!document.querySelector('#workflow-panel')?.hasAttribute('data-request-busy'));}
async function click(selector){await page.locator(selector).click();await idle();}
(async()=>{
 server=spawn(process.env.NOVEL_WRITER_PYTHON||'python',['-B','-X','utf8','-u','tests/c14_browser_server.py','--trace',trace],{cwd:root,windowsHide:true,env:process.env});
 server.stderr.on('data',d=>fs.appendFileSync(path.join(out,'server.log'),d));
 const url=await new Promise((resolve,reject)=>{let text='';const timer=setTimeout(()=>reject(new Error('fixture startup timeout')),20000);server.stdout.on('data',d=>{text+=d;const m=text.match(/http:\/\/127\.0\.0\.1:\d+/);if(m){clearTimeout(timer);resolve(m[0]);}});server.once('exit',c=>{clearTimeout(timer);reject(new Error('fixture exited '+c));});});
 browser=await chromium.launch({headless:true,executablePath:process.env.NOVEL_WRITER_BROWSER,args:['--disable-gpu']});
 const context=await browser.newContext({viewport:{width:1440,height:900}});
 await context.route('**/*',route=>{const hostname=new URL(route.request().url()).hostname;if(hostname!=='127.0.0.1'){report.external.push(route.request().url());return route.abort();}return route.continue();});
 page=await context.newPage();page.on('pageerror',e=>report.errors.push(e.message));
 await page.goto(url);const pid=(await(await page.request.get(url+'/api/projects')).json())[0].id;
 if(!await page.locator('#project-list').isVisible())await page.locator('#toggle-left').click();
 await page.locator('[data-project="'+pid+'"]').click();
 await page.waitForFunction(()=>!document.querySelector('#toggle-modules').disabled);
 const writing=page.locator('#tabs').getByRole('button',{name:'章节写作',exact:true,includeHidden:true});
 if(!await writing.isVisible())await page.locator('#toggle-modules').click();await writing.click();
 await page.getByRole('button',{name:'工作流与人工节点',exact:true}).click();
 await click('#workflow-use-chapter-chain');
 const editor=page.locator('#workflow-template-json');let spec=JSON.parse(await editor.inputValue());assert.equal(spec.nodes.length,8);
 const idea=page.locator('[data-wf-edit-node="idea"]');await idea.locator('[data-wf-edit="up"]').click();await idle();
 assert.equal(JSON.parse(await editor.inputValue()).nodes[0].id,'idea');
 await page.locator('[data-wf-edit-node="idea"] [data-wf-edit="down"]').click();await idle();
 const before=await editor.inputValue();await page.locator('[data-wf-edit-node="read"] [data-wf-parents]').fill('idea');await page.locator('[data-wf-edit-node="read"] [data-wf-source]').fill('idea');
 await click('[data-wf-edit-node="read"] [data-wf-edit="connect"]');
 assert.equal(await editor.inputValue(),before);assert.match(await page.locator('#workflow-operation').textContent(),/循环/);
 await click('#workflow-use-chapter-chain');await click('#workflow-preflight');await click('#workflow-import');
 await page.waitForSelector('#workflow-create');assert.equal(await page.locator('[name=max_external_calls]').inputValue(),'5');
 await page.getByLabel('本次流程要求',{exact:true}).fill('只使用虚构守塔人与信，生成待作者采纳的章节链。');
 await page.getByLabel('写作角色模型编号',{exact:true}).fill('author-selected-model');await page.getByLabel('审核角色模型编号',{exact:true}).fill('author-selected-model');
 await page.getByLabel('允许本次请求费用未知，仍逐节点确认',{exact:true}).check();await page.getByLabel('新外发模式',{exact:true}).selectOption('confirm_each');
 await page.locator('#workflow-create button[type=submit]').click();await page.waitForSelector('#workflow-run-status');
 const state=async()=> (await(await page.request.get(url+'/api/projects/'+pid)).json());
 const base=await state();assert.equal(base.document.chapters[0].content,'');assert.equal(JSON.parse(fs.readFileSync(trace)).loopback_calls,0);
 report.checks.push('visible graph editor reorders nodes, rejects cycles, saves versioned dedicated template without sending');
 await click('[data-wf-control=start]');await click('#workflow-step');
 for(const id of ['idea','outline','draft','audit','rewrite']){
  await click('#workflow-step');const card=page.locator('[data-wf-node="'+id+'"][data-wf-status=waiting_request]');await card.waitFor();
  await card.getByLabel('我已核对本节点外发内容、上限和未知费用风险',{exact:true}).check();await card.locator('[data-wf-confirm]').click();await idle();
  await page.waitForFunction(async ({pid,id})=>{const s=await(await fetch('/api/projects/'+pid)).json();const a=s.workflow_attempts.find(a=>a.node_id===id);return s.generation_tasks.find(t=>t.id===a.task_id)?.status==='succeeded';},{pid,id});
  await click('#workflow-refresh');await click('#workflow-step');
  assert.equal((await state()).document.chapters[0].content,'');
 }
 assert.equal(JSON.parse(fs.readFileSync(trace)).loopback_calls,5);
 assert.equal(await page.locator('[data-wf-node=outline]').getByText('真实未采纳typed结果',{exact:true}).count(),1);
 report.checks.push('all five model requests require separate confirmation and consume actual typed/candidate outputs; no automatic formal write');
 await click('#workflow-step');const human=page.locator('[data-wf-node=human][data-wf-status=waiting_human]');
 await human.getByLabel('我已逐字核对本次目标与差异',{exact:true}).check();await human.locator('[data-wf-confirm]').click();await idle();await click('#workflow-step');await click('#workflow-step');
 const saved=await state();assert.equal(saved.document.chapters[0].content,'虚构守塔人拾起湿漉漉的信，纸角冰冷。');assert.equal(saved.workflow_receipts.length,1);
 report.checks.push('separate human diff approval adopts the rewritten candidate exactly once');
 // Isolate only GET polling to verify multiple attempts of the same node. The
 // real SSE transport is covered by test_candidate_model_reviews separately.
 const fakeAttempt=(id,status)=>({id,node_id:'same-audit',node_kind:'model_candidate_audit',status,task_status:status,number:id==='old-attempt'?1:2,input_attempt_ids:[],output_refs:[],error_code:null});
 const fakeView={run_id:'c14-preview-fixture',revision:1,status:'running',requires_recovery:false,external_calls:2,reserved_output_tokens:1024,limits:{max_external_calls:3,max_reserved_output_tokens:1536,concurrency:1},network_mode:'confirm_each',execution_mode:'step',nodes:[],events:[{epoch:'test-preview'}],attempts:[fakeAttempt('old-attempt','failed'),fakeAttempt('new-attempt','running')]};
 await page.route('**/workflows/runs/c14-preview-fixture',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({...fakeView,attempts:[fakeView.attempts[0],{...fakeView.attempts[1],stream_preview:{text:'仅属于第二次attempt的临时预览🙂'}}]})}));
 await page.evaluate(async ({workspace,view})=>{const module=await import('/workflow_views.js');const host=document.createElement('div');host.hidden=true;host.id='c14-preview-host';host.innerHTML=module.renderWorkflow(workspace,{templates:[],runs:[]},view,{real_model_enabled:true});document.body.append(host);window.c14StopPreview=module.bindWorkflow(host,workspace,{templates:[],runs:[]},view,workspace.document.chapters[0].id,{refresh:async()=>{},created:async()=>{}});},{workspace:saved,view:fakeView});
 await page.waitForTimeout(2500);
 assert.equal(await page.locator('#c14-preview-host [data-wf-attempt="old-attempt"] [data-workflow-stream-preview]').count(),0);
 assert.match(await page.locator('#c14-preview-host [data-wf-attempt="new-attempt"] [data-workflow-stream-preview]').textContent(),/第二次attempt/);
 await page.evaluate(()=>{window.c14StopPreview();document.querySelector('#c14-preview-host').remove();delete window.c14StopPreview;});
 assert.deepEqual(await state(),saved);
 report.checks.push('stubbed multi-poll GET preview belongs to the new attempt, never the earlier failed card; durable state unchanged');
 await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),false);
 await page.setViewportSize({width:1440,height:900});await page.screenshot({path:path.join(out,'workflow.png'),fullPage:true});
 assert.deepEqual(report.errors,[]);assert.deepEqual(report.external,[]);report.status='passed';
})().catch(async error=>{report.status='failed';report.error=String(error.stack||error);if(page){try{report.body=(await page.locator('body').innerText()).slice(-14000);await page.screenshot({path:path.join(out,'failure.png'),fullPage:true});}catch{}}process.exitCode=1;}).finally(async()=>{fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));if(browser)await browser.close();if(server){server.kill();await new Promise(resolve=>server.once('exit',resolve));}console.log(JSON.stringify(report,null,2));});
