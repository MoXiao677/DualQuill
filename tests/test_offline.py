"""离线维护不读取凭据，HTTP 与启动入口都拒绝供应商操作。"""
import http.client
import inspect
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from novel_writer.application import provider_connections as providers, settings
from novel_writer.ui.server import create_server


class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "providers.dpapi"
        self.path.write_bytes(b"fictional-unread-credential-store")

    def manager(self):
        self.assertIn("offline", inspect.signature(providers.ProviderConnections).parameters,
                      "凭据管理器缺少离线维护边界")
        return providers.ProviderConnections(self.path, offline=True)

    def test_offline_status_reports_unknown_credentials_without_loading_them(self):
        manager = self.manager()
        with patch.object(manager, "_load", side_effect=AssertionError("禁止读取凭据")):
            status = manager.status()
        self.assertEqual(set(status), set(providers.PROVIDERS))
        for identifier, item in status.items():
            self.assertEqual(item["id"], identifier)
            self.assertIsNone(item["key_configured"])
            self.assertFalse(item["credential_access_enabled"])
            self.assertEqual(item["model_id"], "")
            self.assertIsNone(item["last_test"])

    def test_offline_actions_reject_before_read_write_or_network_access(self):
        manager = self.manager()
        before = self.path.read_bytes()
        with patch.object(manager, "_load", side_effect=AssertionError("禁止读取")), \
             patch.object(manager, "_write", side_effect=AssertionError("禁止写入")), \
             patch.object(providers, "build_opener", side_effect=AssertionError("禁止外发")):
            with self.assertRaisesRegex(ValueError, "离线维护"):
                manager.save(id="gg", base_url=providers.PROVIDERS["gg"]["base_url"],
                             model_id="fictional", api_key="fictional")
            with self.assertRaisesRegex(ValueError, "离线维护"):
                manager.test_connection("gg")
        self.assertEqual(self.path.read_bytes(), before)

    def test_offline_http_contract_and_backend_rejection(self):
        self.assertIn("offline", inspect.signature(create_server).parameters,
                      "HTTP 入口缺少离线维护选项")
        server = create_server(Path(self.temp.name) / "fictional.sqlite3", port=0,
                               provider_path=self.path, offline=True)
        threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def request(method, endpoint, payload=None):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
            try:
                connection.request(method, endpoint, body=json.dumps(payload) if payload else None,
                                   headers={"Content-Type": "application/json", "X-Novel-Token": server.token})
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally:
                connection.close()

        with patch.object(server.providers, "_load", side_effect=AssertionError("禁止读取凭据")), \
             patch.object(settings, "safe_status", side_effect=AssertionError("禁止读取环境密钥")), \
             patch.object(providers, "build_opener", side_effect=AssertionError("禁止外发")):
            code, result = request("GET", "/api/settings")
            self.assertEqual(code, 200)
            self.assertTrue(result["offline_mode"])
            self.assertFalse(result["connection_checks_enabled"])
            self.assertFalse(result["model_calls_enabled"])
            self.assertEqual(set(result["connections"]), set(providers.PROVIDERS))
            self.assertIsNone(result["providers"]["gemini"]["key_configured"])
            self.assertEqual(Path(result["database_path"]), server.database_path)
            for endpoint, payload in (
                ("/api/providers/save", {"id": "gg", "base_url": providers.PROVIDERS["gg"]["base_url"],
                                         "model_id": "fictional", "api_key": "fictional"}),
                ("/api/providers/test", {"id": "gg"}),
            ):
                code, error = request("POST", endpoint, payload)
                self.assertEqual(code, 422)
                self.assertIn("离线维护", error["error"])
        self.assertEqual(self.path.read_bytes(), b"fictional-unread-credential-store")

    def test_offline_launcher_uses_requested_database_without_reading_store(self):
        database = Path(self.temp.name) / "fictional.sqlite3"
        process = subprocess.Popen(
            [sys.executable, "-B", "-X", "utf8", "-u", str(ROOT / "run.py"), "--no-browser",
             "--port", "0", "--database", str(database), "--offline"],
            cwd=self.temp.name, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
            env={**os.environ, "NOVEL_WRITER_PROVIDER_CONFIG": str(self.path)})
        lines = queue.Queue()
        def collect():
            for line in process.stdout:
                if line.startswith("http://127.0.0.1:"):
                    lines.put(line.strip())
                    return
            lines.put(None)
        reader = threading.Thread(target=collect, daemon=True)
        reader.start()
        try:
            url = lines.get(timeout=10)
            self.assertIsNotNone(url, "--offline 启动入口没有提供本机地址")
            connection = http.client.HTTPConnection("127.0.0.1", urlsplit(url).port, timeout=5)
            try:
                connection.request("GET", "/api/settings")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                result = json.loads(response.read())
                self.assertTrue(result["offline_mode"])
                self.assertEqual(Path(result["database_path"]), database)
                self.assertIsNone(result["connections"]["gg"]["key_configured"])
            finally:
                connection.close()
        finally:
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=10)
            reader.join(timeout=2)
        self.assertEqual(self.path.read_bytes(), b"fictional-unread-credential-store")


if __name__ == "__main__":
    unittest.main()
