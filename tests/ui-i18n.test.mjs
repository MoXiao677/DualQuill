import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const file=new URL('../src/novel_writer/ui/static/i18n.js',import.meta.url);
test('Chinese-only UI ignores an old English preference and never rewrites author text',async()=>{
  assert.ok(fs.existsSync(file),'desktop language resources and preference are missing');
  const original=JSON.stringify({version:1,uiLanguage:'en-US'}),values=new Map([['novel-writer.preferences',original]]);globalThis.localStorage={getItem:key=>values.get(key)||null,setItem:(key,value)=>values.set(key,value)};
  globalThis.document={documentElement:{lang:'zh-CN'},body:{textContent:'作者正文 unchanged'}};
  try{
    const module=await import('data:text/javascript;base64,'+fs.readFileSync(file).toString('base64'));
    assert.equal(module.getLanguage(),'zh-CN');module.setLanguage('en-US');
    assert.equal(module.getLanguage(),'zh-CN');assert.equal(module.t('desktop.enable'),'启用本次会话的模型');
    assert.equal(document.documentElement.lang,'zh-CN');assert.equal(document.body.textContent,'作者正文 unchanged');
    assert.equal(values.get('novel-writer.preferences'),original);
    module.setLanguage('zh-CN');assert.equal(module.t('desktop.enable'),'启用本次会话的模型');
  }finally{delete globalThis.localStorage;delete globalThis.document;}
});
