const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {stage,open}=require('./electron-local-harness.cjs');
const out=process.env.NOVEL_WRITER_ARTIFACTS||fs.mkdtempSync(path.join(os.tmpdir(),'novel-v27-evidence-'));
const report={status:'running',checks:[],errors:[],external:[],providerCalls:0};
(async()=>{
 fs.mkdirSync(out,{recursive:true});const shell=stage(),profile=fs.mkdtempSync(path.join(os.tmpdir(),'novel-v27-profile-'));report.shell=shell;report.profile=profile;let ui;
 try{
  ui=await open({shell,profile,report});await ui.click('#new-project');await ui.fill('#create-form [name="title"]','V27 作者流程');await ui.click('#create-form button[type="submit"]');await ui.idle();
  const pid=await ui.evaluate("fetch('/api/projects').then(r=>r.json()).then(v=>v[0].id)");report.project=pid;
  await ui.action(pid,'add_chapter',{title:'原章'});let state=await ui.state(pid),original=state.document.chapters[0].id;
  await ui.action(pid,'save_chapter',{chapter_id:original,content:'原章正文，不丢失'});
  await ui.action(pid,'save_book_outline',{volumes:[{number:1,title:'原卷',summary:'',chapter_ids:[original]}]});
  await ui.send('Page.reload');await ui.idle();await ui.nav('writing');await ui.click('#open-import-export');
  await ui.evaluate(`(()=>{const raw=Uint8Array.from(atob('tdox1cIg19S2r9bQzsQK0c+48dX9zsQK'),c=>c.charCodeAt(0));const dt=new DataTransfer();dt.items.add(new File([raw],'自动中文.txt',{type:'text/plain'}));const input=document.querySelector('#migration-file');input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  await ui.click('#migration-preview');await ui.wait("document.querySelector('#migration-status').textContent.includes('gb18030')");
  await ui.click('#import-confirm');await ui.click('#import-commit');await ui.wait("document.querySelector('#migration-status').textContent.includes('导入完成')");
  state=await ui.state(pid);const imported=state.document.chapters.find(c=>c.id!==original).id;assert.equal(state.document.chapters.find(c=>c.id===imported).content,'严格正文\n');report.checks.push('GB18030 file through UI auto detection, preview and confirmed import preserves exact body');
  await ui.nav('writing');await ui.wait("document.querySelector('[data-drop-volume=\"2\"]')");
  await ui.evaluate(`(()=>{const source=document.querySelector('[data-chapter="${original}"]'),target=document.querySelector('[data-drop-volume="2"]'),dt=new DataTransfer();source.dispatchEvent(new DragEvent('dragstart',{bubbles:true,dataTransfer:dt}));target.dispatchEvent(new DragEvent('dragover',{bubbles:true,cancelable:true,dataTransfer:dt}));target.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:dt}));})()`);
  await ui.idle();state=await ui.state(pid);assert.deepEqual(state.document.book_outline.volumes[1].chapter_ids,[imported,original]);report.checks.push('real DragEvent cross-volume move persists membership and order');
  await ui.close();ui=await open({shell,profile,report});state=await ui.state(pid);assert.deepEqual(state.document.book_outline.volumes[1].chapter_ids,[imported,original]);report.checks.push('close and reopen retains cross-volume move and bodies');
  await ui.nav('writing');await ui.fill('#chapter-select',original);await ui.idle();await ui.click('#trash-preview');await ui.wait("document.querySelector('#trash-confirm')");
  assert.match(await ui.evaluate("document.querySelector('#trash-preview-result').innerText"),/引用/);
  await ui.fill('#trash-title','原章');await ui.click('#trash-ack');await ui.click('#trash-confirm');await ui.idle();await ui.wait(`!document.querySelector('#chapter-tree [data-chapter="${original}"]')`);
  assert.equal(await ui.evaluate(`!!document.querySelector('#chapter-select option[value="${original}"]')`),false);state=await ui.state(pid);assert.equal(state.document.chapters.find(c=>c.id===original).content,'原章正文，不丢失');report.checks.push('UI deletion impact preview, precise title and references confirmation hide chapter without content loss');
  const exported=await ui.evaluate(`fetch('/api/projects/${pid}/export?scope=book&format=txt').then(r=>r.text())`);assert.ok(!exported.includes('原章正文'));report.checks.push('recycle bin excluded from tree, selector and book export');
  await ui.click('#chapter-trash summary');await ui.click(`[data-restore-trash="${original}"]`);await ui.idle();state=await ui.state(pid);assert.deepEqual(state.document.book_outline.volumes[1].chapter_ids,[imported,original]);await ui.wait(`document.querySelector('#chapter-tree [data-chapter="${original}"]')`);report.checks.push('UI restores original volume and exact position');
  const shot=await ui.send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(out,'v27-ui.png'),Buffer.from(shot.data,'base64'));
  assert.deepEqual(report.errors,[]);assert.deepEqual(report.external,[]);report.status='passed';
 }catch(error){report.status='failed';report.error=String(error.stack||error);if(ui)try{report.body=await ui.evaluate('document.body.innerText.slice(-9000)');}catch{}throw error;}
 finally{if(ui)await ui.close();fs.writeFileSync(path.join(out,'v27-ui-report.json'),JSON.stringify(report,null,2));}
})().then(()=>process.stdout.write(JSON.stringify(report)+'\n')).catch(error=>{process.stderr.write(String(error.stack||error)+'\n');process.exitCode=1;});
