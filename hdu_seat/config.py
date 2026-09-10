from __future__ import annotations

import json
import os
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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
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
        if not cookie:
            raise ValueError("cookie is required (set it in config or HDU_LIBRARY_COOKIE)")

        values = {
            k: v
            for k, v in data.items()
            if k in cls.__dataclass_fields__ and k not in {"cookie", "space_category", "rule", "booking"}
        }
        return cls(cookie=cookie, space_category=space_category, rule=rule, booking=booking, **values)


def load_settings(path: str | os.PathLike[str]) -> Settings:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"配置文件不存在: {source}")
    with source.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("configuration must be a JSON object")
    return Settings.from_dict(data)
