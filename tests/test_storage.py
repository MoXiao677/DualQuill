"""使用真实临时 SQLite 文件验证持久化、冲突与事务回滚。"""

from copy import deepcopy
from contextlib import closing
from importlib import import_module, util
from pathlib import Path
import sqlite3
import json
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from novel_writer.domain.models import NovelDocument, NovelProject
from novel_writer.storage.json_codec import document_to_dict


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(util.find_spec("novel_writer.storage.sqlite_repository"), "磁盘持久化模块尚未实现")
        module = import_module("novel_writer.storage.sqlite_repository")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "novels.sqlite3"
        self.repository_type = module.SQLiteRepository
        self.repo = self.repository_type(self.path)
        self.state = {
            "workspace_version": 1, "revision": 0,
            "document": document_to_dict(NovelDocument(project=NovelProject(title="测试小说"))),
            "ideas": {}, "worldbuilding": "雾港", "writing_rules": "第三人称",
        }

    def test_reopening_database_preserves_chinese_content(self):
        saved = self.repo.create(self.state)
        loaded = self.repository_type(self.path).get(saved["document"]["project"]["id"])
        self.assertEqual(loaded, saved)
        self.assertEqual(loaded["worldbuilding"], "雾港")

    def test_stale_editor_cannot_overwrite_newer_save(self):
        first = self.repo.create(self.state)
        newer = deepcopy(first)
        newer["worldbuilding"] = "新版设定"
        self.repo.save(newer, expected_revision=1)
        stale = deepcopy(first)
        stale["worldbuilding"] = "旧窗口内容"
        with self.assertRaisesRegex(ValueError, "更新"):
            self.repo.save(stale, expected_revision=1)
        self.assertEqual(self.repo.get(first["document"]["project"]["id"])["worldbuilding"], "新版设定")

    def test_failed_snapshot_insert_rolls_back_current_document(self):
        first = self.repo.create(self.state)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("CREATE TRIGGER fail_save BEFORE INSERT ON project_snapshots WHEN NEW.revision > 1 BEGIN SELECT RAISE(ABORT, 'simulated disk error'); END")
        changed = deepcopy(first)
        changed["worldbuilding"] = "未成功保存的设定"
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.save(changed, expected_revision=1)
        self.assertEqual(self.repo.get(first["document"]["project"]["id"]), first)

    def test_project_history_cannot_be_overwritten_or_deleted(self):
        self.repo.create(self.state)
        for statement in ("UPDATE project_snapshots SET payload = '{}'", "DELETE FROM project_snapshots"):
            with self.subTest(statement=statement), closing(sqlite3.connect(self.path)) as connection, connection:
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(statement)

    def test_every_successful_save_keeps_previous_whole_project_snapshot(self):
        first = self.repo.create(self.state)
        changed = deepcopy(first)
        changed["writing_rules"] = "新的文风"
        saved = self.repo.save(changed, expected_revision=1)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            snapshots = connection.execute("SELECT revision FROM project_snapshots ORDER BY revision").fetchall()
        self.assertEqual(snapshots, [(1,), (2,)])
        self.assertEqual(saved["revision"], 2)

    def test_invalid_worldbuilding_cannot_reach_disk(self):
        self.state["worldbuilding"] = {}
        with self.assertRaises(ValueError):
            self.repo.create(self.state)
        self.assertEqual(self.repo.list_projects(), [])

    def test_duplicate_project_creation_does_not_replace_existing_content(self):
        first = self.repo.create(self.state)
        self.state["worldbuilding"] = "不可覆盖"
        with self.assertRaises(ValueError):
            self.repo.create(self.state)
        self.assertEqual(self.repo.get(first["document"]["project"]["id"]), first)

    def test_optional_document_fields_are_normalized_before_storage(self):
        self.state["document"] = {"schema_version": 1, "project": {"title": "只有书名的小说"}}
        original = deepcopy(self.state)
        from novel_writer.domain import models
        with patch.object(models, "uuid4", wraps=models.uuid4) as new_id:
            first = self.repo.create(self.state)
            self.assertIn("versions", first["document"])
            self.assertEqual(self.repo.get(first["document"]["project"]["id"]), first)
            saved = self.repo.save(first, expected_revision=1)
            self.assertEqual(self.repository_type(self.path).get(first["document"]["project"]["id"]), saved)
            self.assertEqual(new_id.call_count, 1, "只在明确新建时生成一次项目ID")
        self.assertEqual(self.state, original)
        self.assertEqual(first['document']['project'], saved['document']['project'])
        for field in ('id', 'created_at', 'updated_at'):
            self.assertTrue(first['document']['project'][field])
        with closing(sqlite3.connect(self.path)) as connection:
            payloads = connection.execute('SELECT payload FROM project_snapshots ORDER BY revision').fetchall()
        self.assertEqual([json.loads(row[0])['document']['project'] for row in payloads],
                         [first['document']['project'], first['document']['project']])

    def test_missing_persisted_identity_or_times_are_rejected_on_read_and_save(self):
        first = self.repo.create(self.state)
        project = first['document']['project']
        original = self.path.read_bytes()
        for field in ('id', 'created_at', 'updated_at'):
            with self.subTest(field=field):
                bad = deepcopy(first)
                del bad['document']['project'][field]
                with self.assertRaises(ValueError):
                    self.repo.save(bad, expected_revision=1)
                self.assertEqual(self.path.read_bytes(), original)
                path = Path(self.temp.name) / (field + '.sqlite3')
                repository = self.repository_type(path)
                payload = json.dumps(bad)
                with closing(sqlite3.connect(path)) as connection, connection:
                    connection.execute('INSERT INTO projects VALUES (?,?,?,?,?)',
                        (project['id'], project['title'], 1, payload, project['updated_at']))
                    connection.execute('INSERT INTO project_snapshots VALUES (?,?,?,?)',
                        (project['id'], 1, payload, project['updated_at']))
                before = path.read_bytes()
                with self.assertRaises(ValueError):
                    repository.get(project['id'])
                self.assertEqual(path.read_bytes(), before)

    def test_creation_defaults_do_not_accept_unknown_or_future_formats(self):
        for variant in ('workspace', 'document', 'unknown'):
            with self.subTest(variant=variant):
                state = deepcopy(self.state)
                state['document'] = {'schema_version': 1, 'project': {'title': '虚构新建'}}
                if variant == 'workspace': state['workspace_version'] = 99
                elif variant == 'document': state['document']['schema_version'] = 99
                else: state['document']['project']['unknown'] = True
                with self.assertRaises(ValueError):
                    self.repo.create(state)
                self.assertEqual(self.repo.list_projects(), [])

    def test_sql_replace_cannot_overwrite_historical_snapshot(self):
        self.repo.create(self.state)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT OR REPLACE INTO project_snapshots SELECT project_id, revision, '{}', saved_at FROM project_snapshots")

    def test_connection_is_closed_when_initial_configuration_fails(self):
        connection = MagicMock()
        connection.execute.side_effect = sqlite3.OperationalError("configuration failure")
        with patch("novel_writer.storage.sqlite_repository.sqlite3.connect", return_value=connection):
            with self.assertRaises(sqlite3.OperationalError):
                self.repository_type(self.path)
        connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
