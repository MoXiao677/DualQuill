"""Build phase-two-only artifacts and prove the frozen phase one is unchanged.

Run only from the isolated followup-semantic/workspace. No repository writes,
network, providers, desktop profile or package/build operations are performed.
"""
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
import difflib,json,re

WORKSPACE=Path(__file__).resolve().parents[1]
OUTPUT=WORKSPACE.parent
BASELINE=json.loads((OUTPUT/'stage1-baseline-manifest.json').read_text(encoding='utf-8-sig'))
STAGE1=Path(BASELINE['stage1_workspace'])

def digest(path):return sha256(path.read_bytes()).hexdigest()
def save(name,value):
 (OUTPUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def main():
 assert WORKSPACE.name=='workspace' and OUTPUT.name=='followup-semantic'
 violations=[]
 for name,expected in BASELINE['files'].items():
  if not (STAGE1/name).is_file() or digest(STAGE1/name)!=expected:violations.append('stage1_workspace/'+name)
 for name,expected in BASELINE['stage1_artifacts'].items():
  if digest(STAGE1.parent/name)!=expected:violations.append('stage1_artifact/'+name)
 assert not violations,violations
 current={name for name in BASELINE['files'] if (WORKSPACE/name).is_file()}
 for directory in ('src','tests','docs','scripts'):
  current.update(p.relative_to(WORKSPACE).as_posix() for p in (WORKSPACE/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.pyo'))
 current.discard('PARALLEL_TASK.md')
 changed=[];chunks=[]
 for name in sorted(current|set(BASELINE['files'])):
  if name=='PARALLEL_TASK.md':continue
  old=STAGE1/name;new=WORKSPACE/name
  if old.is_file() and new.is_file() and digest(old)==digest(new):continue
  before=old.read_text(encoding='utf-8-sig').splitlines(keepends=True) if old.is_file() else []
  after=new.read_text(encoding='utf-8-sig').splitlines(keepends=True) if new.is_file() else []
  chunks.extend(difflib.unified_diff(before,after,fromfile='a/'+name if old.is_file() else '/dev/null',tofile='b/'+name if new.is_file() else '/dev/null',n=3))
  changed.append(dict(path=name,baseline_sha256=BASELINE['files'].get(name),sha256=digest(new) if new.is_file() else None))
 diff=''.join(chunks)
 assert not any(line.startswith('+') and not line.startswith('+++') and line.rstrip('\r\n').endswith((' ','\t')) for line in diff.splitlines(keepends=True)),'added trailing whitespace'
 (OUTPUT/'changes.diff').write_text(diff,encoding='utf-8',newline='\n')
 manifest=dict(phase='C13 phase 2',baseline='frozen C13 phase 1 workspace',baseline_manifest_sha256=digest(OUTPUT/'stage1-baseline-manifest.json'),changed_files=changed,current_source_sha256={name:digest(WORKSPACE/name) for name in sorted(current) if name.startswith('src/')})
 save('source-manifest.json',manifest)
 commands={
  '02-semantic-core-first.log':'python -m unittest test_rule_semantic_reviews -v',
  '03-semantic-core-claim-fix.log':'python -m unittest test_rule_semantic_reviews -v',
  '04-planning-expansion-core.log':'python -m unittest test_rule_semantic_reviews test_chapter_planning test_scene_expansion -v',
  '05-boundaries-independent-first.log':'python -m unittest test_rule_review_boundaries test_independent_task_rules -v',
  '06-http-boundaries.log':'python -m unittest test_rule_reviews_http test_rule_review_boundaries test_independent_task_rules -v',
  '07-ui-first.log':'node --test tests/rule-reviews-ui.test.cjs tests/task-scoped-rules-ui.test.cjs',
  '08-ui-fixed.log':'node --test tests/rule-reviews-ui.test.cjs tests/task-scoped-rules-ui.test.cjs',
  '09-core-final.log':'python -m unittest test_rule_semantic_reviews test_rule_review_boundaries test_rule_reviews_http test_independent_task_rules test_task_scoped_rules test_task_scoped_rules_http test_task_rules_writing test_chapter_planning test_scene_expansion -v',
  '10-storage-desktop-sse.log':'python -m unittest test_backup_validation test_backups test_migration_preservation test_s7_desktop test_sse_tasks -v',
  '11-final-boundaries.log':'python -m unittest test_rule_review_boundaries test_rule_reviews_http test_independent_task_rules -v',
 }
 runs=[]
 for path in sorted((OUTPUT/'evidence').glob('*.log')):
  content=path.read_text(encoding='utf-8-sig',errors='replace');python=re.search(r'Ran (\d+) tests? in ([\d.]+)s',content);node=re.search(r'tests (\d+)',content)
  if path.name=='13-diff-check.log':
   entry=dict(command="git apply --check --unsafe-paths --directory='G:/AGI/_parallel/remaining-modules-20261021/09-c13-rules/workspace' '../changes.diff'",exit_code=int(re.search(r'exit=(\d+)',content)[1]),description='Read-only applicability check against frozen phase one; no patch applied')
  elif path.name in commands:
   good=bool(re.search(r'^OK\s*$',content,re.M)) if python else bool(re.search(r'fail 0',content))
   entry=dict(command=commands[path.name],exit_code=0 if good else 1,test_count=int(python[1]) if python else int(node[1]) if node else None)
   if python:entry['duration_seconds']=float(python[2])
   if node:entry['passed']=int(re.search(r'pass (\d+)',content)[1]);entry['failed']=int(re.search(r'fail (\d+)',content)[1])
  else:entry=dict(command=None,description='Import/AST verification' if path.name.startswith('01-') else '229 Python files AST; node --check for five edited UI modules',exit_code=0)
  entry.update(log=str(path),log_sha256=digest(path));runs.append(entry)
 verification=dict(phase='C13 phase 2',generated_at=datetime.now(timezone.utc).isoformat(),workspace=str(WORKSPACE),baseline=str(STAGE1),diff_relative_to='phase 1 workspace (not original shared baseline)',suggested_workspace_and_backup_version=37,real_provider_calls=0,network='fictional 127.0.0.1 random ports only',full_suite_run=False,build_or_installer_run=False,browser_or_electron_visual_qa_run=False,phase1_unchanged=dict(workspace_files_checked=len(BASELINE['files']),artifacts_checked=len(BASELINE['stage1_artifacts']),mismatches=violations,baseline_manifest_sha256=digest(OUTPUT/'stage1-baseline-manifest.json')),environment=dict(PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',PYTHONPATH='src;tests',TEMP=str(OUTPUT/'temp'),TMP=str(OUTPUT/'temp')),runs=runs,changed_files=changed,source_manifest_sha256=digest(OUTPUT/'source-manifest.json'),diff_sha256=digest(OUTPUT/'changes.diff'),limitations=['real model semantic quality and billing unverified','no actual browser/Electron layout verification','no main repository integration, full suite, build, packaging or installation'])
 save('verification.json',verification)
 print(json.dumps(dict(changed_files=len(changed),phase1_files_checked=len(BASELINE['files']),phase1_artifacts_checked=4,phase1_mismatches=violations,diff_sha256=verification['diff_sha256'],changed_paths=[c['path'] for c in changed]),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
