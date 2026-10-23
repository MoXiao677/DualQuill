import test from 'node:test';
import assert from 'node:assert/strict';
import {renderModelPurposeGuide,providerDisplayName} from '../src/novel_writer/ui/static/provider_views.js';
import {text} from '../desktop/localization.cjs';
test('public settings explain model purposes and retain author-supplied connection names',()=>{
 const html=renderModelPurposeGuide();
 for(const purpose of ['构思与大纲','正文与润色','审核与反馈','文风分析与短试写','公开样本搜索'])assert.ok(html.includes(purpose));
 assert.doesNotMatch(html,/GG|Catiecli|Odys|https?:/);
 assert.equal(providerDisplayName({id:'gg',name:'historical brand'}),'旧版连接 1');
 assert.equal(providerDisplayName({id:'own-connection',name:'Author English 保存 / Cancel'}),'Author English 保存 / Cancel');
});
test('native application dialogs safely fall back to Chinese for old English preferences',()=>{
 assert.equal(text('en-US','unsavedTitle'),'保留未保存修改');
 assert.equal(text('en-US','keep'),'继续编辑');assert.equal(text('en-US','discard'),'放弃未保存并关闭');
});
