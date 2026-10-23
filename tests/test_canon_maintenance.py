import unittest
from pathlib import Path
from uuid import uuid4

from novel_writer.application.canon_maintenance import CanonMaintenance, set_analyzer
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository


class CanonMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.db = Path.cwd() / ("canon-" + str(uuid4()) + ".sqlite3")
        self.addCleanup(lambda: self.db.unlink(missing_ok=True))
        self.service = NovelService(SQLiteRepository(self.db))
        created = self.service.create(title="canon test")
        self.pid = created["document"]["project"]["id"]
        state = self.service.execute(self.pid, "add_chapter", {"title": "chapter one"}, expected_revision=created["revision"])
        self.cid = state["document"]["chapters"][0]["id"]
        state = self.service.execute(self.pid, "add_character", {"name": "Lin"}, expected_revision=state["revision"])
        self.char_id = state["document"]["characters"][0]["id"]
        self.maintenance = CanonMaintenance(self.service)
        self.maintenance.configure(self.pid, {"operation_id": str(uuid4()), "enabled": True,
                                               "expected_revision": self.service.get(self.pid)["revision"]})

    def tearDown(self):
        set_analyzer(None)

    def _changes(self):
        return {"changes": [
            {"kind": "outline", "entity": "book", "field": "main_plot", "before": None,
             "after": "Lin finds the old key", "quote": "old key"},
            {"kind": "character", "entity": self.char_id, "field": "notes", "before": None,
             "after": "at the lighthouse", "quote": "lighthouse"},
            {"kind": "foreshadow", "entity": "key-1", "field": "status", "before": None,
             "after": "planted", "quote": "old key"},
            {"kind": "timeline", "entity": "time-1", "field": "story_time", "before": None,
             "after": "day two", "quote": "day two"},
            {"kind": "worldbuilding", "entity": "world", "field": "fact", "before": None,
             "after": "the lighthouse belongs to the tower guild", "quote": "lighthouse"},
        ]}

    def _save_with(self, output, content):
        set_analyzer(lambda prompt, context: output)
        state = self.service.get(self.pid)
        return self.service.execute(self.pid, "save_chapter", {
            "chapter_id": self.cid, "content": content, "canon_analysis": output,
        }, expected_revision=state["revision"])

    def test_saved_chapter_updates_all_five_canon_kinds_and_audits_quotes(self):
        content = "Lin finds an old key at the lighthouse; time moves to day two."
        self._save_with(self._changes(), content)
        state = self.service.get(self.pid)
        self.assertEqual(state["document"]["chapters"][0]["content"], content)
        self.assertEqual({item["kind"] for item in state["canon_maintenance_facts"]},
                         {"outline", "character", "foreshadow", "timeline", "worldbuilding"})
        self.assertEqual(state["document"]["book_outline"]["main_plot"], "Lin finds the old key")
        self.assertEqual(state["document"]["characters"][0]["notes"], "at the lighthouse")
        self.assertTrue(all(item["quote"] in content for item in state["canon_maintenance_events"]
                            if item["kind"] == "change"))

    def test_non_exact_quote_is_rejected_and_sync_failure_is_visible(self):
        bad = self._changes()
        bad["changes"][0]["quote"] = "not in body"
        self._save_with(bad, "body")
        state = self.service.get(self.pid)
        self.assertEqual(state["canon_maintenance_facts"], [])
        self.assertEqual(state["canon_maintenance_events"][-1]["status"], "failed")
        self.assertEqual(state["canon_maintenance_events"][-1]["chapter_id"], self.cid)

    def test_rollback_chapter_restores_canon_without_changing_body(self):
        content = "Lin finds an old key at the lighthouse; time moves to day two."
        self._save_with(self._changes(), content)
        state = self.service.get(self.pid)
        result = self.maintenance.rollback(self.pid, {
            "operation_id": str(uuid4()), "chapter_id": self.cid,
            "expected_revision": state["revision"],
        })
        self.assertEqual(result["status"], "rolled_back")
        state = self.service.get(self.pid)
        self.assertEqual(state["canon_maintenance_facts"], [])
        self.assertEqual(state["document"]["chapters"][0]["content"], content)

    def test_rollback_can_target_a_checkpoint_without_repeating_chapter_id(self):
        content = "Lin finds an old key at the lighthouse; time moves to day two."
        self._save_with(self._changes(), content)
        state = self.service.get(self.pid)
        checkpoint_id = state["canon_maintenance_checkpoints"][-1]["id"]
        result = self.maintenance.rollback(self.pid, {
            "operation_id": str(uuid4()), "checkpoint_id": checkpoint_id,
            "expected_revision": state["revision"],
        })
        self.assertEqual(result["checkpoint_id"], checkpoint_id)
        self.assertEqual(self.service.get(self.pid)["canon_maintenance_facts"], [])

    def test_disabled_switch_leaves_canon_unchanged(self):
        state = self.service.get(self.pid)
        self.maintenance.configure(self.pid, {"operation_id": str(uuid4()), "enabled": False,
                                               "expected_revision": state["revision"]})
        self._save_with(self._changes(), "body")
        state = self.service.get(self.pid)
        self.assertEqual(state["canon_maintenance_facts"], [])
        self.assertEqual(state["canon_maintenance_events"], [])

    def test_body_is_byte_for_byte_unchanged_after_automatic_maintenance(self):
        content = "prefix😀e\u0301\r\nlighthouse and old key\nending"
        output = {"changes": [{"kind": "timeline", "entity": "t", "field": "event",
                               "before": None, "after": "lighthouse", "quote": "lighthouse and old key"}]}
        self._save_with(output, content)
        self.assertEqual(self.service.get(self.pid)["document"]["chapters"][0]["content"], content)


if __name__ == "__main__":
    unittest.main()
