"""Replay the login protocol without real accounts or reservations.

The signed-in shell uses the public platform's lab-user-data shape. A seat
query can independently fail because its requested booking window is closed.
"""
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import tempfile
import threading
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch
import urllib.error
from urllib.parse import urlsplit

from hdu_seat.android_runtime import AndroidSeatWebServer
from hdu_seat.android_auth import verify_library_session
from hdu_seat.server import default_settings


class Reply(io.BytesIO):
    def __init__(self, body, content_type):
        super().__init__(body.encode())
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.status = 200

    def geturl(self):
        return "https://hdu.huitu.zhishulib.com/"


class AndroidLoginRegressionTests(unittest.TestCase):
    def test_logged_in_shell_is_accepted_when_booking_window_is_closed(self):
        requests = []

        def upstream(opener, request, data=None, timeout=None):
            requests.append(request)
            path = urlsplit(request.full_url).path
            if path == "/":
                return Reply('<html><div id="lab-user-data" style="display:none;">'
                    '{"accessToken":"synthetic-token","objectId":"synthetic-user"}'
                    '</div><div id="react-root"></div></html>', "text/html; charset=utf-8")
            if path == "/Seat/Index/searchSeats":
                return Reply(json.dumps({"CODE": "error", "MESSAGE": "当前时段不可预约", "DATA": {}, "ui_type": "com.Message"}), "application/json")
            self.fail("Login must not call a booking or mutation endpoint")

        with tempfile.TemporaryDirectory() as directory:
            app = AndroidSeatWebServer(Path(directory) / "config.json")
            try:
                app.settings.booking.date = "2000-01-01"
                app.settings.booking.start_time = "08:00"
                with patch("urllib.request.OpenerDirector.open", new=upstream):
                    self.assertTrue(app.set_session("sid=synthetic-valid"),
                        "A signed-in library session must not be rejected because seats cannot be queried now")
                self.assertTrue(app.session()["authenticated"])
                self.assertEqual(len(requests), 1)
                self.assertEqual(requests[0].get_method(), "GET")
                self.assertEqual(requests[0].get_header("Cookie"), "sid=synthetic-valid")
            finally:
                app.close()

    def test_official_bootstrap_id_compatibility_does_not_require_access_token(self):
        for user in ({"id": "legacy-test-user"}, {"objectId": "modern-test-user", "accessToken": ""}):
            with self.subTest(user_keys=list(user)):
                html = '<div id="lab-user-data">' + json.dumps(user) + '</div>'
                with patch("urllib.request.OpenerDirector.open", return_value=Reply(html, "text/html")):
                    result = verify_library_session(default_settings())
                self.assertTrue(result["authenticated"])
                self.assertNotIn("test-user", json.dumps(result))

    def test_anonymous_bootstrap_and_malformed_page_are_distinguished(self):
        for html, expected in (
            ('<div id="lab-user-data">{"accessToken":"","objectId":""}</div>', "login_required"),
            ('<body>Seat Index</body>', "upstream_error"),
            ('<div id="lab-user-data">invalid-json</div>', "upstream_error"),
            ('<div id="lab-user-data">null</div>', "upstream_error"),
        ):
            with self.subTest(expected=expected, html=html):
                with patch("urllib.request.OpenerDirector.open", return_value=Reply(html, "text/html")):
                    result = verify_library_session(default_settings())
                self.assertFalse(result["authenticated"])
                self.assertEqual(result["status"], expected)

    def test_network_failure_is_not_reported_as_wrong_credentials(self):
        with patch("urllib.request.OpenerDirector.open", side_effect=urllib.error.URLError("synthetic private diagnostic")):
            result = verify_library_session(default_settings())
        self.assertEqual(result["status"], "network_error")
        self.assertNotIn("synthetic private diagnostic", result["message"])

    def test_webview_user_agent_survives_save_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            app = AndroidSeatWebServer(path)
            try:
                with patch("hdu_seat.android_runtime.verify_library_session", return_value={"authenticated": True, "status": "authenticated", "message": "ok"}) as probe:
                    self.assertTrue(app.set_session("sid=test-only", "Synthetic Android WebView/1"))
                    self.assertEqual(probe.call_args.args[0].user_agent, "Synthetic Android WebView/1")
                app.save_config({"keywords": ["window"]})
                self.assertEqual(app.settings.user_agent, "Synthetic Android WebView/1")
            finally:
                app.close()
            reopened = AndroidSeatWebServer(path)
            try:
                self.assertEqual(reopened.settings.user_agent, "Synthetic Android WebView/1")
                self.assertTrue(reopened.session()["authenticated"])
            finally:
                reopened.close()

    def test_failed_recheck_keeps_existing_session_and_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            app = AndroidSeatWebServer(Path(directory) / "config.json")
            try:
                with patch("hdu_seat.android_runtime.verify_library_session", return_value={"authenticated": True, "status": "authenticated", "message": "ok"}):
                    app.set_session("sid=old-test-only")
                with patch("hdu_seat.android_runtime.verify_library_session", return_value={"authenticated": False, "status": "network_error", "message": "网络失败"}):
                    result = app.verify_session("sid=new-test-only")
                self.assertEqual(result["status"], "network_error")
                self.assertEqual(app.settings.cookie, "sid=old-test-only")
            finally:
                app.close()

    def test_login_probe_never_forwards_cookie_to_redirect_target(self):
        received = []

        class Upstream(BaseHTTPRequestHandler):
            def do_GET(self):
                received.append(self.path)
                self.send_response(302)
                self.send_header("Location", "/redirect-target")
                self.end_headers()

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            settings = default_settings()
            settings.cookie = "sid=synthetic-private"
            with patch("hdu_seat.android_auth.DEFAULT_BASE_URL", f"http://127.0.0.1:{server.server_port}"):
                result = verify_library_session(settings)
            self.assertEqual(result["status"], "login_required")
            self.assertEqual(received, ["/"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
