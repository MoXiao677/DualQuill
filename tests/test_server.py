"""通过真实本地 HTTP 入口验证页面、保存、冲突和请求边界。"""

import http.client
from importlib import import_module, util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(util.find_spec("novel_writer.ui.server"), "可运行的本地界面入口尚未实现")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.server = import_module("novel_writer.ui.server").create_server(Path(self.temp.name) / "novels.sqlite3", port=0)
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.port = self.server.server_address[1]
        _, data = self.request("GET", "/api/session")
        self.token = data["token"]

    def stop_server(self):
        self.server.shutdown()
        self.thread.join(timeout=3)
        self.server.server_close()

    def request(self, method, path, payload=None, *, token=True, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        actual = {"Content-Type": "application/json"}
        if token and hasattr(self, "token"):
            actual["X-Novel-Token"] = self.token
        actual.update(headers or {})
        try:
            connection.request(method, path, body=None if payload is None else json.dumps(payload).encode(), headers=actual)
            response = connection.getresponse()
            body = response.read()
            return response.status, json.loads(body) if "application/json" in response.getheader("Content-Type", "") else body.decode()
        finally:
            connection.close()

    def create(self):
        status, state = self.request("POST", "/api/projects", {"title": "接口测试小说"})
        self.assertEqual(status, 201)
        return state

    def test_homepage_and_static_assets_are_served(self):
        status, page = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("DualQuill", page)
        self.assertIn("app.js", page)
        self.assertEqual(self.request("GET", "/app.js")[0], 200)
        self.assertEqual(self.request("GET", "/style.css")[0], 200)

    def test_ui_modules_use_explicit_static_whitelist(self):
        for asset in ("api.js", "state.js", "layout.js", "views.js"):
            self.assertEqual(self.request("GET", "/" + asset)[0], 200)
        for path in ("/server.py", "/../server.py", "/static/../server.py", "/unknown.js"):
            self.assertEqual(self.request("GET", path)[0], 404)

    def test_create_then_read_from_new_server_survives_restart(self):
        state = self.create()
        project_id = state["document"]["project"]["id"]
        status, saved = self.request("POST", f"/api/projects/{project_id}/actions",
                                     {"action": "save_worldbuilding", "fields": {"content": "重启不丢失"}, "expected_revision": 1})
        self.assertEqual(status, 200)
        reopened = import_module("novel_writer.storage.sqlite_repository").SQLiteRepository(self.server.database_path)
        self.assertEqual(reopened.get(project_id), saved)
        self.assertEqual(self.request("GET", f"/api/projects/{project_id}")[1]["worldbuilding"], "重启不丢失")

    def test_write_without_session_token_is_rejected(self):
        self.assertEqual(self.request("POST", "/api/projects", {"title": "被阻止"}, token=False)[0], 403)
        self.assertEqual(self.request("GET", "/api/projects")[1], [])

    def test_foreign_origin_cannot_write_even_with_token(self):
        self.assertEqual(self.request("POST", "/api/projects", {"title": "被阻止"}, headers={"Origin": "https://foreign.example"})[0], 403)

    def test_unknown_host_cannot_read_private_projects(self):
        self.assertEqual(self.request("GET", "/api/projects", headers={"Host": "foreign.example"})[0], 403)

    def test_conflict_returns_409_and_keeps_latest_content(self):
        state = self.create()
        path = f"/api/projects/{state['document']['project']['id']}/actions"
        payload = {"action": "save_worldbuilding", "fields": {"content": "新版"}, "expected_revision": 1}
        self.assertEqual(self.request("POST", path, payload)[0], 200)
        payload["fields"]["content"] = "旧版"
        self.assertEqual(self.request("POST", path, payload)[0], 409)
        self.assertEqual(self.request("GET", path.removesuffix("/actions"))[1]["worldbuilding"], "新版")

    def test_validation_error_preserves_database(self):
        status, error = self.request("POST", "/api/projects", {"title": ""})
        self.assertEqual(status, 422)
        self.assertIn("不能为空", error["error"])
        self.assertEqual(self.request("GET", "/api/projects")[1], [])

    def test_model_endpoint_reports_disabled_instead_of_fake_success(self):
        state = self.create()
        path = f"/api/projects/{state['document']['project']['id']}/actions"
        status, body = self.request("POST", path, {"action": "generate_body", "fields": {}, "expected_revision": 1})
        self.assertEqual(status, 422)
        self.assertIn("未启用", body["error"])

    def test_export_contains_all_saved_data(self):
        state = self.create()
        path = f"/api/projects/{state['document']['project']['id']}/export"
        status, export = self.request("GET", path)
        self.assertEqual(status, 200)
        self.assertEqual(export, state)

    def test_missing_project_returns_404(self):
        self.assertEqual(self.request("GET", "/api/projects/unknown-project")[0], 404)

    def test_skill_import_is_readable_after_persistent_save(self):
        original = "---\nname: 写作示例\ndescription: 测试导入\n---\n# 指南\n保留原文。"
        status, skill = self.request("POST", "/api/skills/import", {"files": [{"path": "SKILL.md", "content": original}]})
        self.assertEqual(status, 201)
        status, retrieved = self.request("GET", f"/api/skills/{skill['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(retrieved["files"][0]["content"], original)
        self.assertNotIn("files", self.request("GET", "/api/skills")[1][0])

    def test_skill_import_requires_session_token(self):
        self.assertEqual(self.request("POST", "/api/skills/import", {"files": []}, token=False)[0], 403)

    def test_script_cannot_be_imported_as_skill(self):
        status, _ = self.request("POST", "/api/skills/import", {"files": [{"path": "run.py", "content": "print('no execution')"}]})
        self.assertEqual(status, 422)
        self.assertEqual(self.request("GET", "/api/skills")[1], [])

    def test_in_app_guide_is_accessible_without_a_novel(self):
        status, guide = self.request("GET", "/guide.html")
        self.assertEqual(status, 200)
        self.assertIn("开始写作", guide)
        self.assertIn("完全手动", guide)
        self.assertIn("逐次确认", guide)
        self.assertNotIn('\ufffd',guide)


if __name__ == "__main__":
    unittest.main()
