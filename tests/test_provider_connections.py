"""配置使用临时加密文件，协议检查使用本地虚构供应商。"""
import http.client
from importlib import util, import_module
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(util.find_spec("novel_writer.application.provider_connections"),
                             "缺少可持久化的安全 API 配置和真实连接检查")
        self.module = import_module("novel_writer.application.provider_connections")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "providers.dpapi"
        self.manager = self.module.ProviderConnections(self.path)

    def save(self, **changes):
        fields = {"id": "gg", "base_url": "https://gcli.ggchan.dev/v1",
                  "model_id": "gemini-test", "api_key": "fictional-private-sentinel"}
        fields.update(changes)
        return self.manager.save(**fields)

    @unittest.skipUnless(sys.platform == "win32", "Windows DPAPI")
    def test_credentials_survive_restart_but_never_appear_in_status_or_file(self):
        status = self.save()
        self.assertTrue(status["key_configured"])
        self.assertNotIn("fictional-private-sentinel", json.dumps(status))
        self.assertNotIn(b"fictional-private-sentinel", self.path.read_bytes())
        reopened = self.module.ProviderConnections(self.path)
        self.assertTrue(reopened.status()["gg"]["key_configured"])
        reopened.save(id="gg", base_url="https://gcli.ggchan.dev/v1", model_id="gemini-next", api_key="")
        self.assertTrue(reopened.status()["gg"]["key_configured"])

    def test_rejects_untrusted_urls_and_does_not_write_credentials(self):
        for url in ("http://gcli.ggchan.dev/v1", "https://evil.example/v1",
                    "https://gcli.ggchan.dev@evil.example/v1", "https://gcli.ggchan.dev/v1?key=secret",
                    "https://gcli.ggchan.dev/login", "https://gcli.ggchan.dev:444/v1"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.save(base_url=url)
        self.assertFalse(self.path.exists())

    @unittest.skipUnless(sys.platform == "win32", "Windows DPAPI")
    def test_storage_failure_never_replaces_previous_configuration(self):
        self.save()
        before = self.path.read_bytes()
        from unittest.mock import patch
        with patch.object(self.module, "protect", side_effect=OSError("DPAPI failure")):
            with self.assertRaises(OSError):
                self.save(api_key="replacement-secret")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertTrue(self.manager.status()["gg"]["key_configured"])

    @unittest.skipUnless(sys.platform == "win32", "Windows DPAPI")
    def test_model_list_and_http_failures_use_real_protocol_without_leaking_body(self):
        calls = []
        class Supplier(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                calls.append(self.path)
                valid = self.headers.get("Authorization") == "Bearer fictional-private-sentinel"
                body = {"data": [{"id": "gemini-test"}, {"id": "gemini-other"}]} if valid else {"error": "replacement-secret"}
                data = json.dumps(body).encode()
                self.send_response(200 if valid else 401)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        remote = ThreadingHTTPServer(("127.0.0.1", 0), Supplier)
        thread = threading.Thread(target=remote.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(remote.server_close)
        self.addCleanup(remote.shutdown)
        self.save()
        from unittest.mock import patch
        fixture = f"http://127.0.0.1:{remote.server_address[1]}/v1"
        with patch.dict(self.module.PROVIDERS["gg"], base_url=fixture):
            self.manager.save(id="gg", base_url=fixture, model_id="gemini-test", api_key="")
            result = self.manager.test_connection("gg")
            self.assertTrue(result["ok"])
            self.assertTrue(result["selected_model_available"])
            self.assertEqual(result["models"], ["gemini-test", "gemini-other"])
            self.assertEqual(calls, ["/v1/models"])
            self.manager.save(id="gg", base_url=fixture, model_id="gemini-test", api_key="replacement-secret")
            result = self.manager.test_connection("gg")
            self.assertFalse(result["ok"])
            self.assertEqual(result["http_status"], 401)
            self.assertNotIn("replacement-secret", json.dumps(result))

    @unittest.skipUnless(sys.platform == "win32", "Windows DPAPI")
    def test_http_settings_writes_require_token_and_keep_key_out_of_reads(self):
        from novel_writer.ui.server import create_server
        server = create_server(Path(self.temp.name) / "fictional.sqlite3", port=0, provider_path=self.path)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        def request(method, endpoint, payload=None, token=""):
            conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
            try:
                conn.request(method, endpoint, body=json.dumps(payload) if payload else None,
                             headers={"Content-Type": "application/json", "X-Novel-Token": token})
                response = conn.getresponse()
                return response.status, json.loads(response.read())
            finally:
                conn.close()
        payload = {"id": "gg", "base_url": "https://gcli.ggchan.dev/v1",
                   "model_id": "gemini-test", "api_key": "fictional-private-sentinel"}
        self.assertEqual(request("POST", "/api/providers/save", payload)[0], 403)
        self.assertEqual(request("POST", "/api/providers/save", payload, server.token)[0], 200)
        code, status = request("GET", "/api/settings")
        self.assertEqual(code, 200)
        self.assertTrue(status["connections"]["gg"]["key_configured"])
        self.assertNotIn("fictional-private-sentinel", json.dumps(status))
        self.assertEqual(request("POST", "/api/providers/test", {"id": "gg"})[0], 403)
        self.assertEqual(request("GET", "/api/projects")[1], [])


if __name__ == "__main__":
    unittest.main()
