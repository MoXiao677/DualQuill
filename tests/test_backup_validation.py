"""S2-B 严格校验；所有库与原文均为独立虚构样本。"""
from contextlib import closing
from copy import deepcopy
from importlib import import_module, util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import tracemalloc
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
from s2_a_samples import build_dataset, create_fixture_database, inspect_fixture_schema
from novel_writer.storage.json_codec import document_from_json
from novel_writer.storage.sqlite_repository import SQLiteRepository


def states(dataset):
    return [row["payload"] for row in dataset["projects"] + dataset["project_snapshots"]]


def mutate_versions(dataset, kind, change):
    for state in states(dataset):
        for version in state["document"]["versions"]:
            if version["entity_type"] == kind and version["version_number"] == 1:
                change(version["snapshot"])


def history_only(dataset):
    for state in states(dataset):
        if state["revision"] > 1:
            state["document"]["chapters"] = state["document"]["chapters"][:1]
            state["document"]["book_outline"]["volumes"] = state["document"]["book_outline"]["volumes"][:1]
            state["ideas"].pop("shared-chapter-2")


class BackupValidationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(util.find_spec("novel_writer.storage.backup_validation"), "S2-B 严格校验模块尚未实现")
        self.validator = import_module("novel_writer.storage.backup_validation")
        self.temp = tempfile.TemporaryDirectory(prefix="novel-s2-b-validation-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "fictional.sqlite3"
        self.dataset = build_dataset()

    def database(self, dataset=None):
        create_fixture_database(self.path, self.dataset if dataset is None else dataset)
        return self.path

    def test_full_fixture_manifest_matches_frozen_contract_and_is_read_only(self):
        self.database()
        before = self.path.read_bytes()
        result = self.validator.validate_database(self.path)
        expected = json.loads((ROOT / "docs/s2-a-manifest.example.json").read_text(encoding="utf-8"))
        self.assertEqual(result["database"], expected["database"])
        self.assertEqual(result["counts"], expected["counts"])
        self.assertEqual(result["project_ids"], expected["scope"]["project_ids"])
        self.assertEqual(result["skill_ids"], expected["scope"]["skills"]["ids"])
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual([path.name for path in self.path.parent.iterdir()], [self.path.name])

    def test_trusted_schema_and_all_three_history_protections(self):
        with closing(sqlite3.connect(self.path)) as connection:
            self.validator.create_schema(connection)
        expected = json.loads((ROOT / "tests/fixtures/s2_a/schema-v1.json").read_text(encoding="utf-8"))
        self.assertEqual(inspect_fixture_schema(self.path), expected)
        empty = self.validator.validate_database(self.path)
        self.assertEqual(empty["counts"], {"projects": [], "skills": 0})
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("INSERT INTO projects VALUES ('p','p',1,'{}','t')")
            connection.execute("INSERT INTO project_snapshots VALUES ('p',1,'{}','t')")
            for sql in ("UPDATE project_snapshots SET payload='bad'", "DELETE FROM project_snapshots",
                        "INSERT OR REPLACE INTO project_snapshots VALUES ('p',1,'bad','t')"):
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(sql)

    def test_strict_json_rejects_duplicates_constants_bad_utf8_bom_surrogates_and_depth(self):
        marker = "PRIVATE-FICTIONAL-TEXT"
        values = ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":-Infinity}',
                  '{"x":1e999}', '\ufeff{}', b'\xef\xbb\xbf{}', b'\xff',
                  '"\\ud800"', '[' * 100 + '0' + ']' * 100, '{"' + marker + '":1,"' + marker + '":2}']
        for value in values:
            with self.subTest(value=type(value).__name__), self.assertRaises(self.validator.BackupValidationError) as error:
                self.validator.strict_loads(value)
            self.assertNotIn(marker, str(error.exception))
        self.assertEqual(self.validator.strict_loads('{"正文":"\\ufeff原文\\r\\n  "}'), {"正文": "\ufeff原文\r\n  "})

    def test_json_depth_is_rejected_before_json_loads_allocates_objects(self):
        codec = import_module("novel_writer.storage.json_codec")
        text = "[" * 65 + "0" + "]" * 65
        with patch.object(codec.json, "loads", return_value=[]) as parser:
            with self.assertRaisesRegex(self.validator.BackupValidationError, "深度.*64"):
                self.validator.strict_loads(text)
            parser.assert_not_called()
        self.assertEqual(self.validator.strict_loads("[" * 64 + "0" + "]" * 64),
                         json.loads("[" * 64 + "0" + "]" * 64))

    def test_json_million_node_limit_precedes_json_loads(self):
        codec = import_module("novel_writer.storage.json_codec")
        text = "[" + "{}," * 999_999 + "{}]"
        with patch.object(codec.json, "loads", return_value=[]) as parser:
            with self.assertRaisesRegex(self.validator.BackupValidationError, "节点.*限额"):
                self.validator.strict_loads(text)
            parser.assert_not_called()

    def test_json_node_budget_counts_keys_containers_and_primitive_values(self):
        codec = import_module("novel_writer.storage.json_codec")
        expected = {"a": [True, None, {"b": "v"}]}
        text = json.dumps(expected)
        with patch.object(codec, "MAX_JSON_NODES", 8, create=True):
            self.assertEqual(self.validator.strict_loads(text), expected)
        with patch.object(codec, "MAX_JSON_NODES", 7, create=True):
            with self.assertRaisesRegex(self.validator.BackupValidationError, "节点.*限额"):
                self.validator.strict_loads(text)

    def test_json_lexical_limits_preserve_quotes_escapes_and_string_contents(self):
        codec = import_module("novel_writer.storage.json_codec")
        values = ['"', '\\', '\\"', '\\\\"', '}{][\n', '\\u0022', '中文 \ufeff', '{}[],:"\\' * 1000]
        text = json.dumps(values, ensure_ascii=False)
        with patch.object(codec, "MAX_JSON_DEPTH", 1), patch.object(codec, "MAX_JSON_NODES", len(values) + 1, create=True):
            self.assertEqual(self.validator.strict_loads(text), values)

    def test_json_wide_array_walk_has_no_per_element_pending_tuple_allocation(self):
        text = "[" + "0," * 99_999 + "0]"
        tracemalloc.start()
        try:
            value = self.validator.strict_loads(text)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(len(value), 100_000)
        self.assertLess(peak, 3 * 1024 * 1024, "十万个节点的后处理不应另建十万个待遍历元组")

    def test_unknown_objects_constraints_and_unprotected_history_are_rejected(self):
        mutations = ["CREATE TABLE extra(x)", "CREATE VIEW extra AS SELECT * FROM projects",
                     "CREATE INDEX extra ON projects(title)", "DROP TRIGGER snapshots_no_update",
                     "PRAGMA user_version=0", "PRAGMA user_version=2",
                     "DROP TRIGGER snapshots_no_delete; CREATE TRIGGER snapshots_no_delete BEFORE DELETE ON project_snapshots BEGIN SELECT 1; END"]
        for number, sql in enumerate(mutations):
            with self.subTest(sql=sql):
                path = self.path.parent / f"schema-{number}.sqlite3"
                create_fixture_database(path, self.dataset)
                with closing(sqlite3.connect(path)) as connection, connection:
                    connection.executescript(sql)
                with self.assertRaises(self.validator.BackupValidationError):
                    self.validator.validate_database(path)

    def test_ddl_changed_without_pragma_changes_is_rejected(self):
        profile = json.loads((ROOT / "tests/fixtures/s2_a/schema-v1.json").read_text(encoding="utf-8"))
        with closing(sqlite3.connect(self.path)) as connection:
            for name, table in profile["tables"].items():
                ddl = table["ddl"]
                if name == "projects":
                    ddl = ddl.replace("title TEXT NOT NULL", "title TEXT NOT NULL CHECK(length(title)>0)")
                connection.execute(ddl)
            for ddl in profile["triggers"].values():
                connection.execute(ddl)
            connection.execute("PRAGMA user_version=1")
        with self.assertRaises(self.validator.BackupValidationError):
            self.validator.validate_database(self.path)

    def test_persistent_field_type_and_metadata_errors_are_rejected(self):
        mutations = [
            lambda d: d["projects"][0]["payload"]["document"]["project"].pop("language"),
            lambda d: d["projects"][0]["payload"]["document"].update(unknown="private"),
            lambda d: d["projects"][0]["payload"].update(workspace_version=True),
            lambda d: d["projects"][0]["payload"]["document"].update(schema_version=2),
            lambda d: d["projects"][0].update(title="metadata mismatch"),
            lambda d: d["projects"][0].update(updated_at="2026-10-14T00:00:13"),
            lambda d: d["skills"][0].update(id=None),
            lambda d: d["projects"][0].update(revision=1.5),
            lambda d: d["project_snapshots"].pop(0),
            lambda d: d["project_snapshots"][0].update(saved_at="invalid"),
            lambda d: d["project_snapshots"][1]["payload"]["document"]["versions"][0].update(change_note="changed"),
            lambda d: d["projects"][0]["payload"]["document"]["chapters"][0].update(number=True),
            lambda d: d["projects"][0]["payload"]["document"]["versions"][0].update(source="unknown"),
        ]
        for number, change in enumerate(mutations):
            with self.subTest(number=number):
                invalid = deepcopy(self.dataset)
                change(invalid)
                path = self.path.parent / f"data-{number}.sqlite3"
                create_fixture_database(path, invalid)
                with self.assertRaises(self.validator.BackupValidationError):
                    self.validator.validate_database(path)

    def test_every_snapshot_kind_has_recursive_semantics(self):
        mutations = [
            ("project", lambda s: s.update(title="  ")),
            ("chapter", lambda s: s.update(number=0)),
            ("chapter", lambda s: s.update(title="  ")),
            ("character", lambda s: s.update(name="  ")),
            ("character", lambda s: s["relationships"][0].update(target_character_id="missing")),
            ("book_outline", lambda s: s["volumes"][0].update(number=0)),
            ("book_outline", lambda s: s["volumes"][0]["chapter_ids"].append("shared-chapter-1")),
            ("book_outline", lambda s: s["volumes"][0]["chapter_ids"].append("missing")),
            ("chapter_outline", lambda s: s.update(chapter_id="missing")),
            ("chapter_outline", lambda s: s["character_ids"].append("missing")),
            ("chapter_outline", lambda s: s["scenes"][0]["character_ids"].append("missing")),
            ("chapter_outline", lambda s: s["scenes"][0].update(order=0)),
            ("chapter_outline", lambda s: s["scenes"][0].pop("location")),
        ]
        for number, (kind, change) in enumerate(mutations):
            with self.subTest(kind=kind, number=number):
                invalid = deepcopy(self.dataset)
                mutate_versions(invalid, kind, change)
                path = self.path.parent / f"versions-{number}.sqlite3"
                create_fixture_database(path, invalid)
                with self.assertRaises(self.validator.BackupValidationError):
                    self.validator.validate_database(path)

    def test_history_only_unversioned_chapter_uses_first_context(self):
        history_only(self.dataset)
        self.database()
        self.assertEqual(self.validator.validate_database(self.path)["counts"]["projects"][0]["chapters"], 1)
        repo = SQLiteRepository(self.path)
        saved = repo.get("s2-a-project-one")
        saved["worldbuilding"] += "进一步保存"
        self.assertEqual(repo.save(saved, expected_revision=3)["revision"], 4)
        self.validator.validate_database(self.path)

    def test_future_chapter_does_not_repair_first_context(self):
        mutate_versions(self.dataset, "book_outline", lambda s: s["volumes"][0]["chapter_ids"].append("future"))
        for state in states(self.dataset):
            if state["revision"] == 3:
                chapter = deepcopy(state["document"]["chapters"][1])
                chapter.update(id="future", number=3)
                state["document"]["chapters"].append(chapter)
        self.database()
        with self.assertRaises(self.validator.BackupValidationError):
            self.validator.validate_database(self.path)

    def test_identity_reuse_across_history_types_is_rejected(self):
        for state in states(self.dataset):
            if state["revision"] > 1:
                chapter = state["document"]["chapters"].pop()
                state["document"]["book_outline"]["volumes"].pop()
                state["ideas"].pop(chapter["id"])
                character = deepcopy(state["document"]["characters"][1])
                character["id"] = chapter["id"]
                state["document"]["characters"].append(character)
        self.database()
        with self.assertRaises(self.validator.BackupValidationError):
            self.validator.validate_database(self.path)

    def test_skills_paths_primary_and_raw_content_rules(self):
        mutations = [lambda s: s.update(primary_path="教材/missing.md"),
                     lambda s: s["files_json"][0].update(path="../bad.md"),
                     lambda s: s["files_json"][0].update(path="教材/skill.md"),
                     lambda s: s["files_json"][0].update(extra=True),
                     lambda s: s.update(imported_at="2026-10-14T00:00:00+08:00"),
                     lambda s: s.update(id="  "),
                     lambda s: s["files_json"][0].update(content="x" * (2 * 1024 * 1024))]
        for number, change in enumerate(mutations):
            invalid = deepcopy(self.dataset)
            change(invalid["skills"][0])
            path = self.path.parent / f"skills-{number}.sqlite3"
            create_fixture_database(path, invalid)
            with self.subTest(number=number), self.assertRaises(self.validator.BackupValidationError):
                self.validator.validate_database(path)

    def test_cancel_callback_is_observed_during_validation(self):
        self.database()
        calls = []
        class Cancelled(RuntimeError):
            pass
        def check():
            calls.append(True)
            if len(calls) == 7:
                raise Cancelled("cancelled")
        with self.assertRaises(Cancelled):
            self.validator.validate_database(self.path, check=check)
        self.assertEqual(len(calls), 7)

    def test_integrity_progress_cancellation_preserves_original_exception(self):
        self.database()
        before = self.path.read_bytes()
        observed = {"statement": None, "in_progress": False, "cancelled": False}
        class Cancelled(RuntimeError):
            pass
        cancellation = Cancelled("fictional one-shot cancellation")
        class ObservedConnection(sqlite3.Connection):
            def set_progress_handler(self, callback, interval):
                def progress():
                    observed["in_progress"] = True
                    try:
                        return callback()
                    finally:
                        observed["in_progress"] = False
                # Real SQLite execution, at a deterministic instruction boundary.
                super().set_progress_handler(progress, 1)
        real_connect = sqlite3.connect
        def connect(*args, **kwargs):
            connection = real_connect(*args, **kwargs, factory=ObservedConnection)
            connection.set_trace_callback(lambda sql: observed.update(statement=sql))
            return connection
        def check():
            if (observed["in_progress"] and observed["statement"] == "PRAGMA integrity_check"
                    and not observed["cancelled"]):
                observed["cancelled"] = True
                raise cancellation
        with patch.object(self.validator.sqlite3, "connect", side_effect=connect):
            with self.assertRaises(Cancelled) as caught:
                self.validator.validate_database(self.path, check=check)
        self.assertIs(caught.exception, cancellation)
        self.assertTrue(observed["cancelled"])
        self.assertEqual(observed["statement"], "PRAGMA integrity_check")
        self.assertEqual(self.path.read_bytes(), before)

    def test_frozen_snapshot_refuses_wal_journal_mode(self):
        self.database()
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
        with self.assertRaises(self.validator.BackupValidationError):
            self.validator.validate_database(self.path)

    def test_oversized_non_json_text_is_refused_before_sql_text_is_returned(self):
        self.database()
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("UPDATE skills SET name=CAST(zeroblob(?) AS TEXT) WHERE id=?",
                               (65 * 1024 * 1024, "s2-a-skill-1"))
        statements = []
        original_connect = sqlite3.connect
        def traced_connect(*args, **kwargs):
            connection = original_connect(*args, **kwargs)
            connection.set_trace_callback(statements.append)
            return connection
        with patch.object(self.validator.sqlite3, "connect", side_effect=traced_connect):
            with self.assertRaisesRegex(self.validator.BackupValidationError, "限额"):
                self.validator.validate_database(self.path)
        self.assertFalse(any(statement.startswith("SELECT id,name,description") for statement in statements),
                         "超大文本列不得先取回 Python 再判断大小")

    def test_all_fifteen_sql_columns_have_pre_read_byte_limits(self):
        for table, columns in self.validator.TABLE_COLUMNS.items():
            for column in columns:
                with self.subTest(table=table, column=column):
                    path = self.path.parent / f"limit-{table}-{column}.sqlite3"
                    with closing(sqlite3.connect(path)) as connection, connection:
                        self.validator.create_schema(connection,version=2 if table=='content_blobs' else 1)
                        connection.execute("PRAGMA foreign_keys=OFF")
                        values = [1 if name == "revision" else "x" for name in columns]
                        values[columns.index(column)] = "字" * 43  # 129 UTF-8 字节，43 个字符。
                        connection.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", values)
                    with patch.object(self.validator, "MAX_SQL_VALUE_BYTES", 128, create=True):
                        with self.assertRaisesRegex(self.validator.BackupValidationError, "字节.*限额"):
                            self.validator.validate_database(path)

    def test_combined_row_limit_applies_when_each_column_fits(self):
        self.database()
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("UPDATE skills SET name=?, description=? WHERE id=?",
                               ("a" * 4096, "b" * 4096, "s2-a-skill-1"))
        with patch.object(self.validator, "MAX_SQL_ROW_BYTES", 8192, create=True):
            with self.assertRaisesRegex(self.validator.BackupValidationError, "整行字节.*限额"):
                self.validator.validate_database(self.path)

    def test_table_and_total_row_counts_are_bounded_before_payload_parsing(self):
        self.database()
        limits = [("MAX_DATABASE_ROWS", 10),
                  ("MAX_TABLE_ROWS", {"projects": 1, "project_snapshots": 100, "skills": 100}),
                  ("MAX_TABLE_ROWS", {"projects": 100, "project_snapshots": 5, "skills": 100}),
                  ("MAX_TABLE_ROWS", {"projects": 100, "project_snapshots": 100, "skills": 2})]
        for name, limit in limits:
            with self.subTest(limit=name), patch.object(self.validator, name, limit, create=True):
                with self.assertRaisesRegex(self.validator.BackupValidationError, "记录数.*限额"):
                    self.validator.validate_database(self.path)

    def test_manifest_ids_are_bounded_before_loading_large_identifiers(self):
        self.database()
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("UPDATE skills SET id=? WHERE id=?", ("x" * (512 * 1024 + 1), "s2-a-skill-1"))
        with self.assertRaisesRegex(self.validator.BackupValidationError, "清单.*ID.*限额"):
            self.validator.validate_database(self.path)

    def test_report_growth_accounts_for_json_escaping(self):
        self.database()
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("UPDATE skills SET id=? WHERE id=?", ("x" + "\x01" * 1000, "s2-a-skill-1"))
        with patch.object(self.validator, "MAX_REPORT_BYTES", 4096, create=True):
            with self.assertRaisesRegex(self.validator.BackupValidationError, "清单.*字节.*限额"):
                self.validator.validate_database(self.path)


class ProductionHistoryValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="novel-s2-b-production-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "fictional.sqlite3"
        self.dataset = build_dataset()

    def test_repository_read_rejects_invalid_historical_nested_reference(self):
        mutate_versions(self.dataset, "book_outline", lambda s: s["volumes"][0]["chapter_ids"].append("missing"))
        create_fixture_database(self.path, self.dataset)
        with self.assertRaisesRegex(ValueError, "历史|快照|关联"):
            SQLiteRepository(self.path).get("s2-a-project-one")

    def test_repository_create_rejects_invalid_historical_nested_reference(self):
        mutate_versions(self.dataset, "chapter_outline", lambda s: s["scenes"][0]["character_ids"].append("missing"))
        with self.assertRaisesRegex(ValueError, "历史|快照|关联"):
            SQLiteRepository(self.path).create(self.dataset["projects"][0]["payload"])

    def test_standalone_document_read_validates_available_history_context(self):
        mutate_versions(self.dataset, "character", lambda s: s["relationships"][0].update(target_character_id="missing"))
        text = json.dumps(self.dataset["projects"][0]["payload"]["document"])
        with self.assertRaisesRegex(ValueError, "历史|快照|关联"):
            document_from_json(text)


if __name__ == "__main__":
    unittest.main()
