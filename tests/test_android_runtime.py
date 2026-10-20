import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from hdu_seat import android_runtime as runtime
from hdu_seat.client import HDUClientError
from hdu_seat.server import DEFAULT_BASE_URL


class AndroidRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "config.json"
        self.app = runtime.AndroidSeatWebServer(self.path)
        self.server, self.url = runtime._private_http_server(self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.app.close()
        if self.app.worker:
            self.app.worker.join(timeout=2)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.directory.cleanup()

    def request(self, path, data=None, headers=None):
        request = urllib.request.Request(
            self.url + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers=headers or {},
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            raw = response.read()
            return json.loads(raw) if "application/json" in response.headers["Content-Type"] else raw

    def login(self):
        with patch.object(runtime.ZhishulibClient, "search", return_value={"userInfo": {"id": "test-only"}}):
            self.assertTrue(self.app.set_session("sid=private-session"))

    def test_anonymous_cookie_cannot_become_authenticated(self):
        with patch.object(runtime.ZhishulibClient, "search", side_effect=HDUClientError("未登录")):
            self.assertFalse(self.app.set_session("sid=anonymous"))
        self.assertFalse(self.request("api/android/session")["authenticated"])
        self.assertFalse(self.path.exists())

    def test_empty_api_response_is_not_proof_of_login(self):
        with patch.object(runtime.ZhishulibClient, "search", return_value={}):
            self.assertFalse(self.app.set_session("sid=anonymous"))
        self.assertFalse(self.app.session()["authenticated"])

    def test_login_uses_current_time_instead_of_an_expired_booking(self):
        self.app.settings.booking.date = "2000-01-01"
        self.app.settings.booking.start_time = "08:00"
        seen = []
        def search(client):
            seen.append(client.settings.booking)
            return {"userInfo": {"id": "test-only"}}
        with patch.object(runtime.ZhishulibClient, "search", search):
            self.assertTrue(self.app.set_session("sid=test-only"))
        self.assertIsNone(seen[0].date)
        self.assertIsNone(seen[0].start_time)
        self.assertEqual(self.app.settings.booking.date, "2000-01-01")

    def test_verified_session_is_persisted_and_never_returned_to_webview(self):
        self.login()
        self.assertTrue(self.request("api/android/session")["authenticated"])
        for endpoint in ("api/config", "api/status"):
            self.assertNotIn("private-session", json.dumps(self.request(endpoint)))
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["cookie"], "sid=private-session")
        loaded = runtime.AndroidSeatWebServer(self.path)
        try:
            self.assertTrue(loaded.session()["authenticated"])
        finally:
            loaded.close()

    def test_webview_cannot_replace_native_session_or_upstream(self):
        self.login()
        saved = self.request("api/config", {"cookie": "stolen", "base_url": "https://evil.example", "keywords": ["window"]})
        self.assertEqual(saved["cookie"], "")
        self.assertEqual(saved["base_url"], DEFAULT_BASE_URL)
        self.assertEqual(self.app.settings.cookie, "sid=private-session")
        self.assertEqual(self.app.settings.rule.keywords, ["window"])

    def test_cookie_cannot_be_supplied_from_http(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("api/seats", {"cookie": "unverified"})
        self.assertEqual(caught.exception.code, 400)
        body = json.loads(caught.exception.read())
        self.assertIn("账号密码登录", body["error"])

    def test_unguessable_prefix_and_same_origin_are_required(self):
        root = self.url.split("/", 3)[:3]
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen("/".join(root) + "/api/config", timeout=3)
        self.assertEqual(caught.exception.code, 404)
        for headers in ({"Origin": "https://evil.example"}, {"Host": "evil.example"}):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.request("api/config", {}, headers)
            self.assertEqual(caught.exception.code, 403)

    def test_html_is_bundled_and_query_parameter_works(self):
        page = self.request("?platform=android")
        self.assertIn(b"<html", page)
        self.assertIn(b"HduAndroid", page)

    def test_logout_cancels_scheduled_task_and_clears_saved_session(self):
        self.login()
        self.request("api/start", {"schedule_at": "2099-01-01T08:00", "seat_ids": ["123"]})
        self.assertTrue(self.request("api/status")["waiting"])
        self.app.clear_session()
        self.assertFalse(self.request("api/status")["running"])
        self.assertFalse(self.request("api/android/session")["authenticated"])
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["cookie"], "")

    def test_empty_control_character_sessions_are_rejected(self):
        for value in ("", " ", "sid=abc\r\nInjected: value", None):
            self.assertFalse(self.app.set_session(value))


class AndroidLifecycleTests(unittest.TestCase):
    def test_native_start_is_idempotent_stop_releases_port(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "config.json")
            try:
                url = runtime.start(path)
                self.assertEqual(runtime.start(path), url)
                self.assertFalse(json.loads(runtime.status_json())["running"])
                runtime.clear_session()
            finally:
                runtime.stop()
            self.assertFalse(runtime.set_session("sid=x"))
            with self.assertRaises(urllib.error.URLError):
                urllib.request.urlopen(url, timeout=1)


if __name__ == "__main__":
    unittest.main()
