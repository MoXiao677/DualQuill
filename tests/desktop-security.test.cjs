const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const target = path.join(__dirname, '../desktop/security.cjs');
const security = fs.existsSync(target) ? require(target) : {};
test('native save only accepts explicit same-origin backup and text export routes',()=>{
  for(const route of ['/api/projects/book-1/export/book/txt','/api/projects/book-1/export/chapter/md/chapter-2','/api/backups/download/ticket-1'])assert.equal(security.downloadPath(route),route);
  for(const route of ['/api/settings','/api/projects','/api/backups/export','https://example.com/file','file:///C:/file','/api/backups/download/../secret','/api/projects/p/export/book/txt?path=C:/file'])assert.throws(()=>security.downloadPath(route));
});
test('app protocol accepts existing API/assets and rejects URLs, traversal and executable paths', () => {
  assert.equal(typeof security.classify, 'function', 'desktop URL boundary is missing');
  assert.equal(security.classify('novel://app/api/projects', 'GET').kind, 'api');
  assert.equal(security.classify('novel://app/app.js', 'GET').kind, 'asset');
  assert.equal(security.classify('novel://app/writing_candidates.js', 'GET').file, 'writing_candidates.js');
  assert.equal(security.classify('novel://app/console_usage.js', 'GET').file, 'console_usage.js');
  for (const url of ['https://example.com/', 'file:///etc/passwd', 'novel://evil/api/projects',
    'novel://user@app/api/projects', 'novel://app:81/api/projects', 'novel://app/api/session?url=https://x',
    'novel://app/../app.js', 'novel://app/%2e%2e/app.js', 'novel://app/api/%2fsettings',
    'novel://app/api/run', 'novel://app/main.cjs']) assert.throws(() => security.classify(url,'GET'), url);
  assert.throws(() => security.classify('novel://app/api/projects','DELETE'));
  assert.throws(() => security.classify('novel://app/app.js','POST'));
});
test('only explicit upload headers cross the main proxy; token and host are owned by main', () => {
  assert.equal(typeof security.proxyHeaders, 'function', 'bounded header policy is missing');
  const headers = security.proxyHeaders({'content-type':'application/json','x-novel-token':'attacker',
    host:'evil','authorization':'secret','x-novel-backup-operation':'123','x-novel-migration-preview':'1'}, 'private', 12345, 2);
  assert.equal(headers['X-Novel-Token'],'private');
  assert.equal(headers.Host,'127.0.0.1:12345');
  assert.equal(headers.Origin,'http://127.0.0.1:12345');
  assert.equal(headers['X-Novel-Backup-Operation'],'123');
  assert.equal(headers['X-Novel-Migration-Preview'],'1','migration preview must never turn into a write during proxying');
  assert.equal(headers.authorization,undefined);
});
test('IPC only accepts the owning top frame at the trusted origin', () => {
  assert.equal(typeof security.assertSender, 'function', 'IPC source validation is missing');
  const frame={url:'novel://app/'}, owner={mainFrame:frame};
  security.assertSender({sender:owner,senderFrame:frame},owner);
  for (const event of [{sender:{},senderFrame:frame},{sender:owner,senderFrame:{url:'novel://app/'}},
    {sender:owner,senderFrame:{url:'https://evil/'}}]) assert.throws(()=>security.assertSender(event,owner));
});
