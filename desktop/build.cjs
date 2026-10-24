'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {spawnSync}=require('node:child_process');
const {ASSETS}=require('./security.cjs');
const contract=require('./delivery-contract.cjs');
const root=path.resolve(__dirname,'..'),cache=path.resolve(process.env.NOVEL_WRITER_BUILD_CACHE||path.join(__dirname,'.cache'));
function sourceFiles(project){
  const result=[],staticNames=new Set(ASSETS.values());
  function walk(directory){
    if(!fs.existsSync(directory))return;
    for(const entry of fs.readdirSync(directory,{withFileTypes:true})){
      if(entry.isSymbolicLink())throw Error('Source symlinks are not packaged');
      const file=path.join(directory,entry.name);
      if(entry.isDirectory()){if(entry.name!=='__pycache__')walk(file);continue;}
      if(entry.name.endsWith('.py')||['schema_v1.json','schema_v2.json'].includes(entry.name)&&path.basename(directory)==='storage'||path.basename(directory)==='static'&&staticNames.has(entry.name))result.push(path.relative(project,file).split(path.sep).join('/'));
    }
  }
  walk(path.join(project,'src','novel_writer'));
  const vendor=path.join(project,'src','pypdf');
  if(fs.existsSync(vendor))walk(vendor);
  for(const file of ['src/pypdf/LICENSE','src/pypdf/py.typed'])if(fs.existsSync(path.join(project,file)))result.push(file);
  return result.sort();
}
function verifyFile(file,expected){
  const actual=crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
  if(!/^[a-f0-9]{64}$/.test(expected)||actual!==expected)throw Error('Binary integrity 校验失败: '+path.basename(file));
  return actual;
}
async function obtain(input){
  const file=path.join(cache,input.file);
  contract.noLinks(file);
  if(!fs.existsSync(file)){
    let last;
    for(const url of [...new Set([input.url,input.download].filter(Boolean))]){
      try{
        const response=await fetch(url,{signal:AbortSignal.timeout(180000)});if(!response.ok)throw Error('HTTP '+response.status);
        fs.writeFileSync(file,Buffer.from(await response.arrayBuffer()));verifyFile(file,input.sha256);last=null;break;
      }catch(error){last=error;if(fs.existsSync(file))fs.unlinkSync(file);}
    }
    if(last)throw last;
  }
  verifyFile(file,input.sha256);return file;
}
function expand(file,destination){
  fs.mkdirSync(destination,{recursive:true});
  const quote=value=>"'"+value.replaceAll("'","''")+"'";
  const result=spawnSync(path.join(process.env.SystemRoot||'C:/Windows','System32','WindowsPowerShell','v1.0','powershell.exe'),['-NoProfile','-NonInteractive','-Command','Expand-Archive -LiteralPath '+quote(file)+' -DestinationPath '+quote(destination)+' -Force'],{windowsHide:true,stdio:'pipe'});
  if(result.status!==0)throw Error('Archive extraction failed');
}
function stagePath(){
  const argument=process.argv.find(value=>value.startsWith('--stage='));
  const requested=process.env.NOVEL_WRITER_BUILD_STAGE||(argument?argument.slice(8):'');
  if(requested){
    const stage=path.resolve(requested);
    return contract.exclusiveDirectory(stage,root);
  }
  return path.join(cache,'build-stage-'+crypto.randomBytes(6).toString('hex'));
}
async function prepare(requestedStage){
  const inventory=contract.inventory(root);
  const files=sourceFiles(root),binding=contract.sourceBinding(root,files);
  contract.storageDirectory(cache,root);
  fs.mkdirSync(cache,{recursive:true});
  const inputs=inventory.inputs;
  const official=require('./node_modules/electron/checksums.json');
  const electron=inputs.find(item=>item.name==='electron');
  if(official[electron.file]!==electron.sha256)throw Error('Electron lock differs from official npm checksum');
  const stage=requestedStage||stagePath();contract.exclusiveDirectory(stage,root);fs.mkdirSync(stage);
  // The runtime is assembled from the locked embeddable zip, never from the frozen preview staging tree.
  for(const input of inputs){
    const file=await obtain(input);
    if(input.name==='electron'){
      // Always unpack the verified archive into this new stage, never trust an existing dist.
      expand(file,path.join(stage,'electron'));
    }else if(input.name==='python'){
      const directory=path.join(stage,'runtime');
      expand(file,directory);
      fs.writeFileSync(path.join(directory,'python314._pth'),'python314.zip\n.\n../backend/src\n');
    }else throw Error('Unknown runtime input');
  }
  const backend=path.join(stage,'backend');
  if(!backend.startsWith(stage+path.sep))throw Error('Unsafe staging directory');
  const manifest=[];
  for(const relative of files){
    const from=path.join(root,relative),to=path.join(backend,relative);fs.mkdirSync(path.dirname(to),{recursive:true});fs.copyFileSync(from,to);
    manifest.push({file:relative,sha256:crypto.createHash('sha256').update(fs.readFileSync(to)).digest('hex')});
  }
  contract.verifyBinding(root,binding,sourceFiles(root));
  contract.verifyResources(stage,{source:manifest,binding});
  fs.writeFileSync(path.join(stage,'resource-manifest.json'),JSON.stringify({format:2,inputs,source:manifest,binding},null,2));
  fs.writeFileSync(path.join(stage,'dependency-inventory.json'),JSON.stringify(inventory,null,2));
  return {stage,manifest,binding};
}
async function main(){
  const outputArgument=process.argv.find(value=>value.startsWith('--output='));
  const output=contract.exclusiveDirectory(process.env.NOVEL_WRITER_BUILD_OUTPUT||(outputArgument?outputArgument.slice(9):path.join(cache,'build-output-'+crypto.randomBytes(6).toString('hex'))),root);
  const requestedStage=stagePath();
  if(contract.inside(requestedStage,output)||contract.inside(output,requestedStage))throw Error('Build stage and output must be disjoint');
  const prepared=await prepare(requestedStage);
  const stage=prepared.stage;
  if(process.argv.includes('--prepare-only'))return;
  for(const key of Object.keys(process.env))if(/(^|_)CSC_|^CSC_/i.test(key))delete process.env[key];
  process.env.CSC_IDENTITY_AUTO_DISCOVERY='false';
  process.env.ELECTRON_BUILDER_CACHE=path.join(cache,'builder');
  process.env.ELECTRON_CACHE=path.join(cache,'electron');
  const {build,Platform,Arch}=require('electron-builder');
  contract.verifyBinding(root,prepared.binding,sourceFiles(root));
  contract.verifyResources(stage,{source:prepared.manifest,binding:prepared.binding});
  const config={directories:{output},electronDist:path.join(stage,'electron'),electronVersion:require('./package.json').devDependencies.electron,extraResources:[
    {from:path.join(stage,'runtime'),to:'runtime',filter:['**/*']},
    {from:path.join(stage,'backend'),to:'backend',filter:['**/*']},
    {from:path.join(root,'LICENSE'),to:'LICENSE.application.txt'},
    {from:path.join(__dirname,'THIRD-PARTY-NOTICES.txt'),to:'THIRD-PARTY-NOTICES.txt'},
    {from:path.join(stage,'resource-manifest.json'),to:'resource-manifest.json'},
    {from:path.join(stage,'dependency-inventory.json'),to:'dependency-inventory.json'},
  ]};
  const targets=process.argv.includes('--dir')?['dir']:process.argv.includes('--zip-only')?['zip']:['zip','nsis'];
  await build({projectDir:__dirname,targets:Platform.WINDOWS.createTarget(targets,Arch.x64),config,publish:'never'});
  contract.verifyBinding(root,prepared.binding,sourceFiles(root));
  contract.verifyResources(stage,{source:prepared.manifest,binding:prepared.binding});
  if(!process.argv.includes('--dir')){
    const pkg=require('./package.json'),version=pkg.version,productName=pkg.build.productName;
    const zip=path.join(output,productName+'-'+version+'-win.zip');
    if(!fs.existsSync(zip)||fs.statSync(zip).size<1024*1024)throw Error('Portable zip was not produced');
    if(!process.argv.includes('--zip-only')&&!fs.existsSync(path.join(output,productName+' Setup '+version+'.exe')))throw Error('NSIS installer was not produced');
  }
  process.stdout.write(JSON.stringify({stage,output,source_digest:prepared.binding.digest,sourceFiles:prepared.manifest.length,artifacts:fs.readdirSync(output).filter(name=>name.startsWith(require('./package.json').build.productName))})+'\n');
}
module.exports={sourceFiles,verifyFile,prepare,stagePath};
if(require.main===module)main().catch(error=>{process.stderr.write(String(error.stack||error)+'\n');process.exitCode=1;});
