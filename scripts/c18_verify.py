"""Small C18 check suite with synthetic profile, scrubbed child env and durable logs."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=False)
    temp=output/'temp';profile=output/'fictional-profile'
    for directory in (temp,profile,profile/'local',profile/'roaming',output/'cache'):
        directory.mkdir(parents=True,exist_ok=True)
    env={name:os.environ[name] for name in ('PATH','SystemRoot','WINDIR','COMSPEC') if name in os.environ}
    env.update(TEMP=str(temp),TMP=str(temp),TMPDIR=str(temp),HOME=str(profile),USERPROFILE=str(profile),
        LOCALAPPDATA=str(profile/'local'),APPDATA=str(profile/'roaming'),PYTHONDONTWRITEBYTECODE='1',
        PYTHONPATH=os.pathsep.join((str(ROOT/'src'),str(ROOT/'tests'))),PYTHONUTF8='1',
        NOVEL_WRITER_PROVIDER_CONFIG=str(profile/'nonexistent-fictional-providers.dpapi'),
        NOVEL_WRITER_BUILD_CACHE=str(output/'cache'),CSC_IDENTITY_AUTO_DISCOVERY='false')
    node=shutil.which('node');
    if not node:raise RuntimeError('Node.js is required; no installation attempted')
    # Network generation is not part of this suite. Python sockets can only connect to loopback.
    bootstrap=("import socket,unittest;original=socket.socket.connect\n"
        "def guarded(self,address):\n"
        " if isinstance(address,tuple) and address[0] not in ('127.0.0.1','::1','localhost'): raise RuntimeError('C18 external network denied')\n"
        " return original(self,address)\n"
        "socket.socket.connect=guarded\n"
        "unittest.main(module=None,verbosity=2)\n")
    commands=[
        ('source-binding-before',[node,'desktop/delivery-contract.cjs']),
        ('extension-policy',[sys.executable,'-B','-X','utf8','-c',bootstrap,'test_c18_extension_policy']),
        ('artifact-auditor',[sys.executable,'-B','-X','utf8','-c',bootstrap,'test_c18_artifact_audit']),
        ('backup-regression',[sys.executable,'-B','-X','utf8','-c',bootstrap,'test_backups','test_s7_legacy_profiles',
            'test_candidate_model_reviews.CandidateModelReviewTests.test_v35_restore_and_two_copies_preserve_wire_and_map_real_producers',
            'test_backup_http.BackupHTTPTests.test_upload_retry_has_recoverable_identity_and_does_not_create_second_target']),
        ('delivery-node',[node,'--test','tests/c18-delivery.test.cjs','tests/desktop-packaging.test.cjs','tests/c18-extension-ui.test.mjs']),
        ('build-syntax',[node,'--check','desktop/build.cjs']),
        ('ui-syntax',[node,'--check','src/novel_writer/ui/static/comparison_views.js']),
        ('app-syntax',[node,'--check','src/novel_writer/ui/static/app.js']),
        ('source-binding-after',[node,'desktop/delivery-contract.cjs'])]
    report=dict(format=1,started_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        workspace=str(ROOT),real_provider_calls=0,external_network_allowed=False,
        environment='allowlisted child environment; fictional profile; loopback-only Python sockets',
        installer_executed=False,clean_vm_tested=False,full_suite_run=False,commands=[])
    for label,command in commands:
        log=output/(label+'.log')
        with log.open('wb') as stream:
            result=subprocess.run(command,cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=180)
        body=log.read_text(encoding='utf-8',errors='replace')
        match=re.search(r'Ran (\d+) tests?',body) or re.search(r'(?:ℹ |# )tests (\d+)',body)
        item=dict(label=label,command=command,exit_code=result.returncode,
                  test_count=int(match[1]) if match else None,log=str(log),
                  log_sha256=hashlib.sha256(log.read_bytes()).hexdigest())
        report['commands'].append(item)
        print(f'{label}: exit={result.returncode}, tests={item["test_count"]}',flush=True)
        (output/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    report['source_binding_unchanged']=(output/'source-binding-before.log').read_bytes()==(output/'source-binding-after.log').read_bytes()
    report['passed']=all(item['exit_code']==0 for item in report['commands']) and report['source_binding_unchanged']
    report['finished_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    (output/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if report['passed'] else 1


if __name__=='__main__':sys.exit(main())
