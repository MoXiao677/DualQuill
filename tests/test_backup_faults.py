"""备份发布与压缩流故障回归；仅操作测试创建的虚构临时库。"""
from contextlib import closing
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))

from s2_a_samples import create_fixture_database
from s2_b_samples import build_runtime_dataset
from novel_writer.application import backups
from novel_writer.application.backup_staging import StagingError
from novel_writer.application.skill_import import SkillLibrary
from novel_writer.storage.backup_validation import validate_database
from novel_writer.storage.sqlite_repository import SQLiteRepository


class BackupFaultTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="novel-backup-faults-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "fictional.sqlite3"
        self.archive = self.root / "complete.nwbak"
        self.target = self.root / "restored"
        create_fixture_database(self.source, build_runtime_dataset())

    def cleanup_failure(self, error_type=OSError):
        original = backups.OwnedTemporaryDirectory

        class FailureAfterCleanup(original):
            def __exit__(self, *arguments):
                result = super().__exit__(*arguments)
                if Path(self.name).name.startswith(".novel-backup-"):
                    raise error_type("fictional-private-cleanup-path")
                return result

        return patch.object(backups, "OwnedTemporaryDirectory", FailureAfterCleanup)

    def test_owned_staging_error_after_publish_preserves_success_and_warning(self):
        with self.cleanup_failure(StagingError):
            result = backups.create_backup(self.source, self.archive)
        self.assertTrue(self.archive.is_file())
        self.assertTrue(result.cleanup_warnings)
        self.assertNotIn("fictional-private-cleanup-path", str(result.cleanup_warnings))
        self.assertTrue(backups.preflight_backup(self.archive)["verified"])

    def test_backup_cleanup_failure_preserves_published_manifest_and_reports_warning(self):
        before = self.source.read_bytes()
        with self.cleanup_failure():
            try:
                result = backups.create_backup(self.source, self.archive)
            except Exception as error:
                self.fail(f"已发布包不能因清理失败被报告失败：{type(error).__name__}")
        self.assertTrue(self.archive.is_file())
        warnings = getattr(result, "cleanup_warnings", [])
        self.assertTrue(warnings)
        self.assertNotIn("fictional-private-cleanup-path", str(warnings))
        with zipfile.ZipFile(self.archive) as package:
            self.assertEqual(backups.strict_loads(package.read("manifest.json")), result)
        self.assertTrue(backups.preflight_backup(self.archive)["verified"])
        self.assertEqual(self.source.read_bytes(), before)

    def test_restore_cleanup_failure_preserves_verified_database_and_reports_warning(self):
        backups.create_backup(self.source, self.archive)
        with self.cleanup_failure():
            try:
                result = backups.restore_backup(self.archive, self.target)
            except Exception as error:
                self.fail(f"已发布恢复库不能因清理失败被报告失败：{type(error).__name__}")
        self.assertTrue(result["verified"])
        self.assertEqual(Path(result["database_path"]), self.target / "novels.sqlite3")
        self.assertTrue(result.get("cleanup_warnings"))
        self.assertNotIn("fictional-private-cleanup-path", str(result["cleanup_warnings"]))
        self.assertEqual(validate_database(result["database_path"])["counts"], result["counts"])
        with closing(sqlite3.connect(self.source)) as source, closing(sqlite3.connect(result["database_path"])) as restored:
            for table in ("projects", "project_snapshots", "skills"):
                query = f"SELECT * FROM {table} ORDER BY 1,2"
                self.assertEqual(source.execute(query).fetchall(), restored.execute(query).fetchall())

    def test_cleanup_failure_before_publish_does_not_report_success(self):
        with self.cleanup_failure(), patch.object(backups, "_write_all", side_effect=OSError("fictional-write-failure")):
            with self.assertRaises(backups.BackupError) as caught:
                backups.create_backup(self.source, self.archive)
        self.assertFalse(self.archive.exists())
        self.assertNotIn("fictional-private-cleanup-path", str(caught.exception))
        self.assertNotIn("fictional-write-failure", str(caught.exception))

    def test_invalid_deflate_stream_returns_controlled_error_and_no_target(self):
        backups.create_backup(self.source, self.archive)
        with zipfile.ZipFile(self.archive) as package:
            header = package.getinfo("snapshot.sqlite3").header_offset
        damaged = bytearray(self.archive.read_bytes())
        name_length, extra_length = struct.unpack_from("<HH", damaged, header + 26)
        compressed_start = header + 30 + name_length + extra_length
        # DEFLATE 的首块设为保留 BTYPE=3，实际触发解压错误，不只改 CRC。
        damaged[compressed_start] = (damaged[compressed_start] & 0xF8) | 7
        corrupted = self.root / "corrupt.nwbak"
        corrupted.write_bytes(damaged)
        for operation in (lambda: backups.preflight_backup(corrupted),
                          lambda: backups.restore_backup(corrupted, self.target)):
            with self.subTest(operation=operation):
                try:
                    operation()
                except Exception as error:
                    self.assertIsInstance(error, backups.BackupError)
                    self.assertNotIn("invalid block type", str(error))
                else:
                    self.fail("损坏的压缩流必须被拒绝")
        self.assertFalse(self.target.exists())
        self.assertFalse(any(path.name.startswith(".novel-backup-") for path in self.root.iterdir()))

    def add_multi_step_content(self):
        SkillLibrary(self.source).import_files([{"path": "SKILL.md", "content": "# 虚构分步样本\n" + "x" * 700000}])

    def test_cancel_after_capture_has_started_removes_unpublished_output(self):
        self.add_multi_step_content()
        before = self.source.read_bytes()
        cancelled = threading.Event()
        started = []

        def progress(stage, done, total):
            if stage == "capture" and 0 < done < total:
                started.append((done, total))
                cancelled.set()

        with self.assertRaises(backups.BackupError) as caught:
            backups.create_backup(self.source, self.archive, cancel=cancelled.is_set, progress=progress)
        self.assertTrue(started, "必须实际进入分步采集")
        self.assertEqual(caught.exception.code, "cancelled")
        self.assertFalse(self.archive.exists())
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(list(self.root.iterdir()), [self.source])

    def test_repeated_source_commits_observe_capture_deadline_without_publishing(self):
        self.add_multi_step_content()
        commits = []
        real_monotonic = time.monotonic

        def monotonic():
            return real_monotonic() + (120 if len(commits) >= 3 else 0)

        def progress(stage, done, total):
            if stage == "capture" and done < total and len(commits) < 3:
                repository = SQLiteRepository(self.source)
                state = repository.get("s2-a-project-one")
                state["worldbuilding"] = f"虚构并发提交 {len(commits) + 1}"
                saved = repository.save(state, expected_revision=state["revision"])
                commits.append(saved["revision"])

        with patch.object(backups.time, "monotonic", side_effect=monotonic):
            with self.assertRaises(backups.BackupError) as caught:
                backups.create_backup(self.source, self.archive, limits=backups.Limits(seconds=60), progress=progress)
        self.assertEqual(commits, [4, 5, 6])
        self.assertEqual(caught.exception.code, "timeout")
        self.assertFalse(self.archive.exists())
        self.assertEqual(SQLiteRepository(self.source).get("s2-a-project-one")["revision"], 6)
        self.assertEqual(list(self.root.iterdir()), [self.source])


if __name__ == "__main__":
    unittest.main()
