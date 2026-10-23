"""开发检查入口的安全契约，仅使用临时目录和虚构环境项。"""
import importlib.util
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/dev_workflow.py'


def load_workflow():
    spec = importlib.util.spec_from_file_location('dev_workflow', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DevelopmentWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), '检查入口尚未实现')
        self.workflow = load_workflow()
        self.temporary = tempfile.TemporaryDirectory(prefix='novel-dev-workflow-test-')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.root = self.directory / 'repository'
        self.root.mkdir()

    def test_artifacts_reject_repository_and_its_ancestors(self):
        for candidate in (self.root, self.root / 'reports', self.directory):
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                self.workflow.create_run(self.root, candidate)

    def test_repeated_checks_keep_separate_evidence(self):
        base = self.directory / 'evidence'
        first = self.workflow.create_run(self.root, base)
        (first / 'sentinel').write_text('first result', encoding='utf8')
        second = self.workflow.create_run(self.root, base)
        self.assertNotEqual(first, second)
        self.assertEqual((first / 'sentinel').read_text(encoding='utf8'), 'first result')

    def test_credentials_and_database_paths_are_rejected_before_reading(self):
        for name in ('data/novels.sqlite3', '.env', 'auth.json', 'providers.dpapi', 'exports/private.txt'):
            with self.subTest(name=name), patch.object(Path, 'read_bytes', side_effect=AssertionError('must not read')):
                with self.assertRaises(ValueError):
                    self.workflow.snapshot(self.root, [name])

    def test_snapshot_rejects_external_file_links(self):
        # Resolve重定向也覆盖Windows junction；无需系统创建symlink的权限。
        with patch.object(Path, 'resolve', return_value=self.directory / 'outside.py'):
            with self.assertRaises(ValueError):
                self.workflow.snapshot(self.root, ['src/test.py'])

    def test_snapshot_rejects_link_into_protected_repository_data(self):
        target = self.root / 'data' / 'fictional.py'
        target.parent.mkdir()
        target.write_text('fictional protected content', encoding='utf8')
        with patch.object(Path, 'resolve', return_value=target), \
             patch.object(Path, 'read_bytes', side_effect=AssertionError('protected content was read')):
            with self.assertRaises(ValueError):
                self.workflow.snapshot(self.root, ['src/friendly.py'])

    def test_secret_scan_rechecks_resolved_protected_path(self):
        target = self.root / 'data' / 'fictional.py'
        with patch.object(Path, 'resolve', return_value=target), \
             patch.object(Path, 'read_text', side_effect=AssertionError('protected content was read')):
            with self.assertRaises(ValueError):
                self.workflow.secret_hints(self.root, ['src/friendly.py'])

    @unittest.skipUnless(sys.platform == 'win32', 'PowerShell入口仅在Windows验证')
    def test_powershell_first_python_strips_fake_secret_and_pythonpath(self):
        # 复制入口到虚构仓库，替换为仅检查环境的本地探针，不执行真实项目检查。
        scripts = self.root / 'scripts with spaces'
        scripts.mkdir()
        launcher = scripts / 'Invoke-DevWorkflow.ps1'
        launcher.write_bytes((SCRIPT.parent / launcher.name).read_bytes())
        (scripts / 'dev_workflow.py').write_text(
            "import os, sys\nprint('WORKFLOW_ENTRY_SECRET' in os.environ)\n"
            "print('PYTHONPATH' in os.environ)\nprint(sys.argv[sys.argv.index('--artifacts')+1])\n", encoding='utf8')
        dummy = self.directory / 'dummy-pythonpath'
        dummy.mkdir()
        marker = str(self.directory / 'evidence with spaces') + '\\'
        env = self.workflow.environment({'WORKFLOW_ENTRY_SECRET': 'fictional-only', 'PYTHONPATH': str(dummy)})
        result = subprocess.run(['powershell', '-NoProfile', '-File', str(launcher),
            '-PythonPath', sys.executable, '-BrowserPath', sys.executable, '-ArtifactsPath', marker], env=env,
            capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['False', 'False', marker])

    def test_changed_missing_and_added_files_are_reported(self):
        changes = self.workflow.compare({'a.py': 'one', 'b.py': 'two'}, {'a.py': 'changed', 'c.py': 'new'})
        self.assertEqual(changes, {'modified': ['a.py'], 'removed': ['b.py'], 'added': ['c.py']})

    def test_live_lock_rejects_second_run_then_releases(self):
        lock = self.directory / 'run.lock'
        with self.workflow.run_lock(lock):
            with self.assertRaises(RuntimeError):
                with self.workflow.run_lock(lock):
                    self.fail('second owner entered')
        with self.workflow.run_lock(lock):
            pass

    def test_child_cannot_inherit_fake_secret(self):
        out = self.directory / 'child.log'
        with patch.dict(os.environ, {'WORKFLOW_TEST_SECRET': 'fictional-do-not-copy'}):
            result = self.workflow.run_check('environment', [sys.executable, '-c',
                "import os; print('WORKFLOW_TEST_SECRET' in os.environ)"], self.root, out, {}, timeout=5)
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(out.read_text(encoding='utf8').strip(), 'False')

    def test_timeout_is_failure_and_keeps_log(self):
        out = self.directory / 'timeout.log'
        result = self.workflow.run_check('timeout', [sys.executable, '-c', 'import time; time.sleep(5)'],
                                         self.root, out, {}, timeout=.1)
        self.assertEqual(result['exit_code'], 124)
        self.assertEqual(result['error'], 'timeout')
        self.assertTrue(out.exists())


if __name__ == '__main__':
    unittest.main()
