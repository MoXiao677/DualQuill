'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const root=path.resolve(__dirname,'..'),contract=require('../desktop/delivery-contract.cjs'),build=require('../desktop/build.cjs');
function temporary(t){const dir=fs.mkdtempSync(path.join(os.tmpdir(),'fiction-c18-'));t.after(()=>fs.rmSync(dir,{force:true,recursive:true}));return dir;}
function fixture(t){
  const project=path.join(temporary(t),'project');
  const binding=contract.sourceBinding(root,[]);
  for(const {file} of binding.files){const dest=path.join(project,file);fs.mkdirSync(path.dirname(dest),{recursive:true});fs.copyFileSync(path.join(root,file),dest);}
  return project;
}
function change(project,file,mutate){const target=path.join(project,file),value=JSON.parse(fs.readFileSync(target));mutate(value);fs.writeFileSync(target,JSON.stringify(value));}
test('all declared dependencies have locked origins, integrity and license metadata',()=>{
  const inventory=contract.inventory(root);assert.equal(inventory.packages.length,284);
  assert.equal(inventory.inputs.length,2);assert.equal(inventory.application_license,'MIT');
  assert.equal(inventory.public_distribution_approved,false);
  assert.ok(inventory.packages.every(p=>p.integrity.startsWith('sha512-')&&p.license));
});
test('runtime path traversal, altered source/version and npm origins fail closed',t=>{
  const cases=[['desktop/inputs.json',x=>x[0].file='../payload.zip'],
    ['desktop/inputs.json',x=>x[0].url='https://fiction.invalid/runtime.zip'],
    ['desktop/inputs.json',x=>x[1].download='https://cdn.npmmirror.com/../python.zip?token=fiction'],
    ['desktop/inputs.json',x=>x[0].sha256='0'],
    ['desktop/package-lock.json',x=>x.version='0.0.0'],
    ['desktop/package-lock.json',x=>x.packages['node_modules/electron'].resolved='file:///private'],
    ['desktop/package-lock.json',x=>delete x.packages['node_modules/electron'].license],
    ['desktop/package-lock.json',x=>x.packages[''].devDependencies.electron='0.0.0']];
  for(const [file,mutate] of cases){const project=fixture(t);change(project,file,mutate);assert.throws(()=>contract.inventory(project));}
});
test('binding detects source edits and newly included source files',t=>{
  const project=fixture(t),binding=contract.sourceBinding(project,[]);
  assert.deepEqual(contract.verifyBinding(project,binding),binding);
  fs.appendFileSync(path.join(project,'desktop/main.cjs'),'\n// fictional edit');
  assert.throws(()=>contract.verifyBinding(project,binding),/changed/);
  const other=fixture(t),frozen=contract.sourceBinding(other,[]),added=path.join(other,'src/novel_writer/new.py');
  fs.mkdirSync(path.dirname(added),{recursive:true});fs.writeFileSync(added,'# fictional');
  assert.throws(()=>contract.verifyBinding(other,frozen,build.sourceFiles(other)),/changed/);
});
test('stage/output cannot reuse directories, source paths, frozen stage or junctions',t=>{
  const parent=temporary(t),project=path.join(parent,'project');fs.mkdirSync(project);
  for(const candidate of [project,parent,path.join(project,'src'),path.join(project,'dist'),path.join(project,'desktop/.cache/stage'),path.join(project,'desktop/.cache/stage/child')])assert.throws(()=>contract.exclusiveDirectory(candidate,project));
  const stage=path.join(parent,'stage');assert.equal(contract.exclusiveDirectory(stage,project),stage);fs.mkdirSync(stage);
  if(process.platform==='win32')assert.throws(()=>contract.exclusiveDirectory(path.join(project.toUpperCase(),'Src','new-stage'),project),/overlaps/);
  assert.throws(()=>contract.storageDirectory(path.join(project,'src','cache'),project),/overlaps/);
  assert.throws(()=>contract.exclusiveDirectory(stage,project),/new and empty/);
  const link=path.join(parent,'junction');fs.symlinkSync(stage,link,process.platform==='win32'?'junction':'dir');
  assert.throws(()=>contract.exclusiveDirectory(path.join(link,'nested'),project),/Symlink/);
});
test('staged files must match source binding and reject traversal or corruption',t=>{
  const stage=temporary(t),file='src/novel_writer/fiction.py',target=path.join(stage,'backend',file);
  fs.mkdirSync(path.dirname(target),{recursive:true});fs.writeFileSync(target,'# fictional');
  const sha=require('node:crypto').createHash('sha256').update('# fictional').digest('hex');
  const manifest={source:[{file,sha256:sha}],binding:{files:[{file,sha256:sha}]}};
  assert.equal(contract.verifyResources(stage,manifest),true);
  assert.throws(()=>contract.verifyResources(stage,{...manifest,source:[{file:'../private',sha256:sha}]}),/traversal/);
  fs.appendFileSync(target,'# corrupt');assert.throws(()=>contract.verifyResources(stage,manifest),/changed/);
});
test('NSIS local defaults prevent auto-run, machine install, signing and publishing',t=>{
  const project=fixture(t);
  for(const [section,key,value] of [['nsis','runAfterFinish',true],['nsis','perMachine',true],['win','signAndEditExecutable',true]]){
    const copy=fixture(t);change(copy,'desktop/package.json',x=>x.build[section][key]=value);assert.throws(()=>contract.inventory(copy));
  }
  change(project,'desktop/package.json',x=>x.build.publish='github');assert.throws(()=>contract.inventory(project));
});
test('CI is pinned, read-only, fictional and has no provider secrets or install/publish steps',()=>{
  const workflow=fs.readFileSync(path.join(root,'.github/workflows/c18-contracts.yml'),'utf8');
  const actions=[...workflow.matchAll(/uses:\s*([^@\s]+)@([^\s]+)/g)];
  assert.equal(actions.length,3);assert.ok(actions.every(match=>/^[a-f0-9]{40}$/.test(match[2])));
  assert.match(workflow,/contents: read/);assert.match(workflow,/persist-credentials: false/);
  assert.match(workflow,/scripts\/c18_verify\.py/);
  const executableWorkflow=workflow.split('\n').filter(line=>!/^\s*#/.test(line)).join('\n');
  assert.doesNotMatch(executableWorkflow,/\$\{\{\s*secrets\.|pull_request_target|npm (?:ci|install)|^\s*run:.*(?:publish|deploy)/m);
  const runner=fs.readFileSync(path.join(root,'scripts/c18_verify.py'),'utf8');
  assert.match(runner,/external network denied/);assert.doesNotMatch(runner,/dict\(os\.environ\)|os\.environ\.copy/);
});

 test('MIT text and notice are required and source-bound',t=>{
 const project=fixture(t);assert.ok(contract.sourceBinding(project,[]).files.some(x=>x.file==='LICENSE'));
 fs.writeFileSync(path.join(project,'LICENSE'),'fictional missing license');assert.throws(()=>contract.inventory(project),/license/i);
 const other=fixture(t);fs.appendFileSync(path.join(other,'desktop/THIRD-PARTY-NOTICES.txt'),'\nUNLICENSED');assert.throws(()=>contract.inventory(other),/license|notice/i);
 const missing=fixture(t);fs.unlinkSync(path.join(missing,'LICENSE'));assert.throws(()=>contract.inventory(missing));
 });
