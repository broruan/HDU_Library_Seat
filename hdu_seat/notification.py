"""SMTP delivery stays separate from booking and uses only the standard library."""
from __future__ import annotations

from datetime import datetime
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
import queue
import smtplib
import ssl
import threading
from typing import Any, Callable

from .client import BEIJING_TZ
from .config import EmailSettings, Settings

SMTP_TIMEOUT = 10


class EmailNotificationError(Exception):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def _delivery_error(exc: Exception) -> EmailNotificationError:
    # SMTP replies can contain credentials or private addresses. Never echo them.
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return EmailNotificationError("邮箱认证失败，请检查登录账号和 SMTP 授权码")
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return EmailNotificationError("收件邮箱被服务器拒绝，请检查收件地址")
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return EmailNotificationError("发件邮箱被服务器拒绝，请检查发件地址")
    if isinstance(exc, ssl.SSLError):
        return EmailNotificationError("SMTP 加密连接失败，请检查服务器、端口与证书")
    if isinstance(exc, smtplib.SMTPNotSupportedError):
        return EmailNotificationError("SMTP 服务器不支持所选加密或认证方式")
    if isinstance(exc, TimeoutError):
        return EmailNotificationError("SMTP 连接或发送超时，请稍后重试", retryable=True)
    if isinstance(exc, smtplib.SMTPResponseException):
        return EmailNotificationError("邮箱服务器拒绝了邮件，请检查配置或稍后重试", retryable=400 <= exc.smtp_code < 500)
    if isinstance(exc, (OSError, smtplib.SMTPServerDisconnected)):
        return EmailNotificationError("无法连接邮箱服务器，请检查网络和 SMTP 设置", retryable=True)
    return EmailNotificationError("邮件发送失败，请检查 SMTP 设置")


def send_email(config: EmailSettings, subject: str, body: str) -> None:
    try:
        config.validate()
    except ValueError as exc:
        raise EmailNotificationError(str(exc)) from None
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.sender or config.username
    message["To"] = config.recipient
    message["Date"] = format_datetime(datetime.now(BEIJING_TZ))
    message["Message-ID"] = make_msgid()
    message.set_content(body)
    smtp = None
    delivery_started = False
    try:
        context = ssl.create_default_context()
        if config.security == "ssl":
            smtp = smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=SMTP_TIMEOUT, context=context)
        else:
            smtp = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=SMTP_TIMEOUT)
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
        smtp.login(config.username, config.password)
        delivery_started = True
        refused = smtp.send_message(message)
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)
    except Exception as exc:
        uncertain_delivery = isinstance(exc, smtplib.SMTPServerDisconnected) or (
            isinstance(exc, OSError) and not isinstance(exc, smtplib.SMTPException)
        )
        if delivery_started and uncertain_delivery:
            raise EmailNotificationError("邮件发送结果未确认，请检查收件箱后再测试发送") from None
        raise _delivery_error(exc) from None
    finally:
        if smtp is not None:
            # DATA acceptance is the delivery result. QUIT/close failure must not
            # turn an accepted message into a retry and duplicate notification.
            try:
                smtp.close()
            except Exception:
                pass


def send_test_email(config: EmailSettings) -> None:
    send_email(config, "杭电图书馆座位助手 · 测试邮件", "邮件通知连接测试已完成。\n\n启用并保存邮件通知后，预约成功会发送座位与使用时段。\n这封邮件没有提交座位预约。")


def booking_email(settings: Settings, attempt: Any) -> tuple[str, str]:
    seat = attempt.seat or {}
    title = str(seat.get("title") or seat.get("name") or seat.get("id") or "未标注")
    area = str(seat.get("area") or (f"{seat['floor']}楼" if seat.get("floor") else "未标注区域"))
    now = datetime.now(BEIJING_TZ)
    try:
        at = datetime.fromisoformat(attempt.at)
        if at.tzinfo is not None:
            now = at.astimezone(BEIJING_TZ)
    except (ValueError, TypeError):
        pass
    date = settings.booking.date or now.date().isoformat()
    start = settings.booking.start_time
    if start:
        window = f"{date} {start} 起 · {settings.booking.duration_hours:g} 小时"
    else:
        window = f"{date} · 立即预约 · {settings.booking.duration_hours:g} 小时"
    # Only selected public seat fields are sent, never the raw upstream response.
    return "杭电图书馆 · 座位预约成功", (
        f"座位预约成功\n\n区域：{area}\n座位：{title}\n使用时段：{window}（北京时间）\n"
        f"使用人数：{settings.booking.num}\n\n请按图书馆规则及时签到，具体预约记录以图书馆系统为准。"
    )


class EmailNotifier:
    """One bounded worker; retries only delivery, deduplicating within a task."""
    def __init__(self, on_status: Callable[[dict[str, Any]], None], *, retry_delays: tuple[float, ...] = (1.0, 3.0)):
        self.on_status = on_status
        self.retry_delays = retry_delays
        self._queue: queue.Queue = queue.Queue(maxsize=16)
        self._keys: set[str] = set()
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._worker: threading.Thread | None = None

    def _status(self, status: str, message: str) -> None:
        try:
            self.on_status({"status": status, "message": message, "at": datetime.now(BEIJING_TZ).isoformat(timespec="seconds")})
        except Exception:
            pass

    def submit(self, config: EmailSettings, subject: str, body: str, key: str) -> bool:
        if not config.enabled:
            return False
        with self._lock:
            if key in self._keys:
                return False
            if self._closed.is_set():
                self._status("failed", "邮件发送服务已停止")
                return False
            self._keys.add(key)
            self._status("pending", "预约成功，邮件已加入发送队列")
            try:
                self._queue.put_nowait((config, subject, body))
            except queue.Full:
                self._status("failed", "邮件发送队列已满，请稍后测试发送")
                return False
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._run, daemon=True, name="seat-email")
                self._worker.start()
            return True

    def _run(self) -> None:
        while not self._closed.is_set():
            try:
                config, subject, body = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                for attempt in range(len(self.retry_delays) + 1):
                    self._status("sending", f"正在发送预约邮件（第 {attempt + 1} 次）")
                    try:
                        send_email(config, subject, body)
                    except EmailNotificationError as exc:
                        if not exc.retryable or attempt == len(self.retry_delays):
                            self._status("failed", str(exc))
                            break
                        self._status("pending", "邮件发送暂未完成，稍后自动重试")
                        if self._closed.wait(self.retry_delays[attempt]):
                            break
                    except Exception:
                        self._status("failed", "邮件发送失败，请检查 SMTP 设置")
                        break
                    else:
                        self._status("sent", "预约邮件已提交至邮箱服务器")
                        break
            finally:
                self._queue.task_done()

    def close(self, *, wait: bool = False) -> None:
        self._closed.set()
        if wait and self._worker is not None:
            self._worker.join(timeout=SMTP_TIMEOUT + 1)
