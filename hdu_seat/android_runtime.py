"""Private loopback runtime for the Android host, sharing the desktop engine.

Only the native login activity supplies sessions. The UI never receives a login
cookie, and its configuration cannot change the upstream to another host.
"""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import secrets
import threading
from typing import Any
from urllib.parse import urlsplit

from .android_auth import verify_library_session
from .client import HDUClientError
from .config import Settings
from .server import DEFAULT_BASE_URL, SeatWebServer, create_http_server


class AndroidSeatWebServer(SeatWebServer):
    def __init__(self, config_path: str | Path):
        self.session_lock = threading.RLock()
        super().__init__(config_path)

    def _load_or_default(self) -> Settings:
        settings = super()._load_or_default()
        # Android credentials may only be sent to the official library origin.
        return replace(settings, base_url=DEFAULT_BASE_URL)

    def _settings_for(self, flat: dict[str, Any], *, validate_email: bool = True) -> Settings:
        with self.lock:
            cookie = self.settings.cookie
            user_agent = self.settings.user_agent
        settings = super()._settings_for(
            {**flat, "base_url": DEFAULT_BASE_URL, "cookie": cookie},
            validate_email=validate_email,
        )
        return replace(settings, user_agent=user_agent)

    def use_config(self, flat: dict[str, Any], *, validate_email: bool = True) -> Settings:
        settings = self._settings_for(flat, validate_email=validate_email)
        if not settings.cookie:
            raise HDUClientError("请先使用学校账号密码登录")
        return settings

    def snapshot(self) -> dict[str, Any]:
        state = super().snapshot()
        state["config"]["cookie"] = ""
        return state

    def save_config(self, flat: dict[str, Any]) -> dict[str, Any]:
        result = super().save_config(flat)
        result["cookie"] = ""
        return result

    def session(self) -> dict[str, Any]:
        with self.lock:
            authenticated = bool(self.settings.cookie)
        return {
            "authenticated": authenticated,
            "message": "已连接图书馆账号，会话失效后请重新登录" if authenticated else "使用学校账号密码登录",
        }

    def set_session(self, cookie: str, user_agent: str = "") -> bool:
        return self.verify_session(cookie, user_agent)["authenticated"]

    def verify_session(self, cookie: str, user_agent: str = "") -> dict[str, Any]:
        with self.session_lock:
            return self._verify_session(cookie, user_agent)

    def _verify_session(self, cookie: str, user_agent: str) -> dict[str, Any]:
        if not isinstance(cookie, str) or not cookie.strip() or any(c in cookie for c in "\r\n"):
            return {"authenticated": False, "status": "login_required", "message": "请先完成学校账号登录"}
        if not isinstance(user_agent, str) or any(c in user_agent for c in "\r\n"):
            return {"authenticated": False, "status": "upstream_error", "message": "登录浏览器信息无效，请重新打开登录页面"}
        with self.lock:
            settings = replace(self.settings, cookie=cookie.strip(), base_url=DEFAULT_BASE_URL,
                               user_agent=user_agent or self.settings.user_agent)
        try:
            result = verify_library_session(settings)
        except Exception:
            return {"authenticated": False, "status": "upstream_error", "message": "登录验证发生异常，请重试"}
        if not result["authenticated"]:
            return result
        try:
            with self.lock:
                settings = replace(self.settings, cookie=cookie.strip(), base_url=DEFAULT_BASE_URL,
                                   user_agent=settings.user_agent)
                self._persist(settings)
                self.settings = settings
        except HDUClientError:
            return {"authenticated": False, "status": "save_error", "message": "登录信息保存失败，请检查存储空间后重试"}
        return result

    def clear_session(self) -> None:
        with self.session_lock:
            self._clear_session()

    def _clear_session(self) -> None:
        self.stop()
        worker = self.worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=self.settings.request_timeout + 1)
        with self.lock:
            settings = replace(self.settings, cookie="", base_url=DEFAULT_BASE_URL)
            self._persist(settings)
            self.settings = settings
            self.available_seats = []
            self.seat_revision += 1
            self.history.clear()
            self.last_result = None


