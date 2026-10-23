// Provider configuration uses fictional keys and an isolated encrypted store.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'novel-providers-'));
let server, browser;
(async () => {
  server = spawn(process.env.NOVEL_WRITER_PYTHON || 'python', ['-B', '-X', 'utf8', '-u', 'run.py', '--no-browser', '--port', '0', '--database', path.join(temp, 'fictional.sqlite3')], {
    cwd: root, windowsHide: true, env: {...process.env, NOVEL_WRITER_PROVIDER_CONFIG: path.join(temp, 'providers.dpapi')}
  });
  const url = await new Promise((resolve, reject) => {
    let output = ''; const timer = setTimeout(() => reject(new Error('Startup timed out')), 10000);
    server.on('error', reject);
    server.stdout.on('data', data => {output += data; const match = output.match(/http:\/\/127\.0\.0\.1:\d+/); if(match) {clearTimeout(timer); resolve(match[0]);}});
    server.stderr.on('data', data => process.stderr.write(data));
  });
  browser = await chromium.launch({headless: true, ...(process.env.NOVEL_WRITER_BROWSER ? {executablePath: process.env.NOVEL_WRITER_BROWSER} : {})});
  const page = await browser.newPage({viewport: {width: 1280, height: 720}});
  const external = [], errors = [];
  page.on('request', r => {if(!r.url().startsWith(url)) external.push(r.url());});
  page.on('pageerror', e => errors.push(e.message));
  await page.goto(url + '/#settings');
  await page.waitForSelector('form[data-provider="gg"]');
  const form = page.locator('form[data-provider="gg"]');
  assert.equal(await form.getByLabel('API Key', {exact:true}).isDisabled(), false);
  assert.equal(await form.getByRole('button', {name:'测试连接',exact:true}).isDisabled(), true);
  await form.getByLabel('API Key', {exact:true}).fill('fictional-private-sentinel');
  await form.getByLabel('模型 ID', {exact:true}).fill('gemini-fictional');
  await form.getByRole('button', {name:'保存配置',exact:true}).click();
  await page.waitForFunction(() => document.querySelector('form[data-provider="gg"] .provider-result').textContent.includes('已加密保存'));
  assert.equal(await form.getByLabel('API Key', {exact:true}).inputValue(), '');
  const safe = await (await page.request.get(url + '/api/settings')).json();
  assert.equal(safe.connections.gg.key_configured, true);
  assert.ok(!JSON.stringify(safe).includes('fictional-private-sentinel'));
  assert.ok(!fs.readFileSync(path.join(temp,'providers.dpapi')).includes(Buffer.from('fictional-private-sentinel')));
  await page.route('**/api/providers/test', async route => {
    assert.deepEqual(route.request().postDataJSON(), {id:'gg'});
    await route.fulfill({json:{ok:true,models:['gemini-fictional','gemini-another'],http_status:200,message:'模型列表连接通过；尚未验证文本生成',selected_model_available:true}});
  });
  await form.getByRole('button', {name:'测试连接',exact:true}).click();
  await page.waitForFunction(() => document.querySelector('form[data-provider="gg"] .provider-result').textContent.includes('模型列表连接通过'));
  assert.equal(await form.locator('datalist option').count(), 2);
  await page.reload();
  await page.waitForSelector('form[data-provider="gg"]');
  assert.equal(await form.getByLabel('API Key', {exact:true}).inputValue(), '');
  assert.equal(await form.getByLabel('模型 ID', {exact:true}).inputValue(), 'gemini-fictional');
  const storage = await page.evaluate(() => JSON.stringify({local:{...localStorage},session:{...sessionStorage}}));
  assert.ok(!storage.includes('fictional-private-sentinel'));
  for(const [width,height] of [[1280,720],[390,844]]) {
    await page.setViewportSize({width,height});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth+1), true);
  }
  assert.deepEqual(external, []);
  assert.deepEqual(errors, []);
  console.log('Provider E2E passed: encrypted save, blank returned key, reload, list UI, isolated browser storage, desktop/mobile.');
})().catch(error => {console.error(error);process.exitCode=1;}).finally(async () => {
  if(browser) await browser.close();
  if(server) {const exited=new Promise(resolve=>server.once('exit',resolve)); server.kill(); await exited;}
  fs.rmSync(temp,{recursive:true,force:true});
});
