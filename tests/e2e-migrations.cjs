// S2-C现有历史入口，虚构库/随机端口/headless，不使用真实配置或外部请求。
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn}=require('node:child_process'),{chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'novel-s2-c-browser-'));
const python=process.env.NOVEL_WRITER_PYTHON||'python',report={checks:[],external:[],errors:[]};
let server,browser;
async function run(args){const p=spawn(python,args,{cwd:root,windowsHide:true,env:process.env});p.stderr.on('data',d=>process.stderr.write(d));return new Promise((resolve,reject)=>{p.once('error',reject);p.once('exit',code=>code===0?resolve():reject(new Error('fixture exit '+code)));});}
async function start(db){server=spawn(python,['-B','-X','utf8','-u','run.py','--no-browser','--offline','--port','0','--database',db],{cwd:root,windowsHide:true,env:{...process.env,NOVEL_WRITER_PROVIDER_CONFIG:path.join(temp,'unused.dpapi')}});server.stderr.on('data',d=>process.stderr.write(d));return new Promise((resolve,reject)=>{let data='';const timer=setTimeout(()=>reject(new Error('startup timeout')),10000);server.once('error',reject);server.stdout.on('data',d=>{data+=d;const m=data.match(/http:\/\/127\.0\.0\.1:\d+/);if(m){clearTimeout(timer);resolve(m[0]);}});});}
async function stop(){if(server&&server.exitCode===null)await new Promise(r=>{server.once('exit',r);server.kill();});}
async function modulePage(page,name){await page.waitForFunction(()=>!document.querySelector('#toggle-modules').disabled);const button=page.locator('#tabs').getByRole('button',{name,exact:true,includeHidden:true});if(!await button.isVisible())await page.locator('#toggle-modules').click();await button.click();await page.waitForFunction(()=>!document.querySelector('#toggle-modules').disabled);if(name==='历史与恢复')await page.waitForSelector('#migration-result');}
async function finished(page){await page.waitForFunction(()=>document.querySelector('#migration-result')?.textContent.includes('迁移完成'));}
(async()=>{
  const db=path.join(temp,'fictional.sqlite3');
  await run(['-B','-X','utf8','-c',"import sys;from pathlib import Path;sys.path.insert(0,'tests/fixtures');from s2_a_samples import create_fixture_database;from s2_b_samples import build_runtime_dataset;create_fixture_database(Path(sys.argv[1]),build_runtime_dataset())",db]);
  let url=await start(db);
  browser=await chromium.launch({headless:true,...(process.env.NOVEL_WRITER_BROWSER?{executablePath:process.env.NOVEL_WRITER_BROWSER}:{})});
  const context=await browser.newContext({viewport:{width:1440,height:900}});
  await context.route('**/*',route=>{if(new URL(route.request().url()).hostname!=='127.0.0.1'){report.external.push(route.request().url());return route.abort();}return route.continue();});
  let page=await context.newPage();page.on('pageerror',e=>report.errors.push(e.message));
  await page.goto(url);
  if(!await page.locator('#project-list').isVisible())await page.locator('#toggle-left').click();
  await page.locator('[data-project="s2-a-project-one"]').click();await modulePage(page,'历史与恢复');
  assert.equal(await page.locator('#copy-project').count(),1,'S2-C真实界面缺少复制入口');
  await page.route('**/api/migrations/capabilities',route=>route.fulfill({status:404,contentType:'application/json',body:'{"error":"old"}'}));
  await modulePage(page,'创作对话');await modulePage(page,'历史与恢复');
  assert.equal(await page.locator('#copy-project').isDisabled(),true);assert.equal(await page.locator('#import-projects').isDisabled(),true);
  await page.unroute('**/api/migrations/capabilities');await modulePage(page,'创作对话');await modulePage(page,'历史与恢复');
  report.checks.push('existing history entry and old backend gate');
  const original=await(await page.request.get(url+'/api/projects/s2-a-project-one')).json();
  await page.getByRole('button',{name:'预检当前小说副本',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#migration-result').textContent.includes('预检完成'));
  assert.equal((await(await page.request.get(url+'/api/projects')).json()).length,2);
  report.checks.push('persisted preview plan leaves target unchanged');
  await page.route('**/api/migrations/copy',async route=>{await route.fetch();await route.abort('failed');});
  await page.getByRole('button',{name:'复制当前小说为新项目',exact:true}).click();await finished(page);
  await page.unroute('**/api/migrations/copy');
  const copied=JSON.parse(await page.locator('#migration-report').textContent());
  assert.equal(copied.state,'already_present');assert.equal(copied.projects.length,1);
  const newId=copied.projects[0].new_id;
  assert.equal((await(await page.request.get(url+'/api/projects')).json()).length,3);
  assert.equal(await page.evaluate(()=>sessionStorage.getItem('novel-writer.migration-operation')),null);
  assert.deepEqual(await(await page.request.get(url+'/api/projects/s2-a-project-one')).json(),original);
  report.checks.push('copy response loss recovered by SQL receipt with no duplicate');
  const legacy=path.join(temp,'legacy.json');fs.writeFileSync(legacy,JSON.stringify(original));
  await page.getByLabel('迁移来源文件',{exact:true}).setInputFiles(legacy);
  await page.getByRole('button',{name:'导入为新项目',exact:true}).click();await finished(page);
  const imported=JSON.parse(await page.locator('#migration-report').textContent());
  assert.ok(imported.missing_scopes.includes('project_snapshots'));assert.ok(imported.missing_scopes.includes('skills'));
  assert.ok((await page.locator('#migration-result').textContent()).includes('缺少'));
  assert.equal((await(await page.request.get(url+'/api/projects')).json()).length,4);
  report.checks.push('legacy workspace honest missing history and Skills');
  await page.getByLabel('迁移来源文件',{exact:true}).setInputFiles({name:'bad.json',mimeType:'application/json',buffer:Buffer.from('{"schema_version":2}')});
  await page.getByRole('button',{name:'导入为新项目',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#migration-result').textContent.includes('失败'));
  assert.equal((await(await page.request.get(url+'/api/projects')).json()).length,4);
  report.checks.push('bad import has no half project');
  for(const [width,height]of[[1440,900],[390,844]]){await page.setViewportSize({width,height});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);}
  await page.setViewportSize({width:1440,height:900});
  await page.screenshot({path:path.join(process.env.NOVEL_WRITER_ARTIFACTS||temp,'migration-history.png'),fullPage:true});
  // 通过复制项目的实际编辑入口保存，源项目与历史保持。
  if(!await page.locator('#project-list').isVisible())await page.locator('#toggle-left').click();
  await page.locator(`[data-project="${newId}"]`).click();await modulePage(page,'章节写作');
  await page.getByLabel('正文',{exact:true}).fill('\nS2-C复制本独立编辑。\n');
  await page.getByLabel('我确认修改这章正式内容，并保留此前版本。',{exact:true}).check();
  await page.getByRole('button',{name:'保存正文',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#save-state').textContent.startsWith('已保存'));
  assert.deepEqual(await(await page.request.get(url+'/api/projects/s2-a-project-one')).json(),original);
  const changed=await(await page.request.get(url+'/api/projects/'+newId)).json();assert.equal(changed.revision,4);
  assert.equal(changed.document.chapters[0].content,'\nS2-C复制本独立编辑。\n');
  report.checks.push('copied book real editor saves independently');
  await page.close();await stop();url=await start(db);page=await context.newPage();page.on('pageerror',e=>report.errors.push(e.message));await page.goto(url);
  assert.equal((await(await page.request.get(url+'/api/projects/'+newId)).json()).revision,4);
  assert.deepEqual(await(await page.request.get(url+'/api/projects/s2-a-project-one')).json(),original);
  report.checks.push('reopened target retains copy and source');
  assert.deepEqual(report.external,[]);assert.deepEqual(report.errors,[]);report.status='passed';
  console.log(JSON.stringify(report));
  if(process.env.NOVEL_WRITER_ARTIFACTS)fs.writeFileSync(path.join(process.env.NOVEL_WRITER_ARTIFACTS,'migration-browser-report.json'),JSON.stringify(report,null,2));
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();await stop();fs.rmSync(temp,{recursive:true,force:true});});
