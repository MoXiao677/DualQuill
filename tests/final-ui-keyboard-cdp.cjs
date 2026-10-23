'use strict';
// Dedicated source-UI acceptance; run only while parent resource owner is 04.
const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process');
const net=require('node:net'),readline=require('node:readline'),crypto=require('node:crypto');
const workspace=path.resolve(__dirname,'..'),task=path.dirname(workspace),shared=path.dirname(task);
const run=process.argv[2];
if(!/^[a-z0-9-]+$/.test(run||''))throw Error('An immutable run name is required');
const grant=JSON.parse(fs.readFileSync(path.join(shared,'resource-queue.json'),'utf8'));
if(grant.owner!=='04-ui-keyboard')throw Error('Parent exclusive UI window is required before launching any process');
const temp=path.join(task,'temporary',run),out=path.join(task,'evidence',run);
if(fs.existsSync(out))throw Error('Never overwrite an original run');
fs.mkdirSync(temp,{recursive:true});fs.mkdirSync(out,{recursive:true});
fs.writeFileSync(path.join(out,'resource-grant.json'),JSON.stringify(grant,null,2));
const source=path.resolve(process.env.FINAL_UI_SOURCE_ROOT||workspace);
if(source!==workspace&&source!==path.join(shared,'baseline'))throw Error('Disallowed source root');
const env={...process.env,TEMP:temp,TMP:temp,PYTHONDONTWRITEBYTECODE:'1',PYTHONIOENCODING:'utf-8',FINAL_UI_SOURCE_ROOT:source};
const hash=file=>crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const manifest=JSON.parse(fs.readFileSync(path.join(shared,'baseline-manifest.json'),'utf8'));
const report={task:'04-ui-keyboard',run,status:'running',started_at:new Date().toISOString(),source,checks:[],failures:[],matrix:[],errors:[],external:[],blockedRequests:[],realPaidCalls:0,ime:'synthetic DOM composition only; Windows system IME unverified',source_sha256:Object.fromEntries(Object.keys(manifest.source_sha256).map(p=>[p,hash(path.join(source,p))])),driver_sha256:hash(__filename),fixture_sha256:hash(path.join(__dirname,'final_ui_keyboard_server.py')),processes:[]};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let backend,browser,ws,ui,fixture,backendError='',browserError='',pendingCommands=[];
const freePort=async()=>{for(let i=0;i<10;i++){const s=net.createServer();await new Promise(r=>s.listen(0,'127.0.0.1',r));const p=s.address().port;await new Promise(r=>s.close(r));if(p!==8765)return p;}throw Error('No safe port');};
const check=async(name,fn)=>{const start=Date.now();try{const detail=await fn();report.checks.push({name,status:'passed',seconds:(Date.now()-start)/1000,detail});}catch(e){report.failures.push({name,error:String(e.stack||e)});report.checks.push({name,status:'failed',seconds:(Date.now()-start)/1000});}process.stdout.write(JSON.stringify({event:'check',name,status:report.checks.at(-1).status,seconds:report.checks.at(-1).seconds})+'\n');};
const assert=(value,message)=>{if(!value)throw Error(message);};
const command=name=>new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('fixture command timeout '+name)),10000);pendingCommands.push(v=>{clearTimeout(timer);resolve(v);});backend.stdin.write(name+'\n');});
async function screenshot(name){const v=await ui.send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});const file=path.join(out,name+'.png');fs.writeFileSync(file,Buffer.from(v.data,'base64'));return {file,sha256:hash(file)};}
async function key(key,code,modifiers=0){await ui.send('Input.dispatchKeyEvent',{type:'keyDown',key,code,modifiers,windowsVirtualKeyCode:key.length===1?key.toUpperCase().charCodeAt(0):({Enter:13,Tab:9,Escape:27,ArrowDown:40}[key]||0)});await ui.send('Input.dispatchKeyEvent',{type:'keyUp',key,code,modifiers});}
const q=JSON.stringify;
async function launch(){
 backend=cp.spawn(process.env.NOVEL_WRITER_PYTHON||'python',['-B','-X','utf8','-u',path.join(__dirname,'final_ui_keyboard_server.py'),path.join(temp,'fixture')],{cwd:workspace,windowsHide:true,env,stdio:['pipe','pipe','pipe']});
 report.processes.push({role:'fixture',pid:backend.pid});backend.stderr.on('data',d=>backendError+=d);
 const lines=readline.createInterface({input:backend.stdout});let init;
 const first=new Promise((resolve,reject)=>{init=resolve;const timer=setTimeout(()=>reject(Error('fixture startup '+backendError)),20000);backend.once('exit',c=>{clearTimeout(timer);reject(Error('fixture exit '+c+' '+backendError));});});
 lines.on('line',line=>{try{const v=JSON.parse(line);if(v.url)init(v);else pendingCommands.shift()?.(v);}catch{}});
 fixture=await first;assert(new URL(fixture.url).hostname==='127.0.0.1'&&new URL(fixture.url).port!=='8765','safe app endpoint');report.fixture=fixture;
 const port=await freePort(),profile=path.join(temp,'edge-profile');report.profile=profile;report.cdpPort=port;
 browser=cp.spawn(process.env.NOVEL_WRITER_BROWSER||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-component-update','--disable-sync','--disable-extensions','--disable-breakpad','--metrics-recording-only','--remote-debugging-address=127.0.0.1','--remote-debugging-port='+port,'--user-data-dir='+profile,'--disk-cache-dir='+path.join(profile,'cache'),'--window-size=1440,900','about:blank'],{windowsHide:true,stdio:['ignore','pipe','pipe'],env});
 report.processes.push({role:'headless-edge',pid:browser.pid});browser.stderr.on('data',d=>browserError+=d);browser.stdout.on('data',()=>{});
 let target;for(let i=0;i<100&&!target;i++){try{target=(await(await fetch('http://127.0.0.1:'+port+'/json/list')).json()).find(t=>t.type==='page');}catch{}if(!target)await sleep(100);}assert(target,'headless CDP target');
 ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise((r,j)=>{ws.addEventListener('open',r,{once:true});ws.addEventListener('error',j,{once:true});});
 let seq=0;const pending=new Map();
 const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq,timer=setTimeout(()=>{pending.delete(id);reject(Error('CDP timeout '+method));},20000);pending.set(id,{resolve,reject,timer});ws.send(JSON.stringify({id,method,params}));});
 ws.addEventListener('message',event=>{const m=JSON.parse(event.data);if(m.id&&pending.has(m.id)){const p=pending.get(m.id);pending.delete(m.id);clearTimeout(p.timer);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result);}
  if(m.method==='Runtime.exceptionThrown')report.errors.push(m.params.exceptionDetails.exception?.description||m.params.exceptionDetails.text);
  if(m.method==='Network.requestWillBeSent'&&/^https?:/.test(m.params.request.url)&&!m.params.request.url.startsWith(fixture.url+'/'))report.external.push(m.params.request.url);
  if(m.method==='Fetch.requestPaused'){const p=m.params,allowed=p.request.url.startsWith(fixture.url+'/')||/^(data:|blob:|about:)/.test(p.request.url);if(!allowed)report.blockedRequests.push(p.request.url);void send(allowed?'Fetch.continueRequest':'Fetch.failRequest',allowed?{requestId:p.requestId}:{requestId:p.requestId,errorReason:'BlockedByClient'}).catch(e=>{if(!String(e).includes('Invalid InterceptionId'))report.errors.push(String(e));});}
 });
 const evaluate=async expression=>{const v=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(v.exceptionDetails)throw Error(v.exceptionDetails.exception?.description||v.exceptionDetails.text);return v.result.value;};
 const wait=async(expression,timeout=15000)=>{const end=Date.now()+timeout;while(Date.now()<end){if(await evaluate(expression))return;await sleep(80);}throw Error('UI timeout '+expression+' '+await evaluate('document.body.innerText.slice(-2000)'));};
 const click=async selector=>{await wait(`document.querySelector(${q(selector)})&&!document.querySelector(${q(selector)}).disabled`);await evaluate(`document.querySelector(${q(selector)}).click()`);};
 const fill=async(selector,value)=>{await wait(`document.querySelector(${q(selector)})`);await evaluate(`(()=>{const n=document.querySelector(${q(selector)});n.value=${q(value)};n.dispatchEvent(new Event('input',{bubbles:true}));n.dispatchEvent(new Event('change',{bubbles:true}));})()`);};
 const idle=()=>wait("document.querySelector('#overview-task')?.textContent==='当前窗口空闲'");
 const navigateClick=async selector=>{await evaluate("window.__uiNavMarker=document.querySelector('#content').firstElementChild");await click(selector);await wait("document.querySelector('#content').firstElementChild!==window.__uiNavMarker&&document.querySelector('#overview-task')?.textContent==='当前窗口空闲'");};
 const nav=async view=>{await idle();if(!await evaluate(`Boolean(document.querySelector('[data-view="${view}"]'))`))await navigateClick('#tabs [data-view="modules"]');await navigateClick(`[data-view="${view}"]`);await idle();};
 ui={send,evaluate,wait,click,fill,idle,nav};await send('Runtime.enable');await send('Network.enable');await send('Page.enable');await send('Fetch.enable',{patterns:[{urlPattern:'*',requestStage:'Request'}]});
 await send('Page.navigate',{url:fixture.url+'/'});await wait("document.querySelector('#overview-task')?.textContent==='当前窗口空闲'");await idle();await evaluate(`sessionStorage.setItem('novel-project',${q(fixture.project_id)});location.reload()`);await idle();await wait("document.querySelector('[data-project].active')");
}

