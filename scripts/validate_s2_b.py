"""仅虚构库的完整回归入口：白名单环境，不继承真实模型凭据或审计URL。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
CHECKS={
    'python':[sys.executable,'-B','-X','utf8','-m','unittest','discover','-s','tests','-v'],
    'example':[sys.executable,'-B','-X','utf8','scripts/validate_example.py'],
    'ui-state':['NODE','--test','tests/ui-state.test.mjs'],
    **{'browser-'+name:['NODE','tests/e2e-'+name+'.cjs'] for name in
       ('smoke','workbench','chat-workbench','providers','offline','backups','performance')},
}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('node','modules','browser','artifacts'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--checks',nargs='+',choices=CHECKS,default=list(CHECKS))
    args=parser.parse_args();artifacts=args.artifacts.resolve()
    if artifacts==ROOT or ROOT in artifacts.parents:
        parser.error('证据必须存入仓库外目录')
    artifacts.mkdir(parents=True,exist_ok=True)
    # 不读取/复制 API 环境项，只读取操作系统运行需要的非秘密变量。
    environment={name:os.environ[name] for name in ('PATH','SystemRoot','WINDIR','COMSPEC',
                 'USERPROFILE','LOCALAPPDATA','APPDATA','TEMP','TMP','PATHEXT') if name in os.environ}
    environment.update(NOVEL_WRITER_PYTHON=sys.executable,NODE_PATH=str(args.modules),
        NOVEL_WRITER_BROWSER=str(args.browser),NOVEL_WRITER_PROVIDER_CONFIG=str(artifacts/'unused-isolated-providers.dpapi'))

    def run(name):
        directory=artifacts/name;directory.mkdir(exist_ok=True)
        command=[str(args.node) if item=='NODE' else item for item in CHECKS[name]]
        env=dict(environment,NOVEL_WRITER_ARTIFACTS=str(directory))
        log=directory/'run.log'
        try:
            with log.open('w',encoding='utf8') as output:
                result=subprocess.run(command,cwd=ROOT,env=env,stdout=output,stderr=subprocess.STDOUT,
                                      # 全量Python随S5增长至近五分钟；只增加验收进程预算，不改任务/API超时或测试选择。
                                      timeout=600 if name=='python' else 300,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            report={'check':name,'exit_code':result.returncode,'log':str(log)}
        except subprocess.TimeoutExpired:
            report={'check':name,'exit_code':124,'log':str(log),'error':'test_timeout'}
        print(json.dumps(report,ensure_ascii=False),flush=True)
        return report

    # 导航性能单独执行，避免并行浏览器使计时证据失真。
    selected=[name for name in args.checks if name!='browser-performance']
    with ThreadPoolExecutor(max_workers=3) as executor:
        reports=list(executor.map(run,selected))
    if 'browser-performance' in args.checks:reports.append(run('browser-performance'))
    (artifacts/'regression-results.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    return 0 if all(item['exit_code']==0 for item in reports) else 1


if __name__=='__main__':raise SystemExit(main())
