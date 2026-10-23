const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {stage,open}=require('./electron-local-harness.cjs');
const out=process.env.NOVEL_WRITER_ARTIFACTS||fs.mkdtempSync(path.join(os.tmpdir(),'novel-c03-evidence-'));
const report={status:'running',checks:[],providerCalls:0,errors:[],external:[]};
(async()=>{
 fs.mkdirSync(out,{recursive:true});const shell=stage(),profile=fs.mkdtempSync(path.join(os.tmpdir(),'novel-c03-profile-'));report.profile=profile;report.shell=shell;let ui;
 try{
  ui=await open({shell,profile,report});await ui.nav('settings');
  const form='#custom-provider-form';await ui.fill(form+' [name="name"]','临时虚构管理测试');await ui.fill(form+' [name="base_url"]','https://fiction.example/v1');await ui.fill(form+' [name="model_id"]','fiction-model');await ui.fill(form+' [name="api_key"]','fiction-ui-not-a-real-credential');await ui.click(form+' button[type="submit"]');
  await ui.wait("document.querySelector('#provider-management [data-manage-connection]')");await ui.idle();
  const id=await ui.evaluate("document.querySelector('#provider-management [data-manage-connection]').dataset.manageConnection"),card='[data-manage-connection="'+id+'"]';
  await ui.click(card+' [data-connection-action="disable"]');await ui.wait(`document.querySelector('${card} [data-connection-action="enable"]')`);await ui.idle();
  let settings=await ui.evaluate("fetch('/api/settings').then(r=>r.json())");assert.equal(settings.connections[id].enabled,false);report.checks.push('UI saves a fictional credential in isolated profile and disables individual connection');
  await ui.click(card+' [data-connection-action="enable"]');await ui.wait(`document.querySelector('${card} [data-connection-action="disable"]')`);await ui.idle();
  await ui.fill(card+' [data-local-interval]','1000');await ui.fill(card+' [data-local-rpm]','5');await ui.click(card+' [data-connection-action="limits"]');await ui.idle();await ui.wait(`document.querySelector('${card} [data-local-interval]')?.value==='1000'`);report.checks.push('UI enables connection and persists per-connection local rate limits');
  await ui.fill('#manual-cost-estimate [name="input_per_million"]','2');await ui.fill('#manual-cost-estimate [name="output_per_million"]','4');await ui.click('#manual-cost-estimate button[type="submit"]');await ui.wait("document.querySelector('#manual-estimate-result')?.textContent.includes('0.006 USD')");
  assert.match(await ui.evaluate("document.querySelector('#provider-catalog').innerText"),/真实价格：未知/);report.checks.push('catalog labels source/date/unknown prices and manual estimate performs no model request');
  await ui.evaluate('window.confirm=()=>true');await ui.click(card+' [data-connection-action="delete_credentials"]');await ui.idle();await ui.wait(`document.querySelector('${card}')?.innerText.includes('无凭据')`);
  await ui.close();ui=await open({shell,profile,report});await ui.nav('settings');settings=await ui.evaluate("fetch('/api/settings').then(r=>r.json())");assert.equal(settings.connections[id].key_configured,false);assert.equal(settings.connections[id].enabled,false);assert.equal(settings.connections[id].requests_per_minute,5);report.checks.push('explicit credential deletion disables connection and persists after close/reopen');
  const shot=await ui.send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(out,'provider-management.png'),Buffer.from(shot.data,'base64'));
  assert.deepEqual(report.errors,[]);assert.deepEqual(report.external,[]);report.status='passed';
 }catch(error){report.status='failed';report.error=String(error.stack||error);if(ui)try{report.body=await ui.evaluate('document.body.innerText.slice(-9000)');}catch{}throw error;}
 finally{if(ui)await ui.close();fs.writeFileSync(path.join(out,'provider-management-report.json'),JSON.stringify(report,null,2));}
})().then(()=>process.stdout.write(JSON.stringify(report)+'\n')).catch(error=>{process.stderr.write(String(error.stack||error)+'\n');process.exitCode=1;});