const pages=[
 {name:'rules',view:'rules',selector:'#rule-reviews',prepare:async()=>{await ui.wait("document.querySelector('[data-review-preview]')");await ui.click('[data-review-preview]');await ui.wait("document.querySelector('[data-review-source]').textContent.length>2");}},
 {name:'body-planning',view:'outline',selector:'[data-body-planning]',prepare:async()=>{await ui.evaluate("document.querySelector('[data-body-planning]').open=true");await ui.click('[data-model-source]');await ui.wait("document.querySelector('[data-model-source-preview]').textContent.length>2");}},
 {name:'deep-review',view:'model-prepare',selector:'#deep-review-preparation'},
 {name:'arena',view:'comparisons',selector:'#comparison-create'},
 {name:'workflow',view:'workflows',selector:'#workflow-panel',prepare:async()=>{await ui.evaluate("for(const d of document.querySelectorAll('#workflow-panel details'))d.open=true");if(await ui.evaluate("Boolean(document.querySelector('#workflow-use-chapter-chain'))"))await ui.click('#workflow-use-chapter-chain');}},
 {name:'graph',view:'knowledge',selector:'#knowledge-panel'},
 {name:'author-lock',view:'writing',selector:'#author-scope'}
];

async function matrix(){
 for(const [width,height]of [[1440,900],[1280,720],[1024,768],[390,844]]){
  await ui.send('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});
  for(const page of pages){await check(`geometry ${page.name} ${width}x${height}`,async()=>{
   await ui.nav(page.view);await ui.wait(`document.querySelector(${q(page.selector)})`);if(page.prepare)await page.prepare();
   await ui.evaluate(`(()=>{const n=document.querySelector(${q(page.selector)});n.scrollIntoView({block:'start'});document.querySelector('#content').scrollLeft=0;})()`);await sleep(50);
   const row={page:page.name,width,height,selector:page.selector,top:await screenshot(`${page.name}-${width}x${height}-top`)};
   row.geometry=await ui.evaluate(`(async()=>{
    const root=document.querySelector(${q(page.selector)}),content=document.querySelector('#content'),box=n=>{const r=n.getBoundingClientRect();return {left:r.left,top:r.top,right:r.right,bottom:r.bottom,width:r.width,height:r.height};};
    const controls=[...root.querySelectorAll('button,input:not([type=hidden]),select,textarea,summary,[tabindex="0"]')].filter(n=>{if(!n.getClientRects().length||getComputedStyle(n).visibility==='hidden')return false;for(let p=n.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS'&&!p.open&&!p.querySelector(':scope>summary')?.contains(n))return false;return true;});
    const initial={pageWidth:document.documentElement.scrollWidth,viewportWidth:innerWidth,contentWidth:content.clientWidth,contentScrollWidth:content.scrollWidth,root:box(root),content:box(content)};const measured=[];
    for(const n of controls){n.scrollIntoView({block:'center',inline:'nearest'});await new Promise(requestAnimationFrame);const r=box(n),c=box(content);const x=Math.max(c.left+2,Math.min(c.right-2,r.left+r.width/2)),y=Math.max(c.top+2,Math.min(c.bottom-2,r.top+r.height/2));const hit=document.elementFromPoint(x,y);measured.push({tag:n.tagName,id:n.id,name:n.name,label:(n.innerText||n.getAttribute('aria-label')||n.labels?.[0]?.innerText||'').slice(0,100),rect:r,content:c,hit:hit?.id||hit?.tagName,horizontalClipped:r.left<c.left-2||r.right>c.right+2,verticalClipped:r.height<c.height&&(r.top<c.top-2||r.bottom>c.bottom+2),covered:!n.disabled&&r.top>=c.top&&r.bottom<=c.bottom&&!(hit===n||n.contains(hit)||hit?.contains(n))});}
    return {...initial,controls:measured};})()`);
   row.bottom=await screenshot(`${page.name}-${width}x${height}-bottom`);report.matrix.push(row);
   fs.writeFileSync(path.join(out,`${page.name}-${width}x${height}-geometry.json`),JSON.stringify(row,null,2));
   const g=row.geometry,bad=g.controls.filter(c=>c.horizontalClipped||c.verticalClipped||c.covered);row.issues=bad;
   assert(g.pageWidth<=width+2&&g.contentScrollWidth<=g.contentWidth+2&&bad.length===0,JSON.stringify({page:page.name,width,height,pageWidth:g.pageWidth,contentWidth:g.contentWidth,contentScrollWidth:g.contentScrollWidth,issues:bad}));
   return {controls:g.controls.length,screenshots:[row.top.file,row.bottom.file]};
  });}
 }
}

async function keyboard(){
 await ui.send('Emulation.setDeviceMetricsOverride',{width:1280,height:720,deviceScaleFactor:1,mobile:false});await ui.nav('writing');
 const state=()=>ui.evaluate(`fetch('/api/projects/${fixture.project_id}').then(r=>r.json())`);
 await check('Ctrl+S saves exact Unicode body; synthetic composition blocks Ctrl+S',async()=>{
  const before=(await state()).revision,text=fixture.body+'合成组合输入保留。\n';await ui.fill('#edit-content',text);await ui.evaluate("document.querySelector('#edit-content').focus();document.querySelector('#edit-content').dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true,data:'组合'}))");await key('s','KeyS',2);await sleep(200);assert((await state()).revision===before,'save occurred during synthetic composition');
  await ui.evaluate("document.querySelector('#edit-content').dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:'组合'}))");await key('s','KeyS',2);await ui.idle();await ui.wait("document.querySelector('#save-state').textContent.includes('已保存')");assert((await state()).document.chapters[0].content===text,'Ctrl+S exact content');return {before,after:(await state()).revision};
 });
 await check('unsaved manuscript survives page navigation without formal save',async()=>{const text=(await state()).document.chapters[0].content+'未保存的往返输入。';await ui.fill('#edit-content',text);const revision=(await state()).revision;await ui.nav('outline');await ui.nav('writing');assert(await ui.evaluate("document.querySelector('#edit-content').value")===text,'unsaved input lost');assert((await state()).revision===revision,'navigation saved manuscript');await key('s','KeyS',2);await ui.idle();});
 await check('author range lock requires explicit confirmation; rejected save preserves draft and saved body',async()=>{
  await ui.evaluate("window.__confirms=[];window.confirm=message=>{window.__confirms.push(message);return true;};const n=document.querySelector('#edit-content');n.focus();n.setSelectionRange(2,9)");await ui.click('#lock-body-selection');await ui.idle();await ui.wait("document.querySelector('[data-unlock-range]')");
  const saved=(await state()).document.chapters[0].content,revision=(await state()).revision,attempt=saved.replace('林默','改写');await ui.fill('#edit-content',attempt);await key('s','KeyS',2);await ui.idle();await ui.wait("!document.querySelector('#notification').hidden");assert(await ui.evaluate("document.querySelector('#edit-content').value")===attempt,'failed input lost');assert((await state()).revision===revision,'rejected save mutated revision');assert((await state()).document.chapters[0].content===saved,'locked saved body changed');report.lockFailureScreenshot=await screenshot('keyboard-lock-rejected-input');
  await ui.fill('#edit-content',saved);await ui.click('[data-unlock-range]');await ui.idle();assert((await ui.evaluate('window.__confirms')).length>=2,'lock/unlock confirmation missing');
 });
 await check('deep-review failure preserves input; draft survives navigation',async()=>{await ui.nav('model-prepare');const selector='#deep-review-prepare-form [name=instruction]',text='虚构失败输入：只核对明确来源与双侧 Unicode。';await ui.fill(selector,text);await ui.click('#deep-review-prepare-form [type=submit]');await ui.wait("document.querySelector('#deep-review-prepare-status').textContent.includes('输入保留')");assert(await ui.evaluate(`document.querySelector(${q(selector)}).value`)===text,'failed review input lost');await ui.nav('writing');await ui.nav('model-prepare');assert(await ui.evaluate(`document.querySelector(${q(selector)}).value`)===text,'review draft lost on navigation');});
 await check('arena unsaved rubric survives navigation',async()=>{await ui.nav('comparisons');const selector='#comparison-create [name=rubric]',text='虚构评价：因果与人物动机；不授予模型许可。';await ui.fill(selector,text);await ui.nav('writing');await ui.nav('comparisons');assert(await ui.evaluate(`document.querySelector(${q(selector)}).value`)===text,'arena draft lost');});
 await check('model-planning unsaved instruction survives navigation',async()=>{await ui.nav('outline');await ui.evaluate("document.querySelector('[data-body-planning]').open=true");const selector='[data-model-planning-form] [name=instruction]',text='虚构正文规划草稿：只建议，不自动采纳。';await ui.fill(selector,text);await ui.nav('writing');await ui.nav('outline');await ui.evaluate("document.querySelector('[data-body-planning]').open=true");assert(await ui.evaluate(`document.querySelector(${q(selector)}).value`)===text,'model-planning draft lost');});
 await check('rule-review failed freeze preserves budget; unsaved budget survives navigation',async()=>{await ui.nav('rules');await ui.wait("document.querySelector('[data-review-risk]')");await ui.fill('[data-review-risk]','2.75');await ui.click('[data-review-preview]');await ui.wait("!document.querySelector('[data-review-prepare]').disabled");await ui.click('[data-review-prepare]');await ui.wait("document.querySelector('[data-review-notice]').textContent.length>0");assert(await ui.evaluate("document.querySelector('[data-review-risk]').value")==='2.75','failed rule freeze lost budget');await ui.nav('writing');await ui.nav('rules');await ui.wait("document.querySelector('[data-review-risk]')");assert(await ui.evaluate("document.querySelector('[data-review-risk]').value")==='2.75','rule-review unsaved budget reset');assert(await ui.evaluate("document.querySelector('[data-review-cost]').checked")===false,'unknown-cost confirmation inherited');});
 await ui.nav('writing');
 await check('Ctrl+K opens commands; Tab/Shift+Tab and ArrowDown navigate; Escape closes',async()=>{await key('k','KeyK',2);await ui.wait("document.querySelector('#command-dialog').open");assert(await ui.evaluate("document.activeElement.id")==='command-search','command focus');await key('Tab','Tab');assert(await ui.evaluate("document.activeElement.closest('#command-dialog')!==null"),'Tab escaped dialog');await key('Tab','Tab',8);await ui.evaluate("document.querySelector('#command-search').focus()");await key('ArrowDown','ArrowDown');assert(await ui.evaluate("document.activeElement.closest('#command-list')!==null"),'ArrowDown navigation');await key('Escape','Escape');await ui.wait("!document.querySelector('#command-dialog').open");});
 await check('synthetic IME Enter cannot execute a command',async()=>{await key('k','KeyK',2);await ui.wait("document.querySelector('#command-dialog').open");await ui.fill('#command-search','切换明暗主题');const before=await ui.evaluate('document.documentElement.dataset.theme');await ui.evaluate("(()=>{const n=document.querySelector('#command-search');n.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true,data:'主题'}));n.dispatchEvent(new KeyboardEvent('keydown',{bubbles:true,cancelable:true,key:'Enter',code:'Enter',isComposing:true,keyCode:229}));n.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:'主题'}));})()");const result={before,after:await ui.evaluate('document.documentElement.dataset.theme'),dialogOpen:await ui.evaluate("document.querySelector('#command-dialog').open")};report.commandIme=result;report.commandImeScreenshot=await screenshot('keyboard-command-ime');assert(result.after===before&&result.dialogOpen,'synthetic composing Enter executed a command: '+JSON.stringify(result));await key('Enter','Enter');await ui.wait("!document.querySelector('#command-dialog').open");assert(await ui.evaluate('document.documentElement.dataset.theme')!==before,'normal command Enter did not execute');});
 if(await ui.evaluate("document.querySelector('#command-dialog').open"))await key('Escape','Escape');
}

(async()=>{try{await launch();await matrix();await keyboard();const calls=await command('status');report.provider=calls;assert(calls.provider_calls===0,'unexpected fictional provider call');assert(report.external.length===0&&report.errors.length===0,'external request or renderer error');report.status=report.failures.length?'failed':'passed';}catch(error){report.status='failed';report.fatal=String(error.stack||error);if(ui)try{report.fatalScreenshot=await screenshot('fatal');report.body=await ui.evaluate('document.body.innerText.slice(-7000)');}catch{}}
 finally{if(ui)try{await ui.send('Browser.close');}catch{}if(ws)ws.close();if(browser&&browser.exitCode===null){await sleep(700);if(browser.exitCode===null){try{cp.execFileSync('taskkill.exe',['/PID',String(browser.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});report.browserForcedTreeCleanup=true;}catch(e){report.browserCleanupError=String(e);}}}if(backend&&backend.exitCode===null){backend.stdin.write('stop\n');await Promise.race([new Promise(r=>backend.once('exit',r)),sleep(3000)]);if(backend.exitCode===null)backend.kill();}await sleep(150);for(const item of report.processes){const child=item.role==='fixture'?backend:browser;item.exitCode=child?.exitCode;item.signalCode=child?.signalCode;item.alive=child?.exitCode===null&&child?.signalCode===null;}report.backendErrors=backendError;report.browserErrors=browserError;report.finished_at=new Date().toISOString();report.duration_seconds=(Date.parse(report.finished_at)-Date.parse(report.started_at))/1000;report.exit_code=report.status==='passed'?0:1;fs.writeFileSync(path.join(out,'backend.log'),backendError);fs.writeFileSync(path.join(out,'browser.log'),browserError);fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));process.stdout.write(JSON.stringify({status:report.status,checks:report.checks.length,failures:report.failures.map(v=>v.name),fatal:report.fatal,seconds:report.duration_seconds,out,processes:report.processes})+'\n');process.exitCode=report.exit_code;}
})();
