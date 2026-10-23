"""显式恢复清理中断；仅本测试独占虚构目录及实时Popen。"""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from novel_writer.application import backup_staging as staging
from novel_writer.application import backup_staging_recovery as recovery


class PrivateAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="novel-private-authority-owned-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.assertNotIn(ROOT, self.root.parents)
        self.sid = recovery._sid()
        self.advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
        self.advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
            ctypes.POINTER(wintypes.LPWSTR), ctypes.c_void_p]
        self.advapi.GetNamedSecurityInfoW.argtypes = [
            wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        self.advapi.GetNamedSecurityInfoW.restype = wintypes.DWORD
        self.advapi.SetNamedSecurityInfoW.argtypes = [
            wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        self.advapi.SetNamedSecurityInfoW.restype = wintypes.DWORD
        self.advapi.GetSecurityDescriptorControl.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(wintypes.WORD), ctypes.POINTER(wintypes.DWORD)]
        self.advapi.GetSecurityDescriptorControl.restype = wintypes.BOOL
        self.kernel.LocalFree.argtypes = [ctypes.c_void_p]

    def create(self, path, sddl):
        class Attributes(ctypes.Structure):
            _fields_ = [("length", wintypes.DWORD), ("descriptor", ctypes.c_void_p),
                        ("inherit", wintypes.BOOL)]
        self.kernel.CreateDirectoryW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(Attributes)]
        self.kernel.CreateDirectoryW.restype = wintypes.BOOL
        descriptor = ctypes.c_void_p()
        self.assertTrue(self.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(descriptor), None), ctypes.get_last_error())
        try:
            attrs = Attributes(ctypes.sizeof(Attributes), descriptor, False)
            self.assertTrue(self.kernel.CreateDirectoryW(str(path), ctypes.byref(attrs)),
                            ctypes.get_last_error())
        finally:
            self.kernel.LocalFree(descriptor)

    def remove_protection(self, path):
        self.assertEqual(path, self.root / "unprotected")
        descriptor, dacl = ctypes.c_void_p(), ctypes.c_void_p()
        self.assertEqual(self.advapi.GetNamedSecurityInfoW(
            str(path), 1, 4, None, None, ctypes.byref(dacl), None, ctypes.byref(descriptor)), 0)
        try:
            self.assertTrue(dacl.value)
            # 仅本用例新建目录，使用原DACL解除保护；Windows可回填父目录的继承ACE。
            self.assertEqual(self.advapi.SetNamedSecurityInfoW(
                str(path), 1, 4 | 0x20000000, None, None, dacl, None), 0)
        finally:
            self.kernel.LocalFree(descriptor)

    def read_security(self, path, *, protected=None):
        descriptor, rendered = ctypes.c_void_p(), wintypes.LPWSTR()
        self.assertEqual(self.advapi.GetNamedSecurityInfoW(
            str(path), 1, 5, None, None, None, None, ctypes.byref(descriptor)), 0)
        try:
            if protected is not None:
                control, revision = wintypes.WORD(), wintypes.DWORD()
                self.assertTrue(self.advapi.GetSecurityDescriptorControl(
                    descriptor, ctypes.byref(control), ctypes.byref(revision)), ctypes.get_last_error())
                self.assertEqual(bool(control.value & 0x1000), protected, "夹具的DACL保护前提不符")
            self.assertTrue(self.advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                descriptor, 1, 5, ctypes.byref(rendered), None), ctypes.get_last_error())
            try:
                return rendered.value
            finally:
                self.kernel.LocalFree(rendered)
        finally:
            self.kernel.LocalFree(descriptor)

    def test_private_root_accepts_current_user_descriptor_after_win32_rendering(self):
        path = self.root / "authority"
        self.assertTrue(recovery._private_root(path, create=True))
        security = self.read_security(path)
        self.assertFalse(recovery._private_root(path, create=False))
        self.assertEqual(self.read_security(path), security)
        self.assertEqual(list(path.iterdir()), [])

    def test_private_root_rejects_different_user_without_changing_existing_directory(self):
        path = self.root / "authority"
        self.create(path, "O:" + self.sid + "D:P(A;OICI;FA;;;" + self.sid + ")(A;OICI;FA;;;SY)")
        security = self.read_security(path)
        marker = path / "fictional-sentinel"
        marker.write_bytes(b"fictional-content-must-survive")
        with patch.object(recovery, "_sid", return_value="S-1-5-18"):
            with self.assertRaises(staging.StagingError):
                recovery._private_root(path, create=True)
        self.assertEqual(self.read_security(path), security)
        self.assertEqual(marker.read_bytes(), b"fictional-content-must-survive")

    def test_private_root_rejects_unprotected_or_unexpected_access_without_rewriting_acl(self):
        owner = "O:" + self.sid
        user = "(A;OICI;FA;;;" + self.sid + ")"
        cases = {"unprotected": owner + "D:P" + user + "(A;OICI;FA;;;SY)",
                 "extra_principal": owner + "D:P" + user + "(A;OICI;FA;;;SY)(A;OICI;FA;;;WD)",
                 "missing_system": owner + "D:P" + user}
        for name, sddl in cases.items():
            with self.subTest(name=name):
                path = self.root / name
                self.create(path, sddl)
                marker = path / "fictional-sentinel"
                marker.write_bytes(b"fictional-content-must-survive")
                if name == "unprotected":
                    self.remove_protection(path)
                security = self.read_security(path, protected=name != "unprotected")
                if name == "extra_principal":
                    self.assertIn("(A;OICI;FA;;;WD)", security, "夹具必须含额外Everyone完全访问ACE")
                elif name == "missing_system":
                    self.assertNotIn(";;;SY)", security, "夹具必须缺少SYSTEM访问ACE")
                with self.assertRaises(staging.StagingError):
                    recovery._private_root(path, create=True)
                self.assertEqual(self.read_security(path, protected=name != "unprotected"), security)
                self.assertEqual(marker.read_bytes(), b"fictional-content-must-survive")

    def test_existing_authority_without_key_does_not_issue_signing_material(self):
        path = self.root / "AI-Novel-Writer-staging-authority-v1"
        self.create(path, "O:" + self.sid + "D:P(A;OICI;FA;;;" + self.sid + ")(A;OICI;FA;;;SY)")
        security = self.read_security(path)
        with patch.object(recovery.tempfile, "gettempdir", return_value=str(self.root)), \
                patch("novel_writer.application.provider_connections._crypt") as crypt:
            with self.assertRaises(FileNotFoundError):
                recovery._authority(create=True)
            crypt.assert_not_called()
        self.assertEqual(self.read_security(path), security)
        self.assertEqual(list(path.iterdir()), [])


