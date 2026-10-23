const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const target=path.join(__dirname,'../desktop/build.cjs');
const build=fs.existsSync(target)?require(target):{};
test('runtime source allowlist excludes fiction, credentials, caches and test fixtures',()=>{
  assert.equal(typeof build.sourceFiles,'function','packaging resource allowlist is missing');
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'novel-s7-allowlist-'));
  for(const file of ['src/novel_writer/domain/models.py','src/novel_writer/ui/static/app.js',
    'src/novel_writer/ui/static/writing_candidates.js',
    'src/novel_writer/ui/static/console_usage.js',
    'src/novel_writer/ui/static/not-allowed.js','src/novel_writer/ui/static/secret.dpapi',
    'src/novel_writer/storage/schema_v1.json','src/novel_writer/__pycache__/x.pyc',
    'data/novels.sqlite3','tests/fixtures/private.json','.git/config']){
    fs.mkdirSync(path.dirname(path.join(root,file)),{recursive:true});fs.writeFileSync(path.join(root,file),'fictional');
  }
  assert.deepEqual(build.sourceFiles(root).sort(),['src/novel_writer/domain/models.py','src/novel_writer/storage/schema_v1.json','src/novel_writer/ui/static/app.js','src/novel_writer/ui/static/console_usage.js','src/novel_writer/ui/static/writing_candidates.js']);
});
test('binary integrity rejects altered bytes before extraction',()=>{
  assert.equal(typeof build.verifyFile,'function','binary integrity check is missing');
  const file=path.join(fs.mkdtempSync(path.join(os.tmpdir(),'novel-s7-integrity-')),'image.zip');fs.writeFileSync(file,'modified binary');
  assert.throws(()=>build.verifyFile(file,'0'.repeat(64)),/integrity|校验/);
});

test('every relative renderer module import is included by the desktop source allowlist',()=>{
  const root=path.join(__dirname,'..'),included=new Set(build.sourceFiles(root).map(p=>p.replaceAll('\\','/')));
  const security=require('../desktop/security.cjs');
  for(const file of security.ASSETS.values()){
    if(!file.endsWith('.js'))continue;
    const source='src/novel_writer/ui/static/'+file;
    assert.ok(included.has(source),'missing renderer asset '+source);
    const text=fs.readFileSync(path.join(root,source),'utf8');
    for(const match of text.matchAll(/(?:\bfrom\s*|\bimport\s*)['"](\.\.?\/[^'"]+)['"]/g)){
      const imported=path.posix.normalize(path.posix.join(path.posix.dirname(source),match[1]));
      assert.ok(included.has(imported),source+' imports unpackaged module '+imported);
    }
  }
});
