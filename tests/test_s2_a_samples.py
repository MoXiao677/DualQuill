"""S2-A 的样本审计；不验收尚未实现的备份/恢复功能。"""
from copy import deepcopy
from contextlib import closing
from dataclasses import fields
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
from s2_a_samples import (
    MODEL_TYPES, TABLE_COLUMNS, assert_fixture_dataset, build_dataset, create_fixture_database,
    inspect_fixture_schema, proposed_copy_mapper, transform_fixture_ids,
)
from novel_writer.storage.sqlite_repository import SQLiteRepository, WorkspaceHistoryValidator, validate_workspace
from novel_writer.storage.skills_repository import SkillsRepository


def all_states(dataset):
    return [item["payload"] for item in dataset["projects"] + dataset["project_snapshots"]]


def mutate_version(dataset, kind, change):
    for state in all_states(dataset):
        for version in state["document"]["versions"]:
            if version["entity_type"] == kind and version["version_number"] == 1:
                change(version["snapshot"])


class S2ASampleTests(unittest.TestCase):
    def setUp(self):
        self.dataset = build_dataset()
        self.temp = tempfile.TemporaryDirectory(prefix="novel-s2-a-")
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "fictional.sqlite3"

    def test_frozen_fixture_contains_all_persistent_fields_and_can_be_reopened(self):
        frozen = json.loads((ROOT / "tests/fixtures/s2_a/full-dataset-v1.json").read_text(encoding="utf8"))
        self.assertEqual(frozen, self.dataset)
        assert_fixture_dataset(frozen)
        create_fixture_database(self.database, frozen)
        reopened = SQLiteRepository(self.database)
        for row in frozen["projects"]:
            self.assertEqual(reopened.get(row["id"]), row["payload"])
        skills = SkillsRepository(self.database)
        for row in frozen["skills"]:
            expected = {**row, "files": row["files_json"]}
            del expected["files_json"]
            self.assertEqual(skills.get(row["id"]), expected)
        for state in all_states(frozen):
            for version in state["document"]["versions"]:
                expected = {item.name for item in fields(MODEL_TYPES[version["entity_type"]])}
                if version["entity_type"] == "chapter":
                    expected.remove("current_version_id")
                self.assertEqual(set(version["snapshot"]), expected)

    def test_real_sqlite_schema_matches_frozen_profile_with_indexes_and_foreign_key(self):
        create_fixture_database(self.database, self.dataset)
        profile = inspect_fixture_schema(self.database)
        expected = json.loads((ROOT / "tests/fixtures/s2_a/schema-v1.json").read_text(encoding="utf8"))
        self.assertEqual(profile, expected)
        self.assertEqual(profile["user_version"], 1)
        self.assertEqual(set(profile["tables"]), set(TABLE_COLUMNS))
        for name, columns in TABLE_COLUMNS.items():
            self.assertEqual([column[1] for column in profile["tables"][name]["columns"]], columns)
            self.assertEqual(len(profile["tables"][name]["indexes"]), 1)
        foreign_keys = profile["tables"]["project_snapshots"]["foreign_keys"]
        self.assertEqual(foreign_keys[0][2:5], ["projects", "project_id", "id"])
        self.assertEqual(set(profile["triggers"]), {"snapshots_no_update", "snapshots_no_delete", "snapshots_no_replace"})
        self.assertEqual(profile["tables"]["projects"]["columns"][0][3], 0, "TEXT PRIMARY KEY 未显式 NOT NULL")

    def test_historical_invalid_chapter_references_are_rejected_by_design_oracle(self):
        for kind, change in (
            ("book_outline", lambda value: value["volumes"][0]["chapter_ids"].append("missing-chapter")),
            ("chapter_outline", lambda value: value.update(chapter_id="missing-chapter")),
        ):
            with self.subTest(kind=kind):
                invalid = deepcopy(self.dataset)
                mutate_version(invalid, kind, change)
                # S2-B 已修复生产历史路径；单个 workspace 本身不携带首现上下文。
                with self.assertRaisesRegex(ValueError, "历史.*关联"):
                    WorkspaceHistoryValidator().validate(invalid["project_snapshots"][0]["payload"])
                with self.assertRaisesRegex(ValueError, "历史章节引用非法"):
                    assert_fixture_dataset(invalid)

    def test_historical_character_and_scene_references_are_rejected(self):
        for kind, change in (
            ("character", lambda value: value["relationships"][0].update(target_character_id="missing-character")),
            ("chapter_outline", lambda value: value["character_ids"].append("missing-character")),
            ("chapter_outline", lambda value: value["scenes"][0]["character_ids"].append("missing-character")),
        ):
            with self.subTest(kind=kind):
                invalid = deepcopy(self.dataset)
                mutate_version(invalid, kind, change)
                with self.assertRaisesRegex(ValueError, "历史.*关联"):
                    WorkspaceHistoryValidator().validate(invalid["project_snapshots"][0]["payload"])
                with self.assertRaisesRegex(ValueError, "历史.*引用非法"):
                    assert_fixture_dataset(invalid)

    def test_historical_semantic_errors_are_rejected(self):
        for kind, change in (
            ("book_outline", lambda value: value["volumes"][0].update(number=0)),
            ("book_outline", lambda value: value["volumes"][0]["chapter_ids"].append("shared-chapter-1")),
            ("chapter_outline", lambda value: value["scenes"][0].update(order=0)),
            ("chapter", lambda value: value.update(number=0)),
            ("character", lambda value: value.update(name="   ")),
            ("project", lambda value: value.update(title="   ")),
        ):
            with self.subTest(kind=kind):
                invalid = deepcopy(self.dataset)
                mutate_version(invalid, kind, change)
                with self.assertRaises(ValueError):
                    assert_fixture_dataset(invalid)

    def test_history_only_chapter_remains_valid_in_its_first_available_context(self):
        historical = deepcopy(self.dataset)
        for state in all_states(historical):
            if state["revision"] > 1:
                state["document"]["chapters"] = state["document"]["chapters"][:1]
                state["document"]["book_outline"]["volumes"] = state["document"]["book_outline"]["volumes"][:1]
                state["ideas"].pop("shared-chapter-2")
        assert_fixture_dataset(historical)
        mapper = proposed_copy_mapper("84c59fa9-ab19-462d-8f9e-8f7b31867879")
        copied = transform_fixture_ids(historical, mapper)
        assert_fixture_dataset(copied)
        early = copied["project_snapshots"][0]["payload"]["document"]
        self.assertEqual(early["book_outline"]["volumes"][1]["chapter_ids"][0],
                         mapper("s2-a-project-one", "chapter", "shared-chapter-2"))

    def test_future_entity_does_not_repair_earlier_invalid_reference(self):
        invalid = deepcopy(self.dataset)
        mutate_version(invalid, "book_outline", lambda value: value["volumes"][0]["chapter_ids"].append("future-chapter"))
        for state in all_states(invalid):
            if state["revision"] == 3:
                future = deepcopy(state["document"]["chapters"][1])
                future.update(id="future-chapter", number=3)
                state["document"]["chapters"].append(future)
        validate_workspace(invalid["projects"][0]["payload"])
        with self.assertRaisesRegex(ValueError, "历史章节引用非法"):
            assert_fixture_dataset(invalid)

    def test_copy_mapping_is_scoped_repeatable_and_reversible_without_replacing_text(self):
        mapper = proposed_copy_mapper("84c59fa9-ab19-462d-8f9e-8f7b31867879")
        mapping = {}
        def remember(project_id, kind, identifier):
            mapped = mapper(project_id, kind, identifier)
            mapping[(project_id, kind, identifier)] = mapped
            return mapped
        copied = transform_fixture_ids(self.dataset, remember)
        assert_fixture_dataset(copied)
        self.assertEqual(copied, transform_fixture_ids(self.dataset, mapper))
        self.assertNotEqual(copied["projects"][0]["id"], copied["projects"][1]["id"])
        self.assertNotEqual(copied["projects"][0]["payload"]["document"]["chapters"][0]["id"],
                            copied["projects"][1]["payload"]["document"]["chapters"][0]["id"])
        reverse = {(mapper(project_id, "project", project_id), kind, new): old
                   for (project_id, kind, old), new in mapping.items()}
        self.assertEqual(transform_fixture_ids(copied, lambda project_id, kind, identifier: reverse[(project_id, kind, identifier)]),
                         self.dataset)
        self.assertIn("shared-chapter-1", copied["projects"][0]["payload"]["document"]["chapters"][0]["content"])
        self.assertEqual(copied["skills"], self.dataset["skills"])

    def test_missing_persistent_field_and_sql_or_history_mismatch_are_rejected(self):
        mutations = [
            lambda value: value["projects"][0]["payload"]["document"]["project"].pop("language"),
            lambda value: value["projects"][0].update(title="错误SQL标题"),
            lambda value: value["project_snapshots"].pop(0),
            lambda value: value["skills"][0].update(primary_path="教材/missing.md"),
        ]
        for change in mutations:
            with self.subTest(change=change):
                invalid = deepcopy(self.dataset)
                change(invalid)
                with self.assertRaises(ValueError):
                    assert_fixture_dataset(invalid)

    def test_uncheckpointed_wal_fixture_proves_main_file_is_not_complete(self):
        create_fixture_database(self.database, self.dataset)
        holder = sqlite3.connect(self.database)
        self.addCleanup(holder.close)
        self.assertEqual(holder.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
        holder.execute("PRAGMA wal_autocheckpoint=0")
        holder.execute("BEGIN")
        holder.execute("SELECT revision FROM projects").fetchall()
        repository = SQLiteRepository(self.database)
        changed = repository.get("s2-a-project-one")
        changed["worldbuilding"] = "虚构 WAL 内已提交文字"
        repository.save(changed, expected_revision=3)
        self.assertGreater(Path(str(self.database) + "-wal").stat().st_size, 0)
        self.assertEqual(repository.get("s2-a-project-one")["revision"], 4)
        # 只用于独立样本反例：immutable 明确忽略 WAL，观察裸主文件缺少的提交。
        with closing(sqlite3.connect(self.database.as_uri() + "?immutable=1", uri=True)) as bare:
            self.assertEqual(bare.execute("SELECT revision FROM projects WHERE id=?", ("s2-a-project-one",)).fetchone()[0], 3)

    def test_sample_database_path_must_not_overwrite_an_existing_file(self):
        self.database.write_bytes(b"fictional-existing-file")
        with self.assertRaisesRegex(ValueError, "不存在的新文件"):
            create_fixture_database(self.database, self.dataset)
        self.assertEqual(self.database.read_bytes(), b"fictional-existing-file")


if __name__ == "__main__":
    unittest.main()
