const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..'),desktop=path.join(root,'desktop');
const {sourceFiles}=require(path.join(desktop,'build.cjs'));
test('packaging source allowlist includes every new UI asset and no tests/data',()=>{
 const files=sourceFiles(root);
 for(const name of ['console.js','chapter_planning.js','scene_expansion.js','rules_scope.js','migration.js','chapter_writing.js'])assert.ok(files.some(v=>v.endsWith('/static/'+name)),name);
 assert.ok(!files.some(v=>v.includes('/tests/')||v.includes('/data/')||v.includes('/.git/')));
 assert.ok(!files.some(v=>v.includes('__pycache__')||v.includes('author-preview')));
});
test('build stage is assembled independently and package metadata is version locked',()=>{
 const build=fs.readFileSync(path.join(desktop,'build.cjs'),'utf8'),pkg=JSON.parse(fs.readFileSync(path.join(desktop,'package.json'),'utf8')),lock=JSON.parse(fs.readFileSync(path.join(desktop,'package-lock.json'),'utf8'));
 assert.doesNotMatch(build,/path\.join\(cache,'stage','runtime'\)/);
 assert.match(build,/build-stage-/);
 assert.equal(pkg.version,'0.4.14');assert.equal(lock.version,'0.4.14');assert.equal(pkg.build.extraResources.length,0);
 assert.ok(fs.readFileSync(path.join(desktop,'THIRD-PARTY-NOTICES.txt'),'utf8').includes('0.4.14'));
 const inputs=JSON.parse(fs.readFileSync(path.join(desktop,'inputs.json'),'utf8'));assert.equal(inputs.find(v=>v.name==='electron').version,'44.7.2');assert.equal(inputs.find(v=>v.name==='python').version,'3.14.8');
});
