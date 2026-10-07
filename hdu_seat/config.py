from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SpaceCategory:
    """标识要抢座的区域/房间，与前端 URL 的 space_category 参数一一对应。

    例如 https://hdu.huitu.zhishulib.com/#!/Seat/Index/searchSeats
        ?space_category[category_id]=591&space_category[content_id]=3
    中的 category_id=591、content_id=3。
    """

    category_id: int | str
    content_id: int | str


@dataclass
class SeatRule:
    """座位筛选规则。真实系统按 POI 返回座位，字段为 id/title/state。"""

    seat_ids: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    preferred_floor: int | None = None
    avoid_near_door: bool = False


@dataclass
class Booking:
    """预约时间设置。

    date / start_time 都为空时表示「立即预约」（每次轮询都按当前时间计算 beginTime）。
    指定 start_time 时按当天该时刻计算；指定 date 则按该日期。
    duration_hours 为预约时长（小时）。
    """

    date: str | None = None  # "YYYY-MM-DD"
    start_time: str | None = None  # "HH:MM"
    duration_hours: float = 4.0
    num: int = 1


@dataclass
class EmailSettings:
    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 465
    security: str = "ssl"
    username: str = ""
    password: str = field(default="", repr=False)
    sender: str = ""
    recipient: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "EmailSettings":
        if data is None:
            return cls()
        if not isinstance(data, dict):
            raise ValueError("邮件配置必须是对象")
        values = {key: value for key, value in data.items() if key in cls.__dataclass_fields__}
        enabled = values.get("enabled", False)
        values["enabled"] = enabled.strip().lower() in {"1", "true", "yes", "on"} if isinstance(enabled, str) else bool(enabled)
        try:
            port = values.get("smtp_port", 465)
            values["smtp_port"] = int(str(port)) if not isinstance(port, bool) else 0
        except (ValueError, TypeError):
            values["smtp_port"] = 0
        for key in ("smtp_host", "security", "username", "sender", "recipient"):
            value = values.get(key, getattr(cls(), key))
            values[key] = value.strip() if isinstance(value, str) else ""
        password = values.get("password", "")
        values["password"] = password if isinstance(password, str) else ""
        return cls(**values)

    def validate(self) -> None:
        if not self.smtp_host or any(c.isspace() or c in "/\\?#" or ord(c) < 32 for c in self.smtp_host):
            raise ValueError("请填写有效的 SMTP 服务器地址")
        if isinstance(self.smtp_port, bool) or not isinstance(self.smtp_port, int) or not 1 <= self.smtp_port <= 65535:
            raise ValueError("SMTP 端口必须是 1 到 65535 的整数")
        if self.security not in {"ssl", "starttls"}:
            raise ValueError("邮件加密方式必须是 SSL 或 STARTTLS")
        if not self.username or any(c in self.username for c in "\r\n"):
            raise ValueError("请填写 SMTP 登录账号")
        if not self.password:
            raise ValueError("请填写 SMTP 授权码")
        for address, label in ((self.sender or self.username, "发件邮箱"), (self.recipient, "收件邮箱")):
            if not re.fullmatch(r"[^\s@<>;,]+@[^\s@<>;,]+", address) or any(ord(c) < 32 or ord(c) == 127 for c in address):
                raise ValueError(f"请填写有效的{label}，仅支持一个邮箱地址")


@dataclass
class Settings:
    base_url: str
    cookie: str
    space_category: SpaceCategory
    rule: SeatRule = field(default_factory=SeatRule)
    booking: Booking = field(default_factory=Booking)
    poll_interval: float = 3.0
    request_timeout: float = 10.0
    max_attempts: int = 8
    # Optional one-shot time at which polling starts, interpreted in Beijing
    # time when no explicit UTC offset is present (ISO 8601 string).
    schedule_at: str | None = None
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) HDU-Library-Seat/0.2"
    email: EmailSettings = field(default_factory=EmailSettings)

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, require_cookie: bool = True) -> "Settings":
        base_url = data.get("base_url")
        if not base_url:
            raise ValueError("base_url is required")

        sc = data.get("space_category") or {}
        try:
            space_category = SpaceCategory(
                category_id=sc.get("category_id"),
                content_id=sc.get("content_id"),
            )
        except Exception as exc:  # noqa: BLE001 - 统一转成可读错误
            raise ValueError("space_category 需要 category_id 和 content_id") from exc
        if space_category.category_id is None or space_category.content_id is None:
            raise ValueError("space_category 需要 category_id 和 content_id")

        rule_data = data.get("rule") or {}
        rule = SeatRule(**{k: v for k, v in rule_data.items() if k in SeatRule.__dataclass_fields__})

        booking_data = data.get("booking") or {}
        booking = Booking(**{k: v for k, v in booking_data.items() if k in Booking.__dataclass_fields__})

        cookie = data.get("cookie") or os.environ.get("HDU_LIBRARY_COOKIE", "")
        # 兼容早期 Web 面板把 {"cookie": "..."} 整段 JSON 当作字符串保存的配置。
        if isinstance(cookie, dict) and isinstance(cookie.get("cookie"), str):
            cookie = cookie["cookie"]
        if isinstance(cookie, str):
            cookie = cookie.strip()
            if cookie.startswith("{"):
                try:
                    decoded = json.loads(cookie)
                except json.JSONDecodeError:
                    decoded = None
                if isinstance(decoded, dict) and isinstance(decoded.get("cookie"), str):
                    cookie = decoded["cookie"].strip()
        if not cookie and require_cookie:
            raise ValueError("cookie is required (set it in config or HDU_LIBRARY_COOKIE)")

        email = EmailSettings.from_dict(data.get("email"))
        if email.enabled and require_cookie:
            email.validate()
        values = {
            k: v
            for k, v in data.items()
            if k in cls.__dataclass_fields__ and k not in {"cookie", "space_category", "rule", "booking", "email"}
        }
        return cls(cookie=cookie, space_category=space_category, rule=rule, booking=booking, email=email, **values)


def load_settings(path: str | os.PathLike[str], *, require_cookie: bool = True) -> Settings:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"配置文件不存在: {source}")
    with source.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("configuration must be a JSON object")
    return Settings.from_dict(data, require_cookie=require_cookie)
