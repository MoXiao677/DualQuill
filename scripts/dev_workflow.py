"""本地开发检查：独立证据、互斥、虚构库回归；不调用模型或修改业务数据。"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
OS_ENVIRONMENT = ('PATH', 'SystemRoot', 'WINDIR', 'COMSPEC', 'USERPROFILE',
                  'LOCALAPPDATA', 'APPDATA', 'TEMP', 'TMP', 'PATHEXT')
DOCUMENTS = ('AGENTS.md', 'PRODUCT_REQUIREMENTS.md', 'ROADMAP.md', 'TASKS.md',
             'ARCHITECTURE.md', 'CHANGELOG.md')


def environment(extra=None):
    return {**{name: os.environ[name] for name in OS_ENVIRONMENT if name in os.environ}, **(extra or {})}


def create_run(root, base):
    root, base = root.resolve(), base.resolve()
    if root == base or root in base.parents or base in root.parents:
        raise ValueError('证据目录必须在仓库外，且不能是仓库的父目录')
    directory = base / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid4().hex[:12])
    directory.mkdir(parents=True, exist_ok=False)
    return directory


def private_path(name):
    path = Path(name)
    parts = [part.lower() for part in path.parts]
    return (path.is_absolute() or '..' in parts or
            any(part in ('data', 'exports', 'backups', '.git', '.ssh') for part in parts) or
            any(part == '.env' or part.startswith('.env.') for part in parts) or
            path.name.lower() in ('auth.json', 'credentials.json', 'id_rsa', 'id_ed25519') or
            path.suffix.lower() in ('.sqlite', '.sqlite3', '.db', '.dpapi', '.pem', '.key') or
            any(marker in path.name.lower() for marker in ('.sqlite3-', '.sqlite-', '.db-')))


def git(root, *arguments):
    return subprocess.check_output(['git', '-C', str(root), *arguments], env=environment(), stderr=subprocess.DEVNULL)


def files(root):
    return sorted(set(name for name in git(root, 'ls-files', '--cached', '--others',
                                          '--exclude-standard', '-z').decode('utf8').split('\0') if name))


def checked_path(root, name):
    if private_path(name):
        raise ValueError('Git候选文件包含数据或凭据路径；停止检查，不读取内容')
    path = (root / name).resolve()
    if root not in path.parents:
        raise ValueError('Git候选文件链接到仓库外；停止检查')
    if private_path(path.relative_to(root)):
        raise ValueError('Git候选文件链接到受保护路径；停止检查，不读取内容')
    return path


def snapshot(root, names):
    result = {}
    for name in names:
        path = checked_path(root, name)
        if path.is_file():
            result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def compare(before, after):
    return {'modified': sorted(name for name in before.keys() & after.keys() if before[name] != after[name]),
            'removed': sorted(before.keys() - after.keys()), 'added': sorted(after.keys() - before.keys())}


@contextmanager
def run_lock(path):
    """只锁检查进程；OS释放崩溃进程的锁，不按陈旧PID杀进程或删除锁文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0, 2)
        if not stream.tell():
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError('本项目已有检查在运行；不启动重复检查') from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def run_check(name, command, root, log, extra, *, timeout=600):
    start = time.monotonic()
    report = {'check': name, 'command': command, 'log': str(log)}
    with log.open('w', encoding='utf8') as stream:
        try:
            child = subprocess.Popen(command, cwd=root, env=environment(extra), stdout=stream,
                stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            try:
                report['exit_code'] = child.wait(timeout=timeout)
            except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
                # 仅清理本入口刚创建且仍在运行的子进程树，绝不按端口/名称找进程。
                if child.poll() is None:
                    if os.name == 'nt':
                        subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'], env=environment(),
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                    else:
                        child.kill()
                    child.wait(timeout=10)
                report.update(exit_code=124 if isinstance(error, subprocess.TimeoutExpired) else 130,
                              error='timeout' if isinstance(error, subprocess.TimeoutExpired) else 'interrupted')
        except OSError as error:
            report.update(exit_code=127, error=type(error).__name__)
    report['seconds'] = round(time.monotonic() - start, 3)
    return report


def secret_hints(root, names):
    """保守提示高置信凭据形状；只输出文件/行，不输出匹配内容，不宣称完全检漏。"""
    pattern = re.compile(r'\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{40,}|AIza[A-Za-z0-9_-]{35}|ghp_[A-Za-z0-9]{36})\b')
    hints = []
    for name in names:
        path = checked_path(root, name)
        if path.suffix.lower() not in ('.py', '.js', '.mjs', '.cjs', '.md', '.json', '.ps1', '.toml', '.html'):
            continue
        for number, line in enumerate(path.read_text(encoding='utf8', errors='replace').splitlines(), 1):
            if pattern.search(line):
                hints.append({'file': name, 'line': number})
    return hints


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('inspect', 'validate'), default='inspect')
    parser.add_argument('--checks', choices=('upload', 'core', 'full'), default='core')
    parser.add_argument('--artifacts', type=Path, default=Path(tempfile.gettempdir()) / 'AI-Novel-Writer-dev-runs')
    parser.add_argument('--node', type=Path)
    parser.add_argument('--modules', type=Path)
    parser.add_argument('--browser', type=Path)
    parser.add_argument('--service-pid', type=int)
    args = parser.parse_args()
    identity = hashlib.sha256(str(ROOT).lower().encode('utf8')).hexdigest()[:24]
    lock = Path(tempfile.gettempdir()) / 'AI-Novel-Writer-dev-locks' / (identity + '.lock')
    try:
        with run_lock(lock):
            directory = create_run(ROOT, args.artifacts)
            report = {'mode': args.mode, 'checks': args.checks, 'repository': str(ROOT),
                      'python': sys.executable, 'formal_listener_pid_observed': args.service_pid,
                      'task_source': 'TASKS.md', 'acceptance': 'not-decided-by-checks',
                      'started_at': datetime.now(timezone.utc).isoformat(), 'checks_run': []}
            before = None
            try:
                missing = [name for name in DOCUMENTS if not (ROOT / name).is_file()]
                if missing:
                    raise ValueError('缺少项目规则文档')
                names = files(ROOT)
                before = snapshot(ROOT, names)
                (directory / 'baseline.json').write_text(json.dumps(before, indent=2), encoding='utf8')
                (directory / 'git-status.txt').write_bytes(git(ROOT, 'status', '--porcelain=v1', '--untracked-files=all'))
                report['head'] = git(ROOT, 'rev-parse', 'HEAD').decode().strip()
                report['baseline_files'] = len(before)
                report['credential_hints'] = secret_hints(ROOT, before)
                if report['credential_hints']:
                    raise ValueError('候选代码中有疑似凭据，仅记录位置，请先核验')
                if args.mode == 'validate':
                    if args.checks == 'upload':
                        command = [sys.executable, '-B', '-X', 'utf8', '-m', 'unittest', 'discover',
                                   '-s', 'tests', '-p', 'test_backup_upload.py', '-v']
                    else:
                        if not args.node or not args.node.is_file():
                            raise ValueError('缺少可用Node运行时')
                        if args.checks == 'full' and (not args.modules or not args.modules.is_dir() or
                                                    not args.browser or not args.browser.is_file()):
                            raise ValueError('完整浏览器回归需要现有Playwright模块和浏览器路径')
                        command = [sys.executable, '-B', '-X', 'utf8', 'scripts/validate_s2_b.py',
                                   '--node', str(args.node), '--modules', str(args.modules or directory),
                                   '--browser', str(args.browser or args.node), '--artifacts', str(directory / 'regression')]
                        if args.checks == 'core':
                            command += ['--checks', 'python', 'example', 'ui-state']
                    extra = {'NOVEL_WRITER_ARTIFACTS': str(directory),
                             'NOVEL_WRITER_PROVIDER_CONFIG': str(directory / 'unused-isolated-providers.dpapi')}
                    report['checks_run'].append(run_check(args.checks, command, ROOT, directory / 'validation.log', extra))
                diff = subprocess.run(['git', '-C', str(ROOT), 'diff', '--check'], env=environment(),
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                report['diff_check_exit_code'] = diff.returncode
                after = snapshot(ROOT, files(ROOT))
                report['during_check_changes'] = compare(before, after)
                report['checks_passed'] = (diff.returncode == 0 and not any(report['during_check_changes'].values())
                                         and all(item['exit_code'] == 0 for item in report['checks_run']))
                report['status'] = ('checks-passed' if args.mode == 'validate' else 'inspection-complete') if report['checks_passed'] else 'failed'
            except Exception as error:
                report.update(status='failed', checks_passed=False, error=type(error).__name__,
                              reason=str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__)
            finally:
                report['ended_at'] = datetime.now(timezone.utc).isoformat()
                (directory / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
                print(json.dumps({'status': report['status'], 'report': str(directory / 'report.json'),
                                  'acceptance': report['acceptance']}, ensure_ascii=False))
            return 0 if report['checks_passed'] else 1
    except (ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
