'use strict';
// External-observer benchmark. Never calls stage() or changes the fixed package.
const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net');
const crypto=require('node:crypto'),assert=require('node:assert/strict');
const TASK=path.resolve(__dirname,'../..'),E=path.join(TASK,'evidence'),T=path.join(TASK,'temporary');
const preflight=JSON.parse(fs.readFileSync(path.join(E,'preflight.json'),'utf8'));
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const hash=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
async function port(){let s=net.createServer();await new Promise(r=>s.listen(0,'127.0.0.1',r));let n=s.address().port;await new Promise(r=>s.close(r));assert.notEqual(n,8765);return n;}
async function json(url){const r=await fetch(url,{signal:AbortSignal.timeout(800)});return r.json();}
async function connect(url,onEvent=()=>{}){
 const ws=new WebSocket(url);await new Promise((r,j)=>{ws.addEventListener('open',r,{once:true});ws.addEventListener('error',j,{once:true});});
 let id=0;const pending=new Map();
 ws.addEventListener('message',ev=>{const m=JSON.parse(ev.data);if(m.id){const p=pending.get(m.id);if(p){pending.delete(m.id);clearTimeout(p.timer);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result);}}else onEvent(m);});
 ws.addEventListener('close',()=>{for(const p of pending.values()){clearTimeout(p.timer);p.reject(Error('CDP socket closed'));}pending.clear();});
 const send=(method,params={})=>new Promise((resolve,reject)=>{let i=++id;let timer=setTimeout(()=>{pending.delete(i);reject(Error('CDP timeout '+method));},120000);pending.set(i,{resolve,reject,timer});ws.send(JSON.stringify({id:i,method,params}));});
 const evaluate=async expression=>{let r=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value;};
 return {send,evaluate,close:()=>ws.close()};
}
async function one(fixture,index,runRoot){
 const group=Math.floor(index/2),opening=index%2?'same-profile-reopen':'new-profile-first-open';
 const profile=path.join(runRoot,fixture.mode,'profile-'+group),database=path.join(runRoot,fixture.mode,'fiction.sqlite3');
 fs.mkdirSync(profile,{recursive:true});
 if(!fs.existsSync(database))fs.copyFileSync(fixture.copied_database,database);
 assert.equal(hash(database),fixture.database_sha256);
 const debug=await port(),inspector=await port(),sampleDir=path.join(runRoot,fixture.mode,'sample-'+String(index+1).padStart(2,'0'));
 fs.mkdirSync(sampleDir,{recursive:true});
 const env={SYSTEMROOT:process.env.SYSTEMROOT||'C:/Windows',WINDIR:'C:/Windows',COMSPEC:'C:/Windows/System32/cmd.exe',PATH:'C:/Windows/System32;C:/Windows',PYTHONDONTWRITEBYTECODE:'1',TEMP:path.join(profile,'tmp'),TMP:path.join(profile,'tmp'),USERPROFILE:profile,APPDATA:path.join(profile,'environment/Roaming'),LOCALAPPDATA:path.join(profile,'environment/Local')};
 for(const n of ['TEMP','APPDATA','LOCALAPPDATA'])fs.mkdirSync(env[n],{recursive:true});
 const record={fixture:fixture.mode,index:index+1,opening,profile,database,database_sha256_before:hash(database),exe:preflight.exe,exe_sha256:preflight.exe_sha256,cache_policy:'Fresh application processes; pair shares profile. OS/file caches deliberately not purged, fixture SHA read before spawn; no cold-OS claim.',lock_mode:'author-scope V48 unlocked fixture',sample_dir:sampleDir,errors:[],external:[],events:[],requests:[],real_provider_calls:0};
 const start=performance.now();record.spawn_wall_time=new Date().toISOString();
 const progress=phase=>{record.phase=phase;fs.writeFileSync(path.join(sampleDir,'progress.json'),JSON.stringify(record,null,2));console.log(JSON.stringify({phase,fixture:fixture.mode,index:index+1,at:(performance.now()-start)/1000}));};
 const at=()=>Number(((performance.now()-start)/1000).toFixed(6));
 let main,renderer,monitor,stopPoll=false,readyTask;let stderr='';
 const child=cp.spawn(preflight.exe,['--inspect=127.0.0.1:'+inspector,'--remote-debugging-address=127.0.0.1','--remote-debugging-port='+debug,'--background-test','--profile-dir='+profile,'--database='+database],{cwd:path.dirname(preflight.exe),env,windowsHide:true,stdio:['ignore','pipe','pipe']});
 record.pid=child.pid;record.spawn_return_seconds=at();child.stderr.on('data',b=>{stderr+=b;fs.appendFileSync(path.join(sampleDir,'stderr-live.log'),b);});child.stdout.on('data',()=>{});progress('spawned');
 const memoryFile=path.join(sampleDir,'memory.json');
 monitor=cp.spawn(preflight.python,[path.join(E,'memory_monitor.py'),String(child.pid),memoryFile],{cwd:T,env:{...env,PATH:process.env.PATH},windowsHide:true,stdio:['ignore','pipe','pipe']});
 let monitorError='';monitor.stderr.on('data',b=>monitorError+=b);
 try{
  readyTask=(async()=>{
   let target;const end=Date.now()+20000;
   while(!target&&Date.now()<end){try{target=(await json('http://127.0.0.1:'+inspector+'/json/list'))[0];}catch{}if(!target)await sleep(10);}
   assert(target,'main inspector unavailable');main=await connect(target.webSocketDebuggerUrl);record.inspector_attached_seconds=at();progress('inspector-attached');
   const expression="(()=>{const cache=process.getBuiltinModule('module')._cache;const m=Object.values(cache).find(m=>/[\\\\/]main\\.cjs$/.test(m.filename));return m?.exports?.status?.()||null;})()";
   let lastNotReady=null,polls=0;
   while(!stopPoll&&Date.now()<end){let before=at(),status=await main.evaluate(expression),after=at();polls++;if(status?.port){assert.notEqual(status.port,8765);record.backend_ready={last_not_ready_seconds:lastNotReady,observation_start_seconds:before,first_ready_seconds:after,polls,backend_pid:status.backendPid,port:status.port,packaged:status.packaged,hidden:status.hidden};progress('backend-ready');break;}lastNotReady=after;await sleep(10);}
  })().catch(e=>{record.inspector_failure=e.stack;});
  // Attach renderer as soon as its target exists, without harness.open()'s idle wait.
  let target;const end=Date.now()+90000;
  while(!target&&Date.now()<end){try{target=(await json('http://127.0.0.1:'+debug+'/json/list')).find(t=>t.type==='page'&&t.url.startsWith('novel://app/'));}catch{}if(!target)await sleep(10);}
  assert(target,'renderer target unavailable '+stderr.slice(-600));record.renderer_target_seconds=at();progress('renderer-target');
  renderer=await connect(target.webSocketDebuggerUrl,m=>{
   if(m.method==='Runtime.exceptionThrown')record.errors.push(m.params.exceptionDetails.exception?.description||m.params.exceptionDetails.text);
   if(m.method==='Page.domContentEventFired')record.dom_event_observed_seconds=at();
   if(m.method==='Network.requestWillBeSent'){
    const u=new URL(m.params.request.url);if(/^https?:$/.test(u.protocol))record.external.push(u.origin+u.pathname);
    if(u.protocol==='novel:')record.requests.push({id:m.params.requestId,path:u.pathname,method:m.params.request.method,start_seconds:at()});
   }
   if(m.method==='Network.loadingFinished'){let r=record.requests.find(r=>r.id===m.params.requestId);if(r){r.end_seconds=at();r.encoded_bytes=m.params.encodedDataLength;}}
  });
  await renderer.send('Runtime.enable');await renderer.send('Page.enable');await renderer.send('Network.enable');
  const wait=async(expr,timeout=120000)=>{let end=Date.now()+timeout;while(Date.now()<end){let value=await renderer.evaluate(expr);if(value)return value;await sleep(10);}throw Error('UI timeout '+expr+' '+await renderer.evaluate('document.body.innerText.slice(-1500)'));};
  await wait("document.readyState!=='loading'&&performance.getEntriesByType('navigation')[0].domContentLoadedEventEnd>0");
  record.dom=await renderer.evaluate("({time_origin_epoch_ms:performance.timeOrigin,dom_content_loaded_ms:performance.getEntriesByType('navigation')[0].domContentLoadedEventEnd,ready_state:document.readyState})");record.dom_observed_seconds=at();record.dom_since_spawn_seconds=(record.dom.time_origin_epoch_ms+record.dom.dom_content_loaded_ms-Date.parse(record.spawn_wall_time))/1000;
  await wait("document.querySelectorAll('#chapter-tree [data-chapter]').length===500&&!document.querySelector('#new-project').disabled&&document.querySelector('#overview-task')?.textContent==='当前窗口空闲'");
  record.project_loaded_seconds=at();progress('project-loaded');
  record.project_identity=await renderer.evaluate("({id:document.querySelector('#project-list [data-project].active')?.dataset.project,chapters:document.querySelectorAll('#chapter-tree [data-chapter]').length})");assert.equal(record.project_identity.id,fixture.project_id);
  const first=`#chapter-tree [data-chapter="${fixture.first_chapter_id}"]`;
  await renderer.evaluate(`document.querySelector(${JSON.stringify(first)}).click()`);
  const expected=JSON.stringify(fixture.first_chapter_content);
  await wait(`document.querySelector('#edit-content')?.value===${expected}&&!document.querySelector('#edit-content').disabled&&!document.querySelector('#edit-content').readOnly`);
  record.first_body_editable_seconds=at();progress('first-body-editable');
  record.first_body=await renderer.evaluate("({characters:Array.from(document.querySelector('#edit-content').value).length,project:document.querySelector('#project-list [data-project].active')?.dataset.project,chapter:document.querySelector('#chapter-tree [data-chapter].active')?.dataset.chapter})");
  assert.equal(record.first_body.chapter,fixture.first_chapter_id);
  await renderer.evaluate("document.querySelectorAll('#chapter-tree [data-chapter]')[1].click()");
  await wait(`document.querySelector('#edit-content')&&!document.querySelector('#edit-content').disabled&&document.querySelector('#chapter-tree [data-chapter].active')?.dataset.chapter!==${JSON.stringify(fixture.first_chapter_id)}`);
  record.second_chapter_navigated_seconds=at();
  await renderer.evaluate(`document.querySelector(${JSON.stringify(first)}).click()`);
  await wait(`document.querySelector('#edit-content')?.value===${expected}&&!document.querySelector('#edit-content').disabled`);
  record.navigation_roundtrip_seconds=at();
  await renderer.evaluate("(()=>{const e=document.querySelector('#edit-content');e.focus();e.setSelectionRange(e.value.length,e.value.length)})()");
  await renderer.send('Input.insertText',{text:'本地输入验收'});
  await wait(`document.querySelector('#edit-content')?.value===${JSON.stringify(fixture.first_chapter_content+'本地输入验收')}`);
  record.input_accepted_seconds=at();record.interactive_seconds=record.input_accepted_seconds;
  await renderer.send('Input.dispatchKeyEvent',{type:'keyDown',key:'z',code:'KeyZ',windowsVirtualKeyCode:90,modifiers:2});await renderer.send('Input.dispatchKeyEvent',{type:'keyUp',key:'z',code:'KeyZ',windowsVirtualKeyCode:90,modifiers:2});
  await wait(`document.querySelector('#edit-content')?.value===${expected}`);
  record.input_undone_seconds=at();
  assert.deepEqual(record.errors,[]);assert.deepEqual(record.external,[]);
  await readyTask;assert(record.backend_ready,'ready observation missing');
  record.valid=true;record.target_under_5_seconds=record.interactive_seconds<5;
 }catch(error){record.valid=false;record.failure=error.stack;}
 finally{
  stopPoll=true;try{await readyTask;}catch(e){record.inspector_failure=e.stack;record.valid=false;}
  if(main)main.close();
  if(renderer){try{await Promise.race([renderer.send('Browser.close'),sleep(1000)]);}catch{}renderer.close();}
  const until=Date.now()+10000;while(child.exitCode===null&&Date.now()<until)await sleep(50);
  if(child.exitCode===null){record.forced_cleanup=true;try{cp.execFileSync('taskkill.exe',['/PID',String(child.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});}catch{}}
  record.exit_code=child.exitCode;fs.writeFileSync(memoryFile+'.stop','stop');
  const monEnd=Date.now()+4000;while(monitor.exitCode===null&&Date.now()<monEnd)await sleep(50);
  record.memory_monitor_exit_code=monitor.exitCode;
  if(fs.existsSync(memoryFile))record.memory=JSON.parse(fs.readFileSync(memoryFile,'utf8'));else record.memory_error=monitorError;
  if(monitor.exitCode!==0||!record.memory?.valid||record.memory.root_pid!==child.pid){record.valid=false;record.memory_error=monitorError||'Missing or invalid process-identity memory evidence';}
  record.database_sha256_after=hash(database);record.database_unchanged=record.database_sha256_before===record.database_sha256_after;
  if(!record.database_unchanged)record.valid=false;
  record.finished_wall_time=new Date().toISOString();record.total_observer_seconds=at();
  fs.writeFileSync(path.join(sampleDir,'stderr.log'),stderr);fs.writeFileSync(path.join(sampleDir,'sample.json'),JSON.stringify(record,null,2));
 }
 return record;
}
async function run(){
 assert.equal(hash(preflight.exe),preflight.exe_sha256);
 const name=process.argv[2]||'fixed-exe-01',count=Number(process.argv[3]||30),mode=process.argv[4];
 const runRoot=path.join(E,name);fs.mkdirSync(runRoot,{recursive:false});
 fs.copyFileSync(__filename,path.join(runRoot,'observer.cjs'));
 fs.copyFileSync(path.join(E,'memory_monitor.py'),path.join(runRoot,'memory_monitor.py'));
 fs.writeFileSync(path.join(runRoot,'measurement-bindings.json'),JSON.stringify({observer_sha256:hash(__filename),memory_monitor_sha256:hash(path.join(E,'memory_monitor.py')),exe_sha256:hash(preflight.exe)},null,2));
 const records=[];
 for(const fixture of preflight.fixtures.fixtures.filter(f=>!mode||f.mode===mode)){
  for(let index=0;index<count;index++){
   const r=await one(fixture,index,runRoot);records.push(r);fs.appendFileSync(path.join(runRoot,'raw.jsonl'),JSON.stringify(r)+'\n');
   console.log(JSON.stringify({fixture:r.fixture,index:r.index,opening:r.opening,valid:r.valid,ready:r.backend_ready?.first_ready_seconds,loaded:r.project_loaded_seconds,interactive:r.interactive_seconds,target:r.target_under_5_seconds,failure:r.failure,inspector_failure:r.inspector_failure}));
   if(!r.valid)throw Error('invalid measurement retained; fix harness before continuing');
  }
 }
 const summary={exe:preflight.exe,exe_sha256:preflight.exe_sha256,measurements:records.length,valid:records.every(r=>r.valid),target_under_5_seconds:records.every(r=>r.target_under_5_seconds),modes:{}};
 for(const mode of new Set(records.map(r=>r.fixture))){const list=records.filter(r=>r.fixture===mode),times=list.map(r=>r.interactive_seconds).sort((a,b)=>a-b);summary.modes[mode]={count:times.length,min:times[0],median:times[Math.floor(times.length/2)],p95:times[Math.ceil(times.length*.95)-1],max:times.at(-1),under5:list.filter(r=>r.target_under_5_seconds).length};}
 fs.writeFileSync(path.join(runRoot,'summary.json'),JSON.stringify(summary,null,2));console.log(JSON.stringify(summary));
}
if(require.main===module)run().catch(e=>{console.error(e.stack);process.exitCode=1;});
module.exports={one,connect};
