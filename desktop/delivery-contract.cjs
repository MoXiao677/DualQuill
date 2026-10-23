'use strict';
// Offline metadata checks. This module never downloads, installs, signs or publishes.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const hash=file=>crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const inside=(parent,child)=>{if(process.platform==='win32'){parent=parent.toLowerCase();child=child.toLowerCase();}return child===parent||child.startsWith(parent+path.sep);};
function noLinks(file){
  let current=path.resolve(file);
  while(true){
    if(fs.existsSync(current)&&fs.lstatSync(current).isSymbolicLink())throw Error('Symlink/junction input rejected: '+current);
    const parent=path.dirname(current);if(parent===current)break;current=parent;
  }
}
function storageDirectory(directory,project){
  const target=path.resolve(directory),root=path.resolve(project);
  noLinks(target);
  if(inside(target,root)||inside(root,target)&&!inside(path.join(root,'desktop','.cache'),target))throw Error('Build stage/output overlaps source tree');
  const frozen=path.join(root,'desktop','.cache','stage');
  if(inside(frozen,target))throw Error('Frozen preview stage is forbidden');
  return target;
}
function exclusiveDirectory(directory,project){
  const target=storageDirectory(directory,project),frozen=path.join(path.resolve(project),'desktop','.cache','stage');
  if(inside(frozen,target)||inside(target,frozen))throw Error('Frozen preview stage is forbidden');
  if(fs.existsSync(target))throw Error('Build stage/output must be new and empty');
  return target;
}
function inventory(project){
  const desktop=path.join(project,'desktop'),pkg=JSON.parse(fs.readFileSync(path.join(desktop,'package.json'))),lock=JSON.parse(fs.readFileSync(path.join(desktop,'package-lock.json')));
  if(pkg.private!==true||pkg.license!=='MIT'||lock.lockfileVersion!==3||lock.version!==pkg.version||lock.packages[''].version!==pkg.version)throw Error('Application version/private license declaration differs from lock');
  const applicationLicense=fs.readFileSync(path.join(project,'LICENSE'),'utf8');
  if(!applicationLicense.startsWith('MIT License')||!applicationLicense.includes('Permission is hereby granted, free of charge')||!applicationLicense.includes('The above copyright notice and this permission notice shall be included'))throw Error('Application MIT license text is missing or invalid');
  const pythonProject=fs.readFileSync(path.join(project,'pyproject.toml'),'utf8');
  if(!pythonProject.includes(`version = "${pkg.version}"`))throw Error('Python application version differs from desktop');
  if(JSON.stringify(pkg.devDependencies)!==JSON.stringify(lock.packages[''].devDependencies))throw Error('Declared dependency lock mismatch');
  const packages=Object.entries(lock.packages).filter(([name])=>name).sort(([a],[b])=>a.localeCompare(b)).map(([name,item])=>{
    if(!/^https:\/\/registry\.npmjs\.org\//.test(item.resolved||'')||!/^sha512-[A-Za-z0-9+/]+=*$/.test(item.integrity||''))throw Error('Untrusted or unhashed npm lock input: '+name);
    if(typeof item.license!=='string'||!item.license)throw Error('Missing dependency license declaration: '+name);
    return {path:name,version:item.version,license:item.license,resolved:item.resolved,integrity:item.integrity};
  });
  for(const [name,version] of Object.entries(pkg.devDependencies))if(lock.packages['node_modules/'+name]?.version!==version)throw Error('Dependency version not pinned: '+name);
  const inputs=JSON.parse(fs.readFileSync(path.join(desktop,'inputs.json')));
  const notices=fs.readFileSync(path.join(desktop,'THIRD-PARTY-NOTICES.txt'),'utf8');
  if(!notices.includes('Application: MIT License.')||!notices.includes('resources/LICENSE.application.txt')||notices.includes('UNLICENSED'))throw Error('Application notice license declaration differs');
  if(!notices.includes('desktop '+pkg.version))throw Error('Application notices version differs');
  if(inputs.length!==2||new Set(inputs.map(x=>x.name)).size!==2)throw Error('Exactly two locked runtime inputs required');
  for(const item of inputs){
    const expected=item.name==='electron'?`electron-v${item.version}-win32-x64.zip`:item.name==='python'?`python-${item.version}-embed-amd64.zip`:null;
    if(item.file!==expected||!/^\d+\.\d+\.\d+$/.test(item.version)||!/^[a-f0-9]{64}$/.test(item.sha256))throw Error('Invalid runtime file/version/hash');
    const url=new URL(item.url);
    if(url.username||url.password||url.search||url.hash||url.protocol!=='https:'||!['github.com','www.python.org'].includes(url.hostname))throw Error('Invalid official runtime origin');
    if(item.name==='electron'&&(item.version!==pkg.devDependencies.electron||url.href!==`https://github.com/electron/electron/releases/download/v${item.version}/${item.file}`))throw Error('Electron runtime origin/version mismatch');
    if(item.name==='python'&&url.href!==`https://www.python.org/ftp/python/${item.version}/${item.file}`)throw Error('Python runtime origin/version mismatch');
    if(!notices.includes((item.name==='electron'?'Electron ':'CPython ')+item.version))throw Error('Runtime notices version differs');
    if(item.download){const mirror=new URL(item.download);if(mirror.protocol!=='https:'||mirror.hostname!=='cdn.npmmirror.com'||mirror.username||mirror.password||mirror.search||mirror.hash||!mirror.pathname.endsWith('/'+item.file))throw Error('Unapproved runtime mirror');}
  }
  const winCfg=pkg.build.win||{};const iconOnlyUnsigned=winCfg.signExecutable===false&&winCfg.signAndEditExecutable===true&&typeof winCfg.icon==='string'&&winCfg.icon.length>0;const legacyUnsigned=winCfg.signAndEditExecutable===false;if(pkg.build.publish!==null||pkg.build.forceCodeSigning!==false||!(iconOnlyUnsigned||legacyUnsigned)||pkg.build.nsis.runAfterFinish!==false||pkg.build.nsis.perMachine!==false)throw Error('Unsigned local packaging defaults changed');
  return {format:1,version:pkg.version,application_license:pkg.license,public_distribution_approved:false,inputs,packages};
}
function sourceBinding(project,files){
  const names=[...new Set([...files,'LICENSE','desktop/main.cjs','desktop/preload.cjs','desktop/security.cjs','desktop/backend.cjs','desktop/localization.cjs','desktop/build.cjs','desktop/delivery-contract.cjs','desktop/package.json','desktop/package-lock.json','desktop/inputs.json','desktop/THIRD-PARTY-NOTICES.txt','pyproject.toml'])].sort();
  const entries=names.map(file=>{const target=path.resolve(project,file);if(!inside(path.resolve(project),target)||file.includes('\\')||file.split('/').includes('..'))throw Error('Invalid source binding path');noLinks(target);return {file,sha256:hash(target)};});
  return {algorithm:'sha256',digest:crypto.createHash('sha256').update(JSON.stringify(entries)).digest('hex'),files:entries};
}
function verifyBinding(project,binding,files=binding.files.map(x=>x.file)){
  const actual=sourceBinding(project,files);
  if(JSON.stringify(actual)!==JSON.stringify(binding))throw Error('Build source changed after binding');
  return actual;
}
function verifyResources(stage,manifest){
  const expected=manifest.source;
  if(!Array.isArray(expected)||!expected.length)throw Error('Empty staged source manifest');
  for(const entry of expected){
    const target=path.resolve(stage,'backend',entry.file);
    if(!inside(path.resolve(stage,'backend'),target)||entry.file.includes('\\')||entry.file.split('/').includes('..'))throw Error('Staged source path traversal');
    noLinks(target);if(hash(target)!==entry.sha256)throw Error('Staged source bytes changed: '+entry.file);
    if(!manifest.binding.files.some(item=>item.file===entry.file&&item.sha256===entry.sha256))throw Error('Staged file not bound to source');
  }
  const actual=[];
  function walk(directory){for(const entry of fs.readdirSync(directory,{withFileTypes:true})){const target=path.join(directory,entry.name);noLinks(target);if(entry.isDirectory())walk(target);else actual.push(path.relative(path.join(stage,'backend'),target).split(path.sep).join('/'));}}
  walk(path.join(stage,'backend'));
  if(JSON.stringify(actual.sort())!==JSON.stringify(expected.map(x=>x.file).sort()))throw Error('Unexpected staged source files');
  return true;
}
module.exports={inventory,sourceBinding,verifyBinding,verifyResources,exclusiveDirectory,storageDirectory,noLinks,inside};
if(require.main===module){
  try{const project=path.resolve(__dirname,'..'),files=require('./build.cjs').sourceFiles(project);process.stdout.write(JSON.stringify({inventory:inventory(project),binding:sourceBinding(project,files)},null,2)+'\n');}
  catch(error){process.stderr.write(String(error.message)+'\n');process.exitCode=1;}
}
