from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
import webbrowser
from dataclasses import asdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .client import BEIJING_TZ, HDUClientError, ZhishulibClient
from .config import Booking, EmailSettings, SeatRule, Settings, SpaceCategory, load_settings
from .hunter import Attempt, SeatHunter
from .notification import EmailNotificationError, EmailNotifier, booking_email, send_test_email


def _status_attempt(status: str, message: str) -> Attempt:
    return Attempt(datetime.now().isoformat(timespec="seconds"), status, message)

DEFAULT_BASE_URL = "https://hdu.huitu.zhishulib.com"
WEB_DIR = Path(__file__).resolve().parent / "web"
INDEX_HTML = WEB_DIR / "index.html"
MAX_HISTORY = 200


def default_settings() -> Settings:
    return Settings(
        base_url=DEFAULT_BASE_URL,
        cookie="",
        space_category=SpaceCategory(591, 3),
        rule=SeatRule(),
        booking=Booking(),
    )


def settings_to_dict(s: Settings) -> dict[str, Any]:
    """扁平化配置，方便前端表单直接读写。"""
    return {
        "base_url": s.base_url,
        "cookie": s.cookie,
        "category_id": s.space_category.category_id,
        "content_id": s.space_category.content_id,
        "date": s.booking.date,
        "start_time": s.booking.start_time,
        "duration_hours": s.booking.duration_hours,
        "num": s.booking.num,
        "seat_ids": list(s.rule.seat_ids),
        "keywords": list(s.rule.keywords),
        "preferred_floor": s.rule.preferred_floor,
        "avoid_near_door": s.rule.avoid_near_door,
        "poll_interval": s.poll_interval,
        "max_attempts": s.max_attempts,
        "request_timeout": s.request_timeout,
        "schedule_at": s.schedule_at,
        "email_enabled": s.email.enabled,
        "smtp_host": s.email.smtp_host,
        "smtp_port": s.email.smtp_port,
        "smtp_security": s.email.security,
        "smtp_username": s.email.username,
        "smtp_password": "",
        "smtp_password_set": bool(s.email.password),
        "email_sender": s.email.sender,
        "email_recipient": s.email.recipient,
    }


