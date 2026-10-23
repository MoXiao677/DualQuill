import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const source = new URL('../src/novel_writer/ui/static/state.js', import.meta.url);
const mod = await import('data:text/javascript;base64,' + Buffer.from(fs.existsSync(source) ? fs.readFileSync(source, 'utf8') : '').toString('base64'));
const layoutSource = new URL('../src/novel_writer/ui/static/layout.js', import.meta.url);
const layout = await import('data:text/javascript;base64,' + Buffer.from(fs.readFileSync(layoutSource,'utf8')).toString('base64'));

test('drafts isolate project and document without changing author whitespace', () => {
  assert.equal(typeof mod.DraftStore, 'function', '缺少按实体隔离的内存草稿');
  const drafts = new mod.DraftStore();
  drafts.put('a/body', 'a', 2, { content: '\n\n甲  ' });
  drafts.put('a/idea', 'a', 2, { content: '灵感' });
  drafts.put('b/body', 'b', 9, { content: '乙' });
  assert.equal(drafts.get('a/body').values.content, '\n\n甲  ');
  drafts.remove('a/idea');
  assert.equal(drafts.get('b/body').baseRevision, 9);
  assert.equal(drafts.size, 2);
});
test('own save advances matching drafts but never rebases a stale draft', () => {
  assert.equal(typeof mod.DraftStore, 'function');
  const drafts = new mod.DraftStore();
  drafts.put('body', 'a', 3, { content: '正文' });
  drafts.put('idea', 'a', 3, { content: 'IDEA' });
  drafts.put('stale', 'a', 2, { content: '旧窗口' });
  drafts.acknowledge('a', 3, 4, 'body');
  assert.equal(drafts.get('body'), undefined);
  assert.equal(drafts.get('idea').baseRevision, 4);
  assert.equal(drafts.get('stale').baseRevision, 2);
  drafts.put('stale', 'a', 4, { content: '保留修改' });
  assert.equal(drafts.get('stale').baseRevision, 2, '输入不能暗中消除冲突');
  drafts.rebase('stale', 4);
  assert.equal(drafts.get('stale').baseRevision, 4);
});
test('line diff reconstructs both texts including blank lines and marks edits', () => {
  assert.equal(typeof mod.diffLines, 'function', '缺少只读正文差异');
  const old = '\n第一行\n旧句\n尾行\n';
  const current = '\n第一行\n新句\n尾行\n';
  const diff = mod.diffLines(old, current);
  assert.equal(diff.filter(row => row.kind !== 'add').map(row => row.text).join('\n'), old);
  assert.equal(diff.filter(row => row.kind !== 'remove').map(row => row.text).join('\n'), current);
  assert.deepEqual(diff.filter(row => row.kind !== 'same').map(row => [row.kind, row.text]), [['remove', '旧句'], ['add', '新句']]);
});
test('large diff has bounded work and still preserves both full texts', () => {
  assert.equal(typeof mod.diffLines, 'function');
  const old = Array.from({length: 2000}, (_, i) => '旧' + i).join('\n');
  const current = Array.from({length: 2000}, (_, i) => '新' + i).join('\n');
  const diff = mod.diffLines(old, current);
  assert.equal(diff.filter(row => row.kind !== 'add').map(row => row.text).join('\n'), old);
  assert.equal(diff.filter(row => row.kind !== 'remove').map(row => row.text).join('\n'), current);
});
test('invalid or private browser preference fields cannot enter stored UI settings',()=>{
  let stored='{"theme":"dark","leftWidth":9000,"rightWidth":-30,"content":"PRIVATE","token":"SECRET"}';
  const storage={getItem:()=>stored,setItem:(_,value)=>{stored=value;}};
  const value=layout.readPreferences(storage);
  assert.equal(value.leftWidth,340);assert.equal(value.rightWidth,220);
  layout.writePreferences({...value,content:'NOVEL',token:'KEY'},storage);
  assert.doesNotMatch(stored,/PRIVATE|SECRET|NOVEL|KEY|content|token/);
  stored='broken JSON';
  assert.equal(layout.readPreferences(storage).theme,'dark');
});
test('conversation preparation isolates requests and stable references per project',()=>{
  assert.equal(typeof mod.PromptStore,'function','缺少按项目隔离的未发送需求');
  const store=new mod.PromptStore();
  store.set('a',{text:'\n请求甲  ',chapter:'id-1',character:'person-1',world:true,revision:3});
  store.set('b',{text:'请求乙',chapter:'id-2',world:false,revision:9});
  assert.equal(store.get('a').text,'\n请求甲  ');
  store.set('a',{...store.get('a'),text:'改后的请求'});
  assert.equal(store.get('a').revision,3,'Typing must not silently advance reviewed context');
  assert.equal(store.get('b').chapter,'id-2');
  assert.equal(store.hasText,true);
  store.clear('a');assert.equal(store.get('a').text,'');assert.equal(store.get('b').text,'请求乙');
  store.clear('b');assert.equal(store.hasText,false);
});
