const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),net=require('node:net');
const {spawn}=require('node:child_process');const {_electron}=require(process.env.NOVEL_WRITER_PLAYWRIGHT||'playwright');
const root=path.resolve(__dirname,'..'),out=process.env.NOVEL_WRITER_ARTIFACTS||fs.mkdtempSync(path.join(os.tmpdir(),'novel-s7-life-'));
const profile=fs.mkdtempSync(path.join(os.tmpdir(),'novel-s7-lifecycle-'));
const executablePath=process.env.NOVEL_WRITER_DESKTOP_EXE||path.join(root,'desktop/node_modules/electron/dist/electron.exe');
const argsFor=directory=>[...(process.env.NOVEL_WRITER_DESKTOP_EXE?[]:[path.join(root,'desktop')]),'--profile-dir='+directory,'--background-test'];
const env={...process.env,PATH:'C:/Windows/System32;C:/Windows'};delete env.ELECTRON_RUN_AS_NODE;
const report={checks:[],profile};let application,blocker;
const record=message=>{report.checks.push(message);process.stdout.write(JSON.stringify({check:message})+'\n');};
const bounded=(operation,label)=>Promise.race([operation,new Promise((_,reject)=>{const timer=setTimeout(()=>reject(Error('timeout: '+label)),12000);timer.unref();})]);
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const state=app=>app.evaluate(({app})=>process.getBuiltinModule('module').createRequire(app.getAppPath()+'/package.json')(app.getAppPath()+'/main.cjs').status());
async function launch(){const app=await _electron.launch({executablePath,args:argsFor(profile),env,timeout:25000});const page=await app.firstWindow();page.on('dialog',d=>{if(d.type()!=='beforeunload')void d.dismiss().catch(()=>{});});await page.waitForFunction(()=>document.readyState==='complete'&&document.querySelector('#tabs button')&&!document.querySelector('#new-project').disabled&&document.querySelector('#content').textContent.trim()!=='正在打开工作台…'&&!document.querySelector('#save-state').textContent.includes('正在处理'));return {app,page};}
async function childRun(args){
  const child=spawn(executablePath,args,{env,windowsHide:true,stdio:['ignore','pipe','pipe']});let diagnostic='';child.stdout.resume();child.stderr.on('data',chunk=>{diagnostic=(diagnostic+chunk).slice(-1500);});
  return await new Promise((resolve,reject)=>{const timer=setTimeout(()=>{child.kill();reject(Error('owned app startup did not finish'));},15000);child.once('error',reject);child.once('exit',code=>{clearTimeout(timer);resolve({code,diagnostic});});});
}
(async()=>{
  blocker=net.createServer();await new Promise(resolve=>blocker.listen(0,'127.0.0.1',resolve));const occupied=blocker.address().port;
  let opened=await launch();application=opened.app;let page=opened.page;const before=await state(application);report.backendPid=before.backendPid;
  assert.notEqual(before.port,occupied);const second=await childRun(argsFor(profile));assert.equal(second.code,0);assert.equal((await state(application)).backendPid,before.backendPid);
  record('occupied random port is untouched; second instance with the same profile exits without another backend');
  const info=await page.evaluate(()=>window.novelDesktop.info());assert.equal(info.uiLanguage,'zh-CN');
  assert.equal(await page.evaluate(()=>{try{window.novelDesktop.info('unexpected');return false;}catch{return true;}}),true);
  assert.equal(await page.evaluate(()=>{try{window.novelDesktop.setLanguage('../../outside');return false;}catch{return true;}}),true);
  await page.evaluate(()=>{const link=document.createElement('a');link.href='https://example.com/';document.body.append(link);link.click();link.remove();});await delay(100);assert.equal(page.url(),'novel://app/');
  record('restricted preload rejects invalid parameters and navigation stays at the packaged origin');
  assert.equal(await page.evaluate(()=>typeof window.novelDesktop.setLanguage),'undefined');record('Chinese-only UI exposes no language IPC');
  await bounded(page.evaluate(async()=>{
    const response=await fetch('/api/projects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:'S7 crash recovery fiction'})});if(!response.ok)throw Error(await response.text());
  }),'create fiction');record('fiction saved');
  await bounded(page.evaluate(()=>fetch('/api/desktop/mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:'models',confirmed:true})}).then(response=>response.status)),'enable models');record('session enabled');
  const identity=await application.evaluate(({app})=>({pid:process.pid,executable:process.execPath,profile:app.getPath('userData')}));
  assert.equal(path.resolve(identity.executable),path.resolve(executablePath));assert.equal(path.resolve(identity.profile),path.resolve(profile));
  report.mainPid=identity.pid;report.launcherPid=application.process().pid;
  process.stdout.write(JSON.stringify({main:identity.pid,launcher:report.launcherPid})+'\n');
  process.kill(identity.pid,'SIGKILL');application=null;
  let alive=true;for(let count=0;count<80;count++){try{process.kill(before.backendPid,0);await delay(100);}catch{alive=false;break;}}assert.equal(alive,false,'main crash left its Python process');
  record('forced termination of the owned main process closes stdin and reaps the backend without scanning or killing unrelated PIDs');
  opened=await launch();application=opened.app;page=opened.page;
  const reopened=await page.evaluate(async()=>({info:await window.novelDesktop.info(),projects:await(await fetch('/api/projects')).json(),caps:await(await fetch('/api/tasks/capabilities')).json()}));
  assert.equal(reopened.info.uiLanguage,'zh-CN');assert.equal(reopened.projects[0].title,'S7 crash recovery fiction');assert.equal(reopened.caps.real_model_enabled,false);
  record('restart preserves saved fiction in the Chinese UI while model access resets to manual');
  record('reopened UI completed initial rendering');await bounded(application.close(),'normal close after restart');application=null;record('reopened application closed');
  const broken=fs.mkdtempSync(path.join(os.tmpdir(),'novel-s7-broken-'));fs.writeFileSync(path.join(broken,'library'),'fictional blocked directory');
  const failed=await childRun(argsFor(broken));assert.equal(failed.code,1);assert.ok(failed.diagnostic.includes('DESKTOP_START_FAILED'));
  record('blocked fictional data directory causes safe hidden startup failure and nonzero exit');report.status='passed';
})().catch(error=>{report.status='failed';report.error=String(error.stack||error);process.exitCode=1;}).finally(async()=>{
  if(application){await application.evaluate(({BrowserWindow})=>{for(const window of BrowserWindow.getAllWindows())window.destroy();}).catch(()=>{});await application.close().catch(()=>{});}if(blocker)await new Promise(resolve=>blocker.close(resolve));
  fs.mkdirSync(out,{recursive:true});fs.writeFileSync(path.join(out,'s7-lifecycle-report.json'),JSON.stringify(report,null,2));process.stdout.write(JSON.stringify(report)+'\n');
});
