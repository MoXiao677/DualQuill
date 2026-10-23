"""B-16真实进程中断；只杀本测试拥有、握手确认的虚构库子进程。"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))

from s2_a_samples import create_fixture_database
from s2_b_samples import build_runtime_dataset
from novel_writer.application import backups
from novel_writer.application import backup_staging
from novel_writer.application.skill_import import SkillLibrary
from novel_writer.storage.backup_validation import validate_database


def rows(path):
    with closing(sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True)) as connection:
        return {table: connection.execute("SELECT * FROM " + table + " ORDER BY 1,2").fetchall()
                for table in ("projects", "project_snapshots", "skills")}


def worker(root, point, nonce):
    """在真实调用完成指定步骤后握手；挂起期间由拥有Popen的父测试强杀。"""
    root = Path(root).resolve(strict=True)

    def pause(stage):
        path = Path(stage).resolve(strict=True)
        if root not in path.parents:
            raise AssertionError("stage leaves owned directory")
        with (root / "ready.json").open("x", encoding="utf8") as output:
            json.dump({"pid": os.getpid(), "nonce": nonce, "point": point,
                       "stage": str(path)}, output)
            output.flush()
            os.fsync(output.fileno())
        # 超过父测试20秒握手限额，避免子进程无限存活。
        time.sleep(60)
        raise AssertionError("parent did not terminate owned worker")

    if point == "capture":
        def progress(stage, done, total):
            if stage == "capture" and 0 < done < total:
                pause(next(root.glob(".novel-backup-*/snapshot.sqlite3")))
        backups.create_backup(root / "fictional.sqlite3", root / "interrupted.nwbak",
                              progress=progress)
    elif point == "transaction":
        original = backups._insert_row
        def insert(connection, table, row):
            original(connection, table, row)
            if table == "projects":
                database = connection.execute("PRAGMA database_list").fetchone()[2]
                pause(database)
        backups._insert_row = insert
        backups.restore_backup(root / "complete.nwbak", root / "restored")
    else:
        original = backups._publish
        def publish(stage, destination):
            if point == "after_publish":
                original(stage, destination)
                pause(Path(destination) / "novels.sqlite3")
            else:
                pause(Path(stage) / "novels.sqlite3")
        backups._publish = publish
        backups.restore_backup(root / "complete.nwbak", root / "restored")


class BackupProcessCrashTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="novel-backup-owned-crash-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.assertNotIn(ROOT, self.root.parents)
        self.source = self.root / "fictional.sqlite3"
        self.archive = self.root / "complete.nwbak"
        self.target = self.root / "restored"
        create_fixture_database(self.source, build_runtime_dataset())
        SkillLibrary(self.source).import_files([
            {"path": "SKILL.md", "content": "# 虚构中断样本\n" + "x" * (1024**2)}])
        self.source_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.expected = rows(self.source)
        backups.create_backup(self.source, self.archive)
        self.archive_hash = hashlib.sha256(self.archive.read_bytes()).hexdigest()

    def crash(self, point):
        nonce = uuid4().hex
        environment = {key: os.environ[key] for key in
                       ("PATH", "SystemRoot", "WINDIR", "COMSPEC", "USERPROFILE",
                        "LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "PATHEXT")
                       if key in os.environ}
        command = [sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve()),
                   "--worker", str(self.root), point, nonce]
        started = time.monotonic()
        with (self.root / "worker.log").open("w", encoding="utf8") as output:
            child = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=output,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            try:
                marker = self.root / "ready.json"
                deadline = started + 20
                while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(marker.exists(), "worker never reached the real operation barrier")
                # Marker is exclusively created, fsynced and then the child stays paused.
                # A partially written marker must not be accepted as ownership evidence.
                while True:
                    try:
                        ready = json.loads(marker.read_text(encoding="utf8"))
                        break
                    except json.JSONDecodeError:
                        if time.monotonic() >= deadline:
                            raise
                        time.sleep(.01)
                self.assertEqual((ready["pid"], ready["nonce"], ready["point"]),
                                 (child.pid, nonce, point))
                stage = Path(ready["stage"]).resolve(strict=True)
                self.assertIn(self.root, stage.parents)
                self.assertIsNone(child.poll())
                child.kill()  # Only this live Popen; never search or kill by port/name/old PID.
                self.assertNotEqual(child.wait(timeout=10), 0)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=10)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.source_hash)
        self.assertEqual(hashlib.sha256(self.archive.read_bytes()).hexdigest(), self.archive_hash)
        self.assertEqual(rows(self.source), self.expected)
        residues = sorted(path.name for path in self.root.glob(".novel-backup-*"))
        self.assertTrue(residues, "abrupt termination should leave its owned unpublished staging")
        bytes_used = sum(path.stat().st_size for path in self.root.rglob("*") if path.is_file())
        self.assertLess(bytes_used, 256 * 1024**2, "small probe exceeded its disk budget")
        self.probe = {"point": point, "owned_pid": child.pid, "ownership_handshake": True,
                      "exit_code": child.returncode, "seconds": round(time.monotonic()-started, 3),
                      "source_hash_unchanged": True, "package_hash_unchanged": True,
                      "residual_owned_directories": residues, "probe_bytes": bytes_used,
                      "published": self.target.exists(), "physical_power_loss": False}
        return stage

    def record(self):
        for directory in self.root.glob(".novel-backup-*"):
            self.assertTrue((directory / ".operation.json").is_file(),
                            "生产暂存没有持久归属，测试自身清理不能代替B-16")
            owned = backup_staging.inspect_staging(directory)
            self.assertEqual(owned["state"], "inactive_owned")
            self.assertTrue(backup_staging.cleanup_staging(directory, owned["operation_id"])["removed"])
        self.assertFalse(list(self.root.glob(".novel-backup-*")))
        self.probe["production_owned_staging_cleanup"] = True
        if os.environ.get("NOVEL_WRITER_ARTIFACTS"):
            directory = Path(os.environ["NOVEL_WRITER_ARTIFACTS"]).resolve()
            self.assertNotEqual(directory, ROOT)
            self.assertNotIn(ROOT, directory.parents)
            directory.mkdir(parents=True, exist_ok=True)
            with (directory / "owned-process-crash-probes.jsonl").open("a", encoding="utf8") as output:
                output.write(json.dumps(self.probe, ensure_ascii=False) + "\n")

    def test_kill_during_capture_never_publishes_half_package(self):
        self.crash("capture")
        self.assertFalse((self.root / "interrupted.nwbak").exists())
        backups.create_backup(self.source, self.root / "interrupted.nwbak")
        self.assertTrue(backups.preflight_backup(self.root / "interrupted.nwbak")["verified"])
        self.probe["retry_verified"] = True
        self.record()

    def test_kill_during_restore_transaction_rolls_back_on_reopen(self):
        stage = self.crash("transaction")
        self.assertFalse(self.target.exists())
        # This owned staging database may have a hot journal: ordinary SQLite open performs recovery.
        with closing(sqlite3.connect(stage)) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone(), ("ok",))
            for table in self.expected:
                self.assertEqual(connection.execute("SELECT count(*) FROM " + table).fetchone()[0], 0)
        restored = backups.restore_backup(self.archive, self.target)
        self.assertEqual(rows(restored["database_path"]), self.expected)
        self.probe.update(uncommitted_rows_after_reopen=0, retry_verified=True)
        self.record()

    def test_kill_after_verified_fsync_before_publish_keeps_target_absent(self):
        stage = self.crash("before_publish")
        self.assertFalse(self.target.exists())
        self.assertTrue(validate_database(stage)["counts"])
        self.assertEqual(rows(stage), self.expected)
        restored = backups.restore_backup(self.archive, self.target)
        self.assertEqual(rows(restored["database_path"]), self.expected)
        self.probe.update(staging_reopened_complete=True, retry_verified=True)
        self.record()

    def test_kill_after_publish_reopens_complete_and_never_overwrites_on_retry(self):
        database = self.crash("after_publish")
        self.assertEqual(database, self.target / "novels.sqlite3")
        self.assertEqual(rows(database), self.expected)
        self.assertEqual(validate_database(database)["counts"],
                         backups.preflight_backup(self.archive)["counts"])
        before = database.read_bytes()
        with self.assertRaises(backups.BackupError) as caught:
            backups.restore_backup(self.archive, self.target)
        self.assertEqual(caught.exception.code, "exists")
        self.assertEqual(database.read_bytes(), before)
        self.probe.update(published_reopened_complete=True, retry_refused_without_overwrite=True)
        self.record()


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--worker":
        worker(*sys.argv[2:])
    else:
        unittest.main()
