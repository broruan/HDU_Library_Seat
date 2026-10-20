"""Replay the native login URL boundary without school credentials or Android.

The official root serves the React shell. An authenticated direct controller
navigation can serve only 'Seat Index', as in the user's failure screenshot.
The Java cookie jar supplies standard URL/path matching, like CookieManager.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from urllib.parse import urlsplit
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "android/app/src/main/java/com/hdu/seathelper/LoginNavigation.java"
HARNESS = r'''
package com.hdu.seathelper;
import java.net.CookieManager;
import java.net.CookiePolicy;
import java.net.URI;
import java.util.List;
import java.util.Map;
public final class LoginNavigationReplay {
    public static void main(String[] args) throws Exception {
        if (args[0].equals("entry")) {
            System.out.println(LoginNavigation.LOGIN_URL);
            return;
        }
        if (args[0].equals("redirect")) {
            String result = LoginNavigation.appUrlForTopLevel(args[1]);
            System.out.println(result == null ? "" : result);
            return;
        }
        CookieManager jar = new CookieManager(null, CookiePolicy.ACCEPT_ALL);
        URI api = URI.create(LoginNavigation.LIBRARY_ORIGIN + "/Seat/Index/searchSeats");
        jar.put(api, Map.of("Set-Cookie", List.of(
            "anonymous=synthetic; Path=/; Secure; HttpOnly",
            "seat_auth=synthetic-authenticated; Path=/Seat; Secure; HttpOnly")));
        String cookies = LoginNavigation.sessionCookies(url -> {
            try {
                return String.join("; ", jar.get(URI.create(url), Map.of()).getOrDefault("Cookie", List.of()));
            } catch (Exception error) { throw new RuntimeException(error); }
        });
        System.out.println(cookies == null ? "" : cookies);
    }
}
'''


class NativeLoginNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        java_home = os.environ.get("JAVA_HOME", "")
        candidates = [Path(java_home) / "bin" / "javac", Path(java_home) / "bin" / "javac.exe",
                      Path("C:/Program Files/JetBrains/PyCharm 2025.2.3/jbr/bin/javac.exe")]
        javac = shutil.which("javac") or next((str(p) for p in candidates if p.is_file()), None)
        if not javac:
            raise unittest.SkipTest("JDK required for native login boundary replay")
        cls.java = str(Path(javac).with_name("java.exe" if str(javac).endswith(".exe") else "java"))
        cls.directory = tempfile.TemporaryDirectory()
        harness = Path(cls.directory.name) / "LoginNavigationReplay.java"
        harness.write_text(HARNESS, encoding="utf-8")
        subprocess.run([javac, "-d", cls.directory.name, str(SOURCE), str(harness)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def native(self, *actions):
        return subprocess.check_output([self.java, "-cp", self.directory.name,
                                        "com.hdu.seathelper.LoginNavigationReplay", *actions], text=True).strip()

    def test_reopening_authenticated_library_loads_app_shell_not_seat_index_stub(self):
        class OfficialPageReplay(BaseHTTPRequestHandler):
            def do_GET(self):
                body = (b'<html><div id="react-root"></div><script src="/rwpublic/js/app.js"></script></html>'
                        if self.path == "/" else b"<html><body>Seat Index</body></html>")
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), OfficialPageReplay)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            destination = urlsplit(self.native("entry"))
            with urlopen(f"http://127.0.0.1:{server.server_port}{destination.path or '/'}", timeout=3) as response:
                body = response.read()
            self.assertIn(b"react-root", body, "Reopening must load the official app shell, not the Seat Index controller stub")
            self.assertTrue(destination.fragment.startswith("!/Seat/Index"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_webview_session_handoff_keeps_cookie_scoped_to_seat_api_path(self):
        self.assertIn("seat_auth=synthetic-authenticated", self.native("cookies"),
                      "The native handoff must include the cookies the authenticated Seat API receives")

    def test_cas_controller_redirect_is_recovered_to_app_without_loops(self):
        for path in ("/Seat/Index", "/Seat/Index/", "/Seat/Index/index"):
            self.assertEqual(self.native("redirect", "https://hdu.huitu.zhishulib.com" + path), self.native("entry"))
        for url in (self.native("entry"), "https://hdu.huitu.zhishulib.com/User/Index/hduCASLogin",
                    "https://evil.example/Seat/Index", "http://hdu.huitu.zhishulib.com/Seat/Index"):
            self.assertEqual(self.native("redirect", url), "")


if __name__ == "__main__":
    unittest.main()
