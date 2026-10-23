'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net'),readline=require('node:readline'),crypto=require('node:crypto');
const root=path.resolve(__dirname,'..'),base=path.resolve(root,'..'),temp=process.env.TEMP||path.join(base,'temp'),out=process.env.NOVEL_WRITER_ARTIFACTS||path.join(base,'evidence');
fs.mkdirSync(out,{recursive:true});
const report={status:'running',checks:[],providerCalls:0,errors:[],external:[],navigationInterceptionsCancelled:0,driver_sha256:crypto.createHash('sha256').update(fs.readFileSync(__filename)).digest('hex')};
const runName=process.env.NOVEL_MODEL_UI_RUN||'08-model-browser';
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function freePort(){const s=net.createServer();await new Promise(r=>s.listen(0,'127.0.0.1',r));const p=s.address().port;await new Promise(r=>s.close(r));return p;}
(async()=>{
 const fixture=fs.mkdtempSync(path.join(temp,'model-browser-')),profile=fs.mkdtempSync(path.join(temp,'edge-model-'));
 const backend=cp.spawn('python',['-B',path.join(__dirname,'model_planning_browser_server.py'),fixture],{cwd:root,windowsHide:true,env:{...process.env,TEMP:temp,TMP:temp,PYTHONPATH:path.join(root,'src')+';'+path.join(root,'tests'),PYTHONIOENCODING:'utf-8',PYTHONDONTWRITEBYTECODE:'1'},stdio:['pipe','pipe','pipe']});
 let backendError='';backend.stderr.on('data',d=>backendError+=d);const lines=readline.createInterface({input:backend.stdout});let initialResolve;const first=new Promise(r=>initialResolve=r),pendingCommands=[];
 lines.on('line',line=>{try{const v=JSON.parse(line);if(v.url)initialResolve(v);else pendingCommands.shift()?.(v);}catch{}});
 const command=name=>new Promise(resolve=>{pendingCommands.push(resolve);backend.stdin.write(name+'\n');});
 let edge,ws,ui;
 try{
  const fixtureInfo=await Promise.race([first,new Promise((_,reject)=>setTimeout(()=>reject(Error('fixture startup '+backendError)),10000))]);
  const port=await freePort();edge=cp.spawn('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',[
   '--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-component-update','--disable-sync','--disable-extensions','--disable-breakpad','--metrics-recording-only',
   '--remote-debugging-address=127.0.0.1','--remote-debugging-port='+port,'--user-data-dir='+profile,'--disk-cache-dir='+path.join(profile,'cache'),'--window-size=1440,1000',fixtureInfo.url],{windowsHide:true,stdio:'ignore',env:{...process.env,TEMP:temp,TMP:temp}});
  let target;for(let i=0;i<80&&!target;i++){try{target=(await(await fetch('http://127.0.0.1:'+port+'/json/list')).json()).find(t=>t.type==='page');}catch{}if(!target)await sleep(100);}
  assert(target,'isolated Edge CDP startup');ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise((r,j)=>{ws.addEventListener('open',r,{once:true});ws.addEventListener('error',j,{once:true});});
  let seq=0;const pending=new Map();ws.addEventListener('message',event=>{const m=JSON.parse(event.data);if(m.id){const p=pending.get(m.id);if(p){pending.delete(m.id);clearTimeout(p.timer);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result);}}
   if(m.method==='Runtime.exceptionThrown')report.errors.push(m.params.exceptionDetails.exception?.description||m.params.exceptionDetails.text);
   if(m.method==='Network.requestWillBeSent'&&/^https?:/.test(m.params.request.url)&&!m.params.request.url.startsWith(fixtureInfo.url))report.external.push(m.params.request.url);
  });
  const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq,timer=setTimeout(()=>reject(Error('CDP timeout '+method)),10000);pending.set(id,{resolve,reject,timer});ws.send(JSON.stringify({id,method,params}));});
  const evaluate=async expression=>{const v=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(v.exceptionDetails)throw Error(v.exceptionDetails.exception?.description||v.exceptionDetails.text);return v.result.value;};
  const wait=async expression=>{const end=Date.now()+15000;while(Date.now()<end){if(await evaluate(expression))return;await sleep(100);}throw Error('UI timeout '+expression+' '+await evaluate('document.body.innerText.slice(-4500)'));};
  const click=async selector=>{await wait(`document.querySelector(${JSON.stringify(selector)})&&!document.querySelector(${JSON.stringify(selector)}).disabled`);await evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);};
  const fill=(selector,value)=>evaluate(`(()=>{const n=document.querySelector(${JSON.stringify(selector)});n.value=${JSON.stringify(value)};n.dispatchEvent(new Event('input',{bubbles:true}));n.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  const check=selector=>evaluate(`(()=>{const n=document.querySelector(${JSON.stringify(selector)});n.checked=true;n.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  ui={send,evaluate,wait,click,fill,check};await send('Runtime.enable');await send('Network.enable');await send('Page.enable');
  // Only page requests to this isolated local application are permitted during this fixture.
  await send('Fetch.enable',{patterns:[{urlPattern:'*',requestStage:'Request'}]});ws.addEventListener('message',event=>{const m=JSON.parse(event.data);if(m.method==='Fetch.requestPaused'){
   const p=m.params;const action=p.request.url.startsWith(fixtureInfo.url)||/^(data:|blob:)/.test(p.request.url)?send('Fetch.continueRequest',{requestId:p.requestId}):send('Fetch.failRequest',{requestId:p.requestId,errorReason:'BlockedByClient'});
   void action.catch(error=>{if(String(error).includes('Invalid InterceptionId.'))report.navigationInterceptionsCancelled++;else report.errors.push('CDP interception: '+error.message);});
  }});
  await wait("document.querySelector('#overview-task')?.textContent==='当前窗口空闲'");await sleep(500);await evaluate(`sessionStorage.setItem('novel-project',${JSON.stringify(fixtureInfo.project_id)});location.reload()`);
  await wait("document.querySelector('#tabs [data-view=outline]')&&!document.querySelector('#new-project').disabled");await click('#tabs [data-view=outline]');await wait("document.querySelector('[data-model-planning-form]')");
  const panel='[data-model-planning]',form=panel+' form';await evaluate("document.querySelector('[data-body-planning]').open=true");
  await fill(form+' [name=connection_id]',fixtureInfo.connection_id);await fill(form+' [name=context_budget_chars]','100000');await check(form+' [name=allow_unknown_cost]');await click('[data-model-source]');await wait("document.querySelector('[data-model-source-preview]').textContent.includes('😀林默')");
  await click(form+' [type=submit]');await wait("document.querySelector('[data-model-send]')");
  assert.equal(await evaluate("document.querySelector('[data-model-send]').disabled"),true);assert.equal((await command('hold')).calls,0);
  assert((await evaluate("document.querySelector('[data-model-tasks]').textContent")).includes('request_sha256'));report.checks.push('source preview/freeze send zero requests; exact wire/destination/budget displayed and per-request send starts disabled');
  await check('[data-model-confirm]');await click('[data-model-send]');await wait("document.querySelector('[data-model-tasks]').textContent.includes('临时流式预览')");await sleep(2200);
  assert.equal(await evaluate("Boolean(window.modelInjected||document.querySelector('[data-model-tasks] img'))"),false);
  const state=()=>evaluate(`fetch('/api/projects/${fixtureInfo.project_id}').then(r=>r.json())`);let saved=await state();assert.equal(saved.model_planning_candidates.length,0);assert.equal(saved.body_planning_proposals.length,0);assert.equal(saved.key_events[0].status,'planned');assert.equal(saved.document.chapters[0].content,fixtureInfo.body);
  await evaluate("document.querySelector('[data-model-tasks]').scrollIntoView({block:'start'})");
  assert.equal(await evaluate("(()=>{const b=document.querySelector('[data-model-cancel]'),r=b.getBoundingClientRect(),p=document.querySelector('[data-model-planning]').getBoundingClientRect();return r.left>=p.left&&r.right<=p.right&&r.bottom<=innerHeight})()"),true);
  await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:false});await sleep(100);
  assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth+2'),true);
  await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});await sleep(100);
  const screenshot=await send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(out,runName+'-stream.png'),Buffer.from(screenshot.data,'base64'));report.checks.push('two polling cycles preserve escaped transient SSE text; no candidate, proposal, planning or manuscript change before terminal frame');
  await command('release');await wait("document.querySelector('[data-model-transfer-preview]')");await click('[data-model-transfer-preview]');await wait("!document.querySelector('[data-model-propose]').disabled");
  // Explicit automated author confirmation for this fixture only.
  await evaluate('window.confirm=()=>true');await click('[data-model-propose]');await wait("document.querySelector('[data-body-proposal]')");saved=await state();assert.equal(saved.key_events[0].status,'planned');assert.equal(saved.model_planning_links.length,1);
  await evaluate("document.querySelector('[data-body-planning]').open=true");await click('[data-body-preview]');await wait("!document.querySelector('[data-body-accept]').disabled");await click('[data-body-accept]');await wait(`fetch('/api/projects/${fixtureInfo.project_id}').then(r=>r.json()).then(s=>s.key_events[0].status==='occurred')`);saved=await state();assert.equal(saved.document.chapters[0].content,fixtureInfo.body);report.checks.push('individual suggestion becomes pending proposal only; independent impact preview and author acceptance create occurrence with exact saved quote');
  await evaluate("document.querySelector('[data-body-planning]').open=true");await command('hold');await click('[data-model-source]');await wait("!document.querySelector('[data-model-planning-form] [type=submit]').disabled");await click(form+' [type=submit]');await wait("document.querySelector('[data-model-send]')");await check('[data-model-confirm]');await click('[data-model-send]');await wait("document.querySelector('[data-model-tasks]').textContent.includes('临时流式预览')");await click('[data-model-cancel]');await wait(`fetch('/api/projects/${fixtureInfo.project_id}').then(r=>r.json()).then(s=>s.model_planning_events.at(-1).status==='cancelled')`);await command('release');await sleep(300);saved=await state();assert.equal(saved.model_planning_candidates.length,1);assert.equal(saved.body_planning_receipts.length,1);report.checks.push('cancel remains accessible during execution; late stream does not create a second candidate/proposal or acceptance');
  await evaluate('location.reload()');await wait("document.querySelector('#new-project')&&!document.querySelector('#new-project').disabled");await click('#tabs [data-view=outline]');await wait("document.querySelector('[data-model-planning]')");assert.equal((await command('release')).calls,2);assert.equal(await evaluate("document.querySelector('[data-model-tasks]').textContent.includes('临时流式预览')"),false);
  report.providerCalls=2;assert.deepEqual(report.errors,[]);assert.deepEqual(report.external,[]);report.checks.push('page reopen preserves history without resend or temporary preview; no renderer exceptions/external page requests; 1440 cancel visible and 390 has no page overflow');report.status='passed';
 }catch(error){report.status='failed';report.error=String(error.stack||error);if(ui)try{report.body=await ui.evaluate('document.body.innerText.slice(-12000)');}catch{}throw error;}
 finally{
  if(ui)try{await ui.send('Browser.close');}catch{}if(ws)ws.close();if(edge&&edge.exitCode===null)edge.kill();
  backend.stdin.write('release\nstop\n');await sleep(300);if(backend.exitCode===null)backend.kill();
  report.backendErrors=backendError;fs.writeFileSync(path.join(out,runName+'-report.json'),JSON.stringify(report,null,2));
 }
})().then(()=>process.stdout.write(JSON.stringify(report)+'\n')).catch(e=>{process.stderr.write(String(e.stack||e)+'\n');process.exitCode=1;});
