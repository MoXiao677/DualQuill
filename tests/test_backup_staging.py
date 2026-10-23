"""崩溃暂存归属与显式清理；只使用本测试独占的虚构目录。"""
import importlib
import gc
from importlib.util import find_spec
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class BackupStagingTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(find_spec("novel_writer.application.backup_staging"),
                             "B-16缺少生产暂存归属识别及明确操作清理")
        self.module = importlib.import_module("novel_writer.application.backup_staging")
        self.temporary = tempfile.TemporaryDirectory(prefix="novel-owned-staging-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def orphan(self):
        (self.root / "ready.json").unlink(missing_ok=True)
        command = [sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve()),
                   "--worker", str(self.root)]
        environment = {key: os.environ[key] for key in
                       ("PATH", "SystemRoot", "WINDIR", "COMSPEC", "USERPROFILE",
                        "LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "PATHEXT") if key in os.environ}
        child = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, encoding="utf8",
                                 creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        try:
            deadline = time.monotonic() + 20
            ready = self.root / "ready.json"
            while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(ready.exists())
            for _ in range(100):
                try:
                    report = json.loads(ready.read_text(encoding="utf8"))
                    break
                except json.JSONDecodeError:
                    time.sleep(.01)
            self.assertEqual(report["pid"], child.pid)
            directory = Path(report["directory"]).resolve(strict=True)
            self.assertEqual(directory.parent, self.root)
            self.assertIsNone(child.poll())
            self.assertEqual(self.module.inspect_staging(directory)["state"], "active_or_locked")
            with self.assertRaises(self.module.StagingError):
                self.module.cleanup_staging(directory, report["operation_id"])
            self.assertTrue((directory / "fictional-payload").is_file())
            child.kill()
            self.assertNotEqual(child.wait(timeout=10), 0)
            return directory, report["operation_id"]
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)
            child.stdout.close()
            child.stderr.close()

    def test_owned_crash_is_identified_without_pid_guess_and_only_explicit_directory_removed(self):
        directory, identity = self.orphan()
        sibling = self.root / "user-keep"
        sibling.mkdir()
        sentinel = sibling / "keep.txt"
        sentinel.write_bytes(b"fictional-user-content")
        report = self.module.inspect_staging(directory)
        self.assertEqual(report["state"], "inactive_owned")
        self.assertEqual(report["operation_id"], identity)
        with self.assertRaises(self.module.StagingError):
            self.module.cleanup_staging(directory, str(uuid4()))
        self.assertTrue(directory.exists())
        result = self.module.cleanup_staging(directory, identity)
        self.assertTrue(result["removed"])
        self.assertFalse(directory.exists())
        self.assertEqual(sentinel.read_bytes(), b"fictional-user-content")

    def test_missing_invalid_or_copied_receipt_never_authorizes_user_directory_deletion(self):
        directory, identity = self.orphan()
        copied = self.root / (directory.name + "-copy")
        shutil.copytree(directory, copied)
        with self.assertRaises(self.module.StagingError):
            self.module.cleanup_staging(copied, identity)
        original = (directory / ".operation.json").read_bytes()
        (directory / ".operation.json").write_bytes(b"{}")
        with self.assertRaises(self.module.StagingError):
            self.module.cleanup_staging(directory, identity)
        self.assertTrue(directory.exists())
        (directory / ".operation.json").write_bytes(original)
        (directory / ".operation.json").unlink()
        with self.assertRaises(self.module.StagingError):
            self.module.cleanup_staging(directory, identity)
        self.assertTrue((directory / "fictional-payload").exists())

    def test_nested_operation_is_preserved_until_separately_identified(self):
        directory, identity = self.orphan()
        nested, nested_id = self.orphan()
        # Copying a nested marker is deliberately untrusted and must block parent cleanup.
        shutil.copytree(nested, directory / "nested-other-operation")
        with self.assertRaises(self.module.StagingError):
            self.module.cleanup_staging(directory, identity)
        self.assertTrue(directory.exists())
        self.assertTrue(nested.exists())

    def test_normal_owned_directory_cleanup_has_no_residue(self):
        with self.module.OwnedTemporaryDirectory(kind="preflight", dir=self.root,
                                                 prefix=".novel-backup-") as directory:
            report = self.module.inspect_staging(directory)
            self.assertEqual(report["state"], "active_or_locked")
            self.assertTrue((Path(directory) / ".operation.json").is_file())
        self.assertFalse(Path(directory).exists())

    def test_normal_gc_closes_owner_lock_and_cleans_once(self):
        owner = self.module.OwnedTemporaryDirectory(kind="preflight", dir=self.root,
                                                    prefix=".novel-backup-")
        directory, stream = Path(owner.name), owner._stream
        del owner
        gc.collect()
        self.assertFalse(directory.exists())
        self.assertTrue(stream.closed, "GC must release the real owner lock")

    def test_cleanup_failure_never_retries_unowned_replacement_during_gc(self):
        owner = self.module.OwnedTemporaryDirectory(kind="restore", dir=self.root,
                                                    prefix=".novel-backup-")
        directory = Path(owner.name)
        (directory / "payload").write_bytes(b"fictional-owned")
        with patch.object(self.module, "_dispose", side_effect=OSError("fictional-delete-failure")):
            with self.assertRaises(self.module.StagingError):
                owner.cleanup()
        self.assertTrue(owner._stream.closed)
        directory.rename(self.root / "held-failed-cleanup")
        directory.mkdir()
        sentinel = directory / "keep.txt"
        sentinel.write_bytes(b"fictional-user-replacement")
        owner.cleanup()  # Completed lifecycle must not retry against a new object.
        del owner
        gc.collect()
        self.assertEqual(sentinel.read_bytes(), b"fictional-user-replacement")

    @unittest.skipUnless(os.name == "nt", "Windows real directory replacement")
    def test_normal_cleanup_preserves_unowned_replacement_directory(self):
        owner = self.module.OwnedTemporaryDirectory(kind="restore", dir=self.root,
                                                    prefix=".novel-backup-")
        directory = Path(owner.name)
        try:
            directory.rename(self.root / "held-original")
        except OSError:
            owner.cleanup()
            return  # OS pinning the live directory also prevents substitution.
        directory.mkdir()
        sentinel = directory / "user-keep.txt"
        sentinel.write_bytes(b"fictional-unowned-replacement")
        try:
            owner.cleanup()
        except self.module.StagingError:
            pass
        self.assertTrue(sentinel.exists(), "normal cleanup must not erase an unowned replacement")
        self.assertEqual(sentinel.read_bytes(), b"fictional-unowned-replacement")

    @unittest.skipUnless(os.name == "nt", "Windows relocated lock replacement")
    def test_relocated_live_lock_cannot_authorize_replacement_in_any_lifecycle(self):
        for action in ("cleanup", "context_exit", "gc"):
            with self.subTest(action=action):
                owner = self.module.OwnedTemporaryDirectory(kind="restore", dir=self.root,
                                                            prefix=".novel-backup-")
                directory = Path(owner.name)
                payload = directory / "original-payload"
                payload.write_bytes(b"fictional-original")
                (directory / ".owner.lock").rename(self.root / (action + "-held-lock"))
                held = self.root / (action + "-held-directory")
                directory.rename(held)
                directory.mkdir()
                sentinel = directory / "user-keep.txt"
                sentinel.write_bytes(b"fictional-user-replacement")
                try:
                    if action == "cleanup":
                        owner.cleanup()
                    elif action == "context_exit":
                        owner.__exit__(None, None, None)
                    else:
                        del owner
                        gc.collect()
                except self.module.StagingError:
                    pass
                self.assertTrue(sentinel.exists(), action + " erased an unowned replacement")
                self.assertEqual(sentinel.read_bytes(), b"fictional-user-replacement")
                self.assertEqual((held / "original-payload").read_bytes(), b"fictional-original")

    @unittest.skipUnless(os.name == "nt", "Windows pinned deletion mutation")
    def test_late_content_is_preserved_with_reinspectable_receipt(self):
        directory, identity = self.orphan()
        original_receipt = (directory / ".operation.json").read_bytes()
        original_lock_identity = self.module.inspect_staging(directory)["lock_identity"]
        original = self.module._dispose
        sentinel = directory / "late-user-keep.txt"
        calls = []
        def dispose(handle):
            if not calls:
                sentinel.write_bytes(b"fictional-late-user-content")
            calls.append(handle)
            return original(handle)
        with patch.object(self.module, "_dispose", side_effect=dispose):
            with self.assertRaises(self.module.StagingError):
                self.module.cleanup_staging(directory, identity)
        self.assertTrue(calls, "mutation must occur after the cleanup enumeration")
        self.assertEqual(sentinel.read_bytes(), b"fictional-late-user-content")
        self.assertTrue((directory / ".operation.json").is_file(),
                        "failed deletion must retain its operation receipt")
        self.assertEqual(self.module.inspect_staging(directory)["operation_id"], identity,
                         "failed deletion must retain verifiable ownership for explicit recovery")
        self.assertEqual((directory / ".operation.json").read_bytes(), original_receipt)
        self.assertEqual(self.module.inspect_staging(directory)["lock_identity"], original_lock_identity)

    @unittest.skipUnless(os.name == "nt", "Windows final root deletion race")
    def test_new_content_at_final_root_removal_retains_recovery_identity(self):
        directory, identity = self.orphan()
        original_receipt = (directory / ".operation.json").read_bytes()
        original_lock_identity = self.module.inspect_staging(directory)["lock_identity"]
        root_handles = []
        original_pin, original_dispose = self.module._pin, self.module._dispose
        @contextmanager
        def pin(path, **options):
            with original_pin(path, **options) as handle:
                if Path(path) == directory:
                    root_handles.append(handle.handle)
                yield handle
        sentinel = directory / "last-window-user.txt"
        def dispose(handle):
            if handle in root_handles:
                sentinel.write_bytes(b"fictional-last-window-user")
            return original_dispose(handle)
        with patch.object(self.module, "_pin", side_effect=pin), \
                patch.object(self.module, "_dispose", side_effect=dispose):
            with self.assertRaises(self.module.StagingError):
                self.module.cleanup_staging(directory, identity)
        self.assertEqual(sentinel.read_bytes(), b"fictional-last-window-user")
        self.assertTrue((directory / ".operation.json").is_file(),
                        "final-root failure must retain recovery ownership")
        self.assertEqual(self.module.inspect_staging(directory)["operation_id"], identity)
        self.assertEqual((directory / ".operation.json").read_bytes(), original_receipt)
        self.assertEqual(self.module.inspect_staging(directory)["lock_identity"], original_lock_identity)

    def junction(self, source, target):
        environment = {key: os.environ[key] for key in
                       ("PATH", "SystemRoot", "WINDIR", "COMSPEC", "USERPROFILE",
                        "LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "PATHEXT") if key in os.environ}
        result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(source), str(target)],
                                env=environment, capture_output=True, timeout=10,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, "owned fictional junction creation failed")
        self.assertTrue(source.is_junction())

    def test_partial_metadata_move_failure_restores_original_objects(self):
        directory, identity = self.orphan()
        before = (directory / ".operation.json").read_bytes()
        lock_identity = self.module.inspect_staging(directory)["lock_identity"]
        original = self.module._move
        calls = []
        def move(*arguments):
            calls.append(arguments)
            if len(calls) == 2:
                raise OSError("fictional-second-move-failure")
            return original(*arguments)
        with patch.object(self.module, "_move", side_effect=move):
            with self.assertRaises(self.module.StagingError):
                self.module.cleanup_staging(directory, identity)
        self.assertGreaterEqual(len(calls), 3, "first moved object must be restored")
        self.assertEqual((directory / ".operation.json").read_bytes(), before)
        self.assertEqual(self.module.inspect_staging(directory)["lock_identity"], lock_identity)
        self.assertFalse(list(self.root.glob(".novel-staging-recovery-*")))
        self.assertTrue(self.module.cleanup_staging(directory, identity)["removed"])

    def test_compensation_never_overwrites_new_metadata_name(self):
        directory, identity = self.orphan()
        before = (directory / ".operation.json").read_bytes()
        original_pin, original_dispose = self.module._pin, self.module._dispose
        handles = []
        @contextmanager
        def pin(path, **options):
            with original_pin(path, **options) as handle:
                if Path(path) == directory:
                    handles.append(handle.handle)
                yield handle
        def dispose(handle):
            if handle in handles:
                (directory / ".operation.json").write_bytes(b"fictional-unowned-collision")
            return original_dispose(handle)
        with patch.object(self.module, "_pin", side_effect=pin), \
                patch.object(self.module, "_dispose", side_effect=dispose):
            with self.assertRaises(self.module.StagingError) as caught:
                self.module.cleanup_staging(directory, identity)
        recovery, = self.root.glob(".novel-staging-recovery-" + identity + "-*")
        self.assertIn(str(recovery), str(caught.exception))
        self.assertEqual((directory / ".operation.json").read_bytes(), b"fictional-unowned-collision")
        self.assertEqual((recovery / ".operation.json").read_bytes(), before)

    def test_metadata_failure_after_root_commit_reports_removed_and_warning(self):
        directory, identity = self.orphan()
        original = self.module._dispose
        def dispose(handle):
            if not directory.exists():
                raise OSError("fictional-postcommit-metadata-delete")
            return original(handle)
        with patch.object(self.module, "_dispose", side_effect=dispose):
            result = self.module.cleanup_staging(directory, identity)
        self.assertTrue(result["removed"])
        self.assertFalse(directory.exists())
        recovery, = self.root.glob(".novel-staging-recovery-" + identity + "-*")
        self.assertIn(str(recovery), " ".join(result["cleanup_warnings"]))
        self.assertEqual(json.loads((recovery / ".operation.json").read_text(encoding="utf8"))["operation_id"], identity)

    @unittest.skipUnless(os.name == "nt", "Windows real junction")
    def test_existing_junction_never_deletes_outside_user_content(self):
        directory, identity = self.orphan()
        outside = self.root / "user-outside"
        outside.mkdir()
        sentinel = outside / "keep.txt"
        sentinel.write_bytes(b"fictional-user-outside")
        link = directory / "unexpected-junction"
        self.junction(link, outside)
        try:
            with self.assertRaises(self.module.StagingError):
                self.module.cleanup_staging(directory, identity)
            self.assertEqual(sentinel.read_bytes(), b"fictional-user-outside")
            self.assertTrue((directory / "fictional-payload").exists())
        finally:
            link.rmdir()  # Only this test's junction, not its target.

    @unittest.skipUnless(os.name == "nt", "Windows real junction race")
    def test_junction_substitution_between_check_and_pin_preserves_outside(self):
        directory, identity = self.orphan()
        child = directory / "child"
        child.mkdir()
        outside = self.root / "outside-race"
        outside.mkdir()
        sentinel = outside / "keep.txt"
        sentinel.write_bytes(b"fictional-user-outside-race")
        original = self.module._pin
        injected = []
        @contextmanager
        def pin(path, **options):
            if Path(path) == child and not injected:
                injected.append(True)
                try:
                    child.rename(directory / "held-child")
                except OSError:
                    pass  # A fixed parent may reject the real replacement at the OS boundary.
                else:
                    self.junction(child, outside)
            with original(path, **options) as handle:
                yield handle
        try:
            with patch.object(self.module, "_pin", side_effect=pin):
                try:
                    self.module.cleanup_staging(directory, identity)
                except self.module.StagingError:
                    self.assertTrue((directory / "fictional-payload").exists())
            self.assertTrue(injected)
            self.assertEqual(sentinel.read_bytes(), b"fictional-user-outside-race")
        finally:
            if child.is_junction():
                child.rmdir()

    @unittest.skipUnless(os.name == "nt", "Windows real junction in normal cleanup")
    def test_normal_cleanup_junction_race_never_sweeps_user_directory(self):
        owner = self.module.OwnedTemporaryDirectory(kind="restore", dir=self.root,
                                                    prefix=".novel-backup-")
        directory = Path(owner.name)
        child = directory / "child"
        child.mkdir()
        (child / "owned-payload").write_bytes(b"fictional-owned")
        outside = self.root / "normal-cleanup-user-directory"
        outside.mkdir()
        sentinel = outside / "keep.txt"
        sentinel.write_bytes(b"fictional-user-data")
        original = os.scandir
        injected = []
        def scandir(path):
            if Path(path) == child and not injected:
                injected.append(True)
                child.rename(directory / "held-child")
                self.junction(child, outside)
            return original(path)
        try:
            with patch.object(os, "scandir", side_effect=scandir):
                try:
                    owner.cleanup()
                except (self.module.StagingError, OSError):
                    pass
            self.assertTrue(sentinel.exists(), "normal cleanup followed a replaced child into user data")
            self.assertEqual(sentinel.read_bytes(), b"fictional-user-data")
            # A safe implementation may avoid the recursive path altogether.
        finally:
            if child.is_junction():
                child.rmdir()

    @unittest.skipUnless(os.name == "nt", "Windows object replacement regression")
    def test_live_lock_replacement_cannot_make_operation_inactive(self):
        owner = self.module.OwnedTemporaryDirectory(kind="restore", dir=self.root,
                                                    prefix=".novel-backup-")
        changed = False
        try:
            directory = Path(owner.name)
            lock = directory / ".owner.lock"
            try:
                lock.rename(directory / "old-owner.lock")
            except OSError:
                self.assertEqual(self.module.inspect_staging(directory)["state"], "active_or_locked")
                return
            changed = True
            lock.write_bytes(b"0")
            try:
                report = self.module.inspect_staging(directory)
            except self.module.StagingError:
                return
            self.assertEqual(report["state"], "active_or_locked",
                             "Replacing a live lock must not authorize cleanup")
        finally:
            if changed:
                with self.assertRaises(self.module.StagingError):
                    owner.cleanup()
                self.assertTrue((directory / "old-owner.lock").exists())
                self.assertTrue((directory / ".operation.json").exists())
            else:
                owner.cleanup()

    @unittest.skipUnless(os.name == "nt", "Windows directory replacement regression")
    def test_live_directory_replacement_cannot_replay_original_receipt(self):
        owner = self.module.OwnedTemporaryDirectory(kind="restore", dir=self.root,
                                                    prefix=".novel-backup-")
        changed = False
        try:
            directory = Path(owner.name)
            receipt = (directory / ".operation.json").read_bytes()
            identity = json.loads(receipt)["operation_id"]
            try:
                directory.rename(self.root / "held-original")
            except OSError:
                with self.assertRaises(self.module.StagingError):
                    self.module.cleanup_staging(directory, identity)
                return
            changed = True
            directory.mkdir()
            (directory / ".operation.json").write_bytes(receipt)
            (directory / ".owner.lock").write_bytes(b"0")
            (directory / "keep.txt").write_bytes(b"unowned replacement")
            with self.assertRaises(self.module.StagingError):
                self.module.cleanup_staging(directory, identity)
            self.assertTrue((directory / "keep.txt").exists())
        finally:
            if changed:
                with self.assertRaises(self.module.StagingError):
                    owner.cleanup()
                self.assertEqual((directory / "keep.txt").read_bytes(), b"unowned replacement")
            else:
                owner.cleanup()

    def test_cli_inspect_and_explicit_cleanup_use_original_operation_identity(self):
        directory, identity = self.orphan()
        environment = {key: os.environ[key] for key in
                       ("PATH", "SystemRoot", "WINDIR", "COMSPEC", "USERPROFILE",
                        "LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "PATHEXT") if key in os.environ}
        def run(*arguments):
            return subprocess.run([sys.executable, "-B", "-X", "utf8", "scripts/manage_backups.py",
                                   *arguments], cwd=ROOT, env=environment, capture_output=True,
                                  text=True, encoding="utf8", timeout=10,
                                  creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        inspected = run("inspect-staging", "--directory", str(directory))
        self.assertEqual(inspected.returncode, 0, inspected.stderr)
        self.assertEqual(json.loads(inspected.stdout)["operation_id"], identity)
        refused = run("cleanup-staging", "--directory", str(directory),
                      "--operation-id", str(uuid4()))
        self.assertEqual(refused.returncode, 1)
        self.assertTrue(directory.exists())
        cleaned = run("cleanup-staging", "--directory", str(directory), "--operation-id", identity)
        self.assertEqual(cleaned.returncode, 0, cleaned.stderr)
        self.assertTrue(json.loads(cleaned.stdout)["removed"])
        self.assertFalse(directory.exists())


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        module = importlib.import_module("novel_writer.application.backup_staging")
        root = Path(sys.argv[2]).resolve(strict=True)
        with module.OwnedTemporaryDirectory(kind="restore", dir=root,
                                           prefix=".novel-backup-") as directory:
            marker = json.loads((Path(directory) / ".operation.json").read_text(encoding="utf8"))
            (Path(directory) / "fictional-payload").write_bytes(b"fictional-owned-operation")
            (root / "ready.json").unlink(missing_ok=True)
            with (root / "ready.json").open("x", encoding="utf8") as ready:
                json.dump({"pid": marker["pid"], "directory": directory,
                           "operation_id": marker["operation_id"]}, ready)
                ready.flush()
            time.sleep(60)
    else:
        unittest.main()
