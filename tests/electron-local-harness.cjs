'use strict';
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),cp=require('node:child_process'),net=require('node:net');
const root=path.resolve(__dirname,'..');
async function freePort(){const server=net.createServer();await new Promise(r=>server.listen(0,'127.0.0.1',r));const port=server.address().port;await new Promise(r=>server.close(r));return port;}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
function stage(){
 const shell=fs.mkdtempSync(path.join(os.tmpdir(),'novel-final-shell-'));
 for(const name of ['main.cjs','backend.cjs','security.cjs','preload.cjs','localization.cjs','package.json'])fs.copyFileSync(path.join(root,'desktop',name),path.join(shell,name));
 const runtime=path.join(shell,'.cache/stage/runtime');fs.mkdirSync(runtime,{recursive:true});
 const quote=s=>"'"+s.replaceAll("'","''")+"'";
 cp.execFileSync('powershell.exe',['-NoProfile','-NonInteractive','-Command','Expand-Archive -LiteralPath '+quote(path.join(root,'desktop/.cache/python-3.14.8-embed-amd64.zip'))+' -DestinationPath '+quote(runtime)],{windowsHide:true});
 fs.writeFileSync(path.join(runtime,'python314._pth'),'python314.zip\n.\n../backend/src\n');
 for(const file of require('../desktop/build.cjs').sourceFiles(root)){const to=path.join(shell,'.cache/stage/backend',file);fs.mkdirSync(path.dirname(to),{recursive:true});fs.copyFileSync(path.join(root,file),to);}
 return shell;
}
async function open({shell,profile,executable,database,downloadDirectory,report}){
 const port=await freePort(),exe=executable||path.join(root,'desktop/node_modules/electron/dist/electron.exe');
 const args=['--remote-debugging-port='+port,'--background-test','--profile-dir='+profile,...(database?['--database='+database]:[]),...(downloadDirectory?['--test-download-dir='+downloadDirectory]:[]),...(executable?[]:[shell])];
 const child=cp.spawn(exe,args,{cwd:executable?path.dirname(executable):shell,env:{...process.env,PATH:'C:/Windows/System32;C:/Windows'},windowsHide:true,stdio:['ignore','pipe','pipe']});
 let stderr='';child.stderr.on('data',d=>stderr+=d);child.stdout.on('data',()=>{});
 let target;
 for(let i=0;i<180&&!target;i++){try{target=(await(await fetch('http://127.0.0.1:'+port+'/json/list')).json()).find(t=>t.type==='page'&&t.url.startsWith('novel://app/'));}catch{}if(!target)await sleep(200);}
 if(!target){if(child.exitCode===null)child.kill();throw Error('Electron CDP startup failed '+stderr.slice(-1800));}
 const ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});
 let seq=0;const pending=new Map();
 ws.addEventListener('message',event=>{const m=JSON.parse(event.data);if(m.id&&pending.has(m.id)){const p=pending.get(m.id);pending.delete(m.id);clearTimeout(p.timer);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result);}if(m.method==='Runtime.exceptionThrown')report.errors.push(m.params.exceptionDetails.exception?.description||m.params.exceptionDetails.text);if(m.method==='Network.requestWillBeSent'&&/^https?:/.test(m.params.request.url))report.external.push(m.params.request.url);});
 const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq,timer=setTimeout(()=>{pending.delete(id);reject(Error('CDP timeout '+method));},20000);pending.set(id,{resolve,reject,timer});ws.send(JSON.stringify({id,method,params}));});
 const evaluate=async expression=>{const r=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value;};
 const wait=async(expression,timeout=30000)=>{const end=Date.now()+timeout;while(Date.now()<end){if(await evaluate(expression))return;await sleep(100);}throw Error('UI timeout '+expression+' '+await evaluate('document.body.innerText.slice(-5000)'));};
 const click=async selector=>{await wait(`document.querySelector(${JSON.stringify(selector)})&&!document.querySelector(${JSON.stringify(selector)}).disabled`);await evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);};
 const fill=async(selector,value)=>{await wait(`document.querySelector(${JSON.stringify(selector)})&&!document.querySelector(${JSON.stringify(selector)}).disabled`);return evaluate(`(()=>{const n=document.querySelector(${JSON.stringify(selector)});n.value=${JSON.stringify(value)};n.dispatchEvent(new Event('input',{bubbles:true}));n.dispatchEvent(new Event('change',{bubbles:true}));})()`);};
 const idle=()=>wait("document.querySelector('#new-project')&&!document.querySelector('#new-project').disabled");
 const nav=async view=>{await idle();await click('#tabs [data-view="'+view+'"]');await idle();};
 const state=pid=>evaluate(`fetch('/api/projects/'+${JSON.stringify(pid)}).then(r=>r.json())`);
 const action=(pid,action,fields)=>evaluate(`(async()=>{const s=await(await fetch('/api/projects/'+${JSON.stringify(pid)})).json();const r=await fetch('/api/projects/'+${JSON.stringify(pid)}+'/actions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:${JSON.stringify(action)},fields:${JSON.stringify(fields)},expected_revision:s.revision})});const v=await r.json();if(!r.ok)throw Error(JSON.stringify(v));return v;})()`);
 const close=async()=>{try{await send('Browser.close');}catch{}await sleep(1000);if(child.exitCode===null){try{cp.execFileSync('taskkill.exe',['/PID',String(child.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});}catch{}}ws.close();};
 await send('Runtime.enable');await send('Page.enable');await send('Network.enable');await wait("document.querySelector('#overview-task')?.textContent==='当前窗口空闲'");await idle();
 return {send,evaluate,wait,click,fill,idle,nav,state,action,close,child};
}
module.exports={root,stage,open,sleep};