def _private_http_server(app: AndroidSeatWebServer):
    server = create_http_server(app, "127.0.0.1", 0)
    prefix = "/" + secrets.token_urlsafe(32) + "/"
    original_handler = server.RequestHandlerClass
    origin = f"http://127.0.0.1:{server.server_port}"

    class PrivateHandler(original_handler):
        def _authorized_path(self) -> bool:
            parsed = urlsplit(self.path)
            # Reject DNS rebinding and cross-origin write requests, even when a
            # caller somehow learns the unguessable per-process URL prefix.
            if self.headers.get("Host") != f"127.0.0.1:{server.server_port}":
                self._send(403, {"error": "forbidden"})
                return False
            if self.headers.get("Origin") not in (None, origin):
                self._send(403, {"error": "forbidden"})
                return False
            if not parsed.path.startswith(prefix):
                self._send(404, {"error": "not found"})
                return False
            self.path = "/" + parsed.path[len(prefix):]
            return True

        def _send(self, code: int, payload: Any, content_type: str = "application/json; charset=utf-8") -> None:
            # Upstream error messages must never ask Android users to copy a
            # cookie. Keep the established desktop wording on desktop only.
            if isinstance(payload, dict) and isinstance(payload.get("error"), str):
                message = payload["error"]
                if "Cookie" in message or "未登录" in message or "会话失效" in message:
                    payload = {**payload, "error": "登录已失效，请点击账号登录后重试"}
            super()._send(code, payload, content_type)

        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; form-action 'none'; base-uri 'none'")
            super().end_headers()

        def do_GET(self) -> None:
            if not self._authorized_path():
                return
            if self.path == "/api/android/session":
                self._send(200, app.session())
            elif self.path == "/api/config":
                self._send(200, app.snapshot()["config"])
            else:
                super().do_GET()

        def do_POST(self) -> None:
            if self._authorized_path():
                with app.session_lock:
                    super().do_POST()

    server.RequestHandlerClass = PrivateHandler
    return server, origin + prefix


_lifecycle = threading.RLock()
_app: AndroidSeatWebServer | None = None
_server = None
_thread: threading.Thread | None = None
_url: str | None = None


def start(config_path: str) -> str:
    global _app, _server, _thread, _url
    with _lifecycle:
        if _url is not None:
            return _url
        app = AndroidSeatWebServer(Path(config_path))
        try:
            server, url = _private_http_server(app)
        except Exception:
            app.close()
            raise
        thread = threading.Thread(target=server.serve_forever, name="android-dashboard", daemon=True)
        _app, _server, _thread, _url = app, server, thread, url
        thread.start()
        return url


def set_session(cookie: str, user_agent: str = "") -> bool:
    with _lifecycle:
        return _app.set_session(cookie, user_agent) if _app is not None else False


def verify_session_json(cookie: str, user_agent: str = "") -> str:
    with _lifecycle:
        result = _app.verify_session(cookie, user_agent) if _app is not None else {
            "authenticated": False, "status": "upstream_error", "message": "本地服务尚未启动，请返回应用后重试"}
        return json.dumps(result, ensure_ascii=False)


def clear_session() -> None:
    with _lifecycle:
        if _app is not None:
            _app.clear_session()


def status_json() -> str:
    with _lifecycle:
        if _app is None:
            return json.dumps({"running": False, "waiting": False, "last_result": None})
        snapshot = _app.snapshot()
        return json.dumps({key: snapshot[key] for key in ("running", "waiting", "scheduled_for", "last_result")}, ensure_ascii=False)


snapshot_json = status_json


def stop() -> None:
    global _app, _server, _thread, _url
    with _lifecycle:
        if _app is not None:
            _app.close()
        if _server is not None:
            _server.shutdown()
            _server.server_close()
        if _thread is not None:
            _thread.join(timeout=2)
        _app, _server, _thread, _url = None, None, None, None
