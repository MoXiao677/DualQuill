const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),cp=require('node:child_process');
const {_electron}=require(process.env.NOVEL_WRITER_PLAYWRIGHT||'playwright');const {sourceFiles}=require('../desktop/build.cjs');
const root=path.resolve(__dirname,'..'),out=process.env.NOVEL_WRITER_ARTIFACTS||fs.mkdtempSync(path.join(os.tmpdir(),'novel-c16-evidence-')),profile=fs.mkdtempSync(path.join(os.tmpdir(),'novel-c16-profile-')),shell=fs.mkdtempSync(path.join(root,'desktop/.cache/c16-drafts-shell-'));
let app,backendPid;const report={checks:[],errors:[],external:[],profile,shell};let projectId,chapterId;
const step=name=>console.log('STEP '+name);
function stage(){
 for(const name of ['main.cjs','backend.cjs','security.cjs','preload.cjs','localization.cjs','package.json'])fs.copyFileSync(path.join(root,'desktop',name),path.join(shell,name));
 const runtime=path.join(shell,'.cache/stage/runtime'),archive=path.join(root,'desktop/.cache/python-3.14.8-embed-amd64.zip');fs.mkdirSync(runtime,{recursive:true});
 cp.execFileSync('powershell.exe',['-NoProfile','-NonInteractive','-Command',"Expand-Archive -LiteralPath '"+archive.replaceAll("'","''")+"' -DestinationPath '"+runtime.replaceAll("'","''")+"' -Force"],{windowsHide:true});
 fs.writeFileSync(path.join(runtime,'python314._pth'),'python314.zip\n.\n../backend/src\n');
 for(const name of sourceFiles(root)){const target=path.join(shell,'.cache/stage/backend',name);fs.mkdirSync(path.dirname(target),{recursive:true});fs.copyFileSync(path.join(root,name),target);}
}
async function idle(page){await page.waitForFunction(()=>!document.querySelector('#new-project').disabled);}
async function nav(page,id){await idle(page);const b=page.locator('#tabs [data-view="'+id+'"]');if(!await b.isVisible())await page.locator('#toggle-modules').click();await b.click();await idle(page);}
async function open(){app=await _electron.launch({executablePath:path.join(root,'desktop/node_modules/electron/dist/electron.exe'),args:[shell,'--profile-dir='+profile,'--background-test'],env:{...process.env,PATH:'C:/Windows/System32;C:/Windows'},timeout:30000});const page=await app.firstWindow();page.setDefaultTimeout(15000);page.on('pageerror',e=>report.errors.push(e.message));page.on('request',r=>{if(!r.url().startsWith('novel://app/'))report.external.push(r.url());});page.on('dialog',d=>{if(d.type()==='beforeunload')void d.dismiss().catch(()=>{});else void d.accept().catch(()=>{});});await page.waitForFunction(()=>document.querySelector('#tabs button')&&!document.querySelector('#new-project').disabled);backendPid=await app.evaluate(({app})=>process.getBuiltinModule('module').createRequire(app.getAppPath()+'/package.json')(app.getAppPath()+'/main.cjs').status().backendPid);return page;}
async function crash(){
 const proc=app.process(),exited=new Promise(resolve=>proc.once('exit',resolve));
 try{cp.execFileSync('taskkill.exe',['/PID',String(proc.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});}catch{}
 await Promise.race([exited,new Promise(resolve=>setTimeout(resolve,5000))]);
 if(backendPid){try{process.kill(backendPid,'SIGKILL');}catch{}}
 const deadline=Date.now()+8000;while(Date.now()<deadline&&backendPid){try{process.kill(backendPid,0);await new Promise(r=>setTimeout(r,80));}catch{backendPid=null;}}
 app=null;assert.equal(backendPid,null,'backend survived simulated whole-application crash');
}
async function close(){if(!app)return;try{await app.evaluate(({BrowserWindow})=>{for(const w of BrowserWindow.getAllWindows())w.destroy();});await app.close();}catch{}app=null;if(backendPid){const deadline=Date.now()+5000;while(Date.now()<deadline){try{process.kill(backendPid,0);await new Promise(r=>setTimeout(r,80));}catch{backendPid=null;break;}}}assert.equal(backendPid,null);}
async function fetchState(page){return page.evaluate(async()=>await(await fetch('/api/projects/'+document.querySelector('#create-form')?.dataset.project||'')).json()).catch(()=>null);}
async function state(page){return page.evaluate(async()=>{const books=await(await fetch('/api/projects')).json();return await(await fetch('/api/projects/'+books[0].id)).json();});}
async function drafts(page){return page.evaluate(async()=>{const books=await(await fetch('/api/projects')).json();return await(await fetch('/api/projects/'+books[0].id+'/drafts')).json();});}
async function action(page,name,fields){return page.evaluate(async arg=>{const books=await(await fetch('/api/projects')).json(),current=await(await fetch('/api/projects/'+books[0].id)).json();const response=await fetch('/api/projects/'+books[0].id+'/actions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:arg.name,fields:arg.fields,expected_revision:current.revision})});if(!response.ok)throw Error(await response.text());return response.json();},{name,fields});}
async function writing(page){await nav(page,'writing');if(await page.locator('[data-pane="body"]').count())await page.locator('[data-pane="body"]').click();await idle(page);await page.locator('#edit-content').waitFor();}
(async()=>{
 stage();
 step('create-project');
 let page=await open();if(!await page.locator('#new-project').isVisible())await page.locator('#toggle-left').click();await page.locator('#new-project').click();await page.getByLabel('小说名称',{exact:true}).fill('C16 磁盘草稿');await page.locator('#create-form button[type="submit"]').click();await idle(page);
 step('create-chapter');
 await action(page,'add_chapter',{title:'第一章'});await page.reload();await idle(page);await writing(page);
 const initial=await state(page);projectId=initial.document.project.id;chapterId=initial.document.chapters[0].id;await action(page,'save_chapter',{chapter_id:chapterId,content:'已保存原正文。'});await page.reload();await idle(page);await writing(page);
 step('type-draft');
 const crashDraft='已保存原正文。未保存的崩溃草稿😀';await page.locator('#edit-content').fill(crashDraft);await page.waitForTimeout(1300);
 let listed=await drafts(page);assert.equal(listed.drafts.length,1);assert.equal(listed.drafts[0].values.content,crashDraft);assert.equal((await state(page)).document.chapters[0].content,'已保存原正文。');report.checks.push('800ms debounce writes the unsaved body draft without touching the saved manuscript');
 step('crash');
 await crash();page=await open();await writing(page);await page.locator('#draft-review').waitFor();const restored=await page.locator('#edit-content').inputValue();assert.equal(restored,crashDraft);assert.ok((await page.locator('#draft-review').innerText()).includes('本地恢复草稿'));assert.equal((await state(page)).document.chapters[0].content,'已保存原正文。');report.checks.push('real Electron process crash and reopen restores the disk draft with an explicit local-recovery banner; database body is unchanged');
 fs.mkdirSync(out,{recursive:true});await page.screenshot({path:path.join(out,'disk-drafts-recovered.png')});
 step('save-draft');
 await page.locator('#edit-content').fill(crashDraft+' 已保存。');await page.keyboard.press('Control+s');await page.waitForFunction(()=>document.querySelector('#save-state')?.textContent?.startsWith('已保存'));listed=await drafts(page);assert.equal(listed.drafts.length,0);assert.equal((await state(page)).document.chapters[0].content,crashDraft+' 已保存。');report.checks.push('successful save clears the matching disk draft');
 step('stale');
 await page.locator('#edit-content').fill('过期草稿内容。');await page.waitForTimeout(1300);const current=await state(page);await action(page,'save_chapter',{chapter_id:chapterId,content:'数据库新正文。'});assert.notEqual((await state(page)).revision,current.revision);
 await close();page=await open();await writing(page);await page.locator('#draft-review').waitFor();const stale=(await page.locator('#draft-review').innerText());assert.ok(stale.includes('草稿基于保存编号'));assert.ok(stale.includes('最新为'));assert.equal(await page.locator('#edit-content').inputValue(),'过期草稿内容。');assert.equal((await state(page)).document.chapters[0].content,'数据库新正文。');report.checks.push('stale draft is shown for explicit comparison and never overwrites the newer saved body');
 step('discard');
 await page.locator('#discard-draft').click();await idle(page);assert.equal(await page.locator('#edit-content').inputValue(),'数据库新正文。');assert.equal((await drafts(page)).drafts.length,0);await close();page=await open();await writing(page);assert.equal(await page.locator('#draft-review').isVisible(),false);assert.equal(await page.locator('#edit-content').inputValue(),'数据库新正文。');report.checks.push('explicit discard clears only that draft and survives another reopen');
 fs.mkdirSync(out,{recursive:true});await page.screenshot({path:path.join(out,'disk-drafts.png')});assert.deepEqual(report.errors,[]);assert.deepEqual(report.external,[]);report.status='passed';
})().catch(error=>{report.status='failed';report.error=String(error.stack||error);process.exitCode=1;}).finally(async()=>{await close().catch(()=>{});fs.mkdirSync(out,{recursive:true});fs.writeFileSync(path.join(out,'disk-drafts-ui.json'),JSON.stringify(report,null,2));process.stdout.write(JSON.stringify(report)+'\n');});
