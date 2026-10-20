"""Exercise the installed Android APK without credentials or real reservations.

The debug APK exposes WebView debugging solely for this installed-device check.
The release APK is separately installed and checked through Android accessibility.
Requires adb, a running emulator, and websocket-client==1.8.0.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import time
import urllib.request
import xml.etree.ElementTree as ET

import websocket


PACKAGE = "com.hdu.seathelper"
ACTIVITY = PACKAGE + "/.MainActivity"


def adb(*args: str, binary: bool = False):
    return subprocess.check_output(
        ["adb", *args], timeout=40, text=not binary, stderr=subprocess.STDOUT
    )


def wait_for(callback, *, seconds: int = 60):
    deadline = time.monotonic() + seconds
    last_error = None
    while time.monotonic() < deadline:
        try:
            result = callback()
            if result:
                return result
        except (AssertionError, OSError, ValueError, RuntimeError,
                subprocess.SubprocessError, websocket.WebSocketException) as error:
            last_error = error
        time.sleep(0.5)
    raise RuntimeError("Timed out waiting for Android app readiness") from last_error


class DevTools:
    def __init__(self, target: dict):
        self.socket = websocket.create_connection(
            target["webSocketDebuggerUrl"], timeout=30, suppress_origin=True
        )
        self.sequence = 0

    def evaluate(self, expression: str):
        self.sequence += 1
        self.socket.send(json.dumps({
            "id": self.sequence,
            "method": "Runtime.evaluate",
            "params": {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": True,
            },
        }))
        while True:
            message = json.loads(self.socket.recv())
            if message.get("id") != self.sequence:
                continue
            if "error" in message or "exceptionDetails" in message.get("result", {}):
                # Do not print browser state or URL: the path is an API secret.
                raise RuntimeError("Android WebView JavaScript assertion failed")
            return message["result"]["result"].get("value")

    def close(self):
        self.socket.close()


def targets() -> list[dict]:
    pid = adb("shell", "pidof", PACKAGE).strip().split()[0]
    adb("forward", "tcp:9222", "localabstract:webview_devtools_remote_" + pid)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://127.0.0.1:9222/json", timeout=5) as response:
        return json.load(response)


def dashboard() -> DevTools:
    for target in targets():
        if target.get("url", "").startswith("http://127.0.0.1:"):
            browser = DevTools(target)
            if browser.evaluate("document.readyState === 'complete' && Boolean(document.querySelector('#signInBtn'))"):
                return browser
            browser.close()
    raise RuntimeError("Embedded Python dashboard is not ready")


def screenshot(destination: Path):
    destination.write_bytes(adb("exec-out", "screencap", "-p", binary=True))


def dump_ui() -> ET.Element:
    adb("shell", "uiautomator", "dump", "/sdcard/hdu-smoke.xml")
    return ET.fromstring(adb("shell", "cat", "/sdcard/hdu-smoke.xml").strip())


def tap_native_button(text: str):
    root = dump_ui()
    for node in root.iter("node"):
        if node.get("text") == text and node.get("class") == "android.widget.Button":
            numbers = [int(value) for value in re.findall(r"\d+", node.get("bounds", ""))]
            if len(numbers) == 4:
                adb("shell", "input", "tap", str((numbers[0] + numbers[2]) // 2), str((numbers[1] + numbers[3]) // 2))
                return True
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug-apk", required=True, type=Path)
    parser.add_argument("--release-apk", type=Path)
    parser.add_argument("--out", default=Path("artifacts/android-smoke"), type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    checks: list[str] = []

    def passed(message: str):
        checks.append(message)
        print("PASS " + message, flush=True)

    try:
        adb("install", "-r", str(args.debug_apk.resolve()))
        adb("shell", "pm", "grant", PACKAGE, "android.permission.POST_NOTIFICATIONS")
        adb("shell", "am", "start", "-W", "-n", ACTIVITY)
        browser = wait_for(dashboard)
        try:
            result = browser.evaluate("""
                (() => {
                  if (document.documentElement.dataset.platform !== 'android') throw Error('mode');
                  if (getComputedStyle(document.querySelector('.cookie-section')).display !== 'none') throw Error('cookie');
                  if (typeof HduAndroid.signIn !== 'function') throw Error('bridge');
                  if (document.documentElement.scrollWidth > innerWidth + 1) throw Error('overflow');
                  if (!document.body.innerText.includes('账号密码登录')) throw Error('login');
                  for (const id of ['date','start_time','duration_hours','num','seat_ids','keywords','preferred_floor','avoid_near_door','schedule_at','poll_interval','max_attempts','email_enabled','smtp_host','smtp_password','startBtn','stopBtn']) {
                    if (!document.getElementById(id)) throw Error('missing '+id);
                  }
                  return {width:innerWidth, height:innerHeight};
                })()
            """)
            passed(f"APK starts shared dashboard; Android mode, mobile layout and all controls ({result['width']}px)")
            screenshot(args.out / "debug-dashboard.png")

            assert browser.evaluate("""
                (async () => {
                  const base = new URL('./', location.href);
                  const request = async (path, body) => {
                    const response = await fetch(new URL(path, base), body === undefined ? {} : {
                      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)
                    });
                    return {status:response.status, data:await response.json()};
                  };
                  const session = await request('api/android/session');
                  if (session.status !== 200 || session.data.authenticated !== false) throw Error('session');
                  const config = await request('api/config');
                  if (config.status !== 200 || config.data.cookie !== '' || config.data.smtp_password !== '') throw Error('redaction');
                  config.data.duration_hours = 2.5;
                  config.data.keywords = ['android-smoke'];
                  config.data.email_enabled = false;
                  const saved = await request('api/config', config.data);
                  if (saved.status !== 200 || saved.data.duration_hours !== 2.5) throw Error('save');
                  const status = await request('api/status');
                  if (status.status !== 200 || status.data.running || status.data.config.cookie !== '') throw Error('status');
                  const seats = await request('api/seats', config.data);
                  if (seats.status !== 400) throw Error('unauthenticated request');
                  const outside = await fetch(new URL('/api/config', location.origin));
                  if (![403,404].includes(outside.status)) throw Error('unprotected API');
                  return true;
                })()
            """) is True
            passed("Local APIs save configuration, redact credentials and reject unauthenticated seat queries/unprotected paths")
        finally:
            browser.close()

        adb("shell", "am", "force-stop", PACKAGE)
        adb("shell", "am", "start", "-W", "-n", ACTIVITY)
        browser = wait_for(dashboard)
        try:
            assert browser.evaluate("""
                (async () => {
                  const response=await fetch(new URL('api/config',new URL('./',location.href)));
                  const config=await response.json();
                  return config.duration_hours===2.5 && config.keywords[0]==='android-smoke';
                })()
            """) is True
            passed("Saved settings survive process shutdown and restart")
            browser.evaluate("HduAndroid.signIn(); true")
        finally:
            browser.close()

        wait_for(lambda: ".LoginActivity" in adb("shell", "dumpsys", "activity", "activities"))

        def official_login():
            for target in targets():
                url = target.get("url", "")
                if not (url.startswith("https://hdu.huitu.zhishulib.com/") or re.match(r"https://([a-zA-Z0-9-]+\.)*hdu\.edu\.cn(?:/|:|$)", url)):
                    continue
                view = DevTools(target)
                try:
                    assert view.evaluate("typeof window.HduAndroid === 'undefined'") is True
                    return True
                finally:
                    view.close()
            return False

        wait_for(official_login, seconds=45)

        def login_ui_ready():
            root = dump_ui()
            text = ' '.join(node.get('text', '') for node in root.iter('node'))
            return '学校账号登录' in text and '返回' in text and ('完成登录' in text or '重新加载' in text)

        # A DevTools target can exist before Android draws the new activity.
        # Require the actual native toolbar before recording login evidence.
        wait_for(login_ui_ready)
        screenshot(args.out / "official-login.png")
        passed("Account login displays native login toolbar and official HTTPS WebView without Android bridge")
        wait_for(lambda: tap_native_button("返回"))
        browser = wait_for(dashboard)
        browser.close()
        passed("Cancelling official login returns to dashboard")

        if args.release_apk and args.release_apk.is_file():
            adb("uninstall", PACKAGE)
            adb("install", str(args.release_apk.resolve()))
            adb("shell", "pm", "grant", PACKAGE, "android.permission.POST_NOTIFICATIONS")
            adb("shell", "am", "start", "-W", "-n", ACTIVITY)

            def release_ready():
                root = dump_ui()
                text = ' '.join(node.get('text', '') + node.get('content-desc', '') for node in root.iter('node'))
                return '账号密码登录' in text and '预约设置' in text

            wait_for(release_ready)
            screenshot(args.out / "release-dashboard.png")
            passed("Signed release APK installs and displays live dashboard with account login")

        (args.out / "report.json").write_text(json.dumps({"passed": True, "checks": checks}, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        screenshot(args.out / "failure.png")
        # No real account or session is used in this smoke test.
        (args.out / "crash.log").write_text(adb("logcat", "-d", "-s", "AndroidRuntime:E", "python.stderr:E"), encoding="utf-8")
        (args.out / "report.json").write_text(json.dumps({"passed": False, "checks": checks}, ensure_ascii=False, indent=2), encoding="utf-8")
        raise


if __name__ == "__main__":
    main()