def dict_to_settings(d: dict[str, Any], existing: Settings | None = None) -> Settings:
    """从前端表单数据构建 Settings；数值字段做容错转换。"""
    def _cookie(value: Any) -> str:
        """兼容误把 ``{\"cookie\": \"...\"}`` 作为字符串保存的旧配置。"""
        if isinstance(value, dict) and isinstance(value.get("cookie"), str):
            value = value["cookie"]
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("{"):
                try:
                    decoded = json.loads(value)
                except json.JSONDecodeError:
                    decoded = None
                if isinstance(decoded, dict) and isinstance(decoded.get("cookie"), str):
                    value = decoded["cookie"]
            return value.strip()
        return str(value or "").strip()

    def _num(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _optional_int(value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _bool(value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "y"}
        return bool(value)

    email_data = asdict(existing.email if existing is not None else EmailSettings())
    email_fields = {"email_enabled": "enabled", "smtp_host": "smtp_host", "smtp_port": "smtp_port", "smtp_security": "security", "smtp_username": "username", "email_sender": "sender", "email_recipient": "recipient"}
    for flat_key, key in email_fields.items():
        if flat_key in d:
            email_data[key] = d[flat_key]
    if _bool(d.get("smtp_password_clear")):
        email_data["password"] = ""
    elif isinstance(d.get("smtp_password"), str) and d["smtp_password"]:
        email_data["password"] = d["smtp_password"]
    email = EmailSettings.from_dict(email_data)
    return Settings(
        base_url=(d.get("base_url") or DEFAULT_BASE_URL).strip(),
        cookie=_cookie(d.get("cookie")),
        space_category=SpaceCategory(
            category_id=_int(d.get("category_id"), 591),
            content_id=_int(d.get("content_id"), 3),
        ),
        booking=Booking(
            date=(d.get("date") or None),
            start_time=(d.get("start_time") or None),
            duration_hours=_num(d.get("duration_hours"), 4.0),
            num=_int(d.get("num"), 1),
        ),
        rule=SeatRule(
            seat_ids=[str(x).strip() for x in (d.get("seat_ids") or []) if str(x).strip()],
            keywords=[str(x).strip() for x in (d.get("keywords") or []) if str(x).strip()],
            preferred_floor=_optional_int(d.get("preferred_floor")),
            avoid_near_door=_bool(d.get("avoid_near_door")),
        ),
        poll_interval=_num(d.get("poll_interval"), 3.0),
        max_attempts=_int(d.get("max_attempts"), 8),
        request_timeout=_num(d.get("request_timeout"), 10.0),
        schedule_at=(str(d.get("schedule_at")).strip() or None) if d.get("schedule_at") else None,
        email=email,
    )


def settings_to_nested(s: Settings) -> dict[str, Any]:
    """写出 config.json 同构的嵌套结构。"""
    return {
        "base_url": s.base_url,
        "cookie": s.cookie,
        "space_category": {
            "category_id": s.space_category.category_id,
            "content_id": s.space_category.content_id,
        },
        "booking": {
            "date": s.booking.date,
            "start_time": s.booking.start_time,
            "duration_hours": s.booking.duration_hours,
            "num": s.booking.num,
        },
        "rule": {
            "seat_ids": list(s.rule.seat_ids),
            "keywords": list(s.rule.keywords),
            "preferred_floor": s.rule.preferred_floor,
            "avoid_near_door": s.rule.avoid_near_door,
        },
        "poll_interval": s.poll_interval,
        "max_attempts": s.max_attempts,
        "request_timeout": s.request_timeout,
        "schedule_at": s.schedule_at,
        "user_agent": s.user_agent,
        "email": asdict(s.email),
    }


def scheduled_start_timestamp(settings: Settings, now: float | None = None) -> float | None:
    """Validate a one-shot scheduled start and return its Unix timestamp."""
    if not settings.schedule_at:
        return None
    try:
        scheduled = datetime.fromisoformat(settings.schedule_at)
    except ValueError as exc:
        raise HDUClientError("定时启动时间格式无效，请重新选择") from exc
    if scheduled.tzinfo is None:
        scheduled = scheduled.replace(tzinfo=BEIJING_TZ)
    else:
        scheduled = scheduled.astimezone(BEIJING_TZ)
    timestamp = scheduled.timestamp()
    current = datetime.now(BEIJING_TZ).timestamp() if now is None else now
    if timestamp <= current:
        raise HDUClientError("定时启动时间已过去，请选择未来时间")
    return timestamp


class SeatWebServer:
    def __init__(self, config_path: str | Path):
        self.config_path = Path(config_path)
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.running = False
        self.waiting = False
        self.scheduled_for: str | None = None
        self.history: list[dict[str, Any]] = []
        self.last_result: dict[str, Any] | None = None
        self.available_seats: list[dict[str, Any]] = []
        self.seat_revision = 0
        self.seat_updated_at: str | None = None
        self.settings = self._load_or_default()
        self.notification: dict[str, Any] = {"status": "idle" if self.settings.email.enabled else "disabled", "message": "等待预约成功" if self.settings.email.enabled else "尚未启用邮件通知", "at": None}
        self.notifier = EmailNotifier(self._set_notification)

    def _load_or_default(self) -> Settings:
        try:
            return load_settings(self.config_path, require_cookie=False)
        except Exception:
            return default_settings()

    # ------------------------------------------------------------------ 状态
    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "running": self.running,
                "waiting": self.waiting,
                "scheduled_for": self.scheduled_for,
                "last_result": self.last_result,
                "history": self.history[-MAX_HISTORY:],
                "config": settings_to_dict(self.settings),
                "seats": self.available_seats,
                "seat_revision": self.seat_revision,
                "seat_updated_at": self.seat_updated_at,
                "notification": dict(self.notification),
            }

    def _append(self, result: Any) -> dict[str, Any]:
        data = asdict(result)
        with self.lock:
            self.history.append(data)
            self.last_result = data
        return data

    # ------------------------------------------------------------------ 动作
    def _persist(self, settings: Settings) -> None:
        temporary: Path | None = None
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.config_path.parent, prefix=f".{self.config_path.name}.", suffix=".tmp", delete=False) as file:
                temporary = Path(file.name)
                json.dump(settings_to_nested(settings), file, ensure_ascii=False, indent=2)
            os.replace(temporary, self.config_path)
        except OSError:
            raise HDUClientError("配置保存失败，请检查文件权限或磁盘空间") from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def _set_notification(self, status: dict[str, Any]) -> None:
        with self.lock:
            self.notification = status

    def _settings_for(self, flat: dict[str, Any], *, validate_email: bool = True) -> Settings:
        with self.lock:
            existing = self.settings
        settings = dict_to_settings(flat, existing)
        if settings.email.enabled and validate_email:
            try:
                settings.email.validate()
            except ValueError as exc:
                raise HDUClientError(str(exc)) from None
        return settings

    def save_config(self, flat: dict[str, Any]) -> dict[str, Any]:
        settings = self._settings_for(flat)
        with self.lock:
            self._persist(settings)
            self.settings = settings
            if self.notification["status"] in {"idle", "disabled"}:
                self.notification = {"status": "idle" if settings.email.enabled else "disabled", "message": "等待预约成功" if settings.email.enabled else "尚未启用邮件通知", "at": None}
        return settings_to_dict(settings)

    def use_config(self, flat: dict[str, Any], *, validate_email: bool = True) -> Settings:
        settings = self._settings_for(flat, validate_email=validate_email)
        if not settings.cookie:
            raise HDUClientError("请先填写 Cookie")
        return settings

    def test_email(self, flat: dict[str, Any]) -> dict[str, Any]:
        settings = self._settings_for(flat, validate_email=False)
        try:
            send_test_email(settings.email)
        except EmailNotificationError as exc:
            status = {"status": "failed", "message": str(exc), "at": datetime.now(BEIJING_TZ).isoformat(timespec="seconds")}
            self._set_notification(status)
            return status
        status = {"status": "sent", "message": "测试邮件已提交至邮箱服务器，请检查收件箱", "at": datetime.now(BEIJING_TZ).isoformat(timespec="seconds")}
        self._set_notification(status)
        return status

    def _handle_result(self, result: Attempt, settings: Settings, task_id: str) -> dict[str, Any]:
        data = self._append(result)
        if result.status == "reserved" and settings.email.enabled:
            try:
                subject, body = booking_email(settings, result)
                self.notifier.submit(settings.email, subject, body, task_id)
            except Exception:
                self._set_notification({"status": "failed", "message": "邮件通知未能提交，预约已成功", "at": datetime.now(BEIJING_TZ).isoformat(timespec="seconds")})
        return data

    def query_seats(self, settings: Settings) -> list[dict[str, Any]]:
        client = ZhishulibClient(settings)
        seats = client.seats()
        self._update_seats(seats)
        return [client.public_seat(s) for s in seats]

    def _update_seats(self, seats: list[dict[str, Any]]) -> None:
        available = [ZhishulibClient.public_seat(seat) for seat in seats if seat.get("available")]
        with self.lock:
            self.available_seats = available
            self.seat_revision += 1
            self.seat_updated_at = datetime.now().isoformat(timespec="seconds")

    def run_once(self, settings: Settings, dry_run: bool) -> dict[str, Any]:
        hunter = SeatHunter(settings, on_seats=self._update_seats)
        result = hunter.run_once(dry_run=dry_run)
        return self._handle_result(result, settings, uuid.uuid4().hex)

    def start(self, flat: dict[str, Any]) -> dict[str, Any]:
        settings = self.use_config(flat)
        scheduled_timestamp = scheduled_start_timestamp(settings)
        with self.lock:
            if self.running:
                raise HDUClientError("抢座任务已经在运行")
            self._persist(settings)
            self.settings = settings
            self.running = True
            self.waiting = scheduled_timestamp is not None
            self.scheduled_for = settings.schedule_at if scheduled_timestamp is not None else None
        self.stop_event.clear()
        self.worker = threading.Thread(target=self._run_loop, args=(settings, scheduled_timestamp), daemon=True)
        self.worker.start()
        return {
            "running": True,
            "waiting": scheduled_timestamp is not None,
            "scheduled_for": self.scheduled_for,
        }

    def _run_loop(self, settings: Settings, scheduled_timestamp: float | None = None) -> None:
        task_id = uuid.uuid4().hex
        try:
            if scheduled_timestamp is not None:
                # Wait in bounded chunks so very distant schedules do not
                # overflow the Windows wait API and clock changes are noticed.
                while True:
                    delay = scheduled_timestamp - datetime.now(BEIJING_TZ).timestamp()
                    if delay <= 0:
                        break
                    if self.stop_event.wait(min(delay, 60.0)):
                        self._append(_status_attempt("stopped", "已取消定时抢座"))
                        return
                with self.lock:
                    self.waiting = False
            attempt = 0
            while True:
                if self.stop_event.is_set():
                    self._append(_status_attempt("stopped", "手动停止"))
                    break
                # Web saves replace self.settings atomically. Re-read them on
                # every attempt so a changed seat/time/rule takes effect for
                # an already waiting or running task.
                with self.lock:
                    current_settings = self.settings
                if attempt >= current_settings.max_attempts:
                    self._append(_status_attempt("stopped", "已达到最大尝试次数"))
                    break
                attempt += 1
                hunter = SeatHunter(current_settings, on_seats=self._update_seats, should_stop=self.stop_event.is_set)
                result = hunter.run_once(dry_run=False)
                self._handle_result(result, current_settings, task_id)
                if result.status in {"reserved", "stopped"}:
                    break
                self.stop_event.wait(current_settings.poll_interval)
        finally:
            with self.lock:
                self.running = False
                self.waiting = False
                self.scheduled_for = None

    def stop(self) -> None:
        self.stop_event.set()

    def close(self) -> None:
        self.stop()
        self.notifier.close()


