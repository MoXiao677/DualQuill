const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn}=require('node:child_process'),{chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),temporary=fs.mkdtempSync(path.join(os.tmpdir(),'novel-s3-browser-'));
const python=process.env.NOVEL_WRITER_PYTHON||'python',report={checks:[],external:[],errors:[]};let server,browser;
async function modulePage(page,name){await page.waitForFunction(()=>!document.querySelector('#toggle-modules').disabled);const button=page.locator('#tabs').getByRole('button',{name,exact:true,includeHidden:true});if(!await button.isVisible())await page.locator('#toggle-modules').click();await button.click();await page.waitForFunction(()=>!document.querySelector('#toggle-modules').disabled);}
async function saved(page){await page.waitForFunction(()=>document.querySelector('#save-state').textContent.startsWith('已保存'));}
async function openBook(page){if(!await page.locator('#project-list').isVisible())await page.locator('#toggle-left').click();await page.locator('[data-project="p1"]').click();await saved(page);}
async function stop(){if(server&&server.exitCode===null)await new Promise(r=>{server.once('exit',r);server.kill();});}
async function referenceOrderChecks(page,url) {
  // 独立的第二本书：通过真实保存入口放入合法逆序/重复引用，不改变原六组样本。
  const session=await(await page.request.get(url+'/api/session')).json();
  const read=async()=>await(await page.request.get(url+'/api/projects/p2')).json();
  async function seed(action,fields){const current=await read();const response=await page.request.post(url+'/api/projects/p2/actions',{
    headers:{'X-Novel-Token':session.token},data:{action,fields,expected_revision:current.revision}});assert.equal(response.status(),200);return await response.json();}
  const initial=await read(),volumes=structuredClone(initial.document.book_outline.volumes),scenes=structuredClone(initial.document.chapter_outlines[0].scenes);
  const original={volume:['p2-c3','p2-c1','p2-c2'],scene:['p2-char3','p2-char1','p2-char3'],chapter:['p2-char3','p2-char1','p2-char3']};
  volumes[0].chapter_ids=original.volume;scenes[0].character_ids=original.scene;
  await seed('save_book_outline',{volumes});
  const seeded=await seed('save_chapter_outline',{chapter_id:'p2-c5',scenes,character_ids:original.chapter});
  const references=state=>({volume:state.document.book_outline.volumes[0].chapter_ids,
    scene:state.document.chapter_outlines[0].scenes[0].character_ids,chapter:state.document.chapter_outlines[0].character_ids});
  assert.deepEqual(references(seeded),original,'真实保存入口应保留合法逆序与重复人物引用');
  await page.goto(url);if(!await page.locator('#project-list').isVisible())await page.locator('#toggle-left').click();
  await page.locator('[data-project="p2"]').click();await saved(page);await modulePage(page,'全书大纲');
  await page.getByLabel('卷名',{exact:true}).first().fill('只改卷名保留引用');
  await page.getByRole('button',{name:'保存全书大纲',exact:true}).click();await saved(page);
  await modulePage(page,'章节写作');await page.locator('#chapter-select').selectOption('p2-c5');await page.locator('[data-pane="outline"]').click();
  await page.getByLabel('场景目标',{exact:true}).first().fill('只改场景摘要');await page.getByLabel('本章目标',{exact:true}).fill('只改章节目标');
  await page.getByRole('button',{name:'保存章节细纲',exact:true}).click();await saved(page);
  let current=await read();
  const unedited={expected:original,actual:references(current)};
  if(process.env.NOVEL_WRITER_ARTIFACTS)fs.writeFileSync(path.join(process.env.NOVEL_WRITER_ARTIFACTS,'reference-order-probe.json'),JSON.stringify(unedited,null,2));
  assert.deepEqual(unedited.actual,original,'仅改文字时三类引用的原顺序和合法重复项均不可改变');
  report.checks.push('三类逆序引用与合法重复项在仅改文字后原样保存');
  await modulePage(page,'全书大纲');
  await page.getByLabel('分卷章节',{exact:true}).first().selectOption(['p2-c1','p2-c3','p2-c4']);
  await modulePage(page,'人物设定');await modulePage(page,'全书大纲');
  assert.deepEqual(references(await read()).volume,original.volume,'切标签草稿不能提前写库');
  await page.getByRole('button',{name:'保存全书大纲',exact:true}).click();await saved(page);
  const changedVolume=['p2-c3','p2-c1','p2-c4'];
  assert.deepEqual(references(await read()).volume,changedVolume,'保留仍选中项原顺序，新增章节追加');
  await page.reload();await modulePage(page,'全书大纲');await page.getByLabel('卷名',{exact:true}).first().fill('刷新后只改卷名');
  await page.getByRole('button',{name:'保存全书大纲',exact:true}).click();await saved(page);
  assert.deepEqual(references(await read()).volume,changedVolume);
  report.checks.push('分卷成员变更保序追加，草稿切标签与刷新再保存一致');
  await modulePage(page,'章节写作');await page.locator('#chapter-select').selectOption('p2-c5');await page.locator('[data-pane="outline"]').click();
  await page.getByLabel('场景人物',{exact:true}).first().selectOption(['p2-char2','p2-char3']);
  await page.getByLabel('本章参与人物',{exact:true}).selectOption(['p2-char1','p2-char2','p2-char3']);
  await modulePage(page,'全书大纲');await modulePage(page,'章节写作');await page.locator('[data-pane="outline"]').click();
  assert.deepEqual(references(await read()),{...original,volume:changedVolume},'人物选择草稿不能提前写库');
  await page.getByRole('button',{name:'保存章节细纲',exact:true}).click();await saved(page);
  const changed={volume:changedVolume,scene:['p2-char3','p2-char3','p2-char2'],chapter:['p2-char3','p2-char1','p2-char3','p2-char2']};
  assert.deepEqual(references(await read()),changed,'人物成员变更保留重复旧项顺序，再追加新成员');
  await page.reload();await modulePage(page,'章节写作');await page.locator('#chapter-select').selectOption('p2-c5');await page.locator('[data-pane="outline"]').click();
  await page.getByLabel('本章目标',{exact:true}).fill('刷新后仅改目标');
  await page.getByRole('button',{name:'保存章节细纲',exact:true}).click();await saved(page);
  current=await read();assert.deepEqual(references(current),changed);
  assert.deepEqual(current.document.versions.slice(0,seeded.document.versions.length),seeded.document.versions,'原历史不可改写');
  report.checks.push('场景与章节人物成员变更、重复项、草稿还原及刷新保存一致');
}
(async()=>{
  const db=path.join(temporary,'fictional.sqlite3');
  const fixture=spawn(python,['-B','-X','utf8','-c',"import sys;from pathlib import Path;sys.path.insert(0,'src');sys.path.insert(0,'tests/fixtures');from s3_planning import create_planning_database;create_planning_database(Path(sys.argv[1]))",db],{cwd:root,windowsHide:true});fixture.stderr.on('data',d=>process.stderr.write(d));assert.equal(await new Promise(r=>fixture.once('exit',r)),0);
  server=spawn(python,['-B','-X','utf8','-u','run.py','--no-browser','--offline','--port','0','--database',db],{cwd:root,windowsHide:true,env:process.env});server.stderr.on('data',d=>process.stderr.write(d));
  const url=await new Promise((resolve,reject)=>{let data='';const timer=setTimeout(()=>reject(new Error('startup')),10000);server.stdout.on('data',d=>{data+=d;const m=data.match(/http:\/\/127\.0\.0\.1:\d+/);if(m){clearTimeout(timer);resolve(m[0]);}});});
  browser=await chromium.launch({headless:true,executablePath:process.env.NOVEL_WRITER_BROWSER});const context=await browser.newContext({viewport:{width:1440,height:900}});
  await context.route('**/*',route=>{if(new URL(route.request().url()).hostname!=='127.0.0.1'){report.external.push(route.request().url());return route.abort();}return route.continue();});
  const page=await context.newPage();page.on('pageerror',e=>report.errors.push(e.message));
  await referenceOrderChecks(page,url);
  await page.goto(url);await openBook(page);await modulePage(page,'全书大纲');
  assert.equal(await page.locator('[data-plan="volumes"]').count(),1,'分卷真实编辑入口缺失');
  await page.getByLabel('卷名',{exact:true}).first().fill('保存的新第一卷');
  const nestedText='\n\n分卷原文  \n末行  ';
  await page.getByLabel('分卷概要',{exact:true}).first().fill(nestedText);
  await page.getByLabel('分卷章节',{exact:true}).first().selectOption(['p1-c1','p1-c2','p1-c3']);
  await page.getByRole('button',{name:'保存全书大纲',exact:true}).click();await saved(page);
  await page.reload();await modulePage(page,'全书大纲');assert.equal(await page.getByLabel('卷名',{exact:true}).first().inputValue(),'保存的新第一卷');
  assert.equal(await page.getByLabel('分卷概要',{exact:true}).first().inputValue(),nestedText,'嵌套首换行/尾空格必须保持');
  report.checks.push('2卷20章分卷归属编辑保存刷新');
  await modulePage(page,'章节写作');await page.locator('#chapter-select').selectOption('p1-c5');await page.locator('[data-pane="outline"]').click();
  await page.getByLabel('场景目标',{exact:true}).first().fill('调查来信');await page.getByLabel('场景顺序',{exact:true}).first().fill('3');
  await page.getByLabel('场景人物',{exact:true}).first().selectOption(['p1-char1','p1-char3']);
  await page.getByRole('button',{name:'保存章节细纲',exact:true}).click();await saved(page);
  let state=await(await page.request.get(url+'/api/projects/p1')).json();assert.equal(state.document.chapter_outlines[0].scenes[0].summary,'调查来信');
  assert.deepEqual(state.document.chapter_outlines[0].scenes[0].character_ids,['p1-char1','p1-char3']);
  assert.equal(state.document.chapter_outlines[0].scenes[1].summary,'\n本章后续场景\r\n保留空格  ','未编辑场景CRLF/首换行原文不变');
  assert.equal(state.document.book_outline.volumes[0].summary,nestedText);
  report.checks.push('场景顺序目标人物实际保存');
  await modulePage(page,'人物设定');await page.getByLabel('人物目标',{exact:true}).first().fill('寻找灯塔');
  await page.getByLabel('关系对象',{exact:true}).first().selectOption('p1-char3');await page.getByLabel('关系名称',{exact:true}).first().fill('盟友');
  await page.getByRole('button',{name:'保存人物',exact:true}).click();await saved(page);
  await page.reload();await modulePage(page,'人物设定');assert.equal(await page.getByLabel('人物目标',{exact:true}).first().inputValue(),'寻找灯塔');
  assert.equal(await page.getByLabel('关系对象',{exact:true}).first().inputValue(),'p1-char3');report.checks.push('人物目标关系保存刷新');
  // 未保存嵌套编辑仍在现有内存草稿内，切回还原。
  await page.getByLabel('人物目标',{exact:true}).first().fill('未保存目标');await modulePage(page,'全书大纲');await modulePage(page,'人物设定');
  assert.equal(await page.getByLabel('人物目标',{exact:true}).first().inputValue(),'未保存目标');
  await modulePage(page,'章节写作');await page.locator('#chapter-select').selectOption('p1-c5');await page.locator('[data-pane="body"]').click();
  await page.getByLabel('正文',{exact:true}).fill('UNSAVED_PRIVATE_BODY');
  await page.getByRole('button',{name:'预览已保存上下文',exact:true}).click();await page.waitForSelector('#context-preview-form');
  await page.getByText('来源、版本、选入/排除及裁剪报告',{exact:true}).click();
  await page.getByRole('button',{name:'生成只读预览',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#context-preview-report').textContent.length>0);
  let result=JSON.parse(await page.locator('#context-preview-report').textContent());
  assert.ok(!result.context_text.includes('FUTURE_'));assert.ok(!JSON.stringify(result).includes('UNSAVED_PRIVATE_BODY'));assert.ok(!result.context_text.includes('BODY_p1_5'));assert.ok(!result.context_text.includes('BODY_p2'));
  await page.getByLabel('包含本章细纲、场景与IDEA（创作计划）',{exact:true}).check();await page.getByLabel('资料字符上限',{exact:true}).fill('128');
  await page.getByRole('button',{name:'生成只读预览',exact:true}).click();await page.waitForFunction(()=>{const text=document.querySelector('#context-preview-report').textContent;return text&&JSON.parse(text).budget_chars===128;});
  result=JSON.parse(await page.locator('#context-preview-report').textContent());assert.equal(result.used_chars,128);assert.ok(result.sources.some(s=>s.truncated));assert.ok(result.warnings.length);
  report.checks.push('已保存上下文来源/未来与未保存跨书排除/计划授权/字符裁剪');
  let release;const gate=new Promise(resolve=>{release=resolve;});let reached;
  const started=new Promise(resolve=>{reached=resolve;});
  await page.route('**/context-preview',async route=>{const response=await route.fetch();reached();await gate;await route.fulfill({response});});
  await page.getByRole('button',{name:'生成只读预览',exact:true}).click();await started;
  await page.getByLabel('写作章节',{exact:true}).selectOption('p1-c6');
  assert.equal(await page.locator('#context-preview-report').textContent(),'');
  const late=page.waitForResponse(r=>r.url().endsWith('/context-preview'));release();await(await late).finished();
  await page.evaluate(()=>new Promise(requestAnimationFrame));assert.equal(await page.locator('#context-preview-report').textContent(),'');
  await page.unroute('**/context-preview');report.checks.push('选章变化清空旧结果并拒绝迟到响应');
  await modulePage(page,'人物设定');
  const session=await(await page.request.get(url+'/api/session')).json(),latest=await(await page.request.get(url+'/api/projects/p1')).json();
  const externalSave=await page.request.post(url+'/api/projects/p1/actions',{headers:{'X-Novel-Token':session.token},data:{action:'save_worldbuilding',fields:{content:'另一个窗口保存'},expected_revision:latest.revision}});assert.equal(externalSave.status(),200);
  await page.getByLabel('人物目标',{exact:true}).first().fill('冲突时保留嵌套目标');
  const conflict=page.waitForResponse(r=>r.url().endsWith('/p1/actions')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'保存人物',exact:true}).click();assert.equal((await conflict).status(),409);
  await page.waitForFunction(()=>document.querySelector('#save-state').textContent.includes('未保存'));
  assert.equal(await page.getByLabel('人物目标',{exact:true}).first().inputValue(),'冲突时保留嵌套目标');
  report.checks.push('原revision冲突保护保留嵌套输入与已保存历史');
  for(const [w,h]of[[1440,900],[390,844]]){await page.setViewportSize({width:w,height:h});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);}
  if(process.env.NOVEL_WRITER_ARTIFACTS)await page.screenshot({path:path.join(process.env.NOVEL_WRITER_ARTIFACTS,'s3-preview.png'),fullPage:true});
  report.status='passed';assert.deepEqual(report.errors,[]);assert.deepEqual(report.external,[]);console.log(JSON.stringify(report));
  if(process.env.NOVEL_WRITER_ARTIFACTS)fs.writeFileSync(path.join(process.env.NOVEL_WRITER_ARTIFACTS,'s3-browser-report.json'),JSON.stringify(report,null,2));
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();await stop();fs.rmSync(temporary,{recursive:true,force:true});});
