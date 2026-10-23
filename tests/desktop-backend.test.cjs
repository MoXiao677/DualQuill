const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process');
const target=path.join(__dirname,'../desktop/backend.cjs');
const {Backend}=fs.existsSync(target)?require(target):{};
const {sourceFiles}=require('../desktop/build.cjs');
const root=path.resolve(__dirname,'..'),shell=fs.mkdtempSync(path.join(root,'desktop/.cache/backend-test-')),resources=path.join(shell,'.cache/stage');
function ensureRuntime(){
  if(fs.existsSync(path.join(resources,'runtime','python.exe')))return;
  const runtime=path.join(resources,'runtime'),archive=path.join(root,'desktop/.cache/python-3.14.8-embed-amd64.zip');
  fs.mkdirSync(runtime,{recursive:true});
  cp.execFileSync('powershell.exe',['-NoProfile','-NonInteractive','-Command',"Expand-Archive -LiteralPath '"+archive.replaceAll("'","''")+"' -DestinationPath '"+runtime.replaceAll("'","''")+"' -Force"],{windowsHide:true});
  fs.writeFileSync(path.join(runtime,'python314._pth'),'python314.zip\n.\n../backend/src\n');
  for(const name of sourceFiles(root)){const file=path.join(resources,'backend',name);fs.mkdirSync(path.dirname(file),{recursive:true});fs.copyFileSync(path.join(root,name),file);}
}
test('Python receives only required Windows environment and no unrelated credential sentinel',()=>{
  const {childEnvironment}=fs.existsSync(target)?require(target):{};
  assert.equal(typeof childEnvironment,'function','Python child environment allowlist is missing');
  const env=childEnvironment({SystemRoot:'C:/Windows',TEMP:'C:/fiction-temp',USERPROFILE:'C:/fiction-user',PATH:'G:/developer/node',OPENAI_API_KEY:'fiction-private-sentinel',UNRELATED_TOOL_TOKEN:'fiction-other-sentinel',PYTHONPATH:'G:/developer/python'});
  assert.equal(env.TEMP,'C:/fiction-temp');assert.equal(env.OPENAI_API_KEY,undefined);assert.equal(env.UNRELATED_TOOL_TOKEN,undefined);assert.equal(env.PYTHONPATH,undefined);
  assert.equal(JSON.stringify(env).includes('sentinel'),false);assert.equal(env.PATH.includes('developer'),false);assert.ok(env.PATH.includes('System32'));
});
test('desktop runtime temporary and user paths stay inside its selected profile',()=>{
  const {childEnvironment}=require(target),profile=path.resolve(os.tmpdir(),'novel-s7-owned-profile');
  const env=childEnvironment({SystemRoot:'C:/Windows',TEMP:'C:/unrelated-temp',APPDATA:'C:/unrelated-roaming',LOCALAPPDATA:'C:/unrelated-local',USERPROFILE:'C:/unrelated-home'},profile);
  for(const key of ['TEMP','TMP','APPDATA','LOCALAPPDATA','USERPROFILE'])assert.ok(path.resolve(env[key]).startsWith(profile),key+' escaped the profile');
  assert.equal(JSON.stringify(env).includes('unrelated-'),false);
});
test('owned embedded backend handshakes and parent close reaps it',async()=>{
  assert.equal(typeof Backend,'function','owned backend lifecycle is missing');
  ensureRuntime();
  const profile=fs.mkdtempSync(path.join(os.tmpdir(),'novel-s7-owned-'));const backend=new Backend({resources,profile});
  try {
    await backend.start();assert.ok(backend.port>0);assert.ok(backend.child.pid);
    const response=await backend.request(new Request('novel://app/api/projects'),'/api/projects');
    assert.equal(response.status,200);assert.deepEqual(await response.json(),[]);
    const pid=backend.child.pid;await backend.stop();assert.throws(()=>process.kill(pid,0));
  }finally{await backend.stop();}
});
test('startup timeout terminates only the child this instance created',async()=>{
  assert.equal(typeof Backend,'function','owned backend lifecycle is missing');
  const profile=fs.mkdtempSync(path.join(os.tmpdir(),'novel-s7-timeout-'));
  const backend=new Backend({resources,profile,startupMs:1});
  await assert.rejects(backend.start(),/启动|startup/);
  await backend.stop();assert.throws(()=>process.kill(backend.child.pid,0));
});
test('missing embedded runtime reports startup failure without PATH fallback',async()=>{
  assert.equal(typeof Backend,'function','owned backend lifecycle is missing');
  const profile=fs.mkdtempSync(path.join(os.tmpdir(),'novel-s7-missing-'));
  const backend=new Backend({resources:path.join(profile,'no-runtime'),profile});
  await assert.rejects(backend.start(),/启动|startup/);await backend.stop();
});
