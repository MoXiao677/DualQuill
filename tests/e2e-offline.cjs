// Offline maintenance UI; optional read-only verification of an existing local service.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
let temp, server, browser;
(async () => {
  let url = process.env.NOVEL_WRITER_AUDIT_URL;
  let store;
  if (!url) {
    temp = fs.mkdtempSync(path.join(os.tmpdir(), 'novel-offline-'));
    store = path.join(temp, 'providers.dpapi');
    fs.writeFileSync(store, 'fictional-unread-credential-store');
    server = spawn(process.env.NOVEL_WRITER_PYTHON || 'python',
      ['-B', '-X', 'utf8', '-u', 'run.py', '--no-browser', '--offline', '--port', '0', '--database', path.join(temp, 'fictional.sqlite3')],
      {cwd: root, windowsHide: true, env: {...process.env, NOVEL_WRITER_PROVIDER_CONFIG: store}});
    url = await new Promise((resolve, reject) => {
      let output = ''; const timer = setTimeout(() => reject(new Error('Startup timed out')), 10000);
      server.once('error', error => {clearTimeout(timer); reject(error);});
      server.once('exit', code => {clearTimeout(timer); reject(new Error('Server exited: ' + code));});
      server.stdout.on('data', data => {output += data; const match = output.match(/http:\/\/127\.0\.0\.1:\d+/); if(match) {clearTimeout(timer); resolve(match[0]);}});
      server.stderr.on('data', data => process.stderr.write(data));
    });
  }
  assert.equal(new URL(url).hostname, '127.0.0.1');
  const origin = new URL(url).origin;
  browser = await chromium.launch({headless: true, ...(process.env.NOVEL_WRITER_BROWSER ? {executablePath: process.env.NOVEL_WRITER_BROWSER} : {})});
  const context = await browser.newContext({viewport: {width: 1440, height: 900}});
  const page = await context.newPage();
  const external = [], errors = [], posts = [];
  page.on('pageerror', error => errors.push(error.message));
  await context.route('**/*', async route => {
    const request = route.request(), target = new URL(request.url());
    if (target.origin !== origin) {external.push(target.origin); await route.abort(); return;}
    if (request.method() !== 'GET') {posts.push(target.pathname); await route.abort(); return;}
    // The actual settings response and static resources remain live; author data stays hidden.
    if (target.pathname === '/api/projects' || target.pathname === '/api/skills') {await route.fulfill({json: []}); return;}
    if (target.pathname.startsWith('/api/projects/') || target.pathname.startsWith('/api/skills/')) {await route.abort(); return;}
    await route.continue();
  });
  await page.goto(url + '/#settings');
  await page.waitForSelector('form[data-provider="gg"]');
  assert.equal(await page.locator('form[data-provider]').count(), 3);
  assert.ok((await page.locator('#content').innerText()).includes('离线维护中'));
  assert.ok(!(await page.locator('#content').innerText()).includes('尚未配置密钥'));
  for (const id of ['gg', 'catie', 'odys']) {
    const form = page.locator(`form[data-provider="${id}"]`);
    for (const input of ['API Base URL', 'API Key', '模型 ID']) {
      assert.equal(await form.getByLabel(input, {exact: true}).isDisabled(), true);
    }
    for (const name of ['保存配置', '测试连接']) {
      assert.equal(await form.getByRole('button', {name, exact: true}).isDisabled(), true);
    }
    assert.equal(await form.getByLabel('API Key', {exact: true}).inputValue(), '');
    await form.evaluate(form => form.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true})));
  }
  await page.reload();
  await page.waitForSelector('form[data-provider="gg"]');
  const response = await page.request.get(url + '/api/settings');
  assert.equal(response.status(), 200);
  const settings = await response.json();
  assert.equal(settings.offline_mode, true);
  assert.equal(settings.connection_checks_enabled, false);
  assert.equal(settings.model_calls_enabled, false);
  assert.deepEqual(Object.keys(settings.connections).sort(), ['catie', 'gg', 'odys']);
  for (const value of Object.values(settings.connections)) {
    assert.equal(value.key_configured, null);
    assert.equal(value.credential_access_enabled, false);
  }
  for (const [width, height] of [[1440, 900], [390, 844]]) {
    await page.setViewportSize({width, height});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
  }
  if (process.env.NOVEL_WRITER_ARTIFACTS) {
    const artifacts = path.resolve(process.env.NOVEL_WRITER_ARTIFACTS);
    assert.ok(!artifacts.startsWith(root + path.sep));
    fs.mkdirSync(artifacts, {recursive: true});
    await page.setViewportSize({width: 1440, height: 900});
    await page.screenshot({path: path.join(artifacts, 'offline-settings.png')});
    fs.writeFileSync(path.join(artifacts, 'offline-settings-report.json'), JSON.stringify({
      status: 'passed', url: url + '/#settings', database_path: settings.database_path,
      connections: Object.keys(settings.connections), offline_mode: settings.offline_mode,
      model_calls_enabled: settings.model_calls_enabled, external, errors, posts
    }, null, 2));
  }
  assert.deepEqual(external, []);
  assert.deepEqual(errors, []);
  assert.deepEqual(posts, []);
  if (store) assert.equal(fs.readFileSync(store, 'utf8'), 'fictional-unread-credential-store');
  console.log('Offline E2E passed: live settings contract, unknown credentials, disabled actions, reload, desktop/mobile; zero writes/external requests.');
})().catch(error => {console.error(error); process.exitCode = 1;}).finally(async () => {
  if (browser) await browser.close();
  if (server && server.exitCode === null) {
    const exited = new Promise(resolve => server.once('exit', resolve)); server.kill(); await exited;
  }
  if (temp) {
    const resolved = path.resolve(temp);
    assert.equal(path.dirname(resolved), path.resolve(os.tmpdir()));
    assert.ok(path.basename(resolved).startsWith('novel-offline-'));
    fs.rmSync(resolved, {recursive: true, force: true});
  }
});
