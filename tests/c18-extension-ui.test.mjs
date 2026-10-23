import test from 'node:test';
import assert from 'node:assert/strict';
import {renderExtensions,bindExtensions} from '../src/novel_writer/ui/static/comparison_views.js';

const workspace={document:{project:{id:'fiction-project'}}};
const version={id:'fiction-version',template_id:'fiction-template',revision:1,
  template:{name:'<fiction>',permissions:['read_saved_source'],capability:'saved-text-reference'}};
const listing={revision:8,versions:[version],authorizations:[{version_id:version.id,enabled:false,policy_revision:2}]};
function ui(){
  const fields=new Map([
    ['#extension-json',{value:'{}',addEventListener(){}}],
    ['[name="template_family"]',{value:'',addEventListener(){}}],
    ['#extension-import',{disabled:true}],['#extension-status',{textContent:''}],
    ['[data-extension-consent="fiction-version"]',{checked:false}]
  ]);
  return {fields,querySelector(selector){assert.ok(fields.has(selector),selector);return fields.get(selector);},addEventListener(name,handler){this[name]=handler;}};
}
const click=(root,dataset)=>root.click({target:{closest(){return {dataset};}},stopPropagation(){}});
test('template cards show default denial, explicit permissions and retained read-only history',()=>{
  const html=renderExtensions(workspace,listing);
  assert.ok(html.includes('&lt;fiction&gt;'));assert.ok(!html.includes('<fiction>'));
  assert.match(html,/本机未启用/);assert.match(html,/read_saved_source/);
  assert.match(html,/data-template-reference="fiction-version" disabled/);
  const upgraded=renderExtensions(workspace,{...listing,versions:[version,{...version,id:'new-version',revision:2}]});
  assert.match(upgraded,/只读历史/);
  assert.ok(!upgraded.includes('data-template-authorize="fiction-version"'));
  assert.match(upgraded,/导入目标/);
});
test('enable requires unchecked-by-default consent and sends exactly registered permissions',async t=>{
  const root=ui(),requests=[];let refreshed=0;
  const original=globalThis.fetch;t.after(()=>{globalThis.fetch=original;});
  globalThis.fetch=async(url,options)=>{requests.push({url,body:JSON.parse(options.body)});return {ok:true,json:async()=>({enabled:true})};};
  bindExtensions(root,workspace,listing,'fiction-chapter',async()=>{refreshed++;});
  await click(root,{templateAuthorize:version.id,enable:'true'});
  assert.equal(requests.length,0);assert.match(root.fields.get('#extension-status').textContent,/勾选/);
  root.fields.get('[data-extension-consent="fiction-version"]').checked=true;
  await click(root,{templateAuthorize:version.id,enable:'true'});
  assert.equal(requests.length,1);assert.equal(refreshed,1);
  assert.equal(requests[0].url,'/api/projects/fiction-project/extensions/authorization');
  assert.deepEqual(requests[0].body.permissions,['read_saved_source']);
  assert.equal(requests[0].body.expected_policy_revision,2);
  assert.equal(requests[0].body.expected_revision,8);
});
test('disable revokes permissions without an enable consent',async t=>{
  const root=ui(),requests=[],original=globalThis.fetch;t.after(()=>{globalThis.fetch=original;});
  globalThis.fetch=async(url,options)=>{requests.push(JSON.parse(options.body));return {ok:true,json:async()=>({enabled:false})};};
  bindExtensions(root,workspace,{...listing,authorizations:[{version_id:version.id,enabled:true,policy_revision:3}]},'fiction-chapter',async()=>{});
  await click(root,{templateAuthorize:version.id,enable:'false'});
  assert.equal(requests[0].enabled,false);assert.deepEqual(requests[0].permissions,[]);
});
