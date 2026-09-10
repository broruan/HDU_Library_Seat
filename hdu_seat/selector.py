from __future__ import annotations

from typing import Any

from .config import SeatRule


def _text(seat: dict[str, Any]) -> str:
    return " ".join(
        str(seat.get(k, "")) for k in ("id", "seatId", "seat_id", "title", "name", "label", "area")
    ).lower()


def is_available(seat: dict[str, Any]) -> bool:
    # 客户端已在 POI 上补充了 available（state==2 或 recommend）；这里再做一次兜底判断。
    raw_available = seat.get("available")
    if raw_available is not None:
        return bool(raw_available)
    state = str(seat.get("state", "")).lower()
    if state in {"1", "3", "4", "5", "occupied", "reserved", "unavailable", "已占用", "不可用"}:
        return False
    if bool(seat.get("recommend")):
        return True
    return state in {"0", "2", "free", "available", "空闲", "可用"}


def matches(seat: dict[str, Any], rule: SeatRule) -> bool:
    if not is_available(seat):
        return False
    seat_id = str(seat.get("id", seat.get("seatId", seat.get("seat_id", ""))))
    seat_title = str(seat.get("title", seat.get("name", seat.get("label", ""))))
    if rule.seat_ids:
        requested = {str(x) for x in rule.seat_ids}
        if seat_id not in requested and seat_title not in requested:
            return False
        # A card click stores the globally unique internal seat id. That exact
        # choice must not then be rejected by a stale broad floor preference.
        if seat_id in requested:
            return True
    if rule.preferred_floor is not None and "floor" in seat and str(seat.get("floor", "")) != str(rule.preferred_floor):
        return False
    if rule.avoid_near_door and bool(seat.get("nearDoor", seat.get("near_door", False))):
        return False
    haystack = _text(seat)
    return all(str(keyword).lower() in haystack for keyword in rule.keywords)


def choose(seats: list[dict[str, Any]], rule: SeatRule) -> dict[str, Any] | None:
    candidates = [seat for seat in seats if matches(seat, rule)]
    if not candidates:
        return None
    # 稳定排序，避免每次重试跳到不同座位。
    return sorted(candidates, key=lambda x: str(x.get("id", x.get("seatId", x.get("seat_id", "")))))[0]