def worker(base, point, nonce):
    base = Path(base).resolve(strict=True)
    owner = staging.OwnedTemporaryDirectory(kind="restore", prefix=".novel-backup-", dir=base)
    directory = Path(owner.name)
    receipt = json.loads((directory / ".operation.json").read_text(encoding="utf8"))
    (directory / "fictional-payload").write_bytes(b"fictional-unpublished-content")
    moved, root_handles, paused = [], [], []
    root_disposed = []
    original_pin, original_move, original_dispose = staging._pin, staging._move, staging._dispose

    def recovery():
        paths = list(base.glob(".novel-staging-recovery-" + receipt["operation_id"] + "-*"))
        if paths:
            return paths[0]
        # Only this test's previously observed path, never production discovery.
        return Path(observed[0])
    observed = []

    def pause():
        if paused:
            return
        paused.append(True)
        path = recovery()
        with (base / "ready.json").open("x", encoding="utf8") as output:
            json.dump({"pid": os.getpid(), "nonce": nonce, "point": point,
                       "directory": str(directory), "recovery_directory": str(path),
                       "operation_id": receipt["operation_id"], "receipt": receipt,
                       "moves": moved}, output)
            output.flush()
            os.fsync(output.fileno())
        time.sleep(60)
        raise AssertionError("parent did not terminate its worker")

    @contextmanager
    def pin(path, **options):
        with original_pin(path, **options) as handle:
            if Path(path) == directory:
                root_handles.append(handle.handle)
            if Path(path).name.startswith(".novel-staging-recovery-"):
                observed[:] = [str(path)]
            original_close = handle.close
            def close():
                original_close()
                if root_disposed and not directory.exists():
                    if point == "root_removed" and Path(path) == directory:
                        pause()
                    if point == "metadata_removed" and Path(path).name == ".operation.json":
                        pause()
                    if point == "recovery_removed" and Path(path) == recovery() and not recovery().exists():
                        pause()
            handle.close = close
            yield handle

    def move(*arguments):
        result = original_move(*arguments)
        moved.append(arguments[2])
        if point == "move_one" and len(moved) == 1:
            pause()
        if point == "move_two" and len(moved) == 2:
            pause()
        return result

    def dispose(handle):
        result = original_dispose(handle)
        if handle in root_handles:
            root_disposed.append(True)
        return result

    with patch.object(staging, "_pin", side_effect=pin), \
            patch.object(staging, "_move", side_effect=move), \
            patch.object(staging, "_dispose", side_effect=dispose):
        owner.cleanup()
    raise AssertionError("worker missed specified real window")


class StagingRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="novel-staging-recovery-owned-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.assertNotIn(ROOT, self.root.parents)
        self.probes = []
        self.sentinel = self.root / "fictional-user-sentinel.txt"
        self.sentinel.write_bytes(b"fictional-user-content-must-survive")

    def crash(self, point):
        nonce = uuid4().hex
        env = {name: os.environ[name] for name in ("PATH", "SystemRoot", "WINDIR", "COMSPEC",
               "USERPROFILE", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "PATHEXT") if name in os.environ}
        command = [sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve()),
                   "--worker", str(self.root), point, nonce]
        with (self.root / "worker.log").open("w", encoding="utf8") as output:
            child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                deadline = time.monotonic() + 20
                ready = self.root / "ready.json"
                while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(ready.exists(), (self.root / "worker.log").read_text(encoding="utf8"))
                while True:
                    try:
                        result = json.loads(ready.read_text(encoding="utf8"))
                        break
                    except json.JSONDecodeError:
                        if time.monotonic() >= deadline:
                            raise
                        time.sleep(.01)
                self.assertEqual((result["pid"], result["nonce"], result["point"]), (child.pid, nonce, point))
                self.assertEqual(Path(result["directory"]).parent, self.root)
                self.assertEqual(Path(result["recovery_directory"]).parent, self.root)
                self.assertIsNone(child.poll())
                child.kill()
                self.assertNotEqual(child.wait(timeout=10), 0)
                result["worker_exit_code"] = child.returncode
                result["owned_handshake"] = True
                self.probes.append(result)
                if os.environ.get("NOVEL_WRITER_ARTIFACTS"):
                    artifacts = Path(os.environ["NOVEL_WRITER_ARTIFACTS"])
                    artifacts.mkdir(parents=True, exist_ok=True)
                    with (artifacts / "staging-recovery-handshakes.jsonl").open("a", encoding="utf8") as output:
                        output.write(json.dumps(result, ensure_ascii=False) + "\n")
                return result
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=10)

    def cli(self, command, probe):
        env = {name: os.environ[name] for name in ("PATH", "SystemRoot", "WINDIR", "COMSPEC",
               "USERPROFILE", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "PATHEXT") if name in os.environ}
        result = subprocess.run([sys.executable, "-B", "-X", "utf8", "scripts/manage_backups.py", command,
                                 "--directory", probe["directory"], "--recovery-directory", probe["recovery_directory"],
                                 "--operation-id", probe["operation_id"]], cwd=ROOT, env=env,
                                capture_output=True, text=True, encoding="utf8", timeout=20,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stderr)
        probe.setdefault("cli_exit_codes", []).append(result.returncode)
        return json.loads(result.stdout)

    def check_window(self, point, exists):
        probe = self.crash(point)
        directory, recovery = Path(probe["directory"]), Path(probe["recovery_directory"])
        self.assertEqual(directory.exists(), exists)
        self.assertTrue(hasattr(staging, "inspect_staging_recovery"),
                        "真实清理窗口强杀后缺少显式归属核对/恢复接口")
        before = self.cli("inspect-staging-recovery", probe)
        self.assertTrue(before["can_recover"])
        after = self.cli("recover-staging", probe)
        self.assertEqual(after["state"], "restored" if exists else "completed")
        again = self.cli("recover-staging", probe)
        self.assertEqual(again["state"], after["state"])
        self.assertFalse(recovery.exists())
        self.assertEqual(self.sentinel.read_bytes(), b"fictional-user-content-must-survive")
        if exists:
            actual = staging.inspect_staging(directory)
            self.assertEqual(actual["operation_id"], probe["operation_id"])
            self.assertEqual(actual["lock_identity"], probe["receipt"]["lock_identity"])
            self.assertEqual(actual["directory_identity"], probe["receipt"]["directory_identity"])
        probe.update(final_state=after["state"], retry_idempotent=True,
                     real_power_loss=False, outside_sentinel_unchanged=True)
        if os.environ.get("NOVEL_WRITER_ARTIFACTS"):
            artifacts = Path(os.environ["NOVEL_WRITER_ARTIFACTS"])
            artifacts.mkdir(parents=True, exist_ok=True)
            with (artifacts / "staging-recovery-crash-probes.jsonl").open("a", encoding="utf8") as output:
                output.write(json.dumps(probe, ensure_ascii=False) + "\n")

    def test_kill_after_one_metadata_move_restores_same_objects(self):
        self.check_window("move_one", True)

    def test_kill_after_both_metadata_moves_restores_same_objects(self):
        self.check_window("move_two", True)

    def test_kill_after_root_removed_completes_only_registered_metadata(self):
        self.check_window("root_removed", False)

    def test_kill_after_metadata_delete_uses_persisted_object_intent(self):
        self.check_window("metadata_removed", False)

    def test_kill_after_recovery_removed_retries_without_recreating_paths(self):
        self.check_window("recovery_removed", False)


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--worker":
        worker(*sys.argv[2:])
    else:
        unittest.main()
