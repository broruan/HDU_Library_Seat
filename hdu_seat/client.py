from __future__ import annotations

import base64
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import Settings

# 汇图/知书「lab」平台座位的真实接口路径（与前端 /Seat/Index/* 路由一致）。
SEARCH_PATH = "/Seat/Index/searchSeats"
BOOK_PATH = "/Seat/Index/bookSeats"
LOCK_PATH = "/Seat/Index/lockSeats"
UNLOCK_PATH = "/Seat/Index/unlockSeats"
UNLOCK_ALL_PATH = "/Seat/Index/unlockAllSeats"
BEIJING_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


class HDUClientError(RuntimeError):
    pass


def _dicts(obj: Any):
    """Depth-first iteration over mappings in a JSON-compatible response."""
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _dicts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _dicts(value)


def _component_value(payload: Any, key: str) -> Any:
    """Find a prop embedded in a LAB component tree."""
    for item in _dicts(payload):
        if key in item:
            return item[key]
    return None


def _seat_maps(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract every room's seat map from old and current LAB responses."""
    # Current responses repeat the selected room under ``content`` and contain
    # all rooms under ``allContent``. Restricting the walk avoids duplicates.
    source = payload.get("allContent") or payload
    maps: list[dict[str, Any]] = []
    for item in _dicts(source):
        seat_map = item.get("seatMap")
        if isinstance(seat_map, dict) and isinstance(seat_map.get("POIs"), list):
            maps.append(seat_map)

    if maps:
        return maps

    # Some deployments return a direct seatMap; the currently recommended
    # room is also exposed as data={info, POIs, bestPairSeats}.
    body = payload.get("DATA") if isinstance(payload.get("DATA"), dict) else payload
    direct = body.get("seatMap")
    if isinstance(direct, dict) and isinstance(direct.get("POIs"), list):
        return [direct]
    component_data = payload.get("data")
    if isinstance(component_data, dict) and isinstance(component_data.get("POIs"), list):
        return [component_data]
    if isinstance(body.get("POIs"), list):
        return [body]
    return []


def _flag(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _floor_from_info(info: dict[str, Any]) -> str | None:
    storey = str(info.get("storey") or "").strip()
    if storey:
        return storey
    title = str(info.get("title") or "")
    arabic = re.search(r"(\d{1,2})\s*[楼层]", title)
    if arabic:
        return arabic.group(1)
    chinese = re.search(r"(十[一二]?|[一二三四五六七八九])\s*[楼层]", title)
    if not chinese:
        return None
    values = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12}
    return str(values[chinese.group(1)])


def _flatten(obj: Any, prefix: str = "") -> list[tuple[str, str]]:
    """把嵌套 dict/list 展平成 qs 风格（括号下标）的键值对，例如
    {"data": {"space_category": {"category_id": 591}}} ->
    [("data[space_category][category_id]", "591")]。
    """
    pairs: list[tuple[str, str]] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = f"{prefix}[{key}]" if prefix else str(key)
            pairs.extend(_flatten(value, child))
    elif isinstance(obj, (list, tuple)):
        for index, value in enumerate(obj):
            pairs.extend(_flatten(value, f"{prefix}[{index}]"))
    elif obj is not None:
        pairs.append((prefix, str(obj)))
    return pairs


class ZhishulibClient:
    """按真实 zhishulib 接口实现的客户端，不记录、不输出 Cookie。"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._order: dict[str, Any] | None = None

    # ------------------------------------------------------------------ HTTP
    def _url(self, path: str) -> str:
        return urllib.parse.urljoin(self.settings.base_url.rstrip("/") + "/", path.lstrip("/"))

    def _post(self, path: str, data: dict[str, Any] | None = None, extra_headers: dict[str, str] | None = None) -> Any:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": self.settings.user_agent,
            "Cookie": self.settings.cookie,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
        }
        if extra_headers:
            headers.update(extra_headers)
        body = urllib.parse.urlencode(_flatten(data or {})).encode("utf-8")
        url = self._url(path) + ("&" if "?" in path else "?") + "LAB_JSON=1"
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.settings.request_timeout) as response:
                raw = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            raise HDUClientError(f"HTTP {exc.code}: {raw[:200]}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, OSError) and getattr(reason, "winerror", None) == 10013:
                raise HDUClientError(
                    "无法连接图书馆服务器：Windows 阻止了 Python 的外网连接（WinError 10013）。"
                    "请检查防火墙/杀毒软件的网络权限，或换用允许联网的 Python 环境。"
                ) from exc
            raise HDUClientError(f"网络连接失败：{reason}") from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HDUClientError("upstream returned non-JSON data") from exc
        self._ensure_ok(payload)
        return payload

    @staticmethod
    def _ensure_ok(payload: Any) -> None:
        """把 redirect / 未登录 / 业务错误转成可读异常。"""
        if not isinstance(payload, dict):
            return
        if payload.get("ui_type") == "com.Redirect" or payload.get("href"):
            href = str(payload.get("href", ""))
            if "CASLogin" in href or "login" in href.lower():
                raise HDUClientError("未登录或会话失效：请先在浏览器登录 hdu.huitu.zhishulib.com 并更新 Cookie")
            raise HDUClientError(f"服务端跳转: {href}")
        if payload.get("CODE") is not None and str(payload.get("CODE")) != "ok":
            raise HDUClientError(str(payload.get("MESSAGE") or payload.get("CODE")))

    # -------------------------------------------------------------- 时间计算
    def _begin_duration(self) -> tuple[int, int]:
        booking = self.settings.booking
        duration = int(booking.duration_hours * 3600)
        if booking.start_time:
            day = booking.date or datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")
            # The library service interprets timestamps as Beijing time. Do not
            # rely on the host's local timezone (Windows machines are often
            # configured differently from the user's selected booking zone).
            parsed = datetime.strptime(f"{day} {booking.start_time}", "%Y-%m-%d %H:%M")
            if parsed.minute:
                raise HDUClientError("图书馆预约开始时间仅支持整点，例如 18:00")
            start = parsed.replace(tzinfo=BEIJING_TZ)
            configured_begin = int(start.timestamp())
            configured_end = configured_begin + duration
            now = int(time.time())
            if configured_end <= now:
                raise HDUClientError("预约时段已结束，请选择仍在进行或未来的时段")
            # A scheduled task normally wakes a fraction after the configured
            # booking start. The official web client handles this by querying
            # from the current moment. Keep the original end time so retries
            # remain inside the user-selected booking window.
            if configured_begin <= now:
                return now, configured_end - now
            begin_time = configured_begin
            return begin_time, duration
        return int(time.time()), duration

    # -------------------------------------------------------------- 座位查询
    def search(self) -> dict[str, Any]:
        begin_time, duration = self._begin_duration()
        data = {
            "space_category": {
                "category_id": self.settings.space_category.category_id,
                "content_id": self.settings.space_category.content_id,
            },
            "beginTime": begin_time,
            "duration": duration,
            "num": self.settings.booking.num,
        }
        resp = self._post(SEARCH_PATH, data)
        # New LAB responses embed these values in component props, while old
        # deployments expose them directly under DATA.
        body = resp.get("DATA") if isinstance(resp.get("DATA"), dict) else resp
        order_info = _component_value(body, "orderInfo") or {}
        user_info = _component_value(body, "userInfo") or {}
        maps = _seat_maps(resp)
        self._order = {
            "begin_time": int(order_info.get("beginTime") or begin_time),
            "duration": int(order_info.get("duration") or duration),
            "num": int(order_info.get("num") or self.settings.booking.num),
            "uid": user_info.get("id"),
            "img_code": _flag(_component_value(resp, "IsImgCode")),
        }
        normalized = dict(body)
        normalized["seatMaps"] = maps
        if maps and not isinstance(normalized.get("seatMap"), dict):
            normalized["seatMap"] = maps[0]
        normalized.setdefault("orderInfo", order_info)
        normalized.setdefault("userInfo", user_info)
        return normalized

    def seats(self) -> list[dict[str, Any]]:
        body = self.search()
        maps = body.get("seatMaps") if isinstance(body, dict) else None
        if not isinstance(maps, list):
            seat_map = body.get("seatMap") if isinstance(body, dict) else None
            maps = [seat_map] if isinstance(seat_map, dict) else []
        seats: list[dict[str, Any]] = []
        seen: set[str] = set()
        for seat_map in maps:
            if not isinstance(seat_map, dict) or not isinstance(seat_map.get("POIs"), list):
                continue
            info = seat_map.get("info") if isinstance(seat_map.get("info"), dict) else {}
            for poi in seat_map["POIs"]:
                if not isinstance(poi, dict):
                    continue
                seat = dict(poi)
                identity = str(seat.get("id", seat.get("seatId", seat.get("seat_id", ""))))
                if identity and identity in seen:
                    continue
                if identity:
                    seen.add(identity)
                # Official SeatSelectBlock mapping: raw 0 -> free, 1/4/5 ->
                # occupied, 3 -> closed, and 2 -> recommended/selected.
                seat["available"] = str(poi.get("state")) in {"0", "2"} or _flag(poi.get("recommend"))
                if info:
                    seat.setdefault("area", info.get("title"))
                    floor = _floor_from_info(info)
                    if floor is not None:
                        seat.setdefault("floor", floor)
                seats.append(seat)
        return seats

    # -------------------------------------------------------------- 座位预约
    @staticmethod
    def _api_token(begin_time: int, duration: int, is_recommend: int, uid: Any, seat_id: Any, api_time: int) -> str:
        # 与前端 bookSeats 一致的签名：hex_md5 后 base64。
        canonical = (
            "post&/Seat/Index/bookSeats?LAB_JSON=1"
            "&api_time" + str(api_time)
            + "&beginTime" + str(begin_time)
            + "&duration" + str(duration)
            + "&is_recommend" + str(is_recommend)
            + "&seatBookers[0]" + str(uid)
            + "&seats[0]" + str(seat_id)
        )
        digest = hashlib.md5(canonical.encode("utf-8")).hexdigest()
        return base64.b64encode(digest.encode("ascii")).decode("ascii")

    def reserve(self, seat: dict[str, Any]) -> Any:
        seat_id = seat.get("id", seat.get("seatId", seat.get("seat_id")))
        if seat_id is None:
            raise HDUClientError("selected seat has no id")
        order = self._order or {}
        begin_time = int(order.get("begin_time") or self._begin_duration()[0])
        duration = int(order.get("duration") or self.settings.booking.duration_hours * 3600)
        uid = order.get("uid")
        if uid is None:
            raise HDUClientError("缺少用户 id：请先成功查询一次座位")
        if order.get("img_code"):
            raise HDUClientError("当前时段预约需要图形验证码，暂不支持自动处理")
        api_time = int(time.time())
        token = self._api_token(begin_time, duration, 0, uid, seat_id, api_time)
        data = {
            "beginTime": begin_time,
            "duration": duration,
            "seatBookers": [uid],
            "seats": [seat_id],
            "is_recommend": 0,
            "api_time": api_time,
        }
        resp = self._post(BOOK_PATH, data, extra_headers={"Api-Token": token})
        if isinstance(resp, dict):
            result = resp.get("DATA", {}) if isinstance(resp.get("DATA"), dict) else resp
            if str(result.get("result", "")).lower() not in {"", "success"}:
                raise HDUClientError(str(result.get("msg") or result.get("result") or "预约失败"))
        return resp

    @staticmethod
    def public_seat(seat: dict[str, Any]) -> dict[str, Any]:
        """返回本地监控接口可安全展示的字段。"""
        allowed = {"id", "seatId", "seat_id", "title", "name", "label", "state", "available", "recommend", "x", "y", "area", "floor"}
        return {k: v for k, v in seat.items() if k in allowed}