def create_http_server(app: SeatWebServer, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, payload: Any, content_type: str = "application/json; charset=utf-8") -> None:
            if isinstance(payload, (dict, list)):
                raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            else:
                raw = payload if isinstance(payload, bytes) else str(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            raw = self.rfile.read(length)
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                return {}
            return data if isinstance(data, dict) else {}

        def _serve_index(self) -> None:
            if INDEX_HTML.exists():
                self._send(200, INDEX_HTML.read_bytes(), "text/html; charset=utf-8")
            else:
                self._send(200, "<h1>web/index.html 缺失</h1>", "text/html; charset=utf-8")

        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                self._serve_index()
            elif self.path == "/api/config":
                self._send(200, settings_to_dict(app.settings))
            elif self.path == "/api/status":
                self._send(200, app.snapshot())
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self) -> None:
            try:
                body = self._body()
                if self.path == "/api/config":
                    self._send(200, app.save_config(body))
                elif self.path == "/api/email/test":
                    result = app.test_email(body)
                    if result["status"] == "failed":
                        self._send(400, {**result, "error": result["message"]})
                    else:
                        self._send(200, result)
                elif self.path == "/api/seats":
                    seats = app.query_seats(app.use_config(body, validate_email=False))
                    self._send(200, {"seats": seats})
                elif self.path == "/api/run":
                    settings = app.use_config(body.get("config") or body)
                    self._send(200, app.run_once(settings, dry_run=bool(body.get("dry_run"))))
                elif self.path == "/api/start":
                    self._send(200, app.start(body))
                elif self.path == "/api/stop":
                    app.stop()
                    self._send(200, {"running": False})
                else:
                    self._send(404, {"error": "not found"})
            except HDUClientError as exc:
                self._send(400, {"error": str(exc)})
            except ValueError:
                self._send(400, {"error": "请求配置格式无效，请检查输入"})
            except Exception:  # noqa: BLE001 - Do not expose credential-bearing diagnostics.
                self._send(500, {"error": "操作失败，请检查配置后重试"})

        def log_message(self, *_: Any) -> None:
            return

    return ThreadingHTTPServer((host, port), Handler)


def serve(config_path: str | Path, host: str = "127.0.0.1", port: int = 8765, *, open_browser: bool = False) -> None:
    app = SeatWebServer(config_path)
    server = create_http_server(app, host, port)
    url = f"http://{host}:{server.server_port}"
    print(f"抢座面板已启动: {url}", flush=True)
    try:
        if open_browser:
            webbrowser.open(url)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.close()
        server.server_close()
