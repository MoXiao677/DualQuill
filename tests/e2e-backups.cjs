// 完整包下载、独立恢复及恢复后编辑/重启；全部虚构库，端口自动分配。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {chromium} = require('playwright');
const root = path.resolve(__dirname,'..');
const temporary = fs.mkdtempSync(path.join(os.tmpdir(),'novel-s2-b-browser-'));
const python = process.env.NOVEL_WRITER_PYTHON || 'python';
let server,browser;
const report = {checks:[],external:[],errors:[]};
async function start(database) {
  server = spawn(python,['-B','-X','utf8','-u','run.py','--no-browser','--offline','--port','0','--database',database],
    {cwd:root,windowsHide:true,env:{...process.env,NOVEL_WRITER_PROVIDER_CONFIG:path.join(temporary,'unused.dpapi')}});
  return new Promise((resolve,reject)=>{
    let text='';const timer=setTimeout(()=>reject(new Error('startup timeout')),10000);
    server.once('error',reject);
    server.stdout.on('data',data=>{text+=data;const match=text.match(/http:\/\/127\.0\.0\.1:\d+/);if(match){clearTimeout(timer);resolve(match[0]);}});
    server.stderr.on('data',data=>process.stderr.write(data));
  });
}
async function stop(){if(server&&server.exitCode===null)await new Promise(resolve=>{server.once('exit',resolve);server.kill();});}
async function modulePage(page,name){const button=page.locator('#tabs').getByRole('button',{name,exact:true,includeHidden:true});if(!await button.isVisible())await page.locator('#toggle-modules').click();await button.click();}
async function saved(page){await page.waitForFunction(()=>document.querySelector('#save-state').textContent.startsWith('已保存'));}
(async()=>{
  const database=path.join(temporary,'source.sqlite3');
  const fixture=spawn(python,['-B','-X','utf8','-c',"import sys; from pathlib import Path; sys.path.insert(0,'tests/fixtures'); from s2_a_samples import create_fixture_database; from s2_b_samples import build_runtime_dataset; create_fixture_database(Path(sys.argv[1]),build_runtime_dataset())",database],{cwd:root,windowsHide:true});
  assert.equal(await new Promise(resolve=>fixture.once('exit',resolve)),0);
  let url=await start(database);
  browser=await chromium.launch({headless:true,...(process.env.NOVEL_WRITER_BROWSER?{executablePath:process.env.NOVEL_WRITER_BROWSER}:{})});
  const context=await browser.newContext({acceptDownloads:true,viewport:{width:1440,height:900}});
  await context.route('**/*',route=>{if(new URL(route.request().url()).hostname!=='127.0.0.1'){report.external.push(route.request().url());return route.abort();}return route.continue();});
  let page=await context.newPage();page.on('pageerror',error=>report.errors.push(error.message));
  await page.goto(url);await modulePage(page,'历史与恢复');
  await page.route('**/api/backups/capabilities',route=>route.fulfill({status:404,contentType:'application/json',body:'{"error":"old backend"}'}));
  await modulePage(page,'创作对话');await modulePage(page,'历史与恢复');
  assert.equal(await page.locator('#create-backup').isDisabled(),true);
  assert.equal(await page.locator('#restore-backup').isDisabled(),true);
  assert.ok((await page.locator('#content').textContent()).includes('当前运行后端尚未加载'));
  await page.unroute('**/api/backups/capabilities');
  await modulePage(page,'创作对话');await modulePage(page,'历史与恢复');
  report.checks.push('old running backend capability gate');
  await page.waitForSelector('#create-backup');
  const downloadPromise=page.waitForEvent('download');
  await page.getByRole('button',{name:'下载完整库备份',exact:true}).click();
  const download=await downloadPromise,archive=path.join(temporary,'download.nwbak');await download.saveAs(archive);
  assert.ok(fs.statSync(archive).size>0);report.checks.push('native complete-library download');
  await page.waitForFunction(()=>!document.querySelector('#create-backup').disabled);
  await page.waitForSelector('#check-backup-operation');
  await page.getByLabel('完整备份包',{exact:true}).setInputFiles(archive);
  // 服务实际落盘后丢弃响应；UI必须查回同一操作而非另建目标。
  await page.route('**/api/backups/restore',async route=>{await route.fetch();await route.abort('failed');});
  await page.getByRole('button',{name:'恢复到独立新目录',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#backup-result').textContent.includes('恢复完成'));
  await page.unroute('**/api/backups/restore');
  const restored=await page.locator('#backup-result').getAttribute('data-database-path');assert.ok(restored&&fs.existsSync(restored));
  assert.notEqual(path.resolve(restored),path.resolve(database));report.checks.push('independent restore with verified result');
  assert.equal(fs.readdirSync(temporary).filter(name=>name.startsWith('restored-backup-')).length,1);
  assert.equal(await page.evaluate(()=>sessionStorage.getItem('novel-writer.backup-operation')),null);
  report.checks.push('lost response recovered by operation identity');
  for(const [width,height]of[[1440,900],[390,844]]){await page.setViewportSize({width,height});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);}
  await page.getByLabel('完整备份包',{exact:true}).setInputFiles({name:'corrupt.nwbak',mimeType:'application/octet-stream',buffer:Buffer.from('notzip')});
  await page.getByRole('button',{name:'恢复到独立新目录',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#backup-result').textContent.includes('失败'));
  assert.deepEqual(fs.readdirSync(temporary).filter(name=>name.startsWith('restored-backup-')),[path.basename(path.dirname(restored))]);
  report.checks.push('bad upload has no half target');
  await page.close();await stop();url=await start(restored);page=await context.newPage();page.on('pageerror',error=>report.errors.push(error.message));
  await page.goto(url);await page.getByRole('button',{name:'切换导航面板',exact:true}).click();
  const books=await(await page.request.get(url+'/api/projects')).json();assert.equal(books.length,2);
  await page.locator('[data-project="s2-a-project-one"]').click();await saved(page);
  await modulePage(page,'章节写作');
  await page.getByLabel('正文',{exact:true}).fill('\n浏览器恢复后新稿。\n');
  await page.getByLabel('我确认修改这章正式内容，并保留此前版本。',{exact:true}).check();
  await page.getByRole('button',{name:'保存正文',exact:true}).click();await saved(page);
  const revision=(await(await page.request.get(url+'/api/projects/s2-a-project-one')).json()).revision;
  assert.equal(revision,4);await page.close();await stop();url=await start(restored);page=await context.newPage();await page.goto(url);
  const reopened=await(await page.request.get(url+'/api/projects/s2-a-project-one')).json();assert.equal(reopened.revision,4);assert.equal(reopened.document.chapters[0].content,'\n浏览器恢复后新稿。\n');
  report.checks.push('restored UI saves and survives server restart');
  if(!await page.locator('#project-list').isVisible())await page.getByRole('button',{name:'切换导航面板',exact:true}).click();
  await page.locator('[data-project="s2-a-project-one"]').click();await saved(page);await modulePage(page,'章节写作');
  if(!await page.locator('#right-panel').isVisible())await page.getByRole('button',{name:'切换上下文面板',exact:true}).click();
  await page.getByLabel('历史版本',{exact:true}).selectOption({index:1});
  page.once('dialog',dialog=>dialog.accept());
  await page.getByRole('button',{name:'恢复此版为新草稿',exact:true}).click();await saved(page);
  const history=(await(await page.request.get(url+'/api/projects/s2-a-project-one')).json()).document;
  assert.equal(history.versions.length,reopened.document.versions.length+1);
  assert.deepEqual(history.versions.slice(0,reopened.document.versions.length),reopened.document.versions);
  assert.deepEqual(history.chapters.map(c=>[c.id,c.number]),reopened.document.chapters.map(c=>[c.id,c.number]));
  await modulePage(page,'人物设定');await page.getByRole('button',{name:'＋ 新建人物',exact:true}).click();
  await page.locator('#create-dialog').getByLabel('人物姓名',{exact:true}).fill('恢复库新增虚构人物');await page.getByRole('button',{name:'创建',exact:true}).click();await saved(page);
  await modulePage(page,'世界观');await page.getByLabel('世界观与设定',{exact:true}).fill('恢复库的新虚构世界观');
  await page.getByRole('button',{name:'保存世界观',exact:true}).click();await saved(page);
  await modulePage(page,'Skills');
  const skills=await(await page.request.get(url+'/api/skills')).json();assert.equal(skills.length,3);
  const texts=[];for(const skill of skills){const data=await(await page.request.get(url+'/api/skills/'+skill.id)).json();texts.push(...data.files.map(f=>f.content));}
  // textarea.value按HTML规则将CRLF呈现为LF；SQL/API原文保真由逐单元格往返断言核验。
  assert.ok(texts.map(text=>text.replace(/\r\n?/g,'\n')).includes(await page.getByLabel('技能原文',{exact:true}).inputValue()));
  report.checks.push('restored history appends without changing originals; characters world and Skills work');
  await modulePage(page,'章节写作');
  const second=await context.newPage();second.on('pageerror',error=>report.errors.push(error.message));await second.goto(url);
  if(!await second.locator('#project-list').isVisible())await second.getByRole('button',{name:'切换导航面板',exact:true}).click();
  await second.locator('[data-project="s2-a-project-one"]').click();await saved(second);await modulePage(second,'章节写作');
  const firstResponse=page.waitForResponse(response=>response.url().endsWith('/s2-a-project-one/actions')&&response.request().method()==='POST');
  await page.getByLabel('正文',{exact:true}).fill('第一窗口合法保存');await page.getByRole('button',{name:'保存正文',exact:true}).click();
  const firstResult=await firstResponse;assert.equal(firstResult.status(),200,await firstResult.text());await saved(page);
  const conflictResponse=second.waitForResponse(response=>response.url().endsWith('/s2-a-project-one/actions')&&response.request().method()==='POST');
  await second.getByLabel('正文',{exact:true}).fill('第二窗口冲突时保留输入');await second.getByRole('button',{name:'保存正文',exact:true}).click();
  const conflictResult=await conflictResponse;assert.equal(conflictResult.status(),409,await conflictResult.text());
  await second.waitForFunction(()=>document.querySelector('#save-state').textContent.includes('未保存'));
  assert.equal(await second.getByLabel('正文',{exact:true}).inputValue(),'第二窗口冲突时保留输入');
  assert.equal((await(await page.request.get(url+'/api/projects/s2-a-project-one')).json()).document.chapters[0].content,'第一窗口合法保存');
  second.once('dialog',dialog=>dialog.accept());await second.close();
  report.checks.push('two restored-library windows reject stale save and retain input');
  report.database=database;report.restored=restored;report.archive=archive;report.status='passed';
  assert.deepEqual(report.external,[]);assert.deepEqual(report.errors,[]);
  console.log(JSON.stringify(report));
  if(process.env.NOVEL_WRITER_ARTIFACTS)fs.writeFileSync(path.join(process.env.NOVEL_WRITER_ARTIFACTS,'backup-browser-report.json'),JSON.stringify(report,null,2));
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(async()=>{
  if(browser)await browser.close();await stop();
  fs.rmSync(temporary,{recursive:true,force:true});
});
